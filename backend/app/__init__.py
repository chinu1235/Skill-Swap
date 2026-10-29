import logging
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from .config import load_config
from .db import DatabaseUnavailableError, close_db_connection, get_db, init_db_indexes
from .extensions import jwt, socketio
from .routes.auth import auth_bp
from .routes.bookings import bookings_bp
from .routes.health import health_bp
from .routes.reviews import reviews_bp
from .routes.skills import skills_bp
from .routes.teachers import teachers_bp
from .classroom_socket import register_classroom_socket_handlers


def create_app(test_config=None):
    """Build the Flask app; MongoDB connection is lazy and pooled."""
    backend_dir = Path(__file__).resolve().parents[1]
    load_dotenv(backend_dir / ".env", override=True)

    app = Flask(__name__)
    app.config.from_mapping(load_config())
    if test_config:
        app.config.update(test_config)

    jwt.init_app(app)
    socketio.init_app(
        app,
        cors_allowed_origins=app.config["FRONTEND_ORIGINS"],
        message_queue=app.config.get("SOCKETIO_MESSAGE_QUEUE") or None,
    )
    register_classroom_socket_handlers(socketio)

    logging.basicConfig(level=logging.INFO)
    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": app.config["FRONTEND_ORIGINS"],
                "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            }
        },
    )

    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(bookings_bp, url_prefix="/api/bookings")
    app.register_blueprint(reviews_bp, url_prefix="/api/reviews")
    app.register_blueprint(skills_bp, url_prefix="/api/skills")
    app.register_blueprint(teachers_bp, url_prefix="/api/teachers")
    app.teardown_appcontext(close_db_connection)

    frontend_dist = backend_dir.parent / "dist"

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path):
        from flask import send_from_directory

        requested_file = frontend_dist / path

        if path and requested_file.is_file():
            return send_from_directory(frontend_dist, path)

        if path.startswith("api/"):
            return jsonify({
                "error": {
                    "code": "not_found",
                    "message": "API endpoint not found."
                }
            }), 404

        return send_from_directory(frontend_dist, "index.html")

    # Initialize indexes if MongoDB is available
    with app.app_context():
        try:
            db = get_db()
            init_db_indexes(db)
        except Exception as error:
            app.logger.warning("Initial MongoDB index sync skipped (DB may be offline): %s", type(error).__name__)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return jsonify({
            "error": {
                "code": error.name.lower().replace(" ", "_"),
                "message": error.description,
            }
        }), error.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.exception("Unhandled API error", exc_info=error)
        return jsonify({
            "error": {
                "code": "internal_server_error",
                "message": "An unexpected server error occurred.",
            }
        }), 500

    @jwt.unauthorized_loader
    def handle_missing_jwt(_reason):
        return jsonify({"error": "Authorization token is required"}), 401

    @jwt.invalid_token_loader
    def handle_invalid_jwt(_reason):
        return jsonify({"error": "Authorization token is invalid"}), 401

    @jwt.expired_token_loader
    def handle_expired_jwt(_jwt_header, _jwt_payload):
        return jsonify({"error": "Authorization token has expired"}), 401

    return app
