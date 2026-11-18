#!/usr/bin/env python3
"""Writes QUEUE.md (every waiting post for every account, with thumbnails) and status.json (what the Pathwei admin dashboard reads)."""
import os, json, datetime
import common
ROOT = common.ROOT
repo = os.environ.get("GITHUB_REPOSITORY", "ArtemPr0/hacker-wei-autopost")
raw = f"https://raw.githubusercontent.com/{repo}/main"
cfg = json.load(open(os.path.join(ROOT, "accounts.json")))
try: pz = json.load(open(os.path.join(ROOT, "state", "paused.json")))
except Exception: pz = {}

HAVE_BUFFER = any(k.startswith("BUFFER_API_KEY") for k in common.secrets())

def item(i):
    return {"id": i["key"], "title": i["caption"].splitlines()[0][:160], "slides": len(i["media"]), "video": i["video"], "vault": i["vault"],
            "cover": None if i["video"] else f"{raw}/{i['rel']}/{i['media'][0]}"}

md = ["# Posting queue", "", "Vault posts (added by hand) go first, then the AI-written queue. To stop a post, delete its files before its slot comes.", ""]
out = []
for a in common.accounts():
    st = common.load_state(a)["posted"]
    todo = common.waiting(a)
    everything = {i["key"]: i for i in common.all_items(a)}
    recent = []
    for p in st[::-1][:8]:
        i = everything.get(p["post"])
        recent.append({"id": p["post"], "title": p.get("title") or (i["caption"].splitlines()[0][:160] if i else p["post"]), "date": p.get("date"), "at": p.get("at"),
                       "instagram": bool(p.get("media_id")), "tiktok": p.get("tiktok"), "cover": (None if not i or i["video"] else f"{raw}/{i['rel']}/{i['media'][0]}")})
    platforms = [x for x in ("instagram", "tiktok") if a.get(x)]
    info = {"id": a["id"], "name": a["name"], "handle": a.get("handle") or "", "format": a.get("format", ""), "writer": a.get("writer", ""),
            "platforms": platforms, "instagram": a.get("instagram") or "", "tiktok": a.get("tiktok") or "", "per_day": a.get("per_day", 1),
            "has_writer": bool(a.get("profile")), "active": bool(platforms) and (bool(a.get("profile")) or bool(todo)),
            "paused": bool(pz.get("paused")) or bool((pz.get("accounts") or {}).get(a["id"])),
            "schedule": f"Up to {a.get('per_day', 1)} a day ({cfg.get('slots', '')})" if platforms else "No platform connected",
            "waiting": len(todo), "vault_waiting": len([t for t in todo if t["vault"]]),
            "posted": len([p for p in st if p.get("date") != "manual"]), "next": [item(i) for i in todo[:6]], "recent": recent}
    if HAVE_BUFFER:
        info["connected"] = {p: bool((p == "instagram" and a["id"] == "hacker") or common.buffer_channel(p, a.get(p))) for p in platforms}
    if a.get("profile") == "only":
        try:
            used = set(json.load(open(common.topics_file(a))).get("quotes", []))
        except Exception: used = set()
        info["quotes_left"] = len([q for q in json.load(open(os.path.join(ROOT, "quotes.json")))["quotes"] if q["text"] not in used])
    out.append(info)
    md += [f"## {a['name']}", "", f"**{len(todo)} waiting** ({info['vault_waiting']} from the vault). {info['posted']} posted by the system so far.", ""]
    for i in todo[:20]:
        thumbs = "(video)" if i["video"] else " ".join(f'<a href="{i["rel"]}/{m}"><img src="{i["rel"]}/{m}" width="110"></a>' for m in i["media"])
        md += [f"### {i['key']}", "", thumbs, "", "<details><summary>Caption</summary>", "", "```", i["caption"], "```", "", "</details>", ""]
    if len(todo) > 20: md.append(f"...and {len(todo) - 20} more after these.\n")
    if not todo: md.append("Nothing waiting.\n")
open(os.path.join(ROOT, "QUEUE.md"), "w", encoding="utf8").write("\n".join(md) + "\n")
status = {"updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "repo": repo, "paused": bool(pz.get("paused")),
          "slots": cfg.get("slots", ""), "queue_page": f"https://github.com/{repo}/blob/main/QUEUE.md",
          "runs_page": f"https://github.com/{repo}/actions/workflows/post.yml", "accounts": out,
          "buffer_accounts": len([k for k in common.secrets() if k.startswith("BUFFER_API_KEY")]),
          "channels": [f"{c.get('service')} {c.get('name')}" for c in common.buffer_channels()] if HAVE_BUFFER else []}
json.dump(status, open(os.path.join(ROOT, "status.json"), "w"), indent=1)
print("QUEUE.md and status.json written:", ", ".join(f"{a['name']} {a['waiting']}" for a in out))
