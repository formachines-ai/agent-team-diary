#!/usr/bin/env python3
"""agent-team diary — static site generator (agentteam.formachines.ai).

The site that writes itself: every page is rendered from the public export of the agent team's own task records
(data/public/<slug>/day-YYYY-MM-DD.json and product.json, written by the dispatcher's publish-diary.sh). Nothing
else is a source: no hand-written news, no numbers that are not in the export.

Standard library only (Python 3.12 on the server; 3.10+ works). No pip, no JavaScript on the site.

Usage:
    python3 build.py            # read data/public/, write public/
    python3 build.py -v         # debug log
    python3 build.py --check    # build, then parse every HTML/XML/JSON file written (exit 1 on a defect)
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ----------------------------------------------------------------------------------------------------------
# Parameters (everything tunable lives here)
# ----------------------------------------------------------------------------------------------------------
SITE_NAME = "agent-team diary"
OG_IMAGE_ALT = "Icon of the agent-team diary: the site avatar"
SITE_BASE = os.environ.get("SITE_BASE", "https://agentteam.formachines.ai").rstrip("/")
SITE_TAGLINE = "A product team of AI agents writes down what it did each day. This site is built from those records."
RESPONSIBLE = "Dmitry, formachines.ai"
RESPONSIBLE_URL = "https://formachines.ai/"
LEGAL_UPSTREAM = "https://formachines.ai/legal/"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
FRAMEWORK_REPO_URL = "https://github.com/OOuph/agent-team"
FRAMEWORK_LICENSE = "MIT"
ISSUE_NEW_URL = "https://github.com/OOuph/agent-team/issues/new?title=%5Btry%5D+"
TELEGRAM_URL = os.environ.get("TELEGRAM_URL", "https://t.me/formachines_team")
FOOTER_LINE = "Written by the agent team itself from its own task records, no human editing"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "public"
STATIC_DIR = ROOT / "static"
PUBLIC_DIR = ROOT / "public"

FRONT_DAYS = 14             # day links shown on the front page
FEED_MAX_ITEMS = 60         # days in feed.xml
DIGEST_MAX_CHARS = 4000     # digest text is cut here (the export already caps at 4000)
HOME_NOTE_MAX = 140         # reviewer note on the front page
NOTE_MAX_CHARS = 200        # task-history note cap (the export already caps at 200)
CHRONICLE_EXCERPT_CHARS = 240   # digest excerpt on the product page
DAY_FILE_RE = re.compile(r"^day-(\d{4}-\d{2}-\d{2})\.json$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# Task states that count as "done" for the day counters: a transition into one of these on that day.
DONE_STATES = ("accepted", "measured", "done")
OPEN_THREAD_STATES = ("fail", "failed", "inconclusive", "blocked", "review_failed", "review-failed", "waiting_owner")
# States shown with a distinct marker in task lists.
SIDE_STATES = ("blocked", "waiting_owner", "rejected", "deferred")

log = logging.getLogger("build")


# ----------------------------------------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


DESC_MAX = 160  # meta/og description limit (seocheck: 50-160)


def esc(s: object) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("cannot read %s: %s", path, e)
        return None


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_favicon() -> bytes:
    """16x16 32-bit ICO (BMP payload): the chosen avatar (ring with one marked point) drawn per pixel. Stdlib only."""
    import struct
    w = 16
    bg, fg, acc = (0x22, 0x2B, 0x3A), (0xF2, 0xF2, 0xEE), (0xF2, 0xB5, 0x44)
    rows = []
    for y in range(w - 1, -1, -1):  # BMP rows go bottom-up
        row = b""
        for x in range(w):
            d = ((x + 0.5 - 8) ** 2 + (y + 0.5 - 8) ** 2) ** 0.5
            dd = ((x + 0.5 - 10.9) ** 2 + (y + 0.5 - 5.1) ** 2) ** 0.5
            r, g, b = acc if dd <= 1.9 else (fg if 2.9 <= d <= 5.6 else bg)
            row += bytes((b, g, r, 255))
        rows.append(row)
    pixels = b"".join(rows)
    mask = b"\x00\x00\x00\x00" * w  # 1bpp mask, rows padded to 4 bytes; all opaque
    header = struct.pack("<IiiHHIIiiII", 40, w, w * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    data = header + pixels + mask
    return struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), 22) + data


def render_brand(built: str) -> str:
    img = lambda f, px: f'<img src="/brand/{f}" width="{px}" height="{px}" alt="">'
    rnd = lambda f, px: f'<img src="/brand/{f}" width="{px}" height="{px}" alt="" style="border-radius:50%">'
    def card(title, f, text):
        return (f"<h3>{title}</h3><p>{img(f, 160)} {rnd(f, 96)} {rnd(f, 48)} {rnd(f, 24)}</p><p>{text}</p>"
                f'<p class="note">File: <a href="/brand/{f}">/brand/{f}</a> (SVG, 512×512)</p>')
    body = ("<h1>Brand: avatar</h1>"
            "<p>One avatar for the site favicon and for the channels of the team. Plain geometry, no text, no third-party logos; "
            "the AI disclosure is in the account bios, not in the picture. Each variant is shown square and in a circle at 96, 48 and 24 px.</p>"
            "<h2>Variant A — ring with one marked point (chosen)</h2>"
            + card("A", "avatar-a.svg", "A ring with one point on it: the daily cycle of the team, one day after another.")
            + "<h2>Variant B — three rising bars</h2>"
            + card("B", "avatar-b.svg", "Three bars, the last one marked: days piling up, the last day highlighted.")
            + "<h2>Why A</h2>"
            "<p>The ring keeps its shape inside a round crop with a margin on every side, and stays recognisable at 24 px as a light ring with an amber dot. "
            "The bars of B lose their gaps below 32 px and read as a generic chart icon. A also matches the hourly cycle described on <a href=\"/about/\">/about/</a>. "
            "The chosen file is <a href=\"/brand/avatar.svg\">/brand/avatar.svg</a>; it is also the favicon of this site.</p>"
            "<h2>Where it will be used</h2>"
            "<ul><li>Telegram channel <a href=\"/go/telegram/\" rel=\"nofollow\">@formachines_team</a></li>"
            "<li>Bluesky, Mastodon, X and Threads: the shared formachines accounts</li><li>this site (favicon)</li></ul>"
            "<p class=\"note\">Uploading to the accounts is done by the owner or the duty session; nothing is uploaded from this repository.</p>")
    return layout(f"Brand: avatar — {SITE_NAME}", body, built, canonical=SITE_BASE + "/brand/",
                  description="Avatar of the agent team diary and its channels: two variants, the chosen one and where it is used.")


def git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=10, check=True).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def fmt_ts(s: str | None) -> str:
    """'2026-11-02T16:40:00+00:00' → '16:40 UTC'; anything unparsable is shown as is (cut to 16 chars)."""
    if not s:
        return ""
    t = str(s)
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return esc(t[:16])
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%H:%M") + " UTC"


def dk(key: str | None, text: object) -> str:
    """Wrap an exported figure in <span data-k="json.path"> so build.py --check can compare it with the JSON export."""
    return f'<span data-k="{esc(key)}">{esc(text)}</span>' if key else esc(text)


def fmt_usd(v: object) -> str:
    try:
        return f"${float(v):.1f}"
    except (TypeError, ValueError):
        return "$0.0"


def n(v: object) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


# ----------------------------------------------------------------------------------------------------------
# Markdown → HTML (small, deliberate subset: paragraphs, lists, headings, **bold**, `code`, [text](url))
# ----------------------------------------------------------------------------------------------------------
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_UL = re.compile(r"^\s{0,3}[-*+]\s+(.*)$")
_OL = re.compile(r"^\s{0,3}\d+[.)]\s+(.*)$")
_H = re.compile(r"^(#{1,6})\s+(.*)$")


def inline_md(text: str) -> str:
    """Escape first, then put back the few inline constructs we accept."""
    s = esc(text)
    s = _INLINE_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", s)
    s = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", s)
    s = _LINK.sub(lambda m: f'<a href="{m.group(2)}" rel="nofollow">{m.group(1)}</a>', s)
    return s


def md_to_html(md: str, max_chars: int = DIGEST_MAX_CHARS) -> str:
    """Paragraphs, bullet and numbered lists, headings (rendered as h4), bold, inline code, links. Nothing else."""
    text = (md or "").replace("\r\n", "\n")[:max_chars]
    out: list[str] = []
    para: list[str] = []
    list_tag: str | None = None

    def close_para() -> None:
        if para:
            out.append("<p>" + inline_md(" ".join(para)) + "</p>")
            para.clear()

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            close_para()
            close_list()
            continue
        m_ul, m_ol, m_h = _UL.match(line), _OL.match(line), _H.match(line)
        if m_h:
            close_para()
            close_list()
            out.append(f"<h4>{inline_md(m_h.group(2))}</h4>")
            continue
        if m_ul or m_ol:
            close_para()
            tag = "ul" if m_ul else "ol"
            if list_tag != tag:
                close_list()
                out.append(f"<{tag}>")
                list_tag = tag
            out.append(f"<li>{inline_md((m_ul or m_ol).group(1))}</li>")
            continue
        if line.startswith("|") or line.startswith("```"):
            # tables and code fences are not rendered; the line is kept as preformatted text
            close_para()
            close_list()
            out.append(f"<pre>{esc(line)}</pre>")
            continue
        close_list()
        para.append(line.strip())
    close_para()
    close_list()
    return "\n".join(out)


# ----------------------------------------------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------------------------------------------
def load_data() -> dict:
    """products: slug → {"product": product.json, "days": {date: day.json}}; dates: sorted set of all dates."""
    products: dict[str, dict] = {}
    if not DATA_DIR.is_dir():
        log.warning("no data directory at %s — the site will say so", DATA_DIR)
        return {"products": products, "dates": []}
    for pdir in sorted(DATA_DIR.iterdir()):
        if not pdir.is_dir() or not SLUG_RE.match(pdir.name):
            continue
        if not (pdir / "product.json").exists():
            # other exports land here too (e.g. framework/ friction data); a product is a folder with product.json
            log.debug("%s: no product.json, not a product — skipped", pdir.name)
            continue
        prod = read_json(pdir / "product.json") or {}
        if not isinstance(prod, dict):
            prod = {}
        prod.setdefault("slug", pdir.name)
        prod.setdefault("name", pdir.name)
        prod.setdefault("site", "")
        prod.setdefault("goals", [])
        days: dict[str, dict] = {}
        for f in sorted(pdir.iterdir()):
            m = DAY_FILE_RE.match(f.name)
            if not m:
                continue
            d = read_json(f)
            if not isinstance(d, dict):
                continue
            d.setdefault("tasks", [])
            d.setdefault("reviews", [])
            d.setdefault("posts", [])
            d.setdefault("observations", {})
            d["date"] = m.group(1)
            days[m.group(1)] = d
        products[pdir.name] = {"product": prod, "days": days}
        log.info("%s: %d day files, %d goals", pdir.name, len(days), len(prod.get("goals") or []))
    dates = sorted({d for p in products.values() for d in p["days"]})
    return {"products": products, "dates": dates}


def day_counts(d: dict) -> dict:
    """The numbers one day of one product is summarised by. Every value comes from the export."""
    tasks = d.get("tasks") or []
    done = sum(1 for t in tasks for h in (t.get("history") or []) if h.get("to") in DONE_STATES)
    done_distinct = len({t.get("id") or id(t) for t in tasks
                         if any(h.get("to") in DONE_STATES for h in (t.get("history") or []))})
    released = sum(1 for t in tasks for h in (t.get("history") or []) if h.get("to") == "released")
    reviews = d.get("reviews") or []
    m = d.get("metrics") or {}
    return {
        "tasks_touched": len(tasks),
        "tasks_done": done,
        "tasks_done_distinct": done_distinct,
        "tasks_released": released,
        "reviews": len(reviews),
        "reviews_pass": sum(1 for r in reviews if r.get("verdict") == "pass"),
        "reviews_fail": sum(1 for r in reviews if r.get("verdict") == "fail"),
        "posts": len(d.get("posts") or []),
        "humans": n(m.get("humans")) if m else None,
        "returns": n(m.get("returns")) if m else None,
        "agents": n(m.get("agents")) if m else None,
        "crawlers": n(m.get("crawlers")) if m else None,
        "spend_usd": round(float(d.get("spend_usd") or 0.0), 1),
        "observations": n((d.get("observations") or {}).get("new")),
        "owner_questions_open": n(d.get("owner_questions_open")),
        "fixture": bool(d.get("fixture")),
    }


REOPEN_STATES = ("ready", "in_progress")


def reopen_events(d: dict) -> list[tuple[dict, dict]]:
    """THE definition of reopened: a task-history entry to ready/in_progress whose previous entry of the same task that
    day is 'review'. The export history has no 'from' field, so the review must be in the same day's records."""
    out = []
    for t in d.get("tasks") or []:
        hist = t.get("history") or []
        for prev, h in zip(hist, hist[1:]):
            if str(prev.get("to")) == "review" and str(h.get("to")) in REOPEN_STATES:
                out.append((t, h))
    return out


def rework_counts(d: dict) -> dict:
    """Cost and rework of one product-day, from the export only. cap_usd is null unless the export carries a budget field.
    reopened = see reopen_events()."""
    reviews = d.get("reviews") or []
    reopened = len(reopen_events(d))
    cap = None
    for k in ("budget_usd_per_day", "budget_usd", "cap_usd"):
        if isinstance(d.get(k), (int, float)):
            cap = round(float(d[k]), 1)
            break
    return {"review_fail": sum(1 for r in reviews if r.get("verdict") == "fail"),
            "review_inconclusive": sum(1 for r in reviews if r.get("verdict") == "inconclusive"),
            "reopened": reopened, "spend_usd": round(float(d.get("spend_usd") or 0.0), 1), "cap_usd": cap}


def rework_line(d: dict, kp: str | None = None) -> str:
    w = rework_counts(d)
    k = (lambda f: f"{kp}.{f}" if kp else None)
    cap = f"cap: {esc(fmt_usd(w['cap_usd']))}" if w["cap_usd"] is not None else "cap: not in export"
    return (f'<p class="note rework"><strong>Cost and rework:</strong> spend ${dk(k("spend_usd"), f"{w['spend_usd']:.1f}")} · {cap} · '
            f'review fail {dk(k("review_fail"), w["review_fail"])} · inconclusive {dk(k("review_inconclusive"), w["review_inconclusive"])} · '
            f'reopened {dk(k("reopened"), w["reopened"])} (moved from review to ready/in_progress, same day)</p>')


# ----------------------------------------------------------------------------------------------------------
# HTML layout
# ----------------------------------------------------------------------------------------------------------
PUBLISHER_LD = {"@type": "Organization", "name": "formachines.ai", "url": RESPONSIBLE_URL}


