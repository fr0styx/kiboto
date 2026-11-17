"""Apps decision 4b: applying a Compose file safely, with a preview and an automatic go-back."""

import pytest

from backend.services import compose_apply as ca

FILE = """
name: shop
services:
  web:
    image: nginx:${TAG:-1.27}
    ports: ["8080:80", "127.0.0.1:8443:443/tcp", {target: 9000, published: 9001, protocol: udp}]
    environment: {MODE: prod, KEY: "${API_KEY}"}
    volumes: ["./html:/usr/share/nginx/html:ro", "/mnt/user/media:/media", "data:/data"]
    depends_on: [db]
    restart: unless-stopped
    command: nginx -g "daemon off;"
    healthcheck: {test: "curl -f http://localhost/", interval: 30s, retries: 3}
  db:
    image: postgres:16
    environment: ["POSTGRES_PASSWORD=$$secret"]
volumes:
  data: {}
x-note: ignored
"""


def test_env_and_interpolation():
    env = ca.parse_env('# c\nAPI_KEY="abc"\nexport TAG=1.28\nbad line\nX=\n')
    assert env == {"API_KEY": "abc", "TAG": "1.28", "X": ""}
    assert ca.interpolate("${TAG:-1} ${NONE:-d} ${X:-e} ${X-f} $API_KEY $$", env) == "1.28 d e  abc $"
    with pytest.raises(ca.ComposeError):
        ca.interpolate("${NEED:?set NEED}", env)
    with pytest.raises(ca.ComposeError):
        ca.interpolate("${X:?}", env)
    assert ca.interpolate({"a": ["${TAG}", 3]}, env) == {"a": ["1.28", 3]}


def test_the_file_becomes_create_requests(tmp_path):
    built = ca.build(FILE, "API_KEY=k", "ignored", str(tmp_path))
    assert built["project"] == "shop" and built["network"] == "shop_default" and built["volumes"] == ["data"]
    assert [s["name"] for s in built["services"]] == ["db", "web"]  # db first: web depends on it
    web = built["services"][1]
    b = web["body"]
    assert web["container"] == "shop-web-1" and b["Image"] == "nginx:1.27" and web["healthcheck"]
    assert sorted(b["Env"]) == ["KEY=k", "MODE=prod"]
    assert b["HostConfig"]["PortBindings"] == {
        "80/tcp": [{"HostIp": "", "HostPort": "8080"}],
        "443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}],
        "9000/udp": [{"HostIp": "", "HostPort": "9001"}],
    }
    assert b["HostConfig"]["Binds"] == [
        f"{tmp_path}/html:/usr/share/nginx/html:ro",
        "/mnt/user/media:/media:rw",
        "shop_data:/data:rw",
    ]
    assert b["HostConfig"]["RestartPolicy"] == {"Name": "unless-stopped"} and b["Cmd"] == ["nginx", "-g", "daemon off;"]
    assert (
        b["Healthcheck"]["Test"] == ["CMD-SHELL", "curl -f http://localhost/"]
        and b["Healthcheck"]["Interval"] == 30 * 10**9
    )
    assert b["NetworkingConfig"] == {"EndpointsConfig": {"shop_default": {"Aliases": ["web"]}}}
    assert b["Labels"]["com.docker.compose.service"] == "web" and len(b["Labels"][ca.HASH_LABEL]) == 16
    assert built["services"][0]["body"]["Env"] == ["POSTGRES_PASSWORD=$secret"]
    again = ca.build(FILE, "API_KEY=k", "x", str(tmp_path))
    assert again["services"][1]["body"]["Labels"][ca.HASH_LABEL] == b["Labels"][ca.HASH_LABEL]


@pytest.mark.parametrize(
    "text,why",
    [
        ("services: {a: {build: .}}", "'build' in a"),
        ("services: {a: {image: x, deploy: {}}}", "'deploy' in a"),
        ("services: {a: {image: x}}\nsecrets: {}", "'secrets' at the top"),
        ("services: {a: {image: x, volumes: ['/data']}}", "anonymous volume"),
        ("services: {a: {image: x, volumes: ['v:/d']}}", "not listed under volumes"),
        ("services: {a: {image: x, depends_on: [b]}, b: {image: y, depends_on: [a]}}", "loop"),
        ("services: {a: {image: x, depends_on: [zz]}}", "not in the file"),
        ("services: {a: {image: x, ports: ['8000-8010:80']}}", "ranges"),
        ("services: {a: {image: x, restart: sometimes}}", "restart"),
        ("services: {a: {image: x, env_file: ../../etc/passwd}}", "env_file"),
        ("services: {}", "no services"),
        ("services: [", "not valid YAML"),
        ("services: {a: {}}", "no image"),
        ("services: {a: {image: x}}\nvolumes: {v: {driver: nfs}}", "plain local volumes"),
        ("services: {a: {image: x}}\nnetworks: {n: {driver: macvlan}}", "plain bridge networks"),
        ("services: {a: {image: x, volumes: ['~/x:/x']}}", "home directory"),
        ("services: {a: {image: x, volumes: [{type: tmpfs, target: /t}]}}", "type 'tmpfs'"),
        ("services: {a: {image: x, shm_size: lots}}", "not a size"),
        ("services: {a: {image: x, healthcheck: {interval: 5s}}}", "no test"),
    ],
)
def test_what_cannot_be_applied_is_named(tmp_path, text, why):
    with pytest.raises(ca.ComposeError) as e:
        ca.build(text, "", "p", str(tmp_path))
    assert why in str(e.value)


