#!/usr/bin/env python3
"""Posts the next queued carousel in posts/ (files NNN_1.jpg ... NNN_7.jpg and NNN_caption.txt) to Instagram (Instagram API with Instagram Login).

Env: IG_ACCESS_TOKEN (required), IG_USER_ID (optional, defaults to the token's own account). Optional: IMAGE_BASE, GRAPH_BASE, GRAPH_VERSION,
SKIP_URL_CHECK=1, STATE_FILE.
Flags: --dry-run (print what would happen), --force (ignore the one post a day guard).
Exit codes: 0 ok, 1 failure, 3 posted fine but the queue is nearly empty (so GitHub emails you).
"""
import os, sys, json, time, datetime, urllib.request, urllib.parse, urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
POSTS = os.path.join(ROOT, "posts")
STATE = os.environ.get("STATE_FILE", os.path.join(ROOT, "state", "posted.json"))
BASE = os.environ.get("GRAPH_BASE", "https://graph.instagram.com").rstrip("/")
VER = os.environ.get("GRAPH_VERSION", "").strip("/")
LOW_QUEUE = 2

def log(*a): print(*a, flush=True)

def url(path):
    return "/".join(x for x in (BASE, VER, path.strip("/")) if x)

def call(method, path, params, tries=3):
    last = None
    for n in range(tries):
        try:
            if method == "GET":
                req = urllib.request.Request(url(path) + "?" + urllib.parse.urlencode(params))
            else:
                req = urllib.request.Request(url(path), data=urllib.parse.urlencode(params).encode(), method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            last = f"HTTP {e.code}: {body}"
            if e.code < 500 and e.code != 429:
                break
        except Exception as e:
            last = repr(e)
        time.sleep(5 * (n + 1))
    raise RuntimeError(f"{method} {path} failed: {last}")

def load_state():
    try:
        return json.load(open(STATE))
    except FileNotFoundError:
        return {"posted": []}

def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, "w"), indent=1)

def check_url(u):
    req = urllib.request.Request(u, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:
        ct = r.headers.get("Content-Type", "")
        if r.status != 200 or "image" not in ct:
            raise RuntimeError(f"image not reachable as an image: {u} ({r.status}, {ct})")

def wait_ready(cid, token, secs=180):
    end = time.time() + secs
    while time.time() < end:
        s = call("GET", cid, {"fields": "status_code", "access_token": token})
        code = s.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {cid} status {code}: {s}")
        time.sleep(4)
    raise RuntimeError(f"container {cid} not ready after {secs}s")

def main():
    dry = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    st = load_state()
    done = {p["post"] for p in st["posted"]}
    files = os.listdir(POSTS)
    queue = sorted({f.split("_")[0] for f in files if f.endswith("_caption.txt")})
    todo = [d for d in queue if d not in done]
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    if not todo:
        log("Queue is empty. Add more posts to posts/.")
        return 3
    if not force and st["posted"] and st["posted"][-1]["date"] == today:
        log("Already posted today, skipping.")
        return 0
    name = todo[0]
    slides = sorted((f for f in files if f.startswith(name + "_") and f.lower().endswith((".jpg", ".jpeg"))),
                    key=lambda f: int(f.split("_")[1].split(".")[0]))
    caption = open(os.path.join(POSTS, name + "_caption.txt"), encoding="utf8").read().strip()
    assert 2 <= len(slides) <= 10, f"{name}: need 2 to 10 slides, found {len(slides)}"
    assert len(caption) <= 2200 and caption.count("#") <= 30, f"{name}: caption too long or too many hashtags"
    repo = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPO")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    img_base = os.environ.get("IMAGE_BASE", f"https://raw.githubusercontent.com/{repo}/{branch}/posts").rstrip("/")
    urls = [f"{img_base}/{s}" for s in slides]
    log(f"Next post: {name} with {len(slides)} slides")
    if dry:
        for u in urls: log("  ", u)
        log("Caption:\n" + caption)
        return 0
    uid = os.environ.get("IG_USER_ID", "").strip() or "me"
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        log("::notice::IG_ACCESS_TOKEN secret is not set yet, nothing posted.")
        return 0
    who = call("GET", "me", {"fields": "user_id,username", "access_token": token})
    log(f"Posting as @{who.get('username')}")
    if os.environ.get("SKIP_URL_CHECK") != "1":
        for u in urls: check_url(u)
    kids = []
    for u in urls:
        c = call("POST", f"{uid}/media", {"image_url": u, "is_carousel_item": "true", "access_token": token})
        kids.append(c["id"])
    for k in kids: wait_ready(k, token)
    car = call("POST", f"{uid}/media", {"media_type": "CAROUSEL", "children": ",".join(kids),
                                        "caption": caption, "access_token": token})
    wait_ready(car["id"], token)
    pub = call("POST", f"{uid}/media_publish", {"creation_id": car["id"], "access_token": token}, tries=1)
    st["posted"].append({"post": name, "date": today, "media_id": pub.get("id")})
    save_state(st)
    log(f"Published {name}: media id {pub.get('id')}")
    left = len(todo) - 1
    if left <= LOW_QUEUE:
        log(f"::warning::Only {left} posts left in the queue. Add more posts to posts/.")
        return 3
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"::error::{e}")
        sys.exit(1)
