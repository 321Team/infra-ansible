#!/usr/bin/env python3
"""Read-only queued-job classifier for the infra-ansible isolated ephemeral Runner.

This tool never issues Runner tokens, registers/deregisters a Runner, changes
repository settings, reruns jobs, or modifies workflow state. It only reads
GitHub Actions job/run/runner metadata and emits a bounded JSON observation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

REPO = "321Team/infra-ansible"
EXPECTED_LABELS = {"self-hosted", "Linux", "X64", "fds-ci", "ansible-isolated"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class WatchError(RuntimeError):
    """Expected operational error with a non-secret stable reason."""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WatchError("INVALID_GITHUB_TIMESTAMP") from exc
    if parsed.tzinfo is None:
        raise WatchError("GITHUB_TIMESTAMP_WITHOUT_TZ")
    return parsed.astimezone(dt.timezone.utc)


def clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("GH_DEBUG", "GH_FORCE_TTY", "ACTIONS_STEP_DEBUG", "ACTIONS_RUNNER_DEBUG"):
        env.pop(key, None)
    return env


def gh_json(path: str, *, paginate: bool = False) -> Any:
    gh = shutil.which("gh")
    if not gh:
        raise WatchError("GH_CLI_NOT_FOUND")
    command = [gh, "api"]
    if paginate:
        command += ["--paginate", "--slurp"]
    command.append(path)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=45,
        env=clean_env(),
    )
    if result.returncode != 0:
        raise WatchError("GITHUB_API_READ_FAILED")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise WatchError("GITHUB_API_INVALID_JSON") from exc


def runner_labels(runner: dict[str, Any]) -> set[str]:
    labels = runner.get("labels") or []
    return {
        item.get("name")
        for item in labels
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def flatten_runner_pages(value: Any) -> list[dict[str, Any]]:
    pages = value if isinstance(value, list) else [value]
    runners: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            raise WatchError("RUNNER_LIST_INVALID_SHAPE")
        current = page.get("runners")
        if not isinstance(current, list):
            raise WatchError("RUNNER_LIST_MISSING")
        runners.extend(item for item in current if isinstance(item, dict))
    return runners


def classify(
    job: dict[str, Any],
    run: dict[str, Any],
    runners: list[dict[str, Any]],
    *,
    threshold_minutes: int,
    now: dt.datetime,
    expected_source_sha: str | None,
) -> dict[str, Any]:
    if threshold_minutes < 1:
        raise WatchError("THRESHOLD_MUST_BE_POSITIVE")

    job_labels = {label for label in job.get("labels") or [] if isinstance(label, str)}
    status = job.get("status")
    if not isinstance(status, str):
        raise WatchError("JOB_STATUS_MISSING")

    run_id = job.get("run_id")
    job_id = job.get("id")
    if not isinstance(run_id, int) or not isinstance(job_id, int):
        raise WatchError("JOB_IDENTITY_MISSING")

    source_sha = expected_source_sha
    if source_sha is not None and not SHA40.fullmatch(source_sha):
        raise WatchError("EXPECTED_SOURCE_SHA_INVALID")

    created = parse_time(job.get("created_at")) or parse_time(run.get("created_at"))
    age_minutes = None
    if created is not None:
        age_minutes = max(0.0, (now - created).total_seconds() / 60.0)

    matching = []
    for runner in runners:
        labels = runner_labels(runner)
        if EXPECTED_LABELS <= labels:
            matching.append(
                {
                    "id": runner.get("id"),
                    "name": runner.get("name"),
                    "status": runner.get("status"),
                    "busy": runner.get("busy"),
                }
            )

    online_matching = [r for r in matching if r.get("status") == "online"]

    isolated_job = EXPECTED_LABELS <= job_labels
    action_required = False

    if not isolated_job:
        classification = "NOT_ANSIBLE_ISOLATED_JOB"
    elif status == "in_progress":
        classification = "JOB_IN_PROGRESS"
    elif status == "completed":
        classification = "JOB_COMPLETED"
    elif status != "queued":
        classification = "UNRECOGNIZED_JOB_STATUS"
    elif online_matching:
        classification = "QUEUED_WITH_MATCHING_RUNNER_ONLINE"
    elif age_minutes is None:
        classification = "QUEUED_AGE_UNKNOWN"
    elif age_minutes < threshold_minutes:
        classification = "QUEUED_WITHIN_GRACE"
    else:
        classification = "EPHEMERAL_RUNNER_NOT_SUPPLIED"
        action_required = True

    return {
        "schema": "infra-ansible.ephemeral-runner-queue-observation.v1",
        "repository": REPO,
        "queried_at_utc": now.isoformat().replace("+00:00", "Z"),
        "threshold_minutes": threshold_minutes,
        "classification": classification,
        "action_required": action_required,
        "run": {
            "id": run_id,
            "attempt": job.get("run_attempt") or run.get("run_attempt"),
            "event": run.get("event"),
            "run_head_sha": run.get("head_sha"),
            "expected_source_sha": source_sha,
            "html_url": run.get("html_url"),
            "created_at": run.get("created_at"),
        },
        "job": {
            "id": job_id,
            "name": job.get("name"),
            "status": status,
            "conclusion": job.get("conclusion"),
            "created_at": job.get("created_at"),
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "labels": sorted(job_labels),
            "queued_age_minutes": None if age_minutes is None else round(age_minutes, 2),
        },
        "runner_observation": {
            "matching_count": len(matching),
            "matching_online_count": len(online_matching),
            "matching": matching,
        },
        "scope": (
            "read-only classification only; no token issuance, registration, "
            "deregistration, rerun, cancellation, repository mutation, or CI PASS assertion"
        ),
    }


def observe(
    job_id: int,
    *,
    threshold_minutes: int,
    expected_source_sha: str | None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    if job_id < 1:
        raise WatchError("JOB_ID_MUST_BE_POSITIVE")

    job = gh_json(f"repos/{REPO}/actions/jobs/{job_id}")
    if not isinstance(job, dict):
        raise WatchError("JOB_RESPONSE_INVALID_SHAPE")

    run_id = job.get("run_id")
    if not isinstance(run_id, int):
        raise WatchError("JOB_RUN_ID_MISSING")

    run = gh_json(f"repos/{REPO}/actions/runs/{run_id}")
    if not isinstance(run, dict):
        raise WatchError("RUN_RESPONSE_INVALID_SHAPE")

    runners = flatten_runner_pages(
        gh_json(f"repos/{REPO}/actions/runners?per_page=100", paginate=True)
    )

    return classify(
        job,
        run,
        runners,
        threshold_minutes=threshold_minutes,
        now=now or utc_now(),
        expected_source_sha=expected_source_sha,
    )


def write_observation(path: Path, observation: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise WatchError("OUTPUT_ALREADY_EXISTS")
    text = json.dumps(observation, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True, type=int)
    parser.add_argument("--threshold-minutes", type=int, default=5)
    parser.add_argument("--expected-source-sha")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return rc=2 when the observation requires Runner supply action",
    )
    args = parser.parse_args()

    try:
        observation = observe(
            args.job_id,
            threshold_minutes=args.threshold_minutes,
            expected_source_sha=args.expected_source_sha,
        )
        if args.output:
            write_observation(args.output, observation)
        print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
        if args.strict and observation["action_required"]:
            return 2
        return 0
    except WatchError as exc:
        print(
            json.dumps(
                {
                    "schema": "infra-ansible.ephemeral-runner-queue-observation.v1",
                    "repository": REPO,
                    "status": "ERROR",
                    "reason": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