def test_more_keys(tmp_path):
    (tmp_path / "app.env").write_text("FROM_FILE=1\n")
    text = """services:
  a:
    image: x
    env_file: app.env
    environment: [B=2]
    network_mode: host
    privileged: true
    cap_add: [NET_ADMIN]
    devices: ["/dev/dri:/dev/dri"]
    shm_size: 1g
    mem_limit: 512m
    cpus: 1.5
    tmpfs: ["/run:size=1m"]
    user: "1000"
    hostname: h
    working_dir: /w
    entrypoint: [/init]
    tty: true
    stdin_open: true
    stop_grace_period: 1m
    expose: ["9100"]
    healthcheck: {disable: true}
    labels: [team=home]
"""
    b = ca.build(text, "", "p", str(tmp_path))["services"][0]["body"]
    hc = b["HostConfig"]
    assert b["Env"] == ["FROM_FILE=1", "B=2"] and hc["NetworkMode"] == "host" and "NetworkingConfig" not in b
    assert hc["Privileged"] and hc["CapAdd"] == ["NET_ADMIN"] and hc["Devices"][0]["PathOnHost"] == "/dev/dri"
    assert (
        hc["ShmSize"] == 1024**3
        and hc["Memory"] == 512 * 1024**2
        and hc["NanoCpus"] == 1_500_000_000
        and hc["Tmpfs"] == {"/run": "size=1m"}
    )
    assert b["User"] == "1000" and b["Hostname"] == "h" and b["WorkingDir"] == "/w" and b["Entrypoint"] == ["/init"]
    assert b["Tty"] and b["OpenStdin"] and b["StopTimeout"] == 60 and "9100/tcp" in b["ExposedPorts"]
    assert b["Healthcheck"] == {"Test": ["NONE"]} and b["Labels"]["team"] == "home"


def _container(name, service, body=None, running=True, image="nginx:1.26", hashv="old"):
    return {
        "Name": f"/{name}",
        "State": {"Running": running},
        "Config": {"Image": image, "Env": [], "Labels": {"com.docker.compose.service": service, ca.HASH_LABEL: hashv}},
        "HostConfig": {},
    }


def test_plan_says_new_replace_keep_remove(tmp_path):
    built = ca.build(FILE, "API_KEY=k", "shop", str(tmp_path))
    db = built["services"][0]["body"]
    current = [
        _container("shop-web-1", "web"),
        _container("shop-db-1", "db", image="postgres:16", hashv=db["Labels"][ca.HASH_LABEL]),
        _container("shop-old-1", "old"),
        {"Name": "/stray", "Config": {"Labels": {}}},
    ]
    p = ca.plan(built, current, lambda body: ["privileged"] if body["Image"].startswith("nginx") else [])
    steps = {s["service"]: s for s in p["steps"]}
    assert steps["db"]["action"] == "keep" and steps["old"]["action"] == "remove"
    assert steps["web"]["action"] == "replace" and "image nginx:1.26 → nginx:1.27" in steps["web"]["why"]
    assert p["elevated"] == [{"service": "web", "reasons": ["privileged"]}]
    assert ca.plan(built, [], lambda b: [])["steps"][0]["action"] == "new"
    assert ca._why_replaced(
        {"Config": {"Image": "a", "Env": ["X=1"]}, "HostConfig": {"Binds": ["/a:/a"], "PortBindings": {"1/tcp": []}}},
        {"Image": "a", "Env": ["X=1"], "HostConfig": {}},
    ) == ["ports", "folders"]
    assert ca._why_replaced(
        {"Config": {"Image": "a"}, "HostConfig": {}}, {"Image": "a", "Env": [], "HostConfig": {}}
    ) == ["its definition changed"]


