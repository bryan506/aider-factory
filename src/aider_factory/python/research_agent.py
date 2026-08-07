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


def run_sitemap_harvester(target_url, grep_pat=None, grep_ex_pat=None, depth=1, out_path=None):
    """Fetch sitemap(s), parse XML <loc> tags, apply case-insensitive regex filtering,
    and save clean URL list to out_path."""
    import xml.etree.ElementTree as ET
    from urllib.parse import urlparse

    # 1. Domain / URL Normalization
    if not target_url.startswith(("http://", "https://")):
        target_url = "https://" + target_url.lstrip("/")

    parsed = urlparse(target_url)
    domain = parsed.netloc or parsed.path.split("/")[0]

    # Resolve target XML endpoint
    sitemap_url = target_url
    if not target_url.lower().endswith(".xml") and "sitemap" not in target_url.lower():
        sitemap_url = f"{parsed.scheme}://{domain}/sitemap.xml"

    visited_sitemaps = set()
    discovered_urls = []

    def _fetch_xml(url):
        try:
            r = requests.get(url, headers={"User-Agent": "AI-Factory/1.0"}, timeout=15)
            if r.status_code == 200:
                return r.content
        except Exception as e:
            print(f"[sitemap] Failed to fetch {url}: {e}", file=sys.stderr)
        return None

    def _parse_sitemap(url, current_depth):
        if url in visited_sitemaps or current_depth > depth or len(visited_sitemaps) >= 50:
            return
        visited_sitemaps.add(url)

        xml_bytes = _fetch_xml(url)
        if not xml_bytes and current_depth == 1 and not url.endswith("robots.txt"):
            # Fallback to robots.txt to discover official Sitemap: directives
            robots_url = f"{parsed.scheme}://{domain}/robots.txt"
            try:
                rr = requests.get(robots_url, headers={"User-Agent": "AI-Factory/1.0"}, timeout=10)
                if rr.status_code == 200:
                    for line in rr.text.splitlines():
                        if line.lower().startswith("sitemap:"):
                            sm_found = line.split(":", 1)[1].strip()
                            _parse_sitemap(sm_found, current_depth)
            except Exception:
                pass
            return

        if not xml_bytes:
            return

        try:
            root = ET.fromstring(xml_bytes)
        except Exception as e:
            print(f"[sitemap] XML parse error for {url}: {e}", file=sys.stderr)
            return

        # Extract all <loc> text regardless of XML namespace
        for elem in root.iter():
            tag_name = elem.tag.split("}", 1)[1] if "}" in elem.tag else elem.tag
            if tag_name.lower() == "loc" and elem.text and elem.text.strip():
                val = elem.text.strip()
                if val.lower().endswith(".xml") or "sitemap" in val.lower():
                    _parse_sitemap(val, current_depth + 1)
                else:
                    discovered_urls.append(val)

    print(f"[sitemap] Crawling sitemap: {sitemap_url} (max_depth={depth})...", file=sys.stderr)
    _parse_sitemap(sitemap_url, 1)

    # 2. Deduplicate
    unique_urls = list(dict.fromkeys(discovered_urls))
    total_found = len(unique_urls)

    # 3. Apply Case-Insensitive Anywhere-Matching Regex Filtering (-i / re.search)
    filtered_urls = unique_urls
    if grep_pat:
        try:
            rx = re.compile(grep_pat, re.IGNORECASE)
            filtered_urls = [u for u in filtered_urls if rx.search(u)]
        except re.error as e:
            print(f"Error: Invalid --grep regex pattern '{grep_pat}': {e}", file=sys.stderr)
            sys.exit(1)

    if grep_ex_pat:
        try:
            rx_ex = re.compile(grep_ex_pat, re.IGNORECASE)
            filtered_urls = [u for u in filtered_urls if not rx_ex.search(u)]
        except re.error as e:
            print(f"Error: Invalid --grep-exclude regex pattern '{grep_ex_pat}': {e}", file=sys.stderr)
            sys.exit(1)

    # 4. Resolve Output File Path
    if not out_path:
        domain_stem = rag_manager.table_name_for(domain)
        out_path = os.path.join(".aider_factory", "markdown", "research", f"{domain_stem}_sitemap.txt")

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        for u in filtered_urls:
            f.write(u + "\n")

    # 5. Summary Output
    print(f"\n[sitemap] Discovery Complete for '{domain}':", file=sys.stderr)
    print(f"          - Total URLs Discovered: {total_found}", file=sys.stderr)
    print(f"          - URLs Matched Filter:  {len(filtered_urls)}", file=sys.stderr)
    print(f"          - Output File:          {out_path}\n", file=sys.stderr)

    for u in filtered_urls:
        print(u)

    return out_path


def main():
    if len(sys.argv) < 2:
        print(
            'usage: aider-research search "<query>" [--academic] [--engines e1,e2] [--top N] [--time-range day|month|year]\n'
            '   or: aider-research search "<url>" --sitemap [--grep "<pat>"] [--grep-exclude "<pat>"] [--site-depth N] [--out <file>]\n'
            '   or: aider-research search --file <query.txt> [--academic] [--top N]'
        )
        sys.exit(0)

    args = sys.argv[1:]
    if args[0] == "search":
        args = args[1:]

    # Route A: Sitemap Harvester
    if "--sitemap" in args:
        target_url = None
        grep_pat = None
        grep_ex_pat = None
        depth = 1
        out_path = None

        i = 0
        while i < len(args):
            a = args[i]
            if a == "--sitemap":
                i += 1
            elif a in ("--grep", "-g") and i + 1 < len(args):
                grep_pat = args[i + 1]
                i += 2
            elif a in ("--grep-exclude", "-ge") and i + 1 < len(args):
                grep_ex_pat = args[i + 1]
                i += 2
            elif a in ("--site-depth", "-d") and i + 1 < len(args):
                depth = int(args[i + 1])
                i += 2
            elif a in ("--out", "-o") and i + 1 < len(args):
                out_path = args[i + 1]
                i += 2
            elif not a.startswith("-") and target_url is None:
                target_url = a
                i += 1
            else:
                i += 1

        if not target_url:
            print("Error: Target URL or domain required for --sitemap mode.", file=sys.stderr)
            sys.exit(1)

        run_sitemap_harvester(target_url, grep_pat, grep_ex_pat, depth, out_path)
        return

    # Route B: SearXNG Search (Default)
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
            args = args[:idx] + args[idx + 2 :]

    if query is None and args and not args[0].startswith("-"):
        query = args[0]
        args = args[1:]

    if not query:
        print("Error: search query required (positional argument or --file <path>).", file=sys.stderr)
        sys.exit(1)

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
