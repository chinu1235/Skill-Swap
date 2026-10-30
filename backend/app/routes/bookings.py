from datetime import date, datetime, time, timedelta, timezone
import base64
import hashlib
import hmac
import re
import time as clock_time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pymongo.errors import DuplicateKeyError, PyMongoError

from ..config import DatabaseConfigurationError
from ..db import DatabaseUnavailableError, get_db, to_object_id
from ..extensions import socketio
from ..utils.code_execution import (
    ExecutionConfigurationError,
    ExecutionServiceError,
    UnsupportedExecutionLanguage,
    execute_code,
)

bookings_bp = Blueprint("bookings", __name__)
VALID_STATUSES = {"pending", "confirmed", "completed", "cancelled"}
VALID_DURATIONS = {30, 45, 60, 90, 120}
VALID_SESSION_TYPES = {"online": "Online", "offline": "Offline"}
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")
DUPLICATE_SLOT_ERROR = "This teacher is already booked for the selected date and time."


def _error(message, status):
    return jsonify({"error": message}), status


def _database_error(error):
    current_app.logger.error("Booking API database operation failed (%s)", type(error).__name__)
    return _error("Booking service is temporarily unavailable", 503)


def _json_object():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def _current_user_id():
    identity = get_jwt_identity()
    return to_object_id(identity)


def _load_user(db, user_id):
    return db.users.find_one({"_id": user_id})


def _booking_payload(doc, learner_name=None, teacher_name=None, skill_doc=None, party=None):
    payload = {
        "id": str(doc["_id"]),
        "skill": (
            {
                "id": str(skill_doc["_id"]),
                "skillName": skill_doc.get("skill_name"),
                "category": skill_doc.get("category"),
            }
            if skill_doc
            else None
        ),
        "bookingDate": doc["booking_date"],
        "bookingTime": doc["booking_time"],
        "durationMinutes": doc["duration_minutes"],
        "sessionType": doc["session_type"],
        "notes": doc.get("notes"),
        "status": doc["status"],
        "createdAt": doc["created_at"].isoformat() if doc.get("created_at") else None,
        "sessionState": _session_state(doc),
        "sessionStartedAt": doc.get("session_started_at").isoformat() if doc.get("session_started_at") else None,
        "sessionEndedAt": doc.get("session_ended_at").isoformat() if doc.get("session_ended_at") else None,
    }

    if party == "teacher":
        payload["teacher"] = (
            {"id": str(doc["teacher_id"]), "name": teacher_name}
            if doc.get("teacher_id") and teacher_name
            else None
        )
    elif party == "learner":
        payload["learner"] = (
            {"id": str(doc["learner_id"]), "name": learner_name}
            if doc.get("learner_id") and learner_name
            else None
        )
    elif party == "both":
        payload["learner"] = (
            {"id": str(doc["learner_id"]), "name": learner_name}
            if learner_name
            else None
        )
        payload["teacher"] = (
            {"id": str(doc["teacher_id"]), "name": teacher_name}
            if teacher_name
            else None
        )
    return payload


def _session_window(booking):
    zone_name = current_app.config.get("SESSION_TIMEZONE", "Asia/Kolkata")
    try:
        tz = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError:
        fixed_zones = {
            "UTC": timezone.utc,
            "Etc/UTC": timezone.utc,
            "Asia/Kolkata": timezone(timedelta(hours=5, minutes=30)),
            "Asia/Calcutta": timezone(timedelta(hours=5, minutes=30)),
        }
        if zone_name not in fixed_zones:
            raise ValueError("Timezone data is unavailable for SESSION_TIMEZONE")
        tz = fixed_zones[zone_name]
    start_date = date.fromisoformat(booking["booking_date"])
    start_time = time.fromisoformat(booking["booking_time"])
    start = datetime.combine(start_date, start_time, tzinfo=tz)
    end = start + timedelta(minutes=int(booking["duration_minutes"]))
    deadline = end + timedelta(minutes=max(0, int(current_app.config.get("SESSION_END_GRACE_MINUTES", 15))))
    return start, end, deadline


