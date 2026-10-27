from datetime import datetime, timezone
import math
import re

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pymongo.errors import DuplicateKeyError, PyMongoError

from ..config import DatabaseConfigurationError
from ..db import DatabaseUnavailableError, get_db, to_object_id

teachers_bp = Blueprint("teachers", __name__)
PROFILE_FIELDS = {
    "bio": ("bio", None),
    "experience": ("experience", 100),
    "teachingStyle": ("teaching_style", 255),
}


def _error(message, status):
    return jsonify({"error": message}), status


def _database_error(error):
    current_app.logger.error("Teacher API database operation failed: %s", error)
    return _error("Teacher service is temporarily unavailable", 503)


def _json_object():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def _profile_values(payload):
    unknown = set(payload) - set(PROFILE_FIELDS)
    if unknown:
        return None, "Only bio, experience, and teachingStyle can be changed"

    values = {}
    for api_name, (column, maximum) in PROFILE_FIELDS.items():
        if api_name not in payload:
            continue
        value = payload[api_name]
        if value is not None and not isinstance(value, str):
            return None, f"{api_name} must be a string or null"
        if value is not None:
            value = value.strip()
            if maximum is not None and len(value) > maximum:
                return None, f"{api_name} must be {maximum} characters or fewer"
        values[column] = value
    return values, None


def _current_user_id():
    identity = get_jwt_identity()
    return to_object_id(identity)


def _load_teacher_user(db, user_id):
    user = db.users.find_one({"_id": user_id})
    if user is None:
        return None, _error("User not found", 404)
    if user.get("role") != "teacher":
        return None, _error("Only teachers can modify teacher profiles", 403)
    return user, None


def _teacher_payload(doc, user_info=None):
    if user_info is None:
        user_info = doc.get("user") or {}
    skills_list = [
        {
            "id": str(s.get("skill_id", s.get("_id", ""))),
            "skillName": s.get("skill_name", ""),
            "category": s.get("category", ""),
        }
        for s in sorted(doc.get("skills", []), key=lambda x: x.get("skill_name", ""))
    ]
    return {
        "id": str(doc["_id"]),
        "userId": str(doc["user_id"]),
        "name": user_info.get("full_name", ""),
        "bio": doc.get("bio"),
        "experience": doc.get("experience"),
        "teachingStyle": doc.get("teaching_style"),
        "rating": float(doc.get("rating", 0.0)),
        "ratingCount": int(doc.get("total_reviews", doc.get("rating_count", 0))),
        "totalReviews": int(doc.get("total_reviews", doc.get("rating_count", 0))),
        "totalSessions": int(doc.get("total_sessions", 0)),
        "skills": skills_list,
    }


