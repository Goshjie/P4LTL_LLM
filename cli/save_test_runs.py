from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


MAX_TYPEERROR_RETRIES = 10
CASE_STUDY_TIMEOUT_SECONDS = 600
SAGEFUZZ_TIMEOUT_SECONDS = 120


def _bootstrap_import_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def main() -> None:
    _bootstrap_import_path()

    from P4LTL_LLM import load_default_benchmark_cases

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = Path("/home/gosh/P4LTL/P4LTL_LLM/run") / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    selected_ids = [
        "case-study:Blink",
        "case-study:Bfs",
        "case-study:CoDel",
        "case-study:Dfs",
        "case-study:P4NIS",
        "case-study:P4sp",
        "case-study:NdN",
        "sagefuzz:firewall",
        "sagefuzz:link_monitor",
        "sagefuzz:heavy-hitter",
        "sagefuzz:fast-reroute",
        "sagefuzz:load-balancing",
    ]

    cases = {case.case_id: case for case in load_default_benchmark_cases()}
    summary: list[dict] = []

    for index, case_id in enumerate(selected_ids, start=1):
        case = cases[case_id]
        case_dir = run_root / f"{index:02d}_{_slug(case_id)}"
        case_dir.mkdir(parents=True, exist_ok=True)

        input_payload = {
            "case_id": case.case_id,
            "suite": case.suite,
            "intent": case.intent,
            "admin_description": case.admin_description,
            "p4_program_paths": case.p4_program_paths,
            "artifact_paths": case.artifact_paths,
            "control_plane_paths": case.control_plane_paths,
            "extra_constraints": case.extra_constraints,
            "guide_path": "/home/gosh/P4LTL/P4LTL_LLM/docs/P4LTL_user_guide",
            "max_rounds": 2,
        }
        (case_dir / "input.json").write_text(
            json.dumps(input_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        attempts_payload: list[dict] = []
        output_payload: dict = {}
        status: dict = {}
        case_start = time.perf_counter()

        for attempt_no in range(1, MAX_TYPEERROR_RETRIES + 1):
            attempt_start = time.perf_counter()
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).resolve().parent / "run_single_case.py"),
                        "--case-id",
                        case.case_id,
                        "--guide-path",
                        "/home/gosh/P4LTL/P4LTL_LLM/docs/P4LTL_user_guide",
                        "--max-rounds",
                        "2",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=CASE_STUDY_TIMEOUT_SECONDS if case.case_id.startswith("case-study:") else SAGEFUZZ_TIMEOUT_SECONDS,
                    check=False,
                )
                attempt_elapsed = time.perf_counter() - attempt_start
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "case subprocess failed")

                response = json.loads(completed.stdout)
                if response.get("ok"):
                    output_payload = response["result"]
                else:
                    raise RuntimeError(f"{response.get('error_type', 'Error')}: {response.get('error', '')}")

                attempt_payload = {
                    "attempt": attempt_no,
                    "elapsed_seconds": round(attempt_elapsed, 3),
                    "result": output_payload,
                }
                attempts_payload.append(attempt_payload)
                (case_dir / f"attempt_{attempt_no:02d}.json").write_text(
                    json.dumps(attempt_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                status = {
                    "case_id": case.case_id,
                    "attempts": attempt_no,
                    "elapsed_seconds": round(time.perf_counter() - case_start, 3),
                    "ok": output_payload.get("ok", False),
                    "syntax": output_payload.get("final_validation", {}).get("syntax", {}).get("valid", False),
                    "context": output_payload.get("final_validation", {}).get("context", {}).get("valid", False),
                    "semantic": output_payload.get("final_validation", {}).get("semantic", {}).get("semantic_verdict", "missing"),
                    "spec": output_payload.get("final_spec_text"),
                }
                break
            except Exception as exc:
                attempt_elapsed = time.perf_counter() - attempt_start
                attempt_payload = {
                    "attempt": attempt_no,
                    "elapsed_seconds": round(attempt_elapsed, 3),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                attempts_payload.append(attempt_payload)
                (case_dir / f"attempt_{attempt_no:02d}.json").write_text(
                    json.dumps(attempt_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                is_type_error = ("TypeError" in str(type(exc).__name__)) or ("TypeError" in str(exc))
                if (not is_type_error) or attempt_no >= MAX_TYPEERROR_RETRIES:
                    output_payload = attempt_payload
                    status = {
                        "case_id": case.case_id,
                        "attempts": attempt_no,
                        "elapsed_seconds": round(time.perf_counter() - case_start, 3),
                        "ok": False,
                        "syntax": False,
                        "context": False,
                        "semantic": "error",
                        "spec": None,
                        "error_type": type(exc).__name__,
                    }
                    break

        (case_dir / "output.json").write_text(
            json.dumps(output_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (case_dir / "attempts_summary.json").write_text(
            json.dumps(attempts_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary.append(status)

    (run_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_root / "summary.md").write_text(
        _render_markdown_summary(summary),
        encoding="utf-8",
    )

    print(str(run_root))


def _slug(value: str) -> str:
    return value.replace(":", "_").replace("/", "_").replace("-", "_")


def _render_markdown_summary(summary: list[dict]) -> str:
    lines = [
        "# Test Summary",
        "",
        "| Case | OK | Attempts | Elapsed (s) | Syntax | Context | Semantic | Spec / Error |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for item in summary:
        spec = item.get("spec")
        error = item.get("error")
        spec_or_error = spec if spec else error if error else ""
        spec_or_error = str(spec_or_error).replace("\n", " ").replace("|", "\\|")
        lines.append(
            f"| {item.get('case_id','')} | "
            f"{'yes' if item.get('ok') else 'no'} | "
            f"{item.get('attempts','')} | "
            f"{item.get('elapsed_seconds','')} | "
            f"{'yes' if item.get('syntax') else 'no'} | "
            f"{'yes' if item.get('context') else 'no'} | "
            f"{item.get('semantic','')} | "
            f"{spec_or_error} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
