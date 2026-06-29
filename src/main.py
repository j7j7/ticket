"""
main.py — CLI entry point for the ticket browser-bot.

Usage:
    python src/main.py <url> [--script scripts/my_script.py]
    python src/main.py <url> --repl      (interactive mode)
"""

import argparse
import runpy
import sys
from pathlib import Path

from src.browser import PageBot


def main():
    parser = argparse.ArgumentParser(
        description="ticket — browser automation for watching web pages"
    )
    parser.add_argument("url", nargs="?", help="URL to navigate to")
    parser.add_argument(
        "--config", default="config.yaml", help="Config file path (default: config.yaml)"
    )
    parser.add_argument(
        "--script", "-s",
        help="Path to a Python script that receives a `bot` variable (PageBot instance)"
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        help="Drop into an interactive Python REPL with `bot` variable available"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Override config to run headless (no visible browser)"
    )

    args = parser.parse_args()

    bot = PageBot(config_path=args.config)

    if args.headless:
        import yaml
        cfg = yaml.safe_load(Path(args.config).read_text()) or {}
        cfg.setdefault("browser", {})["headless"] = True
        # Re-init with overridden config
        bot._config = _reload_with_headless(args.config)

    if args.url:
        bot.start()
        bot.go(args.url)
        print(f"\n  Navigated to: {args.url}")
        print(f"  Page title: {bot.page.title()}\n")

        if args.script:
            script_path = Path(args.script)
            if not script_path.exists():
                print(f"  Script not found: {args.script}", file=sys.stderr)
                sys.exit(1)
            sys.argv = [str(script_path)]  # so __name__ == "__main__" works
            runpy.run_path(str(script_path), init_globals={"bot": bot})

        elif args.repl:
            _repl(bot)

        else:
            print("  Bot is ready. Use --script or --repl to drive it, or pass nothing for screenshot + quit.")
            bot.screenshot("landing.png")
            print("  Saved landing.png — exiting.")

        bot.stop()
    else:
        parser.print_help()


def _repl(bot):
    """Drop into an interactive Python session with `bot` available."""
    print("  Interactive mode. `bot` is ready to use (type `help(bot)` for methods).")
    print("  Type exit() or Ctrl-D to quit.\n")
    import code
    code.interact(local={"bot": bot, "PageBot": PageBot})


def _reload_with_headless(config_path: str) -> dict:
    import yaml
    from copy import deepcopy
    cfg: dict = yaml.safe_load(Path(config_path).read_text()) or {}
    cfg.setdefault("browser", {})["headless"] = True
    return cfg


if __name__ == "__main__":
    main()
