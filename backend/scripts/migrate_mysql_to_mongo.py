#!/usr/bin/env python3
"""
SkillSwap Database Migration: MySQL to MongoDB Atlas.

Migrates relational MySQL tables (users, skills, teacher_profiles, teacher_skills, bookings)
into MongoDB Atlas collections (users, skills, teacher_profiles, bookings) with embedded
teacher skills and partial filter indexes for active booking conflicts.

Usage:
    python scripts/migrate_mysql_to_mongo.py [--dry-run] [--drop-existing] [--json-dump FILE]
"""

import argparse
from datetime import date, datetime, time, timezone
import json
import logging
import os
from pathlib import Path
import sys

from bson import ObjectId
from dotenv import load_dotenv
import pymongo
from pymongo.errors import DuplicateKeyError, PyMongoError

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("migration")


def ensure_datetime(val):
    """Normalize date/datetime values to Python datetime with UTC timezone."""
    if val is None:
        return datetime.now(timezone.utc)
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, date):
        return datetime.combine(val, time.min, tzinfo=timezone.utc)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def ensure_date_str(val):
    """Normalize date to YYYY-MM-DD string."""
    if isinstance(val, (date, datetime)):
        return val.strftime("%Y-%m-%d")
    return str(val).strip()


def ensure_time_str(val):
    """Normalize time to HH:MM:SS string."""
    if isinstance(val, datetime):
        return val.strftime("%H:%M:%S")
    if isinstance(val, time):
        return val.strftime("%H:%M:%S")
    # timedelta or string like "14:00" or "14:00:00"
    s = str(val).strip()
    if len(s) == 5:
        return f"{s}:00"
    return s


class MigrationReporter:
    def __init__(self):
        self.stats = {
            "users": {"read": 0, "migrated": 0, "skipped": 0, "failed": 0},
            "skills": {"read": 0, "migrated": 0, "skipped": 0, "failed": 0},
            "teacher_profiles": {"read": 0, "migrated": 0, "skipped": 0, "failed": 0},
            "bookings": {"read": 0, "migrated": 0, "skipped": 0, "failed": 0},
        }
        self.errors = []

    def record_success(self, entity):
        self.stats[entity]["migrated"] += 1

    def record_read(self, entity, count):
        self.stats[entity]["read"] = count

    def record_skipped(self, entity, reason):
        self.stats[entity]["skipped"] += 1
        logger.warning(f"[{entity.upper()}] Skipped record: {reason}")

    def record_failure(self, entity, record_id, reason):
        self.stats[entity]["failed"] += 1
        msg = f"[{entity.upper()}] Failed on ID {record_id}: {reason}"
        self.errors.append(msg)
        logger.error(msg)

    def print_summary(self, dry_run=False):
        print("\n" + "=" * 60)
        mode = "DRY-RUN (NO DATA COMMITTED)" if dry_run else "LIVE MIGRATION"
        print(f"       SKILLSWAP MIGRATION SUMMARY REPORT ({mode})")
        print("=" * 60)
        for entity, data in self.stats.items():
            print(
                f"{entity.capitalize():<18}: Read={data['read']:<4} | "
                f"Migrated={data['migrated']:<4} | Skipped={data['skipped']:<4} | "
                f"Failed={data['failed']:<4}"
            )
        print("-" * 60)
        total_read = sum(d["read"] for d in self.stats.values())
        total_migrated = sum(d["migrated"] for d in self.stats.values())
        total_failed = sum(d["failed"] for d in self.stats.values())
        print(f"Total Records Read:     {total_read}")
        print(f"Total Records Migrated: {total_migrated}")
        print(f"Total Records Failed:   {total_failed}")

        if self.errors:
            print("\nError Details:")
            for err in self.errors:
                print(f"  - {err}")
        else:
            print("\nAll records processed cleanly with zero data loss!")
        print("=" * 60 + "\n")


