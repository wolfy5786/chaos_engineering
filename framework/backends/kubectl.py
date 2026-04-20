"""kubectl-based execution backend."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from framework.backends.base import (
    BackendError,
    ExecResult,
    ExecutionBackend,
    ManifestRef,
    ManifestResource,
    Target,
)


class KubectlBackend(ExecutionBackend):
    """Runs cluster operations via the ``kubectl`` CLI (JSON I/O, structured errors)."""

    def __init__(self, kubectl_bin: str = "kubectl") -> None:
        self._kubectl = kubectl_bin

    def list_targets(self, namespace: str, label_selector: str) -> list[Target]:
        cmd = [self._kubectl, "get", "pods", "-n", namespace, "-o", "json"]
        if label_selector.strip():
            cmd.extend(["-l", label_selector])
        out = self._run_json(cmd)
        items = out.get("items") or []
        targets: list[Target] = []
        for item in items:
            md = item.get("metadata") or {}
            name = md.get("name")
            ns = md.get("namespace") or namespace
            if not name:
                continue
            targets.append(Target(namespace=ns, name=name))
        return targets

    def delete_pod(self, target: Target) -> None:
        self._run(
            [
                self._kubectl,
                "delete",
                "pod",
                target.name,
                "-n",
                target.namespace,
                "--wait=false",
            ],
            capture_json=False,
        )

    def exec_in_pod(
        self,
        target: Target,
        argv: list[str],
        *,
        container: str | None = None,
        timeout: float | None = None,
    ) -> ExecResult:
        cmd = [self._kubectl, "exec", target.name, "-n", target.namespace]
        if container:
            cmd.extend(["-c", container])
        cmd.append("--")
        cmd.extend(argv)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise BackendError(
                "kubectl exec timed out",
                stderr=str(e),
                command=cmd,
            ) from e
        except FileNotFoundError as e:
            raise BackendError(
                f"kubectl executable not found ({self._kubectl!r})",
                command=cmd,
            ) from e
        return ExecResult(
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )

    def apply_manifest(self, yaml_str: str) -> ManifestRef:
        self._run(
            [self._kubectl, "apply", "-f", "-"],
            stdin=yaml_str.encode(),
            capture_json=False,
        )
        out = self._run_json(
            [self._kubectl, "get", "-f", "-", "-o", "json"],
            stdin=yaml_str.encode(),
        )
        resources = _manifest_resources_from_get_json(out)
        if not resources:
            raise BackendError(
                "apply_manifest produced no addressable objects (empty YAML or unsupported get output)",
                command=[self._kubectl, "apply", "-f", "-"],
            )
        return ManifestRef(resources=tuple(resources))

    def delete_manifest(self, ref: ManifestRef) -> None:
        for r in reversed(ref.resources):
            ns_args: list[str] = []
            if r.namespace:
                ns_args = ["-n", r.namespace]
            self._run(
                [self._kubectl, "delete", r.kind, r.name, *ns_args, "--wait=false"],
                capture_json=False,
            )

    def copy_into_pod(self, target: Target, local_path: str, remote_path: str) -> None:
        spec = f"{target.namespace}/{target.name}:{remote_path}"
        self._run(
            [self._kubectl, "cp", local_path, spec],
            capture_json=False,
        )

    def _run_json(
        self,
        cmd: list[str],
        *,
        stdin: bytes | None = None,
    ) -> dict[str, Any]:
        raw = self._run(cmd, stdin=stdin, capture_json=True)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise BackendError(
                f"Invalid JSON from kubectl: {e}",
                stderr=raw[:2000],
                command=cmd,
            ) from e
        if not isinstance(data, dict):
            raise BackendError(
                "Expected JSON object from kubectl",
                stderr=raw[:2000],
                command=cmd,
            )
        return data

    def _run(
        self,
        cmd: list[str],
        *,
        stdin: bytes | None = None,
        capture_json: bool = True,
    ) -> str:
        try:
            proc = subprocess.run(
                cmd,
                input=stdin,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise BackendError(
                "kubectl command timed out",
                stderr=str(e),
                command=cmd,
            ) from e
        except FileNotFoundError as e:
            raise BackendError(
                f"kubectl executable not found ({self._kubectl!r})",
                command=cmd,
            ) from e
        out = proc.stdout or ""
        err = proc.stderr or ""
        if proc.returncode != 0:
            raise BackendError(
                err.strip() or f"kubectl exited with status {proc.returncode}",
                returncode=proc.returncode,
                stderr=err,
                stdout=out,
                command=cmd,
            )
        if capture_json and out.strip() == "":
            raise BackendError(
                "kubectl produced empty stdout",
                returncode=proc.returncode,
                stderr=err,
                stdout=out,
                command=cmd,
            )
        return out


def _manifest_resources_from_get_json(data: Any) -> list[ManifestResource]:
    if isinstance(data, dict) and data.get("kind") == "List":
        items = data.get("items") or []
        acc: list[ManifestResource] = []
        for item in items:
            acc.extend(_resource_from_object(item))
        return acc
    return list(_resource_from_object(data))


def _resource_from_object(obj: Any) -> list[ManifestResource]:
    if not isinstance(obj, dict):
        return []
    if obj.get("kind") == "Status":
        return []
    md = obj.get("metadata") or {}
    name = md.get("name")
    kind = obj.get("kind")
    api_version = obj.get("apiVersion")
    if not name or not kind or not api_version:
        return []
    ns = md.get("namespace") or ""
    return [
        ManifestResource(
            api_version=api_version,
            kind=kind,
            name=name,
            namespace=ns,
        )
    ]


__all__ = ["KubectlBackend"]
