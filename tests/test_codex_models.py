"""模型目录只投影公开可选项，测试不读取真实用户缓存。"""

import json

import pytest

from daily_analyzer.codex_models import load_codex_models
from daily_analyzer.config import ConfigurationError


def test_catalog_filters_hidden_and_does_not_expose_identity(tmp_path, monkeypatch):
    catalog = {"fetched_at": "2026-10-02T03:00:00Z", "identity": {"private": "不可公开"},
               "models": [
                   {"slug": "可选模型", "display_name": "固定展示名", "visibility": "list",
                    "default_reasoning_level": "medium", "supported_reasoning_levels": [{"effort": "medium"}, {"effort": "xhigh"}]},
                   {"slug": "隐藏模型", "visibility": "hide"},
               ]}
    (tmp_path / "models_cache.json").write_text(json.dumps(catalog))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    result = load_codex_models()
    assert result["models"] == [{"id": "可选模型", "name": "固定展示名",
                                  "reasoning_efforts": ["medium", "xhigh"], "default_effort": "medium"}]
    assert result["updated_at"] == catalog["fetched_at"]
    assert "不可公开" not in json.dumps(result, ensure_ascii=False)
    catalog["models"][0]["slug"] = "新型号"
    (tmp_path / "models_cache.json").write_text(json.dumps(catalog))
    assert load_codex_models()["models"][0]["id"] == "新型号"


def test_unavailable_catalog_requires_codex_refresh(tmp_path):
    with pytest.raises(ConfigurationError, match="更新模型列表"):
        load_codex_models(tmp_path / "不存在.json")
    path = tmp_path / "models_cache.json"
    path.write_text('{"models": []}')
    with pytest.raises(ConfigurationError, match="更新模型列表"):
        load_codex_models(path)
