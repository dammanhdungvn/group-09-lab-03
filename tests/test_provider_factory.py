from src.core.dashscope_provider import DashScopeProvider
from src.core.provider_factory import create_llm_provider


def test_provider_factory_creates_dashscope_provider(monkeypatch):
    monkeypatch.setenv("DEFAULT_PROVIDER", "dashscope")
    monkeypatch.setenv("DEFAULT_MODEL", "qwen3-coder-flash")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

    provider = create_llm_provider()

    assert isinstance(provider, DashScopeProvider)
    assert provider.model_name == "qwen3-coder-flash"
    assert provider.base_url == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
