from __future__ import annotations

import json
from dataclasses import dataclass
from os import getenv
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "api_config.json"


@dataclass
class APIConfig:
    model_id: str
    api_key: str
    base_url: str
    stream: bool = True


def load_api_config(path: str | Path = DEFAULT_CONFIG_PATH) -> APIConfig:
    config_path = Path(path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))

    model_id = getenv("AGNO_MODEL_ID", raw["model_id"])
    api_key = getenv("AGNO_API_KEY", raw["api_key"])
    base_url = getenv("AGNO_BASE_URL", raw["base_url"])
    stream = _coerce_bool(getenv("AGNO_STREAM"), raw.get("stream", True))

    return APIConfig(
        model_id=model_id,
        api_key=api_key,
        base_url=base_url,
        stream=stream,
    )


def _coerce_bool(env_value: str | None, default: bool) -> bool:
    if env_value is None:
        return default
    return env_value.strip().lower() not in {"0", "false", "no", "off"}
