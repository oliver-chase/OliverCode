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
