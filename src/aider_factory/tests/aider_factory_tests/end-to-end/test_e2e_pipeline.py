#!/usr/bin/env python3
# test_e2e_pipeline.py — End-to-End Golden Smoke Test for AI Factory Pipeline

import json
import os
import shutil
import subprocess
import sys

print("==================================================")
print("Starting E2E Golden Smoke Test (Academic + Code)...")
print("==================================================")

# 1. Path Resolution
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(script_dir, "../../../../.."))

academic_config_path = os.path.join(script_dir, "env_e2e_academic.yml")
code_config_path = os.path.join(script_dir, "env_e2e_code.yml")
source_pdf = os.path.join(script_dir, "January-2026-FX-Report.pdf")

# Academic paths
academic_collection = "e2e_golden_smoke"
academic_job_dir = os.path.join(
    project_dir, ".aider_factory", "markdown", "lanceDB", academic_collection
)
academic_output_md = os.path.join(
    project_dir, ".aider_factory", "tests", "aider_factory_tests", "end-to-end", "January-2026-FX-Report.md"
)
validation_report = os.path.join(
    project_dir, ".aider_factory", "logs", "validations", "January-2026-FX-Report.gate.md"
)
validation_ledger = os.path.join(
    project_dir, ".aider_factory", "logs", "validations", "January-2026-FX-Report.ledger.json"
)

# Code paths
code_collection = "e2e_code_golden_smoke"
code_job_dir = os.path.join(
    project_dir, ".aider_factory", "markdown", "lanceDB", code_collection
)
generated_test_file = os.path.join(
    project_dir, "tests", "testthat", "test-unit-fut_aac.R"
)

# 2. Cleanup Previous Runs
print("[E2E] Cleaning up previous run artifacts...")
for d in (
    academic_job_dir,
    code_job_dir,
    os.path.join(script_dir, ".aider_factory", "logs", "validations"),
    os.path.join(script_dir, ".aider_factory", "logs", "debates"),
):
    if os.path.exists(d):
        shutil.rmtree(d)

for f in (academic_output_md,):
    if os.path.exists(f):
        os.remove(f)

# 3. Bootstrap Academic Collection & Copy Source PDF
print(f"[E2E] Bootstrapping academic collection directory: {academic_job_dir}")
os.makedirs(academic_job_dir, exist_ok=True)
dest_pdf = os.path.join(academic_job_dir, "January-2026-FX-Report.pdf")
print(f"[E2E] Copying source PDF: {source_pdf} -> {dest_pdf}")
shutil.copy2(source_pdf, dest_pdf)

# Copy validation scripts to .aider_factory/tests/aider_factory_tests/end-to-end/ so the pipeline finds them
dest_val_dir = os.path.join(project_dir, ".aider_factory", "tests", "aider_factory_tests", "end-to-end")
os.makedirs(dest_val_dir, exist_ok=True)
shutil.copy2(os.path.join(script_dir, "validations_context_check.sh"), os.path.join(dest_val_dir, "validations_context_check.sh"))

# Bootstrap Code Collection & Copy Source Code
code_repo_dir = os.path.join(code_job_dir, "BaseFeatures", "R")
print(f"[E2E] Bootstrapping code collection directory: {code_repo_dir}")
os.makedirs(code_repo_dir, exist_ok=True)
source_code = os.path.join(script_dir, "fut_aac.R")
dest_code = os.path.join(code_repo_dir, "fut_aac.R")
print(f"[E2E] Copying source code: {source_code} -> {dest_code}")
shutil.copy2(source_code, dest_code)

# 4. Execute Phase 1: Academic / Literary Review
print("\n[E2E] Execute Phase 1: Academic Pathway...")
python_bin = sys.executable
workflow_script = os.path.join(project_dir, "src", "aider_factory", "python", "run_workflow.py")

try:
    res = subprocess.run(
        [python_bin, workflow_script, academic_config_path],
        capture_output=True,
        text=True,
        check=True,
    )
    print("[E2E] Academic Pathway completed successfully.")
    print(res.stdout)
