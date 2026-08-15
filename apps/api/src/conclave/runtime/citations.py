"""Pull source citations out of a provider's response.

Each provider shapes web-search results differently:

- Anthropic returns `web_search_tool_result` blocks plus per-text-block
  `citations`.
- OpenAI's Responses API annotates *text* blocks with `url_citation`s — but when
  the expert answers through a tool call there is no text block, so the sources
  have to come from the `web_search_call` blocks, whose `action` records each
  page the model opened.

This walks the content defensively and returns a de-duplicated list; a shape we
don't recognise yields nothing rather than breaking a turn.
"""

from __future__ import annotations

from typing import Any

MAX_CITATIONS = 40


def extract_citations(content: Any) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}

    def add(url: Any, title: Any = None) -> None:
        if not isinstance(url, str) or not url.startswith("http"):
            return
        if url in found or len(found) >= MAX_CITATIONS:
            return
        text = title if isinstance(title, str) and title.strip() else url
        found[url] = {"url": url, "title": text[:200]}

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        if not isinstance(node, dict):
            return
        # Direct hit: any dict carrying a url alongside a title-ish field.
        if "url" in node:
            add(node.get("url"), node.get("title") or node.get("page_title"))
        for key in ("content", "citations", "annotations", "results", "sources", "action"):
            if key in node:
                walk(node[key], depth + 1)

    walk(content)
    return list(found.values())


# Block types that mean "a search actually ran", across providers.
_SEARCH_BLOCKS = {"web_search_call", "web_search_tool_result", "server_tool_use"}


def used_web_search(content: Any) -> bool:
    """A search can run and yield no extractable URL (a query with no page
    opened), which is still worth telling the reader about."""
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind in _SEARCH_BLOCKS and "search" in str(kind) + str(block.get("name", "")):
            return True
    return False
