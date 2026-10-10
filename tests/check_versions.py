"""Checks that every place holding the version number agrees with APP_VERSION in wuwa_app.py.

    python tests/check_versions.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


version = re.search(r'APP_VERSION = "([0-9.]+)"', read("wuwa_app.py")).group(1)
four_parts = version + ".0"
expected = {
    "version.txt": [four_parts, "(%s)" % ",".join((four_parts).split("."))],
    "installer.iss": ['#define AppVer "%s"' % version, "VersionInfoVersion=" + four_parts],
    "installer_embedded.iss": ['#define AppVer "%s"' % version, "VersionInfoVersion=" + four_parts],
    ".github/workflows/build-nuitka.yml": ["--file-version=" + four_parts, "--product-version=" + four_parts],
}
missing = ["%s: %s" % (name, text) for name, texts in expected.items() for text in texts if text not in read(name)]
print("APP_VERSION =", version)
if missing:
    print("Version number missing or different in:\n  " + "\n  ".join(missing))
    sys.exit(1)
print("All version numbers match.")
