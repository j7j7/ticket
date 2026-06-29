"""
teacher.py — Teach-by-demonstration: record one manual loop, then replay it.

Workflow
--------
1. ``teach_loop()`` opens the browser and starts recording.
2. You perform ONE complete cycle of your workflow manually.
3. Press Enter when done → recording is saved, actions are extracted.
4. The extracted actions are replayed in a loop automatically.

You can also export the taught actions to a Python script with
``generate_script()`` for inspection and tweaking.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from src.exceptions import ElementError, NavigationError
from src.replayer import SessionReplay
from src.timeline import Timeline, TimelineEvent

if TYPE_CHECKING:
    from src.browser import PageBot
    from src.recorder import SessionRecorder

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

# How long to pause between replayed actions (seconds)
REPLAY_PAUSE = 0.3

# Default number of loops (0 = forever)
DEFAULT_LOOPS = 0


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def teach_loop(
    bot: "PageBot",
    recorder: "SessionRecorder",
    url: str,
    teach_dir: str,
    *,
    loops: int = DEFAULT_LOOPS,
    instructions: str = None,
) -> str:
    """Record one manual cycle, then replay it in a loop.

    Parameters
    ----------
    bot : PageBot
        Active browser bot (already started).
    recorder : SessionRecorder
        Recorder attached to the bot (already started).
    url : str
        Target URL.
    teach_dir : str
        Directory to save recording and generated script.
    loops : int
        Number of times to replay after teaching (0 = forever until Ctrl-C).
    instructions : str, optional
        Extra instructions displayed to the user before teaching.

    Returns
    -------
    str
        Path to the generated replay script.
    """
    teach_path = Path(teach_dir)
    teach_path.mkdir(parents=True, exist_ok=True)
    script_path = teach_path / "replay_script.py"
    action_log = teach_path / "actions.jsonl"

    # --- Phase 1: Teach -------------------------------------------------
    print()
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║                   TEACH MODE                            ║")
    print("  ║  Perform ONE complete cycle of your workflow now.       ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print(f"  URL: {url}")
    if instructions:
        print(f"  {instructions}")
    print()
    print("  The browser is recording everything — clicks, typing,")
    print("  network requests, console messages, screenshots.")
    print()
    print("  When you've finished ONE cycle, press Enter here to stop")
    print("  recording and let the bot take over.")
    print()

    try:
        input("  Press Enter when your manual cycle is complete... ")
    except (EOFError, KeyboardInterrupt):
        print("\n  Teach cancelled.")
        sys.exit(130)

    # --- Phase 2: Save -------------------------------------------------
    recorder.snapshot("teach_complete")
    recorder.stop()
    print(f"\n  Recording saved → {teach_path}")

    # --- Phase 3: Analyse ----------------------------------------------
    replay = SessionReplay(str(teach_path))
    actions = replay.timeline.actions()

    if not actions:
        print("  No actions were recorded. Nothing to replay.")
        return ""

    print(f"\n  Recorded {len(actions)} actions:")
    for ev in actions:
        method = ev.data.get("method", "?")
        args = _fmt_args(ev.data.get("args", ()))
        print(f"    {ev.seq:4d}. {method}({args})")

    # Save action log for inspection
    with open(action_log, "w") as f:
        for ev in actions:
            f.write(ev.to_json() + "\n")

    # --- Phase 4: Generate script --------------------------------------
    script_text = _build_replay_script(actions, url)
    script_path.write_text(script_text)
    print(f"\n  Replay script generated → {script_path}")

    # Show suggestions from the replayer
    suggestions = replay.suggest_next_action()
    if suggestions:
        print("\n  Suggestions from analysis:")
        for s in suggestions[:3]:
            bar = "█" * int(s.confidence * 10)
            print(f"    [{bar}] {s.action}")

    # --- Phase 5: Replay -----------------------------------------------
    _replay_loop(bot, script_path, url, loops)

    return str(script_path)


# ------------------------------------------------------------------
# Script generation
# ------------------------------------------------------------------

def generate_script(timeline: Timeline, output_path: str = None) -> str:
    """Generate a Python replay script from a recorded timeline.

    Parameters
    ----------
    timeline : Timeline
        The recorded timeline containing action events.
    output_path : str, optional
        If provided, write the script to this path.

    Returns
    -------
    str
        The generated Python script.
    """
    actions = timeline.actions()
    # Try to extract URL from the first navigation event
    navs = timeline.by_kind("navigation")
    url = navs[0].data.get("url", "") if navs else ""
    script = _build_replay_script(actions, url)

    if output_path:
        Path(output_path).write_text(script)
        print(f"  Script written → {output_path}")

    return script


# ------------------------------------------------------------------
# Internal: replay execution
# ------------------------------------------------------------------

def _replay_loop(bot: "PageBot", script_path: Path, url: str, loops: int):
    """Execute the generated script in a loop."""
    import runpy

    if not script_path.exists():
        print(f"  Script not found: {script_path}")
        return

    loop_count = 0
    try:
        while True:
            loop_count += 1
            if loops > 0 and loop_count > loops:
                break

            print()
            print(f"  ── Loop #{loop_count}" + ("  (press Ctrl-C to stop)" if loops == 0 else ""))
            print()

            # Navigate back to the starting URL first
            try:
                bot.go(url)
            except NavigationError as exc:
                print(f"  Navigation failed: {exc}")
                break

            # Wait a moment for the page to settle
            time.sleep(1)

            # Run the generated script
            try:
                runpy.run_path(str(script_path), init_globals={
                    "bot": bot,
                    "PageBot": __import__("src.browser", fromlist=["PageBot"]).PageBot,
                    "CountdownWatcher": __import__("src.observer", fromlist=["CountdownWatcher"]).CountdownWatcher,
                    "TextWatcher": __import__("src.observer", fromlist=["TextWatcher"]).TextWatcher,
                    "wait_for_url_change": __import__("src.observer", fromlist=["wait_for_url_change"]).wait_for_url_change,
                })
            except (ElementError, NavigationError, TimeoutError) as exc:
                print(f"  Loop #{loop_count} failed: {exc}")
                break

            print(f"  ✓ Loop #{loop_count} complete")

            # Pause between loops
            time.sleep(2)

    except KeyboardInterrupt:
        print(f"\n  Looping stopped after {loop_count} cycles.")


# ------------------------------------------------------------------
# Internal: script builder
# ------------------------------------------------------------------

def _build_replay_script(actions: List[TimelineEvent], url: str) -> str:
    """Turn a list of action events into a runnable Python script."""
    lines = [
        '"""',
        "Auto-generated replay script from taught recording.",
        f"  Source URL: {url}",
        f"  Actions:    {len(actions)}",
        '"""',
        "",
        "",
        "def run(bot):",
    ]

    for ev in actions:
        method = ev.data.get("method", "")
        args = ev.data.get("args", ())
        kwargs = ev.data.get("kwargs", {})

        py_line = _action_to_python(method, args, kwargs)
        if py_line:
            lines.append(f"    {py_line}")

    lines.extend([
        "",
        "",
        'if __name__ == "__main__":',
        "    import sys",
        "    from src.browser import PageBot",
        f'    url = sys.argv[1] if len(sys.argv) > 1 else "{url}"',
        "    with PageBot() as bot:",
        "        bot.go(url)",
        "        run(bot)",
    ])

    return "\n".join(lines)


