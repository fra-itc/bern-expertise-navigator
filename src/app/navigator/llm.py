"""Thin client for Apertus behind an OpenAI-compatible API (vLLM locally, or a sovereign hosted endpoint)."""
from __future__ import annotations

import contextvars
import json
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, ValidationError

from .config import settings


class LLMError(RuntimeError):
    pass


# Token accounting -> cost per indexed page / per query (printed by the CLI and eval)
_lock = threading.Lock()
usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

# Structured-output modes, strongest first. vLLM supports json_schema (guided decoding);
# some hosted gateways only accept json_object or nothing. We downgrade once and remember.
_MODES = ["json_schema", "json_object", "none"]
_mode_idx = 0


def reset_usage() -> None:
    with _lock:
        for k in usage:
            usage[k] = 0


@dataclass
class Meter:
    """The Apertus calls made on behalf of one web request (written to the usage log by api.py)."""
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0           # time spent waiting for Apertus
    case_id: str = ""              # the request (case) the calls were made for, when known
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, prompt: int, completion: int, seconds: float) -> None:
        with self._lock:
            self.calls += 1
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.seconds += seconds


_meter: contextvars.ContextVar[Meter | None] = contextvars.ContextVar("llm_meter", default=None)


@contextmanager
def metered():
    """Count the Apertus calls made inside the block (and in threads started with `bound`)."""
    m = Meter()
    tok = _meter.set(m)
    try:
        yield m
    finally:
        _meter.reset(tok)


def current_meter() -> Meter | None:
    return _meter.get()


def bound(fn):
    """fn, counting its Apertus calls on the caller's meter when it runs in a thread pool."""
    m = _meter.get()

    def run(*a, **kw):
        tok = _meter.set(m)
        try:
            return fn(*a, **kw)
        finally:
            _meter.reset(tok)
    return run


def _from_sse(lines) -> dict:
    """Server-sent events of a streamed completion -> the usual non-streamed response body."""
    parts: list[str] = []
    u: dict = {}
    for line in lines:
        if not line.startswith("data:"):
            continue
        d = line[5:].strip()
        if d == "[DONE]":
            break
        try:
            j = json.loads(d)
        except json.JSONDecodeError:
            continue
        u = j.get("usage") or u
        for ch in j.get("choices") or []:
            parts.append((ch.get("delta") or {}).get("content") or "")
    return {"choices": [{"message": {"content": "".join(parts)}}], "usage": u}


def _post(body: dict, usage_in_stream: bool = True) -> httpx.Response:
    url = f"{settings.llm_base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    if not settings.llm_stream:
        return httpx.post(url, json=body, headers=headers, timeout=settings.llm_timeout)
    # Streamed, so a gateway in front of a slow 70B model never sees a silent connection and cuts it
    # (gateway.keera.ch answers 504 after 60 s without a byte). The caller still gets one JSON body.
    sbody = {**body, "stream": True, **({"stream_options": {"include_usage": True}} if usage_in_stream else {})}
    with httpx.stream("POST", url, json=sbody, headers=headers, timeout=settings.llm_timeout) as r:
        if r.status_code >= 400:
            r.read()
            if usage_in_stream and "stream_options" in r.text:  # gateway without usage-in-stream support
                return _post(body, usage_in_stream=False)
            return httpx.Response(r.status_code, text=r.text, request=r.request)
        return httpx.Response(200, json=_from_sse(r.iter_lines()), request=r.request)


def _keys(schema: type[BaseModel]) -> str:
    """The expected keys in plain words: a raw JSON schema gets echoed back by some models."""
    out = []
    for name, f in schema.model_fields.items():
        t = getattr(f.annotation, "__name__", None) or str(f.annotation).replace("typing.", "")
        out.append(f'"{name}" ({t})')
    return ", ".join(out)


