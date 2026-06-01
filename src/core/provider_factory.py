from __future__ import annotations

import os
from typing import Callable

from dotenv import load_dotenv

from src.core.llm_provider import LLMProvider


class ProviderConfigurationError(RuntimeError):
    """Raised when the configured LLM provider cannot be created safely."""


ProviderFactory = Callable[[], LLMProvider]


def create_llm_provider() -> LLMProvider:
    """Create the configured LLM provider from .env settings."""
    load_dotenv()

    provider = os.getenv("DEFAULT_PROVIDER", "openai").strip().lower()
    model = os.getenv("DEFAULT_MODEL", "").strip()

    if provider == "openai":
        from src.core.openai_provider import OpenAIProvider

        api_key = _required_env("OPENAI_API_KEY", "your_openai_api_key_here")
        return OpenAIProvider(model_name=model or "gpt-4o", api_key=api_key)

    if provider in {"google", "gemini"}:
        from src.core.gemini_provider import GeminiProvider

        api_key = _required_env("GEMINI_API_KEY", "your_gemini_api_key_here")
        return GeminiProvider(model_name=model or "gemini-1.5-flash", api_key=api_key)

    if provider in {"dashscope", "qwen"}:
        from src.core.dashscope_provider import DashScopeProvider

        api_key = _required_any_env(
            ("DASHSCOPE_API_KEY", "GWEN_API_KEY", "QWEN_API_KEY"),
            "your_dashscope_api_key_here",
        )
        base_url = os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        ).strip()
        return DashScopeProvider(
            model_name=model or "qwen3-coder-flash",
            api_key=api_key,
            base_url=base_url,
        )

    if provider == "local":
        from src.core.local_provider import LocalProvider

        model_path = os.getenv("LOCAL_MODEL_PATH", "./models/Phi-3-mini-4k-instruct-q4.gguf").strip()
        if not model_path:
            raise ProviderConfigurationError("LOCAL_MODEL_PATH is required when DEFAULT_PROVIDER=local.")
        return LocalProvider(model_path=model_path)

    raise ProviderConfigurationError(
        "DEFAULT_PROVIDER must be one of: openai, google, gemini, dashscope, qwen, local."
    )


def _required_env(name: str, placeholder: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value == placeholder:
        raise ProviderConfigurationError(f"{name} is required for the selected LLM provider.")
    return value


def _required_any_env(names: tuple[str, ...], placeholder: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value and value != placeholder:
            return value
    joined = " or ".join(names)
    raise ProviderConfigurationError(f"{joined} is required for the selected LLM provider.")