class FakeDocker:
    def __init__(self, fail_start=(), fail_create=(), unhealthy=(), pull_ok=True, rename_fails=False, net_exists=False):
        self.calls, self.fail_start, self.fail_create, self.unhealthy = (
            [],
            set(fail_start),
            set(fail_create),
            set(unhealthy),
        )
        self.pull_ok, self.rename_fails, self.net_exists = pull_ok, rename_fails, net_exists
        self.made = {}

    def request(self, method, path, body=None, headers=None):
        self.calls.append((method, path))
        if path.startswith("/networks/") and method == "GET":
            return (200 if self.net_exists else 404), {}
        if path.startswith("/volumes/") and method == "GET":
            return 404, {}
        if path in ("/networks/create", "/volumes/create"):
            return 201, {}
        if path.startswith("/containers/create"):
            name = path.split("name=")[1]
            if name in self.fail_create:
                return 409, {"message": "conflict"}
            cid = f"id-{name}"
            self.made[cid] = name
            return 201, {"Id": cid}
        if path.endswith("/start"):
            cid = path.split("/")[2]
            return (500, {"message": "boom"}) if self.made.get(cid) in self.fail_start else (204, {})
        if "/rename" in path:
            return (500, {"message": "no"}) if self.rename_fails else (204, {})
        if method == "GET" and path.endswith("/json"):
            cid = path.split("/")[2]
            if self.made.get(cid) in self.unhealthy:
                return 200, {"State": {"Running": True, "Health": {"Status": "unhealthy"}}}
            return 200, {"State": {"Running": True, "Health": {"Status": "healthy"}}}
        return 204, {}

    def pull(self, image):
        return (self.pull_ok, "" if self.pull_ok else "denied")


def _run(fake, current, **kw):
    built = ca.build(FILE, "API_KEY=k", "shop", "/mnt/user/appdata/shop")
    return ca.apply_built(
        built, current, ca.Docker(fake.request, fake.pull), kw.pop("elevated_ok", False), wait=lambda s: None, **kw
    )


def test_apply_sets_aside_then_removes_the_old_ones():
    fake = FakeDocker()
    msgs = []
    res = _run(
        fake, [_container("shop-web-1", "web"), _container("shop-gone-1", "gone")], progress=lambda m, p: msgs.append(m)
    )
    assert res["ok"] and res["error"] == ""
    assert ("POST", "/containers/shop-web-1/stop?t=10") in fake.calls
    assert ("POST", f"/containers/shop-web-1/rename?name=shop-web-1{ca.ASIDE_SUFFIX}") in fake.calls
    assert ("DELETE", f"/containers/shop-web-1{ca.ASIDE_SUFFIX}?v=false") in fake.calls
    assert ("DELETE", "/containers/shop-gone-1?v=false") in fake.calls
    assert ("POST", "/networks/create") in fake.calls and ("POST", "/volumes/create") in fake.calls
    assert msgs[-1] == "Done"


@pytest.mark.parametrize(
    "kw", [{"fail_start": {"shop-web-1"}}, {"fail_create": {"shop-web-1"}}, {"unhealthy": {"shop-web-1"}}]
)
def test_any_failure_puts_everything_back(kw):
    fake = FakeDocker(**kw)
    res = _run(fake, [_container("shop-web-1", "web")])
    assert not res["ok"] and "Everything is back as it was." in res["error"]
    assert ("POST", f"/containers/shop-web-1{ca.ASIDE_SUFFIX}/rename?name=shop-web-1") in fake.calls
    assert ("POST", "/containers/shop-web-1/start") in fake.calls
    assert ("DELETE", "/containers/id-shop-db-1?force=true&v=false") in fake.calls  # the new db goes too


def test_a_failed_download_changes_nothing_and_host_access_needs_an_ok():
    fake = FakeDocker(pull_ok=False, net_exists=True)
    res = _run(fake, [])
    assert not res["ok"] and "Nothing was changed." in res["error"] and not [c for c in fake.calls if "create" in c[1]]
    with pytest.raises(ca.ComposeError):
        _run(FakeDocker(), [], elevated_reasons=lambda b: ["privileged"])
    ok = _run(FakeDocker(), [], elevated_ok=True, elevated_reasons=lambda b: ["privileged"])
    assert ok["ok"]


def test_a_container_that_cannot_be_set_aside_stops_the_apply():
    fake = FakeDocker(rename_fails=True)
    res = _run(fake, [_container("shop-web-1", "web")])
    assert not res["ok"] and "could not be set aside" in res["error"]


def test_waiting_for_a_container():
    states = iter([{"Running": False, "Status": "created"}, {"Running": True}])
    req = lambda m, p, **k: (200, {"State": next(states)})  # noqa: E731
    assert ca._wait_running(ca.Docker(req, None), "c", False, lambda s: None, 5) == ""
    req2 = lambda m, p, **k: (200, {"State": {"Running": False, "Status": "exited", "ExitCode": 3}})  # noqa: E731
    assert ca._wait_running(ca.Docker(req2, None), "c", False, lambda s: None, 5) == "stopped (exit code 3)"
    req3 = lambda m, p, **k: (200, {"State": {"Running": True, "Health": {"Status": "starting"}}})  # noqa: E731
    assert ca._wait_running(ca.Docker(req3, None), "c", True, lambda s: None, 2) == "did not become healthy in time"
    req4 = lambda m, p, **k: (404, {})  # noqa: E731
    assert ca._wait_running(ca.Docker(req4, None), "c", False, lambda s: None, 1) == "did not start in time"
