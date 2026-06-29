"""
replayer.py — Load, navigate, compare, and learn from recorded sessions.

A ``SessionReplay`` loads a recording directory and gives you tools to:

- Walk through the timeline step-by-step
- View screenshots, network traffic, and console output at each step
- Compare two recordings (regression detection)
- Search through requests/responses
- Detect patterns and suggest next actions (decision support)
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.timeline import Timeline, TimelineEvent


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------

@dataclass
class NetworkSummary:
    """Aggregated view of all network traffic in a recording."""
    total_requests: int = 0
    total_transfer_bytes: int = 0
    status_codes: Counter = field(default_factory=Counter)
    slowest_urls: List[Tuple[str, float]] = field(default_factory=list)
    error_urls: List[Tuple[str, int]] = field(default_factory=list)
    by_type: Counter = field(default_factory=Counter)  # resource_type -> count


@dataclass
class Pattern:
    """A repeated sequence of events detected in a recording."""
    description: str
    event_kinds: List[str]
    count: int
    avg_duration: float  # seconds


@dataclass
class Suggestion:
    """A suggested next action based on recorded patterns."""
    action: str
    confidence: float  # 0.0 – 1.0
    reason: str
    supporting_evidence: List[str] = field(default_factory=list)


# ------------------------------------------------------------------
# SessionReplay
# ------------------------------------------------------------------

class SessionReplay:
    """Load and analyse a recorded session.

    Usage::

        replay = SessionReplay("recordings/session_20250401_120000")
        print(replay.summary())
        replay.show_timeline(max_events=20)
        replay.show_network_errors()
        replay.show_snapshots()

        # Compare two recordings
        replay2 = SessionReplay("recordings/session_20250401_130000")
        diffs = replay.compare(replay2)
    """

    def __init__(self, path: str):
        self._path = Path(path)
        self._metadata: Dict[str, Any] = {}
        self._timeline: Optional[Timeline] = None
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self):
        """Load metadata and timeline from the recording directory."""
        meta_path = self._path / "recording.json"
        tl_path = self._path / "recording.jsonl"

        if meta_path.exists():
            self._metadata = json.loads(meta_path.read_text())
        if tl_path.exists():
            self._timeline = Timeline.load(str(tl_path))
        else:
            self._timeline = Timeline()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def metadata(self) -> Dict[str, Any]:
        return dict(self._metadata)

    @property
    def timeline(self) -> Optional[Timeline]:
        return self._timeline

    @property
    def events(self) -> List[TimelineEvent]:
        return self._timeline.events if self._timeline else []

    # ------------------------------------------------------------------
    # Summary & display
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Return a multi-line summary of the recorded session."""
        if not self._timeline:
            return "(empty recording)"

        m = self._metadata
        lines = [
            f"Recording:  {self._path.name}",
            f"URL:        {m.get('url', '?')}",
            f"Title:      {m.get('title', '?')}",
            f"Created:    {m.get('created', '?')}",
            f"Duration:   {m.get('duration_seconds', 0):.1f}s",
            "",
            self._timeline.summary(),
        ]
        return "\n".join(lines)

    def show_timeline(self, max_events: int = 50):
        """Print the event timeline to stdout."""
        if not self._timeline:
            print("(empty recording)")
            return
        self._timeline.print_timeline(max_events=max_events)

    def show_network_errors(self):
        """Print all failed or errored network requests."""
        if not self._timeline:
            print("(empty recording)")
            return
        errors = [e for e in self._timeline.responses()
                  if e.data.get("status_code", 200) in (0, 400, 403, 404, 500, 502, 503)]
        if not errors:
            print("No network errors found.")
            return
        for e in errors:
            code = e.data.get("status_code")
            if code == 0:
                print(f"  FAILED: {e.data.get('url')}")
            else:
                print(f"  HTTP {code}: {e.data.get('url')}")

    def show_snapshots(self, max_snapshots: int = 10):
        """List available snapshot points with their labels."""
        snapshots = self._timeline.snapshots() if self._timeline else []
        if not snapshots:
            print("No snapshots recorded.")
            return
        for ev in snapshots[:max_snapshots]:
            label = ev.data.get("label", "?")
            ss = ev.data.get("screenshot_path", "-")
            dom = ev.data.get("dom_path", "-")
            rel_ss = os.path.relpath(ss, self._path) if ss and ss != "-" else "-"
            rel_dom = os.path.relpath(dom, self._path) if dom and dom != "-" else "-"
            print(f"  #{ev.seq:04d}  {label}")
            print(f"         screenshot: {rel_ss}")
            print(f"         dom:        {rel_dom}")

    def show_console_errors(self):
        """Print all console errors and JS exceptions."""
        errors = self._timeline.errors() if self._timeline else []
        if not errors:
            print("No console errors found.")
            return
        for ev in errors:
            if ev.kind == "console":
                print(f"  [{ev.data.get('level')}] {ev.data.get('text')}")
            elif ev.kind == "exception":
                print(f"  [EXCEPTION] {ev.data.get('message')}")

    # ------------------------------------------------------------------
    # Network analysis
    # ------------------------------------------------------------------

    def network_summary(self) -> NetworkSummary:
        """Aggregate all network traffic into a summary."""
        ns = NetworkSummary()
        if not self._timeline:
            return ns

        requests = self._timeline.requests()
        responses = self._timeline.responses()
        ns.total_requests = len(requests)

        duration_urls: List[Tuple[str, float]] = []
        for resp in responses:
            code = resp.data.get("status_code", 0)
            ns.status_codes[code] += 1
            dur = resp.data.get("duration_ms")
            url = resp.data.get("url", "")
            if dur is not None:
                duration_urls.append((url, dur))
            if code >= 400 or code == 0:
                ns.error_urls.append((url, code))

        for req in requests:
            rt = req.data.get("resource_type")
            if rt:
                ns.by_type[rt] += 1

        # Top 10 slowest
        duration_urls.sort(key=lambda x: x[1], reverse=True)
        ns.slowest_urls = duration_urls[:10]

        return ns

    def print_network_summary(self):
        """Print a human-readable network summary."""
        ns = self.network_summary()
        print(f"Total requests:  {ns.total_requests}")
        print(f"Status codes:    {dict(ns.status_codes)}")
        print(f"By type:         {dict(ns.by_type)}")
        if ns.slowest_urls:
            print("\nSlowest requests:")
            for url, dur in ns.slowest_urls[:5]:
                print(f"  {dur:.0f}ms  {url[:120]}")
        if ns.error_urls:
            print(f"\nError URLs ({len(ns.error_urls)}):")
            for url, code in ns.error_urls[:5]:
                print(f"  HTTP {code}  {url[:120]}")

    # ------------------------------------------------------------------
    # Pattern detection (decision support)
    # ------------------------------------------------------------------

    def detect_patterns(self, min_repeat: int = 2) -> List[Pattern]:
        """Find repeated sequences of event kinds.

        This is the foundation of "intelligent decisions" — if the same
        sequence of actions happens every time, we can suggest automating it.
        """
        if not self._timeline or len(self._timeline.events) < min_repeat * 2:
            return []

        kinds = [e.kind for e in self._timeline.events]
        patterns: List[Pattern] = []
        seen: set = set()

        # Look for repeated consecutive 2- and 3-event sequences
        for n in (2, 3):
            seq_counts: Counter = Counter()
            seq_times: Dict[Tuple[str, ...], List[float]] = defaultdict(list)
            for i in range(len(kinds) - n):
                seq = tuple(kinds[i:i + n])
                seq_counts[seq] += 1
                if len(self._timeline.events) > i + n:
                    start_t = self._timeline.events[i].timestamp
                    end_t = self._timeline.events[i + n - 1].timestamp
                    seq_times[seq].append(end_t - start_t)

            for seq, count in seq_counts.most_common():
                if count < min_repeat or seq in seen:
                    continue
                seen.add(seq)
                times = seq_times.get(seq, [0.0])
                avg_dur = sum(times) / len(times) if times else 0.0
                desc = " → ".join(seq)
                patterns.append(Pattern(
                    description=desc,
                    event_kinds=list(seq),
                    count=count,
                    avg_duration=avg_dur,
                ))

        return patterns

    def suggest_next_action(self) -> List[Suggestion]:
        """Analyse the recording and suggest what to do next.

        Uses:
        - Detected patterns (automate what repeats)
        - Network errors (retry failed requests)
        - Console errors (respond to page errors)
        """
        suggestions: List[Suggestion] = []

        if not self._timeline:
            return suggestions

        # -- Pattern-based suggestions ---------------------------------
        patterns = self.detect_patterns(min_repeat=2)
        for p in patterns[:3]:
            suggestions.append(Suggestion(
                action=f"Automate sequence: {p.description}",
                confidence=min(0.5 + 0.1 * (p.count - 2), 0.95),
                reason=f"This sequence repeats {p.count} times (avg {p.avg_duration:.1f}s)",
                supporting_evidence=[
                    f"Detected {p.count}x in recording",
                    f"Average duration: {p.avg_duration:.2f}s",
                ],
            ))

        # -- Error-based suggestions -----------------------------------
        network_errors = [e for e in self._timeline.responses() if e.data.get("status_code", 200) == 0]
        if network_errors:
            suggestions.append(Suggestion(
                action="Retry failed network requests with backoff",
                confidence=0.8,
                reason=f"{len(network_errors)} requests failed",
                supporting_evidence=[e.data.get("url", "?") for e in network_errors[:3]],
            ))

        client_errors = [e for e in self._timeline.responses() if e.data.get("status_code", 200) == 500]
        if client_errors:
            suggestions.append(Suggestion(
                action="Add wait before requests that get 500s",
                confidence=0.7,
                reason=f"{len(client_errors)} requests returned HTTP 500",
                supporting_evidence=[e.data.get("url", "?") for e in client_errors[:3]],
            ))

        console_errs = [e for e in self._timeline.errors() if e.kind == "console"]
        if console_errs:
            suggestions.append(Suggestion(
                action="Handle page console errors in script logic",
                confidence=0.6,
                reason=f"{len(console_errs)} console error messages detected",
                supporting_evidence=[e.data.get("text", "")[:80] for e in console_errs[:3]],
            ))

        # -- Timing-based suggestions ----------------------------------
        snapshots = self._timeline.snapshots() if self._timeline else []
        if len(snapshots) >= 2:
            suggestions.append(Suggestion(
                action="Add a wait after '{}'".format(snapshots[0].data.get("label", "start")),
                confidence=0.5,
                reason="Multiple snapshots indicate state transitions worth pacing",
                supporting_evidence=[f"{len(snapshots)} snapshot points recorded"],
            ))

        return suggestions

    # ------------------------------------------------------------------
    # Comparison (regression detection)
    # ------------------------------------------------------------------

    def compare(self, other: "SessionReplay") -> List[str]:
        """Compare this recording with another and return a list of differences.

        Useful for regression testing: run the same script twice and compare.
        """
        diffs: List[str] = []

        a_tl = self._timeline
        b_tl = other.timeline

        if not a_tl or not b_tl:
            diffs.append("One or both recordings are empty.")
            return diffs

        # Compare action lists
        a_actions = a_tl.actions()
        b_actions = b_tl.actions()

        if len(a_actions) != len(b_actions):
            diffs.append(
                f"Different action count: {len(a_actions)} vs {len(b_actions)}"
            )
        else:
            for i, (a, b) in enumerate(zip(a_actions, b_actions)):
                a_m = a.data.get("method", "")
                b_m = b.data.get("method", "")
                if a_m != b_m:
                    diffs.append(f"Action #{i + 1}: {a_m} vs {b_m}")

        # Compare network responses
        a_responses = a_tl.responses()
        b_responses = b_tl.responses()

        a_statuses = Counter(e.data.get("status_code") for e in a_responses)
        b_statuses = Counter(e.data.get("status_code") for e in b_responses)
        if a_statuses != b_statuses:
            diffs.append(
                f"HTTP status distribution differs: {dict(a_statuses)} vs {dict(b_statuses)}"
            )

        # Compare error counts
        a_errs = len(a_tl.errors())
        b_errs = len(b_tl.errors())
        if a_errs != b_errs:
            diffs.append(f"Error count: {a_errs} vs {b_errs}")

        # Compare duration
        a_dur = self._metadata.get("duration_seconds", 0)
        b_dur = other.metadata.get("duration_seconds", 0)
        if abs(a_dur - b_dur) > max(a_dur * 0.2, 2.0):
            diffs.append(
                f"Session duration differs significantly: "
                f"{a_dur:.1f}s vs {b_dur:.1f}s"
            )

        return diffs

    # ------------------------------------------------------------------
    # Decision helpers
    # ------------------------------------------------------------------

    def find_countdown_patterns(self) -> List[Dict[str, Any]]:
        """Scan actions for countdown-watching patterns (observer usage)."""
        results = []
        actions = self._timeline.actions() if self._timeline else []
        for ev in actions:
            method = ev.data.get("method", "")
            args = ev.data.get("args", ())
            if "wait_until" in method or "wait_until_changes" in method:
                results.append({
                    "seq": ev.seq,
                    "method": method,
                    "args": args,
                    "timestamp": ev.timestamp,
                })
        return results

    def find_page_changes(self) -> List[Dict[str, Any]]:
        """Find state transitions between consecutive snapshots.

        Returns a list of changes between snapshot points.
        """
        snapshots = self._timeline.snapshots() if self._timeline else []
        changes = []
        for i in range(1, len(snapshots)):
            prev = snapshots[i - 1]
            curr = snapshots[i]
            changes.append({
                "from_seq": prev.seq,
                "from_label": prev.data.get("label"),
                "from_url": prev.data.get("page_url"),
                "to_seq": curr.seq,
                "to_label": curr.data.get("label"),
                "to_url": curr.data.get("page_url"),
                "delta_s": curr.timestamp - prev.timestamp,
            })
        return changes
