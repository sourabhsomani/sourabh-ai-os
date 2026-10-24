"""AI layer tests against the fake server. Run:  python3 -m tests.test_ai"""
import csv
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.fake_ai_server import start  # noqa: E402
from sourabhos.ai import AIService, AIError, JobManager  # noqa: E402
from sourabhos.ai.hardware import Hardware  # noqa: E402

SRV, URL = start()


def svc(**kw):
    return AIService({"ollama_url": URL, "anthropic_url": URL, "anthropic_key": "test-key",
                      "openai_url": URL + "/v1", "default_model": "ollama/qwen2.5:0.5b", **kw})


def wait(job, secs=20):
    t = time.time()
    while job.status in ("queued", "running") and time.time() - t < secs:
        time.sleep(0.05)
    return job.status


def test_providers():
    ai = svc()
    toks = []
    r = ai.ask("hello there", on_token=toks.append)
    assert r["text"].startswith("Echo from fake model: hello there"), r
    assert len(toks) > 3 and r["tokens"] > 0
    assert ai.ask("hi", "anthropic/claude-haiku-5-5")["text"].endswith("hi")
    assert ai.ask("yo", "openai/fake-gpt")["text"].strip().endswith("yo")
    refs = [m for m, _ in ai.all_models()]
    assert "ollama/qwen2.5:0.5b" in refs and "anthropic/claude-sonnet-5-5" in refs and "openai/fake-gpt" in refs
    bad = svc(anthropic_key="nope")
    try:
        bad.ask("x", "anthropic/claude-haiku-5-5")
        raise AssertionError("expected auth error")
    except AIError as e:
        assert "401" in str(e)
    try:
        ai.ask("x", "ollama/missing-model")
        raise AssertionError("expected 404")
    except AIError as e:
        assert "not found" in str(e)
    dead = AIService({"ollama_url": "http://127.0.0.1:9"})
    assert not dead.providers["ollama"].available()
    stop = threading.Event()
    stop.set()
    assert ai.ask("stop me", stop=stop)["text"] == ""


def test_pull_delete():
    ai = svc()
    seen = []
    ai.providers["ollama"].pull("phi3:mini", lambda s, c, t: seen.append((s, c, t)))
    assert seen[-1][0] == "success"
    assert any(m["name"] == "phi3:mini" for m in ai.providers["ollama"].models())
    ai.providers["ollama"].delete("phi3:mini")
    assert not any(m["name"] == "phi3:mini" for m in ai.providers["ollama"].models())


def test_jobs_all_input_types():
    home = Path(tempfile.mkdtemp())
    base = home / "work"
    (base / "docs").mkdir(parents=True)
    for i in range(6):
        (base / "docs" / f"doc{i}.txt").write_text(f"document number {i}")
    (base / "lines.txt").write_text("apple\n\nbanana\ncherry FLAKY\n")
    with (base / "rows.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "text", "lang"])
        w.writerow(["a1", "bonjour", "fr"])
        w.writerow(["a2", "hola", "es"])
    ai = svc()
    events = []
    jm = JobManager(home, ai, max_parallel=2, on_event=events.append)
    j1 = jm.submit({"name": "docs", "prompt": "Summarise {name}:\n{input}", "concurrency": 3,
                    "inputs": {"type": "folder", "path": "docs", "glob": "*.txt"}}, base)
    j2 = jm.submit({"name": "lines", "model": "anthropic/claude-haiku-5-5", "prompt": "Fruit: {input}",
                    "retries": 2, "inputs": {"type": "lines", "path": "lines.txt"}}, base)
    j3 = jm.submit({"name": "csv", "model": "openai/fake-gpt", "prompt": "Translate from {lang}: {input}",
                    "inputs": {"type": "csv", "path": "rows.csv", "column": "text", "id_column": "id"}}, base)
    for j in (j1, j2, j3):
        assert wait(j) == "done", (j.name, j.state)
    assert j1.state["done"] == 6 and len(list((j1.dir / "outputs").glob("*.md"))) == 6
    assert j2.state["total"] == 3 and j2.state["done"] == 3, j2.state      # FLAKY item retried
    rows = list(csv.DictReader((j3.dir / "results.csv").open()))
    assert [r["name"] for r in rows] == ["a1", "a2"] and "Translate from fr: bonjour" in rows[0]["output"]
    assert any("queued job" in e for e in events) and any("done" in e for e in events)


def test_failures_pause_resume_and_reboot():
    home = Path(tempfile.mkdtemp())
    ai = svc()
    jm = JobManager(home, ai)
    jf = jm.submit({"name": "fails", "retries": 0, "prompt": "{input}",
                    "inputs": {"type": "list", "items": ["ok one", "ALWAYSFAIL", "ok two"]}}, home)
    wait(jf)
    assert jf.status == "done" and jf.state["failed"] == 1 and jf.state["done"] == 2
    # pause a long job mid-way, then "reboot" (new manager) and check it resumes without redoing work
    import tests.fake_ai_server as fake
    fake.DELAY = 0.03
    items = [f"task {i}" for i in range(40)]
    j = jm.submit({"name": "long", "concurrency": 2, "prompt": "{input}", "inputs": {"type": "list", "items": items}}, home)
    while j.state["done"] < 6:
        time.sleep(0.02)
    jm.pause(j)
    j.thread.join(10)
    assert j.status == "paused", j.status
    done_before = j.state["done"]
    assert 6 <= done_before < 40
    j.state["status"] = "running"       # pretend the machine died while it was running
    j.save_state()
    fake.DELAY = 0.002
    jm2 = JobManager(home, ai)          # boot again
    j2 = jm2.find(j.id)
    assert wait(j2, 30) == "done", j2.state
    names = [json.loads(l)["name"] for l in (j2.dir / "results.jsonl").read_text().splitlines()]
    assert len(names) == len(set(names)) == 40, len(names)   # nothing processed twice
    # cancel
    j3 = jm2.submit({"name": "cancel me", "prompt": "{input}", "inputs": {"type": "list", "items": items}}, home)
    time.sleep(0.05)
    jm2.cancel(j3)
    assert wait(j3) == "cancelled"


def test_cli():
    from sourabhos.ai import cli
    home = Path(tempfile.mkdtemp())
    (home / ".config").mkdir()
    (home / ".config" / "settings.json").write_text(json.dumps({"ai": {"ollama_url": URL}}))
    os.environ["SOURABHOS_HOME"] = str(home)
    job = home / "j.job.json"
    job.write_text(json.dumps({"name": "cli", "prompt": "{input}", "inputs": {"type": "list", "items": ["a", "b"]}}))
    assert cli.main(["ask", "hello", "cli"]) == 0
    assert cli.main(["models"]) == 0
    assert cli.main(["run", str(job)]) == 0
    assert cli.main(["submit", str(job)]) == 0
    assert cli.main(["jobs"]) == 0
    st = [json.loads((d / "state.json").read_text())["status"] for d in sorted((home / "AIJobs/runs").iterdir())]
    assert sorted(st) == ["done", "queued"], st


def test_hardware():
    hw = Hardware()
    s = hw.poll()
    time.sleep(0.1)
    s = hw.poll()
    assert s["ram_total"] > 0 and 0 <= s["cpu"] <= 1
    assert "inference" in hw.advice()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
