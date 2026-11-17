"""Applying a Compose file safely (Apps decision 4b, owner 16 Nov 2026).

"Save and restart" only restarts the containers a stack already has, so a stack Kib writes cannot
start and an app backup cannot be brought back. Apply turns the file into containers itself, through
Kiboto's Docker access and its guard, without a Docker CLI:

- plan(): the file is read with its .env (never Kiboto's own environment), every service becomes a
  Docker create request, and the result says per service what happens: new, replaced (and why), kept
  as it is, or removed. Keys Kiboto does not apply yet are named and refused, never dropped quietly.
  Host-level access (privileged, host network, risky folders, …) is listed; applying it needs the
  person's confirmation.
- apply(): the old file is kept (save_stack_config writes a .bak), images are pulled before anything
  stops, a service that changes is set aside (stopped and renamed) before its successor starts, and
  only when every started container runs (and is healthy, where it has a health check) are the old
  ones removed. Otherwise everything goes back: new containers removed, old ones renamed back and
  started, the old file restored.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import time
from collections.abc import Callable
from typing import Any

import yaml

from backend.config import logger

HASH_LABEL = "kiboto.compose.hash"
ASIDE_SUFFIX = "-kiboto-previous"

SERVICE_KEYS = {
    "image",
    "container_name",
    "environment",
    "env_file",
    "ports",
    "volumes",
    "restart",
    "command",
    "entrypoint",
    "labels",
    "networks",
    "network_mode",
    "cap_add",
    "cap_drop",
    "devices",
    "privileged",
    "user",
    "working_dir",
    "hostname",
    "depends_on",
    "healthcheck",
    "shm_size",
    "tmpfs",
    "extra_hosts",
    "dns",
    "security_opt",
    "stop_grace_period",
    "mem_limit",
    "cpus",
    "init",
    "tty",
    "stdin_open",
    "group_add",
    "expose",
    "logging",
    "pull_policy",
}
TOP_KEYS = {"services", "volumes", "networks", "name", "version"}
RESTARTS = {"no", "always", "unless-stopped", "on-failure"}
_VAR = re.compile(r"\$\$|\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?])([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


class ComposeError(ValueError):
    """The file cannot be applied; the message says why, in words."""


# ---------------------------------------------------------------- reading the file


def parse_env(text: str | None) -> dict[str, str]:
    """KEY=value lines of a .env file; quotes around a value are taken off."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            out[key] = value
    return out


def interpolate(value: Any, env: dict[str, str]) -> Any:
    """${VAR}, ${VAR:-default}, ${VAR-default}, ${VAR:?error}, $VAR and $$, as Compose does, from the
    stack's .env only."""
    if isinstance(value, dict):
        return {k: interpolate(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, env) for v in value]
    if not isinstance(value, str):
        return value

    def sub(m: re.Match[str]) -> str:
        if m.group(0) == "$$":
            return "$"
        name = m.group(1) or m.group(4)
        op, arg = m.group(2), m.group(3) or ""
        have = name in env
        val = env.get(name, "")
        if op in (":-", "-"):
            return val if (have and (val or op == "-")) else arg
        if op in (":?", "?"):
            if not have or (op == ":?" and not val):
                raise ComposeError(arg or f"{name} is not set in the stack's .env")
            return val
        return val

    return _VAR.sub(sub, value)


