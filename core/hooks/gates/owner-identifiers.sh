# OWNER-ID-1. A shipped file cannot name the people or accounts behind the repo. The gate derives
# the identifiers itself, so no hand-kept list exists: the full names, matched as one phrase, and the
# email local parts of `git log` authors, the owner segment of the origin remote, and the string values of the account, shop, store, handle,
# username, owner, brand and seller keys in the config files that docs/IDENTIFIER-GATE.json lists under "configGlobs". Each is
# lowercased, kept at 5 characters or more, and matched on whole words, so a short name never matches
# inside a longer word. Generic authors (noreply addresses, bots, Claude, GitHub) are ignored.
#
# Every staged file is scanned, markdown and tests included, except local data: the built-in
# paths below, which are fixed in this gate, and the "localData" globs in docs/IDENTIFIER-GATE.json,
# whose reasons are recorded there for readers. Fewer than one derivable identifier skips the gate.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Owner identifiers..."
ID_LIST="$(mktemp "${TMPDIR:-/tmp}/oc-identifiers.XXXXXX")"
trap 'rc=$?; rm -f "$ID_LIST"; log_failure $rc' EXIT
# The origin's owner/repo path, from an https or ssh remote.
ID_ORIGIN="$(git remote get-url origin 2>/dev/null || true)"
case "$ID_ORIGIN" in
  *://*) ID_ORIGIN="${ID_ORIGIN#*://}"; ID_ORIGIN="${ID_ORIGIN#*/}" ;;
  *:*) ID_ORIGIN="${ID_ORIGIN#*:}" ;;
  *) ID_ORIGIN="" ;;
esac
# An org-owned repo shares its org name on purpose, so the org is allowed and only the committer's own identity is checked.
ID_ORG=0
if [ -n "$ID_ORIGIN" ] && command -v gh >/dev/null 2>&1; then
  [ "$(gh api "users/${ID_ORIGIN%%/*}" --jq .type 2>/dev/null || true)" = "Organization" ] && ID_ORG=1
fi
id_authors() {
  if [ "$ID_ORG" = 1 ]; then
    printf '%s\t%s\n' "$(git config user.name 2>/dev/null || true)" "$(git config user.email 2>/dev/null || true)"
  else
    git log --format='%an%x09%ae' 2>/dev/null
  fi
}
{
  id_authors | sort -u | while IFS="$(printf '\t')" read -r id_name id_mail; do
    id_name_lc="$(printf '%s' "$id_name" | tr 'A-Z' 'a-z')"
    id_mail_lc="$(printf '%s' "$id_mail" | tr 'A-Z' 'a-z')"
    case "$id_name_lc$id_mail_lc" in *"[bot]"*|*"-bot@"*) continue ;; esac
    # An Anthropic noreply commit is a session and not a person. Its author name would otherwise split
    # into ordinary words that block later commits.
    case "$id_mail_lc" in *@anthropic.com) continue ;; esac
    # The full name is one phrase, so an author called "Scratch Person" never blocks the word "person".
    printf '%s\n' "$id_name_lc" | LC_ALL=C tr '[:punct:]' ' ' | tr -s ' ' | sed 's/^ //; s/ $//'
    case "$id_mail_lc" in
      *@users.noreply.github.com) printf '%s\n' "${id_mail_lc%@*}" | sed 's/^[0-9]*+//' ;;
      *@noreply.github.com) ;;
      *@*) printf '%s\n' "${id_mail_lc%@*}" | sed 's/+.*//' ;;
    esac
  done
  [ "$ID_ORG" = 1 ] || printf '%s\n' "${ID_ORIGIN%%/*}" | tr 'A-Z' 'a-z'
  gate_list docs/IDENTIFIER-GATE.json configGlobs | while IFS= read -r id_glob; do
    git ls-files | while IFS= read -r id_cfg; do
      case "$id_cfg" in $id_glob) git show ":$id_cfg" 2>/dev/null ;; esac
    done
  done | tr 'A-Z' 'a-z' | tr ',{}' '\n\n\n' \
    | sed -nE 's/.*"[^"]*(account|shop|store|handle|username|owner|brand|seller)[^"]*"[[:space:]]*:[[:space:]]*"([^"]+)".*/\2/p'
} | awk 'length($0) >= 5' | grep '[a-z]' | grep -vxE '#[0-9a-f]+|[0-9]+' \
  | grep -vxE 'claude|github|anthropic|noreply|no-reply|copilot|dependabot|renovate|root|user|users|test|tests|admin|unknown|none|null|example|local|localhost|bot|runner|support|hello|contact|office|sales|info|team|help|billing|mail|email|webmaster|postmaster|abuse|security|press|marketing|careers|jobs' \
  | sort -u > "$ID_LIST" || true
