import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.models.search import PlaceIntent
from app.services.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("intent.txt")

_prompt = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", "{query}"),
])

_DEFAULT_INTENT = PlaceIntent(
    venue_types=["restaurant", "cafe", "bar", "pub"],
    mood="casual",
    price_level=[1, 2, 3],
    features=[],
    cuisine=[],
)


async def parse_intent(query: str, llm: BaseChatModel) -> PlaceIntent:
    chain = (_prompt | llm.with_structured_output(PlaceIntent)).with_retry(stop_after_attempt=2)
    try:
        result = await chain.ainvoke({"query": query})
        return result
    except Exception:
        logger.exception("intent parsing failed for query %r, using default", query)
        return _DEFAULT_INTENT
