from __future__ import annotations

from agent_admin_config import (
    SUPPORTED_RUNTIME_MATRIX,
    is_supported_runtime_combo,
    provider_default_base_url,
    provider_default_model,
    provider_url_matches,
)


def test_deepseek_in_supported_runtime_matrix() -> None:
    assert "deepseek" in SUPPORTED_RUNTIME_MATRIX["claude"]["api"]
    assert is_supported_runtime_combo("claude", "api", "deepseek")


def test_deepseek_in_provider_defaults() -> None:
    assert provider_default_base_url("claude", "deepseek") == "https://api.deepseek.com/anthropic"
    assert provider_default_model("claude", "deepseek") == "deepseek-v4-pro[1M]"
    assert provider_url_matches("claude", "deepseek", "https://api.deepseek.com/anthropic")