def _action_to_python(method: str, args: tuple, kwargs: dict) -> str:
    """Convert a recorded action to a line of Python code.

    Handles the common bot methods and inserts observer usage where
    appropriate (e.g. ``click_text`` → safe, ``wait_for`` → already safe).
    """
    # Build arg string
    arg_strs = []
    for a in args:
        if isinstance(a, str):
            # Escape quotes and wrap
            escaped = a.replace("'", "\\'").replace('"', '\\"')
            arg_strs.append(repr(a))
        else:
            arg_strs.append(repr(a))

    kwarg_strs = []
    for k, v in kwargs.items():
        if v is not None or k in ("clear",):
            kwarg_strs.append(f"{k}={repr(v)}")

    all_args = ", ".join(arg_strs + kwarg_strs)

    # Map to observer patterns where applicable
    method_lower = method.lower()
    method_safe = method

    if "countdown" in method_lower or "timer" in str(args).lower():
        # If the user clicked something related to a timer/countdown,
        # add a CountdownWatcher usage comment
        return (
            f"# Recorded action: {method}({all_args})\n"
            f"    # bot.{method}({all_args})\n"
            f"    # You may want to use CountdownWatcher here:\n"
            f"    # from src.observer import CountdownWatcher\n"
            f"    # timer = CountdownWatcher(bot, '#timer')\n"
            f"    # timer.wait_until(target=0)"
        )

    # Default: generate a simple bot call
    return f"bot.{method_safe}({all_args})"


def _fmt_args(args: tuple) -> str:
    """Pretty-print arguments for display."""
    return ", ".join(repr(a) if isinstance(a, str) else str(a) for a in args)
