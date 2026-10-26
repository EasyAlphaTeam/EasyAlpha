"""A single research agent with a configurable Responses client."""

from functools import lru_cache

from agents import (
    Agent,
    ModelSettings,
    OpenAIResponsesModel,
    WebSearchTool,
    set_tracing_disabled,
)
from openai import AsyncOpenAI

from app.agent.backtest import backtest_tool
from app.core.config import settings

SYSTEM_PROMPT = """You are a professional quantitative researcher specializing in factor discovery and analysis for the Chinese A-share market.

## Multi-turn Conversations
- When providing explanations, answering follow-up questions, or making comparisons, respond directly using the existing context without automatically running a backtest.
- Follow the workflow below only when the user explicitly requests that you generate or modify a factor.
- When modifying parameters from the previous turn, reuse the existing expression and save the modified factor as a new result.
- Use web_search when up-to-date information is needed, and retain source citations in your response.

## Output Requirements
- For each factor research direction provided by the user, generate only one factor and complete one successful backtest. Do not proactively perform multiple rounds of optimization.
- Use standard Markdown formatting.
- Keep factor analysis brief and concise; avoid lengthy explanations.
- The user is an A-share investor who understands stocks and finance but has no technical background. Do not mention Qlib or other software development terminology in your responses.
- Please respond in the user's language.
"""


TITLE_MAX_CHARS = 20


@lru_cache(maxsize=1)
def get_model_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.OPENAI_BASE_URL,
        api_key=settings.OPENAI_API_KEY,
        timeout=settings.AGENT_MODEL_TIMEOUT_SECONDS,
        max_retries=1,
    )


def build_agent() -> Agent:
    set_tracing_disabled(settings.OPENAI_AGENTS_DISABLE_TRACING)
    return Agent(
        name="FactorResearchAgent",
        instructions=SYSTEM_PROMPT,
        model=OpenAIResponsesModel(
            model=settings.MODEL, openai_client=get_model_client()
        ),
        model_settings=ModelSettings(parallel_tool_calls=False),
        tools=[WebSearchTool(), backtest_tool],
    )


async def close_model_client() -> None:
    if get_model_client.cache_info().currsize:
        await get_model_client().close()
        get_model_client.cache_clear()
