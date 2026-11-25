"""One line, at most LIMIT characters, naming the doc section that explains it: the shape of every hook refusal and advice (#893).

A hook's message is read again on every later call, so a refusal costs its length each time. `bounded` is the one place that
holds the limit. A message over it is cut and ends with a doc pointer, and a message with no pointer gets the default one.
"""

import re

LIMIT = 200
DEFAULT_DOC = "See docs/RULES.md, Execution."
POINTER = re.compile(r"(?:See )?docs/[\w./-]+(?:, [A-Z][\w ]*)?\.?\s*$")


def bounded(text: str, limit: int = LIMIT) -> str:
    """`text` as one line of at most `limit` characters that ends with a doc pointer."""
    line = " ".join(str(text).split())
    found = POINTER.search(line)
    tail = found.group(0).strip() if found else DEFAULT_DOC
    body = line[:found.start()].rstrip() if found else line
    if not tail.startswith("See "):
        tail = f"See {tail}"
    room = limit - len(tail) - 1
    if len(body) > room:
        body = body[:max(room - 1, 0)].rstrip() + "…"
    return f"{body} {tail}".strip()
