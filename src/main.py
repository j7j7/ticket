"""
main.py — CLI entry point for the ticket browser-bot.

Usage:
    python src/main.py <url> [--script scripts/my_script.py]
    python src/main.py <url> --repl
    python src/main.py <url> --record recordings/my-test
    python src/main.py <url> --replay recordings/my-test
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from src.browser import PageBot
from src.exceptions import BrowserError, ElementError, NavigationError, TicketError
from src.observer import CountdownWatcher, TextWatcher, wait_for_url_change
from src.recorder import SessionRecorder, load_recording
from src.replayer import SessionReplay

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s  %(message)s",
)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="ticket — browser automation for watching web pages"
    )
    parser.add_argument("url", nargs="?", help="URL to navigate to")
    parser.add_argument(
        "--config", default="config.yaml",
        help="Config file path (default: config.yaml)",
    )
    parser.add_argument(
        "--script", "-s",
        help="Path to a Python script that receives a `bot` variable (PageBot instance)",
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        help="Drop into an interactive Python REPL with `bot` variable available",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Override config to run headless (no visible browser)",
    )
    parser.add_argument(
        "--record",
        metavar="DIR",
        help="Record the session to DIR (e.g. recordings/my-test)",
    )
    parser.add_argument(
        "--replay",
        metavar="DIR",
        help="Analyse/replay a previously recorded session from DIR",
    )
    parser.add_argument(
        "--replay-compare",
        metavar="DIR",
        help="When set with --replay, compare this second recording to the first",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable more detailed logging",
    )
    parser.add_argument(
        "--auth-state",
        metavar="PATH",
        help="Path to auth state JSON (saved cookies + localStorage)",
    )
    parser.add_argument(
        "--manual-login",
        action="store_true",
        help="Open browser, let you log in manually, then save auth state",
    )
    parser.add_argument(
        "--auth-timeout",
        type=int,
        default=300,
        help="Max seconds to wait for manual login (default: 300)",
    )
    parser.add_argument(
        "--teach",
        metavar="DIR",
        help="Teach mode: record one manual loop, then replay it (saves to DIR)",
    )
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        help="When used with --script, repeat the script N times (0 = forever)",
    )
    parser.add_argument(
        "--export-script",
        metavar="PATH",
        help="In replay mode, export recorded actions as a Python script",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    # -- Replay mode (no browser needed) -------------------------------
    if args.replay:
        handle_replay(args)
        return

    # -- Export mode (no browser needed) -------------------------------
    if args.export_script:
        _export_script(args)
        return

    # -- Teach mode ----------------------------------------------------
    if args.teach:
        _teach_mode(args)
        return

    # -- Live browser mode --------------------------------------------
    if not args.url:
        parser.print_help()
        return

    exit_code = 0
    try:
        bot = PageBot(config_path=args.config, storage_state=args.auth_state)

        # Handle --headless properly (merge into config dict)
        if args.headless:
            import yaml
            cfg = yaml.safe_load(Path(args.config).read_text()) or {}
            cfg.setdefault("browser", {})["headless"] = True
            bot._config = _merge_config(bot._config, cfg)

        # Optional recording
        recorder = None
        if args.record:
            recorder = SessionRecorder(bot, record_dir=args.record)
            bot.set_recorder(recorder)

        bot.start()

        # -- Manual login flow -----------------------------------------
        if args.manual_login:
            from src.auth import manual_login
            auth_path = args.auth_state or (
                f"{args.record}/auth_state.json" if args.record else "auth_state.json"
            )
            manual_login(
                bot, args.url,
                auth_state_path=auth_path,
                timeout=args.auth_timeout,
            )
            # Re-start recorder after login so auth actions aren't recorded
            if recorder:
                recorder.stop()
                recorder = SessionRecorder(bot, record_dir=args.record)
                bot.set_recorder(recorder)
                recorder.start()
                recorder.snapshot("post_login")
        else:
            if recorder:
                recorder.start()
            bot.go(args.url)
        print(f"  Navigated to: {args.url}")
        print(f"  Page title: {bot.page.title()}")

        if recorder:
            recorder.snapshot("landing")

        if args.script:
            script_path = Path(args.script)
            if not script_path.exists():
                print(f"  Script not found: {args.script}", file=sys.stderr)
                sys.exit(1)
            _run_script_loop(bot, script_path, args.url, args.loop)

        elif args.repl:
            _repl(bot)

        else:
            print("  Bot is ready. Use --script or --repl to drive it, or pass nothing for screenshot + quit.")
            bot.screenshot("landing.png")
            print("  Saved landing.png — exiting.")

    except TicketError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        exit_code = 1
    except KeyboardInterrupt:
        print("\n  Interrupted.", file=sys.stderr)
        exit_code = 130
    finally:
        if "recorder" in locals() and recorder:
            recorder.snapshot("final")
            recorder.stop()
            print(f"  Recording saved → {recorder.record_dir}")
        if "bot" in locals():
            bot.stop()


# ------------------------------------------------------------------
# Replay mode
# ------------------------------------------------------------------


def handle_replay(args):
    """Run in replay / analysis mode — no browser launched."""
    try:
        replay = SessionReplay(args.replay)
    except Exception as exc:
        print(f"  Failed to load recording: {exc}", file=sys.stderr)
        sys.exit(1)

    print()
    print("  " + "─" * 60)
    print(f"  Session replay: {replay.path.name}")
    print("  " + "─" * 60)
    print()
    print(replay.summary())
    print()

    # Compare mode
    if args.replay_compare:
        try:
            other = SessionReplay(args.replay_compare)
            diffs = replay.compare(other)
        except Exception as exc:
            print(f"  Failed to load comparison recording: {exc}", file=sys.stderr)
            sys.exit(1)

        print("  " + "─" * 60)
        print(f"  Comparison with: {other.path.name}")
        print("  " + "─" * 60)
        if diffs:
            for d in diffs:
                print(f"    ⚠ {d}")
        else:
            print("    ✓ No differences found — recordings match.")
        print()

    # Network analysis
    print("  " + "─" * 60)
    print("  Network traffic")
    print("  " + "─" * 60)
    replay.print_network_summary()
    print()

    # Console errors
    print("  " + "─" * 60)
    print("  Console errors")
    print("  " + "─" * 60)
    replay.show_console_errors()
    print()

    # Snapshots
    print("  " + "─" * 60)
    print("  Snapshots")
    print("  " + "─" * 60)
    replay.show_snapshots(max_snapshots=20)
    print()

    # Decision suggestions
    print("  " + "─" * 60)
    print("  Intelligent suggestions")
    print("  " + "─" * 60)
    suggestions = replay.suggest_next_action()
    if suggestions:
        for s in suggestions:
            bar = "█" * int(s.confidence * 10) + "░" * (10 - int(s.confidence * 10))
            print(f"  [{bar}]  {s.action}")
            print(f"         {s.reason}")
            if s.supporting_evidence:
                for ev in s.supporting_evidence[:2]:
                    print(f"         • {ev}")
            print()
    else:
        print("  No suggestions generated.\n")

    # Detected patterns
    print("  " + "─" * 60)
    print("  Detected patterns")
    print("  " + "─" * 60)
    patterns = replay.detect_patterns(min_repeat=2)
    if patterns:
        for p in patterns:
            print(f"  {p.description}  (x{p.count}, avg {p.avg_duration:.1f}s)")
    else:
        print("  No repeated patterns found.\n")

    # Timeline
    print("  " + "─" * 60)
    print("  Event timeline")
    print("  " + "─" * 60)
    replay.show_timeline(max_events=30)
    print()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _run_script_loop(bot, script_path: Path, url: str, loops: int):
    """Run a script, optionally repeating it N times."""
    import runpy
    import sys
    import time

    script_path = Path(script_path)
    if not script_path.exists():
        print(f"  Script not found: {script_path}", file=sys.stderr)
        return

    loop_count = 0
    try:
        while True:
            loop_count += 1
            if loops > 0 and loop_count > loops:
                break

            if loops != 0 or loop_count > 1:
                print(f"\n  ── Loop #{loop_count}")
                # Navigate back to starting URL for each new loop
                bot.go(url)
                time.sleep(1)

            sys.argv = [str(script_path)]
            runpy.run_path(str(script_path), init_globals={
                "bot": bot,
                "PageBot": PageBot,
                "CountdownWatcher": CountdownWatcher,
                "TextWatcher": TextWatcher,
                "wait_for_url_change": wait_for_url_change,
                "recorder": bot._recorder if hasattr(bot, "_recorder") else None,
            })

            if loops != 0:
                print(f"  ✓ Loop #{loop_count} complete")
                if loop_count < loops:
                    time.sleep(1)

    except (ElementError, NavigationError) as exc:
        print(f"  Loop #{loop_count} failed: {exc}")
    except KeyboardInterrupt:
        print(f"\n  Looping stopped after {loop_count} cycles.")


def _teach_mode(args):
    """Teach mode: record one manual cycle, then replay it."""
    from src.auth import manual_login
    from src.teacher import teach_loop

    bot = PageBot(config_path=args.config, storage_state=args.auth_state)
    recorder = SessionRecorder(bot, record_dir=args.teach)

    if args.headless:
        import yaml
        cfg = yaml.safe_load(Path(args.config).read_text()) or {}
        cfg.setdefault("browser", {})["headless"] = True
        bot._config = _merge_config(bot._config, cfg)

    bot.start()
    bot.set_recorder(recorder)

    # Manual login first if needed
    if args.manual_login:
        auth_path = args.auth_state or f"{args.teach}/auth_state.json"
        manual_login(bot, args.url, auth_state_path=auth_path, timeout=args.auth_timeout)
        # Fresh recorder after login
        recorder.stop()
        recorder = SessionRecorder(bot, record_dir=args.teach)
        bot.set_recorder(recorder)

    recorder.start()
    recorder.snapshot("teach_start")

    loops = args.loop or 0
    result = teach_loop(bot, recorder, args.url, args.teach, loops=loops)

    if result:
        print(f"  To run this again without teaching:\n")
        print(f"    python src/main.py {args.url} --script {result}")
        if loops:
            print(f"    python src/main.py {args.url} --script {result} --loop {loops}")

    bot.stop()


def _export_script(args):
    """Export a recording's actions as a Python script (no browser needed)."""
    from src.replayer import SessionReplay
    from src.teacher import generate_script

    replay = SessionReplay(args.replay or args.export_script)
    if not replay.timeline or not replay.timeline.actions():
        print("  No actions found in this recording.", file=sys.stderr)
        return

    output = args.export_script
    if output == args.replay:
        # When called as --replay --export-script, output is separate
        output = args.export_script

    if output and Path(output).suffix != ".py":
        output = str(Path(output) / "replay_script.py")

    script = generate_script(replay.timeline, output_path=output)
    if not output:
        print(script)


def _repl(bot):
    """Drop into an interactive Python session with `bot` and friends available."""
    print("  Interactive mode. `bot` is ready to use (type `help(bot)` for methods).")
    print("  Type exit() or Ctrl-D to quit.\n")
    import code
    code.interact(local={
        "bot": bot,
        "PageBot": PageBot,
        "CountdownWatcher": CountdownWatcher,
        "TextWatcher": TextWatcher,
        "wait_for_url_change": wait_for_url_change,
    })


def _merge_config(base: dict, overlay: dict) -> dict:
    """Deep-merge two config dicts, returning a new dict."""
    from copy import deepcopy
    result = deepcopy(base)
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _merge_config(result[key], val)
        else:
            result[key] = val
    return result


if __name__ == "__main__":
    main()