if [ ! -s "$ID_LIST" ]; then
  echo "  Gate {{N}} skipped (no owner identifier can be derived from git or docs/IDENTIFIER-GATE.json)."
else
  # A project names itself: its origin path, its repo name (also spaced) and its package name are not owner data, so a
  # line is matched after those strings are removed. A bare author name in prose still blocks.
  ID_SELF="$(mktemp "${TMPDIR:-/tmp}/oc-identifier-self.XXXXXX")"
  ID_RE="$(mktemp "${TMPDIR:-/tmp}/oc-identifier-re.XXXXXX")"
  trap 'rc=$?; rm -f "$ID_LIST" "$ID_SELF" "$ID_RE"; log_failure $rc' EXIT
  # A name is written with any punctuation between its words ("Kesh-Ulster", "O'Neill"), so the words join on non-alphanumerics.
  sed -e 's/[][().*+?{}|^$\\]/\\&/g' -e 's/ /[^a-zA-Z0-9]+/g' "$ID_LIST" > "$ID_RE"
  {
    id_self_path="${ID_ORIGIN%.git}"
    printf '%s\n' "$id_self_path"
    # A repo named like its owner would strip the owner's own name from every line, so only its path is removed.
    if [ "${id_self_path##*/}" != "${id_self_path%%/*}" ]; then
      printf '%s\n' "${id_self_path##*/}"
      # Prose writes the repo name with spaces ("my repo name" for my-repo-name).
      printf '%s\n' "${id_self_path##*/}" | tr '_-' '  '
    fi
    git show ":package.json" 2>/dev/null | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("name",""))
except Exception: pass' || true
  } | awk 'length($0) >= 5' | sort -u > "$ID_SELF"
  ID_MATCHER='import re, sys
words = [w.strip() for w in open(sys.argv[1]) if w.strip()]
selfs = sorted((w.strip() for w in open(sys.argv[2]) if w.strip()), key=len, reverse=True)
join = lambda w: r"[^A-Za-z0-9]+".join(re.escape(p) for p in w.split())
pattern = re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(join(w) for w in words) + r")(?![A-Za-z0-9_])", re.I) if words else None
for number, line in enumerate(sys.stdin, 1):
    for own in selfs:
        line = re.sub(re.escape(own), " ", line, flags=re.I)
    for match in (pattern.finditer(line) if pattern else []):
        print(f"{number}:{match.group(0)}")'
  ID_LOCAL="$(gate_list docs/IDENTIFIER-GATE.json localData)"
  ID_HITS=0
  command -v python3 >/dev/null 2>&1 || { echo "  BLOCKED: python3 is needed to check owner identifiers."; exit 1; }
  while IFS= read -r id_file; do
    [ -n "$id_file" ] || continue
    case "$id_file" in
      .secrets/*|scratch/*|.githooks/*|docs/backlog-config.json|docs/IDENTIFIER-GATE.json) continue ;;
    esac
    matches_glob "$id_file" "$ID_LOCAL" && continue
    # grep finds the candidates fast and reads the whole file, so the reader never gets SIGPIPE; python re-reads only a file
    # that has a candidate, with the project's own names removed.
    id_found="$(staged_content "$id_file" 2>/dev/null | grep -iwEf "$ID_RE" >/dev/null && staged_content "$id_file" 2>/dev/null | python3 -c "$ID_MATCHER" "$ID_LIST" "$ID_SELF" || true)"
    if [ -n "$id_found" ]; then
      while IFS= read -r id_line; do
        echo "  $id_file:${id_line%%:*} names the owner"
      done <<< "$id_found"
      ID_HITS=$((ID_HITS + 1))
    fi
  done <<< "$TEXT_FILES"
  if [ "$ID_HITS" -gt 0 ]; then
    echo "  BLOCKED: $ID_HITS file(s) contain an identifier derived from git authors, the remote owner or config."
    echo "  Replace it with a placeholder such as my-shop, or list the file under \"localData\" in docs/IDENTIFIER-GATE.json with a reason."
    exit 1
  fi
  echo "  Gate {{N}} passed ($(wc -l < "$ID_LIST" | tr -d ' ') identifiers derived)."
fi
