from datetime import datetime, timezone
import logging

from bson import ObjectId
from flask import current_app, request
from flask_jwt_extended import decode_token
from flask_socketio import emit, join_room, leave_room
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from .config import DatabaseConfigurationError
from .db import DatabaseUnavailableError, get_db
from .routes.bookings import _is_booking_participant, _refresh_review_state, _session_state, _session_window

logger = logging.getLogger(__name__)
_socket_users = {}
SUPPORTED_LANGUAGES = {"javascript", "python", "html", "css", "c", "cpp"}
MAX_CODE_LENGTH = 100_000
MAX_SIGNAL_LENGTH = 100_000


def _booking_id(value):
    return ObjectId(value) if isinstance(value, str) and ObjectId.is_valid(value) else None


def _active_booking(booking_id, user_id):
    db = get_db()
    booking = db.bookings.find_one({"_id": booking_id})
    if booking is None or booking.get("status") != "confirmed" or not _is_booking_participant(db, booking, user_id):
        return None
    _refresh_review_state(db, booking)
    if _session_state(booking) != "in_progress":
        return None
    try:
        start, _end, deadline = _session_window(booking)
        now = datetime.now(timezone.utc).astimezone(start.tzinfo)
        if now < start or now > deadline:
            _refresh_review_state(db, booking)
            return None
    except (TypeError, ValueError, KeyError):
        return None
    return db, booking


