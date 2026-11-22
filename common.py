"""A vault item may carry NAME_meta.json: {"at": "2026-11-20T18:30:00Z" (post at this time), "platform": "tiktok" or "instagram" (only there),
"hold": "..." (do not auto-post; a founder posts it by hand; "song" is ignored, carousels go without one), "sound": "...", "title": "..."}.
Shared helpers: the list of accounts, where each account keeps its queue, vault and record of what was posted."""
import os, re, json, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.abspath(__file__))
IMG = (".jpg", ".jpeg", ".png")
VID = (".mp4", ".mov")

def accounts():
    return json.load(open(os.path.join(ROOT, "accounts.json")))["accounts"]

def posts_dir(a): return os.path.join(ROOT, a.get("dir") or "posts_" + a["id"])
def vault_dir(a): return os.path.join(ROOT, "vault", a["id"])
def state_file(a): return os.path.join(ROOT, "state", "posted.json" if a["id"] == "hacker" else f"posted_{a['id']}.json")
def topics_file(a): return os.path.join(ROOT, "state", "topics.json" if a["id"] == "hacker" else f"topics_{a['id']}.json")

def load_state(a):
    try: return json.load(open(state_file(a)))
    except FileNotFoundError: return {"posted": []}

def save_state(a, st):
    os.makedirs(os.path.dirname(state_file(a)), exist_ok=True)
    json.dump(st, open(state_file(a), "w"), indent=1)

def _items(folder, prefix):
    """Every post in a folder: NAME_caption.txt plus NAME_1.jpg, NAME_2.jpg ... (a carousel) or NAME.mp4 (a video)."""
    if not os.path.isdir(folder): return []
    files = os.listdir(folder); out = []
    for cap in sorted(f for f in files if f.endswith("_caption.txt")):
        name = cap[:-len("_caption.txt")]
        vids = [f for f in files if os.path.splitext(f)[0] == name and f.lower().endswith(VID)]
        pics = [f for f in files if re.fullmatch(re.escape(name) + r"_\d+\.(jpe?g|png)", f, re.I)]
        pics.sort(key=lambda f: int(re.search(r"_(\d+)\.\w+$", f).group(1)))
        media = vids[:1] or pics
        try: meta = json.load(open(os.path.join(folder, name + "_meta.json"), encoding="utf8"))
        except Exception: meta = {}
        if not media and meta.get("format") != "text": continue      # a text post (LinkedIn) is a caption with format "text"
        out.append({"meta": meta, "at": meta.get("at") or "", "platform": meta.get("platform") or "", "hold": "" if meta.get("hold") == "song" else (meta.get("hold") or ""),   # carousels no longer wait for a song: TikTok's music cannot be added through Buffer
                    "key": prefix + name, "name": name, "folder": folder, "rel": os.path.relpath(folder, ROOT).replace(os.sep, "/"),
                    "media": media, "video": bool(vids), "vault": bool(prefix),
                    "caption": open(os.path.join(folder, cap), encoding="utf8").read().strip()})
    return out

def all_items(a):
    """Vault first (what a founder added by hand), then the AI-written queue."""
    queue = [] if a.get("queue") is False else _items(posts_dir(a), "")
    vault = _items(vault_dir(a), "vault/")
    return sorted([i for i in vault if i["at"]], key=lambda i: i["at"]) + [i for i in vault if not i["at"]] + queue

def by_hand(a, i):
    """True when a founder posts this item themselves: the account is hand-posted, or the item is held (for example until a song is added)."""
    return bool(a.get("manual") or i["hold"])

def waiting(a):
    done = {p["post"] for p in load_state(a)["posted"]}
    return [i for i in all_items(a) if i["key"] not in done]

def paused(a=None):
    try: p = json.load(open(os.path.join(ROOT, "state", "paused.json")))
    except Exception: return False
    return bool(p.get("paused")) or bool(a and (p.get("accounts") or {}).get(a["id"]))

