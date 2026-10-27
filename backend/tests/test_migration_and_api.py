from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import pytest
from bson import ObjectId

from app import create_app
from app.db import get_db, init_db_indexes
from app.utils.auth import verify_password
from scripts.migrate_mysql_to_mongo import run_migration


@pytest.fixture(scope="session")
def app():
    test_db_name = "skillswap_test_db"
    test_config = {
        "TESTING": True,
        "MONGODB_DB_NAME": test_db_name,
        "JWT_SECRET_KEY": "test_secret_key_12345_very_long_secure_key_for_testing_2026",
    }
    app = create_app(test_config=test_config)
    with app.app_context():
        db = get_db()
        # Clean test DB
        db.client.drop_database(test_db_name)
        init_db_indexes(db)
    yield app
    with app.app_context():
        db = get_db()
        db.client.drop_database(test_db_name)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    with app.app_context():
        return get_db()


def test_health_check(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


def test_user_registration_and_hash(client, db):
    # Register learner
    payload = {
        "fullName": "Test Learner",
        "email": "learner_test@example.com",
        "password": "Password123!",
        "role": "learner",
    }
    res = client.post("/api/auth/register", json=payload)
    assert res.status_code == 201
    data = res.get_json()
    assert "user" in data
    assert data["user"]["email"] == "learner_test@example.com"
    assert data["user"]["role"] == "learner"
    user_id = data["user"]["id"]
    assert ObjectId.is_valid(user_id)

    # Check MongoDB document
    user_doc = db.users.find_one({"_id": ObjectId(user_id)})
    assert user_doc is not None
    assert user_doc["email"] == "learner_test@example.com"
    # Never store plaintext password!
    assert "password" not in user_doc
    assert user_doc["password_hash"] != "Password123!"
    assert verify_password(user_doc["password_hash"], "Password123!")

    # Duplicate registration should return 409
    res_dup = client.post("/api/auth/register", json=payload)
    assert res_dup.status_code == 409
    assert "already registered" in res_dup.get_json()["error"]


def test_user_login_and_me(client):
    # Register teacher
    reg_res = client.post(
        "/api/auth/register",
        json={
            "fullName": "Professor Test",
            "email": "prof_test@example.com",
            "password": "SecretPassword123",
            "role": "teacher",
        },
    )
    assert reg_res.status_code == 201

    # Login
    login_res = client.post(
        "/api/auth/login",
        json={"email": "prof_test@example.com", "password": "SecretPassword123"},
    )
    assert login_res.status_code == 200
    login_data = login_res.get_json()
    assert "access_token" in login_data
    token = login_data["access_token"]

    # Invalid login
    bad_login = client.post(
        "/api/auth/login",
        json={"email": "prof_test@example.com", "password": "WrongPassword"},
    )
    assert bad_login.status_code == 401

    # /api/auth/me
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.get_json()["user"]["email"] == "prof_test@example.com"


def test_skills_listing(client, db):
    # Insert skills directly to test listing
    db.skills.delete_many({})
    db.skills.insert_many([
        {"skill_name": "Python", "category": "Programming"},
        {"skill_name": "React", "category": "Technology"},
    ])

    res = client.get("/api/skills")
    assert res.status_code == 200
    data = res.get_json()
    assert "skills" in data
    assert len(data["skills"]) == 2
    names = [s["skillName"] for s in data["skills"]]
    assert "Python" in names
    assert "React" in names


def test_teacher_profile_and_skills_flow(client, db):
    # Register teacher
    reg = client.post(
        "/api/auth/register",
        json={
            "fullName": "Sarah Mentor",
            "email": "sarah@example.com",
            "password": "Password123!",
            "role": "teacher",
        },
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "sarah@example.com", "password": "Password123!"},
    ).get_json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create profile
    prof_res = client.post(
        "/api/teachers/profile",
        headers=headers,
        json={
            "bio": "Experienced tutor",
            "experience": "5 years",
            "teachingStyle": "Interactive exercises",
        },
    )
    assert prof_res.status_code == 201
    teacher_id = prof_res.get_json()["teacher"]["id"]

    # Duplicate profile creation should be 409
    dup_prof = client.post("/api/teachers/profile", headers=headers, json={"bio": "dup"})
    assert dup_prof.status_code == 409

    # Add skill
    py_skill = db.skills.find_one({"skill_name": "Python"})
    add_skill_res = client.post(
        "/api/teachers/profile/skills",
        headers=headers,
        json={"skillId": str(py_skill["_id"])},
    )
    assert add_skill_res.status_code == 201

    # Adding same skill again should be 409
    dup_skill = client.post(
        "/api/teachers/profile/skills",
        headers=headers,
        json={"skillId": str(py_skill["_id"])},
    )
    assert dup_skill.status_code == 409

    # Verify teacher appears in teacher list
    list_res = client.get("/api/teachers")
    assert list_res.status_code == 200
    teachers = list_res.get_json()["teachers"]
    matched = [t for t in teachers if t["id"] == teacher_id]
    assert len(matched) == 1
    assert matched[0]["name"] == "Sarah Mentor"
    assert len(matched[0]["skills"]) == 1
    assert matched[0]["skills"][0]["skillName"] == "Python"

    # Remove skill
    del_skill = client.delete(
        f"/api/teachers/profile/skills/{str(py_skill['_id'])}",
        headers=headers,
    )
    assert del_skill.status_code == 200


