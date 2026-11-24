"""``run_klt`` adds ``--wait-for-capacity`` to batch ``klt characterize`` submits only.

Regression for issue #142: a batch ``klt characterize`` submit *is* a batch
``klt sim`` submit underneath (klt docs: "The whole grid is one ``klt sim``
request"), and the host rule requires ``--wait-for-capacity`` on every batch
``klt sim`` submit -- a burst otherwise fails the step with
``batch_no_capacity`` instead of waiting with backoff. But ``klt`` rejects the
flag outright on ``--backend local`` (measured: exit 1 during argument
validation, before the request file is even read), so the flag is gated on the
backend, never added unconditionally.

Run from the repo root:  python -m pytest sim/tests
"""

import json
import subprocess

from sim.characterize import runner


def run_and_capture(monkeypatch, backend, lib_path=None, tmp_path=None):
    """Stub ``subprocess.run``; return (argv, parsed response) for one ``run_klt`` call."""
    seen = {}

    def fake_run(cmd, **_kwargs):
        seen["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"ok": True}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    response = runner.run_klt({"corner": {"name": "tt"}}, backend=backend, lib_path=lib_path,
                              workdir=tmp_path)
    return seen["cmd"], response


def test_batch_submit_carries_capacity_wait(monkeypatch, tmp_path):
    cmd, response = run_and_capture(monkeypatch, "batch", tmp_path=tmp_path)
    i = cmd.index("--wait-for-capacity")
    assert cmd[i + 1] == str(runner.BATCH_CAPACITY_WAIT_S)
    assert response == {"ok": True}


def test_batch_flag_lands_before_the_request_path(monkeypatch, tmp_path):
    cmd, _ = run_and_capture(monkeypatch, "batch", tmp_path=tmp_path)
    assert cmd[-1].endswith("request.json")  # positional request path stays last
    assert cmd.index("--wait-for-capacity") < len(cmd) - 1


def test_batch_flag_and_lib_both_land_before_the_request_path(monkeypatch, tmp_path):
    # Both flags insert at the same ``cmd[-1:-1]`` point; the second insertion
    # must not displace the first past the positional request path. This is the
    # library + batch combination -- the one ``run_klt`` caller that passes
    # ``lib_path`` (``characterize_library()``) is also the one that runs batch.
    cmd, _ = run_and_capture(monkeypatch, "batch", lib_path=tmp_path / "x.lib",
                             tmp_path=tmp_path)
    assert cmd[-1].endswith("request.json")  # positional request path stays last
    assert cmd[cmd.index("--lib") + 1].endswith("x.lib")
    assert cmd[cmd.index("--wait-for-capacity") + 1] == str(runner.BATCH_CAPACITY_WAIT_S)


def test_local_submit_has_no_capacity_flag(monkeypatch, tmp_path):
    cmd, response = run_and_capture(monkeypatch, "local", tmp_path=tmp_path)
    assert not any("wait-for-capacity" in part for part in cmd)
    assert response == {"ok": True}


def test_wait_constant_matches_host_rule():
    assert runner.BATCH_CAPACITY_WAIT_S == 600
