"""Full Grand Tour timing gate and its disabled-controller positive control.

This runs a real sound-on browser session. qa_world calls verify_tour() in
its cumulative V5 block.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "qa_browser.py").is_file()
             and (p / "viewer").is_dir()), None)
if ROOT is None:
    raise RuntimeError("Could not find the repository root")
sys.path.insert(0, str(ROOT))
from qa_browser import Engine


def snapshot(engine):
    return engine.evaluate("""() => {
      const v = window.__vc, t = v.tour;
      return {ready: Boolean(t), active: Boolean(t?.active),
        sound: v.beat.sound, enabled: v.audio.enabled, room: v.beat.room,
        sourceChanges: v.beat.diagnostics.sourceChanges,
        crossings: t ? t.debug.crossings.map(x => ({...x})) : [],
        wrongDrops: t?.debug.wrongDrops ?? null,
        surfaceGaps: t?.debug.surfaceGaps ?? null,
        errors: t?.debug.firstMiss ?? null,
        jointGap: t?.debug.jointGap ?? null,
        pass: t?.debug.crossings.filter(x => x.pass === 0).length ?? 0};
    }""")


def open_tour(engine, url, control):
    engine.page.goto("about:blank")
    engine.goto(url)
    engine.ready()
    deadline = time.monotonic() + 90
    engine.click("#sound")
    while time.monotonic() < deadline:
        if engine.evaluate("() => window.__vc.audio.enabled && window.__vc.audio.ready && window.__vc.beat.sound"):
            break
        engine.wait(1)
    else:
        raise RuntimeError("Sound did not become ready for the tour gate")
    engine.click("#ride")
    if control:
        engine.evaluate("() => { window.__vc.tour.debug.noSpeedControl = true; }")
    state = snapshot(engine)
    if not state["active"]:
        raise RuntimeError("The Ride control did not start the Grand Tour")
    return state


def timing_checks(state, expected=15):
    beat = 60 / 140
    crossings = state["crossings"][:expected]
    return {
        "tour: every planned boundary crossed within one beat of its drop":
            len(crossings) == expected and all(abs(x["errorSeconds"]) <= beat for x in crossings),
        "tour: cut beat stays on every bridge deck longer than a beat":
            len(crossings) == expected and all(x["cutOnDeck"] for x in crossings if x["deckSeconds"] > beat),
        "tour: at least eight bars of groove before every next transition":
            len(crossings) == expected and all(x["grooveBars"] >= 8 for x in crossings),
        "tour: all rooms and road surfaces remain valid":
            len(crossings) == expected and all(x["roomAtCrossing"] == x["to"] for x in crossings)
            and state["wrongDrops"] == 0 and state["surfaceGaps"] == 0,
    }


def verify_tour(engine, url, prefix="b-v5", output=None, max_seconds=900):
    """Return the regular checks and a control that must fail the timing check."""
    output = output or ROOT / "renders" / "qa"
    output.mkdir(parents=True, exist_ok=True)
    start = open_tour(engine, url, False)
    begun = time.monotonic()
    sound_on_throughout = bool(start["sound"] and start["enabled"])
    while time.monotonic() - begun < max_seconds:
        engine.wait(2)
        state = snapshot(engine)
        sound_on_throughout &= bool(state["sound"] and state["enabled"])
        if state["pass"] >= 1 and not (output / f"{prefix}-tour-drop.png").exists():
            engine.screenshot(output / f"{prefix}-tour-drop.png")
        if state["pass"] >= 15 or state["surfaceGaps"]:
            break
    regular = timing_checks(state)
    regular["tour: sound remains on for the whole run"] = (
        sound_on_throughout and state["sourceChanges"] == start["sourceChanges"])
    regular["tour: browser errors"] = not engine.errors

    control_start = open_tour(engine, url, True)
    control_begun = time.monotonic()
    while time.monotonic() - control_begun < min(max_seconds, 180):
        engine.wait(2)
        control_state = snapshot(engine)
        if control_state["errors"] or len(control_state["crossings"]) >= 3:
            break
    control_red = bool(control_state["crossings"]) and any(
        abs(x["errorSeconds"]) > 60 / 140 for x in control_state["crossings"])
    control = {
        "tour: disabling speed control misses a drop by more than one beat":
            control_start["active"] and control_red,
    }
    result = {"start": start, "regular": state, "control": control_state,
              "checks": regular, "positiveControls": control,
              "passed": all(regular.values()) and all(control.values()),
              "durationSeconds": time.monotonic() - begun}
    (output / f"{prefix}-tour-report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/viewer/")
    parser.add_argument("--prefix", default="b-v5")
    parser.add_argument("--max-seconds", type=int, default=900)
    args = parser.parse_args()
    if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.prefix):
        parser.error("--prefix must contain only letters, digits, hyphens or underscores")
    with Engine(width=1440, height=900) as engine:
        result = verify_tour(engine, args.url, args.prefix, max_seconds=args.max_seconds)
    print(json.dumps({"checks": result["checks"], "positiveControls": result["positiveControls"],
                      "passed": result["passed"]}, indent=2))
    return int(not result["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
