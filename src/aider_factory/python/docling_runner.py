#!/usr/bin/env python3
"""docling_runner.py — Standalone isolated entrypoint for Docling conversion.

Invoked out-of-process via `uv run --isolated --with docling>=2.0.0 python -m aider_factory.python.docling_runner ...`
"""

import logging
import os
import sys

logging.getLogger("docling").setLevel(logging.ERROR)


def extract_metadata_header(doc_result) -> str:
    """Extract structural metadata and format as a standard Markdown block."""
    meta_lines = []
    try:
        doc = getattr(doc_result, "document", None)
        if doc is None:
            return ""

        # Check for standard document metadata attributes
        meta = getattr(doc, "metadata", None) or getattr(doc_result, "metadata", None)
        if meta:
            title = getattr(meta, "title", None)
            authors = getattr(meta, "authors", None)
            created = getattr(meta, "creation_date", None) or getattr(meta, "created", None)
            subject = getattr(meta, "subject", None)

            if title:
                meta_lines.append(f"- **Title**: {title}")
            if authors:
                auth_str = ", ".join(authors) if isinstance(authors, list) else str(authors)
                meta_lines.append(f"- **Author(s)**: {auth_str}")
            if created:
                meta_lines.append(f"- **Date**: {created}")
            if subject:
                meta_lines.append(f"- **Subject**: {subject}")
    except Exception:
        pass

    if meta_lines:
        return "# Document Metadata\n\n" + "\n".join(meta_lines) + "\n\n---\n\n"
    return ""


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("Usage: docling_runner.py <input_path> <output_md_path> [do_ocr=true|false]\n")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    do_ocr = sys.argv[3].lower() == "true" if len(sys.argv) > 3 else True

    try:
        from docling.document_converter import DocumentConverter
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import PdfFormatConverter

            opts = PdfPipelineOptions()
            opts.do_ocr = do_ocr
            opts.generate_page_images = False
            converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatConverter(pipeline_options=opts)}
            )
        except Exception:
            converter = DocumentConverter()

        result = converter.convert(input_path)
        body_text = result.document.export_to_markdown()

        if not body_text or len(body_text.strip()) <= 100:
            sys.stderr.write(f"[docling_runner] Extracted text too short ({len(body_text or '')} chars).\n")
            sys.exit(3)

        meta_header = extract_metadata_header(result)
        final_markdown = meta_header + body_text

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(final_markdown)

        sys.exit(0)
    except Exception as exc:
        sys.stderr.write(f"[docling_runner] Error: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
