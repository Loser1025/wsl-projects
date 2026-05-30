import sys
import os
sys.stdout.reconfigure(encoding="utf-8")

from youtube_transcript_api import YouTubeTranscriptApi

video_ids = [
    "VlOuOjlqAXY",
    "7KyTXLiBv0o",
    "LIGEIwYmfeU",
    "YmFGXMC9kEs",
]

cookies_path = os.path.join(os.path.dirname(__file__), "cookies.txt")

for video_id in video_ids:
    print(f"\n--- {video_id} ---")
    for use_cookie in [False, True]:
        try:
            if use_cookie and os.path.exists(cookies_path):
                api = YouTubeTranscriptApi(http_client=None, cookies=cookies_path)
            else:
                api = YouTubeTranscriptApi()

            transcript = api.fetch(video_id, languages=["ja", "en"])
            text = " ".join([entry.text for entry in transcript])

            out_path = f"{video_id}.txt"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)

            label = "Cookie認証" if use_cookie else "認証なし"
            print(f"OK [{label}] {len(text)}文字 -> {out_path}")
            break

        except Exception as e:
            label = "Cookie認証" if use_cookie else "認証なし"
            print(f"NG [{label}]: {e}")
