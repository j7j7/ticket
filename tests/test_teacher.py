"""
Tests for the teacher module — teach loop, script generation.
"""

import json
from pathlib import Path

import pytest

from src.teacher import generate_script, teach_loop
from src.timeline import (
    Timeline,
    action_event,
    navigation_event,
)


class TestGenerateScript:
    def test_generate_from_actions(self):
        """Generate a script from a timeline with action events."""
        tl = Timeline()
        tl.begin()
        tl.push(navigation_event(seq=0, timestamp=0.0, url="https://x.com", event_type="finish"))
        tl.push(action_event(seq=0, timestamp=1.0, method="click", args=("#start",)))
        tl.push(action_event(seq=0, timestamp=2.0, method="click_text", args=("Submit",), kwargs={"timeout": 5000}))

        script = generate_script(tl)

        # Should contain the methods used
        assert "def run(bot):" in script
        assert "bot.click" in script
        assert "#start" in script
        assert "bot.click_text" in script
        assert "Submit" in script
        assert "timeout=5000" in script
        assert "if __name__" in script

    def test_generate_with_navigation(self):
        """Generated script should include the URL from navigation events."""
        tl = Timeline()
        tl.begin()
        tl.push(navigation_event(seq=0, timestamp=0.0, url="https://example.com/page", event_type="finish"))
        tl.push(action_event(seq=0, timestamp=1.0, method="click", args=("#btn",)))

        script = generate_script(tl)

        assert "https://example.com/page" in script
        assert "bot.click" in script

    def test_generate_no_actions(self):
        """An empty timeline should produce a minimal script."""
        tl = Timeline()
        script = generate_script(tl)
        assert "def run(bot):" in script

    def test_generate_writes_file(self, tmp_data_dir):
        """If output_path is provided, the script should be written to disk."""
        tl = Timeline()
        tl.begin()
        tl.push(navigation_event(seq=0, timestamp=0.0, url="https://x.com", event_type="finish"))
        tl.push(action_event(seq=0, timestamp=1.0, method="click", args=("#btn",)))

        out_path = tmp_data_dir / "generated.py"
        generate_script(tl, output_path=str(out_path))

        assert out_path.exists()
        content = out_path.read_text()
        assert "def run(bot):" in content


class TestTeachLoop:
    def test_teach_returns_empty_with_no_actions(self, page_bot_mock, tmp_data_dir, mocker):
        """teach_loop should handle zero recorded actions gracefully."""
        mocker.patch("builtins.input", return_value="")

        recorder = mocker.MagicMock()
        tl = Timeline()
        tl.begin()
        tl.push(navigation_event(seq=0, timestamp=0.0, url="https://example.com", event_type="finish"))
        recorder.timeline = tl

        teach_dir = tmp_data_dir / "teach_test"
        result = teach_loop(
            page_bot_mock, recorder, "https://example.com",
            str(teach_dir), loops=0,
        )
        # No actions means no script path returned
        assert result == ""
