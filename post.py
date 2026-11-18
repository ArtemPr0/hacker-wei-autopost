#!/usr/bin/env python3
"""Posts the next item for every account (or one account). An item is a carousel (NAME_1.jpg ... plus NAME_caption.txt) or a video
(NAME.mp4 plus NAME_caption.txt). Items in vault/<account>/ go first, then the AI-written queue in the account's posts folder.

Each account posts up to its per_day limit, at least GAP_MIN minutes apart. Instagram goes through the Instagram API (accounts with an
"instagram" entry), TikTok through Buffer (accounts with a "tiktok" handle that is connected in Buffer).

Env: IG_ACCESS_TOKEN, IG_USER_ID (optional), BUFFER_API_KEY, BUFFER_API_KEY_2 (optional second Buffer account), ACCOUNT (one account id, or all),
FORCE_POST=1 (ignore the daily limit, the gap and pause), GRAPH_BASE, GRAPH_VERSION, SKIP_URL_CHECK=1, IMAGE_BASE.
Flags: --dry-run, --force, --pause ID|all, --resume ID|all.
Exit codes: 0 ok, 1 failure, 3 fine but an AI-written queue is nearly empty (so GitHub emails the owner).
"""
import os, sys, json, time, datetime, subprocess, urllib.request, urllib.parse, urllib.error
import common

ROOT = common.ROOT
BASE = os.environ.get("GRAPH_BASE", "https://graph.instagram.com").rstrip("/")
VER = os.environ.get("GRAPH_VERSION", "").strip("/")
LOW_QUEUE = 2
GAP_MIN = 150
DEFAULT_IG_ID = "17841413475185588"  # hacker.weii, used only on graph.facebook.com

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

BUFFER_URL = os.environ.get("BUFFER_URL", "https://api.buffer.com")

def gql(query, key):
    req = urllib.request.Request(BUFFER_URL, data=json.dumps({"query": query}).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Buffer HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    if out.get("errors"): raise RuntimeError(f"Buffer error: {json.dumps(out['errors'])[:400]}")
    return out["data"]

_channels = None
def buffer_channels():
    """Every channel in every connected Buffer account, each with the key that reaches it."""
    global _channels
    if _channels is None:
        _channels = []
        for key in [os.environ.get(k, "").strip() for k in ("BUFFER_API_KEY", "BUFFER_API_KEY_2")]:
            if not key: continue
            for org in gql("query { account { organizations { id name } } }", key)["account"]["organizations"]:
                for c in gql('query { channels(input: {organizationId: "%s"}) { id name displayName service } }' % org["id"], key)["channels"]:
                    _channels.append(dict(c, key=key))
    return _channels

def tiktok_via_buffer(handle, urls, caption, video=False):
    """Sends a carousel or a video to the TikTok channel connected in Buffer (an approved TikTok partner). Returns a short status."""
    if not any(os.environ.get(k, "").strip() for k in ("BUFFER_API_KEY", "BUFFER_API_KEY_2")): return "not set up"
    want = handle.lower().lstrip("@")
    match = [c for c in buffer_channels() if c.get("service") == "tiktok" and want in ((c.get("name") or "").lower(), (c.get("displayName") or "").lower())]
    if not match:
        return "not connected in Buffer: %s (connected: %s)" % (handle, ", ".join(c.get("name") or "?" for c in buffer_channels()) or "none")
    kind = "video" if video else "image"
    assets = ", ".join('{%s: {url: %s}}' % (kind, json.dumps(u)) for u in urls)
    soon = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 180))
    last = ""
    for mode in ("shareNow", 'customScheduled, dueAt: "%s"' % soon, "addToQueue"):
        q = ('mutation { createPost(input: {text: %s, channelId: "%s", schedulingType: automatic, mode: %s, assets: [%s]}) '
             '{ ... on PostActionSuccess { post { id } } ... on MutationError { message } } }') % (json.dumps(caption, ensure_ascii=False), match[0]["id"], mode, assets)
        try:
            res = gql(q, match[0]["key"])["createPost"]
        except RuntimeError as e:
            last = str(e); continue
        if res.get("post"): return f"sent ({mode.split(',')[0]}, Buffer post {res['post']['id']})"
        last = res.get("message") or json.dumps(res)[:200]
    return "failed: " + last[:300]