def read_data_from_mysql(config):
    """Connect to MySQL and fetch all relational tables."""
    import pymysql

    host = config["MYSQL_HOST"]
    port = int(config["MYSQL_PORT"])
    db_name = config["MYSQL_DB"]
    user = config["MYSQL_USER"]
    password = config.get("MYSQL_PASSWORD", "")

    logger.info(f"Connecting to MySQL database '{db_name}' at {host}:{port} as '{user}'...")
    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, full_name, email, password_hash, role, created_at FROM users")
            users = cursor.fetchall()

            cursor.execute("SELECT id, skill_name, category FROM skills")
            skills = cursor.fetchall()

            cursor.execute(
                "SELECT id, user_id, bio, experience, teaching_style, rating, total_sessions, created_at "
                "FROM teacher_profiles"
            )
            teacher_profiles = cursor.fetchall()

            cursor.execute("SELECT id, teacher_id, skill_id FROM teacher_skills")
            teacher_skills = cursor.fetchall()

            cursor.execute(
                "SELECT id, learner_id, teacher_id, skill_id, booking_date, booking_time, "
                "duration_minutes, session_type, notes, status, created_at FROM bookings"
            )
            bookings = cursor.fetchall()

            return {
                "users": users,
                "skills": skills,
                "teacher_profiles": teacher_profiles,
                "teacher_skills": teacher_skills,
                "bookings": bookings,
            }
    finally:
        conn.close()


def read_data_from_json(file_path):
    """Load migration source data from a JSON dump file."""
    logger.info(f"Loading migration source data from JSON dump: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "users": data.get("users", []),
        "skills": data.get("skills", []),
        "teacher_profiles": data.get("teacher_profiles", []),
        "teacher_skills": data.get("teacher_skills", []),
        "bookings": data.get("bookings", []),
    }


def init_mongo_indexes(db):
    """Create MongoDB indexes and partial filter constraints."""
    logger.info("Initializing MongoDB indexes and constraints...")
    # Users
    db.users.create_index([("email", pymongo.ASCENDING)], unique=True, name="uq_users_email")
    db.users.create_index([("role", pymongo.ASCENDING)], name="idx_users_role")

    # Skills
    db.skills.create_index([("skill_name", pymongo.ASCENDING)], unique=True, name="uq_skills_skill_name")
    db.skills.create_index([("category", pymongo.ASCENDING)], name="idx_skills_category")

    # Teacher profiles
    db.teacher_profiles.create_index([("user_id", pymongo.ASCENDING)], unique=True, name="uq_teacher_profiles_user")
    db.teacher_profiles.create_index([("rating", pymongo.DESCENDING)], name="idx_teacher_profiles_rating")
    db.teacher_profiles.create_index([("skills.skill_id", pymongo.ASCENDING)], name="idx_teacher_profiles_skills_id")
    db.teacher_profiles.create_index([("skills.skill_name", pymongo.ASCENDING)], name="idx_teacher_profiles_skills_name")
    db.teacher_profiles.create_index([("skills.category", pymongo.ASCENDING)], name="idx_teacher_profiles_skills_cat")

    # Bookings: Partial filter unique index prevents double booking for active slots
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
    db.bookings.create_index([("learner_id", pymongo.ASCENDING), ("booking_date", pymongo.ASCENDING)], name="idx_bookings_learner_date")
    db.bookings.create_index([("teacher_id", pymongo.ASCENDING), ("booking_date", pymongo.ASCENDING)], name="idx_bookings_teacher_date")
    db.bookings.create_index([("skill_id", pymongo.ASCENDING)], name="idx_bookings_skill")
    logger.info("Indexes successfully ensured.")


