"""LLM client: structured-output fallback and per-page extraction cache (HTTP stubbed, no endpoint needed)."""
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import extract, llm  # noqa: E402
from navigator.schema import Extraction, Page  # noqa: E402

PAGE = Page(url="https://x.unibe.ch/p", source="artorg", title="Jane Doe",
            text="Prof. Dr. Jane Doe leads the Diabetes Technology Lab.\nShe works on continuous glucose monitoring.",
            fetched_at="2026-10-18T09:00:00Z", page_type="person")

ANSWER = {"entities": [{"entity_type": "person",
                        "name": {"value": "Jane Doe", "snippet": "Prof. Dr. Jane Doe leads the Diabetes Technology Lab."},
                        "expertise": [{"value": "continuous glucose monitoring",
                                       "snippet": "She works on continuous glucose monitoring."},
                                      {"value": "astrophysics", "snippet": "She studies black holes."}]}]}


class Server:
    def __init__(self, reject_schema=False):
        self.calls: list[dict] = []
        self.reject_schema = reject_schema

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append(json)
        req = httpx.Request("POST", url)
        rf = (json.get("response_format") or {}).get("type")
        if self.reject_schema and rf == "json_schema":
            return httpx.Response(400, text='{"error": "response_format json_schema not supported"}', request=req)
        content = "```json\n" + __import__("json").dumps(ANSWER) + "\n```"
        return httpx.Response(200, request=req, json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}})


def test_downgrades_when_json_schema_unsupported(monkeypatch):
    srv = Server(reject_schema=True)
    monkeypatch.setattr(llm.httpx, "post", srv)
    monkeypatch.setattr(llm.settings, "llm_stream", False)
    monkeypatch.setattr(llm, "_mode_idx", 0)
    llm.reset_usage()
    out = llm.chat_json([{"role": "user", "content": "x"}], Extraction)
    assert out.entities[0].name.value == "Jane Doe"
    assert srv.calls[0]["response_format"]["type"] == "json_schema"
    assert srv.calls[-1]["response_format"]["type"] == "json_object"
    assert "schema" in srv.calls[-1]["messages"][-1]["content"]  # schema moved into the prompt
    assert llm.usage["calls"] == 1 and llm.usage["prompt_tokens"] == 100


def test_extraction_is_verified_and_cached(monkeypatch, tmp_path):
    srv = Server()
    monkeypatch.setattr(llm.httpx, "post", srv)
    monkeypatch.setattr(llm.settings, "llm_stream", False)
    monkeypatch.setattr(llm, "_mode_idx", 0)
    monkeypatch.setattr(extract, "CACHE_DIR", tmp_path)
    rejected: list[dict] = []
    [e] = extract.extract_page(PAGE, rejected)
    assert [c.value for c in e.expertise] == ["continuous glucose monitoring"]
    assert rejected == [{"source": "artorg", "url": PAGE.url, "field": "expertise",
                         "value": "astrophysics", "snippet": "She studies black holes."}]
    extract.extract_page(PAGE, [])
    assert len(srv.calls) == 1  # second run served from cache
    assert json.loads(next(tmp_path.glob("*.json")).read_text())["entities"]


def test_streamed_completion_is_reassembled():
    lines = ['data: {"choices":[{"delta":{"role":"assistant"}}]}', "",
             'data: {"choices":[{"delta":{"content":"{\\"a\\": "}}]}',
             'data: {"choices":[{"delta":{"content":"1}"}}]}',
             ': keep-alive', 'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}', "data: [DONE]"]
    out = llm._from_sse(lines)
    assert out["choices"][0]["message"]["content"] == '{"a": 1}' and out["usage"]["completion_tokens"] == 2
