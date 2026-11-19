#!/usr/bin/env python3
"""Posts the next item for every account (or one account). An item is a carousel (NAME_1.jpg ... plus NAME_caption.txt) or a video
(NAME.mp4 plus NAME_caption.txt). Items in vault/<account>/ go first, then the AI-written queue in the account's posts folder.

Each account posts up to its per_day limit, at least GAP_MIN minutes apart. Instagram goes through the Instagram API (accounts with an
"instagram" entry), TikTok through Buffer (accounts with a "tiktok" handle that is connected in Buffer).

Env: SECRETS_JSON (all repository secrets: IG_ACCESS_TOKEN, IG_TOKEN_<ID>, BUFFER_API_KEY, BUFFER_API_KEY_2, ...), ACCOUNT (one account id, or all),
FORCE_POST=1 (ignore the daily limit, the gap and pause), GRAPH_BASE, GRAPH_VERSION, SKIP_URL_CHECK=1, IMAGE_BASE.
Flags: --dry-run, --force, --pause ID|all, --resume ID|all.
Exit codes: 0 ok, 1 failure. A nearly empty AI-written queue is a warning in the log and shows on the dashboard.
"""
import os, sys, json, time, datetime, subprocess, urllib.request, urllib.parse, urllib.error
import common

ROOT = common.ROOT
BASE = os.environ.get("GRAPH_BASE", "https://graph.instagram.com").rstrip("/")
VER = os.environ.get("GRAPH_VERSION", "").strip("/")
LOW_QUEUE = 2
GAP_MIN = 150
AHEAD_H = 24     # a timed vault post is handed to Buffer this many hours before its time
LATE_H = 6       # and is dropped (left in the vault, flagged) if it could not be scheduled within this many hours after it
SLOTS = ["07:30", "12:30", "18:30"]   # UTC. The workflow wakes every hour; an account posts when a slot has passed that it has not used yet,
                                      # so a late or missed run only delays a post, it never loses one.
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

gql = common.gql

def via_buffer(service, handle, urls, caption, video=False, when=None):
    """Sends a carousel or a video to a channel connected in Buffer (an approved partner of TikTok and Instagram). Returns a short status."""
    if not any(k.startswith("BUFFER_API_KEY") for k in common.secrets()): return "not set up"
    ch = common.buffer_channel(service, handle)
    if not ch:
        return "not connected in Buffer: %s (connected: %s)" % (handle, ", ".join(f"{c.get('service')} {c.get('name')}" for c in common.buffer_channels()) or "none")
    kind = "video" if video else "image"
    assets = ", ".join('{%s: {url: %s}}' % (kind, json.dumps(u)) for u in urls)
    meta = ""
    if service == "instagram":
        meta = ', metadata: {instagram: {type: %s, shouldShareToFeed: true}}' % ("reel" if video else "post")
    soon = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 180))
    last = ""
    modes = ['customScheduled, dueAt: "%s"' % when] if when else ["shareNow", 'customScheduled, dueAt: "%s"' % soon, "addToQueue"]
    for extra in (meta, ""):
        for mode in modes:
            q = ('mutation { createPost(input: {text: %s, channelId: "%s", schedulingType: automatic, mode: %s, assets: [%s]%s}) '
                 '{ ... on PostActionSuccess { post { id } } ... on MutationError { message } } }') % (json.dumps(caption, ensure_ascii=False), ch["id"], mode, assets, extra)
            try:
                res = gql(q, ch["key"])["createPost"]
            except RuntimeError as e:
                last = str(e); continue
            if res.get("post"): return (f"sent (scheduled in Buffer for {when}, post {res['post']['id']})" if when else f"sent ({mode.split(',')[0]}, Buffer post {res['post']['id']})")
            last = res.get("message") or json.dumps(res)[:200]
        if not meta: break
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
def ig_token(a):
    """The account's own Instagram API token: IG_TOKEN_<ID>, or IG_ACCESS_TOKEN for Hacker Wei. None means: use Buffer for Instagram."""
    sec = common.secrets()
    return sec.get("IG_TOKEN_" + a["id"].upper()) or (sec.get("IG_ACCESS_TOKEN") if a["id"] == "hacker" else None)

def ig_login(a):
    """Works out which Graph host accepts the token. Returns (user id, token)."""
    global BASE
    if a["id"] in _ig: return _ig[a["id"]]
    token = ig_token(a)
    uid = (common.secrets().get("IG_USER_ID") if a["id"] == "hacker" else None) or "me"
    try:
        who = call("GET", "me", {"fields": "user_id,username", "access_token": token}, tries=1)
    except RuntimeError as e:
        if "GRAPH_BASE" in os.environ or a["id"] != "hacker": raise
        log(f"graph.instagram.com did not accept the token ({str(e)[:160]}), trying graph.facebook.com")
        BASE = "https://graph.facebook.com"
        if uid == "me": uid = DEFAULT_IG_ID
        who = call("GET", uid, {"fields": "username", "access_token": token}, tries=1)
    log(f"Instagram: posting as @{who.get('username')} via {BASE}")
    if (who.get("username") or "").lower() not in ("", a["instagram"].lower()):
        raise RuntimeError(f"the Instagram token belongs to @{who.get('username')}, not @{a['instagram']}")
    _ig[a["id"]] = (uid, token); return _ig[a["id"]]

def instagram(a, it, urls):
    """Publishes a carousel, a single image or a reel through the Instagram API. Returns the media id."""
    uid, token = ig_login(a)
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

