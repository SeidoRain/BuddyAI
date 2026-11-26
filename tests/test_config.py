"""Unit tests for path settings resolution in buddyai.config."""

import os
import unittest
from unittest import mock

from buddyai.config import (
    DEFAULT_VOICE_MODEL,
    DEFAULT_WEATHER_LOCATION,
    PROJECT_ROOT,
    get_data_dir,
    get_ics_file,
    get_voice_model,
    get_weather_location,
)


class TestPathSettings(unittest.TestCase):
    """Checks relative, absolute, and empty path resolution in config.py."""

    def test_get_data_dir_returns_default_data_folder_when_empty(self):
        with mock.patch.dict(os.environ, {"BUDDYAI_DATA_DIR": ""}, clear=False):
            self.assertEqual(get_data_dir(), os.path.join(PROJECT_ROOT, "data"))

    def test_get_data_dir_resolves_relative_path_under_project_root(self):
        with mock.patch.dict(
            os.environ, {"BUDDYAI_DATA_DIR": os.path.join("sample_data", "generated")}, clear=False
        ):
            expected = os.path.abspath(
                os.path.join(PROJECT_ROOT, "sample_data", "generated")
            )
            self.assertEqual(get_data_dir(), expected)

    def test_get_data_dir_keeps_absolute_path_unchanged(self):
        absolute = os.path.abspath(os.path.join(PROJECT_ROOT, "..", "other_data"))
        with mock.patch.dict(os.environ, {"BUDDYAI_DATA_DIR": absolute}, clear=False):
            self.assertEqual(get_data_dir(), absolute)

    def test_get_ics_file_returns_empty_string_when_unset(self):
        with mock.patch.dict(os.environ, {"BUDDYAI_ICS_FILE": ""}, clear=False):
            self.assertEqual(get_ics_file(), "")

    def test_get_ics_file_resolves_relative_path_under_project_root(self):
        rel = os.path.join("sample_data", "generated", "sample_calendar.ics")
        with mock.patch.dict(os.environ, {"BUDDYAI_ICS_FILE": rel}, clear=False):
            expected = os.path.abspath(os.path.join(PROJECT_ROOT, rel))
            self.assertEqual(get_ics_file(), expected)

    def test_get_ics_file_keeps_absolute_path_unchanged(self):
        absolute = os.path.abspath(os.path.join(PROJECT_ROOT, "cal.ics"))
        with mock.patch.dict(os.environ, {"BUDDYAI_ICS_FILE": absolute}, clear=False):
            self.assertEqual(get_ics_file(), absolute)

    def test_get_voice_model_returns_default_when_unset(self):
        with mock.patch.dict(os.environ, {"BUDDYAI_VOICE_MODEL": ""}, clear=False):
            self.assertEqual(get_voice_model(), DEFAULT_VOICE_MODEL)

    def test_get_voice_model_returns_env_override_when_set(self):
        with mock.patch.dict(
            os.environ,
            {"BUDDYAI_VOICE_MODEL": "gemini-3.1-flash-live-preview"},
            clear=False,
        ):
            self.assertEqual(get_voice_model(), "gemini-3.1-flash-live-preview")

    def test_get_weather_location_returns_default_when_unset(self):
        with mock.patch.dict(os.environ, {"BUDDYAI_LOCATION": ""}, clear=False):
            self.assertEqual(get_weather_location(), DEFAULT_WEATHER_LOCATION)

    def test_get_weather_location_returns_env_override_when_set(self):
        with mock.patch.dict(
            os.environ, {"BUDDYAI_LOCATION": "Cebu City"}, clear=False
        ):
            self.assertEqual(get_weather_location(), "Cebu City")


if __name__ == "__main__":
    unittest.main()
