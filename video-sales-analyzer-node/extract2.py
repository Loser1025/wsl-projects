import re
with open('api/index.js', 'r') as f:
    lines = f.readlines()
# Find the line index of the pattern
pattern = r"app\.post\('/api/analyze/drive',\s*async\s*\(req,\s*res\)\s*=>\s*\{"
start_idx = None
for idx, line in enumerate(lines):
    if re.search(pattern, line):
        start_idx = idx
        break
if start_idx is not None:
    brace_count = 0
    end_idx = None
    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        for ch in line:
            if ch == '{':
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = idx
                    break
        if end_idx is not None:
            break
    if end_idx is not None:
        with open('/tmp/function.txt', 'w') as out:
            out.writelines(lines[start_idx:end_idx+1])
        print(f"Function written to /tmp/function.txt, lines {start_idx+1} to {end_idx+1}")
    else:
        print("Could not find matching closing brace")
else:
    print("Pattern not found")
