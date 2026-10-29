import logging
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised when the configured mail server cannot deliver a message."""


def send_verification_code(recipient, code):
    config = current_app.config
    host = config.get("SMTP_HOST")
    sender = config.get("SMTP_FROM")
    if not host or not sender:
        raise EmailDeliveryError("Email delivery is not configured.")

    message = EmailMessage()
    message["Subject"] = "Verify your SkillSwap email"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        f"Your SkillSwap verification code is {code}. It expires in "
        f"{config.get('OTP_TTL_MINUTES', 10)} minutes. If you did not request this, ignore this email."
    )

    username = config.get("SMTP_USERNAME")
    password = config.get("SMTP_PASSWORD")
    port = int(config.get("SMTP_PORT", 587))
    use_tls = config.get("SMTP_USE_TLS", True)
    if not use_tls:
        logger.warning("SMTP email delivery rejected: TLS is disabled")
        raise EmailDeliveryError("TLS is required for email delivery.")

    phase = "connection"
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as server:
                phase = "SMTP greeting"
                server.ehlo()
                if username:
                    phase = "authentication"
                    server.login(username, password or "")
                phase = "message submission"
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                phase = "SMTP greeting"
                server.ehlo()
                phase = "STARTTLS negotiation"
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                if username:
                    phase = "authentication"
                    server.login(username, password or "")
                phase = "message submission"
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        status = getattr(error, "smtp_code", None)
        if isinstance(status, int):
            logger.warning("SMTP email delivery failed during %s (%s, SMTP status %d)", phase, type(error).__name__, status)
        else:
            logger.warning("SMTP email delivery failed during %s (%s; no SMTP status received)", phase, type(error).__name__)
        raise EmailDeliveryError("Email delivery failed.") from None
