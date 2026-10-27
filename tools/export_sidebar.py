"""Export a copied Arc sidebar to portable JSON and browser bookmarks.

Reads one file; never modifies Arc. Refuses ambiguous maps and cycles rather
than quietly omitting data. Orphaned items get a separate recovered-items folder.
"""

import argparse
from collections import Counter
from html import escape
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def ordered_pairs(value):
    if isinstance(value, dict):
        return list(value.items())
    if not isinstance(value, list) or len(value) % 2:
        raise ValueError("Expected a dictionary or an alternating key/value array")
    return list(zip(value[::2], value[1::2]))


def recover(document):
    groups = []
    expected = Counter()
    recovered = Counter()
    for _, scope in ordered_pairs(document["sidebar"]["containers"]):
        pairs = ordered_pairs(scope["items"])
        items = dict(pairs)
        if len(items) != len(pairs):
            raise ValueError("Duplicate item identifiers")
        seen = set()
        for item in items.values():
            tab = item.get("data", {}).get("tab", {})
            if tab.get("savedURL"):
                expected[tab["savedURL"]] += 1

        def visit(key, ancestors=frozenset()):
            if key in ancestors:
                raise ValueError("Cycle in sidebar item graph")
            if key not in items:
                raise ValueError("Sidebar references an absent item")
            if key in seen:
                return []
            seen.add(key)
            item = items[key]
            tab = item.get("data", {}).get("tab", {})
            children = []
            for child in item.get("childrenIds", []):
                children.extend(visit(child, ancestors | {key}))
            if tab.get("savedURL"):
                url = tab["savedURL"]
                recovered[url] += 1
                node = {"title": item.get("title") or tab.get("savedTitle") or url, "url": url}
                return [node, *children]
            return [{"title": item.get("title") or "Folder", "children": children}] if children else []

        for _, root in ordered_pairs(scope.get("topAppsContainerIDs", [])):
            if root in items:
                nodes = visit(root)
                if nodes:
                    groups.append({"title": "Favorites", "children": nodes})
        for _, space in ordered_pairs(scope.get("spaces", [])):
            roots = [v for _, v in ordered_pairs(space.get("newContainerIDs", []))]
            roots += space.get("containerIDs", [])
            nodes = []
            for root in dict.fromkeys(roots):
                if root in items:
                    nodes.extend(visit(root))
            groups.append({"title": space.get("title") or "Untitled Space", "children": nodes})
        orphans = []
        for key in items:
            if key not in seen:
                orphans.extend(visit(key))
        if orphans:
            groups.append({"title": "Recovered items outside Spaces", "children": orphans})
    if expected != recovered:
        raise ValueError("Recovered URL counts do not match source tab counts")
    return {"format": "artbrowser-sidebar-export-v1", "source_version": document.get("version"), "tab_count": sum(recovered.values()), "groups": groups}


def bookmarks(export):
    lines = ['<!DOCTYPE NETSCAPE-Bookmark-file-1>', '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">', '<TITLE>Recovered Arc bookmarks</TITLE>', '<H1>Recovered Arc bookmarks</H1>', '<DL><p>']
    omitted = 0

    def render(node, indent):
        nonlocal omitted
        title = escape(str(node["title"]))
        if "url" in node:
            # Preserve every scheme in JSON; avoid executable bookmark URLs in HTML.
            if urlsplit(node["url"]).scheme.lower() not in {"http", "https", "file", "arc", "chrome", "about"}:
                omitted += 1
                return
            lines.append(f'{indent}<DT><A HREF="{escape(node["url"], quote=True)}">{title}</A>')
        else:
            lines.extend([f'{indent}<DT><H3>{title}</H3>', f'{indent}<DL><p>'])
            for child in node.get("children", []):
                render(child, indent + "    ")
            lines.append(f'{indent}</DL><p>')

    for group in export["groups"]:
        render(group, "    ")
    lines.append('</DL><p>')
    return "\n".join(lines) + "\n", omitted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidebar", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    source = json.loads(args.sidebar.read_text())
    export = recover(source)
    html, omitted = bookmarks(export)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    json_path = args.output / "sidebar.json"
    html_path = args.output / "bookmarks.html"
    for target in (json_path, html_path):
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite {target}")
    json_path.write_text(json.dumps(export, ensure_ascii=False, indent=2) + "\n")
    html_path.write_text(html)
    print(json.dumps({"tabs_verified_against_source": export["tab_count"], "top_level_groups": len(export["groups"]), "non_web_urls_in_json_only": omitted, "output": str(args.output)}))


if __name__ == "__main__":
    main()
