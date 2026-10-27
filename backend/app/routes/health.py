from flask import Blueprint, current_app, jsonify
from pymongo.errors import PyMongoError

from ..config import DatabaseConfigurationError
from ..db import DatabaseUnavailableError, get_db

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health():
    try:
        db = get_db()
        db.command("ping")
        return jsonify({"status": "ok", "database": "connected"}), 200
    except DatabaseConfigurationError as error:
        current_app.logger.warning("Database configuration is incomplete: %s", error)
        return jsonify({
            "status": "error",
            "database": "disconnected",
            "message": str(error),
        }), 503
    except (DatabaseUnavailableError, PyMongoError) as error:
        current_app.logger.warning("MongoDB health check failed: %s", error)
        return jsonify({
            "status": "error",
            "database": "disconnected",
            "message": "MongoDB is unavailable. Check the server and database settings.",
        }), 503
