import os

from openai import AsyncOpenAI

DEFAULT_MODEL = "anthropic/claude-haiku-4-5"

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1",
        )
    return _client


def get_model() -> str:
    return os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)


async def llm_call(messages: list[dict], *, tools: list[dict] | None = None):
    return await get_client().chat.completions.create(
        model=get_model(),
        messages=messages,
        **({"tools": tools, "tool_choice": "auto"} if tools else {}),
    )
