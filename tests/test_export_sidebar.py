import unittest

from tools.export_sidebar import bookmarks, recover


def fixture(items, roots, spaces=None):
    return {
        "version": 1,
        "sidebar": {"containers": [
            {"global": {}},
            {"items": [x for pair in items.items() for x in pair],
             "topAppsContainerIDs": [],
             "spaces": spaces or ["space", {"title": "Work", "newContainerIDs": [{"pinned": {}}, roots[0]], "containerIDs": roots}]},
        ]},
    }


def tab(url, title="Example"):
    return {"data": {"tab": {"savedURL": url, "savedTitle": title}}, "childrenIds": []}


class SidebarExportTests(unittest.TestCase):
    def test_recovers_nested_and_orphaned_tabs_including_duplicate_urls(self):
        items = {
            "root": {"title": "Folder", "data": {"list": {}}, "childrenIds": ["a"]},
            "a": tab("https://example.com/"),
            "orphan": tab("https://example.com/"),
        }
        result = recover(fixture(items, ["root"]))
        self.assertEqual(result["tab_count"], 2)
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(bookmarks(result)[0].count("<A HREF="), 2)

    def test_refuses_cycles(self):
        items = {"root": {"data": {"list": {}}, "childrenIds": ["root"]}}
        with self.assertRaisesRegex(ValueError, "Cycle"):
            recover(fixture(items, ["root"]))

    def test_refuses_missing_children(self):
        items = {"root": {"data": {"list": {}}, "childrenIds": ["absent"]}}
        with self.assertRaisesRegex(ValueError, "absent"):
            recover(fixture(items, ["root"]))

    def test_html_escapes_titles_and_keeps_executable_urls_in_json_only(self):
        items = {"root": tab("https://example.com/?a=1&b=2", '<script>"&'), "other": tab("javascript:alert(1)")}
        result = recover(fixture(items, ["root"]))
        html, omitted = bookmarks(result)
        self.assertIn("&lt;script&gt;&quot;&amp;", html)
        self.assertIn("?a=1&amp;b=2", html)
        self.assertNotIn("javascript:", html)
        self.assertEqual(omitted, 1)
        self.assertEqual(result["tab_count"], 2)


if __name__ == "__main__":
    unittest.main()
