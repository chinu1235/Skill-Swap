from datetime import datetime, timezone
import re

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from pymongo.errors import DuplicateKeyError, PyMongoError

from ..config import DatabaseConfigurationError
from ..db import DatabaseUnavailableError, get_db, to_object_id
from ..utils.auth import hash_password, verify_password

auth_bp = Blueprint("auth", __name__)
VALID_ROLES = {"learner", "teacher"}
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


def _safe_user(doc):
    return {
        "id": str(doc["_id"]),
        "fullName": doc["full_name"],
        "email": doc["email"],
        "role": doc["role"],
    }


def _json_object():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def _database_error_response(error):
    current_app.logger.error("Authentication database operation failed: %s", error)
    return jsonify({"error": "Authentication service is unavailable"}), 503


@auth_bp.post("/register")
def register():
    body = _json_object()
    if body is None:
        return jsonify({"error": "A JSON request body is required"}), 400

    full_name = body.get("fullName")
    email = body.get("email")
    password = body.get("password")
    role = body.get("role")

    if not isinstance(full_name, str) or not full_name.strip():
        return jsonify({"error": "fullName is required"}), 400
    full_name = full_name.strip()
    if len(full_name) > 100:
        return jsonify({"error": "fullName must be 100 characters or fewer"}), 400
    if not isinstance(email, str) or not email.strip():
        return jsonify({"error": "email is required"}), 400
    email = email.strip().lower()
    if len(email) > 150 or not EMAIL_PATTERN.fullmatch(email):
        return jsonify({"error": "A valid email is required"}), 400
    if not isinstance(password, str) or not password:
        return jsonify({"error": "password is required"}), 400
    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400
    if not isinstance(role, str) or role not in VALID_ROLES:
        return jsonify({"error": "role must be learner or teacher"}), 400

    try:
        db = get_db()
        if db.users.find_one({"email": email}) is not None:
            return jsonify({"error": "Email is already registered"}), 409

        new_user = {
            "full_name": full_name,
            "email": email,
            "password_hash": hash_password(password),
            "role": role,
            "created_at": datetime.now(timezone.utc),
        }
        result = db.users.insert_one(new_user)
        new_user["_id"] = result.inserted_id

        return jsonify({
            "message": "Registration successful",
            "user": _safe_user(new_user),
        }), 201
    except DuplicateKeyError:
        return jsonify({"error": "Email is already registered"}), 409
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error_response(error)


@auth_bp.post("/login")
def login():
    body = _json_object()
    if body is None:
        return jsonify({"error": "A JSON request body is required"}), 400

    email = body.get("email")
    password = body.get("password")
    if not isinstance(email, str) or not email.strip():
        return jsonify({"error": "email is required"}), 400
    if not isinstance(password, str) or not password:
        return jsonify({"error": "password is required"}), 400

    email = email.strip().lower()
    if len(email) > 150 or not EMAIL_PATTERN.fullmatch(email):
        return jsonify({"error": "Invalid email or password"}), 401

    try:
        db = get_db()
        user = db.users.find_one({"email": email})
        if user is None or not verify_password(user["password_hash"], password):
            return jsonify({"error": "Invalid email or password"}), 401

        if not current_app.config.get("JWT_SECRET_KEY"):
            current_app.logger.error("JWT_SECRET_KEY is not configured")
            return jsonify({"error": "Authentication is not configured"}), 503

        access_token = create_access_token(
            identity=str(user["_id"]),
            additional_claims={"role": user["role"]},
        )
        return jsonify({
            "message": "Login successful",
            "access_token": access_token,
            "user": _safe_user(user),
        }), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error_response(error)


@auth_bp.get("/me")
@jwt_required()
def current_user():
    identity = get_jwt_identity()
    user_id = to_object_id(identity)
    if user_id is None:
        return jsonify({"error": "Authorization token is invalid"}), 401

    try:
        db = get_db()
        user = db.users.find_one({"_id": user_id})
        if user is None:
            return jsonify({"error": "User not found"}), 404
        return jsonify({"user": _safe_user(user)}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error_response(error)
