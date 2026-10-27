from bson import ObjectId
from bson.errors import InvalidId
from flask import current_app, g
import pymongo
from pymongo.errors import ConnectionFailure, PyMongoError, ServerSelectionTimeoutError

from .config import DatabaseConfigurationError, get_database_settings

_mongo_client = None


class DatabaseUnavailableError(RuntimeError):
    """Raised when the configured MongoDB server cannot provide a connection."""


def get_mongo_client(uri=None):
    """Return a shared PyMongo MongoClient with connection pooling."""
    global _mongo_client
    if _mongo_client is None or uri is not None:
        if uri is None:
            settings = get_database_settings(current_app.config)
            uri = settings["uri"]
        try:
            client = pymongo.MongoClient(
                uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
            )
            # Verify connectivity eagerly
            client.admin.command("ping")
            _mongo_client = client
        except (ConnectionFailure, ServerSelectionTimeoutError, PyMongoError) as error:
            raise DatabaseUnavailableError("Could not connect to MongoDB.") from error
    return _mongo_client


def get_db():
    """Return the active MongoDB database object for the current request."""
    if "mongo_db" not in g:
        settings = get_database_settings(current_app.config)
        try:
            client = get_mongo_client(settings["uri"])
            g.mongo_db = client[settings["database"]]
        except (ConnectionFailure, ServerSelectionTimeoutError, PyMongoError) as error:
            raise DatabaseUnavailableError("Could not connect to MongoDB.") from error
    return g.mongo_db


def close_db_connection(_error=None):
    """Clean up request context database references."""
    g.pop("mongo_db", None)


def init_db_indexes(db):
    """Ensure required indexes and uniqueness constraints in MongoDB collections."""
    # 1. Users collection
    db.users.create_index([("email", pymongo.ASCENDING)], unique=True, name="uq_users_email")
    db.users.create_index([("role", pymongo.ASCENDING)], name="idx_users_role")

    # 2. Skills collection
    db.skills.create_index([("skill_name", pymongo.ASCENDING)], unique=True, name="uq_skills_skill_name")
    db.skills.create_index([("category", pymongo.ASCENDING)], name="idx_skills_category")

    # 3. Teacher profiles collection
    db.teacher_profiles.create_index([("user_id", pymongo.ASCENDING)], unique=True, name="uq_teacher_profiles_user")
    db.teacher_profiles.create_index([("rating", pymongo.DESCENDING)], name="idx_teacher_profiles_rating")
    db.teacher_profiles.create_index([("skills.skill_id", pymongo.ASCENDING)], name="idx_teacher_profiles_skills_id")
    db.teacher_profiles.create_index([("skills.skill_name", pymongo.ASCENDING)], name="idx_teacher_profiles_skills_name")
    db.teacher_profiles.create_index([("skills.category", pymongo.ASCENDING)], name="idx_teacher_profiles_skills_cat")

    # 4. Bookings collection
    # Active slot unique constraint: teacher_id + booking_date + booking_time
    # Cancelled bookings have status == 'cancelled' and are excluded via partial filter
    db.bookings.create_index(
        [
            ("teacher_id", pymongo.ASCENDING),
            ("booking_date", pymongo.ASCENDING),
            ("booking_time", pymongo.ASCENDING),
        ],
        unique=True,
        partialFilterExpression={"status": {"$in": ["pending", "confirmed", "completed"]}},
        name="uq_bookings_active_teacher_slot",
    )
    db.bookings.create_index(
        [("learner_id", pymongo.ASCENDING), ("booking_date", pymongo.ASCENDING)],
        name="idx_bookings_learner_date",
    )
    db.bookings.create_index(
        [("teacher_id", pymongo.ASCENDING), ("booking_date", pymongo.ASCENDING)],
        name="idx_bookings_teacher_date",
    )
    db.bookings.create_index([("skill_id", pymongo.ASCENDING)], name="idx_bookings_skill")

    # 5. Reviews collection
    db.reviews.create_index([("booking_id", pymongo.ASCENDING)], unique=True, name="uq_reviews_booking_id")
    db.reviews.create_index(
        [("teacher_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
        name="idx_reviews_teacher_created",
    )
    db.reviews.create_index([("learner_id", pymongo.ASCENDING)], name="idx_reviews_learner")


def to_object_id(val):
    """Safely convert a string or value to BSON ObjectId; return None if invalid."""
    if isinstance(val, ObjectId):
        return val
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    if not ObjectId.is_valid(val):
        return None
    try:
        return ObjectId(val)
    except (InvalidId, TypeError, ValueError):
        return None
