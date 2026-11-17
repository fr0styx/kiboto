"""Kib's model advice says how each sentence was made, so the page shows it in the reader's language."""

import json
import re
from pathlib import Path

import pytest

from backend.services import media_engine as me

ROOT = Path(__file__).resolve().parents[1]
EN = {
    m.group(1): json.loads(m.group(2))
    for m in re.finditer(
        r'^  "([^"]+)": (".*"),$', (ROOT / "frontend/src/locales/en.js").read_text(encoding="utf-8"), re.M
    )
}


def english(how):
    """A sentence as the page writes it in English; every value the text names must be given."""
    key = how.get("msg_key") or how.get("key")
    assert key in EN, key
    text = EN[key]
    params = how.get("params") or {}
    assert set(re.findall(r"\{(\w+)\}", text)) == set(params), (key, params)
    for name, value in params.items():
        if isinstance(value, dict) and "number" in value:
            value = f"{value['number']:.{value['digits']}f}"
        elif isinstance(value, dict):
            value = english(value)
        text = text.replace("{" + name + "}", str(value))
    return text


NPU_IGPU = {"has_npu": True, "has_igpu": True, "device_label": "Intel AI Boost", "secondary_gpu": "Intel Arc"}
PROFILES = [
    (NPU_IGPU, 58.4),
    (NPU_IGPU, 8.0),
    ({"has_npu": True}, 16.0),  # an NPU without a name: "Onboard NPU", translated
    ({"has_igpu": True, "secondary_gpu": "Intel UHD 770"}, 16.0),
    ({"has_cuda": True, "secondary_gpu": "RTX 4090"}, 64.0),
    ({}, 4.0),
]


@pytest.mark.parametrize("accel,ram", PROFILES)
def test_every_sentence_of_the_advice_is_known_to_the_page(accel, ram):
    rec = me.build_llm_recommendations(accel, ram, include_incompatible=True, min_release_year=None, removed_models=[])
    assert english(rec["headline_text"]) and english(rec["hardware_summary_text"])
    assert rec["models"]
    for m in rec["models"]:
        assert english(m["fit_badge_text"]) and english(m["fit_reason_text"])
        assert m["why_recommended_text"] == m["fit_reason_text"]
        if not m["fits_hardware"]:
            assert english(m["warning_text"]) == english(m["fit_reason_text"])
        if m.get("role_text"):
            assert english(m["use_case_text"]) == m["use_case"]
        if m.get("target_device_text"):
            assert english(m["target_device_text"]).startswith("Needs a discrete GPU")


def test_the_headline_names_the_hardware_in_the_readers_words():
    rec = me.build_llm_recommendations({}, 4.0, include_incompatible=True, min_release_year=None, removed_models=[])
    assert english(rec["headline_text"]) == "CPU only (4.0 GB memory)"
    rec = me.build_llm_recommendations(
        NPU_IGPU, 58.4, include_incompatible=True, min_release_year=None, removed_models=[]
    )
    assert english(rec["headline_text"]) == "NPU + graphics (Intel AI Boost + Intel Arc (58.4 GB memory))"
    assert "OpenVINO Model Server can use Intel AI Boost" in english(rec["hardware_summary_text"])
    rec = me.build_llm_recommendations({"has_npu": True}, 16.0, min_release_year=None, removed_models=[])
    assert rec["headline_text"]["params"]["tier"]["params"]["device"] == {
        "key": "srv.ai_label_npu",
        "default": "Onboard NPU",
    }


def test_each_kind_of_fit_has_its_own_words():
    kinds = set()
    for accel, ram in PROFILES:
        rec = me.build_llm_recommendations(
            accel, ram, include_incompatible=True, min_release_year=None, removed_models=[]
        )
        kinds |= {m["fit_badge_text"]["msg_key"] for m in rec["models"]}
    assert {"srv.ai_badge_no_fit", "srv.ai_badge_over_onboard", "srv.ai_badge_fits"} <= kinds
    assert kinds & {"srv.ai_badge_best_npu", "srv.ai_badge_best_npu_gpu", "srv.ai_badge_best_gpu"}
    # more than the NAS can spare for Kib, though it would fit in its memory
    fit = me.evaluate_model_hardware_fit({"est_ram_gb": 6.0, "min_ram_gb": 8.0}, accel={}, eff_ram=10.0)
    assert fit["fit_badge_text"]["msg_key"] == "srv.ai_badge_over_safe"
    assert english(fit["warning_text"]).startswith(
        "The model needs about 6.0 GB, more than the NAS can spare for Kib (5.5 of 10.0 GB)"
    )


def test_every_catalog_role_is_translated_word_for_word_from_the_catalog():
    cat = json.loads((ROOT / "backend/resources/ai_models.json").read_text(encoding="utf-8"))
    for m in cat["models"] + cat["large_models"]:
        assert EN["srv." + me._role_key(m["id"])] == m["role"], m["id"]


@pytest.mark.parametrize(
    "repo,accel,needs_card",
    [
        ("Qwen/Qwen3-4B-GGUF", {"has_igpu": True}, False),
        ("Qwen/Qwen2.5-32B-Instruct-GGUF", {"has_igpu": True}, True),
        ("Qwen/Qwen2.5-32B-Instruct-GGUF", {"has_cuda": True, "secondary_gpu": "RTX"}, False),
    ],
)
def test_hugging_face_results_say_how_too(repo, accel, needs_card):
    item = {"id": repo, "tags": ["gguf"], "downloads": 12345, "likes": 7, "pipeline_tag": "text-generation"}
    m = me._format_hf_api_item(item, accel, 32.0, "")
    assert english(m["use_case_text"]) == "Hugging Face release (text-generation) · 12345 downloads · 7 likes"
    assert m["use_case_text"]["params"]["downloads"] == {"number": 12345, "digits": 0}
    assert english(m["why_recommended_text"])
    assert bool(m["target_device_text"]) is needs_card


@pytest.mark.parametrize(
    "sort_by,first",
    [("date", "new"), ("recommended", "rec"), ("downloads", "popular"), ("size_asc", "small"), ("size_desc", "big")],
)
def test_the_advice_orders_its_models(sort_by, first):
    models = [
        {"id": "new", "release_timestamp": 3.0, "downloads": 1, "est_ram_gb": 4.0},
        {
            "id": "rec",
            "release_timestamp": 1.0,
            "downloads": 2,
            "est_ram_gb": 5.0,
            "recommended": True,
            "fits_hardware": True,
        },
        {"id": "popular", "release_timestamp": 2.0, "downloads": 900, "est_ram_gb": 3.0},
        {"id": "small", "release_timestamp": 0.0, "downloads": 0, "vram_or_ram_gb": 1.0},
        {"id": "big", "release_timestamp": 0.0, "downloads": 0, "est_ram_gb": 40.0},
    ]
    me._sort_models(models, sort_by)
    assert models[0]["id"] == first
