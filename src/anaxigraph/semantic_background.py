"""Detached host workers for durable semantic-queue execution."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anaxigraph.local_runtime import local_database_path, local_state_root


@dataclass(frozen=True, slots=True)
class SemanticBackgroundSpec:
    repository: Path
    executor: str
    model: str
    reasoning_effort: str
    index: dict[str, Any]
    parallel_jobs: int = 0
    timeout_seconds: int = 0
    config_path: Path | None = None
    database_path: Path | None = None
    service_url: str | None = None
    force: bool = False
    retry_failed: bool = False


def launch_understand_background(
    args: Any,
    repository: Path,
    execution_semantic: Any | None,
    execution_mode: str,
    service: Any | None,
) -> dict[str, Any]:
    if args.limit is not None or args.plan_only:
        raise ValueError(
            "--background runs the complete queue and cannot use --limit or --plan-only"
        )
    if execution_semantic is None or execution_mode not in {"codex", "claude"}:
        raise ValueError("--background requires --executor codex or --executor claude")
    database_path = None if service else local_database_path(repository, explicit=args.db)
    index = (
        service.identity() if service else {"authority": "local", "database": str(database_path)}
    )
    run = launch_semantic_background(
        SemanticBackgroundSpec(
            repository=repository,
            executor=execution_mode,
            model=execution_semantic.model,
            reasoning_effort=execution_semantic.reasoning_effort,
            index=index,
            parallel_jobs=int(getattr(execution_semantic, "max_parallel_jobs", 0)),
            timeout_seconds=int(getattr(execution_semantic, "timeout_seconds", 0)),
            config_path=args.config,
            database_path=database_path,
            service_url=service.base_url if service else None,
            force=args.force,
            retry_failed=args.retry_failed,
        )
    )
    return {
        "status": run["status"],
        "complete": False,
        "execution": _execution_identity(execution_mode, execution_semantic),
        "index": index,
        "execution_run": run,
        "next_action": "Use anaxigraph semantic-status for progress; the worker survives this session.",
    }


def _execution_identity(mode: str, execution: Any) -> dict[str, Any]:
    return {
        "mode": mode,
        "model": execution.model or None,
        "reasoning_effort": execution.reasoning_effort or None,
        "parallel_jobs": int(getattr(execution, "max_parallel_jobs", 0)) or None,
        "timeout_seconds": int(getattr(execution, "timeout_seconds", 0)) or None,
        "background": True,
    }


def launch_semantic_background(spec: SemanticBackgroundSpec) -> dict[str, Any]:
    """Start a detached CLI worker whose lifetime is independent of the invoking agent."""

    directory = _run_directory(spec.repository)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if os.name == "posix":
        directory.chmod(0o700)
    latest_path = directory / "latest.json"
    lock_path = directory / "active.lock"
    active = semantic_background_status(spec.repository)
    if active and active["active"]:
        return {**active, "status": "already_running"}
    run_id = str(uuid.uuid4())
    if not _reserve(lock_path, latest_path, run_id):
        active = semantic_background_status(spec.repository)
        return {**(active or {}), "status": "already_running", "active": True}
    record_path = directory / f"{run_id}.json"
    log_path = directory / f"{run_id}.log"
    record = _initial_record(spec, run_id, record_path, log_path)
    _write_state(record, record_path, latest_path)
    try:
        process = _spawn_wrapper(record_path, latest_path, lock_path, log_path)
    except OSError as exc:
        _finish_launch_failure(record, record_path, latest_path, lock_path, exc)
        raise RuntimeError(f"Could not start the semantic background worker: {exc}") from exc
    launched = {**record, "status": "running", "pid": process.pid}
    return _public_record(launched)


def semantic_background_status(repository: Path) -> dict[str, Any] | None:
    """Read the most recent detached-run state and detect an orphaned process."""

    latest_path = _run_directory(repository) / "latest.json"
    if not latest_path.exists():
        return None
    try:
        record = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"status": "unreadable", "active": False, "state_path": str(latest_path)}
    status = str(record.get("status") or "unknown")
    pid = int(record.get("pid") or 0)
    active = (status == "starting" and _recent(record)) or (
        status == "running" and _pid_exists(pid)
    )
    if status in {"running", "starting"} and not active:
        record["status"] = "interrupted"
    record["active"] = active
    return _public_record(record)


def _initial_record(
    spec: SemanticBackgroundSpec,
    run_id: str,
    record_path: Path,
    log_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "status": "starting",
        "active": True,
        "pid": None,
        "repository": str(spec.repository.expanduser().resolve()),
        "executor": spec.executor,
        "model": spec.model or None,
        "reasoning_effort": spec.reasoning_effort or None,
        "parallel_jobs": spec.parallel_jobs or None,
        "timeout_seconds": spec.timeout_seconds or None,
        "index": spec.index,
        "started_at": _now(),
        "record_path": str(record_path),
        "log_path": str(log_path),
        "command": _understand_command(spec),
    }


def _understand_command(spec: SemanticBackgroundSpec) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "anaxigraph",
        "understand",
        str(spec.repository.expanduser().resolve()),
        "--executor",
        spec.executor,
        "--until-complete",
    ]
    if spec.config_path:
        command.extend(("--config", str(spec.config_path.expanduser().resolve())))
    if spec.database_path:
        command.extend(("--db", str(spec.database_path.expanduser().resolve())))
    if spec.service_url:
        command.extend(("--service-url", spec.service_url))
    if spec.model:
        command.extend(("--model", spec.model))
    if spec.reasoning_effort:
        command.extend(("--reasoning-effort", spec.reasoning_effort))
    if spec.parallel_jobs:
        command.extend(("--parallel-jobs", str(spec.parallel_jobs)))
    if spec.timeout_seconds:
        command.extend(("--timeout-seconds", str(spec.timeout_seconds)))
    if spec.force:
        command.append("--force")
    if spec.retry_failed:
        command.append("--retry-failed")
    command.append("--json")
    return command


def _spawn_wrapper(
    record_path: Path,
    latest_path: Path,
    lock_path: Path,
    log_path: Path,
) -> subprocess.Popen[bytes]:
    command = [
        sys.executable,
        "-m",
        "anaxigraph.semantic_background",
        "run",
        str(record_path),
        str(latest_path),
        str(lock_path),
    ]
    options: dict[str, Any] = {"stdin": subprocess.DEVNULL, "close_fds": True}
    if os.name == "posix":
        options["start_new_session"] = True
    elif os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with log_path.open("a", encoding="utf-8") as output:
        if os.name == "posix":
            log_path.chmod(0o600)
        return subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, **options)


def _run_worker(record_path: Path, latest_path: Path, lock_path: Path) -> int:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.update(status="running", active=True, pid=os.getpid())
    _write_state(record, record_path, latest_path)
    print(f"AnaxiGraph semantic run {record['run_id']} started at {_now()}", flush=True)
    exit_code = 1
    try:
        completed = subprocess.run(record["command"], check=False)
        exit_code = int(completed.returncode)
        record["status"] = "completed" if exit_code == 0 else "failed"
    except BaseException as exc:
        record["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        record["error"] = f"{type(exc).__name__}: {exc}"[:1_000]
        exit_code = 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        record.update(active=False, exit_code=exit_code, finished_at=_now())
        _write_state(record, record_path, latest_path)
        _release(lock_path, str(record["run_id"]))
    print(
        f"AnaxiGraph semantic run {record['run_id']} ended with status {record['status']}",
        flush=True,
    )
    return exit_code


def _write_state(record: dict[str, Any], record_path: Path, latest_path: Path) -> None:
    for path in (record_path, latest_path):
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        if os.name == "posix":
            temporary.chmod(0o600)
        os.replace(temporary, path)


def _reserve(lock_path: Path, latest_path: Path, run_id: str) -> bool:
    for _ in range(2):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if _lock_is_active(lock_path, latest_path):
                return False
            try:
                lock_path.unlink()
            except FileNotFoundError:
                continue
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(run_id)
            return True
    return False


def _lock_is_active(lock_path: Path, latest_path: Path) -> bool:
    try:
        lock_age = time.time() - lock_path.stat().st_mtime
        lock_run_id = lock_path.read_text(encoding="utf-8")
        record = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return lock_age < 60 if "lock_age" in locals() else True
    if str(record.get("run_id") or "") != lock_run_id:
        return lock_age < 60
    status = str(record.get("status") or "")
    return (status == "starting" and _recent(record)) or (
        status == "running" and _pid_exists(int(record.get("pid") or 0))
    )


def _release(lock_path: Path, run_id: str) -> None:
    try:
        if lock_path.read_text(encoding="utf-8") == run_id:
            lock_path.unlink()
    except OSError:
        pass


def _finish_launch_failure(
    record: dict[str, Any],
    record_path: Path,
    latest_path: Path,
    lock_path: Path,
    error: OSError,
) -> None:
    record.update(status="failed", active=False, error=str(error), finished_at=_now())
    _write_state(record, record_path, latest_path)
    _release(lock_path, str(record["run_id"]))


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "command"}


def _run_directory(repository: Path) -> Path:
    resolved = repository.expanduser().resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    return local_state_root() / "semantic-runs" / digest


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _recent(record: dict[str, Any], seconds: int = 60) -> bool:
    try:
        started = datetime.fromisoformat(str(record["started_at"]))
    except (KeyError, TypeError, ValueError):
        return False
    return (datetime.now(UTC) - started).total_seconds() < seconds


def _now() -> str:
    return datetime.now(UTC).isoformat()


def main(argv: list[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 4 or arguments[0] != "run":
        raise SystemExit("usage: python -m anaxigraph.semantic_background run RECORD LATEST LOCK")
    raise SystemExit(_run_worker(*(Path(value) for value in arguments[1:])))


if __name__ == "__main__":
    main()