def run_migration(source_data, mongo_uri, mongo_db_name, dry_run=False, drop_existing=False):
    """Execute the full data transformation and insertion."""
    reporter = MigrationReporter()

    user_id_map = {}      # mysql_user_id -> ObjectId
    skill_id_map = {}     # mysql_skill_id -> { "_id": ObjectId, "skill_name": ..., "category": ... }
    teacher_id_map = {}   # mysql_teacher_id -> ObjectId

    users_data = source_data.get("users", [])
    skills_data = source_data.get("skills", [])
    teacher_profiles_data = source_data.get("teacher_profiles", [])
    teacher_skills_data = source_data.get("teacher_skills", [])
    bookings_data = source_data.get("bookings", [])

    reporter.record_read("users", len(users_data))
    reporter.record_read("skills", len(skills_data))
    reporter.record_read("teacher_profiles", len(teacher_profiles_data))
    reporter.record_read("bookings", len(bookings_data))

    mongo_client = None
    db = None

    if not dry_run:
        logger.info(f"Connecting to MongoDB Atlas / target database '{mongo_db_name}'...")
        mongo_client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command("ping")
        db = mongo_client[mongo_db_name]

        if drop_existing:
            logger.warning(f"Dropping existing collections in database '{mongo_db_name}' as requested...")
            db.users.drop()
            db.skills.drop()
            db.teacher_profiles.drop()
            db.bookings.drop()

        init_mongo_indexes(db)

    # ----------------------------------------------------
    # 1. Migrate Users
    # ----------------------------------------------------
    logger.info(f"Phase 1: Migrating {len(users_data)} users...")
    seen_emails = set()
    for row in users_data:
        sql_id = row["id"]
        email = str(row.get("email", "")).strip().lower()
        if not email:
            reporter.record_failure("users", sql_id, "User has empty or null email")
            continue

        if email in seen_emails:
            reporter.record_skipped("users", f"Duplicate email '{email}' in source data")
            continue
        seen_emails.add(email)

        # Retain Werkzeug password hash exactly
        password_hash = row.get("password_hash", "")
        if not password_hash:
            reporter.record_failure("users", sql_id, f"User '{email}' has empty password_hash")
            continue

        mongo_user_id = ObjectId()
        user_id_map[sql_id] = mongo_user_id

        user_doc = {
            "_id": mongo_user_id,
            "full_name": str(row.get("full_name", "")).strip(),
            "email": email,
            "password_hash": password_hash,
            "role": str(row.get("role", "learner")).strip(),
            "created_at": ensure_datetime(row.get("created_at")),
        }

        if not dry_run:
            try:
                db.users.insert_one(user_doc)
            except DuplicateKeyError:
                # User already exists in DB
                existing = db.users.find_one({"email": email})
                if existing:
                    user_id_map[sql_id] = existing["_id"]
                    reporter.record_skipped("users", f"User '{email}' already exists in MongoDB; mapped to existing ObjectId.")
                    continue
                reporter.record_failure("users", sql_id, f"Duplicate email collision on '{email}'")
                continue
            except PyMongoError as err:
                reporter.record_failure("users", sql_id, str(err))
                continue

        reporter.record_success("users")
        logger.debug(f"Migrated user {sql_id} ({email}) -> {mongo_user_id}")

    # ----------------------------------------------------
    # 2. Migrate Skills
    # ----------------------------------------------------
    logger.info(f"Phase 2: Migrating {len(skills_data)} skills...")
    seen_skills = set()
    for row in skills_data:
        sql_id = row["id"]
        skill_name = str(row.get("skill_name", "")).strip()
        category = str(row.get("category", "")).strip()
        if not skill_name:
            reporter.record_failure("skills", sql_id, "Skill name is missing")
            continue

        if skill_name.lower() in seen_skills:
            reporter.record_skipped("skills", f"Duplicate skill name '{skill_name}'")
            continue
        seen_skills.add(skill_name.lower())

        mongo_skill_id = ObjectId()
        skill_info = {
            "_id": mongo_skill_id,
            "skill_name": skill_name,
            "category": category,
        }
        skill_id_map[sql_id] = skill_info

        skill_doc = {
            "_id": mongo_skill_id,
            "skill_name": skill_name,
            "category": category,
        }

        if not dry_run:
            try:
                db.skills.insert_one(skill_doc)
            except DuplicateKeyError:
                existing = db.skills.find_one({"skill_name": skill_name})
                if existing:
                    skill_id_map[sql_id] = existing
                    reporter.record_skipped("skills", f"Skill '{skill_name}' already exists in MongoDB; mapped.")
                    continue
                reporter.record_failure("skills", sql_id, f"Duplicate key on skill '{skill_name}'")
                continue
            except PyMongoError as err:
                reporter.record_failure("skills", sql_id, str(err))
                continue

        reporter.record_success("skills")

    # ----------------------------------------------------
    # 3. Migrate Teacher Profiles & Embed Teacher Skills
    # ----------------------------------------------------
    logger.info(f"Phase 3: Migrating {len(teacher_profiles_data)} teacher profiles with embedded skills...")
    # Index teacher skills by mysql teacher_id
    skills_by_teacher = {}
    for ts in teacher_skills_data:
        t_id = ts.get("teacher_id")
        s_id = ts.get("skill_id")
        if t_id is not None and s_id is not None:
            skills_by_teacher.setdefault(t_id, []).append(s_id)

    for row in teacher_profiles_data:
        sql_id = row["id"]
        mysql_user_id = row.get("user_id")

        if mysql_user_id not in user_id_map:
            reporter.record_failure(
                "teacher_profiles",
                sql_id,
                f"Referenced user_id {mysql_user_id} was not found in migrated users",
            )
            continue

        mongo_user_id = user_id_map[mysql_user_id]
        mongo_teacher_id = ObjectId()
        teacher_id_map[sql_id] = mongo_teacher_id

        # Build embedded skills list
        embedded_skills = []
        assigned_skill_ids = skills_by_teacher.get(sql_id, [])
        for assigned_sid in assigned_skill_ids:
            if assigned_sid in skill_id_map:
                s_meta = skill_id_map[assigned_sid]
                embedded_skills.append({
                    "skill_id": s_meta["_id"],
                    "skill_name": s_meta["skill_name"],
                    "category": s_meta["category"],
                })
            else:
                logger.warning(
                    f"Teacher profile {sql_id} references skill {assigned_sid} which is not in skills table."
                )

        teacher_doc = {
            "_id": mongo_teacher_id,
            "user_id": mongo_user_id,
            "bio": row.get("bio"),
            "experience": row.get("experience"),
            "teaching_style": row.get("teaching_style"),
            "rating": float(row.get("rating", 0.0) or 0.0),
            "total_sessions": int(row.get("total_sessions", 0) or 0),
            "skills": embedded_skills,
            "created_at": ensure_datetime(row.get("created_at")),
        }

        if not dry_run:
            try:
                db.teacher_profiles.insert_one(teacher_doc)
            except DuplicateKeyError:
                reporter.record_failure(
                    "teacher_profiles", sql_id, f"Teacher profile already exists for user {mongo_user_id}"
                )
                continue
            except PyMongoError as err:
                reporter.record_failure("teacher_profiles", sql_id, str(err))
                continue

        reporter.record_success("teacher_profiles")

    # ----------------------------------------------------
    # 4. Migrate Bookings
    # ----------------------------------------------------
    logger.info(f"Phase 4: Migrating {len(bookings_data)} bookings...")
    active_slot_tracker = set()

    for row in bookings_data:
        sql_id = row["id"]
        mysql_learner_id = row.get("learner_id")
        mysql_teacher_id = row.get("teacher_id")
        mysql_skill_id = row.get("skill_id")

        if mysql_learner_id not in user_id_map:
            reporter.record_failure(
                "bookings", sql_id, f"Learner user {mysql_learner_id} was not found in migrated users"
            )
            continue

        if mysql_teacher_id not in teacher_id_map:
            reporter.record_failure(
                "bookings", sql_id, f"Teacher profile {mysql_teacher_id} was not found in migrated teacher profiles"
            )
            continue

        mongo_learner_id = user_id_map[mysql_learner_id]
        mongo_teacher_id = teacher_id_map[mysql_teacher_id]

        mongo_skill_id = None
        if mysql_skill_id:
            if mysql_skill_id in skill_id_map:
                mongo_skill_id = skill_id_map[mysql_skill_id]["_id"]
            else:
                logger.warning(
                    f"Booking {sql_id} references skill {mysql_skill_id} which does not exist. Migrating as None."
                )

        b_date = ensure_date_str(row.get("booking_date"))
        b_time = ensure_time_str(row.get("booking_time"))
        status = str(row.get("status", "pending")).strip().lower()

        # Slot conflict detection for active (non-cancelled) bookings
        if status != "cancelled":
            slot_key = (mongo_teacher_id, b_date, b_time)
            if slot_key in active_slot_tracker:
                reporter.record_failure(
                    "bookings",
                    sql_id,
                    f"Conflict: Slot already booked for teacher {mongo_teacher_id} on {b_date} at {b_time}",
                )
                continue
            active_slot_tracker.add(slot_key)

        mongo_booking_id = ObjectId()
        booking_doc = {
            "_id": mongo_booking_id,
            "learner_id": mongo_learner_id,
            "teacher_id": mongo_teacher_id,
            "skill_id": mongo_skill_id,
            "booking_date": b_date,
            "booking_time": b_time,
            "duration_minutes": int(row.get("duration_minutes", 60) or 60),
            "session_type": str(row.get("session_type", "Online")).strip(),
            "notes": row.get("notes"),
            "status": status,
            "created_at": ensure_datetime(row.get("created_at")),
        }

        if not dry_run:
            try:
                db.bookings.insert_one(booking_doc)
            except DuplicateKeyError:
                reporter.record_failure(
                    "bookings",
                    sql_id,
                    f"MongoDB index duplicate key error on teacher slot ({b_date} {b_time})",
                )
                continue
            except PyMongoError as err:
                reporter.record_failure("bookings", sql_id, str(err))
                continue

        reporter.record_success("bookings")

    if mongo_client:
        mongo_client.close()

    reporter.print_summary(dry_run=dry_run)
    return reporter


