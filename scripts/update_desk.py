#!/usr/bin/env python3
"""Rebuild the Journal Research Desk (desk/index.html) from all eight blogs.

Run once a day by .github/workflows/update-desk.yml. It downloads every
published post from each blog, keeps one copy of any article that appears on
more than one blog (the most recent copy, using the same rule as the catalog),
and writes the post list into desk/template.html to make desk/index.html.

Because it rebuilds from the live blogs each time, it also picks up edited
titles, tags and text, and drops posts that were deleted.

Safety: if any blog cannot be read, or the number of posts falls by more than
2% compared with the current desk, nothing is written and the run fails, so a
bad day on one of the blog hosts never empties the app.

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
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from update_channels import find_duplicates, html_to_text  # same duplicate rule as the catalog

DESK = os.path.join(ROOT, "desk")
TEMPLATE = os.path.join(DESK, "template.html")
OUTPUT = os.path.join(DESK, "index.html")
MAX_DROP = 0.02

# id: (name, slug, source). Source is a WordPress site or "substack".
BLOGS = {
    1: ("Active Objection", "active-objection", "substack"),
    8: ("Channels Into Knowledge", "channels-into-knowledge", "channelsintoknowledge.com"),
    6: ("First Nation-Farmer Unity", "first-nation-farmer-unity", "firstnationfarmer.com"),
    5: ("LANDBACK Friends", "landback-friends", "landbackfriends.com"),
    3: ("New Conscientious Objector (NewCO)", "new-conscientious-objector", "newconscientiousobjector.com"),
    4: ("Quakers and Mutual Aid (formerly Quakers and Religious Socialism)", "quakers-and-mutual-aid", "quakersandreligioussocialism.com"),
    7: ("Quakers, social justice and revolution", "quakers-social-justice-and-revolution", "jeffkisling.com"),
    2: ("Unflinching", "unflinching", "unflinching.blog"),
}
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


def fetch_substack(sid):
    """Returns (posts, complete). Substack often refuses requests from cloud
    servers such as GitHub's, so this falls back to the blog's RSS feed, which
    lists only the most recent posts (complete=False)."""
    try:
        return fetch_substack_api(sid), True
    except Exception as e:
        print(f"Active Objection: full list unavailable ({e}); using the RSS feed.", flush=True)
    req = urllib.request.Request("https://activeobjection.substack.com/feed", headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        root = ET.fromstring(r.read())
    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    out = []
    for it in root.iter("item"):
        out.append({"s": sid, "t": it.findtext("title") or "", "u": it.findtext("link"),
                    "published": parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "html": it.findtext("content:encoded", default="", namespaces=ns),
                    "terms": [c.text for c in it.findall("category") if c.text], "sub": it.findtext("description") or ""})
    return out, False


def fetch_substack_api(sid):
    arch, off = [], 0
    while True:
        a, _ = get(f"https://activeobjection.substack.com/api/v1/archive?sort=new&offset={off}&limit=50")
        if not a:
            break
        arch += a
        off += len(a)

    def one(a):
        p, _ = get(f"https://activeobjection.substack.com/api/v1/posts/{a['slug']}")
        return {"s": sid, "t": p["title"], "u": p.get("canonical_url"),
                "published": iso_utc(p["post_date"]), "html": p.get("body_html") or "",
                "terms": [t["name"] for t in p.get("postTags", [])], "sub": p.get("subtitle") or ""}
    with ThreadPoolExecutor(4) as ex:
        return list(ex.map(one, arch))


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


def main():
    current = current_data()
    old = len(current["posts"])
    raw, partial = [], set()
    for sid, (name, slug, src) in BLOGS.items():
        try:
            if src == "substack":
                got, complete = fetch_substack(sid)
                if not complete:
                    partial.add(sid)
            else:
                got = fetch_wordpress(sid, src)
        except Exception as e:
            sys.exit(f"Stopped: could not read {name} ({e}). The desk was not changed.")
        if not got:
            sys.exit(f"Stopped: {name} returned no posts. The desk was not changed.")
        print(f"{name}: {len(got)} posts", flush=True)
        raw += got

    posts = []
    for p in raw:
        if not p["u"] or not p["published"]:
            continue
        tags = []
        for t in p["terms"]:
            t = html.unescape(t).strip()
            if t and t.lower() not in SKIP_TAGS and t.lower() not in (x.lower() for x in tags):
                tags.append(t)
        posts.append({"s": p["s"], "t": html.unescape(p["t"]).strip() or "(untitled)",
                      "sub": html.unescape(p["sub"]).strip(), "u": p["u"], "d": p["published"][:10],
                      "x": html_to_text(p["html"]), "html": p["html"], "tags": tags})

    # A blog read only through its feed: keep the posts already in the desk as
    # they are, and add only feed posts the desk does not have yet.
    carried = []
    if partial:
        names = [b["name"] for b in current["blogs"]]
        for e in current["posts"]:
            sid = next((s for s in partial if names[e["b"]] == BLOGS[s][0]), None)
            if sid:
                carried.append((sid, e))
        known = {e["u"] for _, e in carried} | {u for _, e in carried for u in e.get("a", [])}
        posts = [p for p in posts if not (p["s"] in partial and p["u"] in known)]
        print(f"Kept {len(carried)} posts already in the desk from blogs read through their feed.")

    hidden, also = find_duplicates(posts)
    hidden = set(hidden)
    keep = [p for p in posts if p["u"] not in hidden]

    if old and len(keep) + len(carried) < old * (1 - MAX_DROP):
        sys.exit(f"Stopped: found {len(keep) + len(carried)} posts but the desk has {old}. "
                 "One of the blogs may be having trouble. The desk was not changed.")

    order = sorted(BLOGS, key=lambda sid: BLOGS[sid][0].lower())
    bidx = {sid: i for i, sid in enumerate(order)}
    entries = []
    for p in keep:
        text = body_text(p["html"])
        fallback = clean(p["sub"] or first_sentence(p["x"]) or "")
        words = set(w for w in re.findall(r"[a-z0-9][a-z0-9'’-]{2,}", text.lower()) if w not in STOP)
        entries.append({"t": p["t"], "d": p["d"], "b": bidx[p["s"]], "u": p["u"], "g": p["tags"],
                        "s": summarize(text, fallback), "w": len(text.split()),
                        "a": [u for _, _, u in also.get(p["u"], [])], "x": " ".join(sorted(words))})
    if partial:
        # Keep links to copies on a feed-only blog that this run could not compare.
        prev = {e["u"]: e for e in current["posts"]}
        for e in entries:
            for u in prev.get(e["u"], {}).get("a", []):
                if u not in e["a"] and "substack.com" in u:
                    e["a"].append(u)
    for sid, e in carried:
        entries.append(dict(e, b=bidx[sid]))
    entries.sort(key=lambda e: (e["d"], e["u"]), reverse=True)

    blogs = []
    for sid in order:
        dates = [e["d"] for e in entries if e["b"] == bidx[sid]]
        blogs.append({"name": BLOGS[sid][0], "slug": BLOGS[sid][1], "count": len(dates),
                      "first": min(dates) if dates else "", "last": max(dates) if dates else ""})

    data = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "blogs": blogs, "posts": entries}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = open(TEMPLATE, encoding="utf-8").read().replace("__DATA__", blob)

    # Leave the file alone when only the date changed, so quiet days make no commit.
    if os.path.exists(OUTPUT):
        prev = open(OUTPUT, encoding="utf-8").read()
        strip = lambda s: re.sub(r'"generated":"\d{4}-\d\d-\d\d"', "", s)
        if strip(prev) == strip(page):
            print(f"No changes. {len(entries)} posts.")
            return
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    print(f"Wrote desk/index.html: {len(entries)} posts (was {old}), {sum(len(e["a"]) for e in entries)} copies linked.")


if __name__ == "__main__":
    main()
