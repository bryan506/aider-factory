#!/usr/bin/env python3
# research_agent.py — SearXNG search client, research report renderer,
# and web ingestion orchestrator for the AI Factory.

import datetime
import os
import re
import sys
import requests
import rag_manager

SEARXNG_DEFAULT_URL = os.environ.get("SEARXNG_BASE_URL", "http://localhost:8088")


def search_searxng(query, academic=False, engines=None, top=10, time_range=None):
    """Query SearXNG JSON API and return parsed list of result dicts."""
    url = f"{SEARXNG_DEFAULT_URL.rstrip('/')}/search"
    params = {"q": query, "format": "json"}
    if academic:
        params["categories"] = "science"
        params["engines"] = "arxiv,google_scholar,crossref,core"
    elif engines:
        params["engines"] = engines
    if time_range:
        params["time_range"] = time_range

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        return results[:top]
    except Exception as e:
        print(f"[research] SearXNG search failed ({url}): {e}", file=sys.stderr)
        print(
            " -> Ensure SearXNG user service is active: systemctl --user status searxng",
            file=sys.stderr,
        )
        sys.exit(1)


def render_research_report(query, results, engines_used="all"):
    """Write markdown research report to .aider_factory/markdown/research/."""
    slug = rag_manager.table_name_for(query)[:40]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    project_dir = os.getcwd()
    out_dir = os.path.join(project_dir, ".aider_factory", "markdown", "research")
    os.makedirs(out_dir, exist_ok=True)

    out_path = os.path.join(out_dir, f"{slug}_{stamp}_report.md")

    lines = [
        f"# Research Report: {query}",
        f"Generated: {datetime.datetime.now().isoformat()}",
        f"Engines: {engines_used}\n",
        "## Search Results\n",
    ]

    if not results:
        lines.append("No results found for query.")
    else:
        for idx, res in enumerate(results, 1):
            title = res.get("title", "Untitled")
            url = res.get("url", "")
            engine = res.get("engine", "unknown")
            snippet = res.get("content", "").strip()
            lines.append(f"{idx}. **{title}**")
            lines.append(f"   - URL: {url}")
            lines.append(f"   - Source Engine: {engine}")
            lines.append(f"   - Snippet: {snippet}\n")

    content = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(content)
    print(f"\n[research] Report saved to: {out_path}", file=sys.stderr)
    return out_path


def main():
    if len(sys.argv) < 2:
        print(
            'usage: aider-research search "<query>" [--academic] [--engines e1,e2] [--top N] [--time-range day|month|year]\n'
            '   or: aider-research search --file <query.txt> [--academic] [--top N]'
        )
        sys.exit(0)

    args = sys.argv[1:]
    if args[0] == "search":
        args = args[1:]

    query = None
    if "--file" in args:
        idx = args.index("--file")
        if idx + 1 < len(args):
            file_path = args[idx + 1]
            from oracle_agent import _resolve_file_path

            resolved_path = _resolve_file_path(file_path)
            if os.path.isfile(resolved_path):
                with open(resolved_path, "r", encoding="utf-8") as f:
                    query = f.read()
            else:
                print(f"Error: File not found: {resolved_path}", file=sys.stderr)
                sys.exit(1)
            # Remove --file and its argument from opts parsing
            args = args[:idx] + args[idx + 2 :]

    if query is None and args and not args[0].startswith("-"):
        query = args[0]
        args = args[1:]

    if not query:
        print("Error: search query required (positional argument or --file <path>).", file=sys.stderr)
        sys.exit(1)

    # Normalize newlines and excess whitespace in query
    query = re.sub(r"\s+", " ", query).strip()

    opts = args

    academic = "--academic" in opts
    top = 10
    engines = None
    time_range = None

    if "--top" in opts:
        idx = opts.index("--top")
        if idx + 1 < len(opts):
            top = int(opts[idx + 1])
    if "--engines" in opts:
        idx = opts.index("--engines")
        if idx + 1 < len(opts):
            engines = opts[idx + 1]
    if "--time-range" in opts:
        idx = opts.index("--time-range")
        if idx + 1 < len(opts):
            time_range = opts[idx + 1]

    results = search_searxng(
        query, academic=academic, engines=engines, top=top, time_range=time_range
    )
    eng_label = (
        "science (academic)" if academic else (engines or "searxng-default")
    )
    render_research_report(query, results, engines_used=eng_label)


if __name__ == "__main__":
    main()
