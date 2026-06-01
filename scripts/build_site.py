#!/usr/bin/env python3
"""
Build the Tarot of Modern Insanity site from card markdown files.

Usage:
    python scripts/build_site.py docs/cards/{date}-{slug}.md

What it does:
  1. Reads the given card markdown (frontmatter + body).
  2. Renders docs/cards/{date}-{slug}.html from templates/card.html (full card).
  3. Rewrites docs/index.html from templates/index.html (today's card).
  4. Rebuilds docs/archive.html from templates/archive.html, scanning every
     docs/cards/*.md and sorting by date desc.

Hard rules:
  - Pure stdlib. No deps.
  - Templates live in templates/. Renderer never edits them.
  - All sections in the markdown become sections on the per-card page.
    The index page only includes sections in INDEX_SECTIONS (sections 1-7
    of the standard 9-section card; "Social Caption" and "Worksheet Prompt"
    are excluded from the front page).
  - Quote section gets the .quote-section CSS class.
  - Excerpt for archive cards = first non-blank line of the Meaning section.
"""
from __future__ import annotations

import datetime as _dt
import html
import pathlib
import re
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
CARDS = DOCS / "cards"
TEMPLATES = REPO_ROOT / "templates"

# Sections to render on the front page (today's card view).
# Anything outside this list is rendered only on the per-card page.
INDEX_SECTIONS = {
    "Meaning",
    "When this appears",
    "The Goblin Claim",
    "Reality Check",
    "Useful Action",
    "Quote",
    "Tiny Ritual",
}

QUOTE_SECTION_NAMES = {"Quote"}


# ---------- markdown parsing ----------

def parse_card(md_text: str) -> dict:
    """Parse a card markdown file. Returns a dict with frontmatter + sections."""
    # frontmatter
    if not md_text.startswith("---"):
        raise ValueError("card markdown missing YAML frontmatter")
    end = md_text.find("\n---", 3)
    if end == -1:
        raise ValueError("unterminated YAML frontmatter")
    fm_raw = md_text[3:end].strip()
    body = md_text[end + 4:].lstrip("\n")

    fm = _parse_frontmatter(fm_raw)

    # strip leading image ref and the # Title line; everything else is sections
    lines = body.splitlines()
    cleaned: list[str] = []
    title_seen = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("![") and "](" in s:
            continue  # the markdown image reference
        if not title_seen and s.startswith("# "):
            title_seen = True
            continue
        cleaned.append(ln)
    body_clean = "\n".join(cleaned).strip()

    sections = _split_sections(body_clean)
    return {"frontmatter": fm, "sections": sections}