def chat(messages: list[dict], *, schema: type[BaseModel] | None = None,
         max_tokens: int = 2048, temperature: float = 0.0, mode: str | None = None) -> str:
    """mode: force one structured-output mode. "none" (format described in the prompt) is ~10x faster than
    guided "json_schema" decoding on the shared Apertus gateway, so interactive calls use it."""
    global _mode_idx
    forced = mode
    while True:
        body: dict = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        mode = (forced or _MODES[_mode_idx]) if schema is not None else "none"
        if mode == "json_schema":
            # Guided decoding: the model can only emit JSON matching the schema
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            }
        elif mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        if schema is not None and mode != "json_schema":
            body["messages"] = [*messages[:-1], {**messages[-1], "content": messages[-1]["content"] +
                                "\n\nReply with exactly ONE JSON object with these keys: " + _keys(schema) +
                                ". No schema, no markdown, no text before or after the object."}]
        t0 = time.monotonic()
        try:
            r = _post(body)
        except httpx.HTTPError as e:
            raise LLMError(str(e)) from e
        if r.status_code in (400, 422) and mode != "none" and "response_format" in r.text and not forced:
            _mode_idx = min(_mode_idx + 1, len(_MODES) - 1)
            continue
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        u = data.get("usage") or {}
        with _lock:
            usage["calls"] += 1
            usage["prompt_tokens"] += u.get("prompt_tokens", 0)
            usage["completion_tokens"] += u.get("completion_tokens", 0)
        if (m := _meter.get()) is not None:
            m.add(u.get("prompt_tokens", 0), u.get("completion_tokens", 0), time.monotonic() - t0)
        return data["choices"][0]["message"]["content"] or ""


def _objects(raw: str):
    """Every top-level JSON object in the text, in order (models sometimes echo the schema first)."""
    dec = json.JSONDecoder()
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M)
    i = raw.find("{")
    while i != -1:
        try:
            obj, end = dec.raw_decode(raw, i)
        except json.JSONDecodeError:
            i = raw.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            yield obj
        i = raw.find("{", end)


def chat_json(messages: list[dict], schema: type[BaseModel], retries: int = 2, **kw) -> BaseModel:
    last: Exception | None = None
    for _ in range(retries + 1):
        raw = chat(messages, schema=schema, **kw)
        try:
            return schema.model_validate_json(_strip(raw))
        except (ValidationError, json.JSONDecodeError) as e:
            last = e
        for obj in _objects(raw):
            if "properties" in obj and "type" in obj:   # an echoed JSON schema, not the answer
                continue
            try:
                return schema.model_validate(obj)
            except ValidationError as e:
                last = e
    raise LLMError(f"Invalid JSON from model after retries: {last}")


def ping() -> str:
    """Fail fast with a readable message if the endpoint is not reachable."""
    try:
        r = httpx.get(f"{settings.llm_base_url}/models",
                      headers={"Authorization": f"Bearer {settings.llm_api_key}"}, timeout=15)
        r.raise_for_status()
        ids = [m.get("id") for m in r.json().get("data", [])]
    except (httpx.HTTPError, ValueError) as e:
        raise LLMError(f"LLM endpoint {settings.llm_base_url} not reachable: {e}") from e
    if ids and settings.llm_model not in ids:
        raise LLMError(f"Model '{settings.llm_model}' not served at {settings.llm_base_url}; available: {ids}")
    return settings.llm_model


_avail: dict = {"ok": None, "at": 0.0}


def available(ttl: float = 60.0) -> bool:
    """Cached reachability check so search degrades instantly (no LLM) instead of timing out per query."""
    if _avail["ok"] is None or time.time() - _avail["at"] > ttl:
        try:
            r = httpx.get(f"{settings.llm_base_url}/models",
                          headers={"Authorization": f"Bearer {settings.llm_api_key}"}, timeout=3)
            _avail["ok"] = r.status_code == 200
        except httpx.HTTPError:
            _avail["ok"] = False
        _avail["at"] = time.time()
    return bool(_avail["ok"])


def _strip(raw: str) -> str:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M)
    m = re.search(r"\{.*\}", raw, re.S)
    return m.group(0) if m else raw