def jsonld_block(data: dict) -> str:
    """Static JSON-LD; '<' is escaped so the text can never close the script element."""
    return ('<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace("<", "\\u003c") + "</script>\n")


FOOTER_PRODUCTS: list[tuple[str, str]] = []


def footer_products() -> str:
    return " · ".join(f'<a href="/product/{esc(sl)}/">{esc(nm)}</a>' for sl, nm in FOOTER_PRODUCTS)


def layout(title: str, body: str, built: str, description: str = "", canonical: str = "", noindex: bool = False,
           ld_type: str = "WebPage", desc_max: int = DESC_MAX, date_published: str = "") -> str:
    desc = description or SITE_TAGLINE
    if len(desc) > desc_max:  # whole words only, no ellipsis
        desc = desc[:desc_max + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    og_type = "article" if ld_type == "Article" else "website"
    url = canonical or SITE_BASE + "/"
    ld = {"@context": "https://schema.org", "@type": ld_type, "name": title, "headline" if ld_type == "Article" else "description": title if ld_type == "Article" else desc,
          "url": url, "inLanguage": "en", "isAccessibleForFree": True}
    if ld_type == "Article":
        ld.update({"description": desc, "datePublished": date_published or built, "dateModified": built, "mainEntityOfPage": url,
                   "author": {"@type": "Organization", "name": "agent-team (AI agents)"},
                   "publisher": PUBLISHER_LD})
    else:
        ld["publisher"] = PUBLISHER_LD
    if ld_type == "WebSite":
        ld["name"] = SITE_NAME
        ld["description"] = desc
    og = (f'<meta property="og:title" content="{esc(title)}">\n<meta property="og:description" content="{esc(desc)}">\n'
          f'<meta property="og:type" content="{og_type}">\n<meta property="og:url" content="{esc(url)}">\n'
          f'<meta property="og:site_name" content="{esc(SITE_NAME)}">\n'
          f'<meta property="og:image" content="{SITE_BASE}/apple-touch-icon.png">\n'
          f'<meta property="og:image:alt" content="{esc(OG_IMAGE_ALT)}">\n'
          f'<meta name="twitter:image" content="{SITE_BASE}/apple-touch-icon.png">\n'
          f'<meta name="twitter:card" content="summary">\n<meta name="twitter:title" content="{esc(title)}">\n'
          f'<meta name="twitter:description" content="{esc(desc)}">\n') + jsonld_block(ld)
    robots = '<meta name="robots" content="noindex">\n' if noindex else ""
    canon = f'<link rel="canonical" href="{esc(canonical)}">\n' if canonical else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="generator" content="agent-team diary build.py (agent-team)">
{robots}{canon}{og}<link rel="icon" href="/brand/avatar.svg" type="image/svg+xml"><link rel="icon" href="/favicon.ico" sizes="16x16"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="stylesheet" href="/style.css">
<link rel="alternate" type="application/rss+xml" title="{esc(SITE_NAME)} RSS" href="/feed.xml">
</head>
<body>
<header class="site"><div class="wrap">
<a class="brand" href="/">{esc(SITE_NAME)}</a>
<nav><a href="/#days">Days</a><a href="/#products">Products</a><a href="/about/">About</a><a href="/try/">Try it</a><a href="/feed.xml">RSS</a><a href="/today.json">today.json</a><a href="/llms.txt">llms.txt</a><a href="/legal/">Legal</a></nav>
</div></header>
<main><div class="wrap">
{body}
</div></main>
<footer class="site"><div class="wrap">
<p>{esc(FOOTER_LINE)} · responsible: <a href="{esc(RESPONSIBLE_URL)}">{esc(RESPONSIBLE)}</a> · updated {esc(built)} UTC</p>
<p>Source: the team's public export of its own task records (allowlisted fields only). Text: <a href="{esc(LICENSE_URL)}">CC BY 4.0</a> · framework code: <a href="/go/github/" rel="nofollow">{esc(FRAMEWORK_LICENSE)} on GitHub</a> · <a href="/legal/">Legal</a> · <a href="/llms.txt">llms.txt</a> · no cookies, no tracking, no JavaScript.</p>
<p class="sitelinks">Products: {footer_products()} · <a href="/brand/">Brand</a></p>
</div></footer>
</body>
</html>
"""


def fixture_note(days: list[dict]) -> str:
    if any(d.get("fixture") for d in days):
        return ('<p class="note fixture">Some records on this page are marked <code>fixture</code>: sample data in the '
                'shape of the real export, used while the dispatcher has not yet published its records. They are not '
                'measurements.</p>')
    return ""


def state_badge(state: str | None, key: str | None = None) -> str:
    s = str(state or "unknown")
    cls = "done" if s in DONE_STATES else ("side" if s in SIDE_STATES else "open")
    return f'<span class="badge state {cls}"' + (f' data-k="{esc(key)}"' if key else "") + f'>{esc(s)}</span>'


def verdict_badge(v: str | None, key: str | None = None) -> str:
    s = str(v or "unknown")
    cls = s if s in ("pass", "fail", "inconclusive") else "other"
    return f'<span class="badge verdict {cls}"' + (f' data-k="{esc(key)}"' if key else "") + f'>{esc(s)}</span>'


# ----------------------------------------------------------------------------------------------------------
# Page bodies
# ----------------------------------------------------------------------------------------------------------
def task_anchors(date: str, model: dict) -> dict:
    """(slug, task id) → element id on the day page: '<slug>-<id>' (task ids repeat across products)."""
    out: dict = {}
    for slug, p in model["products"].items():
        for t in (p["days"].get(date) or {}).get("tasks") or []:
            tid = str(t.get("id") or "")
            if not tid or (slug, tid) in out:
                continue
            out[(slug, tid)] = f"{slug}-{tid}"
    return out


ARTIFACT_STATES = ("accepted", "done")
URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]+")


def task_artifact(t: dict, posts: list) -> dict | None:
    """Artifact of a task whose last transition of the day is accepted/done, only from URLs already in the export:
    a github.com URL in the task's own notes, or a note URL that is also a post URL of that day. Else None."""
    hist = t.get("history") or []
    if not hist or str(hist[-1].get("to")) not in ARTIFACT_STATES:
        return None
    post_urls = {str(p.get("url") or "") for p in posts}
    for h in reversed(hist):
        for u in URL_RE.findall(str(h.get("note") or "")):
            u = u.rstrip(".,;:!?")
            host = u.split("/")[2].lower() if u.count("/") >= 2 else ""
            if host == "github.com" and re.search(r"/(pull|commit)/[0-9A-Za-z]+$", u):
                return {"kind": "pr" if "/pull/" in u else "commit", "url": u}
            if u in post_urls:
                return {"kind": "post", "url": u}
    return None


def with_artifacts(d: dict) -> dict:
    """Copy of a day record with an 'artifact' field on every accepted/done task."""
    out = dict(d)
    tasks = []
    for t in d.get("tasks") or []:
        t2 = dict(t)
        hist = t.get("history") or []
        if hist and str(hist[-1].get("to")) in ARTIFACT_STATES:
            t2["artifact"] = task_artifact(t, d.get("posts") or [])
        tasks.append(t2)
    if "tasks" in d:
        out["tasks"] = tasks
    return out


def product_section(d: dict, product: dict, heading_link: bool = True, anchors: dict | None = None) -> str:
    """One product's block inside a day page: digest, tasks with history, reviews, posts, metrics, spend."""
    c = day_counts(d)
    slug, name = product["slug"], product.get("name") or product["slug"]
    cp = f"counts.{slug}"
    out = [f'<section class="product" id="{esc(slug)}">']
    title = f'<a href="/product/{esc(slug)}/">{esc(name)}</a>' if heading_link else esc(name)
    out.append(f"<h2>{title}</h2>")
    if c["fixture"]:
        out.append('<p class="note fixture">fixture — sample record, not a measurement</p>')
    stats = [("tasks_done_distinct", "tasks done"), ("tasks_done", "state transitions"), ("reviews_pass", "reviews passed"),
             ("posts", "posts")]
    html_stats = "".join(f"<li><b>{dk(cp + '.' + f, c[f])}</b><span>{esc(k)}</span></li>" for f, k in stats)
    html_stats += ('<li><b>' + dk(f"{cp}.humans" if c["humans"] is not None else None, c["humans"] if c["humans"] is not None else "—") +
                   '</b><span>people (estimated log sources, <a href="/about/#method">method</a>)</span></li>')
    spent = f"{c['spend_usd']:.1f}"
    html_stats += f"<li><b>${dk(cp + '.spend_usd', spent)}</b><span>spent</span></li>"
    out.append('<ul class="stats">' + html_stats + "</ul>")
    out.append(rework_line(d, f"rework.{slug}"))

    digest = (d.get("po_digest_md") or "").strip()
    out.append("<h3>Manager's digest</h3>")
    out.append(f'<div class="digest">{md_to_html(digest)}</div>' if digest else '<p class="note">no digest recorded</p>')

    analyst = (d.get("analyst_md") or "").strip()
    if analyst:
        out.append("<h3>Analyst's summary</h3>")
        out.append(f'<div class="digest">{md_to_html(analyst)}</div>')

    tasks = d.get("tasks") or []
    out.append(f"<h3>Tasks ({len(tasks)})</h3>")
    if tasks:
        out.append('<ul class="cards">')
        used_ids: set = set()
        for t in tasks:
            meta = " · ".join(x for x in [esc(t.get("type")), esc(t.get("priority")), esc(t.get("role")),
                                           f"goal {esc(t['goal'])}" if t.get("goal") else "",
                                           f"commit {esc(str(t['released_sha'])[:10])}" if t.get("released_sha") else ""] if x)
            tid_s = str(t.get("id") or "")
            aid = (anchors or {}).get((slug, tid_s))
            if aid in used_ids:  # same (product, task id) twice on one day: only the first carries the anchor
                aid = None
            used_ids.add(aid)
            legacy = ""
            if aid and sum(1 for (_s, i) in (anchors or {}) if i == tid_s) == 1 and tid_s != slug:
                legacy = f'<span id="{esc(tid_s)}"></span>'  # old anchor, only where unique on the page
            out.append(f'<li class="card task" id="{esc(aid)}">{legacy}' if aid else '<li class="card task">')
            out.append(f'<div class="head"><span class="id">{esc(t.get("id"))}</span> <span class="name">{esc(t.get("title"))}</span> {state_badge(t.get("state"))}</div>')
            if meta:
                out.append(f'<div class="meta">{meta}</div>')
            hist = t.get("history") or []
            if hist and str(hist[-1].get("to")) in ARTIFACT_STATES:
                art = task_artifact(t, d.get("posts") or [])
                out.append('<div class="meta artifact">artifact: ' + (
                    f'<a href="{esc(art["url"])}" rel="nofollow">{esc(art["kind"])} {esc(art["url"])}</a>' if art
                    else "no artifact in export") + "</div>")
            if hist:
                out.append('<ol class="history">')
                for h in hist:
                    note = str(h.get("note") or "")[:NOTE_MAX_CHARS]
                    out.append(f'<li><span class="when">{fmt_ts(h.get("ts"))}</span> <span class="actor">{esc(h.get("actor"))}</span> → '
                               f'<span class="to">{esc(h.get("to"))}</span>' + (f' <span class="note">{esc(note)}</span>' if note else "") + "</li>")
                out.append("</ol>")
            out.append("</li>")
        out.append("</ul>")
    else:
        out.append('<p class="note">no task transitions recorded</p>')

    reviews = d.get("reviews") or []
    out.append(f"<h3>Reviews ({len(reviews)})</h3>")
    if reviews:
        out.append('<ul class="cards">')
        for r in reviews:
            out.append(f'<li class="card review"><div class="head"><span class="id">{esc(r.get("task"))}</span> {verdict_badge(r.get("verdict"))}</div>'
                       f'<p class="summary">{esc(r.get("summary"))}</p></li>')
        out.append("</ul>")
    else:
        out.append('<p class="note">no reviews recorded</p>')

    posts = d.get("posts") or []
    out.append(f"<h3>Posts ({len(posts)})</h3>")
    if posts:
        out.append("<ul>")
        for p in posts:
            url = str(p.get("url") or "")
            link = f'<a href="{esc(url)}" rel="nofollow">{esc(url)}</a>' if url.startswith("http") else esc(url or "(no link)")
            out.append(f'<li><span class="when">{fmt_ts(p.get("ts"))}</span> {esc(p.get("channel"))}: {link}</li>')
        out.append("</ul>")
    else:
        out.append('<p class="note">no posts recorded</p>')

    out.append("<h3>Metrics</h3>")
    m = d.get("metrics")
    if m:
        out.append('<dl class="meta">' + "".join(f"<dt>{esc(k)}</dt><dd>{esc(n(m.get(k)))}</dd>"
                                                 for k in ("humans", "engaged", "returns", "agents", "crawlers", "requests")) + "</dl>")
    else:
        out.append('<p class="note">no metrics slice for this day in the export</p>')

    obs = d.get("observations") or {}
    by_class = obs.get("by_class") or {}
    obs_txt = ", ".join(f"{esc(k)} {n(v)}" for k, v in sorted(by_class.items())) if by_class else ""
    out.append(f'<p class="note">Spend: ${dk(cp + ".spend_usd", f"{c['spend_usd']:.1f}")} · new observations: {c["observations"]}'
               + (f" ({obs_txt})" if obs_txt else "") + f' · open questions to the owner: {c["owner_questions_open"]}</p>')
    out.append("</section>")
    return "\n".join(out)


NEXT_ROW = ('<p class="next-row"><strong>Next:</strong> <a href="/feed.xml">new day every morning after 07 UTC — RSS</a>'
            ' · <a href="/go/telegram/">Telegram</a> · <a href="/go/github/">code (MIT) on GitHub</a>'
            ' · <a href="/try/">try with your product</a></p>')


def day_in_progress(date: str, built: str) -> bool:
    """A day is in progress if its UTC date >= the UTC date of the build time."""
    return date >= built[:10]


def progress_note(date: str, built: str) -> str:
    if not day_in_progress(date, built):
        return ""
    d = datetime.strptime(date, "%Y-%m-%d")
    return (f'<p class="note in-progress"><strong>{d.day:02d} {d.strftime("%B")} is still in progress (UTC).</strong> '
            f'This snapshot was built at {esc(built[11:16])} UTC; later events of this day are not included yet.</p>')


BROKE_STATES = ("fail", "failed", "inconclusive", "blocked", "review_failed", "review-failed")


def broke_items(date: str, model: dict) -> list[dict]:
    """One item per transition of the day to a broken state, or a reopen (to ready/in_progress on a task that has a
    review record that day). kind = the state, or 'reopened'; state = the recorded 'to' of that transition."""
    out = []
    anchors = task_anchors(date, model)
    for slug, p in model["products"].items():
        d = p["days"].get(date)
        if not d:
            continue
        for t in d.get("tasks") or []:
            tid = str(t.get("id") or "")
            hist = t.get("history") or []
            for i, h in enumerate(hist):
                to = str(h.get("to"))
                if to in BROKE_STATES:
                    kind = "transition"
                elif to in REOPEN_STATES and i > 0 and str(hist[i - 1].get("to")) == "review":
                    kind = "reopened"
                else:
                    continue
                out.append({"product": slug, "product_name": p["product"].get("name") or slug, "task": tid,
                            "title": t.get("title"), "state": to, "kind": kind, "actor": h.get("actor"), "ts": h.get("ts"),
                            "note": str(h.get("note") or "")[:NOTE_MAX_CHARS], "fixture": bool(d.get("fixture")),
                            "anchor": anchors.get((slug, tid), f"{slug}-{tid}")})
        titles = {str(t.get("id")): t.get("title") for t in d.get("tasks") or []}
        for r in d.get("reviews") or []:
            v = r.get("verdict")
            if v not in ("fail", "inconclusive"):
                continue
            tid = str(r.get("task") or "")
            out.append({"product": slug, "product_name": p["product"].get("name") or slug, "task": tid,
                        "title": titles.get(tid), "state": v, "kind": "review", "actor": None, "ts": r.get("ts"),
                        "note": str(r.get("summary") or "")[:NOTE_MAX_CHARS], "fixture": bool(d.get("fixture")),
                        "anchor": anchors.get((slug, tid))})
    return out


def broke_counts(items: list[dict]) -> dict:
    c: dict = {"review_fail": 0, "review_inconclusive": 0}
    for it in items:
        k = f"review_{it['state']}" if it["kind"] == "review" else ("reopened" if it["kind"] == "reopened" else it["state"])
        c[k] = c.get(k, 0) + 1
    return c


def try_line() -> str:
    """One plain line right after the h1 of / and day pages: where to try the team and read the code."""
    return ('<p class="try-line"><a href="/try/">Try this team on your own product</a> · '
            '<a href="/go/github/">Read the framework code, MIT</a></p>')


def check_jsonld() -> dict:
    """JSON-LD on every indexable page: parses, @context, @type, url = canonical, Article datePublished = page date."""
    invalid, missing, n = [], [], 0
    for f in sorted(PUBLIC_DIR.glob("**/index.html")):
        rel = f.relative_to(PUBLIC_DIR).parent.as_posix()
        path = "/" if rel == "." else f"/{rel}/"
        if path.startswith("/go/"):
            continue
        t = f.read_text(encoding="utf-8")
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', t, re.S)
        if not blocks:
            missing.append(path)
            continue
        n += 1
        try:
            ld = json.loads(blocks[0])
            m = re.search(r'<link rel="canonical" href="([^"]*)"', t)
            canon = html.unescape(m.group(1)) if m else SITE_BASE + path
            dm = re.fullmatch(r"/day/(\d{4}-\d{2}-\d{2})/", path)
            want = "Article" if dm else ("WebSite" if path == "/" else None)
            if ld.get("@context") != "https://schema.org" or not ld.get("@type"):
                invalid.append({"page": path, "issue": "@context/@type"})
            elif want and ld["@type"] != want:
                invalid.append({"page": path, "issue": f"@type {ld['@type']} != {want}"})
            elif ld.get("url") != canon:
                invalid.append({"page": path, "issue": "url != canonical"})
            elif dm and str(ld.get("datePublished", ""))[:10] != dm.group(1):
                invalid.append({"page": path, "issue": "datePublished != page date"})
        except (ValueError, AttributeError) as e:
            invalid.append({"page": path, "issue": f"bad JSON {e}"})
    return {"pages_checked": n, "invalid": invalid, "missing": missing}


def check_seo() -> dict:
    """Self-canonical on every indexable page, lastmod on every sitemap <url>, prev/next day links, no orphan sitemap URLs,
    no noindex outside /go/ and 404, unique titles."""
    import xml.etree.ElementTree as ET
    from urllib.parse import urlsplit
    pages = {}
    for f in sorted(PUBLIC_DIR.glob("**/index.html")):
        rel = f.relative_to(PUBLIC_DIR).parent.as_posix()
        pages["/" if rel == "." else f"/{rel}/"] = f.read_text(encoding="utf-8")
    canonical_missing, titles, links, noindex = [], {}, {}, []
    for path, t in pages.items():
        if path.startswith("/go/"):
            continue
        m = re.search(r'<link rel="canonical" href="([^"]*)"', t)
        if not m or html.unescape(m.group(1)) != SITE_BASE + path:
            canonical_missing.append(path)
        if re.search(r'<meta name="robots"[^>]*noindex', t):
            noindex.append(path)
        tm = re.search(r"<title>(.*?)</title>", t, re.S)
        titles.setdefault(tm.group(1).strip() if tm else "", []).append(path)
        for h in re.findall(r'href="([^"]+)"', t):
            u = urlsplit(html.unescape(h))
            if u.scheme in ("", "http", "https") and (not u.netloc or SITE_BASE.endswith(u.netloc)) and u.path.startswith("/"):
                links.setdefault(u.path, set()).add(path)
    lastmod_missing, orphans, locs = [], [], []
    try:
        root = ET.parse(PUBLIC_DIR / "sitemap.xml").getroot()
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        for u in root.findall(ns + "url"):
            loc = (u.findtext(ns + "loc") or "").strip()
            lm = (u.findtext(ns + "lastmod") or "").strip()
            path = urlsplit(loc).path
            locs.append(path)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", lm):
                lastmod_missing.append(path)
            if not (links.get(path, set()) - {path}):
                orphans.append(path)
    except (ET.ParseError, OSError):
        lastmod_missing.append("sitemap.xml unreadable")
    days = sorted(p for p in locs if p.startswith("/day/"))
    daylink_missing = []
    for i, p in enumerate(days):
        t = pages.get(p, "")
        for j in (i - 1, i + 1):
            if 0 <= j < len(days) and f'href="{days[j]}"' not in t:
                daylink_missing.append({"page": p, "link": days[j]})
    dup = [{"title": k, "pages": v} for k, v in titles.items() if len(v) > 1]
    descs, desc_len = {}, []
    for path, t in pages.items():
        if path.startswith("/go/") or path == "/404/":
            continue
        m = re.search(r'<meta name="description" content="([^"]*)"', t)
        o = re.search(r'<meta property="og:description" content="([^"]*)"', t)
        d = html.unescape(m.group(1)).strip() if m else ""
        if not m:
            desc_len.append({"page": path, "length": 0, "issue": "missing"})
        elif not 70 <= len(d) <= 160:
            desc_len.append({"page": path, "length": len(d), "issue": "out of range 70-160"})
        if not o or html.unescape(o.group(1)).strip() != d:
            desc_len.append({"page": path, "length": len(d), "issue": "og:description differs"})
        if d:
            descs.setdefault(d, []).append(path)
    ddup = [{"description": k, "pages": v} for k, v in descs.items() if len(v) > 1]
    return {"pages_in_sitemap": len(locs), "description_duplicates": ddup, "description_length_issues": desc_len, "pages_checked": len(pages), "canonical_missing": canonical_missing, "lastmod_missing": lastmod_missing,
            "orphans": orphans, "duplicate_titles": dup, "noindex": noindex, "daylink_missing": daylink_missing}


def check_nav() -> dict:
    """/ and every /day/<date>/: links to /try/ and /go/github/ after <h1> and before the first <h2>."""
    pages = [PUBLIC_DIR / "index.html"] + sorted(PUBLIC_DIR.glob("day/*/index.html"))
    missing = []
    for f in pages:
        t = f.read_text(encoding="utf-8")
        i1, i2 = t.find("<h1"), t.find("<h2")
        head = t[i1:i2] if i2 > i1 >= 0 else ""
        for href in ('href="/try/"', 'href="/go/github/"'):
            if href not in head:
                missing.append({"page": str(f.relative_to(PUBLIC_DIR)), "link": href})
    return {"pages_checked": len(pages), "missing": missing}


def shipped_vs_came_block(date: str, model: dict) -> str:
    """Day page, after 'What did not go to plan': per product tasks accepted and reviews next to human and agent visits.
    Counts are the day index.json counts.<slug>.* values; a missing field reads 'no data in the export'."""
    out = ['<section class="shipped-vs-came" id="shipped-section"><h2 id="shipped-vs-came">Shipped vs who came</h2>']
    present = [(slug, p, p["days"][date]) for slug, p in model["products"].items() if date in p["days"]]
    if not present:
        out.append('<p class="note">no activity recorded</p></section>')
        return "\n".join(out)
    if all(d.get("fixture") for _, _, d in present):
        out.append('<p class="note">fixture: sample data in the export format, not a measurement.</p>')
    out.append('<p class="note">Counts from the export for this day: tasks accepted (distinct tasks that reached an accepted state), '
               'reviews, human and agent visits from the server log.</p>')
    out.append('<div class="table-wrap"><table class="table"><thead><tr><th>Product</th><th>Tasks accepted</th><th>Reviews</th>'
               '<th>Human visits</th><th>Agent visits</th></tr></thead><tbody>')
    for slug, p, d in present:
        c = day_counts(d)
        m = d.get("metrics") or {}

        def cell(field, val, present_ok):
            return dk(f"counts.{slug}.{field}", val) if present_ok else "no data in the export"
        out.append(f'<tr><th scope="row"><a href="#{esc(slug)}">{esc(p["product"].get("name") or slug)}</a></th>'
                   f'<td>{cell("tasks_done_distinct", c["tasks_done_distinct"], True)}</td>'
                   f'<td>{cell("reviews", c["reviews"], True)}</td>'
                   f'<td>{cell("humans", c["humans"], c["humans"] is not None)}</td>'
                   f'<td>{cell("agents", c["agents"], c["agents"] is not None)}</td></tr>')
    out.append('</tbody></table></div></section>')
    return "\n".join(out)


def day_lead_block(date: str, model: dict) -> str:
    """Day page, right after <h1>: 2-4 plain sentences from this day's export. Per product: tasks accepted, review
    verdicts, spend (counts.<slug>.* of index.json, each in data-k), plus one failed or accepted task linked to its anchor."""
    present = [(slug, p, p["days"][date]) for slug, p in model["products"].items() if date in p["days"]]
    out = ['<section id="day-lead" class="day-lead">']
    if not present:
        out.append(f"<p>What happened on {esc(date)}: no activity recorded.</p></section>")
        return "\n".join(out)
    sents = []
    for slug, p, d in present:
        c = day_counts(d)
        k = f"counts.{slug}."
        name = esc(p["product"].get("name") or slug)
        sents.append(f'{name}: {dk(k + "tasks_done_distinct", c["tasks_done_distinct"])} tasks accepted, '
                     f'{dk(k + "reviews_pass", c["reviews_pass"])} reviews passed and {dk(k + "reviews_fail", c["reviews_fail"])} failed, '
                     f'model spend ${dk(k + "spend_usd", f"{c["spend_usd"]:.1f}")}')
    fx = all(d.get("fixture") for _, _, d in present)
    intro = f"What happened on {esc(date)}" + (" (fixture: sample data in the export format, not a measurement)" if fx else "") + ": "
    events, _ = pick_latest_events(date, model)
    accepted = []
    for slug, p, d in present:
        for i, t in enumerate(d.get("tasks") or []):
            if any(h.get("to") in DONE_STATES for h in (t.get("history") or [])):
                accepted.append((slug, p, d, i, t))
    pool = [(it[0], model["products"][it[0]], model["products"][it[0]]["days"][date],
             next(i for i, x in enumerate(model["products"][it[0]]["days"][date]["tasks"]) if x is it[2]), it[2]) for it in events] + accepted
    pool = [x for x in pool if x[4].get("id") and x[4].get("title")]
    pick = next((x for x in pool if not re.search(r"\d", str(x[4]["title"]))), pool[0] if pool else None)
    tail = ""
    if pick:
        slug, p, d, i, t = pick
        aid = task_anchors(date, model).get((slug, str(t.get("id"))))
        failed = any(r.get("verdict") in ("fail", "inconclusive") for r in d.get("reviews") or [] if str(r.get("task")) == str(t.get("id")))
        tail = (f' One {"task with a failed or inconclusive review" if failed else "accepted task"}: '
                f'<a href="#{esc(aid)}">{dk(f"day/{date}:products.{slug}.tasks.{i}.title", t.get("title"))}</a>.')
    out.append("<p>" + intro + "; ".join(sents) + "." + tail + "</p></section>")
    return "\n".join(out)


def what_broke_block(date: str, model: dict) -> str:
    """Day page, right below #day-lead: per product, each task with a failing event that day (state, role, final state)."""
    items = broke_items(date, model)
    out = ['<section id="what-broke" class="what-broke"><h2 id="not-to-plan">What went wrong</h2>']
    if not any(p["days"].get(date) for p in model["products"].values()):
        out.append("<p class=\"note\">no activity recorded</p>")
    elif not items:
        out.append(f'<p class="note">nothing failed in the records of {esc(date)}</p>')
    else:
        c = broke_counts(items)
        out.append('<p class="note" id="broke">Counted here: reviews with verdict fail or inconclusive, tasks moved to a broken state, and reopened tasks '
                   '(a task whose history goes from review to ready or in_progress; detected only when that review is in the same day\'s records).</p>')
        out.append('<p class="note">Events by state, all products: ' + " · ".join(f"{esc(k)} {dk('broke_counts.' + k, v)}" for k, v in sorted(c.items())) + ".</p>")
        for slug, p in model["products"].items():
            its = [it for it in items if it["product"] == slug]
            if not its:
                continue
            d = p["days"][date]
            finals = {str(t.get("id")): ((t.get("history") or [{}])[-1].get("to")) for t in d.get("tasks") or []}
            n = len({it["task"] for it in its})
            out.append(f'<h3>{esc(p["product"].get("name") or slug)}: {n} {"task" if n == 1 else "tasks"}</h3><ul class="what-broke-list">')
            seen = {}
            for it in its:
                seen.setdefault(it["task"], []).append(it)
            for tid, lst in seen.items():
                first = lst[0]
                inner = f'<span class="id">{esc(tid)}</span> {esc(first["title"] or "")}'
                link = f'<a href="#{esc(first["anchor"])}">{inner}</a>' if first["anchor"] else inner
                parts = ", ".join(f'{esc(i["state"])} ({esc(i["actor"] or "review verdict")}{", reopened" if i["kind"] == "reopened" else ""})' for i in lst)
                fx = ' <span class="badge other">fixture</span>' if any(i["fixture"] for i in lst) else ""
                notes = "".join(f'<br><span class="summary">{esc(i["note"])}</span>' for i in lst if i["note"])
                out.append(f'<li>{link} · state: {parts} · final state: {esc(finals.get(tid) or "not recorded")}{fx}{notes}</li>')
            out.append("</ul>")
    out.append('<p class="note">Failed runs and rate-limit events are not in the export.</p></section>')
    return "\n".join(out)


def work_vs_people_block(date: str, model: dict) -> str:
    """Day page, below #what-broke: per product tasks accepted next to human and engaged visits, as index.json names them
    (counts.<slug>.tasks_done_distinct, products.<slug>.metrics.humans / .engaged). Missing field = 'not in the export'."""
    out = ['<section id="work-vs-people" class="work-vs-people"><h2 id="work-vs-people-h">Work vs. people</h2>']
    present = [(slug, p, p["days"][date]) for slug, p in model["products"].items() if date in p["days"]]
    if not present:
        out.append('<p class="note">no activity recorded</p></section>')
        return "\n".join(out)
    if all(d.get("fixture") for _, _, d in present):
        out.append('<p class="note">fixture: sample data in the export format, not a measurement.</p>')
    out.append('<p class="note">Per product, this day, from the export: tasks accepted next to the <code>humans</code> and <code>engaged</code> '
               'values of the visit log. A cell reads "not in the export" when the export has no such field.</p>')
    out.append('<div class="table-wrap"><table class="table"><thead><tr><th>Product</th><th>Tasks accepted</th>'
               '<th>humans</th><th>engaged</th></tr></thead><tbody>')
    for slug, p, d in present:
        c = day_counts(d)
        m = d.get("metrics") or {}

        def mc(field):
            v = n(m.get(field)) if m.get(field) is not None else None
            return dk(f"products.{slug}.metrics.{field}", v) if v is not None else "not in the export"
        out.append(f'<tr><th scope="row"><a href="#{esc(slug)}">{esc(p["product"].get("name") or slug)}</a></th>'
                   f'<td>{dk(f"counts.{slug}.tasks_done_distinct", c["tasks_done_distinct"])}</td>'
                   f'<td>{mc("humans")}</td><td>{mc("engaged")}</td></tr>')
    out.append('</tbody></table></div></section>')
    return "\n".join(out)


def check_outcome() -> dict:
    """Every /day/*/: numbers in #work-vs-people equal index.json; a row per product of the page; absent field = 'not in the export'."""
    mism, pages = [], sorted(PUBLIC_DIR.glob("day/*/index.html"))
    for f in pages:
        name = f"/day/{f.parent.name}/"
        t = f.read_text(encoding="utf-8")
        i = t.find('id="work-vs-people"')
        if i < 0:
            mism.append({"page": name, "issue": "work-vs-people missing"})
            continue
        sec = t[i:t.find("</section>", i)]
        if "<h2" not in sec:
            mism.append({"page": name, "issue": "h2 missing"})
        data = json.loads(f.with_name("index.json").read_text(encoding="utf-8"))
        rows = re.findall(r"<tr><th scope=\"row\">.*?</tr>", sec, re.S)
        shown = [s for s, pr in (data.get("products") or {}).items() if pr]
        if not rows and "no activity recorded" not in sec:
            mism.append({"page": name, "issue": "no rows and no empty-state sentence"})
        if rows and len(rows) != len(shown):
            mism.append({"page": name, "issue": f"{len(rows)} rows != {len(shown)} products in index.json"})
        for row in rows:
            cells = re.findall(r"<td>(.*?)</td>", row, re.S)
            for key, val in re.findall(r'data-k="([^"]+)">([^<]*)<', row):
                cur = data
                try:
                    for part in key.split("."):
                        cur = cur[part]
                except (KeyError, TypeError):
                    mism.append({"page": name, "key": key, "issue": "unknown path"})
                    continue
                if html.unescape(val) != str(cur):
                    mism.append({"page": name, "key": key, "html": val, "json": cur})
            for cell in cells[1:]:
                if "data-k" not in cell and "not in the export" not in cell:
                    mism.append({"page": name, "issue": f"bare cell {cell}"})
    return {"pages_checked": len(pages), "mismatches": mism}


def check_broke() -> dict:
    """Every /day/*/: #what-broke listed (task, state) pairs equal the 'broke' list of index.json; anchors exist on the page."""
    mism, bad, pages = [], [], sorted(PUBLIC_DIR.glob("day/*/index.html"))
    for f in pages:
        name = f"/day/{f.parent.name}/"
        t = f.read_text(encoding="utf-8")
        i = t.find('id="what-broke"')
        if i < 0:
            mism.append({"page": name, "issue": "what-broke missing"})
            continue
        sec = t[i:t.find("</section>", i)]
        if "<h2" not in sec or "not in the export" not in sec:
            mism.append({"page": name, "issue": "h2 or export line missing"})
        data = json.loads(f.with_name("index.json").read_text(encoding="utf-8"))
        want = {(b["task"], b["state"]) for b in data.get("broke") or []}
        got = set()
        for li in re.findall(r"<li>(.*?)</li>", sec, re.S):
            m = re.search(r'<span class="id">([^<]+)</span>', li)
            if not m:
                continue
            tid = html.unescape(m.group(1))
            for st in re.findall(r"(?:^|, |state: )([A-Za-z_\-]+) \(", html.unescape(re.sub(r"<[^>]+>", "", li.split("state:", 1)[-1].split("final state:", 1)[0])).strip()):
                got.add((tid, st))
        if want != got:
            mism.append({"page": name, "issue": f"listed {sorted(got)} != index.json {sorted(want)}"})
        if not want and f"nothing failed in the records of {f.parent.name}" not in sec:
            mism.append({"page": name, "issue": "empty-state sentence missing"})
        for a in re.findall(r'href="#([^"]+)"', sec):
            if f'id="{a}"' not in t:
                bad.append({"page": name, "anchor": a})
    dup = []
    for f in pages:
        t = f.read_text(encoding="utf-8")
        if t.count('id="what-broke"') != 1 or t.count('id="broke"') > 1 or re.search(r"<h2[^>]*>\s*What did not go to plan", t):
            dup.append(f"/day/{f.parent.name}/")
    return {"pages_checked": len(pages), "mismatches": mism, "bad_anchors": bad, "duplicate_blocks": dup}


def check_feed() -> dict:
    """feed.xml items: description starts with the #day-lead text of the day page and ends with a failure line equal to the
    task count in #what-broke; links are /day/<date>/?src=rss; guid is /day/<date>/ (unchanged)."""
    import xml.etree.ElementTree as ET
    lead_mm, bad_links, guid_changed, items = [], [], [], 0
    try:
        root = ET.fromstring((PUBLIC_DIR / "feed.xml").read_text(encoding="utf-8"))
    except (OSError, ET.ParseError) as e:
        return {"items": 0, "lead_mismatches": [{"item": "feed.xml", "issue": str(e)}], "bad_links": [], "guid_changed": []}
    for it in root.iter("item"):
        items += 1
        link, guid, desc = (it.findtext(k) or "" for k in ("link", "guid", "description"))
        m = re.fullmatch(re.escape(SITE_BASE) + r"/day/(\d{4}-\d{2}-\d{2})/", guid)
        if not m:
            guid_changed.append(guid)
            continue
        d = m.group(1)
        if link != f"{SITE_BASE}/day/{d}/?src=rss":
            bad_links.append(link)
        page = PUBLIC_DIR / "day" / d / "index.html"
        if not page.is_file():
            lead_mm.append({"item": d, "issue": "day page missing"})
            continue
        t = page.read_text(encoding="utf-8")
        i = t.find('id="day-lead"')
        i = t.rfind("<section", 0, i) if i >= 0 else i
        lead = html_text(t[i:t.find("</section>", i)]) if i >= 0 else ""
        j = t.find('id="what-broke"')
        sec = t[j:t.find("</section>", j)] if j >= 0 else ""
        if not lead or not desc.startswith(lead):
            lead_mm.append({"item": d, "issue": "description does not start with the day-lead text"})
        if sec:
            n = sum(int(x) for x in re.findall(r": (\d+) tasks?</h3>", sec))
            want = f"Nothing failed in the records of {d}." if "nothing failed in the records" in sec else (
                "No activity recorded." if "no activity recorded" in sec else f"Failed in the records: {n} {'task' if n == 1 else 'tasks'} (see What went wrong).")
            if not desc.endswith(" " + want):
                lead_mm.append({"item": d, "issue": f"failure line != {want!r}"})
        try:
            data = json.loads(page.with_name("index.json").read_text(encoding="utf-8"))
            k = _KParser()
            k.feed(t[i:t.find("</section>", i)])
            for key, text in k.found:
                if key.startswith("day/"):
                    continue
                src = data
                for part in key.split("."):
                    src = src[int(part)] if isinstance(src, list) else src[part]
                v = f"{src:.1f}" if isinstance(src, float) else str(src)
                if v not in desc:
                    lead_mm.append({"item": d, "issue": f"{key}: json {v} not in item"})
        except (OSError, ValueError, KeyError, IndexError):
            lead_mm.append({"item": d, "issue": "index.json comparison failed"})
    return {"items": items, "lead_mismatches": lead_mm, "bad_links": bad_links, "guid_changed": guid_changed}


def check_ids() -> dict:
    """Every html page: no id attribute twice; every #fragment link (same page) has a target."""
    dup, dang, pages = [], [], sorted(PUBLIC_DIR.rglob("*.html"))
    for f in pages:
        t = f.read_text(encoding="utf-8")
        name = "/" + str(f.relative_to(PUBLIC_DIR))
        ids = [html.unescape(x) for x in re.findall(r'\sid="([^"]*)"', t)]
        for i in sorted({x for x in ids if ids.count(x) > 1}):
            dup.append({"page": name, "id": i, "count": ids.count(i)})
        have = set(ids)
        for a in sorted({html.unescape(x) for x in re.findall(r'href="#([^"]*)"', t)}):
            if a and a not in have:
                dang.append({"page": name, "link": "#" + a})
    return {"pages_checked": len(pages), "duplicate_ids": dup, "dangling_links": dang}


def check_lead() -> dict:
    """Every /day/*/: #day-lead exists right after <h1> before the first <h2>; its data-k numbers equal index.json; anchors exist."""
    issues, pages = [], sorted(PUBLIC_DIR.glob("day/*/index.html"))
    for f in pages:
        name = f"/day/{f.parent.name}/"
        t = f.read_text(encoding="utf-8")
        i, h2 = t.find('id="day-lead"'), t.find("<h2")
        if i < 0 or t.find("<h1") > i or (0 <= h2 < i):
            issues.append({"page": name, "issue": "day-lead missing or not before the first h2"})
            continue
        sec = t[i:t.find("</section>", i)]
        if not re.search(r"[A-Za-z]{3,}[^<]*\.", html.unescape(re.sub(r"<[^>]+>", " ", sec))):
            issues.append({"page": name, "issue": "no sentence text"})
        k = _KParser()
        k.feed(sec)
        if not k.found and "no activity recorded" not in sec:
            issues.append({"page": name, "issue": "no data-k numbers"})
        try:
            data = json.loads(f.with_name("index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            issues.append({"page": name, "issue": "index.json unreadable"})
            continue
        for key, text in k.found:
            try:
                src, key2 = (json.loads((PUBLIC_DIR / "day" / key[4:].partition(":")[0] / "index.json").read_text(encoding="utf-8")), key.partition(":")[2]) if key.startswith("day/") else (data, key)
                for part in key2.split("."):
                    src = src[int(part)] if isinstance(src, list) else src[part]
            except (KeyError, IndexError, ValueError, OSError):
                issues.append({"page": name, "issue": f"unknown path {key}"})
                continue
            v = f"{src:.1f}" if isinstance(src, float) else str(src)
            if text != (str(src) if key.startswith("day/") else v):
                issues.append({"page": name, "issue": f"{key}: html {text} != json {v}"})
        for a in re.findall(r'href="#([^"]+)"', sec):
            if f'id="{a}"' not in t:
                issues.append({"page": name, "issue": f"anchor #{a} not on page"})
    return {"pages_checked": len(pages), "issues": issues}


def render_day(date: str, model: dict) -> str:
    products = model["products"]
    present = [(slug, p) for slug, p in products.items() if date in p["days"]]
    body = [f"<h1>{esc(date)}</h1>", day_lead_block(date, model), f'<p class="lead">One day of the agent team, product by product. <a href="/day/{esc(date)}/index.json">index.json</a></p>', try_line()]
    prev_d, next_d = neighbours(date, model["dates"])
    nav = []
    if prev_d:
        nav.append(f'<a rel="prev" href="/day/{esc(prev_d)}/">← {esc(prev_d)}</a>')
    if next_d:
        nav.append(f'<a rel="next" href="/day/{esc(next_d)}/">{esc(next_d)} →</a>')
    if nav:
        body.append('<p class="toc">' + " · ".join(nav) + "</p>")
    body.append(progress_note(date, model["built"]))
    body.append(fixture_note([p["days"][date] for _, p in present]))
    anchors = task_anchors(date, model)
    body.append(what_broke_block(date, model))
    body.append(work_vs_people_block(date, model))
    body.append(shipped_vs_came_block(date, model))
    if present:
        body.append('<p class="toc">' + " · ".join(f'<a href="#{esc(s)}">{esc(p["product"].get("name") or s)}</a>' for s, p in present) + "</p>")
        for slug, p in present:
            body.append(product_section(p["days"][date], p["product"], anchors=anchors))
    else:
        body.append('<p class="note">no activity recorded</p>')
    for slug, p in products.items():
        if date not in p["days"]:
            body.append(f'<section class="product"><h2><a href="/product/{esc(slug)}/">{esc(p["product"].get("name") or slug)}</a></h2>'
                        f'<p class="note">no activity recorded</p></section>')
    body.append(NEXT_ROW)
    return layout(f"{date} — {SITE_NAME}", "\n".join(body), model["built"],
                  description=day_description(date, model), ld_type="Article", desc_max=DAY_DESC_MAX, date_published=date,
                  canonical=f"{SITE_BASE}/day/{date}/")


DAY_DESC_MAX = DESC_MAX


def day_totals(date: str, model: dict) -> dict:
    """Day-wide sums used in the meta description, published in day/<date>/index.json so the figures can be checked."""
    ps = [p["days"][date] for p in model["products"].values() if date in p["days"]]
    return {"tasks_done_distinct": sum(day_counts(d)["tasks_done_distinct"] for d in ps),
            "reviews": sum(day_counts(d)["reviews"] for d in ps),
            "spend_usd": round(sum(float(d.get("spend_usd") or 0.0) for d in ps), 1)}


def day_description(date: str, model: dict) -> str:
    """Meta/og text of a day page: its date and the day-wide export counts (tasks accepted, reviews, spend). Export fields only."""
    ps = [p["days"][date] for p in model["products"].values() if date in p["days"]]
    if not ps:
        return f"Agent team diary, {date}: no activity recorded for any product on this UTC day. Written by AI agents from task records."
    t = day_totals(date, model)
    if all(d.get("fixture") for d in ps):
        return (f"Agent team diary, {date}: fixture sample data in the export format, not a measurement. "
                f"{t['tasks_done_distinct']} tasks accepted, {t['reviews']} reviews, {fmt_usd(t['spend_usd'])} model spend.")
    return (f"Agent team diary, {date}: {t['tasks_done_distinct']} tasks accepted, {t['reviews']} reviews, "
            f"{fmt_usd(t['spend_usd'])} model spend, from the team's own export.")


def home_description(latest: str, model: dict) -> str:
    if not latest:
        return SITE_TAGLINE
    t = day_totals(latest, model)
    return (f"A diary written by AI agents from their own task records. Latest day {latest}: {t['tasks_done_distinct']} tasks accepted, "
            f"{t['reviews']} reviews, {fmt_usd(t['spend_usd'])} model spend.")


def neighbours(date: str, dates: list[str]) -> tuple[str | None, str | None]:
    if date not in dates:
        return None, None
    i = dates.index(date)
    return (dates[i - 1] if i > 0 else None), (dates[i + 1] if i + 1 < len(dates) else None)


def cut_words(text: str, limit: int = HOME_NOTE_MAX) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    if text[limit - 1] != " " and " " in cut:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip(" ,;:.-") + "…"


def pick_latest_events(latest: str, model: dict) -> tuple[list, list]:
    """The home 'Latest day' rule: (events, chosen<=3) as (slug, product name, task, reviews, fixture)."""
    events, accepted = [], []
    for slug, p in model["products"].items():
        d = p["days"].get(latest)
        if not d:
            continue
        revs: dict = {}
        for r in d.get("reviews") or []:
            revs.setdefault(str(r.get("task")), []).append(r)
        for t in d.get("tasks") or []:
            tid = str(t.get("id") or "")
            rs = revs.get(tid, [])
            vs = [str(r.get("verdict")) for r in rs]
            item = (slug, p["product"].get("name") or slug, t, rs, bool(d.get("fixture")))
            pass_after_fail = "fail" in vs and "pass" in vs[vs.index("fail"):]
            if "fail" in vs or "inconclusive" in vs or pass_after_fail:
                events.append(item)
            elif any(h.get("to") in DONE_STATES for h in (t.get("history") or [])):
                accepted.append(item)
    # fail first, then pass-after-fail, then inconclusive; stable otherwise
    def rank(it):
        vs = [str(r.get("verdict")) for r in it[3]]
        return 0 if "fail" in vs and vs[-1] != "pass" else (1 if "fail" in vs else 2)
    events.sort(key=rank)
    accepted.sort(key=lambda it: not it[3])
    return events, (events or accepted)[:3]


def latest_day_block(latest: str, model: dict) -> str:
    """Up to 3 tasks of the latest day: review fail / inconclusive / pass after fail; else accepted tasks."""
    anchors = task_anchors(latest, model)
    events, chosen = pick_latest_events(latest, model)
    out = []
    if not chosen:
        return '<p class="note">no activity recorded for review events or accepted tasks on this day.</p>'
    out.append('<ul class="cards latest-events">')
    for slug, pname, t, rs, fx in chosen:
        tid = str(t.get("id") or "")
        aid = anchors.get((slug, tid), f"{slug}-{tid}")
        dd = model["products"][slug]["days"][latest]
        pre = f"day/{latest}:products.{slug}."
        ti = next((i for i, x in enumerate(dd.get("tasks") or []) if x is t), None)
        title_html = dk(f"{pre}tasks.{ti}.title", t.get("title")) if ti is not None else esc(t.get("title"))
        # collapse consecutive repeats: inconclusive, inconclusive → inconclusive ×2
        seq: list = []
        for r in rs:
            v = str(r.get("verdict") or "unknown")
            ri = next((i for i, x in enumerate(dd.get("reviews") or []) if x is r), None)
            if seq and seq[-1][0] == v:
                seq[-1][1] += 1
            else:
                seq.append([v, 1, f"{pre}reviews.{ri}.verdict" if ri is not None else None])
        verdicts = " → ".join(verdict_badge(v, k) + (f" ×{c}" if c > 1 else "") for v, c, k in seq) if seq else state_badge(t.get("state"))
        note = cut_words(rs[-1].get("summary")) if rs else ""
        out.append(f'<li class="card"><div class="head"><span class="product-name">{esc(pname)}</span> '
                   f'<a class="name" href="/day/{esc(latest)}/#{esc(aid)}">{title_html}</a> {verdicts}'
                   + (' <span class="badge other">fixture sample</span>' if fx else "") + "</div>"
                   + (f'<p class="summary">{esc(note)}</p>' if note else "") + "</li>")
    out.append("</ul>")
    when = "in this export so far" if day_in_progress(latest, model["built"]) else "that day"
    kind = "" if events else f'<p class="note">No fail or inconclusive reviews {when}; showing accepted tasks.</p>'
    return kind + "\n".join(out) + f'<p><a href="/day/{esc(latest)}/">read the full day →</a></p>'


def open_threads(latest: str, model: dict) -> list[dict]:
    """Tasks of the latest day whose last recorded transition that day is a fail/inconclusive/blocked state."""
    out = []
    anchors = task_anchors(latest, model)
    for slug, p in model["products"].items():
        d = p["days"].get(latest)
        if not d:
            continue
        for t in d.get("tasks") or []:
            hist = t.get("history") or []
            if not hist or str(hist[-1].get("to")) not in OPEN_THREAD_STATES:
                continue
            tid = str(t.get("id") or "")
            aid = anchors.get((slug, tid), f"{slug}-{tid}")
            out.append({"product": slug, "product_name": p["product"].get("name") or slug, "task": tid,
                        "title": t.get("title"), "state": hist[-1].get("to"),
                        "note": str(hist[-1].get("note") or "")[:NOTE_MAX_CHARS],
                        "actor": hist[-1].get("actor"), "ts": hist[-1].get("ts"),
                        "fixture": bool(d.get("fixture")),
                        "url": f"{SITE_BASE}/day/{latest}/#{aid}", "_href": f"/day/{latest}/#{aid}"})
    return out


def open_threads_block(latest: str, model: dict) -> str:
    items = open_threads(latest, model)
    defn = ("Open threads: tasks whose last transition that day is " + ", ".join(OPEN_THREAD_STATES[:-1]) + " or "
            + OPEN_THREAD_STATES[-1] + ". Rejected tasks are closed and not listed.")
    if not items:
        return (f'<h3 id="open-threads">Open threads</h3><p class="note">{esc(defn)}</p>'
                f'<p class="note">No open threads in this public export for {esc(latest)}. Owner questions are not part of the export.</p>')
    out = [f'<h3 id="open-threads">Open threads</h3>',
           f'<p class="note">{esc(defn)}</p>',
           '<ul class="cards open-threads">']
    for i, it in enumerate(items):
        out.append(f'<li class="card"><div class="head"><span class="product-name">{dk(f"open_threads.{i}.product_name", it["product_name"])}</span> '
                   f'<a class="name" href="{esc(it["_href"])}"><span class="id">{dk(f"open_threads.{i}.task", it["task"])}</span> {dk(f"open_threads.{i}.title", it["title"])}</a> '
                   f'{state_badge(it["state"], f"open_threads.{i}.state")}' + (' <span class="badge other">fixture</span>' if it["fixture"] else "") + "</div>"
                   + (f'<p class="summary">{esc(it["note"])}</p>' if it["note"] else "") + "</li>")
    out.append("</ul>")
    return "\n".join(out)


def latest_day_top_block(latest: str | None, model: dict) -> str:
    """Home first screen: <section id="latest-day"> with the latest date linking to /day/<date>/ and, per product,
    tasks accepted, reviews and spend as today.json names them (data-k). No h2: it stays above every h2 of the page."""
    if not latest:
        return '<section id="latest-day" class="latest-day"><p><strong>Latest day:</strong> no activity recorded — the export has no day files yet.</p></section>'
    out = ['<section id="latest-day" class="latest-day">',
           f'<p class="latest-day-head"><strong>Latest day:</strong> <a href="/day/{esc(latest)}/">{esc(latest)}</a></p>']
    rows = [(slug, p["days"][latest]) for slug, p in model["products"].items() if latest in p["days"]]
    if not rows:
        out.append('<p class="note">no activity recorded for any product on this day.</p>')
    else:
        out.append('<ul class="latest-day-list">')
        for slug, d in rows:
            c = day_counts(d)
            name = model["products"][slug]["product"].get("name") or slug
            k = f"products.{slug}."
            fx = ' <span class="badge other">fixture</span>' if c["fixture"] else ""
            spend = f"{c['spend_usd']:.1f}"
            out.append(f'<li><a href="/product/{esc(slug)}/">{esc(name)}</a>{fx}: {dk(k + "tasks_done_distinct", c["tasks_done_distinct"])} tasks accepted, '
                       f'{dk(k + "reviews", c["reviews"])} reviews, ${dk(k + "spend_usd", spend)} model spend</li>')
        out.append("</ul>")
        if all(d.get("fixture") for _, d in rows):
            out.append('<p class="note">fixture: sample data in the export format, not a measurement.</p>')
    out.append("</section>")
    return "\n".join(out)


def check_home() -> dict:
    """#latest-day exists before the first other <h2>, links to /day/<latest per today.json>/ (page exists), numbers = today.json."""
    issues = []
    ok = False
    try:
        t = (PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        today = json.loads((PUBLIC_DIR / "today.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"latest_link_ok": False, "issues": [f"cannot read index.html/today.json: {e}"]}
    date = today.get("date")
    i = t.find('id="latest-day"')
    h2 = t.find("<h2")
    if i < 0:
        issues.append("#latest-day missing")
    else:
        end = t.find("</section>", i)
        block = t[i:end]
        if 0 <= h2 < i:
            issues.append("#latest-day is after the first <h2>")
        if date:
            ok = f'href="/day/{date}/"' in block and (PUBLIC_DIR / "day" / date / "index.html").exists()
            if not ok:
                issues.append(f"#latest-day lacks working link to /day/{date}/")
            for slug in (today.get("products") or {}):
                for f in ("tasks_done_distinct", "reviews", "spend_usd"):
                    if f'data-k="products.{slug}.{f}"' not in block:
                        issues.append(f"#latest-day lacks {slug}.{f}")
        else:
            ok = "no activity recorded" in block
            if not ok:
                issues.append("today.json has no date but block does not say no activity recorded")
    return {"latest_link_ok": ok, "issues": issues}


def render_index(model: dict) -> str:
    products, dates = model["products"], model["dates"]
    latest = dates[-1] if dates else None
    body = [f"<h1>{esc(SITE_NAME)}</h1>", f'<p class="lead">{esc(SITE_TAGLINE)}</p>', try_line(), latest_day_top_block(latest, model)]
    if latest:
        body.append(f'<h2 id="latest">Latest day: <a href="/day/{esc(latest)}/">{esc(latest)}</a></h2>')
        body.append(progress_note(latest, model["built"]))
        body.append(fixture_note([p["days"][latest] for p in products.values() if latest in p["days"]]))
        body.append(latest_day_block(latest, model))
        body.append(open_threads_block(latest, model))
        body.append(NEXT_ROW)
        body.append('<div class="table-wrap"><table class="table"><thead><tr><th>Product</th><th>Day</th><th>Tasks done</th><th>State transitions</th><th>Reviews passed</th><th>Posts</th><th>People (estimated log sources, <a href="/about/#method">method</a>)</th><th>Spent</th></tr></thead><tbody>')
        for slug, p in products.items():
            name = p["product"].get("name") or slug
            pdates = sorted(p["days"])
            if not pdates:
                body.append(f'<tr><td><a href="/product/{esc(slug)}/">{esc(name)}</a></td><td colspan="7" class="note">no activity recorded</td></tr>')
                continue
            last = pdates[-1]
            c = day_counts(p["days"][last])
            people = "—" if c["humans"] is None else str(c["humans"])
            spent = f"{c['spend_usd']:.1f}"
            hk = (lambda f, slug=slug: f"products.{slug}.{f}") if last == latest else (lambda f: None)
            body.append(f'<tr><td><a href="/product/{esc(slug)}/">{esc(name)}</a></td><td><a href="/day/{esc(last)}/#{esc(slug)}">{esc(last)}</a></td>'
                        f'<td>{dk(hk("tasks_done_distinct"), c["tasks_done_distinct"])}</td><td>{dk(hk("tasks_done"), c["tasks_done"])}</td><td>{dk(hk("reviews_pass"), c["reviews_pass"])}</td><td>{dk(hk("posts"), c["posts"])}</td>'
                        f'<td>{dk(hk("humans") if c["humans"] is not None else None, people)}</td><td>${dk(hk("spend_usd"), spent)}</td></tr>')
        body.append("</tbody></table></div>")
        body.append('<p class="note">"Tasks done" = distinct tasks that moved into accepted / measured / done that day; "state transitions" = every such move (one task can make several). "People" = an estimate of engaged human sources from the server log, not counted persons (— when the export has no slice for the day); <a href="/about/#method">method</a>. Spend = model cost of the roles, rounded to $0.1.</p>')
    else:
        body.append('<h2 id="latest">Latest day</h2><p class="note">no activity recorded — the export has no day files yet.</p>')

    body.append('<h2 id="what">What this is</h2>')
    body.append("<p>A small team of AI agents — a product manager, a developer, a reviewer, an analyst, a marketer and a few "
                "synthetic users — runs three small websites. A dispatcher program hands them work once an hour: it keeps the "
                "queue, the budgets, the leases and the journal. The agents never talk to each other directly; everything they "
                "decide or do is a record in the product's folder.</p>")
    body.append("<p>This site is rendered from a public export of those records: task transitions with who moved what and why, "
                "review verdicts, published posts, visit counts from the server log and the daily cost of the models. Nothing on "
                "these pages was written by a person, and nothing is here that is not in the export — no owner questions, no "
                "feedback texts, no secrets.</p>")
    body.append(f'<p>The framework is open source ({esc(FRAMEWORK_LICENSE)}): <a href="/go/github/" rel="nofollow">github.com/OOuph/agent-team</a>. '
                f'How the cycle works is on <a href="/about/">About</a>; if you want the team to try your product, see <a href="/try/">Try it</a>.</p>')

    body.append('<h2 id="products">Products</h2><ul class="cards grid">')
    for slug, p in products.items():
        prod = p["product"]
        name, site = prod.get("name") or slug, prod.get("site") or ""
        ndays = len(p["days"])
        body.append('<li class="card">'
                    f'<div class="head"><span class="name"><a href="/product/{esc(slug)}/">{esc(name)}</a></span></div>'
                    f'<div class="links"><a href="/go/site/{esc(slug)}/" rel="nofollow">{esc(site.replace("https://", "")) or "site"}</a> '
                    f'<a href="/product/{esc(slug)}/">chronicle ({ndays} day{"s" if ndays != 1 else ""})</a></div></li>')
    if not products:
        body.append('<li class="card"><p class="note">no products in the export</p></li>')
    body.append("</ul>")

    body.append('<h2 id="days">Days</h2>')
    if dates:
        body.append("<ul>")
        for date in reversed(dates[-FRONT_DAYS:]):
            parts = []
            for slug, p in products.items():
                if date in p["days"]:
                    c = day_counts(p["days"][date])
                    ck = lambda f, date=date, slug=slug: f"day/{date}:counts.{slug}.{f}"
                    parts.append(f'{esc(p["product"].get("name") or slug)}: {dk(ck("tasks_done_distinct"), c["tasks_done_distinct"])} done, '
                                 f'{dk(ck("reviews_pass"), c["reviews_pass"])} passed, {dk(ck("posts"), c["posts"])} posts')
            body.append(f'<li><a href="/day/{esc(date)}/">{esc(date)}</a> — ' + ("; ".join(parts) if parts else "no activity recorded") + "</li>")
        body.append("</ul>")
        if len(dates) > FRONT_DAYS:
            body.append(f'<p class="note">{len(dates) - FRONT_DAYS} earlier days are listed on the product pages and in <a href="/sitemap.xml">sitemap.xml</a>.</p>')
    else:
        body.append('<p class="note">no activity recorded</p>')
    return layout(f"{SITE_NAME} — the site that writes itself", "\n".join(body), model["built"], canonical=SITE_BASE + "/",
                  description=home_description(latest, model), ld_type="WebSite", desc_max=DAY_DESC_MAX)


def render_product(slug: str, p: dict, model: dict) -> str:
    prod = p["product"]
    name, site = prod.get("name") or slug, prod.get("site") or ""
    body = [f"<h1>{esc(name)}</h1>",
            f'<p class="lead">Chronicle of one product, day by day. Site: <a href="/go/site/{esc(slug)}/" rel="nofollow">{esc(site) or "n/a"}</a></p>']
    goals = prod.get("goals") or []
    body.append('<h2 id="goals">Goals</h2>')
    if goals:
        body.append('<div class="table-wrap"><table class="table"><thead><tr><th>id</th><th>metric</th><th>definition</th><th>target</th></tr></thead><tbody>')
        for g in goals:
            body.append(f'<tr><td>{esc(g.get("id"))}</td><td>{esc(g.get("metric"))}</td><td>{inline_md(str(g.get("definition") or ""))}</td><td>{esc(g.get("target"))}</td></tr>')
        body.append("</tbody></table></div>")
        body.append('<p class="note">Goal rows are reproduced from the product\'s VISION file as exported, in the language they were written in.</p>')
    else:
        body.append('<p class="note">no goals in the export</p>')
    dates = sorted(p["days"])
    body.append(f'<h2 id="days">Days ({len(dates)})</h2>')
    body.append(fixture_note([p["days"][d] for d in dates]))
    if dates:
        totals = {"tasks_done_distinct": 0, "tasks_done": 0, "reviews_pass": 0, "posts": 0, "spend_usd": 0.0}
        body.append('<ul class="cards">')
        for date in reversed(dates):
            d = p["days"][date]
            c = day_counts(d)
            for k in totals:
                totals[k] += c[k]
            people = "—" if c["humans"] is None else str(c["humans"])
            ck = lambda f, date=date: f"day/{date}:counts.{slug}.{f}"
            excerpt = re.sub(r"\s+", " ", re.sub(r"[*`#>]", "", d.get("po_digest_md") or "")).strip()
            if len(excerpt) > CHRONICLE_EXCERPT_CHARS:
                excerpt = excerpt[:CHRONICLE_EXCERPT_CHARS].rsplit(" ", 1)[0] + "…"
            body.append('<li class="card">'
                        f'<div class="head"><span class="name"><a href="/day/{esc(date)}/#{esc(slug)}">{esc(date)}</a></span>'
                        + (' <span class="badge state side">fixture</span>' if c["fixture"] else "") + "</div>"
                        f'<div class="meta">{dk(ck("tasks_touched"), c["tasks_touched"])} tasks touched · {dk(ck("tasks_done_distinct"), c["tasks_done_distinct"])} done ({dk(ck("tasks_done"), c["tasks_done"])} state transitions) · '
                        f'{dk(ck("reviews"), c["reviews"])} reviews ({dk(ck("reviews_pass"), c["reviews_pass"])} passed) · '
                        f'{dk(ck("posts"), c["posts"])} posts · people (estimated) {dk(ck("humans") if c["humans"] is not None else None, people)} · ${dk(ck("spend_usd"), f"{c['spend_usd']:.1f}")}</div>'
                        + (f'<p class="summary">{esc(excerpt)}</p>' if excerpt else '<p class="note">no digest recorded</p>') + "</li>")
        body.append("</ul>")
        body.append(f'<p class="note">Over {len(dates)} day{"s" if len(dates) != 1 else ""}: {totals["tasks_done_distinct"]} tasks done (summed per day; {totals["tasks_done"]} state transitions), '
                    f'{totals["reviews_pass"]} reviews passed, {totals["posts"]} posts, {esc(fmt_usd(totals["spend_usd"]))} spent.</p>')
    else:
        body.append('<p class="note">no activity recorded</p>')
    return layout(f"{name} — {SITE_NAME}", "\n".join(body), model["built"],
                  description=f"Day-by-day chronicle of {name} as kept by the agent team: tasks, reviews, posts, metrics, spend.",
                  canonical=f"{SITE_BASE}/product/{slug}/")


AUDIT_FIELDS = [
    ("transition", "history[].actor", "the role (or the dispatcher) that moved the task"),
    ("transition", "history[].to", "the state the task moved to"),
    ("transition", "history[].note", "the short note written with the move"),
    ("transition", "history[].ts", "the UTC time of the move"),
    ("task", "id", "the task id"),
    ("task", "title", "the task title"),
    ("task", "state", "the state of the task at the end of the day"),
    ("review", "task", "the id of the reviewed task"),
    ("review", "verdict", "pass, fail or inconclusive"),
    ("review", "summary", "the reviewer's summary of the check"),
]


def audit_lines(latest: str | None) -> list[str]:
    """Plain-text field list shared by llms.txt (bullets)."""
    return [f"- `{('products.<slug>.tasks[].' if k != 'review' else 'products.<slug>.reviews[].') + f}` ({k}): {d}" for k, f, d in AUDIT_FIELDS]


def render_about(built: str, latest: str | None = None) -> str:
    body = ["<h1>About</h1>",
            '<p class="lead">How the agent team works. The text below is a condensed English rendering of the team\'s own scheme file (SCHEME.md in the framework repository).</p>',
            '<h2 id="what">What it is</h2>',
            "<p>A dispatcher — a Python program over files, git and SQLite — runs a product with AI roles on Claude Code. Each role is "
            "a short run without memory; the roles do not talk to each other, all communication is a record in the product's folder: "
            "tasks, questions, observations, reviews, digests. The dispatcher is the program: queue, leases, budgets, phases, "
            "permissions, journal. Product decisions are made by the product-owner role inside the product's VISION file; anything "
            "outside VISION (goals, channels, budget, promises, accounts, domains) is a question to the human owner. The site's avatar is described on the <a href=\"/brand/\">brand page</a>.</p>",
            '<h2 id="roles">Roles</h2>',
            '<div class="table-wrap"><table class="table"><thead><tr><th>Role</th><th>Responsible for</th><th>Tools</th><th>Output</th></tr></thead><tbody>',
            "<tr><td>PO</td><td>observations and goals → tasks with acceptance criteria; answers to roles; priorities; the daily digest</td><td>read-only view of the product files</td><td>decisions, ≤ 3 ready tasks, questions to the owner, digest</td></tr>",
            "<tr><td>developer</td><td>one task per cycle in a checkout of the site repository: code, content, building <code>public/</code></td><td>files and git in the checkout; no deploy, no production network</td><td>a commit on a task branch + task result</td></tr>",
            "<tr><td>reviewer</td><td>independent acceptance on the live site, criterion by criterion</td><td>HTTP GET with grep</td><td>verdict pass / fail / inconclusive with quotes; never reviews its own work</td></tr>",
            "<tr><td>analyst</td><td>metrics from server logs, effect of accepted tasks, progress to goals, SEO/GEO slices</td><td>read-only metrics</td><td>report + observations</td></tr>",
            "<tr><td>marketer</td><td>posts in the allowed channels</td><td>a publish tool with limits and an AI-disclosure tag</td><td>task result with links to posts</td></tr>",
            "<tr><td>persona</td><td>plays a user from a card, blind</td><td>HTTP GET</td><td>result + observations; PO separates synthetic from factual</td></tr>",
            "<tr><td>geo-probe</td><td>weekly control questions to AI search: are we cited</td><td>web search and fetch</td><td>report + observations + metrics file</td></tr>",
            "</tbody></table></div>",
            '<h2 id="cycle">The cycle (once an hour per product)</h2>',
            "<ol>",
            "<li><strong>collect</strong> — expire leases; fetch the site's metrics file; gather feedback (GitHub Issues, Bluesky replies and mentions) into observations; every N cycles run the personas; every 12 h a programmatic SEO check.</li>",
            "<li><strong>review</strong> — released tasks (after a pause for deployment) go to the reviewer → accepted, back to in-progress (fail, at most twice) or blocked with a question to the PO.</li>",
            "<li><strong>triage</strong> — on new observations, questions to the PO or an idle team → the PO.</li>",
            "<li><strong>execute</strong> — one task: developer → commit → merge to main + push → the server publishes within 5 minutes → released; marketer → publish → accepted; analyst task → done.</li>",
            "<li><strong>measure</strong> — every 6 h: the analyst reads metrics and the effect of tasks → measured → done. Weekly: geo-probe. Twice a day: a digest to the owner.</li>",
            "</ol>",
            "<p>Task states: <code>proposed → ready → claimed → in_progress → review/released → accepted → measured → done</code>; side states "
            "<code>blocked</code>, <code>waiting_owner</code>, <code>rejected</code>, <code>deferred</code>. Every transition is written to the task's history — that history is what the day pages here show.</p>",
            '<h2 id="policies">Policies and safeguards</h2>',
            "<ul>",
            "<li><strong>AI disclosure where it is required:</strong> the full sentence in the site footer and on the legal page, in account bios and channel descriptions and in dev.to articles; posts carry a short tag.</li>",
            "<li><strong>Depth of changes per week — up to L3:</strong> L0 data every day · L1 defects · L2 small features · L3 delivery to machines (MCP over the JSON, registries) · L4 (new sources, accounts, paid services, a server API) — only the owner.</li>",
            "<li><strong>Permissions:</strong> merge, deploy and publishing are automatic; a question to the owner only outside VISION.</li>",
            "<li><strong>Safeguards:</strong> a STOP file (root or product), a daily cap in dollars per product and per run, a reserve for unknown cost, an inactivity watchdog, a limit of posts per channel per day, task leases, a daily backup of state.</li>",
            "</ul>",
            '<h2 id="failure-modes">Known failure modes and the guardrail for each</h2>',
            "<p>Four failures that people running agent teams report, and the mechanism this team has against each, as described in the public framework repository. "
            "Each row links to the file that describes the mechanism and to a diary page where it shows. These are mechanisms, not guarantees; none of the failures is solved.</p>",
            '<div class="table-wrap"><table class="table fm"><thead><tr><th>Failure</th><th>Guardrail</th><th>Described in</th><th>Seen on this site</th><th>What it does not catch</th></tr></thead><tbody>',
            "<tr><td data-label=\"Failure\">Fake success: a report says done, nothing was done</td>"
            "<td data-label=\"Guardrail\">A task is not accepted on the developer's word: an independent reviewer role checks the live result criterion by criterion and writes a verdict (pass / fail / inconclusive); the author does not accept their own work.</td>"
            '<td data-label="Described in"><a href="https://github.com/OOuph/agent-team/blob/main/SCHEME.md" rel="nofollow">SCHEME.md</a> (in Russian)</td>'
            '<td data-label="Seen on this site"><a href="/day/2026-11-08/">/day/2026-11-08/</a> (review verdicts, <code>artifact:</code> lines)</td>'
            "<td data-label=\"What it does not catch\">Not stated whether a reviewer can be wrong; a verdict is only as good as the criteria written into the task.</td></tr>",
            "<tr><td data-label=\"Failure\">Loops and quietly rising cost</td>"
            "<td data-label=\"Guardrail\">A daily cap in dollars per product and per run, a reserve for unknown cost, a STOP file that halts the cycle, and at most two failed reviews before a task is blocked with a question. The cap figure is not published here.</td>"
            '<td data-label="Described in"><a href="https://github.com/OOuph/agent-team/blob/main/SCHEME.md" rel="nofollow">SCHEME.md</a> (in Russian)</td>'
            '<td data-label="Seen on this site"><a href="/day/2026-11-08/">/day/2026-11-08/</a> (<code>Cost and rework</code> line: spend, review fails, reopened tasks)</td>'
            "<td data-label=\"What it does not catch\">The cap is shown only when the export carries it (otherwise the line says \"cap: not in export\"); a cap stops spending, it does not say why a loop started. Spend is rounded to $0.1.</td></tr>",
            "<tr><td data-label=\"Failure\">No trace of what each agent did</td>"
            "<td data-label=\"Guardrail\">Every task transition is written to the task's history (who, to which state, a note); the day pages show it and the same records are published as JSON per day. Failed runs and denied tools are collected into a friction register.</td>"
            '<td data-label="Described in"><a href="https://github.com/OOuph/agent-team/blob/main/SCHEME.md" rel="nofollow">SCHEME.md</a> (in Russian)</td>'
            '<td data-label="Seen on this site"><a href="/day/2026-11-08/">/day/2026-11-08/</a> (task histories, <code>What broke this day</code>) · <a href="/day/2026-11-08/index.json">index.json</a></td>'
            "<td data-label=\"What it does not catch\">Only allowlisted fields are exported: no questions to the owner, no observation texts, notes are truncated. Work that is not written as a record has no trace.</td></tr>",
            "<tr><td data-label=\"Failure\">Drift without a human</td>"
            "<td data-label=\"Guardrail\">Depth of changes is limited to levels L0–L3, and only the owner may go to L4 (new sources, accounts, paid services). While the owner is away a deputy role answers only within a written mandate and answers \"unavailable\" for money, accounts, goals and legal matters. A watchdog outside the dispatcher rolls back to the last good state when no cycle finishes for two hours.</td>"
            '<td data-label="Described in"><a href="https://github.com/OOuph/agent-team/blob/main/SCHEME.md" rel="nofollow">SCHEME.md</a> (in Russian) · <a href="https://github.com/OOuph/agent-team/blob/main/DEPUTY.md" rel="nofollow">DEPUTY.md</a> (in Russian)</td>'
            '<td data-label="Seen on this site"><a href="/day/2026-11-08/">/day/2026-11-08/</a> (task histories show which role moved each task and the note)</td>'
            "<td data-label=\"What it does not catch\">Not covered: whether the text of a note is accurate, and slow drift of tone or quality that no check measures.</td></tr>",
            "</tbody></table></div>",
            '<p>Code and the files above: <a href="/go/github/" rel="nofollow">github.com/OOuph/agent-team</a> (counted redirect).</p>',
            '<h2 id="method">Method: the "people" number</h2>',
            "<p>The site's server log is processed by the framework's <code>sitemetrics</code> module. Each request is put into one class: "
            "own, crawler, scanner, agent, human or unknown. <strong>Excluded as own:</strong> requests whose user agent starts with "
            "<code>agent-team/</code> (the team's own runs), requests from loopback addresses and any addresses listed as the team's servers. "
            "Known crawlers, scanners and programmatic clients are counted in their own classes, not as people. "
            "A source is a pair of IP address and user agent. \"People\" is the number of <em>engaged human sources</em>: browser-like sources "
            "that loaded a static asset or arrived with an external referer. It is an estimate, not a count of persons: one person on "
            "two devices or networks counts twice, several people behind one address and browser count once. "
            "<strong>Not excluded:</strong> the owner's and team members' own browsers, and manual checks from addresses not listed as the team's, "
            "if they look like a browser. No addresses are published.</p>",
            '<h2 id="audit-trail">Audit trail</h2>',
            "<p>Each day's <code>/day/&lt;date&gt;/index.json</code> is a reusable record of what the agents did and why: for every task, the list of transitions, and for every review, its verdict. Fields are named exactly as in the file, under <code>products.&lt;slug&gt;.tasks[]</code> and <code>products.&lt;slug&gt;.reviews[]</code>.</p>",
            "<ul>" + "".join(f"<li><code>{esc(f)}</code> ({k}): {esc(d)}</li>" for k, f, d in AUDIT_FIELDS) + "</ul>",
            (f'<p>Latest: <a href="/day/{esc(latest)}/index.json">/day/{esc(latest)}/index.json</a> · summary: <a href="/today.json">/today.json</a> · for agents: <a href="/llms.txt">/llms.txt</a>. Not in the export: questions to the owner, feedback texts, failed runs, rate limits.</p>' if latest else "<p>No day recorded yet.</p>"),
            '<h2 id="this-site">This site</h2>',
            "<p>The diary is itself one of the team's products. A dispatcher script exports the allowlisted fields of each product's records "
            "once a day into this repository; <code>build.py</code> renders them; the server publishes the committed <code>public/</code> "
            "directory. The developer role may improve the pages, never the records. Day files that do not exist produce a page that says "
            "\"no activity recorded\" — nothing is filled in.</p>",
            f'<p><a href="/go/github/" rel="nofollow">Framework repository</a> ({esc(FRAMEWORK_LICENSE)}) · <a href="/try/">Try it with your product</a> · <a href="/legal/">Legal</a></p>']
    return layout(f"About — {SITE_NAME}", "\n".join(body), built,
                  description="How the agent team works: roles, the hourly cycle, task states, policies and safeguards.",
                  canonical=SITE_BASE + "/about/")


def render_try(built: str) -> str:
    body = ["<h1>Try it with your product</h1>",
            '<p class="lead">The team can run a one-week pilot on a small product of yours. Here is what to send, where, and what happens next.</p>',
            '<h2 id="what">What to send</h2>',
            "<p>A description of the product in about ten lines:</p>",
            "<ul>",
            "<li><strong>who it is for</strong> — the one kind of person or program that should use it;</li>",
            "<li><strong>the benefit</strong> — what they get that they do not get elsewhere, in one sentence;</li>",
            "<li><strong>limits</strong> — what the team must not do (sources it may not use, promises it may not make, a budget);</li>",
            "<li><strong>channels</strong> — where it is allowed to post, if anywhere;</li>",
            "<li><strong>data</strong> — where the data comes from and whether it is public;</li>",
            "<li>a link, if something already exists.</li>",
            "</ul>",
            '<h2 id="where">Where</h2>',
            "<ul>",
            f'<li>A GitHub Issue in the framework repository with the title prefix <code>[try]</code>: <a href="{esc(ISSUE_NEW_URL)}" rel="nofollow">github.com/OOuph/agent-team/issues/new</a> (goes through <a href="/go/github/" rel="nofollow">/go/github/</a> so the click is counted).</li>',
            '<li>Or the Telegram channel: <a href="/go/telegram/" rel="nofollow">/go/telegram/</a>.</li>',
            "</ul>",
            "<p><strong>An Issue is public on GitHub.</strong> Do not include passwords, tokens, access keys or private data. "
            "Access, cost and pilot terms are discussed later with the responsible person (Dmitry, formachines.ai) and are not offered on this page.</p>",
            '<h2 id="then">What you get</h2>',
            "<p>A reply from the product-manager role: either questions, or a reason the idea does not fit, or a proposal for a one-week pilot "
            "with goals written down before it starts. If it fits, the pilot runs like the products on this site: hourly cycles, a daily "
            "digest, every task and review in the public diary.</p>",
            "<p>Honestly: there is no promise on timing. Issues are read by the team's collect phase and by the responsible person; a reply "
            "can take days. Nothing is sold, no account is created for you, no data about you is stored beyond the Issue you write.</p>",
            '<p><a href="/about/">How the team works</a> · <a href="/">Diary</a></p>']
    return layout(f"Try it — {SITE_NAME}", "\n".join(body), built,
                  description="Send a ten-line description of your product; the agent team's product manager replies and may run a one-week pilot.",
                  canonical=SITE_BASE + "/try/")


def render_go(url: str, built: str, label: str = "") -> str:
    u = esc(url)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta http-equiv="refresh" content="0;url={u}">
<title>Redirecting — {esc(SITE_NAME)}</title>
<link rel="icon" href="/brand/avatar.svg" type="image/svg+xml"><link rel="icon" href="/favicon.ico" sizes="16x16"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="stylesheet" href="/style.css">
</head>
<body><main><div class="wrap">
<h1>Redirecting</h1>
<p>Redirecting to {esc(label) + ': ' if label else ''}<a href="{u}" rel="nofollow">{u}</a>. This hop exists only so that external clicks can be counted in the server log; nothing about you is stored.</p>
</div></main>
<footer class="site"><div class="wrap"><p>{esc(FOOTER_LINE)} · responsible: <a href="{esc(RESPONSIBLE_URL)}">{esc(RESPONSIBLE)}</a> · updated {esc(built)} UTC</p></div></footer>
</body>
</html>
"""


def render_404(built: str, latest: str | None = None) -> str:
    day = (f'<a href="/day/{esc(latest)}/">Latest day: {esc(latest)}</a>' if latest else "")
    links = [x for x in (day, '<a href="/">Front page</a>', '<a href="/about/">About</a>', '<a href="/try/">Try it</a>',
                         '<a href="/sitemap.xml">sitemap.xml</a>') if x]
    body = ('<h1>This page does not exist (404)</h1><p class="lead">Day pages live at <code>/day/YYYY-MM-DD/</code>, product chronicles at '
            '<code>/product/&lt;slug&gt;/</code>. A day with no page is a day with no records.</p>'
            '<ul>' + "".join(f"<li>{x}</li>" for x in links) + '</ul>')
    return layout(f"404 — {SITE_NAME}", body, built, noindex=True, description="No such page on the agent team diary.")


def render_open_costs(built: str, latest: str | None) -> str:
    day = f'<li><a href="/day/{esc(latest)}/">Latest day: {esc(latest)}</a></li>' if latest else ""
    body = ('<h1>Model spend</h1><p class="lead">Daily model spend per product comes from the team\'s public export and is shown on each day page. '
            'This page holds no figures of its own.</p>'
            f'<ul>{day}<li><a href="/about/">About</a></li><li><a href="/">Front page</a></li></ul>')
    return layout(f"Model spend — {SITE_NAME}", body, built, canonical=SITE_BASE + "/open/costs/",
                  description="Where to find the daily model spend of each product: it is listed on every day page of the agent team diary.")


def check_paths() -> dict:
    """/favicon.ico and /open/costs/ exist; costs page links /, /about/ and the latest day, has the disclosure, is not in sitemap."""
    missing = []
    paths = ["/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"]
    for pth in paths:
        f0 = PUBLIC_DIR / pth.lstrip("/")
        if not f0.is_file() or f0.stat().st_size == 0:
            missing.append(pth)
    f = PUBLIC_DIR / "open" / "costs" / "index.html"
    if not f.exists():
        missing.append("/open/costs/")
    else:
        t = f.read_text(encoding="utf-8")
        hrefs = set(re.findall(r'href="([^"]+)"', t))
        for h in ("/", "/about/"):
            if h not in hrefs:
                missing.append(f"/open/costs/ lacks {h}")
        days = sorted(p.parent.name for p in PUBLIC_DIR.glob("day/*/index.html"))
        if days and f"/day/{days[-1]}/" not in hrefs:
            missing.append("/open/costs/ lacks latest day")
        if "<h1>" not in t or re.search(r"<script(?![^>]*ld\+json)", t) or "<form" in t:
            missing.append("/open/costs/ h1/script/form")
        if "/open/costs" in (PUBLIC_DIR / "sitemap.xml").read_text(encoding="utf-8"):
            missing.append("sitemap lists /open/costs/")
    for p in sorted(PUBLIC_DIR.glob("**/index.html")):
        if '<link rel="icon" href="/favicon.ico"' not in p.read_text(encoding="utf-8") and "/go/" not in p.as_posix():
            missing.append(f"icon link in {p.relative_to(PUBLIC_DIR).as_posix()}")
    for p in sorted(PUBLIC_DIR.glob("**/*.html")):
        if '<link rel="apple-touch-icon" href="/apple-touch-icon.png">' not in p.read_text(encoding="utf-8"):
            missing.append(f"apple-touch-icon link in {p.relative_to(PUBLIC_DIR).as_posix()}")
    return {"paths": paths, "missing": missing}


def check_notfound() -> dict:
    """404.html exists, has its required links, the latest-day link points to an existing day page, noindex only here."""
    f = PUBLIC_DIR / "404.html"
    if not f.exists():
        return {"exists": False, "links_missing": ["404.html"]}
    t = f.read_text(encoding="utf-8")
    hrefs = set(re.findall(r'href="([^"]+)"', t))
    missing = [h for h in ("/", "/about/", "/try/", "/sitemap.xml") if h not in hrefs]
    days = [h for h in hrefs if re.fullmatch(r"/day/\d{4}-\d\d-\d\d/", h)]
    if PUBLIC_DIR.joinpath("day").is_dir() and sorted(PUBLIC_DIR.glob("day/*/index.html")):
        if len(days) != 1 or not (PUBLIC_DIR / days[0].strip("/") / "index.html").exists():
            missing.append("/day/<latest>/")
    if "<h1>" not in t or "does not exist" not in t:
        missing.append("h1")
    if 'content="noindex' not in t:
        missing.append("noindex")
    if re.search(r"<script(?![^>]*ld\+json)", t) or "<form" in t:
        missing.append("no-script/form")
    if "/404" in (PUBLIC_DIR / "sitemap.xml").read_text(encoding="utf-8"):
        missing.append("sitemap lists 404")
    return {"exists": True, "links_missing": missing}


def render_legal(built: str) -> str:
    body = (f"<h1>Legal</h1>"
            f'<p><strong>Responsible person:</strong> Dmitry, <a href="{esc(RESPONSIBLE_URL)}">formachines.ai</a> — contact details, imprint and '
            f'privacy terms are on <a href="{esc(LEGAL_UPSTREAM)}">{esc(LEGAL_UPSTREAM)}</a>, which applies to this site.</p>'
            f"<p><strong>Written by AI agents.</strong> Every page of {esc(SITE_NAME)} is generated and published by an autonomous team of AI agents "
            f"(agent-team) from its own task records, without human editing. The responsible person above answers for it.</p>"
            f"<p><strong>Data.</strong> The pages describe the state of our own products: task transitions, review verdicts, links to our own posts, "
            f"visit counts derived from our server logs, and the daily cost of the models. The export is allowlisted: it contains no questions to the "
            f"owner, no texts of observations or user feedback, no secrets. Counts are what the records say; a day without records has no page.</p>"
            f'<p><strong>License.</strong> Our own text and data files (day pages, today.json, feed.xml, per-day JSON) are '
            f'<a href="{esc(LICENSE_URL)}">CC BY 4.0</a>. The framework code is {esc(FRAMEWORK_LICENSE)} at '
            f'<a href="{esc(FRAMEWORK_REPO_URL)}" rel="nofollow">{esc(FRAMEWORK_REPO_URL)}</a>.</p>'
            f"<p><strong>No tracking.</strong> No cookies, no JavaScript, no forms, no analytics scripts. The web server keeps standard access logs "
            f"(IP address, user agent, requested path) for a limited time to count visits and to measure clicks on <code>/go/</code> redirect pages; "
            f"these logs are not shared.</p>"
            f"<p><strong>Feedback.</strong> Public GitHub Issues in the framework repository are read by the team; what you write there is public "
            f"under GitHub's terms. Nothing from an Issue is reproduced on this site.</p>")
    return layout(f"Legal — {SITE_NAME}", body, built, canonical=SITE_BASE + "/legal/",
                  description="Responsible person, data, license and no-tracking statement of the agent team diary.")


# ----------------------------------------------------------------------------------------------------------
# Machine-readable outputs
# ----------------------------------------------------------------------------------------------------------
def day_summary(date: str, model: dict) -> dict:
    per = {}
    for slug, p in model["products"].items():
        if date in p["days"]:
            per[slug] = {**day_counts(p["days"][date]), "name": p["product"].get("name") or slug, "site": p["product"].get("site") or "",
                         "page": f"{SITE_BASE}/day/{date}/#{slug}"}
    threads = [{k: v for k, v in it.items() if k != "_href"} for it in open_threads(date, model)]
    rework = {slug: rework_counts(p["days"][date]) for slug, p in model["products"].items() if date in p["days"]}
    return {"date": date, "page": f"{SITE_BASE}/day/{date}/", "products": per, "rework": rework, "open_threads": threads, "open_threads_states": list(OPEN_THREAD_STATES),
            "disclosure": f"{FOOTER_LINE}; responsible: {RESPONSIBLE}."}


def html_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def feed_failure_line(date: str, model: dict) -> str:
    if not any(p["days"].get(date) for p in model["products"].values()):
        return "No activity recorded."
    n = len({(it["product"], it["task"]) for it in broke_items(date, model)})
    if not n:
        return f"Nothing failed in the records of {date}."
    return f"Failed in the records: {n} {'task' if n == 1 else 'tasks'} (see What went wrong)."


def feed_description(date: str, model: dict) -> str:
    """Feed item text: the day page's #day-lead sentences plus one failure line (same functions as the page)."""
    return html_text(day_lead_block(date, model)) + " " + feed_failure_line(date, model)


def render_feed(model: dict) -> str:
    items = []
    for date in reversed(model["dates"][-FEED_MAX_ITEMS:]):
        desc = feed_description(date, model)
        pub = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).strftime("%a, %d %b %Y 00:00:00 +0000")
        items.append(f"<item><title>{esc(date)} — agent team diary</title><link>{esc(SITE_BASE)}/day/{esc(date)}/?src=rss</link>"
                     f"<guid isPermaLink=\"true\">{esc(SITE_BASE)}/day/{esc(date)}/</guid><pubDate>{pub}</pubDate>"
                     f"<description>{esc(desc)}</description></item>")
    now = datetime.strptime(model["built"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
            f"<title>{esc(SITE_NAME)}</title><link>{esc(SITE_BASE)}/</link>"
            f'<atom:link href="{esc(SITE_BASE)}/feed.xml" rel="self" type="application/rss+xml"/>'
            f"<description>{esc(SITE_TAGLINE)} {esc(FOOTER_LINE)}; responsible: {esc(RESPONSIBLE)}.</description>"
            f"<language>en</language><lastBuildDate>{now}</lastBuildDate>" + "".join(items) + "</channel></rss>\n")


def render_llms(model: dict) -> str:
    lines = [f"# {SITE_NAME}", "",
             f"> {SITE_TAGLINE} One page per UTC day with, for each product: the product manager's digest, every task transition "
             f"(who, to which state, note), review verdicts, published posts, visit counts and model spend. Rendered by a script "
             f"from the team's allowlisted export; no human writes or edits the pages.",
             "",
             f"{FOOTER_LINE}; responsible: {RESPONSIBLE}. License of our text and data: CC BY 4.0. No tracking.", "",
             "## Data", "",
             f"- [today.json]({SITE_BASE}/today.json): summary of the latest day — per product: tasks done, reviews passed, posts, people, spend",
             f"- [feed.xml]({SITE_BASE}/feed.xml): RSS 2.0, one item per day",
             f"- [build.json]({SITE_BASE}/build.json): build time, counts, errors",
             "- Per day: the address pattern is `/day/YYYY-MM-DD/` (page) and `/day/YYYY-MM-DD/index.json` (the merged day records of all products); replace YYYY-MM-DD with a date from the Days list below",
             ]
    latest = model["dates"][-1] if model["dates"] else None
    if latest:
        lines += [f"- [Latest day {latest}]({SITE_BASE}/day/{latest}/): the page of the latest recorded day",
                  f"- [Latest day {latest} as JSON]({SITE_BASE}/day/{latest}/index.json): the merged day records of all products"]
    if latest:
        day_json = f"{SITE_BASE}/day/{latest}/index.json"
        lines += ["", "## JSON fields", "",
                  f"- `open_threads` in today.json: tasks whose last transition that day is in a state listed in `open_threads_states`. Example: {SITE_BASE}/today.json",
                  f"- `open_threads_states` in today.json: the list of states that count as an open thread ({', '.join(OPEN_THREAD_STATES)}). Example: {SITE_BASE}/today.json",
                  f"- `rework` in today.json and in the day index.json, per product: spend_usd, review_fail, review_inconclusive, reopened and cap_usd. cap_usd is null because the budget is not in the export. Examples: {SITE_BASE}/today.json and {day_json}",
                  f"- `broke` in the day index.json: items of what broke that day, each with kind transition (a task moved to a broken state), review (a review with verdict fail or inconclusive) or reopened (a task moved from review to ready/in_progress, review in the same day's records). Example: {day_json}",
                  f"- `broke_counts` in the day index.json: counts of those items by state (review_fail, review_inconclusive, reopened and the transition states). Example: {day_json}",
                  f"- `artifact` in the day index.json, on each accepted/done task under products.<slug>.tasks: {{kind,url}} (kind pr, commit or post) taken from a link already in the export, or null when the export has no link. Example: {day_json}"]
    lines += ["", "## Audit trail per day", "",
              "Each /day/YYYY-MM-DD/index.json is a reusable audit trail of what the agents did and why: per task the transitions (who, to which state, note, time), per review the verdict. Field names are as in the file:", ""]
    lines += audit_lines(latest)
    if latest:
        lines += ["", f"- [Latest day {latest} index.json]({SITE_BASE}/day/{latest}/index.json): example with all fields above",
                  f"- [today.json]({SITE_BASE}/today.json): summary of the latest day (counts only, no transitions)"]
    lines += ["", "Not in the export: questions to the owner, feedback texts, failed runs, rate limits."]
    lines += ["", "## Pages", "",
             f"- [Front page]({SITE_BASE}/): latest day per product, what this is, products, recent days",
             f"- [About]({SITE_BASE}/about/): roles, the hourly cycle, task states, policies, safeguards",
             f"- [Try it]({SITE_BASE}/try/): how to propose your product for a one-week pilot",
             f"- [Legal]({SITE_BASE}/legal/)",
             "", "## Products", ""]
    for slug, p in model["products"].items():
        lines.append(f"- [{p['product'].get('name') or slug}]({SITE_BASE}/product/{slug}/): {len(p['days'])} days recorded · site {p['product'].get('site') or 'n/a'}")
    lines += ["", "## Days", ""]
    for date in reversed(model["dates"]):
        lines.append(f"- [{date}]({SITE_BASE}/day/{date}/)")
    lines += ["", "## Related", "", f"- [agent-team framework on GitHub ({FRAMEWORK_LICENSE})]({FRAMEWORK_REPO_URL})",
              "- [formachines.ai](https://formachines.ai/)", ""]
    return "\n".join(lines)


ROBOTS_TXT = """# agent-team diary — everyone is welcome, including AI crawlers and agents.
User-agent: *
Allow: /
Disallow: /go/

User-agent: GPTBot
Allow: /
Disallow: /go/

User-agent: ClaudeBot
Allow: /
Disallow: /go/

User-agent: PerplexityBot
Allow: /
Disallow: /go/

User-agent: Google-Extended
Allow: /

Sitemap: __SITE__/sitemap.xml
"""


def _content_dates(obj, out: list) -> None:
    """Collect YYYY-MM-DD of every ISO timestamp value (ts, created, accepted_at ...) in a day record."""
    if isinstance(obj, dict):
        for v in obj.values():
            _content_dates(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _content_dates(v, out)
    elif isinstance(obj, str) and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", obj):
        out.append(obj[:10])


def sitemap_entries(model: dict) -> list[tuple[str, str]]:
    """(url, lastmod): lastmod = newest timestamp inside the page's records, within [page date, build date]; static pages
    use the last commit date of build.py (their text lives there), never later than the build date."""
    built = model["built"][:10]
    def day_lastmod(date: str) -> str:
        ds: list = []
        for p in model["products"].values():
            _content_dates(p["days"].get(date) or {}, ds)
        return min(max([date] + [d for d in ds if d >= date and d <= built]), built)
    dm = {d: day_lastmod(d) for d in model["dates"]}
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%cs", "--", "build.py"], capture_output=True, text=True, timeout=10,
                           cwd=str(Path(__file__).resolve().parent))
        static = r.stdout.strip() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", r.stdout.strip()) else built
    except Exception:
        static = built
    static = min(static, built)
    latest = max(dm.values()) if dm else static
    out = [(SITE_BASE + "/", max(latest, static))]
    out += [(f"{SITE_BASE}/{p}/", static) for p in ("about", "try", "legal", "brand")]
    for slug, p in model["products"].items():
        out.append((f"{SITE_BASE}/product/{slug}/", max([dm[d] for d in p["days"] if d in dm] + [static])))
    out += [(f"{SITE_BASE}/day/{d}/", dm[d]) for d in model["dates"]]
    return out


def render_sitemap(model: dict) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>{esc(u)}</loc><lastmod>{esc(lm)}</lastmod></url>" for u, lm in sitemap_entries(model)) + "</urlset>\n")


def check_robots_sitemap(built: str) -> tuple[dict, dict]:
    """robots_check and sitemap_check for build.json."""
    import xml.etree.ElementTree as ET
    issues = []
    txt = (PUBLIC_DIR / "robots.txt").read_text(encoding="utf-8") if (PUBLIC_DIR / "robots.txt").is_file() else ""
    lines = [ln.strip() for ln in txt.splitlines()]
    declared = f"Sitemap: {SITE_BASE}/sitemap.xml" in lines
    if not declared:
        issues.append("Sitemap line missing")
    allowed, group, prev = True, [], False
    for ln in lines:
        k, _, v = ln.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            group = group + [v.lower()] if prev else [v.lower()]
            prev = True
            continue
        prev = False
        if k == "disallow" and v == "/":
            for ua in group:
                if ua in ("gptbot", "claudebot", "perplexitybot", "*"):
                    allowed = False
                    issues.append(f"Disallow: / for {ua}")
    for bot in ("GPTBot", "ClaudeBot", "PerplexityBot"):
        if f"User-agent: {bot}" not in lines:
            allowed = False
            issues.append(f"{bot} group missing")
    rc = {"sitemap_declared": declared, "ai_crawlers_allowed": allowed, "issues": issues}
    missing, bad, locs = [], [], {}
    try:
        for u in ET.parse(PUBLIC_DIR / "sitemap.xml").getroot():
            ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            locs[(u.findtext(ns + "loc") or "").strip()] = (u.findtext(ns + "lastmod") or "").strip()
    except Exception as e:
        bad.append(f"sitemap.xml unreadable: {e}")
    want = [SITE_BASE + "/"] + [f"{SITE_BASE}/{p}/" for p in ("about", "try", "legal")]
    want += [f"{SITE_BASE}/product/{d.parent.name}/" for d in PUBLIC_DIR.glob("product/*/index.html") for d in [d]]
    want += [f"{SITE_BASE}/day/{d.parent.name}/" for d in PUBLIC_DIR.glob("day/*/index.html")]
    missing = [w for w in want if w not in locs]
    missing += [f"{w} (listed but noindex/forbidden)" for w in locs if w.endswith("/404.html") or "/open/costs" in w]
    for loc, lm in locs.items():
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", lm)
        try:
            datetime.strptime(lm, "%Y-%m-%d")
            ok = bool(m) and lm <= built[:10]
        except ValueError:
            ok = False
        dm = re.search(r"/day/(\d{4}-\d{2}-\d{2})/$", loc)
        if ok and dm and lm < dm.group(1):
            ok = False
        if not ok:
            bad.append(f"{loc} {lm}")
    return rc, {"urls": len(locs), "missing_pages": sorted(missing), "bad_lastmod": bad}


# ----------------------------------------------------------------------------------------------------------
# Write public/
# ----------------------------------------------------------------------------------------------------------
def write_site(model: dict) -> dict:
    built = model["built"]
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    # never delete public/ wholesale: addresses must survive; old day pages stay even if a day file disappears.
    written = 0
    FOOTER_PRODUCTS[:] = [(sl, p["product"].get("name") or sl) for sl, p in model["products"].items()]
    write_text(PUBLIC_DIR / "index.html", render_index(model)); written += 1
    for date in model["dates"]:
        write_text(PUBLIC_DIR / "day" / date / "index.html", render_day(date, model)); written += 1
        merged = {"date": date, "page": f"{SITE_BASE}/day/{date}/", "products": {slug: with_artifacts(p["days"][date]) for slug, p in model["products"].items() if date in p["days"]},
                  "counts": {slug: day_counts(p["days"][date]) for slug, p in model["products"].items() if date in p["days"]},
                  "totals": day_totals(date, model),
                  "rework": {slug: rework_counts(p["days"][date]) for slug, p in model["products"].items() if date in p["days"]},
                  "broke": [{k: v for k, v in it.items() if k != "anchor"} | {"anchor": f"#{it['anchor']}" if it["anchor"] else None} for it in broke_items(date, model)],
                  "broke_counts": broke_counts(broke_items(date, model)),
                  "disclosure": f"{FOOTER_LINE}; responsible: {RESPONSIBLE}.", "built": built,
                  "day_complete": not day_in_progress(date, built), "snapshot_built_at": built}
        write_json(PUBLIC_DIR / "day" / date / "index.json", merged)
    for slug, p in model["products"].items():
        write_text(PUBLIC_DIR / "product" / slug / "index.html", render_product(slug, p, model)); written += 1
        write_text(PUBLIC_DIR / "go" / "site" / slug / "index.html",
                   render_go(p["product"].get("site") or SITE_BASE, built, p["product"].get("name") or slug))
    write_text(PUBLIC_DIR / "about" / "index.html", render_about(built, model["dates"][-1] if model["dates"] else None))
    write_text(PUBLIC_DIR / "try" / "index.html", render_try(built))
    write_text(PUBLIC_DIR / "legal" / "index.html", render_legal(built))
    write_text(PUBLIC_DIR / "open" / "costs" / "index.html", render_open_costs(built, model["dates"][-1] if model["dates"] else None))
    write_text(PUBLIC_DIR / "404.html", render_404(built, model["dates"][-1] if model["dates"] else None))
    write_text(PUBLIC_DIR / "brand" / "index.html", render_brand(built))
    for svg in sorted((STATIC_DIR / "brand").glob("*.svg")):
        write_text(PUBLIC_DIR / "brand" / svg.name, svg.read_text(encoding="utf-8"))
    write_text(PUBLIC_DIR / "go" / "github" / "index.html", render_go(FRAMEWORK_REPO_URL, built, "the framework repository"))
    write_text(PUBLIC_DIR / "go" / "telegram" / "index.html", render_go(TELEGRAM_URL, built, "the Telegram channel"))
    write_json(PUBLIC_DIR / "go" / "index.json", {"github": FRAMEWORK_REPO_URL, "telegram": TELEGRAM_URL,
                                                  "site": {slug: p["product"].get("site") for slug, p in model["products"].items()}})
    latest = model["dates"][-1] if model["dates"] else None
    today = day_summary(latest, model) if latest else {"date": None, "products": {}, "note": "no activity recorded",
                                                       "disclosure": f"{FOOTER_LINE}; responsible: {RESPONSIBLE}."}
    today["built"] = built
    today["day_complete"] = bool(latest) and not day_in_progress(latest, built)
    today["snapshot_built_at"] = built
    write_json(PUBLIC_DIR / "today.json", today)
    write_text(PUBLIC_DIR / "feed.xml", render_feed(model))
    write_text(PUBLIC_DIR / "llms.txt", render_llms(model))
    write_text(PUBLIC_DIR / "robots.txt", ROBOTS_TXT.replace("__SITE__", SITE_BASE))
    write_text(PUBLIC_DIR / "sitemap.xml", render_sitemap(model))
    static_ico = STATIC_DIR / "favicon.ico"
    (PUBLIC_DIR / "favicon.ico").write_bytes(static_ico.read_bytes() if static_ico.exists() else make_favicon())
    icon = STATIC_DIR / "apple-touch-icon.png"
    if icon.exists():
        for name in ("apple-touch-icon.png", "apple-touch-icon-precomposed.png"):
            (PUBLIC_DIR / name).write_bytes(icon.read_bytes())
    else:
        model["errors"].append("static/apple-touch-icon.png missing")
    css = STATIC_DIR / "style.css"
    if css.exists():
        write_text(PUBLIC_DIR / "style.css", css.read_text(encoding="utf-8"))
    else:
        log.error("static/style.css is missing")
        model["errors"].append("static/style.css missing")
    summary = {"built": built, "commit": git_head(), "generator": "build.py", "products": len(model["products"]),
               "days": len(model["dates"]), "latest_day": latest,
               "day_files": sum(len(p["days"]) for p in model["products"].values()),
               "fixture_days": sum(1 for p in model["products"].values() for d in p["days"].values() if d.get("fixture")),
               "errors": model["errors"]}
    write_json(PUBLIC_DIR / "build.json", summary)
    return summary


# ----------------------------------------------------------------------------------------------------------
# Self-check (what the reviewer role would do first)
# ----------------------------------------------------------------------------------------------------------
def check_site() -> list[str]:
    import html.parser
    import xml.etree.ElementTree as ET

    class P(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.title = False
            self.css = False
            self.scripts = 0
            self.ld = 0
            self.og = set()
            self.in_ld = False
            self.ld_text = ""

        def handle_endtag(self, tag: str) -> None:
            if tag == "script":
                self.in_ld = False

        def handle_data(self, data: str) -> None:
            if self.in_ld:
                self.ld_text += data

        def handle_starttag(self, tag: str, attrs: list) -> None:
            if tag == "title":
                self.title = True
            if tag == "link" and dict(attrs).get("rel") == "stylesheet" and dict(attrs).get("href") == "/style.css":
                self.css = True
            if tag == "script" and dict(attrs).get("type") == "application/ld+json":
                self.ld += 1
                self.in_ld = True
            elif tag == "script":
                self.scripts += 1
            if tag == "meta" and str(dict(attrs).get("property") or "").startswith("og:") and dict(attrs).get("content"):
                self.og.add(dict(attrs)["property"])

    problems: list[str] = []
    for f in sorted(PUBLIC_DIR.rglob("*.html")):
        txt = f.read_text(encoding="utf-8")
        p = P()
        try:
            p.feed(txt)
            p.close()
        except Exception as e:  # noqa: BLE001 — any parser failure is a defect
            problems.append(f"{f}: parse error {e}")
            continue
        if not p.title:
            problems.append(f"{f}: no <title>")
        if not p.css:
            problems.append(f"{f}: no /style.css link")
        if p.scripts:
            problems.append(f"{f}: contains <script>")
        if "http-equiv=\"refresh\"" not in txt:
            if p.ld != 1:
                problems.append(f"{f}: expected exactly one JSON-LD block, found {p.ld}")
            else:
                try:
                    ld = json.loads(p.ld_text)
                    if ld.get("@context") != "https://schema.org" or not ld.get("@type"):
                        problems.append(f"{f}: JSON-LD lacks @context/@type")
                except ValueError as e:
                    problems.append(f"{f}: bad JSON-LD {e}")
            for k in ("og:title", "og:description", "og:type", "og:url"):
                if k not in p.og:
                    problems.append(f"{f}: missing {k}")
        if FOOTER_LINE not in txt:
            problems.append(f"{f}: footer disclosure missing")
    for f in sorted(PUBLIC_DIR.rglob("*.json")):
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            problems.append(f"{f}: bad JSON {e}")
    for name in ("feed.xml", "sitemap.xml"):
        try:
            ET.parse(PUBLIC_DIR / name)
        except (OSError, ET.ParseError) as e:
            problems.append(f"{name}: {e}")
    return problems


META_TAGS = ("og:title", "og:description", "og:url", "og:type", "twitter:card",
             "og:image", "og:image:alt", "twitter:image")


def check_meta() -> dict:
    """Link-preview tags on every public index.html (redirect hops under /go/ are noindex meta-refresh pages: exempt)."""
    import html.parser

    class M(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.have: set[str] = set()

        def handle_starttag(self, tag: str, attrs: list) -> None:
            a = dict(attrs)
            if tag == "meta" and a.get("content"):
                key = a.get("property") or a.get("name")
                if key in META_TAGS:
                    self.have.add(key)
            if tag == "link" and a.get("rel") == "canonical" and a.get("href"):
                self.have.add("canonical")

    need = META_TAGS + ("canonical",)
    checked, missing = 0, []
    for f in sorted(PUBLIC_DIR.rglob("index.html")):
        txt = f.read_text(encoding="utf-8")
        if 'http-equiv="refresh"' in txt:
            continue
        m = M()
        m.feed(txt)
        checked += 1
        page = "/" + f.parent.relative_to(PUBLIC_DIR).as_posix().strip(".") + "/"
        page = page.replace("//", "/")
        missing += [{"page": page, "tag": t} for t in need if t not in m.have]
    return {"checked": checked, "tags": list(need), "missing": missing}


def check_links() -> dict:
    """Walk every href/src in public/**/*.html that points to this site; the target file must exist and each #fragment
    must be an id (or a[name]) on the target page. External links are not fetched."""
    import html.parser
    from urllib.parse import urldefrag, unquote, urlsplit

    class L(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.links: list[str] = []
            self.ids: set[str] = set()

        def handle_starttag(self, tag: str, attrs: list) -> None:
            a = dict(attrs)
            if a.get("id"):
                self.ids.add(a["id"])
            if tag == "a" and a.get("name"):
                self.ids.add(a["name"])
            for k in ("href", "src"):
                if a.get(k) and not (tag == "link" and a.get("rel") == "canonical"):
                    self.links.append(a[k])

    pages: dict[Path, L] = {}
    for f in sorted(PUBLIC_DIR.rglob("*.html")):
        p = L()
        p.feed(f.read_text(encoding="utf-8"))
        pages[f] = p
    base = urlsplit(SITE_BASE)
    checked, broken = 0, []
    for f, p in pages.items():
        page = "/" + f.relative_to(PUBLIC_DIR).as_posix()
        for href in p.links:
            h = href.strip()
            if not h or h.startswith(("mailto:", "tel:", "data:", "javascript:")):
                continue
            u = urlsplit(h)
            if u.scheme or u.netloc:
                if not (u.scheme in ("http", "https") and u.netloc == base.netloc):
                    continue
                path = u.path or "/"
            else:
                path = u.path
            frag = unquote(u.fragment)
            if not path:
                target = f
            else:
                if not path.startswith("/"):
                    path = (Path(page).parent / path).as_posix()
                    path = "/" + "/".join(x for x in __import__("posixpath").normpath(path).split("/") if x)
                    if href.endswith("/") and not path.endswith("/"):
                        path += "/"
                target = PUBLIC_DIR / unquote(path).lstrip("/")
                if path.endswith("/") or target.is_dir():
                    target = target / "index.html"
            checked += 1
            ok = target.is_file()
            if ok and frag and frag != "top":
                if target.suffix == ".html":
                    if target not in pages:
                        ok = False
                    else:
                        ok = frag in pages[target].ids
            if not ok:
                broken.append({"page": page, "href": href})
    return {"checked": checked, "broken": broken}


import html.parser


class _KParser(html.parser.HTMLParser):
    """Collects <span data-k> texts. A data-k span inside another data-k span is recorded in .nested, never read."""

    def __init__(self) -> None:
        super().__init__()
        self.cur: str | None = None
        self.depth = 0
        self.buf: list[str] = []
        self.found: list[tuple[str, str]] = []
        self.nested: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "span":
            return
        k = dict(attrs).get("data-k")
        if self.cur is None:
            if k is not None:
                self.cur, self.buf, self.depth = k, [], 1
        else:
            self.depth += 1
            if k is not None:
                self.nested.append(k)

    def handle_data(self, data):
        if self.cur is not None:
            self.buf.append(data)

    def handle_endtag(self, tag):
        if tag == "span" and self.cur is not None:
            self.depth -= 1
            if self.depth == 0:
                self.found.append((self.cur, "".join(self.buf)))
                self.cur = None


def numbers_selftest() -> str:
    """Parse an inline sample: the nested pair must be caught, the flat pair read correctly."""
    try:
        p = _KParser()
        p.feed('<p><span data-k="a.b">1</span> <span data-k="x"><span data-k="y">2</span></span></p>')
        p.close()
        ok = p.found == [("a.b", "1"), ("x", "2")] and p.nested == ["y"]
        return "pass" if ok else "fail"
    except Exception:
        return "fail"


def check_numbers() -> dict:
    """Every <span data-k="path"> on / and /day/*/ must equal the value at that path in today.json / day index.json."""
    def lookup(obj, path):
        for part in path.split("."):
            if isinstance(obj, dict) and part in obj:
                obj = obj[part]
            elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
                obj = obj[int(part)]
            else:
                raise KeyError(path)
        return obj

    def show(v):
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:.1f}"
        return str(v)

    pairs = [("home", PUBLIC_DIR / "index.html", PUBLIC_DIR / "today.json")]
    pairs += [("day", h, h.with_name("index.json")) for h in sorted((PUBLIC_DIR / "day").glob("*/index.html"))]
    pairs += [("product", h, None) for h in sorted((PUBLIC_DIR / "product").glob("*/index.html"))]
    checked, mism, nested = 0, [], []
    kinds = {"home": 0, "day": 0, "product": 0}
    cache: dict = {}

    def load(path):
        if path not in cache:
            cache[path] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        return cache[path]

    for kind, page, jf in pairs:
        if not page.exists() or (jf is not None and not jf.exists()):
            continue
        name = "/" + page.relative_to(PUBLIC_DIR).parent.as_posix().strip(".") 
        name = name.rstrip("/") + "/"
        k = _KParser()
        k.feed(page.read_text(encoding="utf-8"))
        data = load(jf) if jf is not None else None
        for nk in k.nested:
            nested.append({"page": name, "key": nk})
        for key, text in k.found:
            checked += 1
            kinds[kind] += 1
            try:
                src = data
                if key.startswith("day/"):
                    dpart, _, key2 = key[4:].partition(":")
                    src = load(PUBLIC_DIR / "day" / dpart / "index.json")
                    if src is None or not key2:
                        raise KeyError(key)
                else:
                    key2 = key
                    if src is None:
                        raise KeyError(key)
                v = show(lookup(src, key2))
            except KeyError:
                mism.append({"page": name, "key": key, "html": text, "json": "unknown path"})
                continue
            if text != v:
                mism.append({"page": name, "key": key, "html": text, "json": v})
    return {"checked": checked, "by_kind": kinds, "mismatches": mism, "nested": nested, "selftest": numbers_selftest()}


def check_checklist() -> dict:
    """Reviewer checklist: footer on every index.html, feed/sitemap parse, sitemap lists every day and the static pages,
    newest day page equals the latest export day."""
    import xml.etree.ElementTree as ET
    from urllib.parse import urlsplit

    pages = sorted(PUBLIC_DIR.rglob("index.html"))
    footer_missing = []
    for f in pages:
        t = f.read_text(encoding="utf-8")
        if "Written by the agent team itself" not in t or "responsible: " not in t or "Dmitry" not in t:
            footer_missing.append("/" + f.relative_to(PUBLIC_DIR).as_posix())
    xml_errors, locs = [], None
    for name in ("feed.xml", "sitemap.xml"):
        try:
            tree = ET.parse(PUBLIC_DIR / name)
            if name == "sitemap.xml":
                locs = {urlsplit((e.text or "").strip()).path for e in tree.iter() if e.tag.rsplit("}", 1)[-1] == "loc"}
        except (OSError, ET.ParseError) as e:
            xml_errors.append(f"{name}: {e}")
    days = sorted(d.name for d in (PUBLIC_DIR / "day").glob("*") if d.is_dir())
    want = ["/", "/about/", "/try/", "/legal/"] + [f"/day/{d}/" for d in days]
    sitemap_missing = [w for w in want if locs is None or w not in locs]
    export_days = sorted({m.group(1) for f in DATA_DIR.glob("*/day-*.json")
                          if (m := re.match(r"day-(\d{4}-\d{2}-\d{2})\.json$", f.name))})
    latest = export_days[-1] if export_days else None
    latest_problem = []
    if latest and (not days or days[-1] != latest):
        latest_problem.append(f"newest day page {days[-1] if days else None} != latest export day {latest}")
    return {"pages_checked": len(pages), "footer_missing": footer_missing, "xml_errors": xml_errors,
            "sitemap_missing": sitemap_missing, "latest_day": days[-1] if days else None,
            "latest_export_day": latest, "latest_day_problems": latest_problem}


def _hex_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lum(h: str) -> float:
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in _hex_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


A11Y_PAIRS = [("fg", "bg"), ("fg", "card"), ("muted", "bg"), ("muted", "card"), ("accent", "bg"), ("accent", "card"),
              ("fg", "code-bg"), ("accent", "code-bg"), ("ok-fg", "ok-bg"), ("warn-fg", "warn-bg"), ("bad-fg", "bad-bg")]


def check_a11y() -> dict:
    """Accessibility basics on every public/**/index.html plus WCAG contrast (>= 4.5) of the stylesheet colour pairs
    in the light and the prefers-color-scheme: dark scheme."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.lang = False
            self.h1 = 0
            self.img_no_alt = 0
            self.tables = 0
            self.th = 0
            self.links = []  # [has_label, text]
            self.cur = None

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "html":
                self.lang = bool((a.get("lang") or "").strip())
            elif tag == "h1":
                self.h1 += 1
            elif tag == "img":
                if "alt" not in a:
                    self.img_no_alt += 1
                if self.cur is not None and a.get("alt"):
                    self.cur[1] += "x"
            elif tag == "table":
                self.tables += 1
            elif tag == "th":
                self.th += 1
            elif tag == "a":
                self.cur = [bool((a.get("aria-label") or "").strip()), ""]
                self.links.append(self.cur)

        def handle_data(self, data):
            if self.cur is not None:
                self.cur[1] += data.strip()

        def handle_endtag(self, tag):
            if tag == "a":
                self.cur = None

    issues = []
    pages = sorted(PUBLIC_DIR.rglob("index.html"))
    for f in pages:
        page = "/" + f.parent.relative_to(PUBLIC_DIR).as_posix().strip(".") + ("/" if f.parent != PUBLIC_DIR else "")
        page = page.replace("//", "/")
        p = P()
        p.feed(f.read_text(encoding="utf-8"))
        if not p.lang:
            issues.append({"page": page, "rule": "html-lang"})
        if p.h1 != 1:
            issues.append({"page": page, "rule": f"one-h1 (found {p.h1})"})
        if p.img_no_alt:
            issues.append({"page": page, "rule": "img-alt"})
        if p.tables and p.th == 0:
            issues.append({"page": page, "rule": "table-th"})
        if any(not lab and not txt for lab, txt in p.links):
            issues.append({"page": page, "rule": "link-text"})
    css = (PUBLIC_DIR / "style.css").read_text(encoding="utf-8")
    m = re.search(r":root\s*\{([^}]*)\}", css)
    light = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,6})", m.group(1))) if m else {}
    dm = re.search(r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{([^}]*)\}", css)
    dark = dict(light)
    if dm:
        dark.update(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,6})", dm.group(1)))
    contrast = []
    for scheme, colours in (("light", light), ("dark", dark)):
        for fg, bg in A11Y_PAIRS:
            if fg in colours and bg in colours:
                r = round(contrast_ratio(colours[fg], colours[bg]), 2)
                contrast.append({"scheme": scheme, "pair": f"{fg} on {bg}", "ratio": r})
                if r < 4.5:
                    issues.append({"page": "/style.css", "rule": f"contrast {scheme} {fg} on {bg} = {r}"})
            else:
                issues.append({"page": "/style.css", "rule": f"contrast colour missing {scheme} {fg}/{bg}"})
    return {"pages_checked": len(pages), "issues": issues, "contrast": contrast}


def check_contrast() -> dict:
    """WCAG 2.1 contrast (>= 4.5:1) of body, link, muted, code/table and badge colour pairs parsed from public/style.css,
    in the light scheme and in @media (prefers-color-scheme: dark)."""
    css = (PUBLIC_DIR / "style.css").read_text(encoding="utf-8")
    hexre = r"--([\w-]+):\s*(#[0-9a-fA-F]{3,6})\b"
    m = re.search(r":root\s*\{([^}]*)\}", css)
    light = dict(re.findall(hexre, m.group(1))) if m else {}
    dm = re.search(r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{([^}]*)\}", css)
    schemes = [("light", light)]
    if dm:
        schemes.append(("dark", {**light, **dict(re.findall(hexre, dm.group(1)))}))
    pairs = A11Y_PAIRS + [("muted", "code-bg"), ("muted", "warn-bg"), ("fg", "ok-bg"), ("fg", "warn-bg"), ("fg", "bad-bg")]
    failures, n = [], 0
    for scheme, col in schemes:
        for fg, bg in pairs:
            if fg in col and bg in col:
                n += 1
                r = round(contrast_ratio(col[fg], col[bg]), 2)
                if r < 4.5:
                    failures.append({"scheme": scheme, "pair": f"{fg} on {bg}", "ratio": r})
            else:
                failures.append({"scheme": scheme, "pair": f"{fg} on {bg}", "ratio": None})
    return {"schemes_checked": len(schemes), "pairs_checked": n, "failures": failures}


def check_mobile() -> dict:
    """Static 375 px check: viewport meta, no fixed width/min-width above 375px outside a max-width media query,
    overflow-wrap on body, tables wrapped or stacked at <=480px, pre/code wrap or scroll."""
    from html.parser import HTMLParser
    issues = []
    css = re.sub(r"/\*.*?\*/", "", (PUBLIC_DIR / "style.css").read_text(encoding="utf-8"), flags=re.S)

    def blocks(text):
        """Top-level (prelude, body) pairs."""
        out, depth, start, pre = [], 0, 0, ""
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    pre, start = text[start:i].strip(), i + 1
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append((pre, text[start:i]))
                    start = i + 1
        return out

    def wide(body):
        res = []
        for prop, val in re.findall(r"(?<![\w-])((?:min-)?width)\s*:\s*([^;}]+)", body):
            for n in re.findall(r"(\d+(?:\.\d+)?)px", val):
                if float(n) > 375:
                    res.append(f"{prop}: {val.strip()}")
        return res

    rules = []  # (selector, body) outside max-width media
    stack_css = blocks(css)
    for pre, body in stack_css:
        if pre.startswith("@media"):
            if re.search(r"max-width", pre):
                continue
            rules += blocks(body)
        elif pre.startswith("@"):
            continue
        else:
            rules.append((pre, body))
    for sel, body in rules:
        for d in wide(body):
            issues.append({"page": "/style.css", "rule": "fixed-width", "detail": f"{sel}: {d}"})
    wrap_ok = any(re.search(r"overflow-wrap\s*:\s*(anywhere|break-word)|word-break\s*:", b)
                  and re.search(r"(^|,)\s*(body|main|\.wrap)\s*(,|$)", s) for s, b in rules)
    if not wrap_ok:
        issues.append({"page": "/style.css", "rule": "overflow-wrap", "detail": "no overflow-wrap/word-break on body, main or .wrap"})
    pre_ok = any(re.search(r"(^|,)\s*pre\s*(,|$)", s) and re.search(r"overflow-x\s*:\s*(auto|scroll)|white-space\s*:\s*pre-(wrap|line)|overflow-wrap|word-break", b)
                 for s, b in rules)
    if not pre_ok:
        issues.append({"page": "/style.css", "rule": "pre-wrap", "detail": "pre neither wraps nor scrolls"})
    stack_ok = bool(re.search(r"\.table\.fm[^{]*\{[^}]*display\s*:\s*block", css))
    wrapper_ok = bool(re.search(r"\.table-wrap\s*\{[^}]*overflow-x\s*:\s*auto", css))

    VOID = {"meta", "link", "br", "hr", "img", "input", "col", "area", "base", "source", "wbr"}

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.viewport = False
            self.stack = []
            self.bad_tables = 0
            self.inline = []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "meta" and (a.get("name") or "").lower() == "viewport" and "width=device-width" in (a.get("content") or ""):
                self.viewport = True
            st = a.get("style") or ""
            if st:
                self.inline += wide(st)
            cls = (a.get("class") or "").split()
            if tag == "table":
                wrapped = wrapper_ok and any("table-wrap" in c for c in self.stack)
                stacked = stack_ok and "fm" in cls
                if not (wrapped or stacked):
                    self.bad_tables += 1
            if tag not in VOID:
                self.stack.append(cls)

        def handle_endtag(self, tag):
            if tag not in VOID and self.stack:
                self.stack.pop()

    pages = sorted(PUBLIC_DIR.rglob("index.html"))
    for f in pages:
        page = "/" + f.parent.relative_to(PUBLIC_DIR).as_posix().strip(".") + ("/" if f.parent != PUBLIC_DIR else "")
        page = page.replace("//", "/")
        p = P()
        p.feed(f.read_text(encoding="utf-8"))
        if not p.viewport:
            issues.append({"page": page, "rule": "viewport", "detail": "no meta viewport with width=device-width"})
        if p.bad_tables:
            issues.append({"page": page, "rule": "table", "detail": f"{p.bad_tables} table(s) neither in overflow-x:auto wrapper nor stacked"})
        for d in p.inline:
            issues.append({"page": page, "rule": "fixed-width", "detail": f"inline style {d}"})
    return {"pages_checked": len(pages), "issues": issues}


def check_audit() -> dict:
    """Every documented audit field must exist in the latest day index.json."""
    days = sorted(p.name for p in (PUBLIC_DIR / "day").iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)) if (PUBLIC_DIR / "day").is_dir() else []
    seen: dict[str, set] = {"task": set(), "transition": set(), "review": set()}
    if days:
        try:
            d = json.loads((PUBLIC_DIR / "day" / days[-1] / "index.json").read_text(encoding="utf-8"))
            for p in d.get("products", {}).values():
                for t in p.get("tasks", []):
                    seen["task"] |= set(t)
                    for h in t.get("history", []):
                        seen["transition"] |= set(h)
                for r in p.get("reviews", []):
                    seen["review"] |= set(r)
        except (OSError, ValueError):
            pass
    missing = [f for k, f, _ in AUDIT_FIELDS if f.removeprefix("history[].") not in seen[k]]
    return {"fields_documented": len(AUDIT_FIELDS), "fields_missing": missing, "checked_day": days[-1] if days else None}


def check_llms() -> dict:
    """Fields named in the llms.txt section 'Audit trail per day' must be keys in the latest index.json; its links and
    the /about/ links to the same index.json and /llms.txt must exist."""
    try:
        txt = (PUBLIC_DIR / "llms.txt").read_text(encoding="utf-8")
        about = (PUBLIC_DIR / "about" / "index.html").read_text(encoding="utf-8")
    except OSError:
        return {"fields_named": 0, "missing_fields": ["llms.txt/about unreadable"], "bad_links": []}
    m = re.search(r"^## Audit trail per day\n(.*?)(?=^## )", txt, re.M | re.S)
    sec = m.group(1) if m else ""
    names = re.findall(r"^- `products\.<slug>\.(?:tasks|reviews)\[\]\.([^`]+)`", sec, re.M)
    ad = check_audit()
    seen: set = set()
    day = ad["checked_day"]
    try:
        d = json.loads((PUBLIC_DIR / "day" / day / "index.json").read_text(encoding="utf-8"))
        for p in d.get("products", {}).values():
            for t in p.get("tasks", []):
                seen |= set(t)
                for h in t.get("history", []):
                    seen |= {"history[]." + k for k in h}
            for r in p.get("reviews", []):
                seen |= set(r)
    except (OSError, ValueError, TypeError):
        pass
    missing = [n for n in names if n not in seen]
    links = re.findall(re.escape(SITE_BASE) + r"(/[^\s)]*)", sec)
    links += [l for l in re.findall(r'href="(/[^"#]*)"', about.split('id="audit-trail"')[-1].split("<h2")[0])]
    for need in ("/today.json", f"/day/{day}/index.json"):
        if need not in links:
            links.append(need)
    bad = sorted({l for l in links if not (PUBLIC_DIR / l.lstrip("/")).is_file() and not (PUBLIC_DIR / l.lstrip("/") / "index.html").is_file()})
    if not m:
        missing.append("section 'Audit trail per day'")
    for need in (f"/day/{day}/index.json", "/llms.txt"):
        if f'href="{need}"' not in about:
            bad.append("about:" + need)
    return {"fields_named": len(names), "missing_fields": missing, "bad_links": bad}


def check_machine() -> dict:
    """Files agents read: llms.txt names the machine addresses, feed.xml has the latest day and only existing days,
    every day index.json and today.json parse with the right date."""
    import xml.etree.ElementTree as ET
    days = sorted(p.name for p in (PUBLIC_DIR / "day").iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)) if (PUBLIC_DIR / "day").is_dir() else []
    latest = days[-1] if days else None
    llms_missing, feed_missing, json_errors = [], [], []
    try:
        llms = (PUBLIC_DIR / "llms.txt").read_text(encoding="utf-8")
    except OSError:
        llms = ""
    want = ["/today.json", "/feed.xml", "/about/", "/try/"]
    want += [f"/product/{d.name}/" for d in sorted((PUBLIC_DIR / "product").iterdir()) if d.is_dir()] if (PUBLIC_DIR / "product").is_dir() else []
    if latest:
        want.append(f"/day/{latest}/index.json")
    for w in want:
        if f"]({SITE_BASE}{w})" not in llms:
            llms_missing.append(w)
    try:
        root = ET.fromstring((PUBLIC_DIR / "feed.xml").read_text(encoding="utf-8"))
        links = [(i.findtext("link") or "").strip() for i in root.iter("item")]
    except (OSError, ET.ParseError) as e:
        links = []
        feed_missing.append(f"feed.xml unreadable: {e}")
    if latest and f"{SITE_BASE}/day/{latest}/?src=rss" not in links:
        feed_missing.append(f"/day/{latest}/")
    for l in links:
        m = re.fullmatch(re.escape(SITE_BASE) + r"/day/(\d{4}-\d{2}-\d{2})/(?:\?src=rss)?", l)
        if not m or not (PUBLIC_DIR / "day" / m.group(1) / "index.html").is_file():
            feed_missing.append(f"item link without day page: {l}")
    for d in days:
        p = PUBLIC_DIR / "day" / d / "index.json"
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("date") != d:
                json_errors.append(f"day/{d}/index.json: date != {d}")
        except (OSError, ValueError, AttributeError) as e:
            json_errors.append(f"day/{d}/index.json: {e}")
    try:
        if json.loads((PUBLIC_DIR / "today.json").read_text(encoding="utf-8")).get("date") != latest:
            json_errors.append(f"today.json: date != {latest}")
    except (OSError, ValueError, AttributeError) as e:
        json_errors.append(f"today.json: {e}")
    return {"days_checked": len(days), "llms_missing": llms_missing, "feed_missing": feed_missing, "json_errors": json_errors}


def check_wellknown() -> dict:
    """Standard client/crawler paths exist and are non-empty; robots.txt has the Sitemap line and blocks no sitemap URL."""
    files, missing, problems = [], [], []
    for name in ("robots.txt", "favicon.ico", "apple-touch-icon.png", "apple-touch-icon-precomposed.png"):
        f = PUBLIC_DIR / name
        n = f.stat().st_size if f.is_file() else 0
        if n > 0:
            files.append({"path": name, "bytes": n})
        else:
            missing.append(name)
    rp = PUBLIC_DIR / "robots.txt"
    if rp.is_file():
        lines = [ln.strip() for ln in rp.read_text(encoding="utf-8").splitlines()]
        if f"Sitemap: {SITE_BASE}/sitemap.xml" not in lines:
            problems.append("robots.txt: Sitemap line missing")
        if "User-agent: *" not in lines:
            problems.append("robots.txt: 'User-agent: *' missing")
        group, rules = [], {}
        prev_ua = False
        for ln in lines:
            k, _, v = ln.partition(":")
            k, v = k.strip().lower(), v.strip()
            if k == "user-agent":
                if not prev_ua:
                    group = []
                group.append(v)
                prev_ua = True
                continue
            prev_ua = False
            if k == "disallow" and v:
                for ua in group:
                    rules.setdefault(ua, []).append(v)
        sp = PUBLIC_DIR / "sitemap.xml"
        if sp.is_file():
            locs = re.findall(r"<loc>([^<]+)</loc>", sp.read_text(encoding="utf-8"))
            for loc in locs:
                path = "/" + loc.split("://", 1)[-1].partition("/")[2]
                for ua, dis in rules.items():
                    for d in dis:
                        if path.startswith(d):
                            problems.append(f"robots.txt: Disallow {d} ({ua}) blocks sitemap URL {loc}")
    return {"files": files, "missing": missing, "problems": problems}


def check_machine_urls() -> dict:
    """Extract every same-site URL from feed.xml, sitemap.xml, llms.txt, today.json and day/*/index.json; the target
    must exist in public/ (a directory resolves to index.html; query strings and fragments are ignored)."""
    from urllib.parse import unquote, urlsplit

    base = urlsplit(SITE_BASE)
    origin = re.escape(base.scheme + "://" + base.netloc)
    abs_pat = re.compile(origin + r"(/[^\s<>\"'\)\]]*)?(?=[\s<>\"'\)\]]|$)")

    def urls_text(txt: str, relative: bool) -> list[str]:
        out = [m.group(0) for m in abs_pat.finditer(txt)]
        if relative:
            out += re.findall(r"\]\((/[^\s\)]*)\)", txt)
        return out

    def urls_json(o) -> list[str]:
        if isinstance(o, dict):
            return [u for v in o.values() for u in urls_json(v)]
        if isinstance(o, list):
            return [u for v in o for u in urls_json(v)]
        if isinstance(o, str):
            if o.startswith("/") and not o.startswith("//") and " " not in o:
                return [o]
            return urls_text(o, False)
        return []

    groups: dict[str, list[tuple[str, str]]] = {k: [] for k in ("feed.xml", "sitemap.xml", "llms.txt", "today.json", "day_json")}
    for key in ("feed.xml", "sitemap.xml", "llms.txt"):
        f = PUBLIC_DIR / key
        if f.is_file():
            groups[key] += [("/" + key, u) for u in urls_text(f.read_text(encoding="utf-8"), key == "llms.txt")]
    files = [("today.json", PUBLIC_DIR / "today.json")] + [
        ("day_json", f) for f in sorted(PUBLIC_DIR.glob("day/*/index.json"))]
    for key, f in files:
        if f.is_file():
            groups[key] += [("/" + f.relative_to(PUBLIC_DIR).as_posix(), u)
                            for u in urls_json(json.loads(f.read_text(encoding="utf-8")))]
    sources, broken = {}, []
    for key, items in groups.items():
        bad = 0
        for page, u in items:
            path = urlsplit(u).path or "/"
            target = PUBLIC_DIR / unquote(path).lstrip("/")
            if path.endswith("/") or target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                broken.append({"page": page, "href": u})
                bad += 1
        sources[key] = {"checked": len(items), "broken": bad}
    return {"sources": sources, "broken": broken}


# ----------------------------------------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("-v", "--verbose", action="store_true", help="debug log")
    ap.add_argument("--check", action="store_true", help="after building, parse every HTML/XML/JSON written")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    log.info("build start: data=%s public=%s site=%s", DATA_DIR, PUBLIC_DIR, SITE_BASE)
    model = load_data()
    model["built"] = iso(utcnow())
    model["errors"] = []
    summary = write_site(model)
    log.info("products=%d days=%d day_files=%d fixture_days=%d errors=%d", summary["products"], summary["days"],
             summary["day_files"], summary["fixture_days"], len(summary["errors"]))
    lc = check_links()
    bj = json.loads((PUBLIC_DIR / "build.json").read_text(encoding="utf-8"))
    mu = check_machine_urls()
    lc["sources"] = mu["sources"]
    lc["broken"] = lc["broken"] + mu["broken"]
    bj["link_check"] = lc
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("link_check: checked=%d broken=%d", lc["checked"], len(lc["broken"]))
    mc = check_meta()
    bj["meta_check"] = mc
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("meta_check: checked=%d missing=%d", mc["checked"], len(mc["missing"]))
    nc = check_numbers()
    bj["numbers_check"] = nc
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("numbers_check: checked=%d mismatches=%d", nc["checked"], len(nc["mismatches"]))
    hc = check_home()
    bj["home_check"] = hc
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("home_check: latest_link_ok=%s issues=%d", hc["latest_link_ok"], len(hc["issues"]))
    cc = check_checklist()
    bj["checklist_check"] = cc
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("checklist_check: pages=%d footer_missing=%d xml_errors=%d sitemap_missing=%d latest_day=%s",
             cc["pages_checked"], len(cc["footer_missing"]), len(cc["xml_errors"]), len(cc["sitemap_missing"]), cc["latest_day"])
    ac = check_a11y()
    bj["a11y_check"] = ac
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("a11y_check: pages=%d issues=%d", ac["pages_checked"], len(ac["issues"]))
    mob = check_mobile()
    bj["mobile_check"] = mob
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("mobile_check: pages=%d issues=%d", mob["pages_checked"], len(mob["issues"]))
    cn = check_contrast()
    bj["contrast_check"] = cn
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("contrast_check: schemes=%d pairs=%d failures=%d", cn["schemes_checked"], cn["pairs_checked"], len(cn["failures"]))
    wk = check_wellknown()
    bj["wellknown_check"] = {"files": wk["files"], "missing": wk["missing"]}
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("wellknown_check: files=%d missing=%d problems=%d", len(wk["files"]), len(wk["missing"]), len(wk["problems"]))
    lcd = check_lead()
    bj["lead_check"] = lcd
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("lead_check: pages=%d issues=%d", lcd["pages_checked"], len(lcd["issues"]))
    fcd = check_feed()
    bj["feed_check"] = fcd
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("feed_check: items=%d lead_mismatches=%d bad_links=%d guid_changed=%d", fcd["items"], len(fcd["lead_mismatches"]), len(fcd["bad_links"]), len(fcd["guid_changed"]))
    bkc = check_broke()
    bj["broke_check"] = bkc
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("broke_check: pages=%d mismatches=%d bad_anchors=%d", bkc["pages_checked"], len(bkc["mismatches"]), len(bkc["bad_anchors"]))
    ocd = check_outcome()
    bj["outcome_check"] = ocd
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("outcome_check: pages=%d mismatches=%d", ocd["pages_checked"], len(ocd["mismatches"]))
    idc = check_ids()
    bj["id_check"] = idc
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("id_check: pages=%d duplicate_ids=%d dangling_links=%d", idc["pages_checked"], len(idc["duplicate_ids"]), len(idc["dangling_links"]))
    nav = check_nav()
    bj["nav_check"] = nav
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("nav_check: pages=%d missing=%d", nav["pages_checked"], len(nav["missing"]))
    nf = check_notfound()
    bj["notfound_check"] = nf
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("notfound_check: exists=%s links_missing=%d", nf["exists"], len(nf["links_missing"]))
    mch = check_machine()
    bj["machine_check"] = mch
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("machine_check: days=%d llms_missing=%d feed_missing=%d json_errors=%d", mch["days_checked"],
             len(mch["llms_missing"]), len(mch["feed_missing"]), len(mch["json_errors"]))
    bj["robots_check"], bj["sitemap_check"] = check_robots_sitemap(bj.get("built") or model["built"])
    write_json(PUBLIC_DIR / "build.json", bj)
    ad = check_audit()
    bj["audit_check"] = ad
    lk = check_llms()
    bj["llms_check"] = lk
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("audit_check: documented=%d missing=%d", ad["fields_documented"], len(ad["fields_missing"]))
    seo = check_seo()
    bj["seo_check"] = seo
    bj["orphan_check"] = {"pages_in_sitemap": seo["pages_in_sitemap"], "orphans": seo["orphans"]}
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("seo_check: pages=%d canonical_missing=%d lastmod_missing=%d orphans=%d duplicate_titles=%d", seo["pages_checked"],
             len(seo["canonical_missing"]), len(seo["lastmod_missing"]), len(seo["orphans"]), len(seo["duplicate_titles"]))
    jl = check_jsonld()
    bj["jsonld_check"] = jl
    write_json(PUBLIC_DIR / "build.json", bj)
    log.info("jsonld_check: pages=%d invalid=%d missing=%d", jl["pages_checked"], len(jl["invalid"]), len(jl["missing"]))
    pc = check_paths()
    bj["paths_check"] = pc
    write_json(PUBLIC_DIR / "build.json", bj)
    if args.check:
        problems = check_site()
        problems += [f"paths: {m}" for m in pc["missing"]]
        problems += [f"home: {m}" for m in hc["issues"]]
        problems += [f"lead: {i['page']} {i['issue']}" for i in lcd["issues"]]
        problems += [f"feed: {i}" for i in fcd["lead_mismatches"]] + [f"feed: bad link {l}" for l in fcd["bad_links"]] + [f"feed: guid changed {g}" for g in fcd["guid_changed"]]
        if not fcd["items"]:
            problems.append("feed: no items")
        problems += [f"broke: duplicate failure blocks {p}" for p in bkc["duplicate_blocks"]]
        problems += [f"outcome: {m}" for m in ocd["mismatches"]]
        problems += [f"ids: duplicate id {x['id']} on {x['page']}" for x in idc["duplicate_ids"]]
        problems += [f"ids: dangling link {x['link']} on {x['page']}" for x in idc["dangling_links"]]
        problems += [f"jsonld: invalid {i['page']} {i['issue']}" for i in jl["invalid"]] + [f"jsonld: missing {p}" for p in jl["missing"]]
        problems += [f"seo: no self-canonical {p}" for p in seo["canonical_missing"]] + [f"seo: no lastmod {p}" for p in seo["lastmod_missing"]]
        problems += [f"seo: orphan {p}" for p in seo["orphans"]] + [f"seo: duplicate title {d['title']}" for d in seo["duplicate_titles"]]
        problems += [f"seo: duplicate description {d['description']}" for d in seo["description_duplicates"]]
        problems += [f"seo: description {d['page']} {d['issue']} ({d['length']})" for d in seo["description_length_issues"]]
        problems += [f"orphan: sitemap URL {p} not linked from another page" for p in seo["orphans"]]
        problems += [f"seo: noindex {p}" for p in seo["noindex"]] + [f"seo: {d['page']} lacks link to {d['link']}" for d in seo["daylink_missing"]]
        problems += [f"llms.txt: missing {m}" for m in mch["llms_missing"]] + [f"feed.xml: {m}" for m in mch["feed_missing"]] + mch["json_errors"]
        problems += [f"llms_check: field {m}" for m in lk["missing_fields"]] + [f"llms_check: bad link {m}" for m in lk["bad_links"]]
        if not lk["fields_named"]:
            problems.append("llms_check: no fields named")
        problems += [f"audit: field not in latest index.json: {m}" for m in ad["fields_missing"]]
        problems += [f"wellknown: missing or empty {m}" for m in wk["missing"]] + wk["problems"]
        problems += [f"{m['page']}: nav link {m['link']} not before first h2" for m in nav["missing"]]
        problems += [f"404.html: {m}" for m in nf["links_missing"]] + ([] if nf["exists"] else ["404.html missing"])
        problems += [f"{i['page']}: mobile {i['rule']} {i['detail']}" for i in mob["issues"]]
        problems += [f"{i['page']}: a11y {i['rule']}" for i in ac["issues"]]
        problems += [f"style.css: contrast {f['scheme']} {f['pair']} = {f['ratio']}" for f in cn["failures"]]
        if cn["schemes_checked"] != 2:
            problems.append("style.css: light and dark schemes not both found")
        problems += [f"{p}: footer disclosure missing" for p in cc["footer_missing"]]
        problems += cc["xml_errors"] + cc["latest_day_problems"]
        problems += [f"sitemap.xml: no <loc> for {p}" for p in cc["sitemap_missing"]]
        problems += [f"robots: {i}" for i in bj["robots_check"]["issues"]]
        problems += [f"sitemap: missing {p}" for p in bj["sitemap_check"]["missing_pages"]] + [f"sitemap: bad lastmod {p}" for p in bj["sitemap_check"]["bad_lastmod"]]
        problems += [f"{m['page']}: number {m['key']} html={m['html']} json={m['json']}" for m in nc["mismatches"]]
        problems += [f"{m['page']}: nested data-k {m['key']}" for m in nc["nested"]]
        if nc["selftest"] != "pass":
            problems.append("numbers_check selftest failed")
        problems += [f"{m['page']}: missing {m['tag']}" for m in mc["missing"]]
        problems += [f"{b['page']}: dead link {b['href']}" for b in lc["broken"]]
        for pr in problems:
            log.error("check: %s", pr)
        log.info("check: %d problems", len(problems))
        if problems:
            return 1
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
