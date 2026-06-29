# ticket 🎫

Browser automation for watching web pages — clicking buttons, reading countdowns, polling for state changes.

```
python src/main.py <url> --script scripts/example.py
```

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Run the example script against any page
python src/main.py https://example.com --script scripts/example.py

# Or run headless (no visible browser window)
python src/main.py https://example.com --script scripts/my_script.py --headless

# Or drop into an interactive REPL to experiment
python src/main.py https://example.com --repl
```

## Usage

| Command | What it does |
|---|---|
| `--script path/to.py` | Run a Python file that receives a `bot` variable |
| `--repl` | Interactive Python shell with `bot` ready |
| `--headless` | Override config to run without displaying the browser |
| `--config path.yaml` | Point to a different config file |

## How to write a script

Your script gets a `bot` object already navigated to the target URL:

```python
from src.observer import CountdownWatcher, TextWatcher

# Click a button
bot.click_text("Start")

# Watch a countdown
timer = CountdownWatcher(bot, "#timer")
raw, secs = timer.wait_until(target=0, timeout=60000)
print(f"Done! Final value: {raw}")

# Wait for text to appear
status = TextWatcher(bot, "#status")
val = status.wait_until_contains("Complete")
```

## API overview

**`PageBot`** (`src/browser.py`)
- `go(url)` — navigate
- `click(selector)` / `click_text(text)` — click elements
- `type_into(selector, text)` — fill input fields
- `text(selector)` / `all_text(selector)` — read element text
- `page_text()` — whole page as text
- `exists(selector)` / `count(selector)` — check for elements
- `wait_for(selector)` — wait for element to appear
- `poll_text(selector, ...)` — poll until a condition is met
- `screenshot(path)` — save a screenshot

**`CountdownWatcher`** (`src/observer.py`)
- `read()` — fetch and parse current countdown → seconds
- `wait_until(target=0)` — block until value hits *target*
- `wait_until_changes()` — block until the timer starts ticking
- Understands `HH:MM:SS`, `MM:SS`, `N seconds`, `N minutes`

**`TextWatcher`** (`src/observer.py`)
- `wait_until_contains(text)` — block until text appears
- `wait_until_not_contains(text)` — block until text disappears

## Config

Edit `config.yaml` to change browser behaviour:

```yaml
browser:
  headless: false          # show the browser window
  slow_mo: 100             # ms delay between actions
  viewport:
    width: 1280
    height: 800
```

Create `config.local.yaml` with your overrides — it merges on top of `config.yaml` and is gitignored.