def retry_instagram(a, img_base, dry):
    """A post that reached TikTok but was refused by Instagram is tried again on Instagram for two days (one per run)."""
    if not a.get("instagram") or dry: return
    st = common.load_state(a); items = {i["key"]: i for i in common.all_items(a)}
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for p in st["posted"]:
        if not p.get("instagram_pending"): continue
        it = items.get(p["post"])
        if not it or p.get("at", "") < cutoff:
            p.pop("instagram_pending"); p["instagram_error"] = (p.get("instagram_error", "") + " (gave up)")[:300]; common.save_state(a, st); continue
        urls = [f"{img_base}/{it['rel']}/{urllib.parse.quote(m)}" for m in it["media"]]
        try:
            if ig_token(a): p["media_id"] = instagram(a, it, urls)
            else:
                r = via_buffer("instagram", a["instagram"], urls, it["caption"], it["video"])
                if not r.startswith("sent"): raise RuntimeError(r)
                p["media_id"] = r
            p.pop("instagram_pending"); p.pop("instagram_error", None)
            log(f"{a['name']}: Instagram caught up on {p['post']}: {p['media_id']}")
        except Exception as e:
            p["instagram_error"] = str(e)[:300]; log(f"::warning::{a['name']}: Instagram still refuses {p['post']}: {str(e)[:200]}")
        common.save_state(a, st); return

def post_account(a, force, dry, img_base):
    """Posts one item for one account. Returns 'posted', 'skipped', 'empty', 'low' or 'failed'."""
    name = a["name"]
    if common.paused(a) and not force:
        log(f"{name}: paused, nothing posted."); return "skipped"
    if a.get("manual"):
        log(f"{name}: posted by hand from the dashboard, never automatically."); return "skipped"
    if not a.get("instagram") and not a.get("tiktok"):
        log(f"{name}: no connected platform yet."); return "skipped"
    retry_instagram(a, img_base, dry)
    st = common.load_state(a)
    todo = [t for t in common.waiting(a) if not t["hold"]]
    now = datetime.datetime.now(datetime.timezone.utc)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Timed vault posts: handed to Buffer up to a day ahead with their exact time, so they go out on time whatever GitHub's scheduler does.
    timed = [t for t in todo if t["at"]]
    todo = [t for t in todo if not t["at"]]
    handed = 0
    for it in timed:
        if it["at"] > iso(now + datetime.timedelta(hours=AHEAD_H)): continue
        if it["at"] < iso(now - datetime.timedelta(hours=LATE_H)):
            log(f"::warning::{name}: {it['key']} was due {it['at']} and is too late to post; left in the vault."); continue
        urls = [f"{img_base}/{it['rel']}/{urllib.parse.quote(m)}" for m in it["media"]]
        when = max(it["at"], iso(now + datetime.timedelta(minutes=3)))[:19] + ".000Z"
        log(f"{name}: timed post {it['key']} for {it['at']}")
        if dry: continue
        entry = {"post": it["key"], "date": it["at"][:10], "at": it["at"], "media_id": None, "title": it["caption"].splitlines()[0][:160], "timed": True}
        for plat in ("tiktok", "instagram"):
            if not a.get(plat) or (it["platform"] and it["platform"] != plat): continue
            try: r = via_buffer(plat, a[plat], urls, it["caption"], it["video"], when=when)
            except Exception as e: r = f"failed: {e}"[:300]
            log(f"{name}: {plat}: {r}")
            if plat == "tiktok": entry["tiktok"] = r
            elif r.startswith("sent"): entry["media_id"] = r
            else: entry["instagram_error"] = r
        if str(entry.get("tiktok", "")).startswith("sent") or entry["media_id"]:
            st["posted"].append(entry); common.save_state(a, st); handed += 1
        else:
            log(f"::warning::{name}: {it['key']} could not be scheduled, it will be tried again on the next wake-up.")
    if not todo:
        log(f"{name}: nothing else waiting."); return "posted" if handed else "empty"
    today = now.strftime("%Y-%m-%d")
    mine = [p for p in st["posted"] if p.get("date") == today]
    if not force:
        if now.hour >= 22 or now.hour < 6:
            log(f"{name}: quiet hours, no catch-up posts between 22:00 and 06:00."); return "posted" if handed else "skipped"
        slots = SLOTS[-max(1, min(len(SLOTS), int(a.get("per_day", 1)))):]
        due = len([t for t in slots if now.strftime("%H:%M") >= t])
        if len(mine) >= due:
            log(f"{name}: {len(mine)} posted today, {due} slot(s) passed, nothing due."); return "skipped"
        last = max((p.get("at", "") for p in mine if not p.get("timed")), default="")
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
            if ig_token(a): entry["media_id"] = instagram(a, it, urls)
            else:
                r = via_buffer("instagram", a["instagram"], urls, it["caption"], it["video"])
                if not r.startswith("sent"): raise RuntimeError(r)
                entry["media_id"] = r
            log(f"{name}: Instagram published: {entry['media_id']}")
        except Exception as e:
            entry["instagram_error"] = str(e)[:300]; log(f"::warning::{name}: Instagram failed: {e}")
        if entry["media_id"]:
            st["posted"].append(entry); common.save_state(a, st)     # saved at once, so a later crash can never cause a double post
    if a.get("tiktok"):
        try: entry["tiktok"] = via_buffer("tiktok", a["tiktok"], urls, it["caption"], it["video"])
        except Exception as e: entry["tiktok"] = f"failed: {e}"[:300]
        log(f"{name}: TikTok: {entry['tiktok']}")
    ok = bool(entry["media_id"]) or str(entry.get("tiktok", "")).startswith("sent")
    if not ok:
        log(f"::warning::{name}: {it['key']} did not go out anywhere, it stays in the queue for the next slot."); return "failed"
    if a.get("instagram") and not entry["media_id"]: entry["instagram_pending"] = True
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
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"::error::{e}")
        sys.exit(1)
