---
name: networked-research
description: Search and read the live web for current documentation, APIs, libraries, examples, breaking changes, and unfamiliar technologies. Use when the user asks for online research, current knowledge, web pages, URLs, external docs, internet learning, or when the assistant needs to learn something new from the public web before answering or coding.
---

# Networked Research

Use live web access when local context is not enough.

## Prefer the built-in web tools

- Use `web_search` for internet discovery, current docs, release notes, API references, and unknown technologies.
- Use `web_fetch` to read a specific URL after you already know the page you need.
- These tools work out of the box and do not require the user to configure a search MCP server.

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
