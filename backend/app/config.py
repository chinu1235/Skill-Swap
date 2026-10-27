import os


def load_config():
    """Read runtime configuration from environment variables."""
    origins = os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
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
        "FRONTEND_ORIGINS": [origin.strip() for origin in origins.split(",") if origin.strip()],
        "FLASK_HOST": os.getenv("FLASK_HOST", "127.0.0.1"),
        "FLASK_PORT": os.getenv("FLASK_PORT", "5000"),
        "FLASK_DEBUG": os.getenv("FLASK_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"},
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
