"""The test suite never changes a real machine's accounts, even run as root on a managed host."""

from backend.services import samba_host


def test_the_real_runner_refuses_in_test_mode():
    code, _, why = samba_host._runner(None)(["useradd", "nobody-kb"])
    assert code == 1 and "does not change" in why


def test_a_runner_a_test_gives_or_patches_is_used(monkeypatch):
    seen = []

    def mine(cmd, feed=None, timeout=20):
        seen.append(cmd)
        return 0, "", ""

    assert samba_host._runner(mine) is mine
    monkeypatch.setattr(samba_host, "run", mine)
    assert samba_host._runner(None) is mine
    samba_host.remove("kb-guard")
    assert seen
