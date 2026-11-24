"""The eval's second opinion (AI-28): a local model grades each answer, next to the rules' score."""

import io
import json

from tests.rag_eval import judge as j

ROWS = [
    {
        "id": "qa-001",
        "question": "At what temperature do I bake the banana bread?",
        "expected": ["175"],
        "relevant": ["en/recipes/banana_bread.md"],
        "answer": "At 175 °C.",
        "auto_correct": True,
    },
    {
        "id": "qa-002",
        "question": "When is the boiler serviced?",
        "expected": ["March"],
        "expected_all": ["2025"],
        "relevant": ["en/missing.md"],
        "answer": "In May.",
        "auto_correct": True,
    },
    {
        "id": "qa-090",
        "question": "What is my bank PIN?",
        "unanswerable": True,
        "relevant": [],
        "answer": "Your files do not say.",
        "auto_correct": True,
    },
]


class Server:
    def __init__(self, answers):
        self.answers, self.asked = list(answers), []

    def __call__(self, url, body, timeout):
        self.asked.append((url, body))
        said = self.answers.pop(0)
        if isinstance(said, Exception):
            raise said
        return {"message": {"content": said if isinstance(said, str) else json.dumps(said)}}


def test_the_judge_sees_the_question_the_facts_and_the_file():
    text = j.prompt(ROWS[0])
    assert "banana bread" in text and "Any of: 175" in text and "Grandma's banana bread" in text
    assert "All of: 2025" in j.prompt(ROWS[1]) and "is made while the eval runs" in j.prompt(ROWS[1])
    assert "the right answer declines" in j.prompt(ROWS[2]) and "(no source file)" in j.prompt(ROWS[2])
    assert j.source_text(["../../../etc/passwd"]) == "(no source file)"  # only files of the corpus


def test_grades_sit_next_to_the_rules_and_disagreements_are_listed():
    server = Server(
        [
            {"grade": "correct", "supported": True, "why": "175 °C as in the recipe"},
            {"grade": "wrong", "supported": False, "why": "the file says March"},
            {"grade": "declined", "supported": True, "why": "it declines"},
        ]
    )
    out = j.judge(ROWS, "http://ollama:11434", "qwen3:8b", post=server)
    assert out["graded"] == 3 and out["right"] == round(2 / 3, 3) and out["supported"] == round(2 / 3, 3)
    assert out["agrees_with_rules"] == round(2 / 3, 3)
    assert out["disagree"] == [{"id": "qa-002", "rules": True, "judge": "wrong", "why": "the file says March"}]
    url, body = server.asked[0]
    assert url == "http://ollama:11434/api/chat" and body["format"] == "json" and body["think"] is False
    assert body["options"]["temperature"] == 0 and body["messages"][0]["content"] == j.SYSTEM
    assert body["options"]["num_gpu"] == 0  # the judge runs on the CPU, never on the iGPU


def test_an_answer_the_judge_could_not_grade_is_left_out_and_time_is_bounded():
    server = Server([OSError("refused"), "not json", {"grade": "maybe"}])
    out = j.judge(ROWS, "http://o", "m", post=server)
    assert out["asked"] == 3 and out["graded"] == 0 and out["right"] == 0.0
    assert out["rows"][0]["why"] == "no grade: OSError"
    ticks = iter([0.0, 0.0, 61.0])
    out = j.judge(ROWS, "http://o", "m", post=Server([{"grade": "correct"}] * 3), minutes=1, clock=lambda: next(ticks))
    assert out["asked"] == 1 and out["of"] == 3  # stopped when the time ran out


def test_the_judge_is_used_only_when_its_model_is_there(monkeypatch):
    def tags(url, timeout):
        return io.BytesIO(json.dumps({"models": [{"name": "qwen3:8b"}, {"name": "llama3.2:latest"}]}).encode())

    monkeypatch.setattr(j.urllib.request, "urlopen", tags)
    assert j.judge_available("http://o", "qwen3:8b") and j.judge_available("http://o", "llama3.2")
    assert not j.judge_available("http://o", "qwen3:14b")  # never pulled from here

    def down(url, timeout):
        raise OSError("down")

    monkeypatch.setattr(j.urllib.request, "urlopen", down)
    assert not j.judge_available("http://o", "qwen3:8b")
