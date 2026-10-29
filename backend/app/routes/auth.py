from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from ..config import DatabaseConfigurationError
from ..db import DatabaseUnavailableError, get_db, to_object_id
from ..utils.auth import hash_password, verify_password
from ..utils.email import EmailDeliveryError, send_verification_code

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
    current_app.logger.error("Authentication database operation failed (%s)", type(error).__name__)
    return jsonify({"error": "Authentication service is unavailable"}), 503


def _otp_settings():
    ttl = max(1, int(current_app.config.get("OTP_TTL_MINUTES", 10)))
    cooldown = max(1, int(current_app.config.get("OTP_RESEND_COOLDOWN_SECONDS", 60)))
    attempts = max(1, int(current_app.config.get("OTP_MAX_ATTEMPTS", 5)))
    resends = max(0, int(current_app.config.get("OTP_MAX_RESENDS", 5)))
    return ttl, cooldown, attempts, resends


def _otp_hash(email, salt, code):
    secret = current_app.config.get("OTP_HASH_SECRET", "")
    if len(secret) < 32:
        raise ValueError("OTP_HASH_SECRET must contain at least 32 characters.")
    return hmac.new(secret.encode(), f"{email}:{salt}:{code}".encode(), hashlib.sha256).hexdigest()


def _as_utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _new_otp(email):
    ttl, cooldown, _attempts, _resends = _otp_settings()
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    now = datetime.now(timezone.utc)
    return code, {
        "otp_salt": salt,
        "otp_hash": _otp_hash(email, salt, code),
        "expires_at": now + timedelta(minutes=ttl),
        "resend_after": now + timedelta(seconds=cooldown),
        "attempts": 0,
        "updated_at": now,
    }


def _send_otp(email, code):
    try:
        send_verification_code(email, code)
    except EmailDeliveryError:
        return False
    return True


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
        if db.pending_registrations.find_one({"email": email}) is not None:
            return jsonify({"error": "Registration is pending verification. Enter or resend its code.", "pending": True}), 409

        code, otp_fields = _new_otp(email)
        pending = {
            "full_name": full_name,
            "email": email,
            "password_hash": hash_password(password),
            "role": role,
            "created_at": datetime.now(timezone.utc),
            "resend_count": 0,
            **otp_fields,
        }
        db.pending_registrations.insert_one(pending)
        if not _send_otp(email, code):
            return jsonify({"error": "Could not confirm email delivery. Enter the code if it arrived, or resend after the cooldown.", "pending": True, "retryAfter": _otp_settings()[1]}), 503
        return jsonify({"message": "Verification code sent. Enter it to activate your account.", "retryAfter": _otp_settings()[1]}), 202
    except DuplicateKeyError:
        return jsonify({"error": "Email is already registered"}), 409
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error_response(error)
    except ValueError:
        current_app.logger.error("OTP verification configuration is invalid")
        return jsonify({"error": "Email verification is not configured"}), 503


@auth_bp.post("/verify")
def verify_registration():
    body = _json_object()
    if body is None or not isinstance(body.get("email"), str) or not isinstance(body.get("code"), str):
        return jsonify({"error": "email and code are required"}), 400
    email = body["email"].strip().lower()
    code = body["code"].strip()
    if not EMAIL_PATTERN.fullmatch(email) or not re.fullmatch(r"\d{6}", code):
        return jsonify({"error": "Invalid or expired verification code"}), 400
    try:
        db = get_db()
        pending = db.pending_registrations.find_one({"email": email})
        now = datetime.now(timezone.utc)
        if pending is None:
            return jsonify({"error": "Invalid or expired verification code"}), 400
        _ttl, _cooldown, max_attempts, _max_resends = _otp_settings()
        expiry = _as_utc(pending.get("expires_at"))
        if not expiry or expiry <= now or pending.get("attempts", 0) >= max_attempts:
            db.pending_registrations.delete_one({"_id": pending["_id"]})
            return jsonify({"error": "Invalid or expired verification code"}), 400
        candidate_hash = _otp_hash(email, pending["otp_salt"], code)
        if not hmac.compare_digest(candidate_hash, pending.get("otp_hash", "")):
            updated = db.pending_registrations.update_one(
                {"_id": pending["_id"], "attempts": {"$lt": max_attempts}, "expires_at": {"$gt": now}},
                {"$inc": {"attempts": 1}},
            )
            status = 429 if updated.modified_count == 0 else 400
            return jsonify({"error": "Invalid or expired verification code"}), status

        claimed = db.pending_registrations.find_one_and_delete({
            "_id": pending["_id"], "otp_hash": candidate_hash,
            "expires_at": {"$gt": now}, "attempts": {"$lt": max_attempts},
        })
        if claimed is None:
            return jsonify({"error": "Invalid or expired verification code"}), 400
        new_user = {
            "full_name": claimed["full_name"], "email": claimed["email"],
            "password_hash": claimed["password_hash"], "role": claimed["role"],
            "email_verified": True, "email_verified_at": now, "created_at": now,
        }
        result = db.users.insert_one(new_user)
        new_user["_id"] = result.inserted_id
        return jsonify({"message": "Email verified. You can now log in.", "user": _safe_user(new_user)}), 201
    except DuplicateKeyError:
        return jsonify({"error": "Email is already registered"}), 409
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error_response(error)
    except ValueError:
        current_app.logger.error("OTP verification configuration is invalid")
        return jsonify({"error": "Email verification is not configured"}), 503


@auth_bp.post("/verify/resend")
def resend_registration_code():
    body = _json_object()
    if body is None or not isinstance(body.get("email"), str):
        return jsonify({"error": "email is required"}), 400
    email = body["email"].strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        return jsonify({"error": "A valid email is required"}), 400
    try:
        db = get_db()
        if db.users.find_one({"email": email}):
            return jsonify({"error": "Email is already registered"}), 409
        pending = db.pending_registrations.find_one({"email": email})
        if pending is None:
            return jsonify({"error": "No pending registration was found"}), 404
        _ttl, _cooldown, _attempts, max_resends = _otp_settings()
        now = datetime.now(timezone.utc)
        if pending.get("resend_count", 0) >= max_resends:
            return jsonify({"error": "Resend limit reached. Please restart registration."}), 429
        resend_after = _as_utc(pending.get("resend_after"))
        if resend_after and resend_after > now:
            seconds = max(1, int((resend_after - now).total_seconds()))
            return jsonify({"error": "Please wait before requesting another code.", "retryAfter": seconds}), 429
        code, otp_fields = _new_otp(email)
        updated = db.pending_registrations.find_one_and_update(
            {"_id": pending["_id"], "resend_count": {"$lt": max_resends}, "resend_after": {"$lte": now}},
            {"$set": otp_fields, "$inc": {"resend_count": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            return jsonify({"error": "Please wait before requesting another code."}), 429
        if not _send_otp(email, code):
            return jsonify({"error": "Could not send a verification email. Try again after the resend cooldown."}), 503
        return jsonify({"message": "A new verification code was sent.", "retryAfter": _otp_settings()[1]}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error_response(error)
    except ValueError:
        current_app.logger.error("OTP verification configuration is invalid")
        return jsonify({"error": "Email verification is not configured"}), 503


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
        if user.get("email_verified") is False:
            return jsonify({"error": "Please verify your email before logging in"}), 403

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
