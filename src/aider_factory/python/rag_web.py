#!/usr/bin/env python3
# rag_web.py — Web content fetching, classification, OpenAPI/llms.txt extraction,
# and Trafilatura/Playwright Markdown conversion for LanceDB ingestion.

import os
import sys
import requests
import trafilatura
from urllib.parse import urlparse
import rag_manager


def fetch_sitemap_urls(sitemap_url, max_depth=1):
    """Extract child page URLs from a sitemap XML URL."""
    import xml.etree.ElementTree as ET

    visited = set()
    urls = []

    def _recurse(u, depth):
        if u in visited or depth > max_depth or len(visited) >= 50:
            return
        visited.add(u)
        try:
            r = requests.get(u, headers={"User-Agent": "AI-Factory/1.0"}, timeout=15)
            if r.status_code != 200:
                return
            root = ET.fromstring(r.content)
            for elem in root.iter():
                if "}" in elem.tag:
                    elem.tag = elem.tag.split("}", 1)[1]
            for loc in root.findall(".//url/loc"):
                if loc.text and loc.text.strip():
                    urls.append(loc.text.strip())
            for loc in root.findall(".//sitemap/loc"):
                if loc.text and loc.text.strip():
                    _recurse(loc.text.strip(), depth + 1)
        except Exception:
            pass

    _recurse(sitemap_url, 1)
    return list(dict.fromkeys(urls))


def fetch_urls_batch(urls, job_dir, workers=1):
    """Fetch and convert a batch of URLs concurrently using ThreadPoolExecutor.
    Returns (success_count, skipped_count)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    expanded_urls = []
    for u in urls:
        if u.lower().endswith(".xml") or "sitemap" in u.lower():
            sm_urls = fetch_sitemap_urls(u)
            if sm_urls:
                print(f"[rag-web] Expanded sitemap '{u}' -> {len(sm_urls)} URLs", file=sys.stderr)
                expanded_urls.extend(sm_urls)
            else:
                expanded_urls.append(u)
        else:
            expanded_urls.append(u)

    unique_urls = list(dict.fromkeys(expanded_urls))
    total = len(unique_urls)
    success_count = 0
    skipped_count = 0

    if workers > 1 and total > 1:
        print(f"[rag-web] Batch fetching {total} URLs ({workers} workers)...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_and_convert_url, url, job_dir): url for url in unique_urls}
            for fut in as_completed(futures):
                try:
                    saved, _ = fut.result()
                    if saved:
                        success_count += 1
                    else:
                        skipped_count += 1
                except Exception as e:
                    print(f"[rag-web] Worker error for {futures[fut]}: {e}", file=sys.stderr)
                    skipped_count += 1
    else:
        for url in unique_urls:
            saved, _ = fetch_and_convert_url(url, job_dir)
            if saved:
                success_count += 1
            else:
                skipped_count += 1

    return success_count, skipped_count


def fetch_and_convert_url(url, job_dir):
    """Fetch URL, classify content type, extract clean Markdown or download binary PDF,
    and save into job_dir using the deterministic <stem>.md / <stem>.pdf naming convention.

    Returns (saved_file_path, content_type) or (None, None) on failure.
    """
    os.makedirs(job_dir, exist_ok=True)

    parsed = urlparse(url)
    domain = parsed.netloc.replace(":", "_")
    raw_path_stem = os.path.basename(parsed.path.rstrip("/")) or "index"
    path_stem = rag_manager.table_name_for(raw_path_stem)
    base_stem = f"{domain}_{path_stem}".strip("_")

    headers = {"User-Agent": "Mozilla/5.0 (AI-Factory/1.0; Research Engine)"}

    # 1. Content-Type Sniff via HEAD request (fallback to GET if HEAD fails)
    ctype = ""
    try:
        head_resp = requests.head(
            url, headers=headers, allow_redirects=True, timeout=10
        )
        ctype = head_resp.headers.get("Content-Type", "").lower()
    except Exception:
        pass

    # Step A: Direct PDF Download
    if "application/pdf" in ctype or parsed.path.lower().endswith(".pdf"):
        pdf_path = os.path.join(job_dir, f"{base_stem}.pdf")
        try:
            r = requests.get(url, headers=headers, stream=True, timeout=30)
            r.raise_for_status()
            with open(pdf_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"[rag-web] PDF downloaded: {url} -> {pdf_path}", file=sys.stderr)
            return pdf_path, "pdf"
        except Exception as e:
            print(f"[rag-web] Failed to download PDF {url}: {e}", file=sys.stderr)
            return None, None

    # Step B: llms.txt Check
    if parsed.scheme and parsed.netloc:
        llms_txt_url = f"{parsed.scheme}://{parsed.netloc}/llms.txt"
        if not url.endswith("/llms.txt"):
            try:
                resp = requests.get(llms_txt_url, headers=headers, timeout=5)
                if resp.status_code == 200 and len(resp.text.strip()) > 50:
                    out_path = os.path.join(job_dir, f"{base_stem}_llms.md")
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(
                            f"# Source: {url}\n# llms.txt: {llms_txt_url}\n\n{resp.text}"
                        )
                    print(
                        f"[rag-web] Discovered llms.txt: {llms_txt_url} -> {out_path}",
                        file=sys.stderr,
                    )
                    return out_path, "text_doc"
            except Exception:
                pass

    # Step C: Trafilatura HTML Extraction
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            extracted = trafilatura.extract(
                downloaded,
                output_format="markdown",
                include_tables=True,
                include_links=False,
            )
            if extracted and len(extracted.strip()) >= 100:
                out_path = os.path.join(job_dir, f"{base_stem}.md")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(f"# Source: {url}\n\n{extracted}")
                print(
                    f"[rag-web] Extracted main text via Trafilatura: {url} -> {out_path}",
                    file=sys.stderr,
                )
                return out_path, "text_doc"
    except Exception as e:
        print(
            f"[rag-web] Trafilatura extraction failed for {url}: {e}",
            file=sys.stderr,
        )

    # Step D: Playwright Fallback (for JS-rendered SPAs)
    try:
        from playwright.sync_api import sync_playwright

        def _launch_browser(p_instance):
            try:
                return p_instance.chromium.launch(headless=True)
            except Exception as _e:
                if "Executable doesn't exist" in str(_e) or "playwright install" in str(_e):
                    import subprocess
                    print("[rag-web] Playwright Chromium binary missing. Auto-installing in the background...", file=sys.stderr)
                    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                    return p_instance.chromium.launch(headless=True)
                raise _e

        with sync_playwright() as p:
            browser = _launch_browser(p)
            page = browser.new_page()
            page.goto(url, timeout=15000)
            html_content = page.content()
            browser.close()

            extracted = trafilatura.extract(
                html_content, output_format="markdown", include_tables=True
            )
            if extracted and len(extracted.strip()) > 50:
                out_path = os.path.join(job_dir, f"{base_stem}.md")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(f"# Source: {url}\n\n{extracted}")
                print(
                    f"[rag-web] Extracted via Playwright fallback: {url} -> {out_path}",
                    file=sys.stderr,
                )
                return out_path, "text_doc"
    except Exception as e:
        print(
            f"[rag-web] Playwright fallback unavailable or failed for {url}: {e}",
            file=sys.stderr,
        )

    print(
        f"[rag-web] Could not extract meaningful content from {url}", file=sys.stderr
    )
    return None, None
