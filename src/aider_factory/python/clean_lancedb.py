#!/usr/bin/env python3
"""clean_lancedb.py — Cross-platform Python equivalent of bash/clean_lancedb_runs.sh.

Cleans ephemeral artifacts (images, validations, debates) for a specific RAG collection.
LanceDB tables, PDF/MD sources, and chat histories remain untouched.

Usage:
    aider-clean-lancedb <collection_name>
    python clean_lancedb.py <collection_name>
    python clean_lancedb.py <collection_name> --project-dir /path/to/project
"""

import argparse
import os
import shutil
import sys


def _empty_dir(path, label):
    """Remove all contents of a directory without removing the directory itself.

    Returns the number of items removed. Prints a summary line if any items
    were removed. Handles non-existent directories gracefully (returns 0).
    Errors on individual items are reported to stderr but do not halt execution.
    """
    if not path or not os.path.isdir(path):
        return 0
    count = 0
    for item in os.listdir(path):
        item_path = os.path.join(path, item)
        try:
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
            count += 1
        except OSError as e:
            print(f"  ⚠️  Could not remove {item_path}: {e}", file=sys.stderr)
    if count:
        print(f" -> Emptied {label}: {path} ({count} item(s))")
    return count


def main():
    """Entry point: parse args, validate collection, clean artifacts."""
    parser = argparse.ArgumentParser(
        description=(
            "Clean ephemeral RAG artifacts (images, validations, debates) "
            "for a specific collection. LanceDB tables, PDF/MD sources, "
            "and chat histories remain untouched."
        ),
    )
    parser.add_argument(
        "collection",
        help="Name of the RAG collection (e.g. summer_intern_papers)",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project root directory (default: current working directory)",
    )
    args = parser.parse_args()

    project_dir = args.project_dir or os.getcwd()
    collection = args.collection.strip()

    if not collection:
        print("Error: collection name cannot be empty.", file=sys.stderr)
        sys.exit(1)

    # Resolve the collection directory
    context_dir = os.path.join(
        project_dir, ".aider_factory", "markdown", "lanceDB", collection
    )

    if not os.path.isdir(context_dir):
        print(
            f"Error: Collection directory does not exist at {context_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Cleaning artifacts for collection: '{collection}'...")

    # 1. Remove OCR images directory completely
    image_dir = os.path.join(context_dir, "images")
    if os.path.isdir(image_dir):
        print(f" -> Removing images directory: {image_dir}")
        shutil.rmtree(image_dir)

    # 2. Empty validation logs (fixed location, not per-collection)
    af_dir = os.path.join(project_dir, ".aider_factory")
    validation_dir = os.path.join(af_dir, "logs", "validations")
    _empty_dir(validation_dir, "validation logs")

    # 3. Empty debate logs (fixed location, not per-collection)
    debate_dir = os.path.join(af_dir, "logs", "debates")
    _empty_dir(debate_dir, "debate logs")

    print()
    print(
        "✅ Cleanup complete. LanceDB tables, PDF/MD sources, "
        "and chat histories remain untouched."
    )


if __name__ == "__main__":
    main()
