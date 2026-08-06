from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI


def build_chat_model(provider: str, model: str, api_key: str) -> BaseChatModel:
    provider = provider.lower()
    if provider == "openai":
        return ChatOpenAI(model=model, api_key=api_key, temperature=0.7)
    if provider == "anthropic":
        # Newer Claude models (Opus 4.7+) reject temperature/top_p/top_k with HTTP 400.
        # Omit sampling params so the request stays valid across Anthropic model generations.
        return ChatAnthropic(model=model, api_key=api_key)
    if provider == "google":
        return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0.7)
    raise ValueError(f"Unsupported provider: {provider}")


async def test_connection(provider: str, model: str, api_key: str) -> str:
    llm = build_chat_model(provider, model, api_key)
    result = await llm.ainvoke("Reply with exactly: ok")
    content = getattr(result, "content", str(result))
    if isinstance(content, list):
        content = " ".join(str(x) for x in content)
    return str(content)[:200]
