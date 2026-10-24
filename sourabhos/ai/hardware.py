"""What the machine can do for AI: CPU, RAM, GPU, disk. Linux-first, safe elsewhere."""
import os
import platform
import shutil
import subprocess
import threading
import time


def _meminfo():
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                k, v = ln.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
    except OSError:
        pass
    return info


def _cpu_times():
    try:
        with open("/proc/stat") as f:
            parts = [int(x) for x in f.readline().split()[1:]]
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
        return idle, sum(parts)
    except (OSError, ValueError, IndexError):
        return None


def _cpu_model():
    try:
        with open("/proc/cpuinfo") as f:
            for ln in f:
                if ln.startswith("model name"):
                    return ln.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _gpus():
    gpus = []
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                 "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=4).stdout
            for ln in out.strip().splitlines():
                name, tot, used, util = [x.strip() for x in ln.split(",")]
                gpus.append({"name": name, "vram": int(tot) * 2**20, "vram_used": int(used) * 2**20,
                             "util": int(util), "compute": True})
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    if not gpus and shutil.which("lspci"):
        try:
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=4).stdout
            for ln in out.splitlines():
                if any(k in ln for k in ("VGA", "3D controller", "Display controller")):
                    name = ln.split(": ", 1)[-1]
                    compute = any(k in name for k in ("NVIDIA", "AMD", "Radeon")) and "Hyper-V" not in name
                    gpus.append({"name": name, "vram": 0, "vram_used": 0, "util": 0, "compute": compute})
        except (OSError, subprocess.SubprocessError):
            pass
    return gpus


class Hardware:
    """Polls in a background thread so the UI never blocks."""

    def __init__(self, interval=2.0):
        self.cpu_model = _cpu_model()
        self.cores = os.cpu_count() or 1
        self.snapshot = {"cpu": 0.0, "ram_total": 0, "ram_used": 0, "gpus": [], "disk_free": 0, "load": 0.0}
        self._prev = _cpu_times()
        self._interval = interval
        self._started = False

    def start(self):
        if not self._started:
            self._started = True
            threading.Thread(target=self._loop, daemon=True, name="hw-poll").start()
        return self

    def poll(self):
        m = _meminfo()
        cur = _cpu_times()
        cpu = 0.0
        if cur and self._prev and cur[1] != self._prev[1]:
            cpu = 1 - (cur[0] - self._prev[0]) / (cur[1] - self._prev[1])
        self._prev = cur
        try:
            load = os.getloadavg()[0]
        except OSError:
            load = 0.0
        try:
            disk_free = shutil.disk_usage(os.path.expanduser("~")).free
        except OSError:
            disk_free = 0
        total = m.get("MemTotal", 0)
        self.snapshot = {"cpu": max(0.0, min(1.0, cpu)), "ram_total": total,
                         "ram_used": total - m.get("MemAvailable", total), "gpus": _gpus(),
                         "disk_free": disk_free, "load": load}
        return self.snapshot

    def _loop(self):
        while True:
            self.poll()
            time.sleep(self._interval)

    def advice(self):
        """Plain-language guidance on which local models fit."""
        s = self.snapshot
        vram = max((g["vram"] for g in s["gpus"] if g["compute"]), default=0)
        ram = s["ram_total"]
        budget = vram or ram * 0.6
        gb = budget / 2**30
        if gb >= 20:
            fit = "up to ~30B parameter models (4-bit)"
        elif gb >= 9:
            fit = "7B–14B models (4-bit)"
        elif gb >= 4.5:
            fit = "3B–8B models (4-bit)"
        elif gb >= 2:
            fit = "1B–3B models"
        else:
            fit = "only tiny models (≤1B); give the VM more RAM"
        where = "GPU" if vram else "CPU"
        return f"{where} inference · {gb:.1f} GB usable → {fit}"


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit not in ("B", "KB") else f"{n:.0f} {unit}"
        n /= 1024
