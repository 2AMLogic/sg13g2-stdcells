# cocotb + Icarus. Usage: make -C verification  (RTL_DIR overrides the DUT dir,
# e.g. to run the same test on a synthesized netlist).
SIM ?= icarus
TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(abspath ../rtl/add8.v)
COCOTB_TOPLEVEL = add8
COCOTB_TEST_MODULES = test_add8
include $(shell cocotb-config --makefiles)/Makefile.sim
