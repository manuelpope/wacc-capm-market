"""The wiki is part of the repository, so it has to hold together.

A broken link in the documentation is a small thing, but it is the kind of
thing nobody notices for a year. These tests keep the pages well-formed and
keep their links pointing at pages that exist.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

from wacc_lab.config import WIKI_DIR

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

EXPECTED_PAGES = {
    "index.html",
    "quickstart.html",
    "methodology.html",
    "analyst.html",
    "sensitivity.html",
    "interface.html",
    "api.html",
    "architecture.html",
    "limits.html",
}


class PageChecker(HTMLParser):
    """A minimal well-formedness check, and a collector of the links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.errors: list[str] = []
        self.links: list[str] = []
        self.has_sidebar = False
        self.has_script = False
        self.has_stylesheet = False
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"])
        if tag == "nav" and attributes.get("id") == "sidebar":
            self.has_sidebar = True
        if tag == "script" and attributes.get("src"):
            self.has_script = True
        if tag == "link" and attributes.get("href", "").endswith(".css"):
            self.has_stylesheet = True
        if tag == "title":
            self._in_title = True
        if tag not in VOID_TAGS:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in VOID_TAGS:
            return
        if not self.stack:
            self.errors.append(f"stray </{tag}> at line {self.getpos()[0]}")
            return
        open_tag, open_line = self.stack.pop()
        if open_tag != tag:
            self.errors.append(
                f"</{tag}> at line {self.getpos()[0]} closes <{open_tag}> "
                f"opened at line {open_line}"
            )

    def handle_data(self, data):
        if self._in_title:
            self.title += data.strip()


def pages() -> list[Path]:
    return sorted(WIKI_DIR.glob("*.html"))


def test_the_wiki_ships_with_the_repository():
    assert WIKI_DIR.is_dir(), "the docs folder is missing"
    assert {page.name for page in pages()} == EXPECTED_PAGES
    assert (WIKI_DIR / "assets" / "wiki.css").is_file()
    assert (WIKI_DIR / "assets" / "wiki.js").is_file()


@pytest.mark.parametrize("page", pages(), ids=lambda page: page.name)
def test_a_page_is_well_formed(page: Path):
    checker = PageChecker()
    checker.feed(page.read_text(encoding="utf-8"))
    checker.close()

    assert checker.errors == []
    assert checker.stack == [], f"unclosed: {checker.stack}"
    assert checker.title, "the page has no title"
    assert checker.has_sidebar, "the page has no navigation"
    assert checker.has_script, "the page does not load the navigation script"
    assert checker.has_stylesheet, "the page does not load the stylesheet"


@pytest.mark.parametrize("page", pages(), ids=lambda page: page.name)
def test_every_local_link_of_a_page_points_at_something(page: Path):
    checker = PageChecker()
    checker.feed(page.read_text(encoding="utf-8"))
    checker.close()

    for link in checker.links:
        if link.startswith(("http://", "https://", "#", "mailto:")):
            continue
        target = (page.parent / link.split("#")[0]).resolve()
        assert target.exists(), f"{page.name} points at a missing {link}"
