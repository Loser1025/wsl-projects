#!/usr/bin/env python3
import cloudinary
import cloudinary.uploader
import re

# Cloudinaryの設定（直接APIキーを指定）
cloudinary.config(
  cloud_name = 'dztwqjquc',  # 例: 'mycloud' → ここにあなたのCloud Nameを入力
  api_key = '698269648359199',      # 例: '123456789012345' → ここにあなたのAPI Keyを入力
  api_secret = 'YOUR_API_SECRET'   # 例: 'abcdefghijklmnopqrstuvwxyz' → ここにあなたのAPI Secretを入力
)

# 画像をアップロード
result = cloudinary.uploader.upload('/home/loser/wsl-projects/1f7492b96a3432bfc244db7e6a15e7e8.png')
image_url = result['secure_url']
print(f"Uploaded Image URL: {image_url}")

# index.htmlを更新
index_file_path = '/home/loser/wsl-projects/nameplates-deploy/public/index.html'
with open(index_file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# 背景画像のURLを置換
updated_content = re.sub(
    r'background: url\("https://res\.cloudinary\.com/demo/image/upload/v[0-9]+/your-image\.jpg"\)',
    f'background: url("{image_url}")',
    content
)

with open(index_file_path, 'w', encoding='utf-8') as file:
    file.write(updated_content)

print("index.html has been updated with the new image URL.")