# OWNER-ID-1. A shipped file cannot name the people or accounts behind the repo. The gate derives
# the identifiers itself, so no hand-kept list exists: the names and email local parts of
# `git log` authors, the owner segment of the origin remote, and the string values of account and
# shop keys in the config files that docs/IDENTIFIER-GATE.json lists under "configGlobs". Each is
# lowercased, kept at 4 characters or more, and matched on whole words, so a short name never matches
# inside a longer word. Generic authors (noreply addresses, bots, Claude, GitHub) are ignored.
#
# Every staged file is scanned, markdown and tests included, except local data: the built-in
# paths below and the "localData" globs in docs/IDENTIFIER-GATE.json, each declared with a
# reason. Fewer than one derivable identifier skips the gate.
echo "[pre-commit] Gate {{N}}/{{TOTAL}}: Owner identifiers..."
ID_CONFIG="$(git show ":docs/IDENTIFIER-GATE.json" 2>/dev/null || true)"
id_array() {
  printf '%s\n' "$ID_CONFIG" | tr '\n' ' ' \
    | sed -n 's/.*"'"$1"'"[[:space:]]*:[[:space:]]*\[\([^]]*\)\].*/\1/p' \
    | grep -o '"[^"]*"' | sed 's/^"//; s/"$//' || true
}
ID_LIST="$(mktemp "${TMPDIR:-/tmp}/oc-identifiers.XXXXXX")"
trap 'rm -f "$ID_LIST"' EXIT
{
  git log --format='%an%x09%ae' 2>/dev/null | sort -u | while IFS="$(printf '\t')" read -r id_name id_mail; do
    id_name_lc="$(printf '%s' "$id_name" | tr 'A-Z' 'a-z')"
    id_mail_lc="$(printf '%s' "$id_mail" | tr 'A-Z' 'a-z')"
    case "$id_name_lc$id_mail_lc" in *"[bot]"*|*"-bot@"*) continue ;; esac
    # An Anthropic noreply commit is a session and not a person. Its author name would otherwise split
    # into ordinary words that block later commits.
    case "$id_mail_lc" in *@anthropic.com) continue ;; esac
    printf '%s\n' "$id_name_lc" | tr -c 'a-z0-9\n' ' ' | tr ' ' '\n'
    case "$id_mail_lc" in
      *@users.noreply.github.com) printf '%s\n' "${id_mail_lc%@*}" | sed 's/^[0-9]*+//' ;;
      *@noreply.github.com) ;;
      *@*) printf '%s\n' "${id_mail_lc%@*}" | sed 's/+.*//' ;;
    esac
  done
  id_remote="$(git remote get-url origin 2>/dev/null || true)"
  case "$id_remote" in
    *://*) id_remote="${id_remote#*://}"; id_remote="${id_remote#*/}" ;;
    *:*) id_remote="${id_remote#*:}" ;;
    *) id_remote="" ;;
  esac
  printf '%s\n' "${id_remote%%/*}" | tr 'A-Z' 'a-z'
  id_array configGlobs | while IFS= read -r id_glob; do
    git ls-files | while IFS= read -r id_cfg; do
      case "$id_cfg" in $id_glob) git show ":$id_cfg" 2>/dev/null ;; esac
    done
  done | tr 'A-Z' 'a-z' \
    | sed -nE 's/.*"[^"]*(account|shop|store|handle|username|owner|brand|seller)[^"]*"[[:space:]]*:[[:space:]]*"([^"]+)".*/\2/p'
} | awk 'length($0) >= 4' \
  | grep -vxE 'claude|github|anthropic|noreply|no-reply|copilot|dependabot|renovate|root|user|users|test|tests|admin|unknown|none|null|example|local|localhost|bot|runner' \
  | sort -u > "$ID_LIST" || true
if [ ! -s "$ID_LIST" ]; then
  echo "  Gate {{N}} skipped (no owner identifier can be derived from git or docs/IDENTIFIER-GATE.json)."
else
  ID_LOCAL="$(id_array localData)"
  ID_HITS=0
  while IFS= read -r id_file; do
    [ -n "$id_file" ] || continue
    case "$id_file" in
      .secrets/*|scratch/*|.githooks/*|docs/backlog-config.json|docs/IDENTIFIER-GATE.json) continue ;;
    esac
    id_skip=0
    while IFS= read -r id_glob; do
      [ -n "$id_glob" ] || continue
      case "$id_file" in $id_glob) id_skip=1; break ;; esac
    done <<< "$ID_LOCAL"
    [ "$id_skip" = 1 ] && continue
    id_found="$(git show ":$id_file" 2>/dev/null | grep -InoiwF -f "$ID_LIST" || true)"
    if [ -n "$id_found" ]; then
      while IFS= read -r id_line; do
        echo "  $id_file:${id_line%%:*} names the owner: ${id_line#*:}"
      done <<< "$id_found"
      ID_HITS=$((ID_HITS + 1))
    fi
  done <<< "$STAGED_FILES"
  if [ "$ID_HITS" -gt 0 ]; then
    echo "  BLOCKED: $ID_HITS file(s) contain an identifier derived from git authors, the remote owner or config."
    echo "  Replace it with a placeholder such as my-shop, or list the file under \"localData\" in docs/IDENTIFIER-GATE.json with a reason."
    exit 1
  fi
  echo "  Gate {{N}} passed ($(wc -l < "$ID_LIST" | tr -d ' ') identifiers derived)."
fi
