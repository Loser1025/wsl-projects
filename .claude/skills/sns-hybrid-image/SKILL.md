---
name: sns-hybrid-image
description: Generates SNS post images for free by combining a Pollinations.ai background photo with a Pillow text overlay (label + headline + optional body, optional footer). Use when asked to create a Threads/Instagram post image, a "hybrid" style image, an SNS thumbnail, or a Note.com header image (1280x670). Handles Japanese fonts via the Windows font mount in WSL, gradient scrim placement (top/bottom/full), and footer-overlap avoidance.
---

# SNS ハイブリッド画像生成(写真+テキストオーバーレイ)

無料でSNS投稿用の画像を作る方法。背景写真はPollinations.ai(APIキー不要)、テキストはPillow(ローカル生成)で合成する。`mimic_sns`のコーチング事業部SNS運用で確立した手法。

## 全体の流れ

1. 背景写真をPollinations.aiで取得する(またはNoto/既存の写真を再利用する)
2. Pillowでグラデーションスクリム(暗幕)を重ねる
3. ラベル・見出し・本文(任意)・フッター(任意)を描画する
4. 用途に応じたキャンバスサイズで保存する

## 1. 背景写真の取得(Pollinations.ai)

```bash
enc=$(python3 -c "import urllib.parse; print(urllib.parse.quote('プロンプトをここに(英語推奨)'))")
curl -sS --max-time 40 -o photo_xxx.jpg \
  "https://image.pollinations.ai/prompt/${enc}?width=1080&height=1350&nologo=true&seed=42"
```

**重要な制約(実測済み)**:
- 匿名利用は**同時1リクエストまで**。並列で叩くと`429 Too Many Requests`(`Queue full for IP`)が返る
- 連続で複数枚取得する場合は、**1枚ごとに15秒前後の間隔**を空けること。詰めて叩くとキューが埋まって失敗する
- `seed`パラメータを固定すると同じ構図を再現できる(バリエーション比較時に有用)
- レスポンスがJSONエラー(`{"error":...}`)の場合があるので、`file <出力ファイル>`で実際に画像かどうか確認する習慣をつけるとよい

**プロンプト設計のコツ**:テーマに応じた比喩を英語で具体的に描写する。例:
- 孤独な没頭・雪国の背景:`a person's hands quietly assembling small electronic parts and wires alone at a desk late at night, warm lamp light, snowy window in the background, cinematic minimal`
- 不安の先に光が見える:`a single path through a misty forest leading toward bright light in the distance, cinematic, minimal, calm`
- 対話・調整:`two people having a warm conversation at a cozy cafe table, soft window light, shallow depth of field, minimal`
- 成長・ブレイクスルー:`a person standing at a cliff edge watching sunrise over mountains, silhouette, cinematic, hopeful, minimal`

## 2. 日本語フォント(WSL環境)

Windows側のフォントを`/mnt/c/Windows/Fonts/`経由でそのまま使う。

```python
FONT_BOLD = "/mnt/c/Windows/Fonts/YuGothB.ttc"  # 見出し用
FONT_REG  = "/mnt/c/Windows/Fonts/YuGothR.ttc"  # 本文用
```

未インストールの場合は `pip install Pillow` を仮想環境に追加するだけでよい(標準ライブラリではないので明示的インストールが必要)。

## 3. 再利用可能な生成関数

以下は改良を重ねた最終形。**フッターの有無に応じてテキストブロックの下端を動的に計算する**ことで、本文とフッターが重なるバグ(初期バージョンで発生)を回避している。

