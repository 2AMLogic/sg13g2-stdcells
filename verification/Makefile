# cocotb + Icarus. Usage: make -C verification
# RTL_DIR overrides the DUT dir (default ../rtl); it selects an alternative
# behavioral add8.v — not yet a synthesized netlist, which needs a tracked
# SG13G2 cell-level Verilog model to elaborate (signoff digital item 7).
SIM ?= icarus
TOPLEVEL_LANG = verilog
RTL_DIR ?= ../rtl
VERILOG_SOURCES = $(abspath $(RTL_DIR)/add8.v)
COCOTB_TOPLEVEL = add8
COCOTB_TEST_MODULES = test_add8
include $(shell cocotb-config --makefiles)/Makefile.sim
