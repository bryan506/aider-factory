#!/usr/bin/env python3
# aggregate_costs.py — Standalone utility to parse and aggregate token/cost logs.
#
# Reads a log file in a single pass, extracts token counts and costs,
# and computes the total run cost using the exact sum of message costs.

import os
import re
import sys

COST_PATTERN = re.compile(
    r"Tokens:\s*(?P<sent>[0-9.]+[kM]?)\s*sent,\s*(?P<recv>[0-9.]+[kM]?)\s*received\.\s*"
    r"Cost:\s*\$\s*(?P<msg>[0-9.]+)\s*message,\s*\$\s*(?P<sess>[0-9.]+)\s*session",
    re.IGNORECASE,
)


def parse_tokens(token_str):
    """Normalize token counts with metric suffixes to integers."""
    token_str = token_str.lower().strip()
    if token_str.endswith("k"):
        return int(float(token_str[:-1]) * 1000)
    elif token_str.endswith("m"):
        return int(float(token_str[:-1]) * 1000000)
    try:
        return int(token_str)
    except ValueError:
        return 0


def aggregate_log(log_path: str):
    """Parse log file and print cost analysis report."""
    if not os.path.isfile(log_path):
        print(f"Error: File not found: {log_path}")
        return None

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    matches = list(COST_PATTERN.finditer(content))
    if not matches:
        print("No cost entries found in log.")
        return None

    total_sent = 0
    total_recv = 0
    total_msg_cost = 0.0

    for m in matches:
        d = m.groupdict()
        sent = parse_tokens(d["sent"])
        recv = parse_tokens(d["recv"])
        msg_cost = float(d["msg"])

        total_sent += sent
        total_recv += recv
        total_msg_cost += msg_cost

    print("=" * 70)
    print(f"COST ANALYSIS REPORT: {os.path.basename(log_path)}")
    print("=" * 70)
    print(f"Total Cost Entries Found:       {len(matches)}")
    print(f"Total Tokens Sent:              {total_sent:,}")
    print(f"Total Tokens Received:          {total_recv:,}")
    print("-" * 70)
    print(f"Total Run Cost:                 ${total_msg_cost:.4f}")
    print("=" * 70)

    return {
        "entries": len(matches),
        "sent": total_sent,
        "received": total_recv,
        "cost": total_msg_cost,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: aggregate_costs.py <path_to_log_file>")
        sys.exit(1)

    aggregate_log(sys.argv[1])


if __name__ == "__main__":
    main()
