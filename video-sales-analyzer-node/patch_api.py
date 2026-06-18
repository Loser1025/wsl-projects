import re

with open('/tmp/mimic_subagent_single_5ndsjzh4/merged/api/index.js', 'r') as f:
    content = f.read()

# 修正案:
# confirmMatch の他に uuid を抽出し、それらを全てURLに含める
old_code = """    const confirmMatch = html.match(/name="confirm" value="([0-9A-Za-z_-]+)"/);
    
    if (confirmMatch) {
      const token = confirmMatch[1];
      console.log(`[DEBUG] confirm token 発見: ${token}`);
      const confirmUrl = `https://drive.google.com/uc?export=download&id=${fileId}&confirm=${token}`;
      console.log(`[DEBUG] 再リクエスト実行URL: ${confirmUrl}`);
      console.log(`[DEBUG] 送信するCookie: ${JSON.stringify(await jar.getCookies(confirmUrl))}`);
      
      const confirmed = await client.get(confirmUrl, {"""

new_code = """    const confirmMatch = html.match(/name="confirm" value="([0-9A-Za-z_-]+)"/);
    const uuidMatch = html.match(/name="uuid" value="([0-9A-Fa-f-]+)"/);
    
    if (confirmMatch) {
      const token = confirmMatch[1];
      const uuid = uuidMatch ? uuidMatch[1] : '';
      console.log(`[DEBUG] confirm token 発見: ${token}, uuid 発見: ${uuid}`);
      // Google Driveのダウンロード用URL構造を再現
      const confirmUrl = `https://drive.google.com/uc?export=download&confirm=${token}&id=${fileId}&uuid=${uuid}`;
      console.log(`[DEBUG] 再リクエスト実行URL: ${confirmUrl}`);
      console.log(`[DEBUG] 送信するCookie: ${JSON.stringify(await jar.getCookies(confirmUrl))}`);
      
      const confirmed = await client.get(confirmUrl, {"""

new_content = content.replace(old_code, new_code)
with open('/tmp/mimic_subagent_single_5ndsjzh4/merged/api/index.js', 'w') as f:
    f.write(new_content)