def main():
    parser = argparse.ArgumentParser(description="Migrate SkillSwap database from MySQL to MongoDB Atlas.")
    parser.add_argument("--dry-run", action="store_true", help="Perform validation and dry-run without writing to MongoDB.")
    parser.add_argument("--drop-existing", action="store_true", help="Drop target MongoDB collections before migration.")
    parser.add_argument("--json-dump", type=str, help="Path to a JSON file containing MySQL source dump.")
    parser.add_argument("--mongo-uri", type=str, help="MongoDB connection URI.")
    parser.add_argument("--mongo-db", type=str, help="MongoDB database name.")
    parser.add_argument("--mysql-host", type=str, help="MySQL host.")
    parser.add_argument("--mysql-port", type=int, help="MySQL port.")
    parser.add_argument("--mysql-db", type=str, help="MySQL database name.")
    parser.add_argument("--mysql-user", type=str, help="MySQL user.")
    parser.add_argument("--mysql-password", type=str, help="MySQL password.")

    args = parser.parse_args()

    # Load environment variables
    backend_dir = Path(__file__).resolve().parents[1]
    load_dotenv(backend_dir / ".env", override=False)

    mongo_uri = args.mongo_uri or os.getenv("MONGODB_URI") or "mongodb://127.0.0.1:27017"
    mongo_db_name = args.mongo_db or os.getenv("MONGODB_DB_NAME") or "skillswap_db"

    mysql_config = {
        "MYSQL_HOST": args.mysql_host or os.getenv("MYSQL_HOST") or os.getenv("DB_HOST") or "127.0.0.1",
        "MYSQL_PORT": args.mysql_port or os.getenv("MYSQL_PORT") or os.getenv("DB_PORT") or 3306,
        "MYSQL_DB": args.mysql_db or os.getenv("MYSQL_DB") or os.getenv("DB_NAME") or "skillswap_db",
        "MYSQL_USER": args.mysql_user or os.getenv("MYSQL_USER") or os.getenv("DB_USER") or "root",
        "MYSQL_PASSWORD": args.mysql_password or os.getenv("MYSQL_PASSWORD") or os.getenv("DB_PASSWORD") or "",
    }

    if args.json_dump:
        source_data = read_data_from_json(args.json_dump)
    else:
        try:
            source_data = read_data_from_mysql(mysql_config)
        except Exception as error:
            logger.error(f"Could not connect to MySQL server: {error}")
            logger.info("Tip: You can pass a JSON export file using --json-dump <path> to run the migration without a live MySQL server.")
            sys.exit(1)

    reporter = run_migration(
        source_data=source_data,
        mongo_uri=mongo_uri,
        mongo_db_name=mongo_db_name,
        dry_run=args.dry_run,
        drop_existing=args.drop_existing,
    )

    if reporter.stats["users"]["failed"] > 0 or reporter.stats["bookings"]["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
