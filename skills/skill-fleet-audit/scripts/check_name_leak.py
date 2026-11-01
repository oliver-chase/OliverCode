#!/usr/bin/env python3
"""Fleet sweep for a real personal name or email in a tracked file. Do not add a real name to this
file's own prose: this docstring is tracked source, and a real name here would be the leak the
script exists to catch.

Three checks:
1. Known-real-identity leak (blocks). A gitignored `.env.local` is where a real name or email
   belongs. The check reads each name and email from every real `.env.local` under the fleet root
   and greps every other file for those exact strings. Any hit is a leak.
2. Filename-example name (advisory). A two-capitalized-word sequence directly against a
   filename cue (`.pdf`, `.docx`, `Resume`) is a candidate for a human look. An example name must
   be one of ESTABLISHED_PLACEHOLDERS.
3. Machine leak (blocks). A skill file that holds the machine account's name or a path under a
   home folder. Test files are skipped, since a fixture needs a sample path. Every token is
   derived at run time.

Usage:
    check_name_leak.py                 # scan the whole fleet
    check_name_leak.py <path-or-dir>   # scan one folder
Tests: python3 -m unittest test_check_name_leak   (from this scripts/ folder)
"""

import getpass
import platform
import re
import subprocess
import sys

import _fleet

SKILLS_ROOT = _fleet.FLEET_ROOT

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
TWO_CAP_WORDS = re.compile(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b")

# .env.local keys that hold a 2-capitalized-word VALUE that is NOT a person's name --
# excluded from tier-1 name-token extraction to keep false positives out of the search list.
NON_NAME_KEY_HINTS = (
    "SHEET", "TEMPLATE", "CONVENTION", "COLUMN", "FOLDER",
    "DOMAIN", "PATH", "TRACKER", "OUTPUT", "SUBJECT", "CHECKLIST",
)

# The shape a leaked example name takes: a name sitting directly against a filename/extension,
# e.g. "Jane Doe_Resume.pdf" or "2510 - John Smith_Resume (Sally May).pdf" -- tight
# adjacency, not "the word résumé appears somewhere on this line" (that alone is common,
# generic prose about résumé folders/fields, and floods this check with noise).
NAME_NEAR_FILENAME = re.compile(
    r"[A-Z][a-z]+ [A-Z][a-z]+(?=[_ ]?(?:Resume|Résumé|CV)?\.(?:pdf|docx|dotx)\b|_Resume)"
)
# Known blind spot: a surname with an internal capital (DeLeon, McDonald, O'Brien) breaks the
# `[A-Z][a-z]+` word shape and slips through both patterns above. Accepted -- chasing every
# capitalization convention turns this into real NER, out of scope for a mechanical check.
# Simple "First Last" Title Case names (the common case) are what this catches.


def find_env_local_files(root):
    return sorted(root.glob("*/**/.env.local"))


def extract_identity_tokens(env_path):
    """(name-or-email, source-line-description) tuples from one real .env.local."""
    tokens = []
    text = env_path.read_text(encoding="utf-8", errors="ignore")
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not value:
            continue

        for email in EMAIL_PATTERN.findall(value):
            tokens.append((email, f"{env_path}:{lineno} ({key})"))

        # Name:email:role,Name:email:role,... roster shape (a *_STAFF or *_ROSTER key).
        # Restricted to a *_STAFF/*_ROSTER key specifically -- a generic "comma + colon"
        # value (e.g. FolderName:status pairs) is not a name roster.
        if "STAFF" in key or "ROSTER" in key:
            for segment in value.split(","):
                segment = segment.strip()
                name = segment.split(":", 1)[0].strip()
                if TWO_CAP_WORDS.fullmatch(name):
                    tokens.append((name, f"{env_path}:{lineno} ({key} roster entry)"))
            continue

        # Single NAME/CONTACT-shaped key holding a plain "First Last" value.
        if any(hint in key for hint in NON_NAME_KEY_HINTS):
            continue
        if ("NAME" in key or "CONTACT" in key) and TWO_CAP_WORDS.fullmatch(value):
            tokens.append((value, f"{env_path}:{lineno} ({key})"))

    return tokens


def iter_tracked_files(root):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in (".env.local",) or path.suffix == ".example":
            continue
        if ".env.local.example" in path.name:
            continue
        if path.suffix in (".md", ".py", ".json"):
            yield path


def check_known_identity_leaks(root):
    env_files = find_env_local_files(root)
    all_tokens = []
    for env_path in env_files:
        all_tokens.extend(extract_identity_tokens(env_path))
    if not all_tokens:
        return [], len(env_files)

    tracked_files = list(iter_tracked_files(root))
    findings = []
    for token, source in all_tokens:
        pattern = re.compile(r"\b" + re.escape(token) + r"\b") if " " not in token and "@" not in token else None
        for path in tracked_files:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if (pattern.search(text) if pattern else token in text):
                lineno = next(
                    (i for i, l in enumerate(text.splitlines(), start=1)
                     if (pattern.search(l) if pattern else token in l)), None
                )
                findings.append(
                    f"{path.relative_to(root.parent)}:{lineno} -- '{token}' (real value from "
                    f"{source}) sits in a tracked file"
                )
    return findings, len(env_files)


HOME_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+")
SCAN_SUFFIXES = (".md", ".py", ".json", ".js", ".sh", ".txt", ".yml", ".yaml")


def account_names():
    names = {getpass.getuser()}
    if platform.system() == "Darwin":
        try:
            full = subprocess.run(["id", "-F"], capture_output=True, text=True).stdout.strip()
            names.update(p for p in full.split() if len(p) >= 3)
        except OSError:
            pass
    return names


def check_machine_leaks(root):
    """Findings for a skill file that names the machine account or a home path. A test file is
    skipped: its fixtures need a sample path."""
    patterns = [(t, re.compile(r"(?<![A-Za-z])" + re.escape(t) + r"(?![A-Za-z])", re.I))
                for t in sorted(account_names(), key=len, reverse=True)]
    findings = []
    for skill in _fleet.find_skills(root):
        for path in sorted(skill.rglob("*")):
            parts = path.relative_to(skill).parts
            if (not path.is_file() or path.suffix not in SCAN_SUFFIXES or "__pycache__" in parts
                    or "tests" in parts or path.name.startswith("test_")):
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                found = [t for t, p in patterns if p.search(line)]
                if HOME_PATH.search(line):
                    found.append("home path")
                if found:
                    findings.append(f"{path.relative_to(root.parent)}:{lineno} -- {found} in a skill file")
    return findings


# Exactly these 3 names are fictional-safe fleet-wide. Any other name is a flag to verify by
# hand, never a candidate to add here on a guess: a real person's name in this set would hide
# every reuse of that name as an example.
ESTABLISHED_PLACEHOLDERS = {"Jane Doe", "John Smith", "Sally May"}


def check_filename_example_candidates(root):
    """Scans .md AND .py -- the real leak this check exists to catch (a name-shaped example
    string) lives in either, and a .md-only scan would miss it. No self-exclusion: this file's own illustrative examples must themselves use
    only `ESTABLISHED_PLACEHOLDERS`, so this check dogfoods itself instead of going blind to its
    own future regressions -- exactly the blind spot that would let a real name sit in this file's own
    examples undetected."""
    findings = []
    for path in iter_tracked_files(root):
        if path.suffix not in (".md", ".py"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in NAME_NEAR_FILENAME.finditer(line):
                name = match.group(0)
                if name in ESTABLISHED_PLACEHOLDERS:
                    continue
                findings.append(
                    f"{path.relative_to(root.parent)}:{lineno} -- possible real name '{name}' "
                    f"directly against a filename/extension, verify by hand"
                )
    return findings


def main(argv=None):
    global SKILLS_ROOT
    SKILLS_ROOT = _fleet.scan_root(sys.argv[1:] if argv is None else argv, SKILLS_ROOT)
    known_findings, env_count = check_known_identity_leaks(SKILLS_ROOT)
    candidate_findings = check_filename_example_candidates(SKILLS_ROOT)
    machine_findings = check_machine_leaks(SKILLS_ROOT)

    print(f"Name-leak sweep: {env_count} real .env.local file(s) found on this machine, "
          f"scanned against every tracked .md/.py/.json file under {SKILLS_ROOT.name}/\n")

    if known_findings:
        print(f"-- {len(known_findings)} known-identity leak(s) (high confidence, act on these) --")
        for f in known_findings:
            print(f"  - {f}")
    else:
        print("Known-identity leak check: clean. No real .env.local name/email found in any "
              "tracked file.")

    print()
    if candidate_findings:
        print(f"-- {len(candidate_findings)} filename-example candidate(s) (advisory -- read "
              f"and judge, real false-positive risk) --")
        for f in candidate_findings:
            print(f"  - {f}")
    else:
        print("Filename-example candidate check: no two-capitalized-word sequence found next "
              "to a résumé/filename cue.")

    print()
    if machine_findings:
        print(f"-- {len(machine_findings)} machine leak(s) (high confidence, act on these) --")
        for f in machine_findings:
            print(f"  - {f}")
    else:
        print("Machine-leak check: clean. No account name or home path in a skill file.")

    if known_findings or machine_findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
