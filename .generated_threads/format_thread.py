#!/usr/bin/env python3
import os, textwrap, re

ROOT = "/home/loser/wsl-projects/.generated_threads"
DIFF_PATTERN = re.compile(r"^\+{1,2}.*")   # lines added in the diff

def truncate(txt, limit=140):
    return txt[:limit] if len(txt) <= limit else txt[:limit-3] + "..."

def make_thread(diff_path, idx, total):
    with open(diff_path, "r", encoding="utf-8") as f:
        diff = f.readlines()

    # extract added/modified lines with simple heuristics
    snippets = [line.rstrip() for line in diff if DIFF_PATTERN.match(line)]

    # create tweet bodies
    tweets = []
    # 1️⃣ intro tweet – include commit summary (first line of diff file)
    with open(diff_path, "r", encoding="utf-8") as f:
        first = f.readline().strip()
    intro = f"{idx}/{total} {first}"
    tweets.append(truncate(intro))

    # 2‑n‑1️⃣ technical tweets – one snippet per tweet (max 120 chars, leave room for numbering)
    for i, snippet in enumerate(snippets[:total-2], start=2):
        # add file‑type hint if possible
        hint = ""
        m = re.search(r"\+\+\+ b/(.+)", diff[i-2])   # crude detection
        if m:
            ext = os.path.splitext(m.group(1))[1].lstrip(".")
            hint = f" [{ext}]"
        tweet = f"{i}/{total} {truncate(snippet + hint)}"
        tweets.append(tweet)

    # final coaching tweet
    coaching = f"{total}/{total} 🎯 Coaching: keep backing up your work – the checkpoint routine saved the day! #AIcantdoThis"
    tweets.append(truncate(coaching))

    # write thread file
    out_path = os.path.join(ROOT, f"thread_{idx}.txt")
    with open(out_path, "w", encoding="utf-8") as out:
        out.write("\n".join(tweets))
    print(f"🧵 Thread {idx}/{total} written to {out_path}")

def main():
    diff_files = sorted([f for f in os.listdir(ROOT) if f.startswith("diff_") and f.endswith(".txt")])
    total = len(diff_files)
    if total == 0:
        print("⚠ No diff files found.")
        return
    for i, diff_file in enumerate(diff_files, start=1):
        make_thread(os.path.join(ROOT, diff_file), i, total)

if __name__ == "__main__":
    main()
