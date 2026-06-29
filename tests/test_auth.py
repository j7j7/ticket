"""
Tests for the auth module.
"""

import json
from pathlib import Path

import pytest

from src.auth import (
    AuthError,
    auth_state_in_recording,
    load_auth_state,
    save_auth_state,
    manual_login,
)


class TestSaveLoadAuthState:
    def test_save_and_load(self, page_bot_mock, tmp_data_dir):
        """Save storage state then load it back."""
        state_path = tmp_data_dir / "auth.json"
        page_bot_mock.page.context.storage_state.return_value = {
            "cookies": [{"name": "session", "value": "abc123", "domain": ".example.com"}],
            "origins": [],
        }
        saved = save_auth_state(page_bot_mock, str(state_path))
        assert Path(saved).exists()

        loaded = load_auth_state(str(state_path))
        assert loaded["cookies"][0]["name"] == "session"
        assert loaded["cookies"][0]["value"] == "abc123"

    def test_load_missing_file(self):
        with pytest.raises(AuthError, match="not found"):
            load_auth_state("/nonexistent/auth.json")

    def test_load_invalid_json(self, tmp_data_dir):
        bad = tmp_data_dir / "bad.json"
        bad.write_text("not json")
        with pytest.raises(AuthError, match="Invalid"):
            load_auth_state(str(bad))

    def test_save_creates_parent_dirs(self, page_bot_mock, tmp_data_dir):
        """save_auth_state should create parent directories if needed."""
        nested = tmp_data_dir / "sub" / "dir" / "auth.json"
        page_bot_mock.page.context.storage_state.return_value = {"cookies": [], "origins": []}
        saved = save_auth_state(page_bot_mock, str(nested))
        assert Path(saved).exists()


class TestAuthStateInRecording:
    def test_finds_auth_state(self, tmp_data_dir):
        record_dir = tmp_data_dir / "recording"
        record_dir.mkdir()
        auth_file = record_dir / "auth_state.json"
        auth_file.write_text("{}")
        result = auth_state_in_recording(str(record_dir))
        assert result == str(auth_file)

    def test_missing_returns_none(self, tmp_data_dir):
        record_dir = tmp_data_dir / "empty_recording"
        record_dir.mkdir()
        assert auth_state_in_recording(str(record_dir)) is None


class TestManualLogin:
    def test_manual_login_saves_state(self, page_bot_mock, tmp_data_dir, mocker):
        """When user presses Enter, state should be saved."""
        mocker.patch("builtins.input", return_value="")
        auth_path = tmp_data_dir / "manual_auth.json"
        page_bot_mock.page.context.storage_state.return_value = {
            "cookies": [{"name": "session", "value": "abc123", "domain": ".example.com"}],
            "origins": [],
        }
        result = manual_login(
            page_bot_mock, "https://example.com/login",
            auth_state_path=str(auth_path),
            timeout=60,
        )
        assert Path(result).exists()
        loaded = json.loads(Path(result).read_text())
        assert loaded["cookies"][0]["value"] == "abc123"

    def test_manual_login_no_page(self, page_bot_mock, tmp_data_dir):
        """Should raise AuthError if bot has no page."""
        page_bot_mock.page = None
        with pytest.raises(AuthError, match="no active page"):
            manual_login(
                page_bot_mock, "https://example.com",
                auth_state_path=str(tmp_data_dir / "auth.json"),
            )
