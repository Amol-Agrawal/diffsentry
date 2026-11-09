"""Model setup."""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel

DEFAULT_MODELS = {
    "gemini": "gemini-3.6-flash",
    "openai": "gpt-4o-mini",
    "ollama": "qwen3:8b",
}


def get_chat_model(
    provider: str | None = None, model: str | None = None, temperature: float = 0.0
) -> BaseChatModel:
    provider = (provider or os.getenv("REVIEW_PROVIDER", "gemini")).lower()
    model = model or os.getenv("REVIEW_MODEL") or DEFAULT_MODELS.get(provider)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("Set GOOGLE_API_KEY (or GEMINI_API_KEY) to use Gemini")
        return ChatGoogleGenerativeAI(model=model, temperature=temperature, google_api_key=key)

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as e:
            raise RuntimeError("pip install 'pr-review-agent[openai]'") from e
        return ChatOpenAI(model=model, temperature=temperature)

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as e:
            raise RuntimeError("pip install 'pr-review-agent[ollama]'") from e
        # thinking off so the reply is just the JSON; default 2k context is too small
        return ChatOllama(model=model, temperature=temperature, reasoning=False, num_ctx=16384)

    raise ValueError(f"Unknown provider: {provider}")
