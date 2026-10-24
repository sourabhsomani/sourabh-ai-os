"""TinyVM unit tests. Run:  python3 -m tests.test_vm"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sourabhos.core.vm import TinyVM, Config, assemble, AssemblyError  # noqa: E402

PROGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "programs")


def run(names, cfg=None, inputs=(), ticks=20000):
    out = []
    vm = TinyVM(cfg or Config(), output=lambda pid, t: out.append(t))
    for n in names:
        vm.load(open(os.path.join(PROGS, n)).read(), n)
    for v in inputs:
        vm.feed_input(v)
    vm.run(ticks)
    return vm, out


def test_programs():
    assert run(["hello.tvm"])[1] == ["1", "2", "3", "4", "5"]
    assert run(["fib.tvm"])[1][-1] == "89"
    assert run(["producer.tvm", "consumer.tvm"])[1] == ["50", "10", "20", "30", "40", "100"]
    assert run(["echo.tvm"], inputs=[21])[1] == ["21", "42"]
    assert run(["countdown.tvm"])[1] == ["5", "4", "3", "2", "1"]
    vm, out = run(["fault.tvm"])
    assert out[0].startswith("FAULT") and vm.procs[1].state == "terminated"


def test_original_tinyos_format():
    # scott1.txt from shanselman/TinyOS (numeric opcodes, tabs, comments)
    src = "6\tr1, $3276834\t;move\n7\tr2, r1\n11\tr2\n" + "2\tr2, $5\n" * 7 + "11\tr2\n27\n"
    out = []
    vm = TinyVM(output=lambda p, t: out.append(t))
    vm.load(src, "scott1")
    vm.run()
    assert out == ["3276834", "3276869"]


def test_paging_under_pressure():
    cfg = Config(physical_memory=64, page_size=16)  # only 4 frames
    vm, out = run(["memhog.tvm", "fib.tvm", "hello.tvm"], cfg)
    assert out.count("89") == 1 and "1" in out
    assert vm.stats["swap_outs"] > 0 and vm.stats["swap_ins"] > 0


def test_assembler_errors():
    for bad in ("movi r1", "foo r1", "movi r11, $1", "movi r1, 5", ""):
        try:
            assemble(bad)
        except AssemblyError:
            continue
        raise AssertionError(f"accepted: {bad!r}")


def test_priority_and_idle():
    vm, out = run(["idle.tvm", "hello.tvm"], ticks=500)
    assert out == ["1", "2", "3", "4", "5"]
    assert vm.procs[1].priority == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
