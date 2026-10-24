"""sourabh-ai: command-line access to the Sourabh OS AI layer.

  sourabh-ai ask "Explain paging in one paragraph"
  echo "some text" | sourabh-ai ask -m anthropic/claude-haiku-5-5 "Summarise:" -
  sourabh-ai models
  sourabh-ai pull qwen2.5:0.5b
  sourabh-ai run ~/AIJobs/examples/summarise-docs.job.json     # runs, shows progress
  sourabh-ai submit job.json        # queue it for the desktop's job runner
  sourabh-ai jobs                   # list runs and their status
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from .providers import AIService, AIError, DEFAULT_AI_SETTINGS
from .jobs import JobManager, DONE, FAILED, CANCELLED, PAUSED


def home():
    return Path(os.environ.get("SOURABHOS_HOME") or Path.home() / "SourabhHome")


def load_settings():
    try:
        data = json.loads((home() / ".config" / "settings.json").read_text())
        return {**DEFAULT_AI_SETTINGS, **data.get("ai", {})}
    except (OSError, ValueError):
        return dict(DEFAULT_AI_SETTINGS)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sourabh-ai", description="Sourabh OS AI command line")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask", help="ask a model (streams the answer)")
    a.add_argument("-m", "--model")
    a.add_argument("-s", "--system")
    a.add_argument("prompt", nargs="+", help="use '-' to append stdin")
    sub.add_parser("models", help="list models from every provider")
    p = sub.add_parser("pull", help="download a local model")
    p.add_argument("model")
    r = sub.add_parser("run", help="run a job file now and wait")
    r.add_argument("jobfile")
    r.add_argument("-m", "--model", help="override the job's model")
    s = sub.add_parser("submit", help="queue a job file (runs in the desktop)")
    s.add_argument("jobfile")
    sub.add_parser("jobs", help="list job runs")
    args = ap.parse_args(argv)

    ai = AIService(load_settings())
    try:
        if args.cmd == "ask":
            parts = [x for x in args.prompt if x != "-"]
            prompt = " ".join(parts)
            if "-" in args.prompt:
                prompt += "\n\n" + sys.stdin.read()
            res = ai.ask(prompt, args.model, args.system,
                         on_token=lambda t: (sys.stdout.write(t), sys.stdout.flush()))
            print(f"\n\n[{res['model']} · {res['tokens']} tokens · {res.tokens_per_s:.1f} tok/s]", file=sys.stderr)
        elif args.cmd == "models":
            rows = ai.all_models()
            if not rows:
                print("no models — try: sourabh-ai pull qwen2.5:0.5b  (or add an API key in Models)")
            for ref, m in rows:
                size = f"{m['size'] / 2**30:.1f} GB" if m["size"] else ""
                print(f"{ref:<44} {m['params']:>8} {size:>9}")
        elif args.cmd == "pull":
            def prog(status, done, total):
                bar = f" {done * 100 // total:3d}%" if total else ""
                print(f"\r{status[:50]:<50}{bar}", end="", flush=True)
            ai.providers["ollama"].pull(args.model, prog)
            print("\ndone")
        elif args.cmd in ("run", "submit"):
            jm = JobManager(home(), ai, on_event=lambda m: print(m, file=sys.stderr), autostart=False)
            path = Path(args.jobfile).expanduser().resolve()
            spec = json.loads(path.read_text())
            if getattr(args, "model", None):
                spec["model"] = args.model
            if args.cmd == "submit":
                job = JobManager(home(), ai, autostart=False).submit(spec, base=path.parent)
                print(f"queued {job.id} — it starts in the AI Jobs app")
                return 0
            job = jm.submit(spec, base=path.parent)
            jm.start_now(job)
            while job.status not in (DONE, FAILED, CANCELLED, PAUSED):
                st = job.state
                print(f"\r{job.name}: {st['done']}/{st['total']} done, {st['failed']} failed, "
                      f"{st['tokens']} tokens", end="", flush=True)
                time.sleep(0.5)
            print(f"\n{job.status}. results: {job.dir}")
            return 0 if job.status == DONE else 1
        elif args.cmd == "jobs":
            root = home() / "AIJobs" / "runs"
            for d in sorted(root.glob("*")) if root.exists() else []:
                try:
                    st = json.loads((d / "state.json").read_text())
                    spec = json.loads((d / "job.json").read_text())
                except (OSError, ValueError):
                    continue
                print(f"{d.name:<46} {st['status']:<10} {st['done']}/{st['total']}  {spec.get('model', '')}")
    except AIError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