@teachers_bp.get("")
def list_teachers():
    search = request.args.get("search", "").strip()
    skill = request.args.get("skill", "").strip()
    category = request.args.get("category", "").strip()
    min_rating_value = request.args.get("minRating")

    min_rating = None
    if min_rating_value is not None:
        try:
            min_rating = float(min_rating_value)
        except ValueError:
            return _error("minRating must be a number between 0 and 5", 400)
        if not math.isfinite(min_rating) or not 0 <= min_rating <= 5:
            return _error("minRating must be a number between 0 and 5", 400)

    try:
        db = get_db()
        pipeline = [
            {
                "$lookup": {
                    "from": "users",
                    "localField": "user_id",
                    "foreignField": "_id",
                    "as": "user",
                }
            },
            {"$unwind": "$user"},
        ]

        match_criteria = {}
        if min_rating is not None:
            match_criteria["rating"] = {"$gte": min_rating}

        if skill:
            match_criteria["skills.skill_name"] = {"$regex": f"^{re.escape(skill)}$", "$options": "i"}

        if category:
            match_criteria["skills.category"] = {"$regex": f"^{re.escape(category)}$", "$options": "i"}

        if search:
            escaped_search = re.escape(search)
            match_criteria["$or"] = [
                {"user.full_name": {"$regex": escaped_search, "$options": "i"}},
                {"bio": {"$regex": escaped_search, "$options": "i"}},
                {"skills.skill_name": {"$regex": escaped_search, "$options": "i"}},
            ]

        if match_criteria:
            pipeline.append({"$match": match_criteria})

        pipeline.append({"$sort": {"rating": -1, "user.full_name": 1}})

        cursor = db.teacher_profiles.aggregate(pipeline)
        teachers = [_teacher_payload(doc) for doc in cursor]
        return jsonify({"teachers": teachers}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@teachers_bp.get("/<teacher_id>")
def get_teacher(teacher_id):
    profile_id = to_object_id(teacher_id)
    if profile_id is None:
        return _error("Teacher profile not found", 404)

    try:
        db = get_db()
        profile = db.teacher_profiles.find_one({"_id": profile_id})
        if profile is None:
            return _error("Teacher profile not found", 404)

        user = db.users.find_one({"_id": profile["user_id"]})
        payload = _teacher_payload(profile, user)

        reviews_cursor = db.reviews.find({"teacher_id": profile["_id"]}).sort("created_at", -1)
        review_docs = list(reviews_cursor)
        learner_ids = {r["learner_id"] for r in review_docs if "learner_id" in r}
        learners_map = {
            u["_id"]: u.get("full_name", "Learner")
            for u in db.users.find({"_id": {"$in": list(learner_ids)}})
        }
        reviews = [
            {
                "id": str(r["_id"]),
                "rating": int(r.get("rating", 5)),
                "comment": r.get("comment", ""),
                "learnerName": learners_map.get(r.get("learner_id"), "Learner"),
                "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in review_docs
        ]
        payload["reviews"] = reviews
        payload["ratingCount"] = len(reviews)
        payload["totalReviews"] = len(reviews)

        return jsonify({"teacher": payload}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@teachers_bp.post("/profile")
@jwt_required()
def create_teacher_profile():
    user_id = _current_user_id()
    if user_id is None:
        return _error("Authorization token is invalid", 401)

    payload = _json_object()
    if payload is None:
        return _error("A JSON object is required", 400)
    values, validation_error = _profile_values(payload)
    if validation_error:
        return _error(validation_error, 400)

    try:
        db = get_db()
        _, role_error = _load_teacher_user(db, user_id)
        if role_error:
            return role_error

        if db.teacher_profiles.find_one({"user_id": user_id}) is not None:
            return _error("Teacher profile already exists", 409)

        doc = {
            "user_id": user_id,
            "bio": values.get("bio"),
            "experience": values.get("experience"),
            "teaching_style": values.get("teaching_style"),
            "rating": 0.0,
            "total_sessions": 0,
            "skills": [],
            "created_at": datetime.now(timezone.utc),
        }
        result = db.teacher_profiles.insert_one(doc)
        doc["_id"] = result.inserted_id

        return jsonify({
            "message": "Teacher profile created",
            "teacher": {
                "id": str(doc["_id"]),
                "userId": str(user_id),
                "bio": values.get("bio"),
                "experience": values.get("experience"),
                "teachingStyle": values.get("teaching_style"),
                "rating": 0.0,
                "totalSessions": 0,
                "skills": [],
            },
        }), 201
    except DuplicateKeyError:
        return _error("Teacher profile already exists", 409)
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@teachers_bp.put("/profile")
@jwt_required()
def update_teacher_profile():
    user_id = _current_user_id()
    if user_id is None:
        return _error("Authorization token is invalid", 401)

    payload = _json_object()
    if payload is None:
        return _error("A JSON object is required", 400)
    values, validation_error = _profile_values(payload)
    if validation_error:
        return _error(validation_error, 400)
    if not values:
        return _error("At least one profile field is required", 400)

    try:
        db = get_db()
        _, role_error = _load_teacher_user(db, user_id)
        if role_error:
            return role_error

        profile = db.teacher_profiles.find_one({"user_id": user_id})
        if profile is None:
            return _error("Teacher profile not found", 404)

        db.teacher_profiles.update_one(
            {"_id": profile["_id"]},
            {"$set": values},
        )
        updated = db.teacher_profiles.find_one({"_id": profile["_id"]})

        return jsonify({
            "message": "Teacher profile updated",
            "teacher": {
                "id": str(updated["_id"]),
                "userId": str(updated["user_id"]),
                "bio": updated.get("bio"),
                "experience": updated.get("experience"),
                "teachingStyle": updated.get("teaching_style"),
                "rating": float(updated.get("rating", 0.0)),
                "totalSessions": int(updated.get("total_sessions", 0)),
            },
        }), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@teachers_bp.post("/profile/skills")
@jwt_required()
def add_teacher_skill():
    user_id = _current_user_id()
    if user_id is None:
        return _error("Authorization token is invalid", 401)

    payload = _json_object()
    if payload is None:
        return _error("A JSON object is required", 400)

    raw_skill_id = payload.get("skillId")
    skill_oid = to_object_id(str(raw_skill_id) if raw_skill_id is not None else "")
    if skill_oid is None:
        return _error("skillId must be a valid ID", 400)

    try:
        db = get_db()
        _, role_error = _load_teacher_user(db, user_id)
        if role_error:
            return role_error

        profile = db.teacher_profiles.find_one({"user_id": user_id})
        if profile is None:
            return _error("Teacher profile not found", 404)

        skill = db.skills.find_one({"_id": skill_oid})
        if skill is None:
            return _error("Skill not found", 404)

        current_skills = profile.get("skills", [])
        if any(s.get("skill_id") == skill_oid for s in current_skills):
            return _error("Teacher already has this skill", 409)

        embedded_skill = {
            "skill_id": skill["_id"],
            "skill_name": skill["skill_name"],
            "category": skill["category"],
        }
        db.teacher_profiles.update_one(
            {"_id": profile["_id"]},
            {"$push": {"skills": embedded_skill}},
        )
        return jsonify({"message": "Skill added successfully"}), 201
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)


@teachers_bp.delete("/profile/skills/<skill_id>")
@jwt_required()
def remove_teacher_skill(skill_id):
    skill_oid = to_object_id(skill_id)
    if skill_oid is None:
        return _error("skill ID must be a valid ID", 400)

    user_id = _current_user_id()
    if user_id is None:
        return _error("Authorization token is invalid", 401)

    try:
        db = get_db()
        _, role_error = _load_teacher_user(db, user_id)
        if role_error:
            return role_error

        profile = db.teacher_profiles.find_one({"user_id": user_id})
        if profile is None:
            return _error("Teacher profile not found", 404)

        current_skills = profile.get("skills", [])
        if not any(s.get("skill_id") == skill_oid for s in current_skills):
            return _error("Teacher skill relationship not found", 404)

        db.teacher_profiles.update_one(
            {"_id": profile["_id"]},
            {"$pull": {"skills": {"skill_id": skill_oid}}},
        )
        return jsonify({"message": "Skill removed successfully"}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        return _database_error(error)
