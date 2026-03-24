from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


CASE_TIMEOUT_SECONDS = 120


def _bootstrap_import_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run LLM semantic review for each saved case in an existing run directory."
    )
    parser.add_argument("--run-dir", required=True)
    return parser.parse_args()


def main() -> None:
    _bootstrap_import_path()

    args = _parse_args()
    source_root = Path(args.run_dir).resolve()
    target_root = source_root.parent / f"{source_root.name}_semantic_llm_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    target_root.mkdir(parents=True, exist_ok=True)

    summary = []
    case_dirs = sorted([p for p in source_root.iterdir() if p.is_dir()])
    for case_dir in case_dirs:
        target_case_dir = target_root / case_dir.name
        target_case_dir.mkdir(parents=True, exist_ok=True)

        input_path = case_dir / "input.json"
        output_path = case_dir / "output.json"
        if input_path.exists():
            (target_case_dir / "input.json").write_text(input_path.read_text(encoding="utf-8"), encoding="utf-8")
        if output_path.exists():
            (target_case_dir / "original_output.json").write_text(output_path.read_text(encoding="utf-8"), encoding="utf-8")

        start = time.perf_counter()
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "review_single_saved_case.py"),
                "--case-dir",
                str(case_dir),
            ],
            capture_output=True,
            text=True,
            timeout=CASE_TIMEOUT_SECONDS,
            check=False,
        )
        elapsed = round(time.perf_counter() - start, 3)

        if completed.returncode != 0:
            payload = {
                "ok": False,
                "case_id": case_dir.name,
                "elapsed_seconds": elapsed,
                "error_type": "SubprocessError",
                "error": completed.stderr.strip() or completed.stdout.strip() or "semantic review subprocess failed",
            }
        else:
            payload = _parse_json_from_process_output(completed.stdout, completed.stderr)
            payload["elapsed_seconds"] = elapsed

        (target_case_dir / "semantic_review.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if payload.get("ok"):
            semantic = payload["semantic"]
            summary.append(
                {
                    "case_id": payload["case_id"],
                    "ok": True,
                    "elapsed_seconds": elapsed,
                    "semantic": semantic.get("semantic_verdict"),
                    "review_reason": semantic.get("review_reason"),
                    "spec": payload.get("spec"),
                }
            )
        else:
            summary.append(
                {
                    "case_id": payload.get("case_id", case_dir.name),
                    "ok": False,
                    "elapsed_seconds": elapsed,
                    "semantic": "error",
                    "review_reason": payload.get("error"),
                    "spec": None,
                }
            )

    (target_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target_root / "summary.md").write_text(
        _render_markdown(summary),
        encoding="utf-8",
    )

    print(str(target_root))


def _render_markdown(summary: list[dict]) -> str:
    lines = [
        "# Semantic LLM Review Summary",
        "",
        "| Case | OK | Elapsed (s) | LLM Semantic | Review Reason | Spec |",
        "|---|---:|---:|---|---|---|",
    ]
    for item in summary:
        reason = str(item.get("review_reason", "")).replace("\n", " ").replace("|", "\\|")
        spec = str(item.get("spec", "")).replace("\n", " ").replace("|", "\\|")
        lines.append(
            f"| {item.get('case_id','')} | "
            f"{'yes' if item.get('ok') else 'no'} | "
            f"{item.get('elapsed_seconds','')} | "
            f"{item.get('semantic','')} | "
            f"{reason} | "
            f"{spec} |"
        )
    lines.append("")
    return "\n".join(lines)


def _parse_json_from_process_output(stdout: str, stderr: str) -> dict:
    candidate_lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(candidate_lines):
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    raise RuntimeError(stderr.strip() or stdout.strip() or "semantic review produced no parseable JSON object")


if __name__ == "__main__":
    main()