def test_booking_and_conflict_prevention(client, db):
    # Setup teacher with Python skill
    client.post(
        "/api/auth/register",
        json={
            "fullName": "David Coach",
            "email": "david@example.com",
            "password": "Password123!",
            "role": "teacher",
        },
    )
    t_token = client.post(
        "/api/auth/login",
        json={"email": "david@example.com", "password": "Password123!"},
    ).get_json()["access_token"]
    t_headers = {"Authorization": f"Bearer {t_token}"}
    t_res = client.post(
        "/api/teachers/profile",
        headers=t_headers,
        json={"bio": "Coach David", "experience": "10y", "teachingStyle": "Hands-on"},
    )
    teacher_id = t_res.get_json()["teacher"]["id"]

    skill_doc = db.skills.find_one({"skill_name": "Python"})
    client.post(
        "/api/teachers/profile/skills",
        headers=t_headers,
        json={"skillId": str(skill_doc["_id"])},
    )

    # Setup learner
    client.post(
        "/api/auth/register",
        json={
            "fullName": "Student Bob",
            "email": "bob@example.com",
            "password": "Password123!",
            "role": "learner",
        },
    )
    l_token = client.post(
        "/api/auth/login",
        json={"email": "bob@example.com", "password": "Password123!"},
    ).get_json()["access_token"]
    l_headers = {"Authorization": f"Bearer {l_token}"}

    future_date = (date.today() + timedelta(days=10)).isoformat()
    booking_payload = {
        "teacherId": teacher_id,
        "skillId": str(skill_doc["_id"]),
        "bookingDate": future_date,
        "bookingTime": "15:00",
        "durationMinutes": 60,
        "sessionType": "Online",
        "notes": "First lesson",
    }

    # 1. Create booking
    b_res = client.post("/api/bookings", headers=l_headers, json=booking_payload)
    assert b_res.status_code == 201
    booking_id = b_res.get_json()["booking"]["id"]

    # 2. Duplicate booking for same teacher / date / time should return 409
    dup_res = client.post("/api/bookings", headers=l_headers, json=booking_payload)
    assert dup_res.status_code == 409
    assert "already booked" in dup_res.get_json()["error"]

    # 3. Cancel the booking
    cancel_res = client.delete(f"/api/bookings/{booking_id}", headers=l_headers)
    assert cancel_res.status_code == 200

    # 4. Verify cancelled booking is still in DB for history
    b_doc = db.bookings.find_one({"_id": ObjectId(booking_id)})
    assert b_doc is not None
    assert b_doc["status"] == "cancelled"

    # 5. Slot reuse: Now the slot can be booked again!
    reuse_res = client.post("/api/bookings", headers=l_headers, json=booking_payload)
    assert reuse_res.status_code == 201


