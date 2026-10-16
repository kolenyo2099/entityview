"""Local control panel for the pipeline.

    python3 app.py      → open http://127.0.0.1:8765

Settings are saved to config.json; question sets to questions/<name>.txt.
An Anthropic API key typed into the page is kept in memory only, never written to disk.
"""
import json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from pipeline import CANARY_CSV

HERE = Path(__file__).parent
CONFIG = HERE / "config.json"
QDIR = HERE / "questions"
LMSTUDIO_MODELS = "http://localhost:1234/v1/models"
DEFAULTS = {"source": CANARY_CSV, "sheet_url": "", "token": "", "backend": "lmstudio",
            "model": "", "questions_name": "default", "limit": 0}

job = {"proc": None, "log": [], "running": False}
api_key = {"value": os.environ.get("ANTHROPIC_API_KEY", "")}


def load_config():
    return {**DEFAULTS, **(json.loads(CONFIG.read_text()) if CONFIG.exists() else {})}


def qfile(name):
    safe = "".join(c for c in name if c.isalnum() or c in "-_") or "default"
    return QDIR / f"{safe}.txt"


def lmstudio_models():
    try:
        with urlopen(LMSTUDIO_MODELS, timeout=2) as r:
            return [m["id"] for m in json.load(r)["data"] if "embed" not in m["id"]]
    except Exception:
        return None  # server not running


def commands(steps, c):
    limit = ["--limit", str(c["limit"])] if int(c["limit"] or 0) else []
    uv = ["uv", "run", "--quiet"]
    cmds = {
        "extract": uv + ["pipeline.py", "--source", c["source"]] + limit,
        "ask": uv + ["ask.py", str(qfile(c["questions_name"])),
                     "--backend", c["backend"]]
               + (["--model", c["model"]] if c["model"] else []) + limit,
        "push": [sys.executable, "push.py"],
    }
    return [(s, cmds[s]) for s in steps]


def run(steps, c):
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "SHEET_URL": c["sheet_url"], "SHEET_TOKEN": c["token"]}
    if api_key["value"]:
        env["ANTHROPIC_API_KEY"] = api_key["value"]
    log = job["log"]
    try:
        for step, cmd in commands(steps, c):
            log.append(f"\n▶ {step}")
            p = job["proc"] = subprocess.Popen(cmd, cwd=HERE, env=env, text=True,
                                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            for line in p.stdout:
                if "Warning" not in line and "warnings.warn" not in line:
                    log.append(line.rstrip())
            if p.wait() != 0:
                log.append(f"✗ {step} failed (exit {p.returncode}), stopping")
                return
            log.append(f"✓ {step} done")
    finally:
        job["running"], job["proc"] = False, None


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            return self.send(200, (HERE / "ui.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/explorer":
            return self.send(200, (HERE / "explorer.html").read_bytes(), "text/html; charset=utf-8")
        if self.path.startswith("/state"):
            c = load_config()
            qf = qfile(c["questions_name"])
            return self.send(200, {
                "config": c, "questions": qf.read_text("utf-8") if qf.exists() else "",
                "question_sets": sorted(p.stem for p in QDIR.glob("*.txt")),
                "lmstudio_models": lmstudio_models(), "api_key_set": bool(api_key["value"]),
                "running": job["running"], "log": job["log"][-400:]})
        if self.path.startswith("/questions/"):
            qf = qfile(self.path.rsplit("/", 1)[1])
            return self.send(200, {"questions": qf.read_text("utf-8") if qf.exists() else ""})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        # Block other websites from driving this server (CSRF / DNS rebinding): a cross-site JSON POST
        # needs a CORS preflight we never grant, and a rebound hostname fails the Host check.
        if self.headers.get("Host") not in ("127.0.0.1:8765", "localhost:8765") \
                or self.headers.get("Content-Type") != "application/json":
            return self.send(403, {"error": "forbidden"})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
        if self.path == "/save" or self.path == "/run":
            c = {k: body.get(k, v) for k, v in load_config().items()}
            CONFIG.write_text(json.dumps(c, indent=2))
            QDIR.mkdir(exist_ok=True)
            qfile(c["questions_name"]).write_text(body.get("questions", ""), "utf-8")
            if body.get("api_key"):
                api_key["value"] = body["api_key"]
            if self.path == "/save":
                return self.send(200, {"ok": True})
            if job["running"]:
                return self.send(409, {"error": "a run is already in progress"})
            steps = [s for s in body.get("steps", []) if s in ("extract", "ask", "push")]
            job.update(running=True, log=[])
            threading.Thread(target=run, args=(steps, c), daemon=True).start()
            return self.send(200, {"ok": True})
        if self.path == "/stop":
            if job["proc"]:
                job["proc"].terminate()
                job["log"].append("■ stopped")
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("Control panel: http://127.0.0.1:8765")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()  # localhost only
