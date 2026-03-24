from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _bootstrap_import_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the online Agno-based intent-to-P4LTL generation pipeline."
    )
    parser.add_argument("--intent", required=True, help="Natural-language verification intent.")
    parser.add_argument("--admin-description", default="", help="Administrator description or extra context.")
    parser.add_argument("--p4", action="append", default=[], help="P4 source path. Repeatable.")
    parser.add_argument("--artifact", action="append", default=[], help="Artifact path. Repeatable.")
    parser.add_argument("--constraint", action="append", default=[], help="Extra constraint. Repeatable.")
    parser.add_argument(
        "--guide-path",
        default="/home/gosh/P4LTL/P4LTL_LLM/docs/P4LTL_user_guide",
        help="Path to the P4LTL user guide.",
    )
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming mode for the Agno model call.")
    parser.add_argument("--no-learning", action="store_true", help="Disable Agno learning integration.")
    parser.add_argument("--learning-db-url", default=None, help="Postgres DB URL for Agno learning.")
    parser.add_argument("--agent-timeout", type=float, default=45.0, help="Timeout in seconds for each online agent stage.")
    parser.add_argument("--agent-retries", type=int, default=2, help="Number of retries for each online agent stage after the first failure.")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="Base delay in seconds before retrying a failed online agent stage.")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode.")
    return parser.parse_args()


def main() -> None:
    _bootstrap_import_path()
    if sys.version_info < (3, 9):
        raise SystemExit("Use Python 3.9+ (recommended: python3.12).")

    from P4LTL_LLM.pipeline.pipeline_protocol import IntentToP4LTLPipeline
    from P4LTL_LLM.pipeline.models import IntentToP4LTLRequest

    args = _parse_args()
    pipeline = IntentToP4LTLPipeline(
        use_agents=True,
        allow_heuristic_fallback=False,
        enable_learning=not args.no_learning,
        learning_db_url=args.learning_db_url,
        agent_stream=not args.no_stream,
        debug_mode=args.debug,
        agent_timeout_seconds=args.agent_timeout,
        agent_max_retries=args.agent_retries,
        agent_retry_delay_seconds=args.retry_delay,
    )
    request = IntentToP4LTLRequest(
        intent=args.intent,
        admin_description=args.admin_description,
        p4_program_paths=args.p4,
        artifact_paths=args.artifact,
        extra_constraints=args.constraint,
        guide_path=args.guide_path,
        max_rounds=args.max_rounds,
    )
    result = pipeline.generate_and_validate(request)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