def test_migration_from_fixture(app):
    fixture_path = Path(__file__).resolve().parents[1] / "scripts" / "sample_mysql_dump.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        source_data = json.load(f)

    migration_db_name = "skillswap_migration_test_db"
    mongo_uri = "mongodb://127.0.0.1:27017"

    reporter = run_migration(
        source_data=source_data,
        mongo_uri=mongo_uri,
        mongo_db_name=migration_db_name,
        dry_run=False,
        drop_existing=True,
    )

    assert reporter.stats["users"]["migrated"] == 3
    assert reporter.stats["skills"]["migrated"] == 4
    assert reporter.stats["teacher_profiles"]["migrated"] == 2
    assert reporter.stats["bookings"]["migrated"] == 2
    assert len(reporter.errors) == 0

    # Clean up test DB
    import pymongo
    client = pymongo.MongoClient(mongo_uri)
    client.drop_database(migration_db_name)
    client.close()


def test_booking_lifecycle_and_queries(client, db):
    # Teacher
    client.post(
        "/api/auth/register",
        json={"fullName": "Dr. Smith", "email": "smith@example.com", "password": "Password123!", "role": "teacher"},
    )
    t_token = client.post(
        "/api/auth/login",
        json={"email": "smith@example.com", "password": "Password123!"},
    ).get_json()["access_token"]
    t_headers = {"Authorization": f"Bearer {t_token}"}
    t_res = client.post("/api/teachers/profile", headers=t_headers, json={"bio": "Doctor Smith"})
    t_id = t_res.get_json()["teacher"]["id"]

    # Learner
    client.post(
        "/api/auth/register",
        json={"fullName": "Alice Learner", "email": "alice@example.com", "password": "Password123!", "role": "learner"},
    )
    l_token = client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "Password123!"},
    ).get_json()["access_token"]
    l_headers = {"Authorization": f"Bearer {l_token}"}

    # Create Booking
    target_date = (date.today() + timedelta(days=20)).isoformat()
    create_res = client.post(
        "/api/bookings",
        headers=l_headers,
        json={
            "teacherId": t_id,
            "bookingDate": target_date,
            "bookingTime": "16:00",
            "durationMinutes": 45,
            "sessionType": "Offline",
            "notes": "Discuss machine learning",
        },
    )
    assert create_res.status_code == 201
    b_id = create_res.get_json()["booking"]["id"]

    # Check /api/bookings/my (learner)
    my_res = client.get("/api/bookings/my", headers=l_headers)
    assert my_res.status_code == 200
    my_bookings = my_res.get_json()["bookings"]
    assert any(b["id"] == b_id for b in my_bookings)

    # Check /api/bookings/received (teacher)
    rec_res = client.get("/api/bookings/received", headers=t_headers)
    assert rec_res.status_code == 200
    rec_bookings = rec_res.get_json()["bookings"]
    assert any(b["id"] == b_id for b in rec_bookings)

    # Teacher confirms booking
    status_res = client.put(
        f"/api/bookings/{b_id}/status",
        headers=t_headers,
        json={"status": "confirmed"},
    )
    assert status_res.status_code == 200
    assert status_res.get_json()["booking"]["status"] == "confirmed"

    # Teacher completes booking
    status_res2 = client.put(
        f"/api/bookings/{b_id}/status",
        headers=t_headers,
        json={"status": "completed"},
    )
    assert status_res2.status_code == 200
    assert status_res2.get_json()["booking"]["status"] == "completed"

