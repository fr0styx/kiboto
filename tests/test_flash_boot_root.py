"""The file manager offers /boot only where it is Unraid's flash drive: on Kiboto OS /boot is
Debian's kernel and boot loader."""

from backend.api.files import browse


def test_flash_boot_shows_only_where_boot_keeps_unraids_settings(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(browse, "ALLOWED_BROWSE_ROOTS", [*browse.ALLOWED_BROWSE_ROOTS, "/boot"])
    monkeypatch.setattr(browse, "FLASH_CONFIG", str(tmp_path / "no-such-config"))
    assert client.get("/api/fs/roots", headers=auth_headers).json()["system"] == []
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(browse, "FLASH_CONFIG", str(tmp_path / "config"))
    system = client.get("/api/fs/roots", headers=auth_headers).json()["system"]
    assert [s["name"] for s in system] == ["Flash Boot (/boot)"] and system[0]["admin_only"] is True
    monkeypatch.setattr(browse, "ALLOWED_BROWSE_ROOTS", [r for r in browse.ALLOWED_BROWSE_ROOTS if r != "/boot"])
    assert client.get("/api/fs/roots", headers=auth_headers).json()["system"] == []
