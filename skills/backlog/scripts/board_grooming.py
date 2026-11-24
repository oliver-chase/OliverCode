"""The board sweep's grooming checks: work the board has not caught up with. Every finding is a judgment
for the owner. check_board_hygiene.py reads the board and the issues and calls these.
"""
import re


def field(item, name):
    """An item's value for a field, matched without case: gh keys a field by the board's own spelling."""
    return next((v for k, v in item.items() if k.lower() == name.lower()), None)


WAITING_STATUSES = {"Backlog", "Ready"}
STOPWORDS = {"the", "and", "for", "with", "that", "this", "from", "into", "every", "each", "when",
             "make", "makes", "only", "its", "their", "them", "they", "one", "all", "add", "fix", "put", "move",
             "bring"}


def title_words(title):
    words = re.findall(r"[a-z0-9][a-z0-9-]*", title.lower())
    return {w[:-1] if w.endswith("s") and len(w) > 4 else w for w in words if len(w) > 2 and w not in STOPWORDS}


def overlapping_titles(items, open_statuses, min_shared=3, ratio=0.6, jaccard=0.7):
    """Pairs of open stories whose titles share most of the shorter title's content words and at least
    70% of all their words, so one template with two different subjects is no pair. An epic
    shares words with its own stories by design, so epics are left out."""
    open_items = [(i["content"]["number"], title_words(i["content"].get("title", "")))
                  for i in items if i.get("status") in open_statuses and i.get("content", {}).get("number")
                  and field(i, "work type") != "Epic"]
    problems = []
    for a in range(len(open_items)):
        for b in range(a + 1, len(open_items)):
            (na, wa), (nb, wb) = open_items[a], open_items[b]
            shared = wa & wb
            if len(shared) >= min_shared and len(shared) / min(len(wa), len(wb)) >= ratio and len(shared) / len(wa | wb) >= jaccard:
                problems.append(f"#{na} and #{nb} share {', '.join(sorted(shared))}: "
                                "possible duplicate or superseded pair, close one or link them")
    return problems


def built_not_moved(items, comments_by_number):
    """Open items still in Backlog or Ready whose issue carries a log_action builder entry."""
    problems = []
    for i in items:
        number = i.get("content", {}).get("number")
        if i.get("status") not in WAITING_STATUSES or number not in comments_by_number:
            continue
        if any("- Role: builder" in (c.get("body") or "") for c in comments_by_number[number]):
            problems.append(f"#{number} \"{i['content'].get('title', '')[:50]}\" ({i.get('status')}): "
                            "has a builder entry, move it to QA")
    return problems


def epic_rollup(items, summaries, finished):
    """Open epics whose Status lags their sub-issues. `summaries` maps number to (total, completed)."""
    problems = []
    for i in items:
        number = i.get("content", {}).get("number")
        if field(i, "work type") != "Epic" or i.get("status") == finished or number not in summaries:
            continue
        total, completed = summaries[number]
        title = i["content"].get("title", "")[:50]
        if total and completed == total:
            problems.append(f"#{number} \"{title}\": all {total} sub-issues closed, move the epic to {finished}")
        elif completed and i.get("status") in WAITING_STATUSES:
            problems.append(f"#{number} \"{title}\" ({i.get('status')}): {completed} of {total} "
                            "sub-issues closed, move the epic to In Progress")
    return problems


EPIC_LINE = re.compile(r"^Epic:\s*#(\d+)[^\n]*\n?", re.M)
GENERIC = {"status", "board", "groom", "grooming", "story", "stories", "epic", "owner", "line", "lines", "check", "checks",
           "command", "file", "files", "card", "cards", "queue", "run", "runs", "set", "sets", "new", "use", "uses"}


def epic_of(body):
    """The number on the story's Epic line, or None."""
    m = EPIC_LINE.search(body or "")
    return int(m.group(1)) if m else None


def is_epic(story):
    return bool(re.search(r"Work type:\s*Epic\b", story.get("body") or "", re.I))


def topic_words(title):
    return title_words(title) - GENERIC


def match_epic(story, epics, files_of, skip=()):
    """(epic number, the match used) for the open epic whose Files area overlaps the story's, or whose title shares at least five words and
    60% of the story's own title words, else None. Generic words never count. `epics` maps number to story; `skip` holds epics the owner undid."""
    own, words = files_of(story.get("body") or ""), topic_words(story.get("title") or "")
    for n, epic in sorted(epics.items()):
        if n in skip:
            continue
        shared = own and [p for p in files_of(epic.get("body") or "") if any(p == q or p.rstrip("/") + "/" == q[:len(p.rstrip("/")) + 1] or q.rstrip("/") + "/" == p[:len(q.rstrip("/")) + 1] for q in own)]
        if shared:
            return n, "shared files " + ", ".join(sorted(shared))
        common = words & topic_words(epic.get("title") or "")
        if len(common) >= 5 and words and len(common) / len(words) >= 0.6:
            return n, "shared title words " + ", ".join(sorted(common))
    return None


def themes(stories, minimum=3):
    """[(shared words, [numbers])] for groups of at least `minimum` stories whose titles share the same two topic words.
    shortcut: a pair of words stands for a theme, upgrade when pairs split one theme into two proposals."""
    words = {n: topic_words(s.get("title") or "") for n, s in stories.items()}
    left, found = set(words), []
    while True:
        counts = {}
        for n in left:
            ws = sorted(words[n])
            for a in range(len(ws)):
                for b in range(a + 1, len(ws)):
                    counts.setdefault((ws[a], ws[b]), set()).add(n)
        pair = max(counts, key=lambda p: (len(counts[p]), p), default=None)
        if pair is None or len(counts[pair]) < minimum:
            return found
        found.append((pair, sorted(counts[pair])))
        left -= counts[pair]


def epic_moves(items, summaries, finished):
    """(number, status, comment) for each open epic whose Status its sub-issues say is wrong: all closed moves it to
    `finished`, some closed moves a waiting epic to In Progress, and a Ready epic with none closed moves to Backlog,
    since an epic is never built directly (#1105). `summaries` maps number to (total, completed)."""
    moves = []
    for i in items:
        number = i.get("content", {}).get("number")
        if field(i, "work type") != "Epic" or i.get("status") == finished or number not in summaries:
            continue
        total, completed = summaries[number]
        status = i.get("status")
        if total and completed == total:
            moves.append((number, finished, f"All {total} sub-issues are closed, so this epic is {finished}."))
        elif completed and status in WAITING_STATUSES:
            moves.append((number, "In Progress", f"{completed} of {total} sub-issues are closed, so this epic is "
                          "In Progress. An epic is not built directly; its stories are."))
        elif status == "Ready":
            moves.append((number, "Backlog", "An epic is not built directly; its stories are. "
                          "This epic moves to Backlog and stays there until its stories are in progress."))
    return moves
