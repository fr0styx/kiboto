"""AI finding 28: Kib's reading hours cover photo search by meaning too, and name their time zone."""

import time

from backend.services import photo_vectors
from backend.services.rag_engine_learning import RagLearningMixin


def test_the_zone_is_the_households(monkeypatch):
    monkeypatch.setattr("backend.services.identity.get_identity", lambda: {"timezone": "America/Puerto_Rico"})
    assert RagLearningMixin.schedule_time_zone() == "America/Puerto_Rico"


def test_without_a_household_zone_the_clocks_own_name(monkeypatch):
    monkeypatch.setattr("backend.services.identity.get_identity", lambda: {"timezone": ""})
    monkeypatch.setattr(time, "tzname", ("AST", "ADT"))
    assert RagLearningMixin.schedule_time_zone() == "AST"
    monkeypatch.setattr(time, "tzname", ("", ""))
    assert RagLearningMixin.schedule_time_zone() == "UTC"

    def broken():
        raise OSError("identity file unreadable")

    monkeypatch.setattr("backend.services.identity.get_identity", broken)
    assert RagLearningMixin.schedule_time_zone() == "UTC"


class _Engine:
    def __init__(self, in_hours):
        self.in_hours = in_hours

    def get_config(self):
        return {"photo_vector_host": "http://127.0.0.1:9", "photo_vector_model": "m"}

    def is_within_learning_schedule(self):
        return (self.in_hours, "01:00")


def test_photo_search_waits_for_the_reading_hours(monkeypatch):
    monkeypatch.setattr(photo_vectors, "settings", lambda cfg: ("http://127.0.0.1:9", "m"))
    job = photo_vectors.PhotoVectorQueue(_Engine(False), idle=lambda: False)
    assert job.process_batch() == "outside_hours"
    job.engine = _Engine(True)
    assert job.process_batch() == "busy"  # inside the hours it goes on to its usual checks