def _list_of(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _env_list(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [f"{k}={'' if v is None else v}" for k, v in value.items()]
    return [str(v) for v in value or []]


def _labels(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): "" if v is None else str(v) for k, v in value.items()}
    out = {}
    for item in value or []:
        k, _, v = str(item).partition("=")
        out[k] = v
    return out


def _duration_ns(value: Any) -> int:
    """'30s', '1m30s', '500ms' or a number of seconds, in nanoseconds."""
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return int(value * 1e9)
    total = 0.0
    for num, unit in re.findall(r"([0-9.]+)\s*(ms|us|ns|h|m|s)?", str(value)):
        total += float(num) * {"h": 3600, "m": 60, "s": 1, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "": 1}[unit or "s"]
    return int(total * 1e9)


def _bytes(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    m = re.match(r"^\s*([0-9.]+)\s*([kmgt]?)b?\s*$", str(value or ""), re.I)
    if not m:
        raise ComposeError(f"'{value}' is not a size")
    return int(float(m.group(1)) * 1024 ** "_kmgt".index(m.group(2).lower() or "_"))


def _ports(service: str, value: Any) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
    exposed: dict[str, Any] = {}
    bindings: dict[str, list[dict[str, str]]] = {}
    for item in value or []:
        if isinstance(item, dict):
            target = str(item.get("target") or "")
            proto = str(item.get("protocol") or "tcp")
            published = str(item.get("published") or "")
            host_ip = str(item.get("host_ip") or "")
        else:
            spec, _, proto = str(item).partition("/")
            proto = proto or "tcp"
            parts = spec.rsplit(":", 2) if spec.count(":") >= 2 else spec.split(":")
            host_ip = parts[0] if len(parts) == 3 else ""
            published = parts[-2] if len(parts) >= 2 else ""
            target = parts[-1]
        if not re.match(r"^[0-9]+$", target) or (published and not re.match(r"^[0-9]+$", published)):
            raise ComposeError(f"{service}: the port '{item}' cannot be applied (ranges are not supported yet)")
        key = f"{target}/{proto}"
        exposed[key] = {}
        if published:
            bindings.setdefault(key, []).append({"HostIp": host_ip, "HostPort": published})
    return exposed, bindings


def _volumes(service: str, value: Any, project: str, base: str, named: set[str]) -> tuple[list[str], list[str]]:
    """Binds for host folders and named volumes; returns (binds, volumes this service uses)."""
    binds: list[str] = []
    used: list[str] = []
    for item in value or []:
        if isinstance(item, dict):
            kind = str(item.get("type") or "volume")
            src, dst = str(item.get("source") or ""), str(item.get("target") or "")
            mode = "ro" if item.get("read_only") else "rw"
            if kind not in ("bind", "volume"):
                raise ComposeError(f"{service}: a volume of type '{kind}' cannot be applied yet")
        else:
            parts = str(item).split(":")
            if len(parts) == 1:
                raise ComposeError(f"{service}: an anonymous volume ('{item}') cannot be applied; give it a name")
            src, dst = parts[0], parts[1]
            mode = parts[2] if len(parts) > 2 else "rw"
            kind = "bind" if src.startswith(("/", ".", "~")) else "volume"
        if not dst.startswith("/"):
            raise ComposeError(f"{service}: the volume target '{dst}' must be an absolute path")
        if kind == "bind":
            if src.startswith("~"):
                raise ComposeError(f"{service}: a folder in a home directory ('{src}') cannot be used")
            host = os.path.normpath(src if src.startswith("/") else os.path.join(base, src))
            binds.append(f"{host}:{dst}:{'ro' if 'ro' in mode.split(',') else 'rw'}")
        else:
            if src not in named:
                raise ComposeError(f"{service}: the volume '{src}' is not listed under volumes at the top of the file")
            binds.append(f"{project}_{src}:{dst}:{'ro' if 'ro' in mode.split(',') else 'rw'}")
            used.append(src)
    return binds, used


def _healthcheck(service: str, value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    if value.get("disable"):
        return {"Test": ["NONE"]}
    test = value.get("test")
    if isinstance(test, str):
        test = ["CMD-SHELL", test]
    if not isinstance(test, list) or not test:
        raise ComposeError(f"{service}: the health check has no test")
    return {
        "Test": [str(t) for t in test],
        "Interval": _duration_ns(value.get("interval")),
        "Timeout": _duration_ns(value.get("timeout")),
        "Retries": int(value.get("retries") or 0),
        "StartPeriod": _duration_ns(value.get("start_period")),
    }


def _order(services: dict[str, Any]) -> list[str]:
    """Services in start order: each after what it depends on; a loop is refused."""
    done: list[str] = []
    seen: set[str] = set()

    def visit(name: str, path: tuple[str, ...]) -> None:
        if name in done:
            return
        if name in path:
            raise ComposeError(f"The services depend on each other in a loop: {' → '.join((*path, name))}")
        deps = services[name].get("depends_on") or []
        for dep in deps if isinstance(deps, list) else list(deps):
            if dep not in services:
                raise ComposeError(f"{name} depends on '{dep}', which is not in the file")
            visit(dep, (*path, name))
        if name not in seen:
            seen.add(name)
            done.append(name)

    for name in services:
        visit(name, ())
    return done


def fingerprint(body: dict[str, Any]) -> str:
    """What a container was created from: the same file gives the same fingerprint, so an unchanged
    service is kept as it is."""
    clean = {k: v for k, v in body.items() if k != "Labels"}
    clean["Labels"] = {k: v for k, v in (body.get("Labels") or {}).items() if k != HASH_LABEL}
    return hashlib.sha256(json.dumps(clean, sort_keys=True).encode()).hexdigest()[:16]


def build(compose_yaml: str, env_text: str | None, project: str, base: str) -> dict[str, Any]:
    """The file as Docker create requests: {project, network, volumes, services: [{name, container,
    body, after}]} in start order. Raises ComposeError with every reason it cannot be applied."""
    try:
        doc = yaml.safe_load(compose_yaml)
    except yaml.YAMLError as e:
        raise ComposeError(f"The file is not valid YAML: {e}") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict) or not doc["services"]:
        raise ComposeError("The file has no services.")
    env = parse_env(env_text)
    doc = interpolate(doc, env)
    problems = [f"'{k}' at the top of the file" for k in doc if k not in TOP_KEYS and not str(k).startswith("x-")]
    project = re.sub(r"[^a-z0-9_-]", "", str(doc.get("name") or project).lower()) or "stack"
    named_vols = doc.get("volumes") or {}
    for vname, vdef in named_vols.items():
        if vdef and (vdef.get("driver") not in (None, "local") or vdef.get("external") or vdef.get("driver_opts")):
            problems.append(f"the volume '{vname}' (only plain local volumes are applied)")
    nets = doc.get("networks") or {}
    for nname, ndef in nets.items():
        if ndef and (ndef.get("driver") not in (None, "bridge") or ndef.get("ipam")):
            problems.append(f"the network '{nname}' (only plain bridge networks are applied)")
    services = doc["services"]
    for name, svc in services.items():
        if not isinstance(svc, dict):
            problems.append(f"the service '{name}' is empty")
            continue
        problems += [f"'{k}' in {name}" for k in svc if k not in SERVICE_KEYS and not str(k).startswith("x-")]
        if not svc.get("image"):
            problems.append(f"{name} has no image (building an image is not supported)")
    if problems:
        raise ComposeError("Kiboto cannot apply " + "; ".join(problems) + " yet.")
    default_net = f"{project}_default"
    out = []
    for name in _order(services):
        svc = services[name]
        exposed, bindings = _ports(name, svc.get("ports"))
        for e in _list_of(svc.get("expose")):
            exposed.setdefault(e if "/" in e else f"{e}/tcp", {})
        binds, _used = _volumes(name, svc.get("volumes"), project, base, set(named_vols))
        restart = str(svc.get("restart") or "no").split(":")[0]
        if restart not in RESTARTS:
            raise ComposeError(f"{name}: restart '{restart}' is not one Docker knows")
        env_list = _env_list(svc.get("environment"))
        for f in _list_of(svc.get("env_file")):
            path = os.path.normpath(os.path.join(base, f))
            if not path.startswith(base.rstrip("/") + "/") or not os.path.isfile(path):
                raise ComposeError(f"{name}: the env_file '{f}' must be a file in the stack's folder")
            with open(path, encoding="utf-8") as fh:
                env_list = [f"{k}={v}" for k, v in parse_env(fh.read()).items()] + env_list
        net_mode = svc.get("network_mode")
        host: dict[str, Any] = {
            "Binds": binds,
            "PortBindings": bindings,
            "RestartPolicy": {"Name": restart},
            "NetworkMode": net_mode or default_net,
        }
        optional = {
            "Privileged": bool(svc.get("privileged")) or None,
            "CapAdd": _list_of(svc.get("cap_add")) or None,
            "CapDrop": _list_of(svc.get("cap_drop")) or None,
            "SecurityOpt": _list_of(svc.get("security_opt")) or None,
            "ExtraHosts": _list_of(svc.get("extra_hosts")) or None,
            "Dns": _list_of(svc.get("dns")) or None,
            "GroupAdd": _list_of(svc.get("group_add")) or None,
            "Init": bool(svc.get("init")) or None,
            "ShmSize": _bytes(svc["shm_size"]) if svc.get("shm_size") else None,
            "Memory": _bytes(svc["mem_limit"]) if svc.get("mem_limit") else None,
            "NanoCpus": int(float(svc["cpus"]) * 1e9) if svc.get("cpus") else None,
            "Tmpfs": {str(t).split(":")[0]: (str(t).split(":", 1) + [""])[1] for t in _list_of(svc.get("tmpfs"))}
            or None,
            "Devices": [
                {
                    "PathOnHost": d.split(":")[0],
                    "PathInContainer": (d.split(":") + [d.split(":")[0]])[1],
                    "CgroupPermissions": "rwm",
                }
                for d in _list_of(svc.get("devices"))
            ]
            or None,
        }
        host.update({k: v for k, v in optional.items() if v is not None})
        cname = str(svc.get("container_name") or f"{project}-{name}-1")
        body: dict[str, Any] = {
            "Image": str(svc["image"]),
            "Env": env_list,
            "ExposedPorts": exposed,
            "HostConfig": host,
            "Labels": {
                **_labels(svc.get("labels")),
                "com.docker.compose.project": project,
                "com.docker.compose.service": name,
            },
        }
        if not net_mode:
            body["NetworkingConfig"] = {"EndpointsConfig": {default_net: {"Aliases": [name]}}}
        for key, field in (("hostname", "Hostname"), ("user", "User"), ("working_dir", "WorkingDir")):
            if svc.get(key):
                body[field] = str(svc[key])
        for key, field in (("command", "Cmd"), ("entrypoint", "Entrypoint")):
            if svc.get(key) is not None:
                v = svc[key]
                body[field] = [str(x) for x in v] if isinstance(v, list) else shlex.split(str(v))
        if svc.get("tty"):
            body["Tty"] = True
        if svc.get("stdin_open"):
            body["OpenStdin"] = True
        if svc.get("stop_grace_period"):
            body["StopTimeout"] = int(_duration_ns(svc["stop_grace_period"]) / 1e9)
        hc = _healthcheck(name, svc.get("healthcheck"))
        if hc:
            body["Healthcheck"] = hc
        body["Labels"][HASH_LABEL] = fingerprint(body)
        out.append({"name": name, "container": cname, "body": body, "healthcheck": bool(hc and hc["Test"] != ["NONE"])})
    return {"project": project, "network": default_net, "volumes": list(named_vols), "services": out}


# ---------------------------------------------------------------- what would change


def _why_replaced(current: dict[str, Any], body: dict[str, Any]) -> list[str]:
    """What differs, in words, between a running container and its new definition."""
    why = []
    cfg = current.get("Config") or {}
    hc = current.get("HostConfig") or {}
    if cfg.get("Image") != body["Image"]:
        why.append(f"image {cfg.get('Image')} → {body['Image']}")
    if set(cfg.get("Env") or []) - set(body.get("Env") or []) or (
        set(body.get("Env") or []) - set(cfg.get("Env") or [])
    ):
        why.append("settings (environment)")
    if (hc.get("PortBindings") or {}) != (body["HostConfig"].get("PortBindings") or {}):
        why.append("ports")
    if sorted(hc.get("Binds") or []) != sorted(body["HostConfig"].get("Binds") or []):
        why.append("folders")
    return why or ["its definition changed"]


def plan(
    built: dict[str, Any], current: list[dict[str, Any]], elevated_reasons: Callable[[dict[str, Any]], list[str]]
) -> dict[str, Any]:
    """Per service: new, replace (with why), keep; containers of the stack no longer in the file:
    remove. Host-level access is listed per service."""
    by_service = {}
    for c in current:
        svc = ((c.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.service")
        if svc:
            by_service[svc] = c
    steps = []
    elevated = []
    for s in built["services"]:
        reasons = elevated_reasons(s["body"])
        if reasons:
            elevated.append({"service": s["name"], "reasons": reasons})
        old = by_service.get(s["name"])
        if not old:
            steps.append({"service": s["name"], "action": "new", "image": s["body"]["Image"]})
            continue
        old_hash = ((old.get("Config") or {}).get("Labels") or {}).get(HASH_LABEL)
        if old_hash == s["body"]["Labels"][HASH_LABEL]:
            steps.append({"service": s["name"], "action": "keep", "image": s["body"]["Image"]})
        else:
            steps.append(
                {
                    "service": s["name"],
                    "action": "replace",
                    "image": s["body"]["Image"],
                    "why": _why_replaced(old, s["body"]),
                }
            )
    names = {s["name"] for s in built["services"]}
    for svc, c in by_service.items():
        if svc not in names:
            steps.append({"service": svc, "action": "remove", "image": (c.get("Config") or {}).get("Image")})
    return {"project": built["project"], "steps": steps, "elevated": elevated}


# ---------------------------------------------------------------- applying it


class Docker:
    """The few Docker calls apply needs; tests pass a fake."""

    def __init__(self, request: Callable[..., tuple[int, Any]], pull: Callable[[str], tuple[bool, str]]):
        self.request = request
        self.pull = pull


def _ensure_network(docker: Docker, built: dict[str, Any]) -> None:
    st, _ = docker.request("GET", f"/networks/{built['network']}")
    if st != 200:
        labels = {"com.docker.compose.project": built["project"], "com.docker.compose.network": "default"}
        st, resp = docker.request(
            "POST", "/networks/create", body={"Name": built["network"], "Driver": "bridge", "Labels": labels}
        )
        if st not in (200, 201):
            raise ComposeError(f"The network {built['network']} could not be made: {resp}")
    for v in built["volumes"]:
        name = f"{built['project']}_{v}"
        st, _ = docker.request("GET", f"/volumes/{name}")
        if st != 200:
            st, resp = docker.request(
                "POST",
                "/volumes/create",
                body={
                    "Name": name,
                    "Labels": {"com.docker.compose.project": built["project"], "com.docker.compose.volume": v},
                },
            )
            if st not in (200, 201):
                raise ComposeError(f"The volume {name} could not be made: {resp}")


def _wait_running(docker: Docker, cid: str, healthcheck: bool, wait: Callable[[float], Any], limit: float) -> str:
    """'' once it runs (and is healthy where it has a check), else why not."""
    waited = 0.0
    while True:
        st, info = docker.request("GET", f"/containers/{cid}/json")
        state = (info or {}).get("State") or {} if st == 200 else {}
        if st == 200 and not state.get("Running") and state.get("Status") in ("exited", "dead"):
            return f"stopped (exit code {state.get('ExitCode')})"
        health = (state.get("Health") or {}).get("Status")
        if state.get("Running") and (not healthcheck or health == "healthy"):
            return ""
        if health == "unhealthy":
            return "its health check failed"
        if waited >= limit:
            return "did not become healthy in time" if healthcheck else "did not start in time"
        wait(1.0)
        waited += 1.0


def apply_built(
    built: dict[str, Any],
    current: list[dict[str, Any]],
    docker: Docker,
    elevated_ok: bool,
    progress: Callable[[str, int], Any] = lambda msg, pct: None,
    wait: Callable[[float], Any] = time.sleep,
    elevated_reasons: Callable[[dict[str, Any]], list[str]] = lambda body: [],
    limit: float = 60.0,
) -> dict[str, Any]:
    """Applies a built file; on any failure everything goes back. Returns {ok, steps, error}."""
    the_plan = plan(built, current, elevated_reasons)
    if the_plan["elevated"] and not elevated_ok:
        raise ComposeError("The file asks for host-level access; confirm it first.")
    by_service = {((c.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.service"): c for c in current}
    todo = {s["service"]: s["action"] for s in the_plan["steps"]}
    images = sorted({s["body"]["Image"] for s in built["services"] if todo[s["name"]] in ("new", "replace")})
    for i, image in enumerate(images):
        progress(f"Getting {image}", 5 + int(40 * i / max(len(images), 1)))
        ok, err = docker.pull(image)
        if not ok:
            return {
                "ok": False,
                "steps": the_plan["steps"],
                "error": f"{image} could not be downloaded: {err}. Nothing was changed.",
            }
    _ensure_network(docker, built)
    started: list[tuple[str, str, bool]] = []  # (service, container id, health check)
    aside: list[dict[str, Any]] = []

    def go_back(error: str) -> dict[str, Any]:
        for _svc, cid, _hc in started:
            docker.request("DELETE", f"/containers/{cid}?force=true&v=false")
        for a in reversed(aside):
            docker.request("POST", f"/containers/{a['aside']}/rename?name={a['name']}")
            if a["was_running"]:
                docker.request("POST", f"/containers/{a['name']}/start")
        logger.warning("compose_apply: %s went back: %s", built["project"], error)
        return {"ok": False, "steps": the_plan["steps"], "error": error + " Everything is back as it was."}

    def set_aside(c: dict[str, Any]) -> None:
        name = str(c.get("Name") or "").lstrip("/")
        was_running = bool((c.get("State") or {}).get("Running"))
        if was_running:
            docker.request("POST", f"/containers/{name}/stop?t=10")
        st, resp = docker.request("POST", f"/containers/{name}/rename?name={name}{ASIDE_SUFFIX}")
        if st not in (200, 204):
            if was_running:
                docker.request("POST", f"/containers/{name}/start")
            raise ComposeError(f"{name} could not be set aside: {resp}")
        aside.append({"name": name, "aside": name + ASIDE_SUFFIX, "was_running": was_running})

    n = len(built["services"])
    for i, s in enumerate(built["services"]):
        action = todo[s["name"]]
        if action == "keep":
            continue
        progress(f"Starting {s['name']}", 50 + int(40 * i / max(n, 1)))
        try:
            if action == "replace":
                set_aside(by_service[s["name"]])
        except ComposeError as e:
            return go_back(str(e))
        headers = {"X-Kiboto-Elevated": "1"} if elevated_ok and elevated_reasons(s["body"]) else {}
        st, resp = docker.request("POST", f"/containers/create?name={s['container']}", body=s["body"], headers=headers)
        cid = resp.get("Id") if st == 201 and isinstance(resp, dict) else None
        if not cid:
            return go_back(f"{s['name']} could not be created: {resp}.")
        started.append((s["name"], cid, s["healthcheck"]))
        st, resp = docker.request("POST", f"/containers/{cid}/start")
        if st not in (204, 304):
            return go_back(f"{s['name']} could not be started: {resp}.")
    progress("Checking that everything runs", 92)
    for svc, cid, hc in started:
        why = _wait_running(docker, cid, hc, wait, limit)
        if why:
            return go_back(f"{svc} {why}.")
    for svc, action in todo.items():
        if action == "remove":
            c = by_service[svc]
            name = str(c.get("Name") or "").lstrip("/")
            docker.request("POST", f"/containers/{name}/stop?t=10")
            docker.request("DELETE", f"/containers/{name}?v=false")
    for a in aside:
        docker.request("DELETE", f"/containers/{a['aside']}?v=false")
    progress("Done", 100)
    return {"ok": True, "steps": the_plan["steps"], "error": ""}
