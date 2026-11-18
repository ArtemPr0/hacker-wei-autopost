#!/usr/bin/env python3
"""Writes QUEUE.md: one page showing every waiting carousel (cover + caption) and the most recently posted ones."""
import os, json
ROOT = os.path.dirname(os.path.abspath(__file__))
POSTS = os.path.join(ROOT, "posts")
try: posted = {p["post"]: p for p in json.load(open(os.path.join(ROOT, "state", "posted.json")))["posted"]}
except FileNotFoundError: posted = {}
ids = sorted({f.split("_")[0] for f in os.listdir(POSTS) if f.endswith("_caption.txt")})
waiting = [i for i in ids if i not in posted]
done = [i for i in ids if i in posted][-10:][::-1]

def block(i):
    cap = open(os.path.join(POSTS, f"{i}_caption.txt"), encoding="utf8").read().strip()
    slides = " ".join(f'<a href="posts/{i}_{n}.jpg"><img src="posts/{i}_{n}.jpg" width="110"></a>' for n in range(1, 8)
                      if os.path.exists(os.path.join(POSTS, f"{i}_{n}.jpg")))
    return f"### Carousel {i}\n\n{slides}\n\n<details><summary>Caption</summary>\n\n```\n{cap}\n```\n\n</details>\n"

out = ["# Hacker Wei queue", "",
       f"**{len(waiting)} waiting to post** (one goes out each day, lowest number first). {len(posted)} posted or skipped so far.", "",
       "To stop a carousel from posting, delete its files in the `posts` folder before its day comes.", "", "## Waiting", ""]
out += [block(i) for i in waiting[:30]] or ["Nothing waiting."]
if len(waiting) > 30: out.append(f"...and {len(waiting) - 30} more after these. Open the `posts` folder to see them all.")
out += ["", "## Recently posted", ""]
for i in done:
    p = posted[i]
    out.append(f"- Carousel {i}: {p.get('date')}")
open(os.path.join(ROOT, "QUEUE.md"), "w", encoding="utf8").write("\n".join(out) + "\n")
print(f"QUEUE.md written: {len(waiting)} waiting")
