from unittest import TestCase
from unittest.mock import patch

from app import create_app
from app.utils import code_execution


class CodeExecutionAdapterTests(TestCase):
    def setUp(self):
        with patch.multiple("app", get_db=lambda: object(), init_db_indexes=lambda _db: None):
            self.app = create_app({
                "TESTING": True,
                "JWT_SECRET_KEY": "execution-test-secret-at-least-32-characters",
                "CODE_EXECUTION_API_URL": "https://judge.example.invalid",
                "CODE_EXECUTION_API_KEY": "test-only-placeholder",
            })

    def test_dynamic_language_lookup_submission_limits_and_polling(self):
        provider_results = [
            [{"id": 11, "name": "Python (3.x)"}, {"id": 12, "name": "JavaScript (Node.js)"}],
            {"token": "submission-token"},
            {"status": {"id": 3, "description": "Accepted"}, "stdout": "hello", "time": "0.01"},
        ]
        with self.app.app_context(), patch("app.utils.code_execution._request_json", side_effect=provider_results) as request_json, patch("app.utils.code_execution.time.sleep"):
            response = code_execution.execute_code("python", "print('hello')", "input")
        self.assertEqual(response["status"], "Accepted")
        self.assertEqual(response["text"], "hello")
        submission = request_json.call_args_list[1].kwargs["payload"]
        self.assertEqual(submission["language_id"], 11)
        self.assertEqual(submission["stdin"], "input")
        self.assertEqual(submission["cpu_time_limit"], 2)
        self.assertEqual(submission["wall_time_limit"], 7)
        self.assertEqual(submission["memory_limit"], 128_000)

    def test_html_is_not_mapped_to_an_execution_language(self):
        with self.assertRaises(code_execution.UnsupportedExecutionLanguage):
            code_execution._language_id([{"id": 1, "name": "HTML"}], "python")

    def test_missing_provider_configuration_fails_closed(self):
        with self.app.app_context():
            from flask import current_app
            current_app.config["CODE_EXECUTION_API_URL"] = ""
            with self.assertRaises(code_execution.ExecutionConfigurationError):
                code_execution.execute_code("python", "print(1)")
