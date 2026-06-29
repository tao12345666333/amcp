---
name: networked-research
description: Search and read the live web for current documentation, APIs, libraries, examples, breaking changes, and unfamiliar technologies. Use when the user asks for online research, current knowledge, web pages, URLs, external docs, internet learning, or when the assistant needs to learn something new from the public web before answering or coding.
---

# Networked Research

Use live web access when local context is not enough.

## Prefer the built-in web tools

- Use `web_search` for internet discovery, current docs, release notes, API references, and unknown technologies.
- Use `web_fetch` to read a specific URL after you already know the page you need.
- The default `auto` backend tries Exa first when available, then falls back to Firecrawl.

## When to search vs fetch

- Search first when the exact page is unknown.
- Fetch directly when the user gives you a URL or when search already surfaced the right page.
- After searching, fetch the most relevant result if you need details rather than snippets.

## Working style

1. Search with a focused query.
2. Narrow by domain when the user wants official docs or a known website.
3. Fetch the most relevant page or pages.
4. Base your answer or implementation on the fetched content, not on stale model memory.
5. Mention uncertainty if the web results conflict or look incomplete.

## Exa MCP

If Exa MCP tools are visible in the tool list, they are also valid:

- `mcp.exa.web_search_exa`
- `mcp.exa.web_fetch_exa`

Use them the same way you would use `web_search` and `web_fetch`.

## Firecrawl notes

- Firecrawl search can work without an API key for quick starts, though rate limits may be lower.
- Set `FIRECRAWL_API_KEY` (or `AMCP_FIRECRAWL_API_KEY`) for better reliability and for scrape-heavy usage.
