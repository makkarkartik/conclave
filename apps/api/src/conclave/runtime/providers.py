from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI


def build_chat_model(provider: str, model: str, api_key: str) -> BaseChatModel:
    provider = provider.lower()
    if provider == "fake":
        from conclave.config import settings

        if not settings.enable_fake_provider:
            raise ValueError("Fake provider disabled (set CONCLAVE_ENABLE_FAKE_PROVIDER=1)")
        from conclave.runtime.fake import FakeDeliberator

        return FakeDeliberator(model=model or "fake", delay=settings.fake_turn_delay)
    if provider == "openai":
        # Responses API + no explicit temperature: newer OpenAI reasoning models
        # reject sampling params, and gpt-5.6+ rejects function tools on Chat
        # Completions ("use /v1/responses or set reasoning_effort to 'none'").
        return ChatOpenAI(model=model, api_key=api_key, use_responses_api=True)
    if provider == "anthropic":
        # Newer Claude models (Opus 4.7+) reject temperature/top_p/top_k with HTTP 400.
        # Omit sampling params so the request stays valid across Anthropic model generations.
        # max_tokens: LangChain's default (1024) truncates full proposals mid-write.
        return ChatAnthropic(model=model, api_key=api_key, max_tokens=16000)
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
