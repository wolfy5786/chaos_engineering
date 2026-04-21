"""Opt-in integration test against a real cluster (dummy-test namespace)."""

from __future__ import annotations

import os
import subprocess
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CHAOS_IT", "").strip() != "1",
    reason="Set CHAOS_IT=1 and ensure kubectl + dummy-test namespace with auth pod",
)


def _kubectl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["kubectl", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_pod_kill_auth_pod_recreated() -> None:
    from framework.backends.kubectl import KubectlBackend
    from framework.fault_injector import FaultInjector

    ns = "dummy-test"
    sel = "app.kubernetes.io/component=auth"
    before = _kubectl(
        "get",
        "pods",
        "-n",
        ns,
        "-l",
        sel,
        "-o",
        "jsonpath={.items[0].metadata.name}",
    )
    if before.returncode != 0 or not (before.stdout or "").strip():
        pytest.skip("No auth pod in dummy-test (deploy dummy_test/k8s first)")

    old_name = before.stdout.strip()
    inj = FaultInjector(backend=KubectlBackend())
    handle = inj.inject(
        {
            "type": "pod_kill",
            "target": {"namespace": ns, "label_selector": sel},
            "delay_seconds": 0,
        }
    )
    assert handle.type == "pod_kill"

    deadline = time.time() + 120
    new_name = ""
    while time.time() < deadline:
        cur = _kubectl(
            "get",
            "pods",
            "-n",
            ns,
            "-l",
            sel,
            "-o",
            "jsonpath={.items[0].metadata.name}",
        )
        if cur.returncode == 0 and (cur.stdout or "").strip():
            new_name = cur.stdout.strip()
            if new_name != old_name:
                break
        time.sleep(2)
    else:
        pytest.fail("Auth pod was not recreated within timeout")

    inj.remove(handle)