def _session_state(booking, now=None):
    if booking.get("session_state") == "review_required":
        return "review_required"
    if booking.get("session_ended_at") or booking.get("status") == "completed":
        return "completed"
    if booking.get("session_started_at"):
        try:
            _start, _end, deadline = _session_window(booking)
            if (now or datetime.now(timezone.utc)).astimezone(deadline.tzinfo) > deadline:
                return "review_required"
        except (TypeError, ValueError, KeyError):
            return "review_required"
        return "in_progress"
    return "not_started"


def _refresh_review_state(db, booking, now=None):
    state = _session_state(booking, now)
    if state == "review_required" and booking.get("session_started_at") and not booking.get("session_ended_at"):
        db.bookings.update_one(
            {"_id": booking["_id"], "status": "confirmed", "session_started_at": {"$exists": True}, "session_ended_at": {"$exists": False}},
            {"$set": {"session_state": "review_required"}},
        )
        booking["session_state"] = "review_required"
    elif state == "in_progress":
        booking["session_state"] = state
    return booking


def _is_booking_participant(db, booking, user_id):
    if booking.get("learner_id") == user_id:
        return True
    profile = db.teacher_profiles.find_one({"_id": booking.get("teacher_id")})
    return bool(profile and profile.get("user_id") == user_id)


