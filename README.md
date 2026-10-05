---
type: Dataset
title: "Jeff Kisling's Journal"
description: "Searchable database of every blog post Jeff Kisling has published since 2015, across eight blogs."
resource: https://kislingjeff-oss.github.io/JAKPublicBlogDatabase/
tags: [blog, writings, catalog]
status: stable
author: "Jeff Kisling"
generated: { by: process:llm-claude-opus-5-5/1, at: 2026-10-04T12:45:00Z }
sources:
  - id: catalog-post
    resource: https://activeobjection.substack.com/p/complete-catalog-of-my-writings
    title: "Complete catalog of my writings, on Active Objection"
    author: human:jkisling
    last_modified: 2026-07-30T00:00:00Z
  - id: channels
    resource: https://channelsintoknowledge.com/
    title: Channels Into Knowledge
    author: human:jkisling
---

# JAKPublicBlogDatabase

A database of all of my blog post writings since 2015, across 8 blogs.

Search it at <https://kislingjeff-oss.github.io/JAKPublicBlogDatabase/> by blog, by year, by tag, or with your own search words.

# Blogs

The eight blogs are described in [blogs/](blogs/index.md). The newest, [Channels Into Knowledge](https://channelsintoknowledge.com/), is kept up to date automatically.[^channels]

# How it is kept current

* `JAK_Writings_Data.js` holds the seven earlier blogs, 2015 to July 2026.
* `JAK_New_Writings.js` holds every post from [Channels Into Knowledge](https://channelsintoknowledge.com/). It is rebuilt by `scripts/update_channels.py`, which a scheduled GitHub Action (`.github/workflows/update-channels.yml`) runs every six hours. New posts appear in the catalog within a few hours of publishing, and each addition is recorded in [log.md](log.md).
* Some articles were copied from one blog to another. The catalog shows each article once, keeping the most recent copy (on a tie, the one on the newer blog) and linking the others under "Also published at". Reposts within the same blog are kept. The rule is in `find_duplicates` in `scripts/update_channels.py`, and it is re-applied on every run, so future copies are handled too.
* The repository is an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) v0.2 bundle. `scripts/okf_validate.py` checks it on every run.

[^channels]: Channels Into Knowledge
