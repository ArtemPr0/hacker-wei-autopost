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

# status.json: what the Pathwei admin dashboard reads
import datetime
repo = os.environ.get("GITHUB_REPOSITORY", "ArtemPr0/hacker-wei-autopost")
raw = f"https://raw.githubusercontent.com/{repo}/main"
try: paused = bool(json.load(open(os.path.join(ROOT, "state", "paused.json"))).get("paused"))
except Exception: paused = False
def item(i):
    cap = open(os.path.join(POSTS, f"{i}_caption.txt"), encoding="utf8").read().strip()
    n = len([f for f in os.listdir(POSTS) if f.startswith(i + "_") and f.endswith(".jpg")])
    return {"id": i, "title": cap.splitlines()[0][:160], "cover": f"{raw}/posts/{i}_1.jpg", "slides": n}
order = [p["post"] for p in json.load(open(os.path.join(ROOT, "state", "posted.json")))["posted"]] if posted else []
recent = [dict(item(i), date=posted[i].get("date"), tiktok=posted[i].get("tiktok"), instagram=bool(posted[i].get("media_id")))
          for i in order[::-1] if i in ids][:8]
accounts = json.load(open(os.path.join(ROOT, "accounts.json")))["accounts"]
for a in accounts:
    if a["id"] == "hacker":
        a.update(waiting=len(waiting), posted=len([p for p in posted.values() if p.get("media_id")]),
                 next=[item(i) for i in waiting[:6]], recent=recent)
    else:
        a.update(waiting=0, posted=0, next=[], recent=[])
status = {"updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "repo": repo, "paused": paused,
          "queue_page": f"https://github.com/{repo}/blob/main/QUEUE.md", "runs_page": f"https://github.com/{repo}/actions/workflows/post.yml",
          "accounts": accounts}
json.dump(status, open(os.path.join(ROOT, "status.json"), "w"), indent=1)
print("status.json written")