def _parse_frontmatter(raw: str) -> dict:
    """Minimal YAML parser. Supports key: value and key:\n  - item lists."""
    out: dict = {}
    cur_key: str | None = None
    cur_list: list | None = None
    for ln in raw.splitlines():
        if not ln.strip():
            continue
        if ln.startswith("  - ") and cur_list is not None:
            cur_list.append(ln[4:].strip())
            continue
        # close any open list
        cur_key = None
        cur_list = None
        if ":" not in ln:
            continue
        k, _, v = ln.partition(":")
        k = k.strip()
        v = v.strip()
        if not v:
            cur_key = k
            cur_list = []
            out[k] = cur_list
        else:
            # strip surrounding quotes
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            out[k] = v
    return out


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split body into [(heading, content), ...] by `## ` markers."""
    parts = re.split(r'(?m)^##\s+', body)
    sections: list[tuple[str, str]] = []
    for chunk in parts:
        chunk = chunk.strip()
        if not chunk:
            continue
        head, _, rest = chunk.partition("\n")
        sections.append((head.strip(), rest.strip()))
    return sections


# ---------- markdown -> html rendering ----------

def render_section_body(content: str) -> str:
    """Render a section body. Blank-line-separated chunks become <p> or <blockquote>.
    A chunk that's a numbered list becomes a single <p> with <br> between items
    (matches the existing hand-coded style)."""
    chunks = re.split(r'\n\s*\n', content)
    out: list[str] = []
    for ch in chunks:
        ch = ch.strip()
        if not ch:
            continue
        if all(line.lstrip().startswith(">") for line in ch.splitlines()):
            inner = "\n".join(_strip_quote_marker(line) for line in ch.splitlines()).strip()
            inner = _inline(inner)
            out.append(f'                    <blockquote>{inner}</blockquote>')
            continue
        if all(re.match(r'^\d+\.\s', line.strip()) for line in ch.splitlines()):
            inner = "<br>\n                    ".join(_inline(line.strip()) for line in ch.splitlines())
            out.append(f'                    <p>{inner}</p>')
            continue
        # otherwise: each line is its own <p>
        for line in ch.splitlines():
            line = line.strip()
            if line:
                out.append(f'                    <p>{_inline(line)}</p>')
    return "\n".join(out)


def _strip_quote_marker(line: str) -> str:
    s = line.lstrip()
    if s.startswith(">"):
        s = s[1:]
        if s.startswith(" "):
            s = s[1:]
    return s


_BOLD = re.compile(r'\*\*(.+?)\*\*')
_EM = re.compile(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)')
_UNDER_EM = re.compile(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)')


def _inline(text: str) -> str:
    """Apply minimal inline markdown -> html. Escapes HTML first, then re-injects tags."""
    text = html.escape(text, quote=False)
    text = _BOLD.sub(r'<strong>\1</strong>', text)
    text = _EM.sub(r'<em>\1</em>', text)
    text = _UNDER_EM.sub(r'<em>\1</em>', text)
    return text


def render_sections(sections: list[tuple[str, str]],
                    only: set[str] | None = None,
                    indent_units: int = 4) -> str:
    """Render a list of sections to HTML. If `only` is given, only sections
    whose heading is in `only` are included (in the order they appear in the markdown)."""
    blocks: list[str] = []
    for head, body in sections:
        if only is not None and head not in only:
            continue
        cls = "card-section quote-section" if head in QUOTE_SECTION_NAMES else "card-section"
        body_html = render_section_body(body)
        blocks.append(
            f'                <section class="{cls}">\n'
            f'                    <h{ "3" if indent_units == 3 else "2" } class="section-heading">{html.escape(head)}</h{ "3" if indent_units == 3 else "2" }>\n'
            f'{body_html}\n'
            f'                </section>'
        )
    return "\n\n".join(blocks)


# ---------- frontmatter helpers ----------

def date_display(iso: str) -> str:
    d = _dt.date.fromisoformat(iso)
    return d.strftime("%B ") + str(d.day) + d.strftime(", %Y")


def excerpt_from(sections: list[tuple[str, str]]) -> str:
    """First non-blank, non-blockquote line of the Meaning section."""
    for head, body in sections:
        if head == "Meaning":
            for line in body.splitlines():
                s = line.strip()
                if s and not s.startswith(">"):
                    return s
    return ""


def quote_text(sections: list[tuple[str, str]]) -> str:
    for head, body in sections:
        if head == "Quote":
            for line in body.splitlines():
                s = _strip_quote_marker(line).strip()
                if s.startswith('"') and s.endswith('"'):
                    s = s[1:-1]
                if s:
                    return s
    return ""


# ---------- template fill ----------

def fill(tpl: str, mapping: dict) -> str:
    out = tpl
    for k, v in mapping.items():
        out = out.replace("{{" + k + "}}", v)
    return out


# ---------- top-level builders ----------

def build_card_page(card: dict, out_path: pathlib.Path) -> None:
    fm = card["frontmatter"]
    sections = card["sections"]
    tpl = (TEMPLATES / "card.html").read_text(encoding="utf-8")
    rendered_sections = render_sections(sections, only=None, indent_units=2)
    page = fill(tpl, {
        "TITLE": html.escape(fm["title"]),
        "DATE": fm["date"],
        "DATE_DISPLAY": date_display(fm["date"]),
        "CATEGORY": html.escape(fm.get("category", "")),
        "SLUG": fm["slug"],
        "IMAGE_PATH": fm["image"],
        "META_DESCRIPTION": html.escape(excerpt_from(sections)),
        "OG_QUOTE": html.escape(quote_text(sections)),
        "SECTIONS": rendered_sections,
    })
    out_path.write_text(page, encoding="utf-8")


def build_index(card: dict, out_path: pathlib.Path) -> None:
    fm = card["frontmatter"]
    sections = card["sections"]
    tpl = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    rendered_sections = render_sections(sections, only=INDEX_SECTIONS, indent_units=3)
    page = fill(tpl, {
        "TITLE": html.escape(fm["title"]),
        "DATE": fm["date"],
        "DATE_DISPLAY": date_display(fm["date"]),
        "CATEGORY": html.escape(fm.get("category", "")),
        "SLUG": fm["slug"],
        "IMAGE_PATH": f'cards/{fm["image"]}',
        "SECTIONS": rendered_sections,
    })
    out_path.write_text(page, encoding="utf-8")


def build_archive(out_path: pathlib.Path) -> None:
    entry_tpl = (TEMPLATES / "archive_entry.html").read_text(encoding="utf-8")
    archive_tpl = (TEMPLATES / "archive.html").read_text(encoding="utf-8")

    md_files = sorted(CARDS.glob("*.md"), reverse=True)  # newest first by filename
    entries: list[str] = []
    for md_path in md_files:
        text = md_path.read_text(encoding="utf-8")
        try:
            card = parse_card(text)
        except Exception as exc:
            print(f"warning: skipping {md_path.name}: {exc}", file=sys.stderr)
            continue
        fm = card["frontmatter"]
        entries.append(fill(entry_tpl, {
            "TITLE": html.escape(fm["title"]),
            "DATE": fm["date"],
            "DATE_DISPLAY": date_display(fm["date"]),
            "CATEGORY": html.escape(fm.get("category", "")),
            "SLUG": fm["slug"],
            "IMAGE_PATH": f'cards/{fm["image"]}',
            "EXCERPT": html.escape(excerpt_from(card["sections"])),
        }))
    page = fill(archive_tpl, {"ENTRIES": "\n".join(entries).rstrip()})
    out_path.write_text(page, encoding="utf-8")


# ---------- main ----------

def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: build_site.py docs/cards/{date}-{slug}.md", file=sys.stderr)
        return 2
    md_path = pathlib.Path(argv[1])
    if not md_path.is_absolute():
        md_path = (REPO_ROOT / md_path).resolve()
    if not md_path.exists():
        print(f"error: {md_path} not found", file=sys.stderr)
        return 1

    text = md_path.read_text(encoding="utf-8")
    card = parse_card(text)
    fm = card["frontmatter"]

    card_html = CARDS / f'{fm["date"]}-{fm["slug"]}.html'
    build_card_page(card, card_html)
    print(f"wrote {card_html.relative_to(REPO_ROOT)}")

    build_index(card, DOCS / "index.html")
    print(f"wrote docs/index.html")

    build_archive(DOCS / "archive.html")
    print(f"wrote docs/archive.html")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
