import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_feedback(
    http_client,
    place_name: str,
    query: str | None,
    mode: str,
    comment: str,
    user_email: str | None,
) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return

    query_display = f'"{esc_html(query)}"' if query else "—"
    user_display = user_email or "anonymous"

    text = (
        f"🍽 <b>Beta Feedback</b>\n"
        f"Mode: <code>{esc_html(mode)}</code>\n"
        f"Place: {esc_html(place_name)}\n"
        f"Query: {query_display}\n"
        f"—\n"
        f"{esc_html(comment)}\n"
        f"—\n"
        f"User: {esc_html(user_display)}"
    )

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        resp = await http_client.post(url, json={
            "chat_id": settings.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
        })
        if not resp.is_success:
            logger.warning("Telegram API error %s: %s", resp.status_code, resp.text)
    except Exception as e:
        logger.warning("Failed to send Telegram feedback notification: %s", e)


def esc_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
