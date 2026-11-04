"""cocotb functional check of rtl/add8.v: exhaustive over a, b, cin (2^17 cases)."""
import cocotb
from cocotb.triggers import Timer


@cocotb.test()
async def exhaustive(dut):
    for cin in (0, 1):
        for a in range(256):
            for b in range(256):
                dut.a.value = a
                dut.b.value = b
                dut.cin.value = cin
                await Timer(1, unit="ns")
                exp = a + b + cin
                got = (int(dut.cout.value) << 8) | int(dut.sum.value)
                assert got == exp, f"{a}+{b}+{cin}: got {got}, expected {exp}"