def check_url(u):
    req = urllib.request.Request(u, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:
        ct = r.headers.get("Content-Type", "")
        if r.status != 200 or not ("image" in ct or "video" in ct or "octet" in ct):
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

_ig = {}
def ig_login():
    """Works out which Graph host accepts the token. Returns (user id, token) or None when no token is set."""
    global BASE
    if "v" in _ig: return _ig["v"]
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    uid = os.environ.get("IG_USER_ID", "").strip() or "me"
    if not token:
        _ig["v"] = None; return None
    try:
        who = call("GET", "me", {"fields": "user_id,username", "access_token": token}, tries=1)
    except RuntimeError as e:
        if "GRAPH_BASE" in os.environ: raise
        log(f"graph.instagram.com did not accept the token ({str(e)[:160]}), trying graph.facebook.com")
        BASE = "https://graph.facebook.com"
        if uid == "me": uid = DEFAULT_IG_ID
        who = call("GET", uid, {"fields": "username", "access_token": token}, tries=1)
    log(f"Instagram: posting as @{who.get('username')} via {BASE}")
    _ig["v"] = (uid, token, (who.get("username") or "").lower()); return _ig["v"]

def instagram(a, it, urls):
    """Publishes a carousel, a single image or a reel. Returns the media id."""
    login = ig_login()
    if not login: raise RuntimeError("IG_ACCESS_TOKEN is not set")
    uid, token, username = login
    if username and username != a["instagram"].lower():
        raise RuntimeError(f"the Instagram token belongs to @{username}, not @{a['instagram']}")
    cap = it["caption"]
    assert len(cap) <= 2200 and cap.count("#") <= 30, "caption too long or too many hashtags for Instagram"
    if it["video"]:
        c = call("POST", f"{uid}/media", {"media_type": "REELS", "video_url": urls[0], "caption": cap, "access_token": token})
        wait_ready(c["id"], token, secs=600); final = c["id"]
    elif len(urls) == 1:
        c = call("POST", f"{uid}/media", {"image_url": urls[0], "caption": cap, "access_token": token})
        wait_ready(c["id"], token); final = c["id"]
    else:
        assert len(urls) <= 10, "Instagram carousels take at most 10 slides"
        kids = [call("POST", f"{uid}/media", {"image_url": u, "is_carousel_item": "true", "access_token": token})["id"] for u in urls]
        for k in kids: wait_ready(k, token)
        car = call("POST", f"{uid}/media", {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": cap, "access_token": token})
        wait_ready(car["id"], token); final = car["id"]
    return call("POST", f"{uid}/media_publish", {"creation_id": final, "access_token": token}, tries=1).get("id")

def set_pause(who, value):
    f = os.path.join(ROOT, "state", "paused.json")
    try: p = json.load(open(f))
    except Exception: p = {}
    if who in ("", "all"): p["paused"] = value; p["accounts"] = {} if not value else p.get("accounts", {})
    else: p.setdefault("accounts", {})[who] = value
    os.makedirs(os.path.dirname(f), exist_ok=True); json.dump(p, open(f, "w"))
    log(f"{'Paused' if value else 'Resumed'}: {who or 'all'}")

def post_account(a, force, dry, img_base):
    """Posts one item for one account. Returns 'posted', 'skipped', 'empty', 'low' or 'failed'."""
    name = a["name"]
    if common.paused(a) and not force:
        log(f"{name}: paused, nothing posted."); return "skipped"
    if not a.get("instagram") and not a.get("tiktok"):
        log(f"{name}: no connected platform yet."); return "skipped"
    st = common.load_state(a)
    todo = common.waiting(a)
    if not todo:
        log(f"{name}: nothing waiting."); return "empty"
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.strftime("%Y-%m-%d")
    mine = [p for p in st["posted"] if p.get("date") == today]
    if not force:
        if len(mine) >= int(a.get("per_day", 1)):
            log(f"{name}: already posted {len(mine)} today, skipping."); return "skipped"
        last = max((p.get("at", "") for p in mine), default="")
        if last and (now - datetime.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)).total_seconds() < GAP_MIN * 60:
            log(f"{name}: last post was under {GAP_MIN} minutes ago, skipping."); return "skipped"
    it = todo[0]
    urls = [f"{img_base}/{it['rel']}/{urllib.parse.quote(m)}" for m in it["media"]]
    log(f"{name}: next is {it['key']} ({'video' if it['video'] else str(len(urls)) + ' slides'})")
    if dry:
        for u in urls: log("  ", u)
        log("Caption:\n" + it["caption"]); return "skipped"
    if os.environ.get("SKIP_URL_CHECK") != "1":
        for u in urls: check_url(u)
    entry = {"post": it["key"], "date": today, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "media_id": None, "title": it["caption"].splitlines()[0][:160]}
    if a.get("instagram"):
        try:
            entry["media_id"] = instagram(a, it, urls); log(f"{name}: Instagram published, media id {entry['media_id']}")
        except Exception as e:
            entry["instagram_error"] = str(e)[:300]; log(f"::warning::{name}: Instagram failed: {e}")
        if entry["media_id"]:
            st["posted"].append(entry); common.save_state(a, st)     # saved at once, so a later crash can never cause a double post
    if a.get("tiktok"):
        try: entry["tiktok"] = tiktok_via_buffer(a["tiktok"], urls, it["caption"], it["video"])
        except Exception as e: entry["tiktok"] = f"failed: {e}"[:300]
        log(f"{name}: TikTok: {entry['tiktok']}")
    ok = bool(entry["media_id"]) or str(entry.get("tiktok", "")).startswith("sent")
    if not ok:
        log(f"::warning::{name}: {it['key']} did not go out anywhere, it stays in the queue for the next slot."); return "failed"
    if entry not in st["posted"]: st["posted"].append(entry)
    common.save_state(a, st)
    left = len([t for t in todo[1:] if not t["vault"]])
    if a.get("profile") and left <= LOW_QUEUE:
        log(f"::warning::{name}: only {left} AI-written posts left in the queue."); return "low"
    return "posted"

def main():
    args = sys.argv[1:]
    for flag, val in (("--pause", True), ("--resume", False)):
        if flag in args:
            set_pause(args[args.index(flag) + 1] if len(args) > args.index(flag) + 1 else "all", val); return 0
    dry = "--dry-run" in args
    force = "--force" in args or os.environ.get("FORCE_POST") == "1"
    only = os.environ.get("ACCOUNT", "all").strip() or "all"
    repo = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPO")
    try: sha = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or "main"
    except Exception: sha = "main"
    img_base = os.environ.get("IMAGE_BASE", f"https://raw.githubusercontent.com/{repo}/{sha}").rstrip("/")
    results = {}
    for a in common.accounts():
        if only != "all" and a["id"] != only: continue
        try: results[a["id"]] = post_account(a, force, dry, img_base)
        except Exception as e:
            log(f"::error::{a['name']}: {e}"); results[a["id"]] = "failed"
    log("Summary:", json.dumps(results))
    return 3 if "low" in results.values() else 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"::error::{e}")
        sys.exit(1)
