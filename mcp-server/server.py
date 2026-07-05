"""Lattice lookup MCP server — keyless external sources for verification and exploration.

Tools:
  - wikipedia_search(query)       → matching article titles
  - wikipedia_summary(title)      → summary extract + canonical URL
  - semantic_scholar_search(query)→ recent papers (title, abstract, year, url)
  - web_lookup(query)             → DuckDuckGo Instant Answer abstract, keyless
  - read_url(url)                 → readable text extracted from any URL the user pastes

All endpoints are keyless public APIs. Every tool returns a JSON string and never
raises — failures come back as {"error": ...} so the agent can carry on.
"""

import json
import re
from html.parser import HTMLParser

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("lattice-lookup")

_UA = {"User-Agent": "Lattice/0.1 (learning app; contact: local)"}
_TIMEOUT = 12.0


async def _get_json(url: str, params: dict | None = None) -> dict | list:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA, follow_redirects=True) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def wikipedia_search(query: str) -> str:
    """Search Wikipedia for article titles matching a query. Returns up to 6 titles with snippets."""
    try:
        data = await _get_json(
            "https://en.wikipedia.org/w/api.php",
            {"action": "query", "list": "search", "srsearch": query, "srlimit": 6, "format": "json"},
        )
        hits = data.get("query", {}).get("search", [])
        return json.dumps(
            [
                {"title": h["title"], "snippet": _strip_html(h.get("snippet", ""))}
                for h in hits
            ]
        )
    except Exception as exc:
        return json.dumps({"error": f"wikipedia_search failed: {exc}"})


@mcp.tool()
async def wikipedia_summary(title: str) -> str:
    """Fetch the lead summary of a Wikipedia article by its exact title, with the canonical URL. Use to verify a fact."""
    try:
        data = await _get_json(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}"
        )
        return json.dumps(
            {
                "title": data.get("title", title),
                "extract": data.get("extract", ""),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            }
        )
    except Exception as exc:
        return json.dumps({"error": f"wikipedia_summary failed: {exc}"})


@mcp.tool()
async def semantic_scholar_search(query: str) -> str:
    """Search Semantic Scholar for academic papers. Returns up to 5 papers (title, year, abstract, url) for going deeper on a claim."""
    try:
        data = await _get_json(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            {"query": query, "limit": 5, "fields": "title,year,abstract,url,authors"},
        )
        papers = data.get("data", []) if isinstance(data, dict) else []
        return json.dumps(
            [
                {
                    "title": p.get("title", ""),
                    "year": p.get("year"),
                    "abstract": (p.get("abstract") or "")[:600],
                    "url": p.get("url", ""),
                    "authors": [a.get("name", "") for a in (p.get("authors") or [])][:4],
                }
                for p in papers
            ]
        )
    except Exception as exc:
        return json.dumps({"error": f"semantic_scholar_search failed: {exc}"})


@mcp.tool()
async def web_lookup(query: str) -> str:
    """General keyless web lookup via DuckDuckGo Instant Answer. Returns an abstract and source URL when available."""
    try:
        data = await _get_json(
            "https://api.duckduckgo.com/",
            {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
        )
        related = [
            t.get("Text", "")
            for t in data.get("RelatedTopics", [])
            if isinstance(t, dict) and t.get("Text")
        ][:4]
        return json.dumps(
            {
                "abstract": data.get("AbstractText", ""),
                "source": data.get("AbstractURL", ""),
                "heading": data.get("Heading", ""),
                "related": related,
            }
        )
    except Exception as exc:
        return json.dumps({"error": f"web_lookup failed: {exc}"})


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


class _TextExtractor(HTMLParser):
    """Minimal readability pass: drop script/style/nav chrome, keep block text."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header"}
    _BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in self._BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        else:
            self.chunks.append(data)

    def text(self) -> str:
        raw = "".join(self.chunks)
        lines = [ln.strip() for ln in raw.splitlines()]
        lines = [ln for ln in lines if ln]
        return "\n".join(lines)


@mcp.tool()
async def read_url(url: str) -> str:
    """Fetch a URL the user pasted (article, blog post, show notes, etc.) and return its readable
    text and title. Use this whenever a user drops a link and wants it discussed, summarized, or
    turned into a card — do not rely on prior knowledge of the URL. Truncates very long pages."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return json.dumps(
                    {"error": f"Unsupported content-type '{content_type}' for {url}"}
                )
            parser = _TextExtractor()
            parser.feed(resp.text)
            text = parser.text()
            if len(text) > 12000:
                text = text[:12000] + "\n\n[truncated]"
            return json.dumps(
                {"url": str(resp.url), "title": parser.title.strip(), "text": text}
            )
    except Exception as exc:
        return json.dumps({"error": f"read_url failed for {url}: {exc}"})


if __name__ == "__main__":
    mcp.run()
