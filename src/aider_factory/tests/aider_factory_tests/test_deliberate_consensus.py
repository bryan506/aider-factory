#!/usr/bin/env python3
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
python_module_dir = os.path.abspath(os.path.join(script_dir, "../../python"))
sys.path.insert(0, python_module_dir)

import deliberate

print("Starting Deliberate Consensus Tests...\n")

# Test 1: Clean Agreement
ledger_agreed = {
    "turns": [
        {"role": "architect", "proposal": "Fix the math."},
        {"role": "oracle", "verdict": "agree"}
    ]
}
assert deliberate.consensus_state(ledger_agreed) == "agreed"
print("✅ Consensus: Agreed PASS")

# Test 2: Deadlock (Architect repeats proposal, Oracle still objects)
ledger_deadlock = {
    "turns": [
        {"role": "architect", "proposal": "Fix the math.", "proposal_hash": "hash1"},
        {"role": "oracle", "verdict": "object"},
        {"role": "architect", "proposal": "Fix the math.", "proposal_hash": "hash1"},
        {"role": "oracle", "verdict": "object"}
    ]
}
assert deliberate.consensus_state(ledger_deadlock) == "deadlock"
print("✅ Consensus: Deadlock PASS")

# Test 3: Continue (Architect changes proposal after object)
ledger_continue = {
    "turns": [
        {"role": "architect", "proposal": "Fix the math.", "proposal_hash": "hash1"},
        {"role": "oracle", "verdict": "object"},
        {"role": "architect", "proposal": "Use different math.", "proposal_hash": "hash2"}
    ]
}
assert deliberate.consensus_state(ledger_continue) == "continue"
print("✅ Consensus: Continue PASS")
