from datetime import date, datetime, time, timezone
import re

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pymongo.errors import DuplicateKeyError, PyMongoError

from ..config import DatabaseConfigurationError
from ..db import DatabaseUnavailableError, get_db, to_object_id

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
    current_app.logger.error("Booking API database operation failed: %s", error)
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
                "confirmed": {"completed", "cancelled"},
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

        db.bookings.update_one(
            {"_id": b_oid, "status": b.get("status")},
            {"$set": {"status": "cancelled"}},
        )
        return jsonify({"message": "Booking cancelled successfully"}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)
