# GATE-SCOPE-1: this gate matched only the two literal filenames SKILL.md and
# CLAUDE.md. A fleet repo's references/*.md file carried 17 real violations the
# gate never saw, because a reference file is the same agent-parsed prose by a
# different name. Matched by path shape (`*/SKILL.md`, `*/CLAUDE.md`,
# `*/references/*.md`) now, not by bare filename. See docs/DECISIONS.md.
# SKILL.md, CLAUDE.md, and references/*.md are agent-parsed instructions, not
# human-read prose -- a dense sentence in one caused a real skill-matching bug
# (SKILLS-PLACEMENT.md's ACT-3). Strict mode: full default ste-lint, no rule disabled, except a repo's own
# named per-file exemptions (see .githooks/ste-exemptions below) for a documented,
# checked false positive -- e.g. a real sheet-column name colliding with a real
# CLI-subcommand name under synonym-rotation's whole-file scope, where renaming
# either would misdescribe the real thing it names.
#
# The linter is a personal vendor install (npx skills add danyuchn/asd-ste100-skill),
# not vendored in-repo -- skip cleanly on a machine or clone that lacks it rather
# than blocking every commit.
STE_LINT=""
for candidate in "$HOME/.claude/skills/asd-ste100/scripts/ste-lint.py" "$HOME/.agents/skills/asd-ste100/scripts/ste-lint.py"; do
  [ -f "$candidate" ] && STE_LINT="$candidate" && break
done

# ste-lint.py counts sentence length one physical line at a time, so a hard-wrapped
# paragraph never trips the long-sentence cap (STE-JOIN-1 in OliverCode's
# docs/DECISIONS.md). ste-lint-joined.py joins soft-wrapped lines first and keeps the
# line numbers. sync-hooks installs it beside this hook. OliverCode's own hook reads
# the template copy.
STE_JOIN=""
for candidate in "$HOOK_DIR/ste-lint-joined.py" "$REPO_ROOT/core/templates/project/ste-lint-joined.py"; do
  [ -f "$candidate" ] && STE_JOIN="$candidate" && break
done

# path:rule pairs exempted from strict mode, one per accepted case. Lives outside
# this file (sync-hooks overwrites this file wholesale) in a plain per-repo file so
# an exemption survives every future hook sync untouched.
STE_EXEMPTIONS=""
STE_EXEMPTIONS_FILE="$REPO_ROOT/.githooks/ste-exemptions"
[ -f "$STE_EXEMPTIONS_FILE" ] && STE_EXEMPTIONS="$(cat "$STE_EXEMPTIONS_FILE")"

# GATE-BASELINE-1: path:count pairs, the hard-violation count accepted per file,
# frozen at adoption so GATE-SCOPE-1's references/*.md scope does not block every
# pre-existing reference file on debt this gate never checked before. A file not
# listed here keeps baseline 0. Same per-repo, outside-the-template location as
# STE_EXEMPTIONS, for the same reason. See docs/DECISIONS.md.
STE_BASELINE=""
STE_BASELINE_FILE="$REPO_ROOT/.githooks/ste-baseline"
[ -f "$STE_BASELINE_FILE" ] && STE_BASELINE="$(cat "$STE_BASELINE_FILE")"

if [ -z "$STE_LINT" ] || ! command -v python3 >/dev/null 2>&1; then
  echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Writing clarity (asd-ste100)... skipped (ste-lint.py or python3 not found on this machine)."
