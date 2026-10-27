from flask import Blueprint, current_app, jsonify
from pymongo.errors import PyMongoError

from ..config import DatabaseConfigurationError
from ..db import DatabaseUnavailableError, get_db

skills_bp = Blueprint("skills", __name__)


@skills_bp.get("")
def list_skills():
    try:
        db = get_db()
        cursor = db.skills.find().sort("skill_name", 1)
        skills = [
            {
                "id": str(doc["_id"]),
                "skillName": doc["skill_name"],
                "category": doc["category"],
            }
            for doc in cursor
        ]
        return jsonify({"skills": skills}), 200
    except (DatabaseConfigurationError, DatabaseUnavailableError, PyMongoError) as error:
        current_app.logger.error("Skills query failed: %s", error)
        return jsonify({"error": "Skills are temporarily unavailable"}), 503
