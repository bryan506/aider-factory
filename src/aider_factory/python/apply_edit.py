import sys
import os

def apply_edits_from_string(patch_content):
    lines = patch_content.splitlines()
    
    current_file = None
    search_lines = []
    replace_lines = []
    
    # State machine: SCANNING, IN_SEARCH, IN_REPLACE
    state = "SCANNING" 
    edits_by_file = {}
    
    # 1. Parse using a strict state machine (fixes Issues 2 & 5)
    for line in lines:
        if state == "SCANNING":
            if line.startswith("--- "):
                current_file = line[4:].strip()
                if current_file not in edits_by_file:
                    edits_by_file[current_file] = []
            elif line == "<<<<<<< SEARCH":
                if not current_file:
                    print("❌ Error: '<<<<<<< SEARCH' found before a file path '--- file.ext'")
                    return
                state = "IN_SEARCH"
                search_lines = []
        elif state == "IN_SEARCH":
            if line == "=======":
                state = "IN_REPLACE"
                replace_lines = []
            else:
                search_lines.append(line)
        elif state == "IN_REPLACE":
            if line == ">>>>>>> REPLACE":
                edits_by_file[current_file].append({
                    "search": "\n".join(search_lines),
                    "replace": "\n".join(replace_lines)
                })
                state = "SCANNING"
            else:
                replace_lines.append(line)

    if state != "SCANNING":
        print("❌ Error: Incomplete SEARCH/REPLACE block. Missing '=======' or '>>>>>>> REPLACE'.")
        return

    # 2. Apply edits strictly
    for filepath, edits in edits_by_file.items():
        if not os.path.exists(filepath):
            print(f"❌ Error: Target file '{filepath}' not found.")
            continue
            
        with open(filepath, 'r', encoding='utf-8') as f:
            file_content = f.read()

        edits_applied = 0
        failed = False
        
        for idx, edit in enumerate(edits):
            search_text = edit['search']
            replace_text = edit['replace']
            
            # Fix Issue 3: Empty SEARCH string
            if not search_text:
                print(f"❌ Error in {filepath}: SEARCH block #{idx+1} is empty. This would corrupt the file.")
                failed = True
                break
                
            # Fix Issue 1: Exact match requirement
            match_count = file_content.count(search_text)
            
            if match_count == 0:
                print(f"\n⚠️  Failed: Could not find exact SEARCH match in {filepath} (Block #{idx+1})")
                print("--- SEARCH BLOCK LOOKED FOR ---")
                print(search_text)
                print("-------------------------------")
                failed = True
                break
            elif match_count > 1:
                print(f"❌ Error in {filepath}: SEARCH block #{idx+1} matches {match_count} times in the file.")
                print("⚠️  You MUST provide more context lines (above and below) to make the SEARCH block unique.")
                failed = True
                break
            
            # Fix Issue 4: Sequential application operates safely because match_count == 1
            file_content = file_content.replace(search_text, replace_text)
            edits_applied += 1
            
        if not failed and edits_applied > 0:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(file_content)
            print(f"✅ Success: Applied {edits_applied} edit(s) to {filepath}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        if not os.path.exists(file_path):
            print(f"❌ Error: Patch file '{file_path}' not found.")
            sys.exit(1)
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    else:
        content = sys.stdin.read()
        
    if not content.strip():
        print("❌ Error: No input provided.")
        sys.exit(1)
        
    apply_edits_from_string(content)
