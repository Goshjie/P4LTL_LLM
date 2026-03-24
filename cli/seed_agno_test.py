from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_import_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _ensure_supported_python() -> None:
    if sys.version_info < (3, 9):
        cur = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        raise SystemExit(
            "Unsupported Python runtime detected: "
            f"{cur}. Please use Python 3.9+ (recommended: .venv/bin/python, currently 3.12).\n"
            "Example: .venv/bin/python seed_agno_test.py"
        )


def main() -> None:
    _bootstrap_import_path()
    _ensure_supported_python()

    from P4LTL_LLM.config import load_api_config

    from agno.agent import Agent
    from agno.models.openai.like import OpenAILike
    from agno.tools import tool

    api_config = load_api_config()

    @tool(name="get_weather")
    def get_weather(city: str) -> str:
        """Get current weather for a city."""
        return f"Weather in {city}: 72F, sunny"

    @tool(name="calculate_tip")
    def calculate_tip(bill: float, tip_percent: float = 18.0) -> float:
        """Calculate tip amount for a restaurant bill."""
        return bill * (tip_percent / 100)

    agent = Agent(
        model=OpenAILike(
            id=api_config.model_id,
            api_key=api_config.api_key,
            base_url=api_config.base_url,
        ),
        markdown=True,
        tools=[get_weather, calculate_tip],
    )

    # This gateway rejects non-streaming calls with HTTP 400.
    agent.print_response("what's the weather like today in guangzhou", stream=api_config.stream)


if __name__ == "__main__":
    main()
