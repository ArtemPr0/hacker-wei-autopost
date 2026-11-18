"""Shared helpers: the list of accounts, where each account keeps its queue, vault and record of what was posted."""
import os, re, json
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
        if not media: continue
        out.append({"key": prefix + name, "name": name, "folder": folder, "rel": os.path.relpath(folder, ROOT).replace(os.sep, "/"),
                    "media": media, "video": bool(vids), "vault": bool(prefix),
                    "caption": open(os.path.join(folder, cap), encoding="utf8").read().strip()})
    return out

def all_items(a):
    """Vault first (what a founder added by hand), then the AI-written queue."""
    return _items(vault_dir(a), "vault/") + _items(posts_dir(a), "")

def waiting(a):
    done = {p["post"] for p in load_state(a)["posted"]}
    return [i for i in all_items(a) if i["key"] not in done]

def paused(a=None):
    try: p = json.load(open(os.path.join(ROOT, "state", "paused.json")))
    except Exception: return False
    return bool(p.get("paused")) or bool(a and (p.get("accounts") or {}).get(a["id"]))
