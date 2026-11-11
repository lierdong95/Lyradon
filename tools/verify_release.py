# SPDX-License-Identifier: MIT
"""Offline release review: strict file allowlist, hashes and common privacy patterns.

Run on the clean distribution, before creating personal local configuration.
This cannot identify every person's name or every possible sensitive statement;
manual content review remains necessary. No network calls or module imports.
"""
from pathlib import Path
import ast
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "PUBLIC_MANIFEST.json"
SENSITIVE_KEYS = {"token", "password", "secret", "api_key", "access_token", "recovery_key", "http_token", "ws_token"}
PATTERNS = {
    "absolute Windows path": re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]"),
    "personal email candidate": re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    "embedded URL credentials": re.compile(r"(?:https?|wss?)://[^/\s]+@"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "access key candidate": re.compile(r"(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})"),
}


def check_config(value, location, errors):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in SENSITIVE_KEYS and item not in (None, ""):
                errors.append(f"{location}: nonempty credential field {key}")
            if key in {"groups"} and item != []:
                errors.append(f"{location}: example group list must be empty")
            if key == "group_id" and item != 123456789:
                errors.append(f"{location}: unexpected group placeholder")
            if key == "enabled" and item is not False:
                errors.append(f"{location}: example must be disabled")
            check_config(item, location, errors)
    elif isinstance(value, list):
        for item in value:
            check_config(item, location, errors)


def main():
    errors = []
    if not MANIFEST.is_file():
        print("FAIL: PUBLIC_MANIFEST.json is missing")
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = {item["path"]: item["sha256"] for item in manifest["files"]}
    actual = {p.relative_to(ROOT).as_posix(): p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.relative_to(ROOT).parts}
    allowed = set(expected) | {MANIFEST.name}
    for name in sorted(set(actual) - allowed):
        errors.append(f"Unexpected file: {name}")
    for name in sorted(set(expected) - set(actual)):
        errors.append(f"Missing file: {name}")
    for name, p in actual.items():
        if p.is_symlink():
            errors.append(f"Symlink is not a release file: {name}")
        raw = p.read_bytes()
        if name in expected and hashlib.sha256(raw).hexdigest() != expected[name]:
            errors.append(f"Changed since review: {name}")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            errors.append(f"Unexpected binary/encoding: {name}")
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{name}: {label}")
        if p.suffix == ".py":
            try:
                ast.parse(text)
            except SyntaxError as exc:
                errors.append(f"{name}: Python syntax line {exc.lineno}")
        if p.suffix == ".json":
            try:
                data = json.loads(text)
                if name.endswith(".example.json"):
                    check_config(data, name, errors)
            except ValueError:
                errors.append(f"{name}: invalid JSON")
    for directory in ROOT.rglob("*"):
        if directory != ROOT / ".git" and directory.is_dir() and directory.name in {".git", ".venv", "__pycache__", "character", "napcat", "QQNT"}:
            errors.append("Runtime/private directory present: " + directory.relative_to(ROOT).as_posix())
    if errors:
        for error in errors:
            print("FAIL:", error)
        return 1
    print(f"PASS: {len(expected)} reviewed files + manifest; hashes, syntax and example privacy checks passed.")
    print("Scope: prepared public copy only; no live service or online integration was tested.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
