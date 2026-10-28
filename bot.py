#!/usr/bin/env python3
"""YeNo paper-only AProbe submission endpoint."""
import json
import math
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from yeno_evaluator.a_probe import AProbeBot

bot = AProbeBot()
mutex = Lock()

def decide(obs):
    if not isinstance(obs, dict) or not isinstance(obs.get("account"), dict):
        return {"action": "HOLD"}
    with mutex:
        action = bot(obs)
    kind = action.get("action")
    if kind == "BUY":
        try:
            cash = float(action["maxCashUsd"])
            cap = min(5., float(obs["account"]["cashUsd"]), float(obs["rules"]["maximumBuyCashUsd"]))
            if (math.isfinite(cash) and math.isfinite(cap)
                    and action.get("outcome") in ("YES", "NO") and 0 < cash <= cap):
                return {"action": "BUY", "outcome": action["outcome"], "maxCashUsd": cash}
        except (KeyError, ValueError, TypeError):
            pass
    if kind == "SELL" and obs.get("account", {}).get("position") is not None:
        return {"action": "SELL"}
    return {"action": "HOLD"}

class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body):
        payload = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path != "/decide":
            return self.reply(404, {"error": "not found"})
        try:
            size = int(self.headers.get("Content-Length", "-1"))
            if not 0 < size <= 1000000:
                return self.reply(413, {"error": "invalid size"})
            return self.reply(200, decide(json.loads(self.rfile.read(size))))
        except (ValueError, UnicodeDecodeError, TypeError):
            return self.reply(400, {"error": "invalid JSON"})

    def do_GET(self):
        return self.reply(200, {"status": "ok"}) if self.path == "/health" else self.reply(404, {"error": "not found"})

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    ThreadingHTTPServer((os.environ.get("YENO_BIND", "127.0.0.1"),
                         int(os.environ.get("YENO_PORT", "8765"))), Handler).serve_forever()
