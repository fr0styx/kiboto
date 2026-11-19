"""The suite does not depend on this machine's network: a name lookup in a test is an error."""

import socket

import pytest


def test_a_name_lookup_in_a_test_is_refused():
    with pytest.raises(AssertionError, match="looked up .unlisted.example.org. on the network"):
        socket.getaddrinfo("unlisted.example.org", 443)
    with pytest.raises(AssertionError, match="KNOWN_NAMES"):
        socket.getaddrinfo(b"unlisted.example.org", 80)


def test_addresses_and_this_machine_still_resolve():
    assert socket.getaddrinfo("127.0.0.1", 80)[0][4][0] == "127.0.0.1"
    assert socket.getaddrinfo("192.0.2.1", 80, type=socket.SOCK_STREAM)[0][4][0] == "192.0.2.1"
    assert socket.getaddrinfo("localhost", 80)
    assert socket.getaddrinfo(None, 80, flags=socket.AI_PASSIVE)


def test_known_names_have_fixed_addresses_and_container_names_do_not_resolve():
    assert socket.getaddrinfo("discord.com", 443, type=socket.SOCK_STREAM)[0][4][0] == "162.159.128.233"
    assert socket.getaddrinfo("NTFY.sh", 443, type=socket.SOCK_STREAM)[0][4][0] == "159.203.148.75"
    with pytest.raises(socket.gaierror):  # the same on a machine that does run such a container
        socket.getaddrinfo("kiboto-ollama", 11434)


def test_a_test_may_resolve_names_itself(fixed_dns):
    from backend.services.ssrf_guard import validate_public_url

    assert validate_public_url("https://api.github.com/")[0] is True  # from the fixed table, not the network
    assert validate_public_url("https://not-in-the-table.invalid/")[0] is False


@pytest.mark.real_network
def test_a_test_marked_real_network_keeps_the_real_lookup():
    assert socket.getaddrinfo.__module__ in ("socket", "_socket")
