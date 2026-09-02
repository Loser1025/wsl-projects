---
name: youtube-transcript
description: Fetches the full transcript/subtitles of a YouTube video (Japanese or English) using yt-dlp, then cleans the raw auto-caption VTT into deduplicated readable text. Use when asked to get a YouTube video's transcript, 文字起こし, 字幕取得, summarize/read a YouTube video's content, or extract captions from one or more youtube.com / youtu.be URLs.
---

# YouTube文字起こし取得(yt-dlp)

YouTube動画の字幕(手動字幕 or 自動生成字幕)を取得し、読みやすいプレーンテキストに変換する手法。`youtube_transcript_api`より`yt-dlp`の方がYouTube側のIPブロック耐性・仕様変更への追従が良く、実績があるためこちらを標準採用する。

## 1. セットアップ(初回のみ)

このLinux環境は`externally-managed-environment`のためシステムPythonへ直接`pip install`できない。venvを切ってその中に入れる。

```bash
python3 -m venv "$SCRATCHPAD/ytdlp-venv"
"$SCRATCHPAD/ytdlp-venv/bin/pip" install yt-dlp
```

既にvenvがあれば再インストール不要。`yt-dlp`は更新頻度が高いツールなので、取得に失敗する場合はまず`pip install -U yt-dlp`を試す。

## 2. 字幕の取得

動画をダウンロードせず、字幕ファイル(vtt)だけを取得する。日本語字幕がなければ英語にフォールバックしたい場合は`--sub-lang ja,ja-orig,en`のように並べる。

```bash
VENV=./ytdlp-venv/bin/yt-dlp
$VENV --skip-download --write-auto-sub --write-sub \
  --sub-lang ja,ja-orig --sub-format vtt \
  -o "video" "https://www.youtube.com/watch?v=VIDEO_ID"
```

- `No supported JavaScript runtime could be found` という警告が出ることがあるが、字幕取得自体は成功するので無視してよい
- 出力ファイル名は `video.ja.vtt` や `video.ja-orig.vtt` になる(自動生成字幕は `-orig` サフィックスが付くことが多い)
- 複数動画をまとめて取る場合は `-o "video2"` のように番号を振って衝突を避ける

## 3. VTTをクリーンなテキストに変換

自動生成字幕のVTTはローリングキャプション形式で同じ行が何度も繰り返されるため、単純にcatすると重複だらけになる。直前行との重複除去とタグ除去が必要。

```bash
python3 -c "
import re
lines = open('video.ja-orig.vtt', encoding='utf-8').read().splitlines()
out = []
prev = ''
for l in lines:
    if '-->' in l or l.startswith('WEBVTT') or l.startswith('Kind:') or l.startswith('Language:') or not l.strip():
        continue
    text = re.sub(r'<[^>]+>', '', l).strip()
    if text and text != prev:
        out.append(text)
        prev = text
print('\n'.join(out))
" > transcript_clean.txt
```

これで整形済みの全文テキストが `transcript_clean.txt` に得られる。この段階では句読点や段落分けがないベタ書きなので、要約・整形して使う際はさらにLLMで読みやすく成形するとよい。

## 4. フォールバック: youtube_transcript_api

`yt-dlp`が使えない/失敗する場合の軽量な代替。`pip install youtube-transcript-api`で入る(このマシンには既にインストール済み)。

```python
from youtube_transcript_api import YouTubeTranscriptApi
api = YouTubeTranscriptApi()
transcript = api.fetch(video_id, languages=["ja", "en"])
text = " ".join(entry.text for entry in transcript)
```

ただしクラウド/データセンター系IP(WSLもここに該当しやすい)からは`IP blocked`で失敗することが多く、Cookie認証(`cookies=path`引数)が必要になるケースがある。`yt-dlp`より不安定なので、まず試すのは`yt-dlp`側とする。

## 5. 用途に応じた後処理

Obsidianボルトへの格納など、取得後の使い道に応じて整形する場合は、`transcript_clean.txt`を元に見出し・箇条書きへ再構成する。内容を削らず全文をベースにまとめる指示がある場合は、要約せず構造化(小見出し分け・重複表現の整理)にとどめること。
