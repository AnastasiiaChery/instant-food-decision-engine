import logging
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from app.models.search import PlaceIntent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "intent.txt").read_text()

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


async def parse_intent(query: str, llm: ChatGroq) -> PlaceIntent:
    chain = (_prompt | llm.with_structured_output(PlaceIntent)).with_retry(stop_after_attempt=2)
    try:
        result = await chain.ainvoke({"query": query})
        return result
    except Exception:
        logger.exception("intent parsing failed for query %r, using default", query)
        return _DEFAULT_INTENT
