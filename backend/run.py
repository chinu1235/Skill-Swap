import os

from app import create_app


app = create_app()


if __name__ == "__main__":
    try:
        port = int(os.getenv("FLASK_PORT", "5000"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError as error:
        raise SystemExit("FLASK_PORT must be an integer between 1 and 65535.") from error

    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=port,
        debug=os.getenv("FLASK_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"},
        use_reloader=False,
    )
