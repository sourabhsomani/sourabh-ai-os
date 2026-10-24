import pygame

from ..theme import C, PID_COLORS, font, rrect, text, lighten
from ..ui import App


class Monitor(App):
    title = "VM Monitor"
    icon = "monitor"
    size = (980, 620)
    min_size = (720, 460)
    single = True

    def __init__(self, desk, **kw):
        super().__init__(desk, **kw)
        self.sel = None
        self.picker = False
        self.out = []
        self.sys.listeners.append(self._out)
        self.ips_hist = []
        self._last_instr = self.sys.vm.stats["instructions"]
        self._acc = 0

    def on_close(self):
        if self._out in self.sys.listeners:
            self.sys.listeners.remove(self._out)

    def _out(self, line):
        self.out.append(line)
        del self.out[:-300]

    def update(self, dt):
        self._acc += dt
        if self._acc >= .5:
            n = self.sys.vm.stats["instructions"]
            self.ips_hist.append(max(0, (n - self._last_instr) / self._acc))
            self.ips_hist = self.ips_hist[-60:]
            self._last_instr, self._acc = n, 0

    # ---------------- actions
    def toggle(self): self.sys.vm_running = not self.sys.vm_running

    def step(self):
        self.sys.vm_running = False
        self.sys.vm.tick()

    def speed(self, f):
        v = self.sys.settings["vm_speed"]
        self.sys.settings["vm_speed"] = int(max(1, min(2000, v * f)))

    def reset(self):
        self.sys.new_vm()
        self.sel = None
        self.out.clear()

    def kill(self):
        if self.sel:
            self.sys.vm.kill(self.sel)

    def load(self, path):
        self.picker = False
        self.desk.toast(self.sys.run_program(path))
        self.sys.vm_running = True

    def on_click(self, pos, button, double=False):
        if self.picker:
            self.picker = False

    # ---------------- drawing
    def draw(self, s):
        vm = self.sys.vm
        W, H = s.get_size()
        # toolbar
        pygame.draw.rect(s, C["panel"], (0, 0, W, 46))
        x = 10
        x = self.btn(s, (x, 8, 96, 30), "Pause" if self.sys.vm_running else "Run", self.toggle, "accent").right + 6
        x = self.btn(s, (x, 8, 64, 30), "Step", self.step).right + 6
        x = self.btn(s, (x, 8, 34, 30), "−", lambda: self.speed(.5)).right + 4
        text(s, f"{self.sys.settings['vm_speed'] * 10} ips", (x + 4, 23), C["dim"], "mono", 12, "midleft")
        x += 78
        x = self.btn(s, (x, 8, 34, 30), "+", lambda: self.speed(2)).right + 14
        x = self.btn(s, (x, 8, 126, 30), "Load program…", lambda: setattr(self, "picker", not self.picker)).right + 6
        x = self.btn(s, (x, 8, 64, 30), "Kill", self.kill, "danger", enabled=bool(self.sel)).right + 6
        self.btn(s, (x, 8, 64, 30), "Reset", self.reset)
        st = vm.stats
        text(s, f"clock {vm.clock}  faults {st['page_faults']}  swap out/in {st['swap_outs']}/{st['swap_ins']}  "
                f"ctx {st['context_switches']}", (W - 10, 23), C["dim"], "mono", 12, "midright")

        left = pygame.Rect(10, 56, int(W * .5) - 15, H - 66)
        right = pygame.Rect(left.right + 10, 56, W - left.right - 20, H - 66)

        # process table
        tbl = pygame.Rect(left.x, left.y, left.w, int(left.h * .42))
        self._panel(s, tbl, "Processes")
        hdr = ["PID", "NAME", "STATE", "PRI", "IP", "CYC", "PF"]
        xs = [10, 46, 160, 250, 290, 336, 390]
        for hx, hd in zip(xs, hdr):
            text(s, hd, (tbl.x + hx, tbl.y + 30), C["dim"], "bold", 11)
        y = tbl.y + 48
        for p in list(vm.procs.values())[-((tbl.h - 52) // 22):]:
            row = pygame.Rect(tbl.x + 4, y - 3, tbl.w - 8, 21)
            if p.pid == self.sel:
                rrect(s, lighten(C["panel"], 18), row, 4)
            self._hits.append((row, lambda pid=p.pid: setattr(self, "sel", pid)))
            col = PID_COLORS[p.pid % len(PID_COLORS)]
            pygame.draw.circle(s, col, (tbl.x + 8, y + 7), 4)
            dim = p.state == "terminated"
            sc = {"running": C["ok"], "ready": C["text"], "sleeping": C["warn"],
                  "blocked": C["danger"], "terminated": C["dim"]}[p.state]
            vals = [p.pid, p.name, p.state, p.priority, p.ip, p.cycles, p.page_faults]
            for vx, v in zip(xs, vals):
                text(s, v, (tbl.x + vx + (6 if vx == 10 else 0), y), sc if v == p.state else (C["dim"] if dim else C["text"]),
                     "mono", 12, maxw=110)
            y += 22
        if not vm.procs:
            text(s, "No processes. Click 'Load program…'", (tbl.x + 12, tbl.y + 54), C["dim"], "sans", 13)

        # cpu / registers of selected
        cpu = pygame.Rect(left.x, tbl.bottom + 10, left.w, left.bottom - tbl.bottom - 10)
        p = vm.procs.get(self.sel)
        self._panel(s, cpu, f"CPU · pid {p.pid} {p.name}" if p else "CPU · select a process")
        if p:
            for i in range(1, 11):
                cx = cpu.x + 12 + ((i - 1) % 5) * (cpu.w - 20) // 5
                cy = cpu.y + 30 + ((i - 1) // 5) * 22
                text(s, f"r{i:<2}", (cx, cy), C["dim"], "mono", 12)
                text(s, p.regs[i], (cx + 28, cy), C["text"], "mono", 12, maxw=(cpu.w - 20) // 5 - 32)
            fy = cpu.y + 78
            text(s, f"ip {p.ip}   sp {p.sp}   sign {int(p.sign)}   zero {int(p.zero)}   "
                    f"wait {p.wait_kind or '-'} {p.wait_obj if p.wait_kind else ''}",
                 (cpu.x + 12, fy), C["accent"], "mono", 12)
            # disassembly with current ip
            y = fy + 24
            ip = 0
            lines = []
            for ins in p.instrs:
                lines.append((ip, ins))
                ip += ins.size
            idx = next((k for k, (a, _) in enumerate(lines) if a == p.ip), 0)
            rows = max(1, (cpu.bottom - y - 6) // 18)
            start = max(0, min(idx - rows // 2, len(lines) - rows))
            for a, ins in lines[start:start + rows]:
                cur = a == p.ip and p.state != "terminated"
                if cur:
                    rrect(s, (*C["accent"][:3],), (cpu.x + 6, y - 2, cpu.w - 12, 18), 4)
                col = (16, 18, 24) if cur else C["text"]
                text(s, f"{a:04x}  {str(ins)}", (cpu.x + 12, y), col, "mono", 12, maxw=cpu.w * .55)
                cm = ins.source.split(";", 1)[1].strip() if ";" in ins.source else ""
                if cm:
                    text(s, "; " + cm, (cpu.x + cpu.w * .58, y), col if cur else C["dim"], "mono", 11, maxw=cpu.w * .4)
                y += 18
            if p.exit_reason:
                text(s, f"exit: {p.exit_reason}", (cpu.right - 10, cpu.y + 8), C["dim"], "sans", 12, "topright")

        # physical memory map
        mem = pygame.Rect(right.x, right.y, right.w, int(right.h * .5))
        used = sum(1 for o in vm.frame_owner if o)
        self._panel(s, mem, f"Physical memory · {used}/{vm.nframes} frames · {vm.cfg.page_size} B pages")
        n = vm.nframes
        cols = 8 if n <= 32 else 16
        gw = (mem.w - 24) // cols
        gh = min(40, (mem.h - 40) // max(1, -(-n // cols)))
        for f in range(n):
            fx = mem.x + 12 + (f % cols) * gw
            fy = mem.y + 32 + (f // cols) * gh
            r = pygame.Rect(fx, fy, gw - 4, gh - 4)
            owner = vm.frame_owner[f]
            if owner:
                col = PID_COLORS[owner[0] % len(PID_COLORS)]
                age = vm.clock - vm.frame_used[f]
                rrect(s, col if age < 30 else tuple(int(c * .55) for c in col), r, 4)
                if gh > 26:
                    text(s, f"p{owner[0]}:{owner[1]}", r.center, (16, 18, 24), "mono", 11, "center")
            else:
                rrect(s, C["field"], r, 4)
                rrect(s, C["line"], r, 4, 1)
        text(s, "bright = recently used (LRU)   label = pid:virtual page", (mem.x + 12, mem.bottom - 18), C["dim"], "sans", 11)

        # throughput sparkline + output
        out = pygame.Rect(right.x, mem.bottom + 10, right.w, right.bottom - mem.bottom - 10)
        self._panel(s, out, "Output")
        if len(self.ips_hist) > 1:
            mx = max(self.ips_hist) or 1
            pts = [(out.right - 130 + i * 120 / 59, out.y + 22 - v / mx * 14) for i, v in enumerate(self.ips_hist)]
            pygame.draw.lines(s, C["accent"], False, pts, 2)
        lh = font("mono", 12).get_linesize()
        rows = (out.h - 36) // lh
        y = out.y + 30
        for line in self.out[-rows:]:
            col = C["danger"] if "FAULT" in line else (C["warn"] if line.startswith("[kernel]") else C["text"])
            text(s, line, (out.x + 12, y), col, "mono", 12, maxw=out.w - 24)
            y += lh

        if self.picker:
            self._draw_picker(s, x - 300, 46)

    def _panel(self, s, r, title):
        rrect(s, C["panel"], r, 8)
        rrect(s, C["line"], r, 8, 1)
        text(s, title, (r.x + 12, r.y + 8), C["text"], "bold", 12, maxw=r.w - 24)

    def _draw_picker(self, s, x, y):
        progs = sorted((self.sys.home / "Programs").glob("*"))
        progs = [p for p in progs if p.is_file()]
        r = pygame.Rect(max(10, x), y, 240, 16 + 28 * max(1, len(progs)))
        rrect(s, C["title_active"], r, 8)
        rrect(s, C["accent"], r, 8, 1)
        for i, p in enumerate(progs):
            self.btn(s, (r.x + 6, r.y + 8 + i * 28, r.w - 12, 26), p.name, lambda p=p: self.load(p), "flat", icon_kind="program")
        if not progs:
            text(s, "~/Programs is empty", (r.x + 12, r.y + 12), C["dim"])
