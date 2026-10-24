"""System services: settings, user home, the shared TinyVM 'kernel', power."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .core.vm import TinyVM, Config, VMFault, AssemblyError
from .ai import AIService, JobManager, Hardware, DEFAULT_AI_SETTINGS

PKG_DIR = Path(__file__).resolve().parent
PROGRAMS_SRC = PKG_DIR.parent / "programs"
AI_EXAMPLES_SRC = PKG_DIR.parent / "ai-examples"
VERSION = "1.0"


def is_appliance() -> bool:
    """True when running as the OS shell inside the bootable image."""
    return os.environ.get("SOURABHOS_SYSTEM") == "1"


class System:
    def __init__(self, home: str | None = None):
        self.home = Path(home or os.environ.get("SOURABHOS_HOME") or Path.home() / "SourabhHome")
        self.cfg_path = self.home / ".config" / "settings.json"
        self.settings = {"theme": "Midnight", "vm_speed": 60, "clock_24h": True,
                         "vm": Config().__dict__.copy(), "ai": dict(DEFAULT_AI_SETTINGS)}
        self.listeners = []          # callables(line: str)
        self.console: list[str] = []  # recent VM/system output
        self.boot_time = time.time()
        self._first_run()
        self._load()
        self.vm_running = True
        self.new_vm()
        # ---- AI layer
        self.ai = AIService(self.settings["ai"])
        self.jobs = JobManager(self.home, self.ai, on_event=self.emit)
        self.hw = Hardware().start()
        self.ai_status = {"local": False, "checked": 0.0, "models": [], "version": ""}
        self.refresh_ai(background=True)

    # ---------------- AI status (polled in a thread so the UI never blocks)
    def refresh_ai(self, background=True):
        import threading

        def work():
            ok = self.ai.providers["ollama"].available()
            models = self.ai.all_models()
            self.ai_status.update(local=ok, models=models, checked=time.time(),
                                  version=self.ai.providers["ollama"].version() if ok else "")
        if background:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    def ai_ready(self):
        return bool(self.ai_status["models"])

    # ---------------- persistence
    def _first_run(self):
        for d in ("Documents", "Programs", ".config", "AIJobs/inputs"):
            (self.home / d).mkdir(parents=True, exist_ok=True)
        if AI_EXAMPLES_SRC.is_dir():
            dst = self.home / "AIJobs" / "examples"
            if not dst.exists():
                shutil.copytree(AI_EXAMPLES_SRC, dst)
        dst = self.home / "Programs"
        if PROGRAMS_SRC.is_dir():
            for f in PROGRAMS_SRC.glob("*"):
                if f.is_file() and not (dst / f.name).exists():
                    shutil.copy(f, dst / f.name)
        readme = self.home / "Documents" / "welcome.txt"
        if not readme.exists():
            readme.write_text(
                "Welcome to Sourabh OS — the operating system for AI work!\n\n"
                "AI\n"
                "• AI Chat: talk to a local model (Ollama) or Claude / any OpenAI-compatible API.\n"
                "• AI Jobs: run one prompt over hundreds of files, lines or CSV rows, in parallel.\n"
                "  Examples are in AIJobs/examples. Results land in AIJobs/runs.\n"
                "• Models: download local models, add API keys, see your CPU/GPU/RAM.\n"
                "• Terminal: 'ai <question>', 'models', 'pull <model>', 'jobs', 'job run <file>'.\n"
                "• Command line / SSH: sourabh-ai ask|models|pull|run|submit|jobs\n\n"
                "TinyVM (learn how an OS works)\n"
                "• Open the Terminal and type 'help'.\n"
                "• Programs/ holds TinyVM assembly programs. Try:\n"
                "      run hello.tvm\n"
                "      run producer.tvm consumer.tvm\n"
                "• Open the VM Monitor to watch paging, the scheduler and registers live.\n"
                "• Double-click a .tvm file in Files to run it.\n")

    def _load(self):
        try:
            data = json.loads(self.cfg_path.read_text())
            vm = {**self.settings["vm"], **data.get("vm", {})}
            ai = {**self.settings["ai"], **data.get("ai", {})}
            self.settings.update(data)
            self.settings["vm"] = vm
            self.settings["ai"] = ai
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            self.cfg_path.write_text(json.dumps(self.settings, indent=2))
            os.chmod(self.cfg_path, 0o600)   # holds API keys
        except OSError as e:
            self.emit(f"[system] could not save settings: {e}")

    # ---------------- console bus
    def emit(self, line: str):
        self.console.append(line)
        del self.console[:-500]
        for fn in list(self.listeners):
            fn(line)

    # ---------------- kernel
    def new_vm(self):
        known = Config().__dict__.keys()
        cfg = Config(**{k: v for k, v in self.settings["vm"].items() if k in known})
        self.vm = TinyVM(cfg, output=self._vm_out, log=lambda m: None)
        self.emit(f"[kernel] TinyVM ready: {cfg.physical_memory}B RAM, "
                  f"{cfg.page_size}B pages, {cfg.process_memory}B per process")

    def _vm_out(self, pid, txt):
        p = self.vm.procs.get(pid)
        self.emit(f"[{pid}:{p.name if p else '?'}] {txt}")

    def run_program(self, path: str | Path) -> str:
        path = Path(path)
        try:
            p = self.vm.load(path.read_text(), path.name)
            return f"started {path.name} as pid {p.pid}"
        except (OSError, VMFault, AssemblyError, UnicodeDecodeError) as e:
            return f"error: {e}"

    def tick(self, dt: float):
        """Called every frame: housekeeping + a slice of VM instructions."""
        now = time.time()
        if now - getattr(self, "_last_scan", 0) > 2:
            self._last_scan = now
            self.jobs.rescan()
        if now - self.ai_status["checked"] > 15:
            self.ai_status["checked"] = now
            self.refresh_ai()
        if not self.vm_running or not self.vm.alive:
            return
        n = max(1, int(self.settings["vm_speed"] * dt * 10))
        for _ in range(n):
            if not self.vm.tick():
                break

    # ---------------- power
    def power(self, action: str):
        """action: shutdown | reboot. Returns False if only the app should quit."""
        if not is_appliance():
            return False
        cmd = {"shutdown": "poweroff", "reboot": "reboot"}[action]
        subprocess.Popen(["sudo", "-n", "/usr/bin/systemctl", cmd])
        return True

    def uptime(self):
        s = int(time.time() - self.boot_time)
        return f"{s // 3600}h {s // 60 % 60}m {s % 60}s"
