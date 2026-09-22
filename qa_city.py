"""Visual and ride-camera verification using the local Patchright harness."""

import argparse
import json
from pathlib import Path

from qa_browser import Engine, measure_frames

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/viewer/")
    parser.add_argument("--prefix", default="", help="Filename prefix inside renders/qa")
    args = parser.parse_args()
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in args.prefix):
        parser.error("--prefix must contain only letters, digits, hyphens or underscores")
    output = ROOT / "renders" / "qa"
    output.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix + "-" if args.prefix else ""
    path = lambda name: output / (prefix + name)

    with Engine(width=1440, height=900, timeout=30) as eng:
        evaluate = eng.evaluate
        eng.goto(args.url)
        eng.ready()
        eng.wait(2)
        eng.screenshot(path("overview.png"))
        report = evaluate("""() => {
          const v = window.__vc;
          const failures = [], walkingFailures = []; let samples = 0;
          for (const route of v.routes) for (let d = 0; d < route.length; d += .10) {
            const p = v.poseOnRoute(route, d); samples++;
            const raw = v.sampleRoute(route, d); raw.y += .64;
            if (v.pointBlocked(raw, .14, false) || v.pointBlocked(p.eye, .14, false) || !v.clearSight(p.eye, p.look)) failures.push({route: route.name, d});
            for (const side of [-1, 1]) {
              const foot = v.sampleRoute(route, d, undefined, Math.min(route.width / 2 + .04, route.clearance - .12) * side); foot.y += .18;
              if (v.pointBlocked(foot, .07, false)) walkingFailures.push({route: route.name, d, side});
            }
          }
          return {buildings: v.nodes.length, people: v.people.length, routes: v.routes.length,
            samples, failures: failures.slice(0, 20), failureCount: failures.length,
            walkingFailures: walkingFailures.slice(0, 20), walkingFailureCount: walkingFailures.length,
            drawCalls: v.renderer.info.render.calls, triangles: v.renderer.info.render.triangles};
        }""")
        report["url"] = args.url
        report.update(measure_frames(eng))
        eng.click("#ride")
        eng.wait(3)
        eng.screenshot(path("ride-archive.png"))
        report["archiveRide"] = evaluate("""() => ({active: window.__vc.state.ride,
            eye: window.__vc.camera.position.toArray(),
            clipped: window.__vc.pointBlocked(window.__vc.camera.position),
            fov: window.__vc.camera.fov})""")
        eng.page.keyboard.press("Escape")
        eng.click('.chip[data-d="working"]')
        eng.wait(2)
        eng.screenshot(path("downtown.png"))
        report["districtFocus"] = evaluate("() => window.__vc.state.isolate")
        eng.click("#ride")
        eng.wait(3)
        eng.screenshot(path("ride-downtown.png"))
        report["downtownRide"] = evaluate("""() => ({active: window.__vc.state.ride,
            district: window.__vc.routes[window.__vc.state.ride]?.district,
            clipped: window.__vc.pointBlocked(window.__vc.camera.position)})""")
        eng.page.keyboard.press("Escape")
        report["returnControls"] = evaluate("""() => ({enabled: window.__vc.controls.enabled,
            ride: window.__vc.state.ride, fov: window.__vc.camera.fov})""")
        evaluate("() => window.__vc.updateWeek(0)")
        eng.wait(.5)
        report["week0"] = evaluate("""() => ({visible: window.__vc.nodes.filter(n => n.state !== 'absent').length,
            finite: window.__vc.nodes.every(n => Number.isFinite(n.h))})""")
        evaluate("() => window.__vc.updateWeek(12)")
        report["week12"] = evaluate("() => ({visible: window.__vc.nodes.filter(n => n.state !== 'absent').length})")
        eng.click(".chip:first-child")
        eng.page.set_viewport_size({"width": 375, "height": 844})
        eng.page.reload(wait_until="domcontentloaded")
        eng.ready()
        eng.wait(2)
        eng.screenshot(path("mobile.png"))
        eng.click("#ride")
        eng.wait(1)
        eng.screenshot(path("mobile-ride.png"))
        report["mobile"] = evaluate("""() => ({width: innerWidth,
            overflow: document.documentElement.scrollWidth > innerWidth,
            ride: window.__vc.state.ride})""")
        report["errors"] = eng.errors
        checks = {
            "node census": report["buildings"] == 1246,
            "route collision clearance": report["failureCount"] == 0,
            "walking lane clearance": report["walkingFailureCount"] == 0,
            "archive ride": report["archiveRide"]["active"] >= 0 and not report["archiveRide"]["clipped"] and report["archiveRide"]["fov"] == 62,
            "district focus": report["districtFocus"] == "working",
            "downtown ride": report["downtownRide"]["district"] == "working" and not report["downtownRide"]["clipped"],
            "overview restored": report["returnControls"] == {"enabled": True, "ride": -1, "fov": 39},
            "timeline": report["week0"]["finite"] and report["week0"]["visible"] < report["week12"]["visible"],
            "375 px mobile": report["mobile"]["width"] == 375 and not report["mobile"]["overflow"] and report["mobile"]["ride"] >= 0,
            "page and console errors": not report["errors"],
        }
        failures = [name for name, passed in checks.items() if not passed]
        report["checks"] = checks
        report["passed"] = not failures
        report["failedChecks"] = failures
        rendered = json.dumps(report, indent=2)
        path("report.json").write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
