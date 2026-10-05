#!/usr/bin/env python3
"""Add new Channels Into Knowledge posts to the Journal Research Desk.

Run once a day by .github/workflows/update-desk.yml. It reads every post on
https://channelsintoknowledge.com/ and rebuilds that blog's entries in
desk/index.html, so new posts are added and edited or deleted posts are
updated. Posts from the other seven blogs stay exactly as they are.

When a Channels Into Knowledge post is a copy of an article from another blog,
the older copy is taken out of the list and linked from the new post under
"Also published at", so each article still appears once.

Safety: if the blog cannot be read, or it returns far fewer posts than the
desk already has, nothing is written and the run fails.

Run by hand:  python3 scripts/update_desk.py
Needs:        pip install beautifulsoup4 markdownify
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DESK = os.path.join(ROOT, "desk")
TEMPLATE = os.path.join(DESK, "template.html")
OUTPUT = os.path.join(DESK, "index.html")

BLOG_NAME = "Channels Into Knowledge"
BLOG_SITE = "channelsintoknowledge.com"
MIN_SHARE = 0.5          # stop if the blog returns under half the posts the desk has for it
SAME_TITLE_OVERLAP = 0.6 # share of words in common to call two posts with one title copies
NEAR_IDENTICAL = 0.9     # share of words in common to call two posts copies whatever the title
SKIP_TAGS = {"uncategorized"}
STOP = set("""a an the and or but of to in on at for with by from as is are was were be been being it its this
that these those i me my we our you your he she they them his her their not no so if then than there here what
which who whom whose when where why how all any each few more most other some such only own same too very can will
just do does did have has had into over under again further once up down out off about above below between through
during before after while also would could should may might must shall upon yet nor""".split())
UA = {"User-Agent": "JAK-research-desk/1 (+https://kislingjeff-oss.github.io/JAKPublicBlogDatabase/desk/)"}


# ------------------------------------------------------------------ download
def get(url, tries=5):
    for t in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return json.load(r), r.headers
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                raise
            time.sleep(3 + 5 * t)
        except Exception:
            time.sleep(3 + 5 * t)
    raise RuntimeError(f"Could not read {url}")


def iso_utc(s):
    if not s:
        return None
    s = s.replace(" ", "T")
    if s.endswith("Z") or re.search(r"[+-]\d\d:\d\d$", s):
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_wordpress(sid, site):
    base = (f"https://public-api.wordpress.com/wp/v2/sites/{site}/posts"
            "?per_page=100&_embed=wp:term&status=publish")
    first, headers = get(base + "&page=1")
    pages = int(headers.get("X-WP-TotalPages", "1"))
    with ThreadPoolExecutor(4) as ex:
        rest = list(ex.map(lambda n: get(base + f"&page={n}")[0], range(2, pages + 1)))
    out = []
    for p in first + [x for r in rest for x in r]:
        terms = [t["name"] for g in p.get("_embedded", {}).get("wp:term", []) for t in g]
        out.append({"s": sid, "t": p["title"]["rendered"], "u": p["link"],
                    "published": iso_utc(p.get("date_gmt") or p["date"]),
                    "html": p["content"]["rendered"], "terms": terms, "sub": ""})
    return out


# ------------------------------------------------------------------ text
class MD(MarkdownConverter):
    def convert_img(self, el, text=None, parent_tags=None, **kw):
        return ""


def to_markdown(raw_html):
    soup = BeautifulSoup(raw_html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "form", "button", "svg", "iframe", "figure"]):
        tag.decompose()
    for sel in ["div.sharedaddy", "div.jp-relatedposts", "div.wpcnt", "div.subscription-widget-wrap",
                "div.subscription-widget", "p.button-wrapper", "div.captioned-button-wrap", "div.wp-block-buttons"]:
        for tag in soup.select(sel):
            tag.decompose()
    md = MD(heading_style="ATX", bullets="*", strip=["span", "font"]).convert_soup(soup)
    return re.sub(r"\n{3,}", "\n\n", md.replace("\xa0", " "))


def clean(s):
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_`#>]+", "", s).replace("\\", "")
    return re.sub(r"\s+", " ", s).strip()


def body_text(raw_html):
    """Running text of the post, without quotes, images and embeds."""
    paras = []
    for block in re.split(r"\n\s*\n", to_markdown(raw_html)):
        b = block.strip()
        if not b or b.startswith((">", "![", "---", "|")):
            continue
        c = clean(b)
        if len(c.split()) >= 4:
            paras.append(c)
    return " ".join(paras)


def summarize(text, fallback):
    """The post's own opening sentences, about 35 to 70 words."""
    out, n = [], 0
    for s in re.split(r"(?<=[.!?])\s+", text):
        if n >= 35 and out:
            break
        out.append(s)
        n += len(s.split())
        if n >= 70:
            break
    summary = " ".join(out).strip()
    if len(summary.split()) > 90:
        summary = " ".join(summary.split()[:85]) + "…"
    if len(summary.split()) < 12 and len(fallback.split()) > len(summary.split()):
        summary = fallback
    return summary


