import re

with open('/tmp/mimic_subagent_single_5ndsjzh4/merged/api/index.js', 'r') as f:
    content = f.read()

# 修正案: confirmUrl に export=download を追加
old_str = "https://drive.google.com/uc?export=download&confirm=${token}&id=${fileId}&uuid=${uuid}"
new_str = "https://drive.google.com/uc?export=download&confirm=${token}&id=${fileId}&uuid=${uuid}"
# 上記はすでに入っていた。何が足りないか？

# もしかして、URLパラメータの順序や export が足りない？
# 以前の調査：name="export" value="download" 
# confirmUrl = `https://drive.google.com/uc?export=download&confirm=${token}&id=${fileId}&uuid=${uuid}`
# これで合っているはずだが...
# 試しに全パラメータを含めるように修正する
# 構造: https://drive.google.com/uc?export=download&id=...&confirm=...&uuid=...

# もう一度確認:
# file2.bin でのパラメータ抽出：
# name="id" value="..."
# name="export" value="download"
# name="confirm" value="t"
# name="uuid" value="..."

# コードを書き換える
import re
new_content = re.sub(r'const confirmUrl = `https://drive\.google\.com/uc\?export=download&confirm=\${token}&id=\${fileId}&uuid=\${uuid}`;',
                     'const confirmUrl = `https://drive.google.com/uc?export=download&id=${fileId}&confirm=${token}&uuid=${uuid}`;',
                     content)

with open('/tmp/mimic_subagent_single_5ndsjzh4/merged/api/index.js', 'w') as f:
    f.write(new_content)