else
  echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Writing clarity (asd-ste100)..."
  CLARITY_FAILED=0
  HAVE_JQ=0
  command -v jq >/dev/null 2>&1 && HAVE_JQ=1
  if [ -n "$STAGED_FILES" ]; then
    while IFS= read -r file; do
      case "$file" in
        */SKILL.md|SKILL.md|*/CLAUDE.md|CLAUDE.md|*/references/*.md) [ -f "$file" ] || continue ;;
        *) continue ;;
      esac
      if [ -z "$STE_JOIN" ]; then
        echo "  BLOCKED: $file needs ste-lint-joined.py, which is missing from $HOOK_DIR."
        echo "  Without it, hard-wrapped prose passes the long-sentence cap unchecked."
        echo "  Run: olivercode sync-hooks"
        exit 1
      fi
      disable_rules=""
      while IFS=: read -r ex_path ex_rule; do
        [ -z "$ex_path" ] && continue
        [ "$ex_path" = "$file" ] && disable_rules="${disable_rules:+$disable_rules,}$ex_rule"
      done <<< "$STE_EXEMPTIONS"
      baseline=0
      while IFS=: read -r bl_path bl_count; do
        [ -z "$bl_path" ] && continue
        [ "$bl_path" = "$file" ] && baseline="$bl_count"
      done <<< "$STE_BASELINE"
      lint_args=(--baseline "$baseline" --json)
      [ -n "$disable_rules" ] && lint_args=(--disable "$disable_rules" --baseline "$baseline" --json)
      # Decide pass/fail from --json first, so a clean file (the common case) costs
      # one summary line instead of ste-lint's full per-finding dump -- that dump
      # was repeating in full on every commit for every staged file regardless of
      # whether it was actually blocking, real token waste on any commit touching
      # more than a couple of SKILL.md/CLAUDE.md files.
      JSON_OUT="$(python3 "$STE_JOIN" "$STE_LINT" "${lint_args[@]}" "$file" 2>&1)" && EXIT_CODE=0 || EXIT_CODE=$?
      if [ "$EXIT_CODE" -ne 0 ]; then
        CLARITY_FAILED=1
        # Re-run in plain mode so the failing file gets full fix-it detail.
        if [ -n "$disable_rules" ]; then
          python3 "$STE_JOIN" "$STE_LINT" --disable "$disable_rules" --baseline "$baseline" "$file" || true
        else
          python3 "$STE_JOIN" "$STE_LINT" --baseline "$baseline" "$file" || true
        fi
      elif [ "$HAVE_JQ" -eq 1 ]; then
        soft=$(printf '%s' "$JSON_OUT" | jq -r '.count')
        hard=$(printf '%s' "$JSON_OUT" | jq -r '.hard_count')
        if [ "$baseline" -gt 0 ]; then
          echo "  $file: $hard hard / baseline $baseline, $soft soft -- not blocking."
          if [ "$hard" -lt "$baseline" ]; then
            echo "    baseline could drop to $hard -- .githooks/ste-baseline is informational, never auto-edited."
          fi
        else
          echo "  $file: $soft soft violation(s) (0 hard) -- not blocking."
        fi
      fi
    done <<< "$STAGED_FILES"
  fi

  # GATE-CITATION-1: a staged skill file can cite `#N` as a real GitHub issue
  # that was never filed -- two commits did exactly this before anything
  # caught it. Checked only when `gh` is installed and already authenticated;
  # any network, auth, or rate-limit problem skips the check silently rather
  # than blocking a commit on infrastructure the content gate does not own.
  # See docs/DECISIONS.md.
  CITATION_FAILED=0
  CITED_NUMS=""
  if [ -n "$STAGED_FILES" ]; then
    while IFS= read -r file; do
      case "$file" in
        */SKILL.md|SKILL.md|*/CLAUDE.md|CLAUDE.md|*/references/*.md) [ -f "$file" ] || continue ;;
        *) continue ;;
      esac
      hits=$(grep -ohE '(^|[^A-Za-z0-9&])#[0-9]{1,5}([^0-9]|$)' "$file" 2>/dev/null | grep -oE '[0-9]{1,5}' || true)
      [ -n "$hits" ] && CITED_NUMS="$CITED_NUMS
$hits"
    done <<< "$STAGED_FILES"
  fi
  CITED_NUMS=$(printf '%s\n' "$CITED_NUMS" | grep -E '^[0-9]+$' | sort -un || true)
  if [ -n "$CITED_NUMS" ] && command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    ALL_ISSUES=$(cd "$REPO_ROOT" && gh issue list --state all --limit 5000 --json number --jq '.[].number' 2>/dev/null) || ALL_ISSUES=""
    if [ -n "$ALL_ISSUES" ]; then
      while IFS= read -r n; do
        [ -z "$n" ] && continue
        if ! printf '%s\n' "$ALL_ISSUES" | grep -qx "$n"; then
          echo "  BLOCKED: #$n is cited in a staged skill file but resolves to no real issue."
          CITATION_FAILED=1
        fi
      done <<< "$CITED_NUMS"
    fi
  fi

  if [ "$CLARITY_FAILED" -eq 1 ]; then
    echo "  WARNING: one or more SKILL.md/CLAUDE.md/references/*.md files have asd-ste100 findings (see output above). Not blocking."
  fi
  if [ "$CITATION_FAILED" -eq 1 ]; then
    echo "  Fix each citation to a real issue number, or remove it, then re-commit."
    exit 1
  fi
  echo "  Gate {{N}} passed."
fi