except subprocess.CalledProcessError as e:
    print(
        "[E2E] Academic Pathway failed with exit code:", e.returncode, file=sys.stderr
    )
    print("STDOUT:\n", e.stdout, file=sys.stderr)
    print("STDERR:\n", e.stderr, file=sys.stderr)
    sys.exit(e.returncode)

# 5. Execute Phase 2: Code Implementation & Testing
print("\n[E2E] Execute Phase 2: Code Pathway...")
try:
    res = subprocess.run(
        [python_bin, workflow_script, code_config_path],
        capture_output=True,
        text=True,
        check=True,
    )
    print("[E2E] Code Pathway completed successfully.")
    print(res.stdout)
except subprocess.CalledProcessError as e:
    print("[E2E] Code Pathway failed with exit code:", e.returncode, file=sys.stderr)
    print("STDOUT:\n", e.stdout, file=sys.stderr)
    print("STDERR:\n", e.stderr, file=sys.stderr)
    sys.exit(e.returncode)

# 6. Assertions & Validation
print("\n[E2E] Running assertions...")

# ------------------------------------------------------------------------
# ASSERTIONS: Phase 1 (Academic / Literary Review)
# ------------------------------------------------------------------------
print("\n[E2E] Verifying Phase 1 (Academic Pathway)...")

# A. Check OCR Output File
ocr_md_file = os.path.join(academic_job_dir, "January-2026-FX-Report.md")
assert os.path.exists(ocr_md_file), f"OCR Markdown file not created: {ocr_md_file}"
print(f"  ✅ OCR Markdown file exists: {ocr_md_file}")

# B. Check LanceDB Table
import lancedb

db = lancedb.connect(os.path.join(academic_job_dir, "lancedb"))
tables = db.table_names()
expected_table = "January-2026-FX-Report"
assert expected_table in tables, (
    f"Expected table '{expected_table}' not found in LanceDB tables: {tables}"
)
tbl = db.open_table(expected_table)
assert tbl.count_rows() > 0, f"Table '{expected_table}' is empty"
print(f"  ✅ LanceDB table '{expected_table}' created with {tbl.count_rows()} chunks.")

# C. Check Generated Review Output
assert os.path.exists(academic_output_md), (
    f"Generated review file not found: {academic_output_md}"
)
print(f"  ✅ Generated review file exists: {academic_output_md}")
with open(academic_output_md, "r", encoding="utf-8") as f:
    content = f.read()
    assert "[evidence]" in content or "[validated]" in content, (
        "Generated review contains no [evidence] or [validated] anchors"
    )
    print("  ✅ Generated review contains valid grounding anchors.")

# D. Check Grounding Ledger & Report
assert os.path.exists(validation_ledger), (
    f"Grounding ledger not found: {validation_ledger}"
)
print(f"  ✅ Grounding ledger exists: {validation_ledger}")
with open(validation_ledger, "r", encoding="utf-8") as f:
    ledger = json.load(f)
    assert "attempts" in ledger, "Validation ledger is empty or malformed"
    print("  ✅ Grounding ledger contains validation attempts.")

# ------------------------------------------------------------------------
# ASSERTIONS: Phase 2 (Code / Testing)
# ------------------------------------------------------------------------
print("\n[E2E] Verifying Phase 2 (Code Pathway)...")

# A. Check LanceDB Tables
code_db = lancedb.connect(os.path.join(code_job_dir, "lancedb"))
code_tables = code_db.table_names()
assert any("e2e_code_golden_smoke" in t for t in code_tables), (
    f"Expected code tables not found in LanceDB: {code_tables}"
)
print(f"  ✅ Code LanceDB tables created: {code_tables}")

# B. Check Generated Test File
assert os.path.exists(generated_test_file), (
    f"Generated test file not found: {generated_test_file}"
)
print(f"  ✅ Generated test file exists: {generated_test_file}")
with open(generated_test_file, "r", encoding="utf-8") as f:
    test_content = f.read()
    assert "test_that" in test_content, (
        "Generated test file does not contain test_that blocks"
    )
    print("  ✅ Generated test file contains valid R unit tests.")

print("\n🎉 E2E Golden Smoke Test Completed Successfully for Both Pathways!")
