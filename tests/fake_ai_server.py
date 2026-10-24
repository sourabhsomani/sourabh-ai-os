"""A fake AI server that speaks the Ollama, Anthropic and OpenAI wire formats.
Used by the tests, and handy for demoing the UI without a real model:
    python3 -m tests.fake_ai_server 11434
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = {"qwen2.5:0.5b": 397_821_319, "llama3.2:3b": 2_019_393_189}
_flaky = {}
DELAY = 0.01


def reply_for(messages):
    user = [m for m in messages if m["role"] == "user"][-1]["content"]
    first = user.strip().splitlines()[-1] if user.strip() else ""
    return f"Echo from fake model: {first[:60]}".split(" ")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _stream(self, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _check_flaky(self, messages):
        text = json.dumps(messages)
        if "FLAKY" in text:
            _flaky[text] = _flaky.get(text, 0) + 1
            if _flaky[text] == 1:
                self._send(500, {"error": "temporary overload"})
                return True
        if "ALWAYSFAIL" in text:
            self._send(500, {"error": "model crashed"})
            return True
        return False

    def do_GET(self):
        if self.path == "/api/version":
            self._send(200, {"version": "0.0-fake"})
        elif self.path == "/api/tags":
            self._send(200, {"models": [{"name": n, "size": s, "details": {"parameter_size": "0.5B" if "0.5" in n else "3B",
                                                                           "quantization_level": "Q4_K_M"}} for n, s in MODELS.items()]})
        elif self.path == "/api/ps":
            self._send(200, {"models": []})
        elif self.path == "/v1/models":
            self._send(200, {"data": [{"id": "fake-gpt"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_DELETE(self):
        if self.path == "/api/delete":
            MODELS.pop(self._body().get("model"), None)
            self._send(200, {})

    def do_POST(self):
        try:
            self._post()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _post(self):
        body = self._body()
        if self.path == "/api/chat":
            if body.get("model") not in MODELS:
                return self._send(404, {"error": f"model '{body.get('model')}' not found"})
            if self._check_flaky(body["messages"]):
                return
            self._stream("application/x-ndjson")
            words = reply_for(body["messages"])
            for i, w in enumerate(words):
                time.sleep(DELAY)
                self.wfile.write((json.dumps({"message": {"role": "assistant", "content": w + (" " if i < len(words) - 1 else "")}, "done": False}) + "\n").encode())
                self.wfile.flush()
            self.wfile.write((json.dumps({"done": True, "eval_count": len(words), "eval_duration": 1}) + "\n").encode())
        elif self.path == "/api/pull":
            self._stream("application/x-ndjson")
            for st, c, t in [("pulling manifest", 0, 0), ("pulling abc", 50, 100), ("pulling abc", 100, 100), ("success", 0, 0)]:
                time.sleep(DELAY)
                self.wfile.write((json.dumps({"status": st, "completed": c, "total": t}) + "\n").encode())
            MODELS[body["model"]] = 1_000_000
        elif self.path == "/v1/messages":
            if self.headers.get("x-api-key") != "test-key":
                return self._send(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
            msgs = body["messages"]
            if self._check_flaky(msgs):
                return
            self._stream("text/event-stream")
            words = reply_for(msgs)
            ev = lambda d: self.wfile.write(f"event: {d['type']}\ndata: {json.dumps(d)}\n\n".encode())  # noqa: E731
            ev({"type": "message_start", "message": {"model": body["model"]}})
            ev({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
            for i, w in enumerate(words):
                ev({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": w + (" " if i < len(words) - 1 else "")}})
            ev({"type": "content_block_stop", "index": 0})
            ev({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": len(words)}})
            ev({"type": "message_stop"})
        elif self.path == "/v1/chat/completions":
            self._stream("text/event-stream")
            for w in reply_for(body["messages"]):
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': w + ' '}}]})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self._send(404, {"error": "not found"})


def start(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":
    srv, url = start(int(sys.argv[1]) if len(sys.argv) > 1 else 11434)
    print("fake AI server on", url)
    threading.Event().wait()
