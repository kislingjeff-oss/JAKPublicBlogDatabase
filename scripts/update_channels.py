#!/usr/bin/env python3
"""Refresh the blog database with posts from Channels Into Knowledge.

What it does, every run:
  1. Reads every published post from https://channelsintoknowledge.com/
     through the WordPress REST API.
  2. Rewrites JAK_New_Writings.js (the "additions" file the catalog page
     loads after JAK_Writings_Data.js) with all of them, newest first.
  3. Regenerates the OKF v0.2 records in blogs/ (one per blog) and
     blogs/index.md, so the bundle always describes what the catalog holds.
  4. Adds a dated entry to log.md naming any posts that are new since the
     last run.

The output depends only on the blog's content, so a run that finds nothing
new changes nothing, and the workflow makes no commit.

Standard library only; run from the repository root:
    python3 scripts/update_channels.py
"""
import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_URL = "https://channelsintoknowledge.com"
API = SITE_URL + "/wp-json/wp/v2/posts?per_page=100&page={page}&_embed=wp:term"
SITE = {"id": 8, "name": "Channels Into Knowledge", "url": SITE_URL}
SKIP_TERMS = {"uncategorized"}
UPDATER = "process:jak-blog-db-update/1"
AUTHOR = "human:jkisling"

# Short descriptions of each blog for its OKF record. Keyed by source id.
BLOG_SLUGS = {
    1: "active-objection",
    2: "unflinching",
    3: "new-conscientious-objector",
    4: "quakers-and-mutual-aid",
    5: "landback-friends",
    6: "first-nation-farmer-unity",
    7: "quakers-social-justice-and-revolution",
    8: "channels-into-knowledge",
}