def first_sentence(text, limit=220):
    t = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"(.{20,}?[.!?])(\s|$)", t)
    s = m.group(1) if m else t
    return s[:limit].rsplit(" ", 1)[0] + "…" if len(s) > limit else s


# ------------------------------------------------------------------ build
def current_data():
    if not os.path.exists(OUTPUT):
        return {"blogs": [], "posts": []}
    m = re.search(r'id="library-data">(.*?)</script>', open(OUTPUT, encoding="utf-8").read(), re.S)
    return json.loads(m.group(1).replace("<\\/", "</")) if m else {"blogs": [], "posts": []}


def norm_title(s):
    return re.sub(r"[^a-z0-9]+", " ", html.unescape(s).lower()).strip()


def overlap(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def main():
    current = current_data()
    names = [b["name"] for b in current["blogs"]]
    if BLOG_NAME not in names:
        sys.exit(f"Stopped: the desk has no blog named {BLOG_NAME}.")
    bi = names.index(BLOG_NAME)
    previous = {e["u"]: e for e in current["posts"] if e["b"] == bi}
    others = [e for e in current["posts"] if e["b"] != bi]

    try:
        raw = fetch_wordpress(8, BLOG_SITE)
    except Exception as e:
        sys.exit(f"Stopped: could not read {BLOG_NAME} ({e}). The desk was not changed.")
    if len(raw) < len(previous) * MIN_SHARE:
        sys.exit(f"Stopped: {BLOG_NAME} returned {len(raw)} posts but the desk has {len(previous)}. "
                 "The desk was not changed.")
    print(f"{BLOG_NAME}: {len(raw)} posts", flush=True)

    fresh = []
    for p in raw:
        if not p["u"] or not p["published"]:
            continue
        tags = []
        for t in p["terms"]:
            t = html.unescape(t).strip()
            if t and t.lower() not in SKIP_TAGS and t.lower() not in (x.lower() for x in tags):
                tags.append(t)
        text = body_text(p["html"])
        words = set(w for w in re.findall(r"[a-z0-9][a-z0-9'’-]{2,}", text.lower()) if w not in STOP)
        title = html.unescape(p["t"]).strip() or "(untitled)"
        fresh.append({"t": title, "d": p["published"][:10], "b": bi, "u": p["u"], "g": tags,
                      "s": summarize(text, clean(first_sentence(text))), "w": len(text.split()),
                      "a": list(previous.get(p["u"], {}).get("a", [])), "x": " ".join(sorted(words))})

    # Find older copies on the other blogs and fold them into the new post.
    folded = 0
    for e in fresh:
        if e["u"] in previous:
            continue                    # already checked when it was first added
        mine, title = set(e["x"].split()), norm_title(e["t"])
        for o in list(others):
            if o["d"] > e["d"]:
                continue
            share = overlap(mine, set(o["x"].split()))
            same_title = norm_title(o["t"]) == title
            if (same_title and share >= SAME_TITLE_OVERLAP) or (share >= NEAR_IDENTICAL and len(mine) >= 80):
                others.remove(o)
                e["a"] += [u for u in [o["u"]] + o.get("a", []) if u not in e["a"]]
                folded += 1
                print(f"  {e['t']}: copy of {o['u']}")

    added = [e for e in fresh if e["u"] not in previous]
    removed = [u for u in previous if u not in {e["u"] for e in fresh}]
    entries = sorted(others + fresh, key=lambda e: (e["d"], e["u"]), reverse=True)

    blogs = []
    for i, b in enumerate(current["blogs"]):
        dates = [e["d"] for e in entries if e["b"] == i]
        blogs.append(dict(b, count=len(dates), first=min(dates) if dates else "", last=max(dates) if dates else ""))

    data = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "blogs": blogs, "posts": entries}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = open(TEMPLATE, encoding="utf-8").read().replace("__DATA__", blob)

    # Leave the file alone when only the date changed, so quiet days make no commit.
    prev_page = open(OUTPUT, encoding="utf-8").read() if os.path.exists(OUTPUT) else ""
    strip = lambda s: re.sub(r'"generated":"\d{4}-\d\d-\d\d"', "", s)
    if strip(prev_page) == strip(page):
        print(f"No changes. {len(entries)} posts.")
        return
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    print(f"Wrote desk/index.html: {len(entries)} posts. Added {len(added)}, "
          f"removed {len(removed)}, folded in {folded} older copies.")
    for e in added:
        print(f"  new: {e['d']} {e['t']}")


if __name__ == "__main__":
    main()
