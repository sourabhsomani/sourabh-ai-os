"""AI model providers, using only the Python standard library.

Model references are written "provider/model", e.g.
    ollama/qwen2.5:0.5b          local model served by Ollama
    anthropic/claude-haiku-5-5   Claude via the Anthropic API
    openai/gpt-4o-mini           any OpenAI-compatible server (OpenAI, vLLM, LM Studio…)
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class AIError(Exception):
    pass


def _open(url, data=None, headers=None, method=None, timeout=600):
    body = json.dumps(data).encode() if data is not None else None
    h = {"Content-Type": "application/json", "User-Agent": "SourabhOS/1.0"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method=method or ("POST" if body else "GET"))
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        try:
            j = json.loads(detail)
            detail = j.get("error", {}).get("message") if isinstance(j.get("error"), dict) else j.get("error", detail)
        except (ValueError, AttributeError):
            pass
        raise AIError(f"HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, OSError) as e:
        raise AIError(f"cannot reach {url.split('/')[2]}: {getattr(e, 'reason', e)}") from None


def _json(url, data=None, headers=None, method=None, timeout=30):
    with _open(url, data, headers, method, timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def _sse(resp):
    """Yield parsed JSON objects from a server-sent-events stream."""
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except ValueError:
            continue


class Result(dict):
    """{text, tokens, seconds, model}  (+ tokens_per_s property)."""
    @property
    def tokens_per_s(self):
        return self["tokens"] / self["seconds"] if self["seconds"] > 0 else 0.0


class Provider:
    key = "base"
    label = "Base"

    def available(self) -> bool:
        return False

    def models(self) -> list[dict]:
        return []

    def chat(self, model, messages, on_token=None, stop=None, temperature=None, max_tokens=2048) -> Result:
        raise NotImplementedError


# ---------------------------------------------------------------- Ollama
class Ollama(Provider):
    key, label = "ollama", "Local (Ollama)"

    def __init__(self, url="http://127.0.0.1:11434"):
        self.url = url.rstrip("/")

    def available(self):
        try:
            _json(self.url + "/api/version", timeout=1.5)
            return True
        except (AIError, ValueError):
            return False

    def version(self):
        return _json(self.url + "/api/version", timeout=3).get("version", "?")

    def models(self):
        out = []
        for m in _json(self.url + "/api/tags", timeout=5).get("models", []):
            d = m.get("details") or {}
            out.append({"name": m.get("name") or m.get("model"), "size": m.get("size", 0),
                        "params": d.get("parameter_size", ""), "quant": d.get("quantization_level", "")})
        return out

    def running(self):
        try:
            return _json(self.url + "/api/ps", timeout=3).get("models", [])
        except (AIError, ValueError):
            return []

    def pull(self, model, progress=None, stop=None):
        with _open(self.url + "/api/pull", {"model": model, "stream": True}, timeout=3600) as r:
            for raw in r:
                if stop is not None and stop.is_set():
                    raise AIError("cancelled")
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if ev.get("error"):
                    raise AIError(ev["error"])
                if progress:
                    progress(ev.get("status", ""), ev.get("completed", 0), ev.get("total", 0))

    def delete(self, model):
        _json(self.url + "/api/delete", {"model": model}, method="DELETE")

    def chat(self, model, messages, on_token=None, stop=None, temperature=None, max_tokens=2048):
        opts = {"num_predict": max_tokens}
        if temperature is not None:
            opts["temperature"] = temperature
        t0 = time.time()
        text, tokens = [], 0
        with _open(self.url + "/api/chat", {"model": model, "messages": messages,
                                             "stream": True, "options": opts}) as r:
            for raw in r:
                if stop is not None and stop.is_set():
                    break
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if ev.get("error"):
                    raise AIError(ev["error"])
                piece = (ev.get("message") or {}).get("content", "")
                if piece:
                    text.append(piece)
                    if on_token:
                        on_token(piece)
                if ev.get("done"):
                    tokens = ev.get("eval_count", tokens)
        out = "".join(text)
        return Result(text=out, tokens=tokens or len(out) // 4, seconds=time.time() - t0, model=model)


# ---------------------------------------------------------------- Anthropic
class Anthropic(Provider):
    key, label = "anthropic", "Anthropic (Claude)"
    MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]

    def __init__(self, api_key="", url="https://api.anthropic.com"):
        self.api_key = api_key
        self.url = url.rstrip("/")

    def available(self):
        return bool(self.api_key)

    def models(self):
        return [{"name": m, "size": 0, "params": "cloud", "quant": ""} for m in self.MODELS]

    def chat(self, model, messages, on_token=None, stop=None, temperature=None, max_tokens=2048):
        if not self.api_key:
            raise AIError("no Anthropic API key (set it in Models → Providers)")
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        msgs = [m for m in messages if m["role"] != "system"]
        body = {"model": model, "max_tokens": max_tokens, "messages": msgs, "stream": True}
        if system:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = temperature
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        t0 = time.time()
        text, tokens = [], 0
        with _open(self.url + "/v1/messages", body, headers) as r:
            for ev in _sse(r):
                if stop is not None and stop.is_set():
                    break
                kind = ev.get("type")
                if kind == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                    piece = ev["delta"]["text"]
                    text.append(piece)
                    if on_token:
                        on_token(piece)
                elif kind == "message_delta":
                    tokens = ev.get("usage", {}).get("output_tokens", tokens)
                elif kind == "error":
                    raise AIError(ev.get("error", {}).get("message", "API error"))
        out = "".join(text)
        return Result(text=out, tokens=tokens or len(out) // 4, seconds=time.time() - t0, model=model)


# ---------------------------------------------------------------- OpenAI-compatible
class OpenAICompat(Provider):
    key, label = "openai", "OpenAI-compatible"

    def __init__(self, url="", api_key=""):
        self.url = url.rstrip("/")
        self.api_key = api_key

    def _h(self):
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def available(self):
        return bool(self.url)

    def models(self):
        if not self.url:
            return []
        data = _json(self.url + "/models", headers=self._h(), timeout=8).get("data", [])
        return [{"name": m["id"], "size": 0, "params": "remote", "quant": ""} for m in data]

    def chat(self, model, messages, on_token=None, stop=None, temperature=None, max_tokens=2048):
        if not self.url:
            raise AIError("no OpenAI-compatible URL set (Models → Providers)")
        body = {"model": model, "messages": messages, "stream": True, "max_tokens": max_tokens}
        if temperature is not None:
            body["temperature"] = temperature
        t0 = time.time()
        text, tokens = [], 0
        with _open(self.url + "/chat/completions", body, self._h()) as r:
            for ev in _sse(r):
                if stop is not None and stop.is_set():
                    break
                for ch in ev.get("choices", []):
                    piece = (ch.get("delta") or {}).get("content") or ""
                    if piece:
                        text.append(piece)
                        if on_token:
                            on_token(piece)
                if ev.get("usage"):
                    tokens = ev["usage"].get("completion_tokens", tokens)
        out = "".join(text)
        return Result(text=out, tokens=tokens or len(out) // 4, seconds=time.time() - t0, model=model)


# ---------------------------------------------------------------- router
DEFAULT_AI_SETTINGS = {
    "ollama_url": "http://127.0.0.1:11434",
    "anthropic_key": "",
    "anthropic_url": "https://api.anthropic.com",
    "openai_url": "",
    "openai_key": "",
    "default_model": "ollama/qwen2.5:0.5b",
    "system_prompt": "You are a helpful assistant running on Sourabh OS.",
    "temperature": 0.7,
}


class AIService:
    """Routes 'provider/model' references to the right provider."""

    def __init__(self, settings: dict):
        self.settings = settings
        self.configure()

    def configure(self):
        s = {**DEFAULT_AI_SETTINGS, **self.settings}
        self.settings.update(s)
        self.providers = {
            "ollama": Ollama(s["ollama_url"]),
            "anthropic": Anthropic(s["anthropic_key"], s["anthropic_url"]),
            "openai": OpenAICompat(s["openai_url"], s["openai_key"]),
        }

    @staticmethod
    def split(ref: str):
        if "/" in ref:
            p, m = ref.split("/", 1)
            if p in ("ollama", "anthropic", "openai"):
                return p, m
        return "ollama", ref

    def provider(self, ref):
        return self.providers[self.split(ref)[0]]

    def all_models(self):
        """[(ref, info)] across every configured provider. Errors are skipped."""
        out = []
        for key, p in self.providers.items():
            if key == "ollama" or p.available():
                try:
                    out += [(f"{key}/{m['name']}", m) for m in p.models()]
                except (AIError, ValueError, KeyError):
                    pass
        return out

    def chat(self, ref, messages, **kw) -> Result:
        prov, model = self.split(ref or self.settings["default_model"])
        if "temperature" not in kw:
            kw["temperature"] = self.settings.get("temperature")
        return self.providers[prov].chat(model, messages, **kw)

    def ask(self, prompt, ref=None, system=None, **kw) -> Result:
        msgs = []
        sp = self.settings.get("system_prompt") if system is None else system
        if sp:
            msgs.append({"role": "system", "content": sp})
        msgs.append({"role": "user", "content": prompt})
        return self.chat(ref or self.settings["default_model"], msgs, **kw)