```python
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350  # 用途に応じて変更(下記「キャンバスサイズの目安」参照)

FONT_BOLD = "/mnt/c/Windows/Fonts/YuGothB.ttc"
FONT_REG = "/mnt/c/Windows/Fonts/YuGothR.ttc"
ACCENT = (255, 200, 87)


def draw_wrapped(draw, text, font, fill, x, y, max_width, line_spacing=1.3):
    """\n で明示改行しつつ、幅超過時は自動折り返しする。"""
    lines = []
    for raw_line in text.split("\n"):
        if not raw_line:
            lines.append("")
            continue
        cur = ""
        for ch in raw_line:
            test = cur + ch
            if draw.textlength(test, font=font) > max_width and cur:
                lines.append(cur)
                cur = ch
            else:
                cur = test
        lines.append(cur)
    line_h = font.size * line_spacing
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_h), line, font=font, fill=fill)
    return y + len(lines) * line_h


def make_hybrid(photo_path, out_path, label, headline, body=None, footer=None,
                gradient="bottom", scrim_strength=238):
    """
    photo_path: 背景写真のパス
    out_path:   出力先パス
    label:      アクセントカラーの小見出し(例: "認知科学コーチング")
    headline:   見出し(\n で改行指定可、省略すると自動折り返し)
    body:       本文(省略可)
    footer:     フッター(省略可。指定時のみ下部に帯を確保して重なりを防ぐ)
    gradient:   "bottom" | "top" | "full"
    """
    base = Image.open(photo_path).convert("RGB")
    src_w, src_h = base.size
    target_ratio = W / H
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        offset = (src_w - new_w) // 2
        base = base.crop((offset, 0, offset + new_w, src_h))
    else:
        new_h = int(src_w / target_ratio)
        offset = (src_h - new_h) // 2
        base = base.crop((0, offset, src_w, offset + new_h))
    base = base.resize((W, H), Image.LANCZOS)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for y in range(H):
        if gradient == "bottom":
            t = max(0, (y - H * 0.28) / (H * 0.72))
        elif gradient == "top":
            t = max(0, 1 - (y / (H * 0.55)))
        else:  # full
            t = 0.55
        alpha = int(scrim_strength * min(1, t ** 1.25))
        odraw.line([(0, y), (W, y)], fill=(6, 6, 8, alpha))
    img = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    font_label = ImageFont.truetype(FONT_BOLD, 32)
    font_headline = ImageFont.truetype(FONT_BOLD, 56)
    font_body = ImageFont.truetype(FONT_REG, 32)
    font_footer = ImageFont.truetype(FONT_REG, 26)

    # フッターがある場合のみ帯を確保し、テキストブロックはその上に収める
    if footer:
        footer_y = H - 76
        scrim_top = footer_y - 40
        sdraw = ImageDraw.Draw(img, "RGBA")
        sdraw.rectangle([(0, scrim_top), (W, H)], fill=(4, 4, 6, 170))
        text_bottom_limit = scrim_top - 40
    else:
        text_bottom_limit = H - 70

    headline_lines = headline.count("\n") + 1
    body_lines = (body.count("\n") + 2) if body else 0
    block_h = 60 + headline_lines * font_headline.size * 1.24 + \
              (30 + body_lines * font_body.size * 1.3 if body else 0)

    y0 = min(900, text_bottom_limit - block_h)

    draw.text((100, y0), label, font=font_label, fill=ACCENT)
    y = draw_wrapped(draw, headline, font_headline, (255, 255, 255), 100, y0 + 56, W - 200, 1.24)
    if body:
        draw_wrapped(draw, body, font_body, (222, 222, 222), 100, y + 26, W - 220)
    if footer:
        draw.text((100, footer_y), footer, font=font_footer, fill=(220, 220, 220))

    img.save(out_path)
    print("saved", out_path)
```

## 4. キャンバスサイズの目安

| 用途 | サイズ | 備考 |
|---|---|---|
| Instagram/Threadsフィード投稿 | 1080×1350(4:5) | 縦長。標準的にこれで作ればよい |
| Note.com見出し画像 | 1280×670(1.91:1) | 横長。左寄せ・縦中央にテキストを配置するレイアウトに調整が必要(下記参照) |

横長(Note見出し等)の場合は`gradient`ロジックを縦方向ではなく**水平方向**(左を暗く、右にかけて抜く)に変更し、テキストは左寄せ・縦中央配置にする。`W/H`比率が大きく変わったら、フォントサイズも比率に応じて調整すること(1280×670では見出し56〜60px程度が可読性の目安)。

## 5. 可読性のチューニング指針

- 写真をしっかり見せたい場合は`scrim_strength`を100〜140程度まで下げる。ただしその場合、文字に薄いドロップシャドウ(オフセット2〜3px、黒・半透明)を追加しないと可読性が落ちる
- **サムネイル表示でも一目で読める**ようにしたい場合(記事のアイキャッチ等):見出しフォントを60px以上に拡大し、本文(サブテキスト)は思い切って削除する。フォントを大きくすると`\n`による手動改行が意図通りに収まらず行が増えすぎることがあるので、**手動改行を外して自動折り返しに任せる**方が安定する
- 見出しが3〜4行に増えて画面下にはみ出す場合は、フォントサイズを下げるか、コピー自体を短くする

## 6. 生成後の確認

Read ツールでPNG/JPGをそのまま開いて目視確認する。特に以下を毎回チェック:
- 本文とフッターが重なっていないか
- 見出しの改行が不自然な位置(助詞だけで行が変わる等)になっていないか
- 写真の顔・主題が文字に隠れすぎていないか
