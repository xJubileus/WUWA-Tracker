"""Runs tests/logic_tests.js against the UI code of wuwa_app.py, in the same engine the app uses
(Edge WebView2 through pywebview), inside a hidden window.

    python tests/test_logic.py

Prints one line per test and exits with code 1 when a test fails.
"""
import json
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import webview  # noqa: E402
import wuwa_app  # noqa: E402

# Stands in for the Python API, so the page boots without touching the real saved data.
FAKE_API = """<script>
window.pywebview = {api: new Proxy({}, {get: (_, name) => () => Promise.resolve(
  name === 'load' || name === 'load_tasks' || name === 'tasks_changed' ? '' : name === 'take_notices' ? [] : null)})};
</script>"""


def main():
    tests = open(os.path.join(ROOT, "tests", "logic_tests.js"), encoding="utf-8").read()
    html = wuwa_app.HTML.replace("<body>", "<body>" + FAKE_API, 1).replace("</body>", "<script>" + tests + "</script></body>", 1)
    outcome = {}

    def run(window):
        try:
            threading.Event().wait(1.5)   # let the page boot
            outcome["results"] = json.loads(window.evaluate_js("JSON.stringify(runTests())"))
        except Exception as error:
            outcome["error"] = repr(error)
        finally:
            window.destroy()

    window = webview.create_window("WUWA Tracker tests", html=html, hidden=True)
    webview.start(run, window, private_mode=True)

    if "error" in outcome:
        print("Could not run the tests:", outcome["error"])
        return 1
    failed = 0
    for result in outcome["results"]:
        if result["ok"]:
            print("  ok    " + result["name"])
        else:
            failed += 1
            print("  FAIL  %s\n        %s" % (result["name"], result["error"]))
    total = len(outcome["results"])
    print("\n%d of %d tests passed." % (total - failed, total))
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)   # pywebview can leave threads behind; do not hang after the summary
