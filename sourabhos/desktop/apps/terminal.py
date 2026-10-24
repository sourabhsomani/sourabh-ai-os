import datetime
import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path

import pygame

from ..theme import C, font, text
from ..ui import App, LineEdit

HELP = """\
Sourabh OS shell — commands
  AI        ai <question>   (streams an answer; ai -m <model> <question>)
            models  pull <model>  jobs  job run <file.job.json>
            job pause|resume|cancel <id>   (also: sourabh-ai in any Linux shell)
  files     ls [dir]  cd <dir>  pwd  cat <file>  mkdir <dir>  touch <file>
            rm <path>  cp <a> <b>  mv <a> <b>  edit <file>  open <app>
  TinyVM    run <prog> [prog…]  ps  kill <pid>  input <n>  vm  pause  resume
            reset  asm <file>  (disassemble)
  web       chrome [url]   install-chrome   install-ai-engine
  system    date  uptime  uname  whoami  sysinfo  echo <text>  history
            clear  theme <name>  sh <linux command>  shutdown  reboot  exit
Tip: Up/Down = history, Tab = complete, Ctrl+L = clear, Ctrl+C = cancel line"""


class Terminal(App):
    title = "Terminal"
    icon = "terminal"
    size = (760, 460)

    def __init__(self, desk, **kw):
        super().__init__(desk, **kw)
        self.cwd = self.sys.home
        self.lines = []
        self.edit = LineEdit()
        self.scroll = 0
        self.say("Sourabh OS terminal — type 'help' for commands", C["accent"])
        self.sys.listeners.append(self._from_kernel)

    def on_close(self):
        if self._from_kernel in self.sys.listeners:
            self.sys.listeners.remove(self._from_kernel)

    def _from_kernel(self, line):
        col = C["danger"] if "FAULT" in line else (C["warn"] if line.startswith("[kernel]") else C["ok"])
        self.say(line, col)

    def say(self, s, color=None):
        for ln in str(s).split("\n"):
            self.lines.append((ln.expandtabs(4), color or C["text"]))
        del self.lines[:-2000]
        self.scroll = 0

    def prompt(self):
        try:
            rel = "~/" + str(self.cwd.relative_to(self.sys.home))
            rel = "~" if rel == "~/." else rel
        except ValueError:
            rel = str(self.cwd)
        return f"sourabh@sourabh-os:{rel}$ "

    def path(self, p):
        p = Path(os.path.expanduser(p.replace("~", str(self.sys.home), 1) if p.startswith("~") else p))
        return p if p.is_absolute() else (self.cwd / p).resolve()

    # ---------------- input
    def on_text(self, s):
        self.edit.on_text(s)

    def on_key(self, ev):
        ctrl = ev.mod & pygame.KMOD_CTRL
        if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            cmd = self.edit.commit()
            self.say(self.prompt() + cmd, C["dim"])
            self.execute(cmd)
        elif ctrl and ev.key == pygame.K_l:
            self.lines.clear()
        elif ctrl and ev.key == pygame.K_c:
            self.say(self.prompt() + self.edit.text + "^C", C["dim"])
            self.edit.text, self.edit.cur = "", 0
        elif ev.key == pygame.K_TAB:
            self.complete()
        elif ev.key == pygame.K_PAGEUP:
            self.scroll += 10
        elif ev.key == pygame.K_PAGEDOWN:
            self.scroll = max(0, self.scroll - 10)
        else:
            self.edit.on_key(ev)

    def on_wheel(self, dy, pos):
        self.scroll = max(0, self.scroll + dy * 3)

    def complete(self):
        parts = self.edit.text.split(" ")
        frag = parts[-1]
        base = self.path(os.path.dirname(frag) or ".")
        stem = os.path.basename(frag)
        try:
            names = [n for n in os.listdir(base) if n.startswith(stem)]
        except OSError:
            return
        if len(names) == 1:
            add = names[0][len(stem):] + ("/" if (base / names[0]).is_dir() else " ")
            self.edit.on_text(add)
        elif names:
            self.say("  ".join(sorted(names)), C["dim"])

    # ---------------- commands
    def execute(self, line):
        line = line.strip()
        if not line:
            return
        try:
            args = shlex.split(line)
        except ValueError as e:
            self.say(f"parse error: {e}", C["danger"])
            return
        cmd, a = args[0], args[1:]
        fn = getattr(self, "cmd_" + cmd.replace("-", "_"), None)
        if fn is None:
            self.say(f"{cmd}: command not found (try 'help')", C["danger"])
            return
        try:
            fn(a)
        except (OSError, ValueError, IndexError, KeyError) as e:
            self.say(f"{cmd}: {e}", C["danger"])

    def cmd_help(self, a): self.say(HELP)
    def cmd_clear(self, a): self.lines.clear()
    def cmd_pwd(self, a): self.say(str(self.cwd))
    def cmd_echo(self, a): self.say(" ".join(a))
    def cmd_whoami(self, a): self.say("sourabh")
    def cmd_date(self, a): self.say(datetime.datetime.now().strftime("%A %d %B %Y, %H:%M:%S"))
    def cmd_uptime(self, a): self.say("up " + self.sys.uptime())
    def cmd_exit(self, a): self.close()
    def cmd_history(self, a):
        for i, h in enumerate(self.edit.history, 1):
            self.say(f"{i:4}  {h}")

    def cmd_uname(self, a):
        self.say(f"Sourabh OS 1.0 (Python {platform.python_version()}) on {platform.system()} {platform.release()} {platform.machine()}")

    def cmd_sysinfo(self, a):
        w, h = self.desk.screen.get_size()
        self.say(f"OS        Sourabh OS 1.0\nKernel    TinyVM (host: {platform.system()} {platform.release()})\n"
                 f"Python    {platform.python_version()}  pygame {pygame.version.ver}\n"
                 f"Display   {w}x{h}\nHome      {self.sys.home}\nUptime    {self.sys.uptime()}")

    def cmd_ls(self, a):
        p = self.path(a[0]) if a else self.cwd
        if p.is_file():
            self.say(p.name)
            return
        items = sorted(p.iterdir(), key=lambda q: (not q.is_dir(), q.name.lower()))
        for q in items:
            if q.name.startswith("."):
                continue
            if q.is_dir():
                self.say(f"  {q.name}/", C["accent"])
            else:
                col = C["ok"] if q.suffix in (".tvm", ".txt") and q.parent.name == "Programs" else C["text"]
                self.say(f"  {q.name:<28} {q.stat().st_size:>8} B", col)

    def cmd_cd(self, a):
        p = self.path(a[0]) if a else self.sys.home
        if not p.is_dir():
            raise ValueError(f"no such directory: {a[0]}")
        self.cwd = p

    def cmd_cat(self, a):
        self.say(self.path(a[0]).read_text(errors="replace"))

    def cmd_mkdir(self, a): self.path(a[0]).mkdir(parents=True, exist_ok=True)
    def cmd_touch(self, a): self.path(a[0]).touch()
    def cmd_cp(self, a): shutil.copy(self.path(a[0]), self.path(a[1]))
    def cmd_mv(self, a): shutil.move(self.path(a[0]), self.path(a[1]))

    def cmd_rm(self, a):
        p = self.path(a[0])
        shutil.rmtree(p) if p.is_dir() else p.unlink()

    def cmd_edit(self, a):
        self.desk.open_by_name("Editor", path=self.path(a[0]) if a else None)

    def cmd_open(self, a):
        if not self.desk.open_by_name(" ".join(a)):
            self.say("apps: " + ", ".join(c.title for c in self.desk.app_list), C["danger"])

    def cmd_theme(self, a):
        from ..theme import THEMES
        if not a or a[0] not in THEMES:
            self.say("themes: " + ", ".join(THEMES))
            return
        self.sys.settings["theme"] = a[0]
        self.sys.save()
        self.desk.apply_theme()

    # ---- TinyVM
    def _find_prog(self, name):
        for cand in (self.path(name), self.sys.home / "Programs" / name,
                     self.sys.home / "Programs" / (name + ".tvm")):
            if cand.is_file():
                return cand
        raise ValueError(f"program not found: {name}")

    def cmd_run(self, a):
        if not a:
            self.say("usage: run <program> [program…]   e.g. run hello.tvm")
            return
        for name in a:
            self.say(self.sys.run_program(self._find_prog(name)), C["accent"])
        self.sys.vm_running = True

    def cmd_asm(self, a):
        from ...core.vm import assemble
        ip = 0
        for ins in assemble(self._find_prog(a[0]).read_text()):
            self.say(f"  {ip:04x}  {str(ins)}")
            ip += ins.size

    def cmd_ps(self, a):
        vm = self.sys.vm
        self.say(f"  {'PID':>3}  {'NAME':<14} {'STATE':<10} {'PRI':>3} {'IP':>5} {'CYCLES':>7} {'FAULTS':>6}", C["dim"])
        for p in vm.procs.values():
            col = C["dim"] if p.state == "terminated" else C["text"]
            self.say(f"  {p.pid:>3}  {p.name[:14]:<14} {p.state:<10} {p.priority:>3} {p.ip:>5} {p.cycles:>7} {p.page_faults:>6}", col)
        if not vm.procs:
            self.say("  (no processes — try 'run hello.tvm')", C["dim"])

    def cmd_kill(self, a):
        pid = int(a[0])
        self.say("killed" if self.sys.vm.kill(pid) else f"no running process {pid}")

    def cmd_input(self, a):
        self.sys.vm.feed_input(int(a[0]))
        self.say(f"queued input {a[0]}")

    def cmd_vm(self, a):
        vm, c = self.sys.vm, self.sys.vm.cfg
        used = sum(1 for o in vm.frame_owner if o)
        self.say(f"clock {vm.clock}   frames {used}/{vm.nframes} used   swap pages {len(vm.swap)}")
        self.say("   ".join(f"{k} {v}" for k, v in vm.stats.items()))
        self.say(f"RAM {c.physical_memory}B  page {c.page_size}B  proc {c.process_memory}B  quantum {c.quantum}")

    def cmd_pause(self, a): self.sys.vm_running = False
    def cmd_resume(self, a): self.sys.vm_running = True

    def cmd_reset(self, a):
        self.sys.new_vm()

    def cmd_sh(self, a):
        if not a:
            self.say("usage: sh <command>   (runs a real Linux command, 10s limit)")
            return
        r = subprocess.run(" ".join(a), shell=True, cwd=self.cwd, capture_output=True, text=True, timeout=10)
        if r.stdout:
            self.say(r.stdout.rstrip("\n"))
        if r.stderr:
            self.say(r.stderr.rstrip("\n"), C["danger"])

    # ---- AI
    def cmd_ai(self, a):
        import threading
        from ...ai import AIError
        model = None
        if len(a) >= 2 and a[0] in ("-m", "--model"):
            model, a = a[1], a[2:]
        if not a:
            self.say("usage: ai <question>      e.g. ai explain demand paging in 3 lines")
            return
        line = {"text": "", "n": 1}
        self.lines.append(("", C["text"]))
        idx = len(self.lines) - 1

        def tok(t):
            # rewrite only this answer's own lines (other output may follow it)
            line["text"] += t
            parts = [(p, C["text"]) for p in line["text"].split("\n")]
            self.lines[idx:idx + line["n"]] = parts
            line["n"] = len(parts)

        def work():
            try:
                r = self.sys.ai.ask(" ".join(a), model, on_token=tok)
                self.say(f"[{r['model']} · {r['tokens']} tokens · {r.tokens_per_s:.1f} tok/s]", C["dim"])
            except AIError as e:
                self.say(f"ai: {e}", C["danger"])
        threading.Thread(target=work, daemon=True).start()

    def cmd_models(self, a):
        rows = self.sys.ai.all_models()
        d = self.sys.ai.settings["default_model"]
        for ref, m in rows:
            self.say(f"  {'*' if ref == d else ' '} {ref:<40} {m.get('params', '')}", C["ok"] if ref == d else C["text"])
        if not rows:
            self.say("no models — 'pull qwen2.5:0.5b' or add an API key in the Models app", C["warn"])

    def cmd_pull(self, a):
        import threading
        from ...ai import AIError
        name = a[0]
        self.say(f"downloading {name}…", C["accent"])

        def work():
            last = [""]
            def prog(st, done, total):
                msg = f"  {st} {done * 100 // total}%" if total else f"  {st}"
                if msg.split()[0] != last[0] or (total and done == total):
                    last[0] = msg.split()[0]
                    self.say(msg, C["dim"])
            try:
                self.sys.ai.providers["ollama"].pull(name, prog)
                self.say(f"{name} ready", C["ok"])
            except AIError as e:
                self.say(f"pull: {e}", C["danger"])
            self.sys.refresh_ai()
        threading.Thread(target=work, daemon=True).start()

    def cmd_jobs(self, a):
        if not self.sys.jobs.jobs:
            self.say("no jobs — try: job run ~/SourabhHome/AIJobs/examples/summarise-docs.job.json", C["dim"])
        for j in self.sys.jobs.jobs:
            st = j.state
            self.say(f"  {j.id[:24]:<24} {j.status:<9} {st['done']:>4}/{st['total']:<4} {j.name}")

    def cmd_job(self, a):
        if not a:
            self.say("usage: job run <file.job.json> | job pause|resume|cancel <id>")
            return
        jm = self.sys.jobs
        if a[0] == "run":
            job = jm.submit_file(self.path(a[1]))
            self.say(f"queued {job.id} ({job.state['total']} items) — watch it in AI Jobs", C["accent"])
            return
        job = jm.find(a[1]) if len(a) > 1 else None
        if not job:
            raise ValueError("no such job")
        {"pause": jm.pause, "resume": jm.resume, "cancel": jm.cancel}[a[0]](job)
        self.say(f"{job.name}: {job.status}")

    # ---- web
    def cmd_chrome(self, a):
        from .browser import Chrome
        Chrome.launch(self.desk, a[0] if a else None)

    def cmd_install_chrome(self, a):
        import threading
        import os
        from ...extapps import install_chrome, find_browser, INSTALLER
        if find_browser():
            self.say("Chrome is already installed — type 'chrome' or click the Chrome icon.", C["ok"])
            return
        if not os.path.exists(INSTALLER):
            self.say("install-chrome works inside the Sourabh OS image (VM or installed PC).", C["warn"])
            self.say("On this computer, install Chrome from https://www.google.com/chrome/ — the Chrome icon will then open it.")
            return
        self.say("Installing Google Chrome (downloads ~120 MB)…", C["accent"])

        def work():
            ok = install_chrome(lambda ln: self.say("  " + ln, C["dim"]))
            self.say("Chrome installed — click the Chrome icon or type 'chrome'." if ok
                     else "install-chrome failed (check the internet connection)", C["ok"] if ok else C["danger"])
        threading.Thread(target=work, daemon=True).start()

    def cmd_install_ai_engine(self, a):
        import os
        import threading
        from ...extapps import run_installer, AI_ENGINE_INSTALLER
        if not os.path.exists(AI_ENGINE_INSTALLER):
            self.say("install-ai-engine works inside the Sourabh OS image.", C["warn"])
            self.say("On this computer, install Ollama from https://ollama.com/download")
            return
        self.say("Installing the local AI engine (Ollama)…", C["accent"])

        def work():
            ok = run_installer(AI_ENGINE_INSTALLER, lambda ln: self.say("  " + ln, C["dim"]))
            self.say("AI engine ready — open Models to download a model." if ok
                     else "install-ai-engine failed (check the internet connection)", C["ok"] if ok else C["danger"])
            self.sys.refresh_ai()
        threading.Thread(target=work, daemon=True).start()

    def cmd_shutdown(self, a): self.desk.power("shutdown")
    def cmd_reboot(self, a): self.desk.power("reboot")

    # ---------------- drawing
    def draw(self, s):
        s.fill(C["field"])
        f = font("mono", 14)
        lh = f.get_linesize()
        w, h = s.get_size()
        cols = max(10, (w - 20) // max(1, f.size("M")[0]))
        wrapped = []
        for ln, col in self.lines:
            while len(ln) > cols:
                wrapped.append((ln[:cols], col))
                ln = ln[cols:]
            wrapped.append((ln, col))
        rows = (h - 16) // lh
        self.scroll = min(self.scroll, max(0, len(wrapped) + 1 - rows))
        visible = wrapped[max(0, len(wrapped) + 1 - rows - self.scroll): len(wrapped) - self.scroll]
        y = 8
        for ln, col in visible:
            text(s, ln, (10, y), col, "mono", 14)
            y += lh
        if self.scroll == 0:
            self.edit.draw(s, (10, y), prefix=self.prompt())
        else:
            text(s, f"-- scrolled {self.scroll} lines (wheel/PgDn) --", (10, h - lh - 6), C["warn"], "mono", 13)
