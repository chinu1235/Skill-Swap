import os
from unittest import TestCase
from unittest.mock import patch

from app.config import load_config


class FrontendOriginConfigTests(TestCase):
    def test_debug_mode_allows_only_the_two_local_vite_5174_origins_in_addition(self):
        with patch.dict(os.environ, {
            "FRONTEND_ORIGINS": "https://app.example.test",
            "FLASK_DEBUG": "true",
        }):
            origins = load_config()["FRONTEND_ORIGINS"]

        self.assertEqual(origins, [
            "https://app.example.test",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ])

    def test_production_mode_does_not_add_development_origins(self):
        with patch.dict(os.environ, {
            "FRONTEND_ORIGINS": "https://app.example.test",
            "FLASK_DEBUG": "false",
        }):
            origins = load_config()["FRONTEND_ORIGINS"]

        self.assertEqual(origins, ["https://app.example.test"])
        self.assertNotIn("*", origins)
