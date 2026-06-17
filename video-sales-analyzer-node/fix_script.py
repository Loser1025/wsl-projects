import re
with open('api/index.js', 'r') as f:
    content = f.read()

# 正規表現で正しく置き換え
new_content = re.sub(
    r'const confirmUrl = .*?;',
    'const confirmUrl = `${downloadUrl}&confirm=${token}`;',
    content
)

with open('api/index.js', 'w') as f:
    f.write(new_content)
