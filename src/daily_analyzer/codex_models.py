"""读取 Codex 公开模型目录，不读取认证或输出身份信息。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from daily_analyzer.config import ConfigurationError


def load_codex_models(path: Path | None = None) -> dict:
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    path = path or home / "models_cache.json"
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
        models = []
        for item in catalog["models"]:
            if item.get("visibility") != "list":
                continue
            efforts = [level["effort"] for level in item["supported_reasoning_levels"]]
            if efforts:
                models.append({"id": item["slug"], "name": item.get("display_name") or item["slug"],
                               "reasoning_efforts": efforts, "default_effort": item["default_reasoning_level"]})
        if not models:
            raise ValueError("目录没有可选模型")
        return {"models": models, "updated_at": catalog.get("fetched_at"), "source": "本机 Codex 模型目录"}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ConfigurationError("无法读取 Codex 模型目录，请先打开本机 Codex CLI 更新模型列表，再重新打开参数设置") from exc
