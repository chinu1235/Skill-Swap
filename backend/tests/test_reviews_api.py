import unittest
from bson import ObjectId
from datetime import datetime, timezone

from app import create_app
from app.db import get_db, init_db_indexes
from app.utils.auth import hash_password


class ReviewsApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_db_name = "skillswap_test_db"
        cls.test_config = {
            "TESTING": True,
            "MONGODB_DB_NAME": cls.test_db_name,
            "JWT_SECRET_KEY": "test_secret_key_for_reviews_test_12345_2026",
        }
        cls.app = create_app(test_config=cls.test_config)

    def setUp(self):
        self.client = self.app.test_client()
        with self.app.app_context():
            self.db = get_db()
            self.db.client.drop_database(self.test_db_name)
            init_db_indexes(self.db)

            # Create test learner
            learner_doc = {
                "full_name": "Alice Learner",
                "email": "alice@example.com",
                "password_hash": hash_password("Pass123!"),
                "role": "learner",
                "created_at": datetime.now(timezone.utc),
            }
            res_l = self.db.users.insert_one(learner_doc)
            self.learner_id = res_l.inserted_id

            # Create another learner
            other_learner_doc = {
                "full_name": "Bob Learner",
                "email": "bob@example.com",
                "password_hash": hash_password("Pass123!"),
                "role": "learner",
                "created_at": datetime.now(timezone.utc),
            }
            res_ol = self.db.users.insert_one(other_learner_doc)
            self.other_learner_id = res_ol.inserted_id

            # Create test teacher user and profile
            teacher_user_doc = {
                "full_name": "Dr. Smith",
                "email": "smith@example.com",
                "password_hash": hash_password("Pass123!"),
                "role": "teacher",
                "created_at": datetime.now(timezone.utc),
            }
            res_t = self.db.users.insert_one(teacher_user_doc)
            self.teacher_user_id = res_t.inserted_id

            profile_doc = {
                "user_id": self.teacher_user_id,
                "bio": "Experienced educator",
                "experience": "10 years",
                "teaching_style": "Hands-on",
                "rating": 0.0,
                "total_sessions": 1,
                "total_reviews": 0,
                "skills": [],
                "created_at": datetime.now(timezone.utc),
            }
            res_tp = self.db.teacher_profiles.insert_one(profile_doc)
            self.teacher_profile_id = res_tp.inserted_id

            # Create completed booking for Alice
            completed_booking = {
                "teacher_id": self.teacher_profile_id,
                "learner_id": self.learner_id,
                "booking_date": "2026-10-25",
                "booking_time": "10:00",
                "duration_minutes": 60,
                "session_type": "Online",
                "status": "completed",
                "notes": "Intro session",
                "created_at": datetime.now(timezone.utc),
            }
            res_cb = self.db.bookings.insert_one(completed_booking)
            self.completed_booking_id = res_cb.inserted_id

            # Create pending booking for Alice
            pending_booking = {
                "teacher_id": self.teacher_profile_id,
                "learner_id": self.learner_id,
                "booking_date": "2026-10-30",
                "booking_time": "14:00",
                "duration_minutes": 60,
                "session_type": "Online",
                "status": "pending",
                "created_at": datetime.now(timezone.utc),
            }
            res_pb = self.db.bookings.insert_one(pending_booking)
            self.pending_booking_id = res_pb.inserted_id

        # Obtain login tokens
        login_res = self.client.post("/api/auth/login", json={"email": "alice@example.com", "password": "Pass123!"})
        self.alice_token = login_res.get_json()["access_token"]

        bob_login_res = self.client.post("/api/auth/login", json={"email": "bob@example.com", "password": "Pass123!"})
        self.bob_token = bob_login_res.get_json()["access_token"]

    def tearDown(self):
        with self.app.app_context():
            self.db.client.drop_database(self.test_db_name)

    def test_create_review_success(self):
        """Learner can successfully review a completed booking and teacher rating updates."""
        res = self.client.post(
            "/api/reviews",
            headers={"Authorization": f"Bearer {self.alice_token}"},
            json={
                "bookingId": str(self.completed_booking_id),
                "rating": 5,
                "comment": "Outstanding teaching, very patient!",
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertIn("review", data)
        self.assertEqual(data["review"]["rating"], 5)
        self.assertEqual(data["review"]["comment"], "Outstanding teaching, very patient!")
        self.assertEqual(data["teacherStats"]["rating"], 5.0)
        self.assertEqual(data["teacherStats"]["totalReviews"], 1)

        # Check teacher profile in DB was updated
        with self.app.app_context():
            profile = self.db.teacher_profiles.find_one({"_id": self.teacher_profile_id})
            self.assertEqual(profile["rating"], 5.0)
            self.assertEqual(profile["total_reviews"], 1)

    def test_prevent_duplicate_review(self):
        """Cannot review the same booking more than once."""
        res1 = self.client.post(
            "/api/reviews",
            headers={"Authorization": f"Bearer {self.alice_token}"},
            json={
                "bookingId": str(self.completed_booking_id),
                "rating": 5,
                "comment": "First review",
            },
        )
        self.assertEqual(res1.status_code, 201)

        # Attempt second review for same booking
        res2 = self.client.post(
            "/api/reviews",
            headers={"Authorization": f"Bearer {self.alice_token}"},
            json={
                "bookingId": str(self.completed_booking_id),
                "rating": 4,
                "comment": "Second review attempt",
            },
        )
        self.assertEqual(res2.status_code, 409)
        self.assertIn("already been reviewed", res2.get_json()["error"])

    def test_prevent_review_for_non_completed_booking(self):
        """Cannot review a pending booking."""
        res = self.client.post(
            "/api/reviews",
            headers={"Authorization": f"Bearer {self.alice_token}"},
            json={
                "bookingId": str(self.pending_booking_id),
                "rating": 5,
                "comment": "Premature review",
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Only completed sessions can be reviewed", res.get_json()["error"])

    def test_prevent_review_by_other_learner(self):
        """Only the learner who owns the booking can review it."""
        res = self.client.post(
            "/api/reviews",
            headers={"Authorization": f"Bearer {self.bob_token}"},
            json={
                "bookingId": str(self.completed_booking_id),
                "rating": 5,
                "comment": "Not my booking",
            },
        )
        self.assertEqual(res.status_code, 403)

    def test_validation_errors(self):
        """Requires 1-5 rating and written feedback."""
        # Invalid rating > 5
        res = self.client.post(
            "/api/reviews",
            headers={"Authorization": f"Bearer {self.alice_token}"},
            json={"bookingId": str(self.completed_booking_id), "rating": 6, "comment": "Good"},
        )
        self.assertEqual(res.status_code, 400)

        # Missing comment
        res = self.client.post(
            "/api/reviews",
            headers={"Authorization": f"Bearer {self.alice_token}"},
            json={"bookingId": str(self.completed_booking_id), "rating": 4, "comment": ""},
        )
        self.assertEqual(res.status_code, 400)

    def test_get_teacher_reviews_and_profile_endpoint(self):
        """Reviews list and teacher profile reflect actual reviews."""
        # Submit review
        self.client.post(
            "/api/reviews",
            headers={"Authorization": f"Bearer {self.alice_token}"},
            json={
                "bookingId": str(self.completed_booking_id),
                "rating": 4,
                "comment": "Very informative session.",
            },
        )

        # Retrieve reviews by teacherId
        res_list = self.client.get(f"/api/reviews?teacherId={self.teacher_profile_id}")
        self.assertEqual(res_list.status_code, 200)
        data = res_list.get_json()
        self.assertEqual(len(data["reviews"]), 1)
        self.assertEqual(data["reviews"][0]["rating"], 4)
        self.assertEqual(data["reviews"][0]["learnerName"], "Alice Learner")

        # Retrieve teacher profile via get_teacher endpoint
        res_teacher = self.client.get(f"/api/teachers/{self.teacher_profile_id}")
        self.assertEqual(res_teacher.status_code, 200)
        teacher_data = res_teacher.get_json()["teacher"]
        self.assertEqual(teacher_data["rating"], 4.0)
        self.assertEqual(teacher_data["totalReviews"], 1)
        self.assertEqual(len(teacher_data["reviews"]), 1)


if __name__ == "__main__":
    unittest.main()
