import re
with open('api/index.js', 'r') as f:
    content = f.read()
pattern = r"app\.post\('/api/analyze/drive',\s*async\s*\(req,\s*res\)\s*=>\s*\{"
match = re.search(pattern, content)
if match:
    start = match.start()
    brace_count = 0
    i = start
    while i < len(content):
        ch = content[i]
        if ch == '{':
            brace_count += 1
        elif ch == '}':
            brace_count -= 1
            if brace_count == 0:
                print(content[start:i+1])
                break
        i += 1
