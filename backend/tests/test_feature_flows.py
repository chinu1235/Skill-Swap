from copy import deepcopy
from datetime import datetime, timedelta, timezone
import smtplib
from unittest import TestCase
from unittest.mock import Mock, patch

from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import socketio
from app.utils.email import EmailDeliveryError, send_verification_code


class FakeCollection:
    def __init__(self):
        self.docs = []

    def _matches(self, doc, query):
        for key, expected in query.items():
            value = doc.get(key)
            if isinstance(expected, dict):
                for operator, operand in expected.items():
                    if operator == "$lt" and not (value is not None and value < operand): return False
                    if operator == "$gt" and not (value is not None and value > operand): return False
                    if operator == "$lte" and not (value is not None and value <= operand): return False
                    if operator == "$exists" and ((key in doc) != operand): return False
            elif value != expected:
                return False
        return True

    def find_one(self, query):
        return deepcopy(next((doc for doc in self.docs if self._matches(doc, query)), None))

    def insert_one(self, doc):
        if "email" in doc and any(item.get("email") == doc["email"] for item in self.docs):
            raise DuplicateKeyError("duplicate")
        stored = deepcopy(doc)
        stored.setdefault("_id", ObjectId())
        self.docs.append(stored)
        return type("InsertResult", (), {"inserted_id": stored["_id"]})()

    def update_one(self, query, update):
        for doc in self.docs:
            if not self._matches(doc, query): continue
            before = deepcopy(doc)
            for key, value in update.get("$set", {}).items(): doc[key] = value
            for key, value in update.get("$inc", {}).items(): doc[key] = doc.get(key, 0) + value
            for key, value in update.get("$addToSet", {}).items():
                doc.setdefault(key, [])
                if value not in doc[key]: doc[key].append(value)
            changed = doc != before
            return type("UpdateResult", (), {"matched_count": 1, "modified_count": int(changed)})()
        return type("UpdateResult", (), {"matched_count": 0, "modified_count": 0})()

    def find_one_and_delete(self, query):
        for index, doc in enumerate(self.docs):
            if self._matches(doc, query): return self.docs.pop(index)
        return None

    def delete_one(self, query):
        for index, doc in enumerate(self.docs):
            if self._matches(doc, query):
                self.docs.pop(index)
                return type("DeleteResult", (), {"deleted_count": 1})()
        return type("DeleteResult", (), {"deleted_count": 0})()

    def find_one_and_update(self, query, update, return_document=None):
        target = next((doc for doc in self.docs if self._matches(doc, query)), None)
        if target is None: return None
        result = self.update_one(query, update)
        if not result.matched_count: return None
        return deepcopy(target)


class FakeDatabase:
    def __init__(self):
        self.users = FakeCollection()
        self.pending_registrations = FakeCollection()
        self.bookings = FakeCollection()
        self.teacher_profiles = FakeCollection()


class FeatureFlowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = FakeDatabase()
        cls.patcher = patch.multiple("app", get_db=lambda: cls.db, init_db_indexes=lambda _db: None)
        cls.patcher.start()
        cls.app = create_app({
            "TESTING": True,
            "JWT_SECRET_KEY": "feature-test-jwt-secret-at-least-32-characters",
            "OTP_HASH_SECRET": "feature-test-otp-secret-at-least-32-characters",
            "OTP_MAX_ATTEMPTS": 2,
            "OTP_RESEND_COOLDOWN_SECONDS": 1,
            "FRONTEND_ORIGINS": ["http://localhost:5173"],
            "SESSION_TIMEZONE": "UTC",
            "STUN_URLS": [],
        })

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()

    def setUp(self):
        self.db.users.docs.clear()
        self.db.pending_registrations.docs.clear()
        self.db.bookings.docs.clear()
        self.db.teacher_profiles.docs.clear()
        self.client = self.app.test_client()

    def test_otp_registration_is_pending_until_single_use_verification_and_legacy_login_remains(self):
        sent = []
        with patch("app.routes.auth.get_db", return_value=self.db), patch("app.routes.auth.send_verification_code", side_effect=lambda email, code: sent.append((email, code))):
            response = self.client.post("/api/auth/register", json={"fullName": "New User", "email": "new@example.com", "password": "secret123", "role": "learner"})
            self.assertEqual(response.status_code, 202)
            self.assertNotIn("code", response.get_json())
            self.assertEqual(self.db.users.docs, [])
            pending = self.db.pending_registrations.docs[0]
            self.assertNotIn(sent[0][1], pending["otp_hash"])
            verified = self.client.post("/api/auth/verify", json={"email": "new@example.com", "code": sent[0][1]})
            self.assertEqual(verified.status_code, 201)
            self.assertTrue(self.db.users.docs[0]["email_verified"])
            reused = self.client.post("/api/auth/verify", json={"email": "new@example.com", "code": sent[0][1]})
            self.assertEqual(reused.status_code, 400)

        legacy = {"_id": ObjectId(), "full_name": "Legacy User", "email": "legacy@example.com", "password_hash": generate_password_hash("secret123"), "role": "learner", "created_at": datetime.now(timezone.utc)}
        self.db.users.docs.append(legacy)
        with patch("app.routes.auth.get_db", return_value=self.db):
            login = self.client.post("/api/auth/login", json={"email": legacy["email"], "password": "secret123"})
        self.assertEqual(login.status_code, 200)

    def test_otp_attempt_limit_and_expiry(self):
        sent = []
        with patch("app.routes.auth.get_db", return_value=self.db), patch("app.routes.auth.send_verification_code", side_effect=lambda email, code: sent.append(code)):
            self.client.post("/api/auth/register", json={"fullName": "New User", "email": "new@example.com", "password": "secret123", "role": "learner"})
            first = self.client.post("/api/auth/verify", json={"email": "new@example.com", "code": "000000"})
            second = self.client.post("/api/auth/verify", json={"email": "new@example.com", "code": "000001"})
            self.assertEqual(first.status_code, 400)
            self.assertEqual(second.status_code, 400)
            self.assertEqual(self.db.pending_registrations.docs[0]["attempts"], 2)
            self.db.pending_registrations.docs[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
            expired = self.client.post("/api/auth/verify", json={"email": "new@example.com", "code": sent[0]})
            self.assertEqual(expired.status_code, 400)

    def test_otp_resend_cooldown_replaces_previous_code_without_exposing_it(self):
        sent = []
        with patch("app.routes.auth.get_db", return_value=self.db), patch("app.routes.auth.send_verification_code", side_effect=lambda email, code: sent.append(code)):
            self.client.post("/api/auth/register", json={"fullName": "New User", "email": "new@example.com", "password": "secret123", "role": "learner"})
            throttled = self.client.post("/api/auth/verify/resend", json={"email": "new@example.com"})
            self.assertEqual(throttled.status_code, 429)
            self.db.pending_registrations.docs[0]["resend_after"] = datetime.now(timezone.utc) - timedelta(seconds=1)
            resent = self.client.post("/api/auth/verify/resend", json={"email": "new@example.com"})
            self.assertEqual(resent.status_code, 200)
            self.assertNotIn("code", resent.get_json())
            old_code = self.client.post("/api/auth/verify", json={"email": "new@example.com", "code": sent[0]})
            new_code = self.client.post("/api/auth/verify", json={"email": "new@example.com", "code": sent[1]})
            self.assertEqual(old_code.status_code, 400)
            self.assertEqual(new_code.status_code, 201)

    def test_smtp_failure_logs_only_safe_diagnostics(self):
        smtp = Mock()
        smtp.__enter__ = Mock(return_value=smtp)
        smtp.__exit__ = Mock(return_value=False)
        smtp.login.side_effect = smtplib.SMTPServerDisconnected("sensitive provider response")
        with self.app.app_context():
            from flask import current_app
            current_app.config.update({
                "SMTP_HOST": "smtp.example.invalid", "SMTP_PORT": 587,
                "SMTP_USERNAME": "private@example.invalid", "SMTP_PASSWORD": "password-sentinel",
                "SMTP_FROM": "private@example.invalid", "SMTP_USE_TLS": True,
            })
            with patch("app.utils.email.smtplib.SMTP", return_value=smtp):
                with self.assertLogs("app.utils.email", level="WARNING") as captured:
                    with self.assertRaises(EmailDeliveryError):
                        send_verification_code("recipient@example.invalid", "654321")
        log_text = "\n".join(captured.output)
        self.assertIn("authentication", log_text)
        self.assertIn("SMTPServerDisconnected", log_text)
        for sensitive in ("private@example.invalid", "password-sentinel", "recipient@example.invalid", "654321", "sensitive provider response"):
            self.assertNotIn(sensitive, log_text)

    def _make_booking(self):
        teacher_id, learner_id, profile_id = ObjectId(), ObjectId(), ObjectId()
        self.db.users.docs.extend([
            {"_id": teacher_id, "full_name": "Teacher", "email": "teacher@example.com", "role": "teacher"},
            {"_id": learner_id, "full_name": "Learner", "email": "learner@example.com", "role": "learner"},
        ])
        self.outsider_id = ObjectId()
        self.db.users.docs.append({"_id": self.outsider_id, "full_name": "Outsider", "email": "outsider@example.com", "role": "learner"})
        self.db.teacher_profiles.docs.append({"_id": profile_id, "user_id": teacher_id})
        now = datetime.now(timezone.utc)
        start = now.replace(second=0, microsecond=0) - timedelta(minutes=2)
        booking = {
            "_id": ObjectId(), "teacher_id": profile_id, "learner_id": learner_id,
            "booking_date": start.date().isoformat(), "booking_time": start.time().strftime("%H:%M"),
            "duration_minutes": 60, "session_type": "Online", "status": "confirmed",
            "created_at": now,
        }
        self.db.bookings.docs.append(booking)
        return booking, teacher_id, learner_id

    def _token(self, user_id, role):
        with self.app.app_context():
            from flask_jwt_extended import create_access_token
            return create_access_token(identity=str(user_id), additional_claims={"role": role})

    def test_classroom_authorization_lifecycle_and_completion_guard(self):
        booking, teacher_id, learner_id = self._make_booking()
        teacher_token = self._token(teacher_id, "teacher")
        learner_token = self._token(learner_id, "learner")
        outsider_token = self._token(self.outsider_id, "learner")
        with patch("app.routes.bookings.get_db", return_value=self.db), patch("app.classroom_socket.get_db", return_value=self.db):
            forbidden = self.client.get(f"/api/bookings/{booking['_id']}/classroom", headers={"Authorization": f"Bearer {outsider_token}"})
            self.assertEqual(forbidden.status_code, 403)
            direct_complete = self.client.put(f"/api/bookings/{booking['_id']}/status", json={"status": "completed"}, headers={"Authorization": f"Bearer {teacher_token}"})
            self.assertEqual(direct_complete.status_code, 400)
            started = self.client.post(f"/api/bookings/{booking['_id']}/session/start", json={}, headers={"Authorization": f"Bearer {teacher_token}"})
            self.assertEqual(started.status_code, 200)
            booking["editor_code"] = "initial shared code"
            booking["editor_language"] = "javascript"
            booking["editor_revision"] = 7
            end_without_call = self.client.post(f"/api/bookings/{booking['_id']}/session/end", json={}, headers={"Authorization": f"Bearer {teacher_token}"})
            self.assertEqual(end_without_call.status_code, 409)

            teacher_socket = socketio.test_client(self.app, namespace="/classroom", auth={"token": teacher_token})
            learner_socket = socketio.test_client(self.app, namespace="/classroom", auth={"token": learner_token})
            outsider_socket = socketio.test_client(self.app, namespace="/classroom", auth={"token": outsider_token})
            teacher_join = teacher_socket.emit("classroom:join", {"bookingId": str(booking["_id"])}, namespace="/classroom", callback=True)
            learner_join = learner_socket.emit("classroom:join", {"bookingId": str(booking["_id"])}, namespace="/classroom", callback=True)
            outsider_join = outsider_socket.emit("classroom:join", {"bookingId": str(booking["_id"])}, namespace="/classroom", callback=True)
            self.assertTrue(teacher_join["ok"])
            self.assertTrue(learner_join["ok"])
            learner_sync = [item["args"][0] for item in learner_socket.get_received("/classroom") if item["name"] == "classroom:editor-sync"]
            self.assertEqual(learner_sync[-1], {"code": "initial shared code", "language": "javascript", "revision": 7})
            self.assertFalse(outsider_join["ok"])
            outsider_edit = outsider_socket.emit("editor:update", {"bookingId": str(booking["_id"]), "code": "unauthorized", "language": "javascript"}, namespace="/classroom", callback=True)
            self.assertFalse(outsider_edit["ok"])
            outsider_signal = outsider_socket.emit("webrtc:signal", {"bookingId": str(booking["_id"]), "kind": "offer", "data": {"sdp": "no"}}, namespace="/classroom", callback=True)
            self.assertFalse(outsider_signal["ok"])
            teacher_signal = teacher_socket.emit("webrtc:signal", {"bookingId": str(booking["_id"]), "kind": "offer", "data": {"sdp": "test"}}, namespace="/classroom", callback=True)
            self.assertTrue(teacher_signal["ok"])
            for client in (teacher_socket, learner_socket):
                client.emit("webrtc:connected", {"bookingId": str(booking["_id"])}, namespace="/classroom")
            edit = teacher_socket.emit("editor:update", {"bookingId": str(booking["_id"]), "code": "print('hi')", "language": "python"}, namespace="/classroom", callback=True)
            self.assertTrue(edit["ok"])
            self.assertGreater(edit["revision"], 0)
            self.assertEqual(self.db.bookings.docs[0]["editor_code"], "print('hi')")
            self.assertEqual(self.db.bookings.docs[0]["editor_language"], "python")
            learner_updates = [item["args"][0] for item in learner_socket.get_received("/classroom") if item["name"] == "editor:update"]
            self.assertTrue(learner_updates)
            self.assertEqual(learner_updates[-1]["language"], "python")
            self.assertEqual(learner_updates[-1]["revision"], edit["revision"])
            learner_edit = learner_socket.emit("editor:update", {"bookingId": str(booking["_id"]), "code": "print('learner edit')", "language": "python"}, namespace="/classroom", callback=True)
            self.assertTrue(learner_edit["ok"])
            teacher_updates = [item["args"][0] for item in teacher_socket.get_received("/classroom") if item["name"] == "editor:update"]
            self.assertTrue(teacher_updates)
            self.assertEqual(teacher_updates[-1]["code"], "print('learner edit')")
            self.assertEqual(teacher_updates[-1]["revision"], learner_edit["revision"])
            reconnect_socket = socketio.test_client(self.app, namespace="/classroom", auth={"token": learner_token})
            self.assertTrue(reconnect_socket.emit("classroom:join", {"bookingId": str(booking["_id"])}, namespace="/classroom", callback=True)["ok"])
            resumed_state = [item["args"][0] for item in reconnect_socket.get_received("/classroom") if item["name"] == "classroom:editor-sync"]
            self.assertEqual(resumed_state[-1]["revision"], learner_edit["revision"])
            self.assertEqual(resumed_state[-1]["code"], "print('learner edit')")
            ended = self.client.post(f"/api/bookings/{booking['_id']}/session/end", json={}, headers={"Authorization": f"Bearer {teacher_token}"})
            self.assertEqual(ended.status_code, 200)
            self.assertEqual(self.db.bookings.docs[0]["status"], "completed")
            ended_events = [item["args"][0] for item in learner_socket.get_received("/classroom") if item["name"] == "classroom:session_ended"]
            self.assertEqual(ended_events, [{"bookingId": str(booking["_id"]), "sessionState": "completed"}])
            duplicate = self.client.post(f"/api/bookings/{booking['_id']}/session/end", json={}, headers={"Authorization": f"Bearer {teacher_token}"})
            self.assertEqual(duplicate.status_code, 409)
            teacher_socket.disconnect(namespace="/classroom")
            learner_socket.disconnect(namespace="/classroom")
            reconnect_socket.disconnect(namespace="/classroom")
            outsider_socket.disconnect(namespace="/classroom")

    def test_classroom_execution_authorization_validation_and_shared_result(self):
        booking, teacher_id, _learner_id = self._make_booking()
        booking["session_started_at"] = datetime.now(timezone.utc)
        booking["session_state"] = "in_progress"
        teacher_token = self._token(teacher_id, "teacher")
        outsider_token = self._token(self.outsider_id, "learner")
        url = f"/api/bookings/{booking['_id']}/classroom/run"
        headers = {"Authorization": f"Bearer {teacher_token}"}
        outsider_headers = {"Authorization": f"Bearer {outsider_token}"}
        payload = {"language": "python", "code": "print('ok')", "stdin": ""}
        with patch("app.routes.bookings.get_db", return_value=self.db), patch("app.routes.bookings.execute_code", return_value={"status": "Accepted", "text": "ok", "time": "0.01"}) as execute, patch("app.routes.bookings.socketio.emit") as broadcast:
            invalid_language = self.client.post(url, json={**payload, "language": "html"}, headers=headers)
            self.assertEqual(invalid_language.status_code, 400)
            unauthorized = self.client.post(url, json=payload, headers=outsider_headers)
            self.assertEqual(unauthorized.status_code, 403)
            response = self.client.post(url, json=payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["text"], "ok")
        execute.assert_called_once_with("python", "print('ok')", "")
        broadcast.assert_called_once()

    def test_session_cannot_start_outside_scheduled_window(self):
        booking, teacher_id, _learner_id = self._make_booking()
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        booking["booking_date"] = tomorrow.date().isoformat()
        booking["booking_time"] = tomorrow.time().strftime("%H:%M")
        token = self._token(teacher_id, "teacher")
        with patch("app.routes.bookings.get_db", return_value=self.db):
            response = self.client.post(f"/api/bookings/{booking['_id']}/session/start", json={}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(booking["status"], "confirmed")

    def test_missed_end_window_is_review_required_without_changing_booking_status(self):
        booking, _teacher_id, learner_id = self._make_booking()
        scheduled_start = datetime.now(timezone.utc) - timedelta(hours=4)
        booking["booking_date"] = scheduled_start.date().isoformat()
        booking["booking_time"] = scheduled_start.time().strftime("%H:%M")
        booking["session_started_at"] = datetime.now(timezone.utc) - timedelta(hours=3)
        booking["session_state"] = "in_progress"
        learner_token = self._token(learner_id, "learner")
        with patch("app.routes.bookings.get_db", return_value=self.db):
            response = self.client.get(f"/api/bookings/{booking['_id']}/classroom", headers={"Authorization": f"Bearer {learner_token}"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["session"]["state"], "review_required")
        self.assertEqual(booking["session_state"], "review_required")
        self.assertEqual(booking["status"], "confirmed")
