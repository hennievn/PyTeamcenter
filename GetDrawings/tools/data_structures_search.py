"""
Search data structure content using ripgrep on the JSONL bundle.
"""
import argparse
import subprocess
import sys
from pathlib import Path
from data_structures_utils import JSONL_PATH

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("term", help="Search term (regex supported by ripgrep).")
    parser.add_argument("--max", "-n", type=int, default=20, help="Max results.")
    args = parser.parse_args()
    
    if not JSONL_PATH.exists():
        print(f"{JSONL_PATH} not found.", file=sys.stderr)
        return 1

    # Construct rg command
    # rg -i "term" --max-columns 300 --no-line-number --no-filename docs/data_structures.jsonl
    cmd = ["rg", "-i", args.term, "--max-columns", "300", "--no-line-number", "--no-filename", str(JSONL_PATH)]
    
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for line_bytes in proc.stdout:
            line = line_bytes.decode("utf-8", errors="replace")
            # Parse ID
            if '"id": "' in line:
                 start = line.find('"id": "') + 7
                 end = line.find('"', start)
                 doc_id = line[start:end]
                 
                 if doc_id in seen:
                     continue
                 seen.add(doc_id)

                 # Extract title if possible
                 title = ""
                 if '"title": "' in line:
                     t_start = line.find('"title": "') + 10
                     t_end = line.find('"', t_start)
                     title = line[t_start:t_end]
                 
                 print(f"{doc_id} | {title}")
                 count += 1
                 if count >= args.max:
                     break
    except FileNotFoundError:
        print("ripgrep ('rg') not found, falling back to slower Python search...", file=sys.stderr)
        import re
        try:
            pattern = re.compile(args.term, re.IGNORECASE)
        except re.error as e:
             print(f"Invalid regex: {e}", file=sys.stderr)
             return 1

        try:
            with open(JSONL_PATH, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if pattern.search(line):
                         if '"id": "' in line:
                             start = line.find('"id": "') + 7
                             end = line.find('"', start)
                             doc_id = line[start:end]
                             
                             if doc_id in seen:
                                 continue
                             seen.add(doc_id)
                             
                             title = ""
                             if '"title": "' in line:
                                 t_start = line.find('"title": "') + 10
                                 t_end = line.find('"', t_start)
                                 title = line[t_start:t_end]
                             
                             print(f"{doc_id} | {title}")
                             count += 1
                             if count >= args.max:
                                 break
        except Exception as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            return 1

    if count == 0:
        print("No matches found.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())