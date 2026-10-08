"""Excerpt of mimiq2/config.py for security review — only the code shown here."""




def install_log_redaction() -> None:
    """Redact the bot token from ALL log output."""
    import logging as _logging
    token = BOT_TOKEN
    if not token:
        return

    class _Redact(_logging.Filter):

        def filter(self, record: _logging.LogRecord) -> bool:
            if token in str(record.msg):
                record.msg = str(record.msg).replace(token, '***')
            if isinstance(record.args, tuple):
                record.args = tuple((str(a).replace(token, '***') if token in str(a) else a for a in record.args))
            return True
    f = _Redact()
    for h in _logging.root.handlers:
        h.addFilter(f)
