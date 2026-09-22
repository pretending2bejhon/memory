"""Repository-contained Patchright harness shared by city and audio checks.

Install Patchright into .tools/browser or the active Python environment. The
default browser is installed Chrome, running headless with a fresh context and
normal autoplay restrictions. No personal browser profile is accessed.
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / ".tools" / "browser"))
from patchright.sync_api import sync_playwright


class Engine:
    """Small explicit browser owner; evaluate always uses the page world."""

    def __init__(self, width=1440, height=900, timeout=30):
        self.width = width
        self.height = height
        self.timeout = timeout * 1000
        self.errors = []
        self._playwright = None
        self.browser = None

    def __enter__(self):
        self._playwright = sync_playwright().start()
        try:
            self.browser = self._playwright.chromium.launch(
                channel=os.environ.get("VC_BROWSER_CHANNEL", "chrome"),
                headless=True,
            )
            self.context = self.browser.new_context(
                viewport={"width": self.width, "height": self.height},
                device_scale_factor=1,
            )
            self.page = self.context.new_page()
            self._page = self.page
            self.page.set_default_timeout(self.timeout)
            self.page.on("pageerror", lambda error: self.errors.append(str(error)))
            self.page.on("console", self._console)
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def _console(self, message):
        if message.type == "error":
            self.errors.append(message.text)

    def __exit__(self, *_):
        if self.browser:
            self.browser.close()
        if self._playwright:
            self._playwright.stop()

    def goto(self, url):
        return self.page.goto(url, wait_until="domcontentloaded")

    def evaluate(self, expression, arg=None):
        return self.page.evaluate(expression, arg, isolated_context=False)

    def ready(self):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.evaluate("Boolean(window.__vc)"):
                return
            self.wait(.1)
        raise RuntimeError("Viewer did not initialize within 45 seconds; errors: " + repr(self.errors))

    def wait(self, seconds):
        # Keep event dispatch active while waiting, including console/pageerror.
        self.page.wait_for_timeout(seconds * 1000)

    def click(self, selector):
        self.page.locator(selector).click()

    def screenshot(self, path):
        self.page.screenshot(path=str(path), full_page=False)


def measure_frames(engine):
    """Existing report method: 40 rAF intervals, discard the first five.

    Keep the original rounded frameTimeMs field, but derive fps from the
    unrounded mean so a rounded 18 ms does not incorrectly fail a 55 fps gate.
    """
    return engine.evaluate("""() => new Promise(resolve => {
      const times = []; let last = performance.now();
      function tick(now) {
        times.push(now - last); last = now;
        if (times.length === 40) {
          const samples = times.slice(5);
          const mean = samples.reduce((a, b) => a + b, 0) / samples.length;
          resolve({frameTimeMs: Math.round(mean), frameTimeMeanMs: mean,
                   fps: 1000 / mean, frameSamples: samples.length,
                   maxFrameMs: Math.max(...samples),
                   framesOver33Ms: samples.filter(value => value > 33).length});
        } else requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    })""")
