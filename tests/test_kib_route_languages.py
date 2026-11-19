"""Kib sends a question about the NAS to the reading that answers it, in all five languages.

The first router knew English words only. Each case is a sentence a person would type."""

import types

import pytest

from backend.services import ai_chat_agent as agent
from backend.services import chat_route_words as words

OWNER = types.SimpleNamespace(scopes=["*"], role_id="superadmin", username="admin", user_id="a1", id="a1")

TOOLS = {
    "get_storage_status": ("tool_get_storage_status", words.STORAGE_WORDS),
    "get_system_telemetry": ("tool_get_system_telemetry", words.TELEMETRY_WORDS),
    "get_disks_and_standby_status": ("tool_get_disks_and_standby_status", words.DISK_WORDS),
    "get_fan_and_thermal_status": ("tool_get_fan_and_thermal_status", words.FAN_WORDS),
    "list_docker_containers": ("tool_list_docker_containers", words.APP_WORDS),
    "get_network_status": ("tool_get_network_status", words.NETWORK_WORDS),
}

ASKS = [
    # German
    ("Wie viel Speicherplatz ist noch frei?", "get_storage_status"),
    ("Gibt es beschädigte Dateien?", "get_storage_status"),
    ("Wie hoch ist die Auslastung vom Prozessor?", "get_system_telemetry"),
    ("Wie hoch ist der Stromverbrauch?", "get_system_telemetry"),
    ("Schlafen meine Festplatten?", "get_disks_and_standby_status"),
    ("Was machen die Lüfter gerade?", "get_fan_and_thermal_status"),
    ("Welche Apps laufen gerade?", "list_docker_containers"),
    ("Wie lautet meine IP-Adresse im Netzwerk?", "get_network_status"),
    # Spanish
    ("¿Cuánto espacio libre queda?", "get_storage_status"),
    ("¿Hay archivos dañados?", "get_storage_status"),
    ("¿Cuánta electricidad gasta el NAS?", "get_system_telemetry"),
    ("¿Cómo va el procesador?", "get_system_telemetry"),
    ("¿Están dormidos los discos duros?", "get_disks_and_standby_status"),
    ("¿Qué hacen los ventiladores?", "get_fan_and_thermal_status"),
    ("¿Qué contenedores están en marcha?", "list_docker_containers"),
    ("¿Cuál es la puerta de enlace?", "get_network_status"),
    # French
    ("Combien d'espace libre reste-t-il ?", "get_storage_status"),
    ("Y a-t-il des fichiers endommagés ?", "get_storage_status"),
    ("Quelle est la consommation électrique du NAS ?", "get_system_telemetry"),
    ("Les disques sont-ils en veille ?", "get_disks_and_standby_status"),
    ("Que font les ventilateurs ?", "get_fan_and_thermal_status"),
    ("Quels conteneurs tournent ?", "list_docker_containers"),
    ("Quelle est mon adresse IP sur le réseau ?", "get_network_status"),
    # Chinese: no spaces, so the word is found inside the sentence
    ("还有多少可用空间？", "get_storage_status"),
    ("有没有损坏的文件？", "get_storage_status"),
    ("NAS一个月用电多少？", "get_system_telemetry"),
    ("内存用了多少？", "get_system_telemetry"),
    ("硬盘在休眠吗？", "get_disks_and_standby_status"),
    ("风扇现在转得快吗？", "get_fan_and_thermal_status"),
    ("现在有哪些容器在运行？", "list_docker_containers"),
    ("我的IP地址和网关是什么？", "get_network_status"),
]

NOT_ASKED = [
    # words that mean something else in another of the languages stay out
    ("put a red label on this file", "get_network_status"),
    ("find my disco playlist", "get_disks_and_standby_status"),
    ("busca la memoria del proyecto", "get_system_telemetry"),
    ("the plan for my program", "get_network_status"),
    ("la red social de mi hermana", "get_network_status"),
    ("ein Bild vom Lüftungsschacht", "get_fan_and_thermal_status"),
    ("how do I cook rice", "get_storage_status"),
]


@pytest.mark.parametrize("question, tool", ASKS)
def test_a_question_in_any_language_finds_its_words(question, tool):
    assert agent._mentions(question.lower(), TOOLS[tool][1]), question


@pytest.mark.parametrize("question, tool", NOT_ASKED)
def test_words_that_mean_something_else_do_not_route(question, tool):
    assert not agent._mentions(question.lower(), TOOLS[tool][1]), question


def test_the_agent_uses_these_lists_and_english_still_reads_whole_words():
    assert agent.STORAGE_WORDS is words.STORAGE_WORDS and agent.NETWORK_WORDS is words.NETWORK_WORDS
    assert agent._mentions("how much ram is used", words.TELEMETRY_WORDS)
    assert not agent._mentions("my program has a plan", words.TELEMETRY_WORDS + words.NETWORK_WORDS)
    for name in ("STORAGE", "TELEMETRY", "DISK", "FAN", "APP", "NETWORK"):
        listed = getattr(words, f"{name}_WORDS")
        assert len(set(listed)) == len(listed), f"{name}_WORDS repeats a word"
        assert all(w == w.lower() and w == w.strip() for w in listed), f"{name}_WORDS must be lower case"


@pytest.fixture
def turn(monkeypatch):
    """One chat turn with no model behind it; `ran` collects the tools that really ran."""
    ran: list[str] = []
    for name, (func, _w) in TOOLS.items():
        monkeypatch.setattr(agent, func, lambda *a, _n=name, **k: ran.append(_n) or {"tool": _n, "status": "ok"})
    monkeypatch.setattr(agent, "_try_local_llm_completion", lambda *a, **k: ("", "", 0, 0.0, {}, None))
    monkeypatch.setattr(agent, "detect_hardware_accelerator", lambda *a, **k: {"has_npu": False, "has_gpu": False})
    from backend import users_db

    monkeypatch.setattr(users_db, "log_security_event", lambda *a, **k: None)
    return (lambda message: agent._run_agentic_chat_turn(message, [], False, True, None, OWNER)), ran


@pytest.mark.parametrize(
    "question, tool",
    [
        ("Wie viel Speicherplatz ist noch frei?", "get_storage_status"),
        ("¿Cuál es la puerta de enlace?", "get_network_status"),
        ("Les disques sont-ils en veille ?", "get_disks_and_standby_status"),
        ("风扇现在转得快吗？", "get_fan_and_thermal_status"),
        ("NAS一个月用电多少？", "get_system_telemetry"),
        ("¿Qué contenedores están en marcha?", "list_docker_containers"),
    ],
)
def test_the_whole_turn_runs_the_tool(turn, question, tool):
    run, ran = turn
    out = run(question)
    assert tool in ran, (question, ran)
    assert any(r.get("tool") == tool for r in out["tool_results"])