def secrets():
    """Every secret the workflow was given (SECRETS_JSON), plus plain environment variables, so a new account's key needs no workflow change."""
    try: s = json.loads(os.environ.get("SECRETS_JSON") or "{}")
    except Exception: s = {}
    for k, v in os.environ.items():
        if k.startswith(("BUFFER_API_KEY", "IG_")) and v.strip(): s.setdefault(k, v)
    return {k: str(v).strip() for k, v in s.items() if str(v).strip()}

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
    """Every channel in every connected Buffer account (secrets named BUFFER_API_KEY, BUFFER_API_KEY_2, ...), each with the key that reaches it."""
    global _channels
    if _channels is None:
        _channels = []
        for name, key in sorted(secrets().items()):
            if not name.startswith("BUFFER_API_KEY"): continue
            try:
                for org in gql("query { account { organizations { id name } } }", key)["account"]["organizations"]:
                    for ch in gql('query { channels(input: {organizationId: "%s"}) { id name displayName service } }' % org["id"], key)["channels"]:
                        _channels.append(dict(ch, key=key))
            except Exception as e:
                print(f"::warning::Buffer account behind {name} could not be read: {str(e)[:200]}", flush=True)
    return _channels

def buffer_channel(service, handle):
    want = (handle or "").lower().lstrip("@")
    for ch in buffer_channels():
        if ch.get("service") == service and want and want in ((ch.get("name") or "").lower().lstrip("@"), (ch.get("displayName") or "").lower().lstrip("@")):
            return ch
    return None

# ---- Format tags: what kind of post it is, which series it belongs to and how its first line hooks ----
def hook_of(text):
    """The hook type of a caption's first line: pov, question, number, confession or statement (a fixed rule, no AI)."""
    s = re.sub(r"#\S+", "", (text or "").strip().split("\n")[0]).strip()
    low = s.lower()
    if not s: return ""
    if low.startswith("pov"): return "pov"
    first = re.split(r"(?<=[.!?])\s", s)[0]
    if "?" in first: return "question"
    if re.match(r"^(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b", low): return "number"
    if re.match(r"^(i|i'm|i've|i was|me|my)\b", low): return "confession"
    return "statement"

FORMAT_WORDS = {"carousel", "meme", "hack", "video", "reel", "skit", "photo"}
def series_of(title):
    """A series name from a batch title such as "AfterHours-Ep2-TheCleanersRules" -> "After Hours" or
    "Carousel-EmailStory-NotEnoughExperience" -> "Email Story". Empty when the title has no series part."""
    toks = [t for t in re.split(r"[-_]", title or "") if t]
    while toks and toks[0].lower() in FORMAT_WORDS: toks = toks[1:]
    if len(toks) < 2: return ""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", toks[0]).strip().capitalize() if toks[0].isupper() else re.sub(r"(?<=[a-z])(?=[A-Z])", " ", toks[0]).strip()

def tags(a, i):
    """format (carousel, video, photo), series and hook for one queue or vault item. A meta.json value always wins."""
    m = i.get("meta") or {}
    fmt = m.get("format") or ("video" if i.get("video") else "carousel" if len(i.get("media") or []) > 1 else "photo" if i.get("media") else "text")
    series = m.get("series") or (series_of(m.get("title") or i.get("name", "").split("-", 3)[-1]) if i.get("vault") else a.get("series") or "")
    return {"format": fmt, "series": series, "hook": m.get("hook") or hook_of(i.get("caption"))}

def buffer_ids():
    """Buffer post ID -> (account, item) for every post the engine handed to Buffer, read from state/posted*.json."""
    out = {}
    for a in accounts():
        items = {i["key"]: i for i in all_items(a)}
        for p in load_state(a).get("posted", []):
            it = items.get(p.get("post"))
            if not it: continue
            for f in ("tiktok", "media_id", "linkedin"):
                for bid in re.findall(r"post ([0-9a-f]{20,})", str(p.get(f) or "")):
                    out[bid] = (a, it)
    return out
