#!/usr/bin/env python3
"""Weekly learning loop: reads analytics.json and writes insights.json.

For every channel it compares the last 28 days of posts by format, posting window, hook type and series.
A winner is named only when the winner and the runner-up each have at least MIN posts; otherwise that
dimension is marked "testing". Comparisons use the median views a post, so one viral post cannot decide it.
The weekly content batch reads this file before it is made; the dashboard shows the three strongest lines.
Runs after analytics.py; rewrites the file once a week (or when FORCE_INSIGHTS is set).
"""
import os, json, datetime, statistics
import common

ROOT = common.ROOT
MIN = 5
DAYS = 28
WINDOWS = ["07:30", "11:00", "15:00", "19:00"]       # the time-testing windows (UK time = UTC in winter)
LABEL = {"format": {"carousel": "Carousels", "video": "Videos", "photo": "Photos"},
         "hook": {"question": "Question hooks", "number": "Number hooks", "confession": "Confession hooks", "pov": "POV hooks", "statement": "Statement hooks"}}

def views(p):
    m = p.get("metrics") or {}
    return float(m.get("views") or m.get("impressions") or 0)

def window(at):
    """The test window a post belongs to (within an hour of it), or None."""
    t = datetime.datetime.fromisoformat(at.replace("Z", "+00:00"))
    mins = t.hour * 60 + t.minute
    best = min(WINDOWS, key=lambda w: abs(int(w[:2]) * 60 + int(w[3:]) - mins))
    return best if abs(int(best[:2]) * 60 + int(best[3:]) - mins) <= 60 else None

def name(dim, v):
    if dim == "window": return v
    if dim == "series": return f'"{v}"'
    return LABEL.get(dim, {}).get(v, v)

def compare(posts, dim):
    groups = {}
    for p in posts:
        v = window(p["at"]) if dim == "window" else p.get({"format": "fmt"}.get(dim, dim))
        if v: groups.setdefault(v, []).append(views(p))
    rows = sorted(({"value": k, "median": round(statistics.median(v)), "posts": len(v)} for k, v in groups.items()), key=lambda r: -r["median"])
    ready = [r for r in rows if r["posts"] >= MIN]
    if len(ready) >= 2:
        return {"status": "known", "best": ready[0], "runner_up": ready[1], "groups": rows}
    return {"status": "testing", "groups": rows}

def main():
    path = os.path.join(ROOT, "insights.json")
    try: old = json.load(open(path))
    except Exception: old = {}
    if old.get("updated") and not os.environ.get("FORCE_INSIGHTS"):
        age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(old["updated"].replace("Z", "+00:00"))
        if age < datetime.timedelta(days=6, hours=12):
            print(f"insights.json is {age.days} days old; rewritten weekly."); return 0
    d = json.load(open(os.path.join(ROOT, "analytics.json")))
    now = datetime.datetime.now(datetime.timezone.utc)
    since = (now - datetime.timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    out = {"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "days": DAYS, "min_posts": MIN, "windows": WINDOWS, "accounts": [], "lines": []}
    cands = []
    for c in d.get("channels", []):
        posts = [p for p in c.get("posts", []) if (p.get("at") or "") >= since]
        if not posts: continue
        who = f'{c.get("brand") or "@" + c["handle"]} {c["service"].capitalize().replace("Tiktok", "TikTok").replace("Linkedin", "LinkedIn")}'
        acc = {"brand": c.get("brand"), "brand_id": c.get("brand_id"), "service": c["service"], "handle": c["handle"], "posts": len(posts)}
        for dim in ("format", "window", "hook", "series"):
            r = compare(posts, dim); acc[dim] = r
            if r["status"] == "known" and r["runner_up"]["median"] > 0:
                b, u = r["best"], r["runner_up"]
                text = (f'{name(dim, b["value"])} beat{"" if dim in ("format", "hook") else "s"} {name(dim, u["value"]).lower() if dim in ("format", "hook") else name(dim, u["value"])} on {who} '
                        f'({b["median"]} vs {u["median"]} median views a post, {b["posts"]} vs {u["posts"]} posts)')
                if dim == "window": text = "Posting at " + text
                cands.append((b["median"] / u["median"], text))
        out["accounts"].append(acc)
    out["lines"] = [t for _, t in sorted(cands, key=lambda x: -x[0])[:3]]
    json.dump(out, open(path, "w"), indent=1, ensure_ascii=False)
    print(f"insights.json written: {len(out['accounts'])} channels, {len(cands)} findings")
    for t in out["lines"]: print(" ", t)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
