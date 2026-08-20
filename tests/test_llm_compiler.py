"""Unit tests for the LLM compiler and its payload parsing."""

import json

from app.models.selector import SelectorInventory
from app.services.llm_compiler import LLMCompiler, _clean_paths


def _inventory():
    return SelectorInventory(
        ids={"#header": 3, "#footer": 3},
        classes={".slide": 3, ".container": 3, ".icon-txt": 3},
        tags={"div": 9, "nav": 3, "footer": 3},
    )


def test_parse_payload_rejects_bad_json():
    assert LLMCompiler()._parse_payload("not json") == {}


def test_clean_paths_keeps_only_safe_paths():
    assert _clean_paths(["/admin", "/cart", "../escape", "https://evil.com/x"]) == ["/admin", "/cart"]


def test_compile_config_filters_utility_class(monkeypatch):
    monkeypatch.setattr(
        "app.services.llm_client.llm_complete",
        lambda prompt, json_mode=False: json.dumps({
            "elementsToRemove": [".slide", ".container", ".icon-txt"],
            "pathsToSkip": ["/admin"],
        }),
    )
    compiler = LLMCompiler()
    result = compiler.compile_config(
        url="https://example.com",
        platforms=["custom"],
        inventory=_inventory(),
        json_ld_blobs=[],
        num_pages=3,
        sample_html="<html></html>",
    )
    assert ".slide" in result["elementsToRemove"]
    assert ".icon-txt" in result["elementsToRemove"]
    assert ".container" not in result["elementsToRemove"]  # utility guard
    assert result["pathsToSkip"] == ["/admin"]


def test_compile_config_caps_selectors(monkeypatch):
    lots = [f".sel-{i}" for i in range(30)]
    monkeypatch.setattr(
        "app.services.llm_client.llm_complete",
        lambda prompt, json_mode=False: json.dumps({"elementsToRemove": lots}),
    )
    result = LLMCompiler().compile_config(
        "https://example.com", ["custom"], _inventory(), [], 3, "<html></html>"
    )
    assert len(result["elementsToRemove"]) <= 15