"""SNMP, the power schedule and Dynamic DNS refuse settings with their message key, so the card
says why in the reader's language."""


def _check(client, auth_headers, path, body, key):
    r = client.put(path, json=body, headers=auth_headers)
    answer = r.json()
    assert r.status_code == 400 and answer["error"] == "invalid_settings", answer
    assert answer["text"]["msg_key"] == key, answer


def test_snmp_refusals(client, auth_headers):
    base = {
        "enabled": False,
        "port": 161,
        "user": "monitor",
        "auth_password": None,
        "priv_password": None,
        "contact": "",
        "location": "",
    }
    _check(client, auth_headers, "/api/network/snmp", {**base, "user": "bad name!"}, "srv.snmp_user")
    _check(
        client, auth_headers, "/api/network/snmp", {**base, "auth_password": "short"}, "srv.snmp_authentication_short"
    )
    _check(client, auth_headers, "/api/network/snmp", {**base, "enabled": True}, "srv.snmp_fill_in")


def test_power_schedule_refusals(client, auth_headers):
    base = {"enabled": False, "off_at": "01:00", "wake_at": "07:00", "days": [0]}
    _check(client, auth_headers, "/api/system/power-schedule", {**base, "off_at": "1am"}, "srv.sched_times")
    _check(client, auth_headers, "/api/system/power-schedule", {**base, "wake_at": "01:00"}, "srv.sched_same_times")
    _check(
        client, auth_headers, "/api/system/power-schedule", {**base, "enabled": True, "days": []}, "srv.sched_no_night"
    )


def test_ddns_refusals(client, auth_headers):
    base = {"enabled": False, "provider": "duckdns", "hostname": "", "token": None}
    _check(client, auth_headers, "/api/network/ddns", {**base, "enabled": True}, "srv.ddns_fill_in")
