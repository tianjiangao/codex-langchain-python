"""Scan candidate tree, new Git history and distribution archives; never auth files.

No matched values are printed. This is a bounded automated review, not a proof
of absence of every secret. Do not use it to inspect the user's Codex home.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW = {"src", "tests", "examples", "integrations", "docs", "scripts", ".github", "licenses"}
ROOT_FILES = {
    "README.md",
    "LICENSE",
    "NOTICE",
    "pyproject.toml",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "COMPATIBILITY.md",
    ".gitignore",
}
PATTERNS = {
    "credential_format": re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,})"
    ),
    "jwt_format": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "bearer_value": re.compile(r"Bearer\s+[A-Za-z0-9._~-]{20,}", re.I),
    "personal_absolute_path": re.compile(
        r"/(?:home|Users)/[A-Za-z0-9_.-]+|[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+"
    ),
    "assigned_secret": re.compile(
        r"\b(?:api_key|access_token|refresh_token|password|cookie)\b\s*[:=]\s*['\"][^'\"\s]{16,}['\"]",
        re.I,
    ),
}
FORBIDDEN_NAMES = {"auth.json", "credentials.json", "cookies.json", ".env"}
FORBIDDEN_PARTS = {"private", "work", ".venv", ".git", "__pycache__"}
findings = []


def scan(name, data, scope):
    path = Path(name)
    if (
        set(path.parts) & FORBIDDEN_PARTS
        or path.name.lower() in FORBIDDEN_NAMES
        or path.suffix in {".jsonl", ".sqlite", ".db", ".log", ".csv"}
    ):
        findings.append({"scope": scope, "file": name, "category": "private_or_raw_artifact_name"})
    text = data.decode("utf-8", errors="replace")
    for category, pattern in PATTERNS.items():
        if pattern.search(text):
            findings.append({"scope": scope, "file": name, "category": category})


def audit(archives=()):
    expected_licenses = json.loads((ROOT / "docs/extraction_sources.json").read_text()).get(
        "license_sha256", {}
    )
    for name, expected in expected_licenses.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            findings.append(
                {"scope": "candidate_tree", "file": name, "category": "license_content_mismatch"}
            )
    files = []
    for name in sorted(ROOT_FILES):
        p = ROOT / name
        if p.exists():
            files.append(p)
    for name in sorted(ALLOW):
        files.extend(
            p for p in (ROOT / name).rglob("*") if p.is_file() and "__pycache__" not in p.parts
        )
    for p in files:
        scan(str(p.relative_to(ROOT)), p.read_bytes(), "candidate_tree")
    git_objects = 0
    if (ROOT / ".git").exists():
        # Scan committed blobs only, without printing file content or traversing original history.
        commits = subprocess.check_output(
            ["git", "rev-list", "--all"], cwd=ROOT, text=True
        ).splitlines()
        seen = set()
        for commit in commits:
            records = subprocess.check_output(
                ["git", "ls-tree", "-r", "-z", commit], cwd=ROOT
            ).split(b"\0")
            for record in records:
                if not record:
                    continue
                info, name = record.split(b"\t", 1)
                _, kind, oid = info.split()
                if kind != b"blob" or oid in seen:
                    continue
                seen.add(oid)
                scan(
                    name.decode(),
                    subprocess.check_output(["git", "cat-file", "blob", oid], cwd=ROOT),
                    "new_git_history",
                )
        git_objects = len(seen)
    archive_members = 0
    for path in archives:
        p = Path(path)
        if p.suffix == ".whl":
            with zipfile.ZipFile(p) as z:
                for name in z.namelist():
                    if not name.endswith("/"):
                        data = z.read(name)
                        scan(name, data, "wheel")
                        for license_path, expected in expected_licenses.items():
                            if (
                                name.endswith("/" + license_path)
                                and hashlib.sha256(data).hexdigest() != expected
                            ):
                                findings.append(
                                    {
                                        "scope": "wheel",
                                        "file": name,
                                        "category": "license_content_mismatch",
                                    }
                                )
                        archive_members += 1
        else:
            with tarfile.open(p, "r:*") as t:
                for entry in t.getmembers():
                    if entry.isfile():
                        data = t.extractfile(entry).read()
                        scan(entry.name, data, "sdist")
                        for license_path, expected in expected_licenses.items():
                            if (
                                entry.name.endswith("/" + license_path)
                                and hashlib.sha256(data).hexdigest() != expected
                            ):
                                findings.append(
                                    {
                                        "scope": "sdist",
                                        "file": entry.name,
                                        "category": "license_content_mismatch",
                                    }
                                )
                        archive_members += 1
    report = {
        "status": "PASS" if not findings else "FAIL",
        "candidate_files": len(files),
        "new_git_blobs": git_objects,
        "archive_members": archive_members,
        "findings": findings,
        "scope": "Only new candidate allowlist, its fresh Git history, and supplied wheel/sdist. No source auth files or private raw logs read.",
        "limits": "Pattern-based bounded review; human approval still required. Original project history is not imported or claimed cleared.",
    }
    print(json.dumps(report, indent=2))
    if findings:
        raise SystemExit(1)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archives", nargs="*", default=[])
    audit(parser.parse_args().archives)