def _ice_servers(user_id):
    ice = [{"urls": url} for url in current_app.config.get("STUN_URLS", [])]
    turn_urls = current_app.config.get("TURN_URLS", [])
    shared_secret = current_app.config.get("TURN_SHARED_SECRET", "")
    if turn_urls and shared_secret:
        expires = int(clock_time.time()) + max(300, int(current_app.config.get("TURN_CREDENTIAL_TTL_SECONDS", 3600)))
        username = f"{expires}:{user_id}"
        credential = base64.b64encode(hmac.new(shared_secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
        ice.append({"urls": turn_urls, "username": username, "credential": credential})
    return ice


def _validate_booking(payload):
    allowed = {
        "teacherId", "skillId", "bookingDate", "bookingTime",
        "durationMinutes", "sessionType", "notes",
    }
    if "learnerId" in payload:
        return None, "learnerId is determined from the authenticated user"
    if set(payload) - allowed:
        return None, "The request contains unsupported booking fields"

    raw_teacher_id = payload.get("teacherId")
    teacher_id = to_object_id(str(raw_teacher_id) if raw_teacher_id is not None else "")
    if teacher_id is None:
        return None, "teacherId must be a valid ID"

    raw_skill_id = payload.get("skillId")
    skill_id = None
    if raw_skill_id is not None:
        skill_id = to_object_id(str(raw_skill_id))
        if skill_id is None:
            return None, "skillId must be a valid ID when provided"

    raw_date = payload.get("bookingDate")
    if not isinstance(raw_date, str) or not DATE_PATTERN.fullmatch(raw_date):
        return None, "bookingDate must use YYYY-MM-DD format"
    try:
        booking_date = date.fromisoformat(raw_date)
    except ValueError:
        return None, "bookingDate is not a valid calendar date"

    raw_time = payload.get("bookingTime")
    if not isinstance(raw_time, str) or not TIME_PATTERN.fullmatch(raw_time):
        return None, "bookingTime must use HH:MM format"
    try:
        parsed_time = datetime.strptime(raw_time, "%H:%M").time()
    except ValueError:
        return None, "bookingTime is not a valid time"

    now = datetime.now()
    if booking_date < now.date() or (
        booking_date == now.date()
        and datetime.combine(booking_date, parsed_time) <= now
    ):
        return None, "Booking date and time must be in the future"

    duration = payload.get("durationMinutes", 60)
    if isinstance(duration, bool) or not isinstance(duration, int) or duration not in VALID_DURATIONS:
        return None, "durationMinutes must be one of 30, 45, 60, 90, or 120"

    session_type = payload.get("sessionType", "Online")
    if not isinstance(session_type, str):
        return None, "sessionType must be Online or Offline"
    session_type = VALID_SESSION_TYPES.get(session_type.strip().lower())
    if session_type is None:
        return None, "sessionType must be Online or Offline"

    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        return None, "notes must be a string or null"
    if isinstance(notes, str) and len(notes) > 60000:
        return None, "notes must be 60000 characters or fewer"

    return {
        "teacher_id": teacher_id,
        "skill_id": skill_id,
        "booking_date": booking_date,
        "booking_time": parsed_time,
        "duration_minutes": duration,
        "session_type": session_type,
        "notes": notes.strip() if isinstance(notes, str) else None,
    }, None


@bookings_bp.post("")
@jwt_required()
def create_booking():
    user_id = _current_user_id()
    if user_id is None:
        return _error("Authorization token is invalid", 401)

    payload = _json_object()
    if payload is None:
        return _error("A JSON object is required", 400)
    booking, validation_error = _validate_booking(payload)
    if validation_error:
        return _error(validation_error, 400)

    try:
        db = get_db()
        user = _load_user(db, user_id)
        if user is None:
            return _error("User not found", 404)
        if user.get("role") != "learner":
            return _error("Only learners can create bookings", 403)

        teacher_profile = db.teacher_profiles.find_one({"_id": booking["teacher_id"]})
        if teacher_profile is None:
            return _error("Teacher not found", 404)

        if booking["skill_id"] is not None:
            skill = db.skills.find_one({"_id": booking["skill_id"]})
            if skill is None:
                return _error("Skill not found", 404)

            # Check if teacher profile embeds this skill
            teacher_skills = teacher_profile.get("skills", [])
            teaches_skill = any(s.get("skill_id") == booking["skill_id"] for s in teacher_skills)
            if not teaches_skill:
                return _error("The selected teacher does not teach this skill.", 400)

        # Check existing active booking on same teacher, date, and time
        date_str = booking["booking_date"].isoformat()
        time_str = booking["booking_time"].strftime("%H:%M:%S")

        conflict = db.bookings.find_one({
            "teacher_id": booking["teacher_id"],
            "booking_date": date_str,
            "booking_time": time_str,
            "status": {"$ne": "cancelled"},
        })
        if conflict is not None:
            return _error(DUPLICATE_SLOT_ERROR, 409)

        booking_doc = {
            "learner_id": user_id,
            "teacher_id": booking["teacher_id"],
            "skill_id": booking["skill_id"],
            "booking_date": date_str,
            "booking_time": time_str,
            "duration_minutes": booking["duration_minutes"],
            "session_type": booking["session_type"],
            "notes": booking["notes"],
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
        }

        try:
            result = db.bookings.insert_one(booking_doc)
            booking_doc["_id"] = result.inserted_id
        except DuplicateKeyError:
            return _error(DUPLICATE_SLOT_ERROR, 409)

        return jsonify({
            "message": "Booking created successfully",
            "booking": {
                "id": str(booking_doc["_id"]),
                "teacherId": str(booking["teacher_id"]),
                "skillId": str(booking["skill_id"]) if booking["skill_id"] else None,
                "bookingDate": date_str,
                "bookingTime": time_str,
                "durationMinutes": booking["duration_minutes"],
                "sessionType": booking["session_type"],
                "notes": booking["notes"],
                "status": "pending",
            },
        }), 201
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@bookings_bp.get("/my")
@jwt_required()
def get_my_bookings():
    user_id = _current_user_id()
    if user_id is None:
        return _error("Authorization token is invalid", 401)

    try:
        db = get_db()
        user = _load_user(db, user_id)
        if user is None:
            return _error("User not found", 404)
        if user.get("role") != "learner":
            return _error("Only learners can view learner bookings", 403)

        bookings_cursor = db.bookings.find({"learner_id": user_id}).sort([
            ("booking_date", 1),
            ("booking_time", 1),
        ])
        booking_list = list(bookings_cursor)

        # Batch load teachers and skills
        teacher_ids = {b["teacher_id"] for b in booking_list if "teacher_id" in b}
        skill_ids = {b["skill_id"] for b in booking_list if b.get("skill_id")}

        teacher_profiles = {tp["_id"]: tp for tp in db.teacher_profiles.find({"_id": {"$in": list(teacher_ids)}})}
        teacher_user_ids = {tp["user_id"] for tp in teacher_profiles.values() if "user_id" in tp}
        users_map = {u["_id"]: u for u in db.users.find({"_id": {"$in": list(teacher_user_ids)}})}
        skills_map = {s["_id"]: s for s in db.skills.find({"_id": {"$in": list(skill_ids)}})}

        booking_ids = [b["_id"] for b in booking_list]
        reviews_map = {
            r["booking_id"]: r
            for r in db.reviews.find({"booking_id": {"$in": booking_ids}})
        }

        result = []
        for b in booking_list:
            _refresh_review_state(db, b)
            tp = teacher_profiles.get(b.get("teacher_id"))
            teacher_name = None
            if tp:
                u = users_map.get(tp.get("user_id"))
                if u:
                    teacher_name = u.get("full_name")
            s = skills_map.get(b.get("skill_id"))
            payload = _booking_payload(b, teacher_name=teacher_name, skill_doc=s, party="teacher")
            r = reviews_map.get(b["_id"])
            if r:
                payload["review"] = {
                    "id": str(r["_id"]),
                    "rating": int(r.get("rating", 5)),
                    "comment": r.get("comment", ""),
                }
                payload["hasReview"] = True
            else:
                payload["review"] = None
                payload["hasReview"] = False
            result.append(payload)

        return jsonify({"bookings": result}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@bookings_bp.get("/received")
@jwt_required()
def get_received_bookings():
    user_id = _current_user_id()
    if user_id is None:
        return _error("Authorization token is invalid", 401)

    try:
        db = get_db()
        user = _load_user(db, user_id)
        if user is None:
            return _error("User not found", 404)
        if user.get("role") != "teacher":
            return _error("Only teachers can view received bookings", 403)

        profile = db.teacher_profiles.find_one({"user_id": user_id})
        if profile is None:
            return _error("Teacher profile not found", 404)

        bookings_cursor = db.bookings.find({"teacher_id": profile["_id"]}).sort([
            ("booking_date", 1),
            ("booking_time", 1),
        ])
        booking_list = list(bookings_cursor)

        learner_ids = {b["learner_id"] for b in booking_list if "learner_id" in b}
        skill_ids = {b["skill_id"] for b in booking_list if b.get("skill_id")}

        learners_map = {u["_id"]: u for u in db.users.find({"_id": {"$in": list(learner_ids)}})}
        skills_map = {s["_id"]: s for s in db.skills.find({"_id": {"$in": list(skill_ids)}})}

        result = []
        for b in booking_list:
            _refresh_review_state(db, b)
            learner = learners_map.get(b.get("learner_id"))
            learner_name = learner.get("full_name") if learner else None
            s = skills_map.get(b.get("skill_id"))
            result.append(_booking_payload(b, learner_name=learner_name, skill_doc=s, party="learner"))

        return jsonify({"bookings": result}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@bookings_bp.get("/<booking_id>")
@jwt_required()
def get_booking(booking_id):
    b_oid = to_object_id(booking_id)
    if b_oid is None:
        return _error("Booking not found", 404)

    user_id = _current_user_id()
    if user_id is None:
        return _error("Authorization token is invalid", 401)

    try:
        db = get_db()
        b = db.bookings.find_one({"_id": b_oid})
        if b is None:
            return _error("Booking not found", 404)

        profile = db.teacher_profiles.find_one({"_id": b.get("teacher_id")})
        teacher_user_id = profile.get("user_id") if profile else None

        is_learner = b.get("learner_id") == user_id
        is_teacher = teacher_user_id == user_id
        if not is_learner and not is_teacher:
            return _error("You do not have access to this booking", 403)

        _refresh_review_state(db, b)

        learner = db.users.find_one({"_id": b.get("learner_id")})
        learner_name = learner.get("full_name") if learner else None

        teacher_user = db.users.find_one({"_id": teacher_user_id}) if teacher_user_id else None
        teacher_name = teacher_user.get("full_name") if teacher_user else None

        skill_doc = db.skills.find_one({"_id": b.get("skill_id")}) if b.get("skill_id") else None

        return jsonify({"booking": _booking_payload(b, learner_name=learner_name, teacher_name=teacher_name, skill_doc=skill_doc, party="both")}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@bookings_bp.put("/<booking_id>/status")
@jwt_required()
def update_booking_status(booking_id):
    b_oid = to_object_id(booking_id)
    if b_oid is None:
        return _error("Booking not found", 404)

    user_id = _current_user_id()
    if user_id is None:
        return _error("Authorization token is invalid", 401)

    payload = _json_object()
    if payload is None or not isinstance(payload.get("status"), str):
        return _error("status is required", 400)
    new_status = payload["status"].strip().lower()
    if new_status not in VALID_STATUSES:
        return _error("status must be pending, confirmed, completed, or cancelled", 400)
    if new_status == "completed":
        return _error("A booking can be completed only by ending its started classroom session", 400)

    try:
        db = get_db()
        b = db.bookings.find_one({"_id": b_oid})
        if b is None:
            return _error("Booking not found", 404)

        actor = _load_user(db, user_id)
        if actor is None:
            return _error("User not found", 404)

        profile = db.teacher_profiles.find_one({"_id": b.get("teacher_id")})
        teacher_user_id = profile.get("user_id") if profile else None

        teacher_owner = teacher_user_id == user_id
        learner_owner = b.get("learner_id") == user_id
        if not teacher_owner and not learner_owner:
            return _error("You do not have access to this booking", 403)

        current_status = b.get("status")
        if actor.get("role") == "teacher" and teacher_owner:
            allowed = {
                "pending": {"confirmed", "cancelled"},
                "confirmed": {"cancelled"},
            }
        elif actor.get("role") == "learner" and learner_owner:
            allowed = {
                "pending": {"cancelled"},
                "confirmed": {"cancelled"},
            }
        else:
            allowed = {}

        if new_status not in allowed.get(current_status, set()):
            return _error(
                f"Status cannot change from {current_status} to {new_status} for this user",
                400,
            )
        if b.get("session_started_at") and new_status == "cancelled":
            return _error("A started session cannot be cancelled", 400)

        db.bookings.update_one(
            {"_id": b_oid, "status": current_status},
            {"$set": {"status": new_status}},
        )
        return jsonify({
            "message": "Booking status updated successfully",
            "booking": {"id": str(b_oid), "status": new_status},
        }), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@bookings_bp.delete("/<booking_id>")
@jwt_required()
def cancel_booking(booking_id):
    b_oid = to_object_id(booking_id)
    if b_oid is None:
        return _error("Booking not found", 404)

    user_id = _current_user_id()
    if user_id is None:
        return _error("Authorization token is invalid", 401)

    try:
        db = get_db()
        b = db.bookings.find_one({"_id": b_oid})
        if b is None:
            return _error("Booking not found", 404)

        actor = _load_user(db, user_id)
        if actor is None:
            return _error("User not found", 404)

        profile = db.teacher_profiles.find_one({"_id": b.get("teacher_id")})
        teacher_user_id = profile.get("user_id") if profile else None

        is_owner = (
            actor.get("role") == "learner" and b.get("learner_id") == user_id
        ) or (
            actor.get("role") == "teacher" and teacher_user_id == user_id
        )
        if not is_owner:
            return _error("You do not have access to cancel this booking", 403)
        if b.get("status") not in {"pending", "confirmed"}:
            return _error("Only pending or confirmed bookings can be cancelled", 400)
        if b.get("session_started_at"):
            return _error("A started session cannot be cancelled", 400)

        db.bookings.update_one(
            {"_id": b_oid, "status": b.get("status")},
            {"$set": {"status": "cancelled"}},
        )
        return jsonify({"message": "Booking cancelled successfully"}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@bookings_bp.get("/<booking_id>/classroom")
@jwt_required()
def get_classroom(booking_id):
    booking_oid = to_object_id(booking_id)
    user_id = _current_user_id()
    if booking_oid is None:
        return _error("Booking not found", 404)
    if user_id is None:
        return _error("Authorization token is invalid", 401)
    try:
        db = get_db()
        booking = db.bookings.find_one({"_id": booking_oid})
        if booking is None:
            return _error("Booking not found", 404)
        if not _is_booking_participant(db, booking, user_id):
            return _error("You do not have access to this classroom", 403)
        if booking.get("status") not in {"confirmed", "completed"}:
            return _error("Only confirmed or completed bookings have a classroom", 409)
        _refresh_review_state(db, booking)
        teacher_profile = db.teacher_profiles.find_one({"_id": booking.get("teacher_id")})
        teacher_user = db.users.find_one({"_id": teacher_profile.get("user_id")}) if teacher_profile else None
        learner = db.users.find_one({"_id": booking.get("learner_id")})
        start, end, deadline = _session_window(booking)
        return jsonify({
            "booking": _booking_payload(
                booking,
                learner_name=learner.get("full_name") if learner else None,
                teacher_name=teacher_user.get("full_name") if teacher_user else None,
                party="both",
            ),
            "session": {
                "state": _session_state(booking),
                "scheduledStart": start.isoformat(),
                "scheduledEnd": end.isoformat(),
                "endDeadline": deadline.isoformat(),
            },
            "iceServers": _ice_servers(user_id) if _session_state(booking) == "in_progress" else [{"urls": url} for url in current_app.config.get("STUN_URLS", [])],
            "editor": {"code": booking.get("editor_code", ""), "language": booking.get("editor_language", "javascript"), "revision": booking.get("editor_revision", 0)},
            "canStart": booking.get("status") == "confirmed" and not booking.get("session_started_at") and start <= datetime.now(start.tzinfo) <= end,
            "canEnd": booking.get("status") == "confirmed" and _session_state(booking) == "in_progress",
        }), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@bookings_bp.post("/<booking_id>/classroom/run")
@jwt_required()
def run_classroom_code(booking_id):
    booking_oid = to_object_id(booking_id)
    user_id = _current_user_id()
    payload = _json_object()
    if booking_oid is None:
        return _error("Booking not found", 404)
    if user_id is None:
        return _error("Authorization token is invalid", 401)
    if not isinstance(payload, dict) or set(payload) - {"code", "language", "stdin"}:
        return _error("Execution request is invalid", 400)
    source, language, stdin = payload.get("code"), payload.get("language"), payload.get("stdin", "")
    if not isinstance(source, str) or not isinstance(stdin, str) or language not in {"javascript", "python", "c", "cpp"}:
        return _error("Execution request is invalid or this language is not executable", 400)
    if len(source.encode("utf-8")) > current_app.config["CODE_EXECUTION_MAX_SOURCE_BYTES"] or len(stdin.encode("utf-8")) > current_app.config["CODE_EXECUTION_MAX_STDIN_BYTES"]:
        return _error("Source code or input exceeds the execution limit", 413)
    try:
        db = get_db()
        booking = db.bookings.find_one({"_id": booking_oid})
        if booking is None:
            return _error("Booking not found", 404)
        if not _is_booking_participant(db, booking, user_id):
            return _error("You do not have access to this classroom", 403)
        _refresh_review_state(db, booking)
        if booking.get("status") != "confirmed" or _session_state(booking) != "in_progress":
            return _error("Code can run only during an active scheduled classroom session", 409)
        start, _end, deadline = _session_window(booking)
        now = datetime.now(timezone.utc).astimezone(start.tzinfo)
        if now < start or now > deadline:
            _refresh_review_state(db, booking, now)
            return _error("The scheduled classroom execution window has closed", 409)
        try:
            result = execute_code(language, source, stdin)
        except UnsupportedExecutionLanguage:
            return _error("This language is not enabled by the configured execution service", 422)
        except ExecutionConfigurationError:
            return _error("Isolated code execution is not configured", 503)
        except ExecutionServiceError as error:
            current_app.logger.warning("Classroom execution provider failed (%s)", str(error))
            return _error("The isolated execution service is unavailable or timed out", 502)
        latest = db.bookings.find_one({"_id": booking_oid})
        if latest is None or not _is_booking_participant(db, latest, user_id):
            return _error("You do not have access to this classroom", 403)
        _refresh_review_state(db, latest)
        if latest.get("status") != "confirmed" or _session_state(latest) != "in_progress":
            return _error("The classroom ended while code was running; output was not shared", 409)
        current_time = datetime.now(timezone.utc).astimezone(start.tzinfo)
        if current_time > deadline:
            _refresh_review_state(db, latest, current_time)
            return _error("The scheduled classroom execution window has closed", 409)
        run_id = str(ObjectId())
        result["runId"] = run_id
        result["language"] = language
        socketio.emit("execution:result", result, to=f"classroom:{booking_oid}", namespace="/classroom")
        return jsonify(result), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@bookings_bp.post("/<booking_id>/session/start")
@jwt_required()
def start_classroom_session(booking_id):
    booking_oid = to_object_id(booking_id)
    user_id = _current_user_id()
    if booking_oid is None:
        return _error("Booking not found", 404)
    if user_id is None:
        return _error("Authorization token is invalid", 401)
    try:
        db = get_db()
        booking = db.bookings.find_one({"_id": booking_oid})
        if booking is None:
            return _error("Booking not found", 404)
        actor = _load_user(db, user_id)
        profile = db.teacher_profiles.find_one({"_id": booking.get("teacher_id")})
        if not actor or actor.get("role") != "teacher" or not profile or profile.get("user_id") != user_id:
            return _error("Only the assigned teacher can start this session", 403)
        if booking.get("status") != "confirmed" or booking.get("session_started_at") or booking.get("session_state") == "review_required":
            return _error("This confirmed session cannot be started", 409)
        start, end, deadline = _session_window(booking)
        now = datetime.now(start.tzinfo)
        if now < start or now > end:
            return _error("The classroom can be started only during its scheduled time window", 409)
        result = db.bookings.update_one(
            {"_id": booking_oid, "status": "confirmed", "session_started_at": {"$exists": False}},
            {"$set": {"session_started_at": now.astimezone(timezone.utc), "session_end_deadline": deadline.astimezone(timezone.utc), "session_state": "in_progress"}},
        )
        if result.modified_count != 1:
            return _error("This session has already started or changed", 409)
        return jsonify({"message": "Classroom session started", "sessionState": "in_progress"}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@bookings_bp.post("/<booking_id>/session/end")
@jwt_required()
def end_classroom_session(booking_id):
    booking_oid = to_object_id(booking_id)
    user_id = _current_user_id()
    if booking_oid is None:
        return _error("Booking not found", 404)
    if user_id is None:
        return _error("Authorization token is invalid", 401)
    try:
        db = get_db()
        booking = db.bookings.find_one({"_id": booking_oid})
        if booking is None:
            return _error("Booking not found", 404)
        actor = _load_user(db, user_id)
        profile = db.teacher_profiles.find_one({"_id": booking.get("teacher_id")})
        if not actor or actor.get("role") != "teacher" or not profile or profile.get("user_id") != user_id:
            return _error("Only the assigned teacher can end this session", 403)
        if booking.get("status") != "confirmed" or not booking.get("session_started_at") or booking.get("session_ended_at"):
            return _error("Only a started session can be ended", 409)
        start, _end, deadline = _session_window(booking)
        now = datetime.now(start.tzinfo)
        if now > deadline:
            _refresh_review_state(db, booking, now)
            return _error("The session missed its end window and requires review", 409)
        result = db.bookings.update_one(
            {"_id": booking_oid, "status": "confirmed", "session_started_at": {"$exists": True}, "session_ended_at": {"$exists": False}},
            {"$set": {"session_ended_at": now.astimezone(timezone.utc), "session_state": "completed", "status": "completed"}},
        )
        if result.modified_count != 1:
            return _error("This session has already ended or changed", 409)
        socketio.emit(
            "classroom:session_ended",
            {"bookingId": str(booking_oid), "sessionState": "completed"},
            to=f"classroom:{booking_oid}",
            namespace="/classroom",
        )
        return jsonify({"message": "Classroom session ended", "sessionState": "completed"}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)
