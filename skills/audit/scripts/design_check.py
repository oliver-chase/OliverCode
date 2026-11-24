#!/usr/bin/env python3
"""Finds the banned design tells in a page: lens 7b's mechanical check, with no model and no dependency.

Usage:
    design_check.py PATH...   # a file, or a folder walked for HTML, CSS and component files
Prints one `file:line  rule  tier  what` row per tell and exits 1 when it printed any, 0 and nothing otherwise.
The tiers are docs/DESIGN.md's: a floor tell is never allowed, and a reflex tell ships only with a waiver in the page's design note.
A hit is a candidate for a reader to judge, since a pattern cannot see intent.
Tests: python3 -m unittest test_design_check   (from this scripts/ folder)
"""

import re
import sys
from pathlib import Path

UI = {".html", ".htm", ".css", ".scss", ".jsx", ".tsx", ".vue", ".svelte", ".astro"}
SKIP_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", ".next"}
FLAGS = re.I | re.S
# shortcut: a reflex waiver in the page's design note is not read here, so every reflex hit prints, and the reader checks the note, when a note parser exists

# (rule, tier, pattern, what). A pattern runs over the whole file, so a tag split across lines still matches.
CLASS = r'class(?:Name)?\s*=\s*["\'{`][^"\'`]*'
FORM_OK = re.compile(r"action\s*=\s*(?:\{|[\"'][^\"'#\s])|onsubmit|@submit|v-on:submit|hx-(?:post|get)|data-netlify|:action|use:enhance", re.I)
RULES = (
    ("placeholder-copy", "floor", r"lorem ipsum|your (?:text|title|headline|company(?: name)?|tagline) here|dolor sit amet", "placeholder copy"),
    ("invented-metric", "floor", r"\b\d[\d,.]*[kKmM]?\+?\s+(?:happy\s+)?(?:users|customers|clients|teams|companies|downloads|developers)\b"
                                r"|\b\d(?:\.\d)?\s*(?:/\s*5|★)|\b9\d(?:\.\d+)?%\s+(?:uptime|satisfaction)", "a metric with no source"),
    ("empty-picture-box", "floor", rf'{CLASS}\b(?:img|image|photo|screenshot|product)[-_]?placeholder|placeholder[-_]?(?:img|image|photo)|via\.placeholder\.com|placehold\.(?:co|it)|placekitten|picsum\.photos',
     "an empty picture box standing in for a photo"),
    ("invented-testimonial", "floor", r"\b(?:John|Jane) (?:Doe|Smith)\b|\bAcme(?: Inc| Corp)?\b|\bSarah J(?:ohnson|\.)", "an invented person or customer"),
    ("pulsing-live-dot", "floor", rf'{CLASS}\b(?:live|pulse|pulsing|status)[-_]dot|animate-ping|{CLASS}\blive-indicator', "a pulsing live dot"),
    ("eyebrow", "reflex", rf'<(?:p|span|div)\b[^>]*{CLASS}\b(?:eyebrow|kicker|overline|pre-?title|section-label)\b'
                          r"|<(p|span|div)\b[^>]*\buppercase\b[^>]*\btracking-[^>]*>[^<]*</\1>\s*<h[1-3]\b", "an eyebrow label above a heading"),
    ("gradient-text", "reflex", r"background-clip\s*:\s*text|bg-clip-text|text-fill-color\s*:\s*transparent", "a gradient on text"),
    ("negative-letter-spacing", "reflex", r"letter-spacing\s*:\s*-|tracking-(?:tight|tighter)\b|tracking-\[-", "negative letter-spacing"),
    ("instrument-serif", "reflex", r"Instrument[ +]Serif", "Instrument Serif"),
    ("pill-tag", "reflex", rf'{CLASS}\b(?:pill|badge|chip|tag)\b', "a tag or pill"),
    ("italic-emphasis", "reflex", r"font-style\s*:\s*italic|<em\b|\bitalic\b(?=[^<>]*>)", "italics for emphasis"),
    ("divider", "reflex", r"<hr\b|\bdivide-[xy]\b|class(?:Name)?\s*=\s*[\"'][^\"']*\bdivider\b", "a divider between blocks"),
    ("numbered-section", "reflex", rf'>\s*0[1-9]\s*<|{CLASS}\b(?:section|step)-(?:num|number|index)\b', "a numbered section"),
    ("code-breadcrumb", "reflex", r">\s*(?:~/|\./|//\s)\w|>\s*\w+\s*/\s*\w+\s*/\s*\w+\s*<", "a code-style breadcrumb"),
    ("squircle", "reflex", r"corner-shape\s*:\s*(?:squircle|superellipse)|squircle", "a squircle"),
    ("dithering", "reflex", r"image-rendering\s*:\s*(?:pixelated|crisp-edges)|dither", "dithering"),
    ("ascii-art", "reflex", r"[─━│┃┌┐└┘├┤┬┴┼]{3,}|/\\_/\\|[+][-=]{6,}[+]", "ASCII art"),
    ("several-opacities", "reflex", r"(?:rgba\([^)]*,\s*0?\.\d+\)[^;{}]*;[^{}]*){5,}", "several opacities of one color"),
)
COMPILED = tuple((rule, tier, re.compile(pat, FLAGS), what) for rule, tier, pat, what in RULES)
FORM = re.compile(r"<form\b[^>]*>", FLAGS)


def check_text(text):
    """Rows (line, rule, tier, what) for the tells in one file's text, in line order."""
    rows = []
    for rule, tier, rx, what in COMPILED:
        rows += [(text.count("\n", 0, m.start()) + 1, rule, tier, what) for m in rx.finditer(text)]
    rows += [(text.count("\n", 0, m.start()) + 1, "dead-form", "floor", "a form that sends nothing")
             for m in FORM.finditer(text) if not FORM_OK.search(m.group())]
    return sorted(set(rows))


def ui_files(paths):
    for p in map(Path, paths):
        if p.is_dir():
            yield from sorted(f for f in p.rglob("*") if f.suffix in UI and f.is_file() and not SKIP_DIRS & set(f.parts))
        elif p.is_file():
            yield p


def check_file(path):
    """Rows (line, rule, tier, what) for one file; a file that is not UI text or cannot be read has none."""
    if Path(path).suffix not in UI:
        return []
    try:
        return check_text(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return []


def main(argv):
    if not argv:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    found = False
    for f in ui_files(argv):
        for line, rule, tier, what in check_file(f):
            print(f"{f}:{line}  {rule}  {tier}  {what}")
            found = True
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
