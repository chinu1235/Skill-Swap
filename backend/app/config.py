import os


def load_config():
    """Read runtime configuration from environment variables."""
    origins = os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    frontend_origins = [origin.strip() for origin in origins.split(",") if origin.strip()]
    flask_debug = os.getenv("FLASK_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}
    if flask_debug:
        for origin in ("http://localhost:5174", "http://127.0.0.1:5174"):
            if origin not in frontend_origins:
                frontend_origins.append(origin)
    mongodb_uri = os.getenv("MONGODB_URI", "").strip()
    mongodb_db_name = os.getenv("MONGODB_DB_NAME", "").strip()

    if not mongodb_uri:
        mongodb_uri = "mongodb://127.0.0.1:27017"
    if not mongodb_db_name:
        mongodb_db_name = os.getenv("DB_NAME", "skillswap_db").strip() or "skillswap_db"

    return {
        "MONGODB_URI": mongodb_uri,
        "MONGODB_DB_NAME": mongodb_db_name,
        # Retain legacy MySQL keys for migration script use if needed
        "DB_HOST": os.getenv("DB_HOST", "").strip(),
        "DB_PORT": os.getenv("DB_PORT", "3306").strip(),
        "DB_NAME": os.getenv("DB_NAME", "").strip(),
        "DB_USER": os.getenv("DB_USER", "").strip(),
        "DB_PASSWORD": os.getenv("DB_PASSWORD", ""),
        "JWT_SECRET_KEY": os.getenv("JWT_SECRET_KEY", "").strip(),
        "JWT_ACCESS_TOKEN_EXPIRES": int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_SECONDS", "3600")),
        "FRONTEND_ORIGINS": frontend_origins,
        "FLASK_HOST": os.getenv("FLASK_HOST", "127.0.0.1"),
        "FLASK_PORT": os.getenv("FLASK_PORT", "5000"),
        "FLASK_DEBUG": flask_debug,
        "SESSION_TIMEZONE": os.getenv("SESSION_TIMEZONE", "Asia/Kolkata").strip(),
        "SESSION_END_GRACE_MINUTES": int(os.getenv("SESSION_END_GRACE_MINUTES", "15")),
        "OTP_HASH_SECRET": os.getenv("OTP_HASH_SECRET", "").strip(),
        "OTP_TTL_MINUTES": int(os.getenv("OTP_TTL_MINUTES", "10")),
        "OTP_RESEND_COOLDOWN_SECONDS": int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "60")),
        "OTP_MAX_ATTEMPTS": int(os.getenv("OTP_MAX_ATTEMPTS", "5")),
        "OTP_MAX_RESENDS": int(os.getenv("OTP_MAX_RESENDS", "5")),
        "SMTP_HOST": os.getenv("SMTP_HOST", "").strip(),
        "SMTP_PORT": int(os.getenv("SMTP_PORT", "587")),
        "SMTP_USERNAME": os.getenv("SMTP_USERNAME", "").strip(),
        "SMTP_PASSWORD": os.getenv("SMTP_PASSWORD", ""),
        "SMTP_FROM": os.getenv("SMTP_FROM", "").strip(),
        "SMTP_USE_TLS": os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"},
        "STUN_URLS": [item.strip() for item in os.getenv("STUN_URLS", "stun:stun.l.google.com:19302").split(",") if item.strip()],
        "TURN_URLS": [item.strip() for item in os.getenv("TURN_URLS", "").split(",") if item.strip()],
        "TURN_SHARED_SECRET": os.getenv("TURN_SHARED_SECRET", ""),
        "TURN_CREDENTIAL_TTL_SECONDS": int(os.getenv("TURN_CREDENTIAL_TTL_SECONDS", "3600")),
        "SOCKETIO_MESSAGE_QUEUE": os.getenv("SOCKETIO_MESSAGE_QUEUE", "").strip(),
        "CODE_EXECUTION_API_URL": os.getenv("CODE_EXECUTION_API_URL", "").strip(),
        "CODE_EXECUTION_API_KEY": os.getenv("CODE_EXECUTION_API_KEY", ""),
        "CODE_EXECUTION_API_KEY_HEADER": os.getenv("CODE_EXECUTION_API_KEY_HEADER", "X-Auth-Token").strip(),
        "CODE_EXECUTION_MAX_SOURCE_BYTES": int(os.getenv("CODE_EXECUTION_MAX_SOURCE_BYTES", "50000")),
        "CODE_EXECUTION_MAX_STDIN_BYTES": int(os.getenv("CODE_EXECUTION_MAX_STDIN_BYTES", "5000")),
    }


class DatabaseConfigurationError(ValueError):
    """Raised when required database environment values are missing or invalid."""


def get_database_settings(config):
    mongodb_uri = config.get("MONGODB_URI", "").strip()
    db_name = config.get("MONGODB_DB_NAME", "").strip()

    if not mongodb_uri:
        raise DatabaseConfigurationError("MONGODB_URI environment variable is required.")
    if not db_name:
        raise DatabaseConfigurationError("MONGODB_DB_NAME environment variable is required.")

    return {
        "uri": mongodb_uri,
        "database": db_name,
    }
