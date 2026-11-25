# GATE-LOCAL-1. A repo adds its own blocking checks in two ways, and sync-hooks never overwrites either.
# docs/SUITE-CHECKS.json lists each check as {"name", "files": [globs], "command"}; a check runs on the
# staged files that match its globs, with those files as its arguments, and a non-zero exit blocks the commit
# (SUITE-CHECKS-1). The unit tests read the same file, so the commit gate and the tests run one list.
if [ -f "$REPO_ROOT/docs/SUITE-CHECKS.json" ] && command -v python3 >/dev/null 2>&1; then
  echo "[pre-commit] Suite checks..."
  STAGED_FILES="$STAGED_FILES" python3 -c '
import fnmatch, json, os, shlex, subprocess, sys
root = sys.argv[1]
try:
    checks = json.load(open(os.path.join(root, "docs", "SUITE-CHECKS.json")))["checks"]
except (OSError, ValueError, KeyError) as exc:
    print("  BLOCKED: docs/SUITE-CHECKS.json cannot be read (%s)." % type(exc).__name__)
    sys.exit(1)
staged = [f for f in os.environ.get("STAGED_FILES", "").splitlines() if f]
failed = 0
for check in checks:
    hit = [f for f in staged if any(fnmatch.fnmatch(f, g) for g in check.get("files", []))]
    if not hit:
        continue
    done = subprocess.run(check["command"] + " " + " ".join(shlex.quote(f) for f in hit), shell=True, cwd=root, capture_output=True, text=True)
    if done.returncode:
        failed += 1
        print("  BLOCKED: suite check %s failed on %d staged file(s)." % (check.get("name", check["command"]), len(hit)))
        print("\n".join("  " + l for l in (done.stdout + done.stderr).strip().splitlines()[-20:]))
sys.exit(1 if failed else 0)
' "$REPO_ROOT" || exit 1
fi
# A repo's own executable .githooks/pre-commit.local, read from the repo root and not from
# HOOK_DIR: core.hooksPath can be one machine-wide folder outside every repo (#1154), so
# HOOK_DIR no longer names this repo's own .githooks. The file is not part of this template,
# so sync-hooks never overwrites it. It gets the staged file list on stdin and blocks the
# commit by exiting non-zero.
if [ -x "$REPO_ROOT/.githooks/pre-commit.local" ]; then
  echo "[pre-commit] Repo-local gates..."
  printf '%s\n' "$STAGED_FILES" | "$REPO_ROOT/.githooks/pre-commit.local" || exit 1
fi
