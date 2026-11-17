"""A Compose apply's progress lines carry message keys for the Jobs centre."""

from backend.services import docker_stacks as ds


def test_each_progress_line_has_its_key():
    assert ds._apply_progress_text("Getting nginx:1.27") == {
        "detail_id": "jobs.d.apply_getting",
        "detail_params": {"image": "nginx:1.27"},
    }
    assert ds._apply_progress_text("Starting web") == {
        "detail_id": "jobs.d.apply_starting",
        "detail_params": {"part": "web"},
    }
    assert ds._apply_progress_text("Checking that everything runs")["detail_id"] == "jobs.d.apply_checking"
    assert ds._apply_progress_text("Done")["detail_id"] == "jobs.d.apply_done"
    assert ds._apply_progress_text("Something new") == {}
