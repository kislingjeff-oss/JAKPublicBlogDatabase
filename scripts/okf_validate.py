#!/usr/bin/env python3
"""Check a directory against the OKF v0.2 conformance rules (SPEC §11).

  1. Every non-reserved .md file has a parseable YAML frontmatter block.
  2. Every frontmatter block has a non-empty `type`.
  3. index.md carries no frontmatter, except the bundle root, which may
     carry `okf_version` and nothing else (§8, §12).
  4. log.md carries no frontmatter, and its date headings are YYYY-MM-DD (§9).

Also checks, as SHOULD-level warnings: `generated.by` / `verified[].by` use
the actor convention (§7), every `sources` entry has a `resource` (§5.1),
and `status` is draft | stable | deprecated (§5.4).

Usage: python3 scripts/okf_validate.py [bundle-dir]   (default: repo root)
Exit status 1 when the bundle is not conformant.
"""
import os
import re
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required: pip install pyyaml")

SKIP_DIRS = {".git", ".github", "node_modules"}
ACTOR = re.compile(r"^(human:\S+|process:\S+|[^\s/:]+/\S+)$")


def frontmatter(text):
    if not text.startswith("---\n"):
        return None, "no frontmatter block"
    end = text.find("\n---", 4)
    if end == -1:
        return None, "frontmatter block is not closed"
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError as e:
        return None, f"frontmatter is not valid YAML ({e.__class__.__name__})"
    if not isinstance(data, dict):
        return None, "frontmatter is not a mapping"
    return data, None


def check(root):
    errors, warnings, concepts = [], [], 0
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for name in sorted(files):
            if not name.endswith(".md"):
                continue
            path = os.path.join(d, name)
            rel = os.path.relpath(path, root)
            text = open(path, encoding="utf-8").read()
            if name == "index.md":
                if text.startswith("---\n"):
                    fm, err = frontmatter(text)
                    if os.path.dirname(rel):
                        errors.append(f"{rel}: index.md below the bundle root must not carry frontmatter")
                    elif err or set(fm) - {"okf_version"}:
                        errors.append(f"{rel}: root index.md frontmatter may hold only okf_version")
                continue
            if name == "log.md":
                if text.startswith("---\n"):
                    errors.append(f"{rel}: log.md must not carry frontmatter")
                for ln in text.splitlines():
                    if ln.startswith("## ") and not re.fullmatch(r"## \d{4}-\d{2}-\d{2}", ln.strip()):
                        errors.append(f"{rel}: date heading is not YYYY-MM-DD: {ln.strip()!r}")
                continue
            concepts += 1
            fm, err = frontmatter(text)
            if err:
                errors.append(f"{rel}: {err}")
                continue
            if not str(fm.get("type") or "").strip():
                errors.append(f"{rel}: missing non-empty `type`")
            gen = fm.get("generated")
            if gen is not None:
                if not isinstance(gen, dict) or not gen.get("by"):
                    warnings.append(f"{rel}: generated needs a `by` actor")
                elif not ACTOR.match(str(gen["by"])):
                    warnings.append(f"{rel}: generated.by {gen['by']!r} does not follow the actor convention")
            ver = fm.get("verified")
            for v in ([ver] if isinstance(ver, dict) else ver or []):
                if not isinstance(v, dict) or not ACTOR.match(str(v.get("by", ""))):
                    warnings.append(f"{rel}: verified entry needs a `by` actor")
            for s in fm.get("sources") or []:
                if not isinstance(s, dict) or not s.get("resource"):
                    warnings.append(f"{rel}: every sources entry needs a `resource`")
            if "status" in fm and fm["status"] not in ("draft", "stable", "deprecated"):
                warnings.append(f"{rel}: status should be draft, stable or deprecated")
    return concepts, errors, warnings


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                           os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    concepts, errors, warnings = check(root)
    for e in errors:
        print("ERROR  ", e)
    for w in warnings:
        print("WARNING", w)
    verdict = "CONFORMANT" if not errors else "NOT CONFORMANT"
    print(f"OKF v0.2: {verdict} — {concepts} concept documents, "
          f"{len(errors)} errors, {len(warnings)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
