"""
Sourabh OS virtual machine.

A Python re-implementation of the ideas in Scott Hanselman's TinyOS (C#):
an abstract CPU with 10 registers, per-process virtual memory with demand
paging and swapping, a priority round-robin scheduler, locks, events,
shared memory and the same 36 opcodes.  Programs written for TinyOS
(numeric opcode format) run unchanged; mnemonics are accepted too.

Encoding: 1 opcode byte followed by 4 bytes (little-endian, 32-bit) per
parameter.  Jumps/calls are relative to the *next* instruction, exactly
like the original.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- opcodes
# value: (mnemonic, number of params)
OPCODES = {
    1: ("incr", 1), 2: ("addi", 2), 3: ("addr", 2), 4: ("pushr", 1),
    5: ("pushi", 1), 6: ("movi", 2), 7: ("movr", 2), 8: ("movmr", 2),
    9: ("movrm", 2), 10: ("movmm", 2), 11: ("printr", 1), 12: ("printm", 1),
    13: ("jmp", 1), 14: ("cmpi", 2), 15: ("cmpr", 2), 16: ("jlt", 1),
    17: ("jgt", 1), 18: ("je", 1), 19: ("call", 1), 20: ("callm", 1),
    21: ("ret", 0), 22: ("alloc", 2), 23: ("acquirelock", 1),
    24: ("releaselock", 1), 25: ("sleep", 1), 26: ("setpriority", 1),
    27: ("exit", 0), 28: ("freememory", 1), 29: ("mapsharedmem", 2),
    30: ("signalevent", 1), 31: ("waitevent", 1), 32: ("input", 1),
    33: ("memoryclear", 2), 34: ("terminateprocess", 1), 35: ("popr", 1),
    36: ("popm", 1),
}
MNEMONICS = {name: code for code, (name, _) in OPCODES.items()}

NUM_REGISTERS = 10
NUM_LOCKS = 10
NUM_EVENTS = 10
SHARED_BASE = 0x8000  # shared regions live above every process' private space


def s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


class VMFault(Exception):
    """Raised when a process does something illegal (protection fault etc.)."""


class AssemblyError(Exception):
    pass


# ---------------------------------------------------------------- assembler
@dataclass
class Instruction:
    opcode: int
    params: list
    source: str = ""

    @property
    def size(self) -> int:
        return 1 + 4 * len(self.params)

    def __str__(self):
        name = OPCODES.get(self.opcode, ("???", 0))[0]
        ps = []
        for kind, val in self.params:
            ps.append(f"r{val}" if kind == "r" else f"${val}")
        return f"{name:<12} {', '.join(ps)}".rstrip()


_TOKEN = re.compile(r"[,\s]+")


def assemble(text: str) -> list[Instruction]:
    """Parse TinyOS source (numeric or mnemonic opcodes) into instructions."""
    out = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        toks = [t for t in _TOKEN.split(line) if t]
        op = toks[0].lower()
        if op.isdigit():
            code = int(op)
        elif op in MNEMONICS:
            code = MNEMONICS[op]
        else:
            raise AssemblyError(f"line {lineno}: unknown opcode '{toks[0]}'")
        if code not in OPCODES:
            raise AssemblyError(f"line {lineno}: invalid opcode {code}")
        want = OPCODES[code][1]
        args = toks[1:]
        if len(args) != want:
            raise AssemblyError(
                f"line {lineno}: {OPCODES[code][0]} needs {want} param(s), got {len(args)}")
        params = []
        for a in args:
            al = a.lower()
            if al.startswith("r") and al[1:].isdigit():
                n = int(al[1:])
                if not 1 <= n <= NUM_REGISTERS:
                    raise AssemblyError(f"line {lineno}: no register {a}")
                params.append(("r", n))
            elif a.startswith("$"):
                try:
                    params.append(("i", s32(int(a[1:], 0))))
                except ValueError:
                    raise AssemblyError(f"line {lineno}: bad constant {a}")
            else:
                raise AssemblyError(f"line {lineno}: bad operand '{a}'")
        out.append(Instruction(code, params, raw.strip()))
    if not out:
        raise AssemblyError("program is empty")
    return out


def to_image(instrs: list[Instruction]) -> bytes:
    b = bytearray()
    for ins in instrs:
        b.append(ins.opcode)
        for _, v in ins.params:
            b += (v & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(b)


# ---------------------------------------------------------------- config
@dataclass
class Config:
    physical_memory: int = 256      # bytes of RAM in the "machine"
    process_memory: int = 512       # virtual address space per process
    page_size: int = 16
    stack_size: int = 64
    data_size: int = 16
    shared_region_size: int = 16
    num_shared_regions: int = 4
    quantum: int = 10               # instructions per time slice
    default_priority: int = 1


# ---------------------------------------------------------------- process
READY, RUNNING, SLEEPING, BLOCKED, TERMINATED = (
    "ready", "running", "sleeping", "blocked", "terminated")


@dataclass
class Process:
    pid: int
    name: str
    image: bytes
    instrs: list
    cfg: Config
    priority: int = 1
    state: str = READY
    regs: list = field(default_factory=lambda: [0] * (NUM_REGISTERS + 1))
    ip: int = 0
    sp: int = 0
    sign: bool = False
    zero: bool = False
    page_table: dict = field(default_factory=dict)   # vpage -> frame
    loaded: set = field(default_factory=set)        # vpages ever materialised
    wait_kind: str = ""
    wait_obj: int = 0
    wake_at: int | None = None
    cycles: int = 0
    page_faults: int = 0
    exit_reason: str = ""
    heap_free: list = field(default_factory=list)
    heap_used: dict = field(default_factory=dict)

    def __post_init__(self):
        c = self.cfg
        if len(self.image) + c.data_size + c.stack_size > c.process_memory:
            raise VMFault(f"{self.name}: program ({len(self.image)} bytes) too big "
                          f"for {c.process_memory}-byte address space")
        self.sp = c.process_memory
        self.heap_start = len(self.image) + c.data_size
        self.stack_limit = c.process_memory - c.stack_size
        self.heap_free = [(self.heap_start, self.stack_limit - self.heap_start)]

    def reg(self, n):
        return self.regs[n]

    def set_reg(self, n, v):
        self.regs[n] = s32(v)


# ---------------------------------------------------------------- machine
class TinyVM:
    def __init__(self, cfg: Config | None = None, output=None, log=None):
        self.cfg = cfg or Config()
        self.output = output or (lambda pid, text: print(f"[{pid}] {text}"))
        self.log = log or (lambda msg: None)
        self.reset()

    # ---------------- lifecycle
    def reset(self):
        c = self.cfg
        if c.physical_memory % c.page_size or c.process_memory % c.page_size:
            raise ValueError("memory sizes must be multiples of the page size")
        self.ram = bytearray(c.physical_memory)
        self.nframes = c.physical_memory // c.page_size
        self.frame_owner: list = [None] * self.nframes   # (pid, vpage)
        self.frame_used = [0] * self.nframes             # LRU timestamps
        self.swap: dict = {}                              # (pid, vpage) -> bytes
        self.shared = bytearray(c.shared_region_size * c.num_shared_regions)
        self.procs: dict[int, Process] = {}
        self.next_pid = 1
        self.current: Process | None = None
        self.slice_left = 0
        self.clock = 0
        self.idle_ticks = 0
        self.locks: dict[int, int] = {}
        self.input_queue: list[int] = []
        self.stats = {"page_faults": 0, "swap_outs": 0, "swap_ins": 0,
                      "context_switches": 0, "instructions": 0}

    def load(self, source: str, name: str = "prog") -> Process:
        instrs = assemble(source)
        p = Process(self.next_pid, name, to_image(instrs), instrs, self.cfg,
                    priority=self.cfg.default_priority)
        self.procs[p.pid] = p
        self.next_pid += 1
        self.log(f"loaded {name} as pid {p.pid} ({len(p.image)} bytes)")
        return p

    def kill(self, pid: int, reason="killed"):
        p = self.procs.get(pid)
        if not p or p.state == TERMINATED:
            return False
        p.state = TERMINATED
        p.exit_reason = reason
        for f, owner in enumerate(self.frame_owner):
            if owner and owner[0] == pid:
                self.frame_owner[f] = None
        for k in [k for k in self.swap if k[0] == pid]:
            del self.swap[k]
        p.page_table.clear()
        for lock, owner in list(self.locks.items()):
            if owner == pid:
                del self.locks[lock]
                self._wake("lock", lock, one=True)
        if self.current is p:
            self.current = None
        self.log(f"pid {pid} ({p.name}) terminated: {reason}")
        return True

    def feed_input(self, value: int):
        self.input_queue.append(s32(value))
        self._wake("input", 0, one=True)

    @property
    def alive(self):
        return [p for p in self.procs.values() if p.state != TERMINATED]

    # ---------------- memory manager
    def _frame_for(self, p: Process, vpage: int) -> int:
        f = p.page_table.get(vpage)
        if f is not None:
            self.frame_used[f] = self.clock
            return f
        # page fault
        p.page_faults += 1
        self.stats["page_faults"] += 1
        f = self._free_frame()
        key = (p.pid, vpage)
        ps = self.cfg.page_size
        if key in self.swap:
            data = self.swap.pop(key)
            self.stats["swap_ins"] += 1
        elif vpage not in p.loaded:
            start = vpage * ps
            data = p.image[start:start + ps].ljust(ps, b"\0")
        else:
            data = bytes(ps)
        self.ram[f * ps:(f + 1) * ps] = data
        self.frame_owner[f] = key
        self.frame_used[f] = self.clock
        p.page_table[vpage] = f
        p.loaded.add(vpage)
        return f

    def _free_frame(self) -> int:
        for f, owner in enumerate(self.frame_owner):
            if owner is None:
                return f
        victim = min(range(self.nframes), key=lambda i: self.frame_used[i])
        pid, vpage = self.frame_owner[victim]
        ps = self.cfg.page_size
        self.swap[(pid, vpage)] = bytes(self.ram[victim * ps:(victim + 1) * ps])
        self.stats["swap_outs"] += 1
        self.procs[pid].page_table.pop(vpage, None)
        self.frame_owner[victim] = None
        return victim

    def _addr(self, p: Process, addr: int):
        c = self.cfg
        if 0 <= addr < c.process_memory:
            vpage, off = divmod(addr, c.page_size)
            f = self._frame_for(p, vpage)
            return self.ram, f * c.page_size + off
        if SHARED_BASE <= addr < SHARED_BASE + len(self.shared):
            return self.shared, addr - SHARED_BASE
        raise VMFault(f"memory protection fault at address {addr}")

    def read8(self, p, addr):
        buf, i = self._addr(p, addr)
        return buf[i]

    def write8(self, p, addr, v):
        buf, i = self._addr(p, addr)
        buf[i] = v & 0xFF

    def read32(self, p, addr):
        return s32(int.from_bytes(bytes(self.read8(p, addr + k) for k in range(4)), "little"))

    def write32(self, p, addr, v):
        for k, byte in enumerate((v & 0xFFFFFFFF).to_bytes(4, "little")):
            self.write8(p, addr + k, byte)

    def push(self, p, v):
        if p.sp - 4 < p.stack_limit:
            raise VMFault("stack overflow")
        p.sp -= 4
        self.write32(p, p.sp, v)

    def pop(self, p):
        if p.sp + 4 > self.cfg.process_memory:
            raise VMFault("stack underflow")
        v = self.read32(p, p.sp)
        p.sp += 4
        return v

    def alloc(self, p, size):
        if size <= 0:
            return 0
        for i, (start, length) in enumerate(p.heap_free):
            if length >= size:
                if length == size:
                    p.heap_free.pop(i)
                else:
                    p.heap_free[i] = (start + size, length - size)
                p.heap_used[start] = size
                return start
        return 0

    def free(self, p, addr):
        size = p.heap_used.pop(addr, None)
        if size is None:
            return
        p.heap_free.append((addr, size))
        p.heap_free.sort()
        merged = []
        for s, l in p.heap_free:
            if merged and merged[-1][0] + merged[-1][1] == s:
                merged[-1] = (merged[-1][0], merged[-1][1] + l)
            else:
                merged.append((s, l))
        p.heap_free = merged

    # ---------------- scheduler
    def _wake(self, kind, obj, one=False):
        for p in sorted(self.procs.values(), key=lambda q: q.pid):
            if p.state == BLOCKED and p.wait_kind == kind and p.wait_obj == obj:
                p.state = READY
                p.wait_kind = ""
                if one:
                    return

    def _pick(self):
        ready = [p for p in self.procs.values() if p.state in (READY, RUNNING)]
        if not ready:
            return None
        best = max(p.priority for p in ready)
        cands = sorted((p for p in ready if p.priority == best), key=lambda p: p.pid)
        cur = self.current.pid if self.current else 0
        after = [p for p in cands if p.pid > cur]
        return (after or cands)[0]

    def _switch(self):
        nxt = self._pick()
        if self.current and self.current.state == RUNNING:
            self.current.state = READY
        if nxt is not self.current:
            self.stats["context_switches"] += 1
            if nxt:
                self.log(f"context switch -> pid {nxt.pid} ({nxt.name})")
        self.current = nxt
        if nxt:
            nxt.state = RUNNING
        self.slice_left = self.cfg.quantum

    def tick(self) -> bool:
        """Advance the machine one clock cycle. Returns False when nothing is left."""
        self.clock += 1
        for p in self.procs.values():
            if p.state == SLEEPING and p.wake_at is not None and self.clock >= p.wake_at:
                p.state = READY
        if (self.current is None or self.current.state != RUNNING
                or self.slice_left <= 0):
            self._switch()
        p = self.current
        if p is None:
            self.idle_ticks += 1
            return bool(self.alive)
        try:
            self._step(p)
        except VMFault as e:
            self.output(p.pid, f"FAULT: {e}")
            self.kill(p.pid, str(e))
        self.slice_left -= 1
        return bool(self.alive)

    def run(self, max_ticks=100_000):
        for _ in range(max_ticks):
            if not self.tick():
                return True
            if all(q.state in (SLEEPING, BLOCKED) and q.wake_at is None
                   for q in self.alive):
                return False  # deadlock / everybody waiting forever
        return False

    # ---------------- CPU
    def decode(self, p, ip):
        op = self.read8(p, ip)
        if op not in OPCODES:
            raise VMFault(f"illegal opcode {op} at ip={ip}")
        n = OPCODES[op][1]
        params = [self.read32(p, ip + 1 + 4 * k) for k in range(n)]
        return op, params, 1 + 4 * n

    def _reg_index(self, n):
        if not 1 <= n <= NUM_REGISTERS:
            raise VMFault(f"bad register r{n}")
        return n

    def _step(self, p: Process):
        op, a, size = self.decode(p, p.ip)
        nip = p.ip + size
        R = lambda i: p.reg(self._reg_index(i))          # noqa: E731
        W = lambda i, v: p.set_reg(self._reg_index(i), v)  # noqa: E731
        p.cycles += 1
        self.stats["instructions"] += 1
        stay = False   # True => re-execute this instruction later (blocked)

        if op == 1:   W(a[0], R(a[0]) + 1)
        elif op == 2: W(a[0], R(a[0]) + a[1])
        elif op == 3: W(a[0], R(a[0]) + R(a[1]))
        elif op == 4: self.push(p, R(a[0]))
        elif op == 5: self.push(p, a[0])
        elif op == 6: W(a[0], a[1])
        elif op == 7: W(a[0], R(a[1]))
        elif op == 8: W(a[0], self.read32(p, R(a[1])))
        elif op == 9: self.write32(p, R(a[0]), R(a[1]))
        elif op == 10: self.write32(p, R(a[0]), self.read32(p, R(a[1])))
        elif op == 11: self.output(p.pid, str(R(a[0])))
        elif op == 12: self.output(p.pid, str(self.read32(p, R(a[0]))))
        elif op == 13: nip += R(a[0])
        elif op in (14, 15):
            rhs = a[1] if op == 14 else R(a[1])
            lhs = R(a[0])
            p.sign, p.zero = lhs < rhs, lhs == rhs
        elif op == 16:
            if p.sign: nip += R(a[0])
        elif op == 17:
            if not p.sign and not p.zero: nip += R(a[0])
        elif op == 18:
            if p.zero: nip += R(a[0])
        elif op in (19, 20):
            off = R(a[0]) if op == 19 else self.read32(p, R(a[0]))
            self.push(p, nip)
            nip += off
        elif op == 21: nip = self.pop(p)
        elif op == 22: W(a[1], self.alloc(p, R(a[0])))
        elif op == 23:
            n = R(a[0])
            if 1 <= n <= NUM_LOCKS:
                owner = self.locks.get(n)
                if owner is None or owner == p.pid:
                    self.locks[n] = p.pid
                else:
                    p.state, p.wait_kind, p.wait_obj = BLOCKED, "lock", n
                    stay = True
        elif op == 24:
            n = R(a[0])
            if self.locks.get(n) == p.pid:
                del self.locks[n]
                self._wake("lock", n, one=True)
        elif op == 25:
            t = R(a[0])
            p.state = SLEEPING
            p.wake_at = None if t <= 0 else self.clock + t
        elif op == 26: p.priority = max(0, min(31, R(a[0])))
        elif op == 27:
            p.ip = nip
            self.kill(p.pid, "exit")
            return
        elif op == 28: self.free(p, R(a[0]))
        elif op == 29:
            n = R(a[0])
            if 1 <= n <= self.cfg.num_shared_regions:
                W(a[1], SHARED_BASE + (n - 1) * self.cfg.shared_region_size)
            else:
                W(a[1], 0)
        elif op == 30: self._wake("event", R(a[0]))
        elif op == 31:
            p.state, p.wait_kind, p.wait_obj = BLOCKED, "event", R(a[0])
        elif op == 32:
            if self.input_queue:
                W(a[0], self.input_queue.pop(0))
            else:
                p.state, p.wait_kind, p.wait_obj = BLOCKED, "input", 0
                stay = True
                self.output(p.pid, "waiting for input…")
        elif op == 33:
            start, n = R(a[0]), R(a[1])
            for k in range(max(0, n)):
                self.write8(p, start + k, 0)
        elif op == 34:
            target = R(a[0])
            if target == p.pid:
                p.ip = nip
            self.kill(target, f"terminated by pid {p.pid}")
            if target == p.pid:
                return
        elif op == 35: W(a[0], self.pop(p))
        elif op == 36: self.write32(p, R(a[0]), self.pop(p))

        if not stay:
            p.ip = nip
        if p.state != RUNNING:
            self.slice_left = 0