# ---------------------------------------------------------------- fetching
def fetch_posts():
    posts, page = [], 1
    while True:
        req = urllib.request.Request(
            API.format(page=page),
            headers={"User-Agent": "JAKPublicBlogDatabase-updater/1"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                batch = json.load(r)
                total_pages = int(r.headers.get("X-WP-TotalPages", "1"))
        except urllib.error.HTTPError as e:
            if e.code == 400 and page > 1:  # past the last page
                break
            raise
        posts.extend(batch)
        if page >= total_pages or not batch:
            break
        page += 1
    return posts


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6",
             "blockquote", "figure", "figcaption", "tr", "ul", "ol", "pre", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "iframe", "noscript"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "iframe", "noscript"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(s):
    p = _Text()
    p.feed(s or "")
    text = "".join(p.out).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def to_record(post):
    terms = []
    for group in post.get("_embedded", {}).get("wp:term", []):
        for t in group:
            name = html.unescape(t.get("name", "")).strip()
            if name and name.lower() not in SKIP_TERMS and name not in terms:
                terms.append(name)
    text = html_to_text(post["content"]["rendered"])
    return {
        "s": SITE["id"],
        "t": html.unescape(post["title"]["rendered"]).strip(),
        "b": "",
        "u": post["link"],
        "d": post["date"][:10],
        "w": len(text.split()),
        "tags": sorted(terms, key=str.lower),
        "x": text,
    }


# ------------------------------------------------------------- data files
def load_js(path, var):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    start = src.index("=", src.index(var)) + 1
    return json.loads(src[start:].strip().rstrip(";"))


def write_additions(records, hidden, also):
    """hidden: URLs of duplicate copies the catalog leaves out.
    also: {kept URL: [[blog id, date, URL], ...]} copies of that post."""
    path = os.path.join(ROOT, "JAK_New_Writings.js")
    data = {"sites": [SITE], "posts": records, "hide": hidden, "also": also}
    body = "window.JAK_ADDITIONS = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if old != body:
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
    return old


# -------------------------------------------------------------- OKF output
def yq(s):
    """Quote a string for YAML."""
    return json.dumps(s, ensure_ascii=False)


def blog_summary(base, records, hidden=frozenset()):
    """Per-blog facts: name, url, count, first/last date, top tags."""
    tags = base["tags"]
    out = {}
    for s in base["sources"]:
        out[s["id"]] = {"name": s["name"], "url": s["url"], "dates": [], "tags": {}, "hidden": 0}
    out[SITE["id"]] = {"name": SITE["name"], "url": SITE["url"], "dates": [], "tags": {}, "hidden": 0}
    for p in base["posts"]:
        b = out[p["s"]]
        b["dates"].append(p["d"])
        b["hidden"] += p["u"] in hidden
        for i in p["g"]:
            b["tags"][tags[i]] = b["tags"].get(tags[i], 0) + 1
    for p in records:
        b = out[p["s"]]
        b["dates"].append(p["d"])
        b["hidden"] += p["u"] in hidden
        for t in p["tags"]:
            b["tags"][t] = b["tags"].get(t, 0) + 1
    return out


def write_if_changed(path, text):
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
    if old != text:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    return False


def write_blog_records(summary):
    rows = []
    for sid in sorted(summary, key=lambda k: min(summary[k]["dates"] or ["9999"])):
        b = summary[sid]
        slug = BLOG_SLUGS[sid]
        n = len(b["dates"])
        first, last = min(b["dates"]), max(b["dates"])
        top = sorted(b["tags"].items(), key=lambda kv: (-kv[1], kv[0].lower()))[:12]
        desc = f"{b['name']}, {n:,} posts from {first} to {last}."
        fm = [
            "---",
            "type: Blog",
            f"title: {yq(b['name'])}",
            f"description: {yq(desc)}",
            f"resource: {b['url']}",
            "tags: [blog, writings]",
            "status: stable",
            f"author: {yq('Jeff Kisling')}",
            f"generated: {{ by: {UPDATER}, at: {last}T00:00:00Z }}",
            "sources:",
            "  - id: blog",
            f"    resource: {b['url']}",
            f"    title: {yq(b['name'])}",
            f"    author: {AUTHOR}",
            f"    last_modified: {last}T00:00:00Z",
            "  - id: catalog",
            "    resource: https://kislingjeff-oss.github.io/JAKPublicBlogDatabase/",
            "    title: \"Jeff Kisling's Journal (searchable catalog)\"",
            f"    author: {AUTHOR}",
            "---",
            "",
        ]
        body = [
            f"# {b['name']}",
            "",
            f"Blog by Jeff Kisling at <{b['url']}>.[^blog]",
            "",
            "| | |",
            "|---|---|",
            f"| Posts published | {n:,} |",
            f"| Shown in the catalog | {n - b['hidden']:,} |",
            f"| Left out as copies of a newer post on another blog | {b['hidden']:,} |",
            f"| First post | {first} |",
            f"| Most recent post | {last} |",
            "",
            "Every post is searchable in the [complete catalog]"
            "(https://kislingjeff-oss.github.io/JAKPublicBlogDatabase/).[^catalog]",
            "",
        ]
        if top:
            body += ["# Most-used tags", ""]
            body += [f"* {t} ({c})" for t, c in top]
            body += [""]
        body += [
            f"[^blog]: {b['name']}",
            "[^catalog]: Jeff Kisling's Journal",
            "",
        ]
        write_if_changed(os.path.join(ROOT, "blogs", slug + ".md"), "\n".join(fm + body))
        rows.append((b["name"], slug, desc))

    idx = ["# Blogs", ""]
    idx += [f"* [{name}]({slug}.md) - {desc}" for name, slug, desc in rows]
    write_if_changed(os.path.join(ROOT, "blogs", "index.md"), "\n".join(idx) + "\n")


def update_log(new_posts):
    if not new_posts:
        return
    path = os.path.join(ROOT, "log.md")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = open(path, encoding="utf-8").read().split("\n") if os.path.exists(path) else ["# Update Log", ""]
    if len(new_posts) > 10:
        first = min(p["d"] for p in new_posts)
        last = max(p["d"] for p in new_posts)
        entries = [
            f"* **Update**: Added {len(new_posts)} posts ({first} to {last}) from "
            f"[Channels Into Knowledge](/blogs/channels-into-knowledge.md)."
        ]
    else:
        entries = [
            f"* **Update**: Added [{p['t']}]({p['u']}) ({p['d']}) from "
            f"[Channels Into Knowledge](/blogs/channels-into-knowledge.md)."
            for p in sorted(new_posts, key=lambda p: p["d"])
        ]
    heading = f"## {today}"
    if heading in lines:
        i = lines.index(heading) + 1
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        lines[i:i] = entries
    else:
        i = next((k for k, ln in enumerate(lines) if ln.startswith("## ")), len(lines))
        lines[i:i] = [heading] + entries + [""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")


# ------------------------------------------------------------- duplicates
# Posts were copied between blogs (Active Objection -> Channels Into
# Knowledge, Unflinching <-> New Conscientious Objector, and others). Two
# posts on DIFFERENT blogs are the same article when their text is nearly
# identical, or when they share a title and most of their text. Reposts
# within one blog (yearly commemorations, revised versions) are left alone.
# From each group the most recent post is kept; on a tie, the post on the
# newer blog.
NEAR_IDENTICAL = 0.90      # share of 6-word phrases in common (Jaccard)
SAME_TITLE_OVERLAP = 0.60
BLOG_AGE = {7: 0, 6: 1, 5: 2, 4: 3, 2: 4, 3: 5, 1: 6, 8: 7}  # oldest -> newest


def _norm_title(t):
    t = html.unescape(t).lower().replace("’", "'").replace("‘", "'")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _shingles(text, k=6):
    w = re.findall(r"[a-z0-9']+", html.unescape(text).lower())
    return {hash(" ".join(w[i:i + k])) for i in range(max(0, len(w) - k + 1))}


def find_duplicates(posts):
    """posts: list of dicts with s, t, u, d, x. Returns (hidden_urls, also)."""
    S = [_shingles(p.get("x", "")) for p in posts]
    T = [_norm_title(p["t"]) for p in posts]
    inv = {}
    for i, s in enumerate(S):
        for h in s:
            inv.setdefault(h, []).append(i)
    parent = list(range(len(posts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, s in enumerate(S):
        if not s:
            continue
        shared = {}
        for h in s:
            bucket = inv[h]
            if len(bucket) > 50:        # boilerplate phrase, not evidence
                continue
            for j in bucket:
                if j > i and posts[j]["s"] != posts[i]["s"]:
                    shared[j] = shared.get(j, 0) + 1
        for j, c in shared.items():
            jac = c / len(s | S[j])
            if jac >= NEAR_IDENTICAL or (jac >= SAME_TITLE_OVERLAP and T[i] == T[j]):
                parent[find(i)] = find(j)

    groups = {}
    for i in range(len(posts)):
        groups.setdefault(find(i), []).append(i)
    hidden, also = [], {}
    for members in groups.values():
        if len(members) < 2:
            continue
        keep = max(members, key=lambda i: (posts[i]["d"], BLOG_AGE.get(posts[i]["s"], 0)))
        others = sorted((i for i in members if i != keep), key=lambda i: posts[i]["d"], reverse=True)
        hidden += [posts[i]["u"] for i in others]
        also[posts[keep]["u"]] = [[posts[i]["s"], posts[i]["d"], posts[i]["u"]] for i in others]
    return sorted(hidden), dict(sorted(also.items()))


# --------------------------------------------------------------------- main
def main():
    posts = fetch_posts()
    if not posts:
        sys.exit("No posts returned from Channels Into Knowledge; leaving files untouched.")
    records = sorted((to_record(p) for p in posts), key=lambda r: (r["d"], r["u"]), reverse=True)

    prev_path = os.path.join(ROOT, "JAK_New_Writings.js")
    prev = load_js(prev_path, "JAK_ADDITIONS") if os.path.exists(prev_path) else {"posts": []}
    seen = {p.get("u") for p in prev.get("posts", [])}
    new_posts = [r for r in records if r["u"] not in seen]

    base = load_js(os.path.join(ROOT, "JAK_Writings_Data.js"), "JAK_DATA")
    hidden, also = find_duplicates(base["posts"] + records)
    write_additions(records, hidden, also)
    write_blog_records(blog_summary(base, records, set(hidden)))
    update_log(new_posts)

    print(f"Channels Into Knowledge: {len(records)} posts, {len(new_posts)} new.")
    print(f"Duplicates across blogs: {len(hidden)} copies left out, {len(also)} posts kept.")
    for r in new_posts[:20]:
        print(f"  + {r['d']}  {r['t']}")


if __name__ == "__main__":
    main()
