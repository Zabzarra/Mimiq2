"""Excerpt of mimiq2/main_bot.py for security review — only the code shown here."""




def register_handlers(app, transport_provider=None) -> None:
    """Register the Telegram ConversationHandlers."""
    try:
        from handlers import register_all
    except ModuleNotFoundError:
        logger.warning('[bot] handlers package not present — running with no UI')
        return
    register_all(app, transport_provider=transport_provider)
