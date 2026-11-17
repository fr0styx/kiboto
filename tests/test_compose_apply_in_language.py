"""A Compose apply that goes back says why with a message key, so the Jobs centre shows it in the
reader's language; the English stays in the error."""

from backend.services import compose_apply as ca


def test_each_failure_kind_has_its_key():
    assert ca.why_text("web", "stopped (exit code 3)") == {
        "msg_key": "srv.apply_part_stopped",
        "params": {"part": "web", "code": "3"},
    }
    assert ca.why_text("web", "keeps restarting (exit code 1)")["msg_key"] == "srv.apply_part_restarting"
    assert ca.why_text("web", "its health check failed")["msg_key"] == "srv.apply_part_unhealthy"
    assert ca.why_text("web", "did not start in time")["msg_key"] == "srv.apply_part_slow"
    assert ca.why_text("web", "did not become healthy in time")["params"]["code"] == ""
    other = ca.why_text("web", "{'message': 'port is already allocated'}")
    assert other == {
        "msg_key": "srv.apply_part_failed",
        "params": {"part": "web", "error": "{'message': 'port is already allocated'}"},
    }


def test_a_failed_download_says_so_with_its_key():
    class NoPull:
        def pull(self, image):
            return False, "manifest unknown"

        def request(self, *a, **k):
            raise AssertionError("nothing may change after a failed download")

    built = {
        "project": "shop",
        "services": [{"name": "web", "container": "shop-web-1", "body": {"Image": "nginx:9"}, "healthcheck": False}],
    }
    res = ca.apply_built(built, [], NoPull(), False, wait=lambda s: None)
    assert res["ok"] is False and res["text"]["msg_key"] == "srv.apply_pull_failed"
    assert res["text"]["params"] == {"image": "nginx:9", "error": "manifest unknown"}