def register_classroom_socket_handlers(socketio):
    @socketio.on("connect", namespace="/classroom")
    def connect(auth=None):
        token = auth.get("token") if isinstance(auth, dict) else None
        if not isinstance(token, str) or not token:
            return False
        try:
            claims = decode_token(token)
            identity = claims.get("sub")
            if not isinstance(identity, str) or not ObjectId.is_valid(identity):
                return False
            db = get_db()
            if db.users.find_one({"_id": ObjectId(identity)}) is None:
                return False
            _socket_users[request.sid] = ObjectId(identity)
            return True
        except Exception as error:
            logger.info("Classroom socket authentication rejected (%s)", type(error).__name__)
            return False

    @socketio.on("disconnect", namespace="/classroom")
    def disconnect(_reason=None):
        _socket_users.pop(request.sid, None)

    @socketio.on("classroom:join", namespace="/classroom")
    def classroom_join(payload):
        user_id = _socket_users.get(request.sid)
        booking_id = _booking_id(payload.get("bookingId")) if isinstance(payload, dict) else None
        if user_id is None or booking_id is None:
            return {"ok": False, "error": "Unauthorized classroom access"}
        try:
            result = _active_booking(booking_id, user_id)
            if result is None:
                return {"ok": False, "error": "Only assigned participants may join an active session"}
            db, booking = result
            room = f"classroom:{booking_id}"
            recorded = db.bookings.update_one(
                {"_id": booking_id, "status": "confirmed", "session_state": "in_progress", "session_ended_at": {"$exists": False}},
                {"$addToSet": {"session_participants": user_id}},
            )
            if recorded.matched_count != 1:
                return {"ok": False, "error": "This classroom is no longer active"}
            join_room(room)
            emit("classroom:participant", {"userId": str(user_id), "role": "teacher" if _is_teacher(db, booking, user_id) else "learner", "state": "joined"}, to=room, include_self=False)
            emit("classroom:editor-sync", {"code": booking.get("editor_code", ""), "language": booking.get("editor_language", "javascript"), "revision": booking.get("editor_revision", 0)}, to=request.sid)
            return {"ok": True, "room": room}
        except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
            logger.error("Classroom join failed (%s)", type(error).__name__)
            return {"ok": False, "error": "Classroom service is unavailable"}

    @socketio.on("classroom:leave", namespace="/classroom")
    def classroom_leave(payload):
        booking_id = _booking_id(payload.get("bookingId")) if isinstance(payload, dict) else None
        if booking_id is None or _socket_users.get(request.sid) is None:
            return {"ok": False, "error": "Unauthorized classroom access"}
        room = f"classroom:{booking_id}"
        if room not in socketio.server.manager.get_rooms(request.sid, "/classroom"):
            return {"ok": False, "error": "You have not joined this classroom"}
        leave_room(room)
        emit("classroom:participant", {"userId": str(_socket_users[request.sid]), "state": "left"}, to=room)
        return {"ok": True}

    @socketio.on("webrtc:signal", namespace="/classroom")
    def webrtc_signal(payload):
        user_id = _socket_users.get(request.sid)
        booking_id = _booking_id(payload.get("bookingId")) if isinstance(payload, dict) else None
        if not isinstance(payload, dict):
            return {"ok": False, "error": "Invalid signalling event"}
        kind, data = payload.get("kind"), payload.get("data")
        if user_id is None or booking_id is None or kind not in {"offer", "answer", "ice-candidate"}:
            return {"ok": False, "error": "Invalid signalling event"}
        if len(str(data)) > MAX_SIGNAL_LENGTH:
            return {"ok": False, "error": "Signalling payload is too large"}
        try:
            if _active_booking(booking_id, user_id) is None:
                return {"ok": False, "error": "Signalling is allowed only in an active assigned session"}
            room = f"classroom:{booking_id}"
            if room not in socketio.server.manager.get_rooms(request.sid, "/classroom"):
                return {"ok": False, "error": "Join the classroom before signalling"}
            emit("webrtc:signal", {"kind": kind, "data": data}, to=room, include_self=False, namespace="/classroom")
            return {"ok": True}
        except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
            logger.error("Classroom signalling failed (%s)", type(error).__name__)
            return {"ok": False, "error": "Classroom service is unavailable"}

    @socketio.on("webrtc:connected", namespace="/classroom")
    def webrtc_connected(payload):
        user_id = _socket_users.get(request.sid)
        booking_id = _booking_id(payload.get("bookingId")) if isinstance(payload, dict) else None
        if user_id is None or booking_id is None:
            return {"ok": False, "error": "Call status is allowed only in an active assigned session"}
        try:
            if _active_booking(booking_id, user_id) is None:
                return {"ok": False, "error": "Call status is allowed only in an active assigned session"}
            room = f"classroom:{booking_id}"
            if room not in socketio.server.manager.get_rooms(request.sid, "/classroom"):
                return {"ok": False, "error": "Join the classroom before confirming the call"}
            db = get_db()
            result = db.bookings.update_one(
                {"_id": booking_id, "status": "confirmed", "session_state": "in_progress", "session_ended_at": {"$exists": False}},
                {"$addToSet": {"call_participants": user_id}},
            )
            return {"ok": result.matched_count == 1}
        except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
            logger.error("Classroom call-state update failed (%s)", type(error).__name__)
            return {"ok": False, "error": "Classroom service is unavailable"}

    @socketio.on("editor:update", namespace="/classroom")
    def editor_update(payload):
        user_id = _socket_users.get(request.sid)
        booking_id = _booking_id(payload.get("bookingId")) if isinstance(payload, dict) else None
        code = payload.get("code") if isinstance(payload, dict) else None
        language = payload.get("language") if isinstance(payload, dict) else None
        if user_id is None or booking_id is None or not isinstance(code, str) or len(code) > MAX_CODE_LENGTH or language not in SUPPORTED_LANGUAGES:
            return {"ok": False, "error": "Invalid editor update"}
        try:
            result = _active_booking(booking_id, user_id)
            if result is None:
                return {"ok": False, "error": "Editing is allowed only in an active assigned session"}
            db, booking = result
            room = f"classroom:{booking_id}"
            if room not in socketio.server.manager.get_rooms(request.sid, "/classroom"):
                return {"ok": False, "error": "Join the classroom before editing"}
            updated = db.bookings.find_one_and_update(
                {"_id": booking_id, "status": "confirmed", "session_state": "in_progress", "session_ended_at": {"$exists": False}},
                {"$set": {"editor_code": code, "editor_language": language, "editor_updated_at": datetime.now(timezone.utc)}, "$inc": {"editor_revision": 1}},
                return_document=ReturnDocument.AFTER,
            )
            if updated is None:
                return {"ok": False, "error": "This classroom is no longer editable"}
            event = {"code": code, "language": language, "revision": updated.get("editor_revision", 1), "userId": str(user_id)}
            emit("editor:update", event, to=room, namespace="/classroom")
            return {"ok": True, "revision": event["revision"]}
        except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
            logger.error("Classroom editor update failed (%s)", type(error).__name__)
            return {"ok": False, "error": "Classroom service is unavailable"}


def _is_teacher(db, booking, user_id):
    profile = db.teacher_profiles.find_one({"_id": booking.get("teacher_id")})
    return bool(profile and profile.get("user_id") == user_id)
