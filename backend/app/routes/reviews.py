from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pymongo.errors import DuplicateKeyError, PyMongoError

from ..config import DatabaseConfigurationError
from ..db import DatabaseUnavailableError, get_db, to_object_id

reviews_bp = Blueprint("reviews", __name__)


def _error(message, status):
    return jsonify({"error": message}), status


def _database_error(error):
    current_app.logger.error("Review API database operation failed: %s", error)
    return _error("Review service is temporarily unavailable", 503)


def _json_object():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def _current_user_id():
    identity = get_jwt_identity()
    return to_object_id(identity)


def recalculate_teacher_rating(db, teacher_id):
    """Aggregate all reviews for a teacher and update their teacher_profile doc."""
    stats = list(
        db.reviews.aggregate([
            {"$match": {"teacher_id": teacher_id}},
            {
                "$group": {
                    "_id": "$teacher_id",
                    "avg_rating": {"$avg": "$rating"},
                    "total_reviews": {"$sum": 1},
                }
            },
        ])
    )
    if stats:
        avg_rating = round(float(stats[0]["avg_rating"]), 1)
        total_reviews = int(stats[0]["total_reviews"])
    else:
        avg_rating = 0.0
        total_reviews = 0

    db.teacher_profiles.update_one(
        {"_id": teacher_id},
        {
            "$set": {
                "rating": avg_rating,
                "rating_count": total_reviews,
                "total_reviews": total_reviews,
            }
        },
    )
    return avg_rating, total_reviews


@reviews_bp.post("")
@jwt_required()
def create_review():
    user_id = _current_user_id()
    if user_id is None:
        return _error("Authorization token is invalid", 401)

    payload = _json_object()
    if payload is None:
        return _error("A JSON object is required", 400)

    raw_booking_id = payload.get("bookingId")
    booking_oid = to_object_id(raw_booking_id)
    if booking_oid is None:
        return _error("bookingId must be a valid ID", 400)

    raw_rating = payload.get("rating")
    try:
        rating = int(raw_rating)
    except (TypeError, ValueError):
        return _error("rating must be an integer between 1 and 5", 400)

    if rating < 1 or rating > 5:
        return _error("rating must be an integer between 1 and 5", 400)

    comment = payload.get("comment")
    if not isinstance(comment, str) or not comment.strip():
        return _error("Written review feedback is required", 400)
    comment = comment.strip()
    if len(comment) > 2000:
        return _error("Feedback must be 2000 characters or fewer", 400)

    try:
        db = get_db()
        booking = db.bookings.find_one({"_id": booking_oid})
        if booking is None:
            return _error("Booking not found", 404)

        if booking.get("learner_id") != user_id:
            return _error("Only the learner who booked this session can review it", 403)

        if booking.get("status") != "completed":
            return _error(
                f"Cannot review booking with status '{booking.get('status')}'. Only completed sessions can be reviewed.",
                400,
            )

        existing = db.reviews.find_one({"booking_id": booking_oid})
        if existing is not None:
            return _error("This booking has already been reviewed", 409)

        teacher_id = booking.get("teacher_id")
        doc = {
            "booking_id": booking_oid,
            "teacher_id": teacher_id,
            "learner_id": user_id,
            "rating": rating,
            "comment": comment,
            "created_at": datetime.now(timezone.utc),
        }

        try:
            result = db.reviews.insert_one(doc)
            doc["_id"] = result.inserted_id
        except DuplicateKeyError:
            return _error("This booking has already been reviewed", 409)

        avg_rating, total_reviews = recalculate_teacher_rating(db, teacher_id)

        learner = db.users.find_one({"_id": user_id})
        learner_name = learner.get("full_name") if learner else "Learner"

        return jsonify({
            "message": "Review submitted successfully",
            "review": {
                "id": str(doc["_id"]),
                "bookingId": str(booking_oid),
                "teacherId": str(teacher_id),
                "learnerId": str(user_id),
                "learnerName": learner_name,
                "rating": rating,
                "comment": comment,
                "createdAt": doc["created_at"].isoformat(),
            },
            "teacherStats": {
                "rating": avg_rating,
                "totalReviews": total_reviews,
            },
        }), 201

    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@reviews_bp.get("")
def list_reviews():
    teacher_param = request.args.get("teacherId", "").strip()
    booking_param = request.args.get("bookingId", "").strip()

    try:
        db = get_db()

        if booking_param:
            b_oid = to_object_id(booking_param)
            if b_oid is None:
                return _error("bookingId must be a valid ID", 400)
            rev = db.reviews.find_one({"booking_id": b_oid})
            if rev is None:
                return jsonify({"review": None}), 200
            learner = db.users.find_one({"_id": rev.get("learner_id")})
            return jsonify({
                "review": {
                    "id": str(rev["_id"]),
                    "bookingId": str(rev["booking_id"]),
                    "teacherId": str(rev.get("teacher_id")),
                    "learnerId": str(rev.get("learner_id")),
                    "learnerName": learner.get("full_name") if learner else "Learner",
                    "rating": int(rev.get("rating", 5)),
                    "comment": rev.get("comment", ""),
                    "createdAt": rev["created_at"].isoformat() if rev.get("created_at") else None,
                }
            }), 200

        filter_criteria = {}
        if teacher_param:
            t_oid = to_object_id(teacher_param)
            if t_oid is None:
                return _error("teacherId must be a valid ID", 400)
            filter_criteria["teacher_id"] = t_oid

        cursor = db.reviews.find(filter_criteria).sort("created_at", -1)
        review_list = list(cursor)

        learner_ids = {r["learner_id"] for r in review_list if "learner_id" in r}
        learners_map = {
            u["_id"]: u.get("full_name", "Learner")
            for u in db.users.find({"_id": {"$in": list(learner_ids)}})
        }

        results = [
            {
                "id": str(r["_id"]),
                "bookingId": str(r.get("booking_id", "")),
                "teacherId": str(r.get("teacher_id", "")),
                "learnerId": str(r.get("learner_id", "")),
                "learnerName": learners_map.get(r.get("learner_id"), "Learner"),
                "rating": int(r.get("rating", 5)),
                "comment": r.get("comment", ""),
                "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in review_list
        ]

        return jsonify({"reviews": results}), 200

    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@reviews_bp.get("/booking/<booking_id>")
def get_booking_review(booking_id):
    b_oid = to_object_id(booking_id)
    if b_oid is None:
        return _error("booking ID must be a valid ID", 400)

    try:
        db = get_db()
        rev = db.reviews.find_one({"booking_id": b_oid})
        if rev is None:
            return _error("Review not found for this booking", 404)
        learner = db.users.find_one({"_id": rev.get("learner_id")})
        return jsonify({
            "review": {
                "id": str(rev["_id"]),
                "bookingId": str(rev["booking_id"]),
                "teacherId": str(rev.get("teacher_id")),
                "learnerId": str(rev.get("learner_id")),
                "learnerName": learner.get("full_name") if learner else "Learner",
                "rating": int(rev.get("rating", 5)),
                "comment": rev.get("comment", ""),
                "createdAt": rev["created_at"].isoformat() if rev.get("created_at") else None,
            }
        }), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)
