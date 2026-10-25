"""Fail if a backend or frontend dependency has a license outside the allowlist.

Backend licenses come from pip-licenses over backend/.venv (run `uv sync` first);
frontend licenses from `pnpm licenses list --json`. Anything unrecognised fails.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIP_LICENSES = "pip-licenses@5.5.5"

ALLOWED = {
    "MIT",
    "MIT-0",
    "MIT-CMU",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "0BSD",
    "Apache-2.0",
    "ISC",
    "PSF-2.0",
    "MPL-2.0",
    "Zlib",
    "CC0-1.0",
    "BlueOak-1.0.0",
    "CNRI-Python",
    "Unlicense",
    # The GPL family is allowed because Oracle is local and single-user (and already
    # ships AGPL-3.0 pymupdf).
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "LGPL-2.1-only",
    "LGPL-2.1-or-later",
    "LGPL-3.0-only",
    "LGPL-3.0-or-later",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
}

# Free-text license names (lowercase) seen in package metadata -> SPDX id.
# "bsd license" and "apache software license" are classifier-level names, broader
# than the SPDX ids they map to; accepted as such.
ALIASES = {
    "mit license": "MIT",
    "apache software license": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "bsd license": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause",
    "isc license (iscl)": "ISC",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "python software foundation license": "PSF-2.0",
    "the unlicense (unlicense)": "Unlicense",
    "gnu general public license v2 (gplv2)": "GPL-2.0-only",
    "gnu general public license v2 or later (gplv2+)": "GPL-2.0-or-later",
    "gnu general public license v3 (gplv3)": "GPL-3.0-only",
    "gnu general public license v3 or later (gplv3+)": "GPL-3.0-or-later",
    "gnu lesser general public license v2 (lgplv2)": "LGPL-2.1-only",
    "gnu lesser general public license v2 or later (lgplv2+)": "LGPL-2.1-or-later",
    "gnu lesser general public license v3 (lgplv3)": "LGPL-3.0-only",
    "gnu lesser general public license v3 or later (lgplv3+)": "LGPL-3.0-or-later",
    "gnu affero general public license v3": "AGPL-3.0-only",
    "gnu affero general public license v3 or later (agplv3+)": "AGPL-3.0-or-later",
    # pymupdf's own free-text string (an AGPL-3.0 / Artifex commercial dual license)
    "dual licensed - gnu affero gpl 3.0 or artifex commercial license": "AGPL-3.0-only",
}

# (package, reported license) -> why it is accepted. Matching the reported string
# too means a real relicense (a changed string) fails instead of passing silently.
_SHIM_NOTE = (
    "empty shim shipped with pymupdf 2.x, no license metadata; AGPL-3.0 like pymupdf"
)
_STEMMER_NOTE = (
    "no license metadata; the wheel's LICENSE file is MIT (qdrant), "
    "pulled in by fastembed"
)
_TIKTOKEN_NOTE = "MIT; pip-licenses reports the whole license body, not a name"
_TIKTOKEN_MIT = (
    "MIT License\n"
    "\n"
    "Copyright (c) 2022 OpenAI, Shantanu Jain\n"
    "\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
    'of this software and associated documentation files (the "Software"), to deal\n'
    "in the Software without restriction, including without limitation the rights\n"
    "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
    "copies of the Software, and to permit persons to whom the Software is\n"
    "furnished to do so, subject to the following conditions:\n"
    "\n"
    "The above copyright notice and this permission notice shall be included in all\n"
    "copies or substantial portions of the Software.\n"
    "\n"
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\n'
    "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\n"
    "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\n"
    "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\n"
    "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\n"
    "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\n"
    "SOFTWARE.\n"
)
EXCEPTIONS = {
    ("tiktoken", _TIKTOKEN_MIT): _TIKTOKEN_NOTE,
    ("pymupdf4llm", "UNKNOWN"): _SHIM_NOTE,
    ("pymupdf_layout", "UNKNOWN"): _SHIM_NOTE,
    ("py_rust_stemmers", "UNKNOWN"): _STEMMER_NOTE,
}

SPLIT = re.compile(r"(\(|\)|\s+AND\s+|\s+OR\s+)")


def parse(expr: str) -> bool:
    """Whether the license expression is allowed: OR needs one branch, AND all."""
    # Whole-string names first: some contain parentheses.
    if (alias := ALIASES.get(expr.lower())) is not None:
        return alias in ALLOWED
    # pip-licenses joins multiple classifiers with ";", which means all of them apply.
    tokens = [t.strip() for t in SPLIT.split(expr.replace(";", " AND ")) if t.strip()]
    pos = 0

    def or_expr() -> bool:
        nonlocal pos
        result = and_expr()
        while pos < len(tokens) and tokens[pos] == "OR":
            pos += 1
            result = and_expr() or result
        return result

    def and_expr() -> bool:
        nonlocal pos
        result = atom()
        while pos < len(tokens) and tokens[pos] == "AND":
            pos += 1
            result = atom() and result
        return result

    def atom() -> bool:
        nonlocal pos
        token = tokens[pos]
        pos += 1
        if token == "(":
            result = or_expr()
            if tokens[pos] != ")":
                raise ValueError("unbalanced parenthesis")
            pos += 1
            return result
        return ALIASES.get(token.lower(), token) in ALLOWED

    result = or_expr()
    if pos != len(tokens):
        raise ValueError("trailing tokens")
    return result


def first_line(text: str) -> str:
    return (text.splitlines() or [""])[0]


def is_allowed(name: str, license_: str) -> bool:
    if (name, license_) in EXCEPTIONS:
        return True
    try:
        return parse(license_)
    except (IndexError, ValueError):  # empty or malformed expression
        return False


SELF_TEST = [
    ("", False),
    ("MIT OR", False),
    ("(MIT", False),
    ("MIT)", False),
    ("()", False),
    ("MIT WITH Classpath-exception-2.0", False),
    ("mit", False),
    ("UNKNOWN", False),
    ("MIT\nSSPL-1.0", False),
    ("MIT OR SSPL-1.0", True),
    ("MIT OR SSPL-1.0 AND BUSL-1.1", True),
    ("MIT AND SSPL-1.0", False),
    ("Apache Software License; BSD License", True),
    ("Apache Software License; BUSL-1.1", False),
    ("Acme Proprietary EULA", False),
    ("SSPL-1.0", False),
    ("BUSL-1.1", False),
    ("Unlicense", True),
    ("GPL-2.0-only", True),
    ("GPL-2.0-or-later", True),
    ("GPL-3.0-only", True),
    ("GPL-3.0-or-later", True),
    ("LGPL-2.1-only", True),
    ("LGPL-2.1-or-later", True),
    ("LGPL-3.0-only", True),
    ("LGPL-3.0-or-later", True),
    ("AGPL-3.0-only", True),
    ("AGPL-3.0-or-later", True),
    ("MIT AND GPL-3.0-only", True),
    ("GNU General Public License v2 (GPLv2)", True),
    ("GNU General Public License v2 or later (GPLv2+)", True),
    ("GNU General Public License v3 (GPLv3)", True),
    ("GNU General Public License v3 or later (GPLv3+)", True),
    ("GNU Lesser General Public License v2 (LGPLv2)", True),
    ("GNU Lesser General Public License v2 or later (LGPLv2+)", True),
    ("GNU Lesser General Public License v3 (LGPLv3)", True),
    ("GNU Lesser General Public License v3 or later (LGPLv3+)", True),
    ("GNU Affero General Public License v3", True),
    ("GNU Affero General Public License v3 or later (AGPLv3+)", True),
    ("The Unlicense (Unlicense)", True),
    ("Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License", True),
    ("Mozilla Public License 2.0 (MPL 2.0)", True),
]


def self_test() -> None:
    for license_, expected in SELF_TEST:
        if is_allowed("pkg", license_) != expected:
            sys.exit(f"self-test failed: {license_!r} should be allowed={expected}")


def backend_packages(json_file: str | None) -> list[tuple[str, str]]:
    if json_file is not None:
        raw = Path(json_file).read_text()
    else:
        raw = subprocess.run(
            [
                "uvx",
                PIP_LICENSES,
                "--python",
                str(ROOT / "backend/.venv/bin/python"),
                "--from=mixed",
                "--format=json",
                "--ignore-packages",
                "oracle",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    return [(p["Name"], p["License"]) for p in json.loads(raw)]


def frontend_packages(json_file: str | None) -> list[tuple[str, str]]:
    if json_file is not None:
        raw = Path(json_file).read_text()
    else:
        raw = subprocess.run(
            ["pnpm", "licenses", "list", "--json"],
            check=True,
            capture_output=True,
            text=True,
            cwd=ROOT / "frontend",
        ).stdout
    by_license = json.loads(raw)
    return [(p["name"], lic) for lic, pkgs in by_license.items() for p in pkgs]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ecosystems", nargs="*", choices=["backend", "frontend"])
    parser.add_argument("--backend-json", help="read pip-licenses JSON from a file")
    parser.add_argument("--frontend-json", help="read pnpm licenses JSON from a file")
    args = parser.parse_args()
    self_test()

    sources = {
        "backend": lambda: backend_packages(args.backend_json),
        "frontend": lambda: frontend_packages(args.frontend_json),
    }
    failures = 0
    for ecosystem in args.ecosystems or ["backend", "frontend"]:
        packages = sources[ecosystem]()
        bad = sorted((n, lic) for n, lic in packages if not is_allowed(n, lic))
        print(f"{ecosystem}: {len(packages)} packages, {len(bad)} disallowed")
        for name, lic in bad:
            print(f"  DISALLOWED {ecosystem}: {name}: {first_line(lic)[:80]}")
        failures += len(bad)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
