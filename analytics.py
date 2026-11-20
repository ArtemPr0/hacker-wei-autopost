#!/usr/bin/env python3
"""Reads the results of every post on every channel connected in Buffer (all Buffer accounts) and writes analytics.json,
which the Social tab of the Pathwei admin dashboard shows as real, per-channel analytics.

Buffer refreshes post metrics about once a day, so running this every few hours is plenty.
Env: BUFFER_API_KEY, BUFFER_API_KEY_2 ... (same as post.py). DAYS (default 90). Flags: --schema (print the fields Buffer offers).
"""
import os, sys, json, time, datetime
import common

ROOT = common.ROOT
DAYS = int(os.environ.get("DAYS", "90"))

def log(*a): print(*a, flush=True)

def fields(type_name, key):
    """The field names Buffer's API offers on a type, so the query only asks for what exists."""
    try:
        t = common.gql('query { __type(name: "%s") { fields { name type { kind name ofType { kind name } } } } }' % type_name, key)["__type"]
        return {f["name"]: f["type"] for f in (t or {}).get("fields") or []}
    except Exception as e:
        log(f"could not read the {type_name} fields: {str(e)[:160]}"); return {}

def scalar(t):
    while t and t.get("kind") in ("NON_NULL", "LIST"): t = t.get("ofType")
    return t and t.get("kind") in ("SCALAR", "ENUM")

def brand_for(service, name):
    n = (name or "").lower().lstrip("@")
    for a in common.accounts():
        if (a.get(service) or "").lower() == n: return a
    return None

def main():
    keys = [(k, v) for k, v in sorted(common.secrets().items()) if k.startswith("BUFFER_API_KEY")]
    if not keys: log("no Buffer keys, nothing to read"); return 0
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DAYS)).strftime("%Y-%m-%dT00:00:00.000Z")
    PF = fields("Post", keys[0][1]); CF = fields("Channel", keys[0][1])
    if "--schema" in sys.argv or os.environ.get("DEBUG"):
        print("Post:", sorted(PF)); print("Channel:", sorted(CF))
        if not os.environ.get("DEBUG"): return 0
        try:
            mt = CF.get("metadata") or {}
            while mt and mt.get("ofType"): mt = mt["ofType"]
            name = mt.get("name")
            t = common.gql('query { __type(name: "%s") { kind fields { name type { kind name ofType { name } } } possibleTypes { name fields { name type { kind name ofType { name } } } } } }' % name, keys[0][1])
            print("METADATA", name, json.dumps(t)[:3000])
            t2 = common.gql('query { __type(name: "Account") { fields { name } } }', keys[0][1]); print("ACCOUNT", json.dumps(t2)[:800])
        except Exception as e: print("METADATA failed", e)
    want_post = [f for f in ("id", "text", "sentAt", "dueAt", "createdAt", "status", "externalLink", "serviceLink", "permalink", "link", "type", "postType") if f in PF and scalar(PF[f])]
    want_chan = [f for f in ("id", "name", "displayName", "service", "avatar", "serviceId", "externalLink", "serviceLink", "url", "type", "isDisconnected", "isLocked") if f in CF and scalar(CF[f])]
    assets = " assets { __typename ... on ImageAsset { thumbnail } ... on VideoAsset { thumbnail } }" if "assets" in PF else ""
    out = {"updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "days": DAYS, "channels": [], "errors": []}
    seen = set()
    for kname, key in keys:
        try: orgs = common.gql("query { account { organizations { id name } } }", key)["account"]["organizations"]
        except Exception as e: out["errors"].append(f"{kname}: {str(e)[:200]}"); continue
        for org in orgs:
            try: chans = common.gql('query { channels(input: {organizationId: "%s"}) { %s } }' % (org["id"], " ".join(want_chan)), key)["channels"]
            except Exception as e: out["errors"].append(f"{kname} channels: {str(e)[:200]}"); continue
            for ch in chans:
                if ch["id"] in seen: continue
                seen.add(ch["id"])
                posts, after, pages = [], None, 0
                while pages < 10:
                    q = ('query { posts(input: {organizationId: "%s", filter: {channelIds: ["%s"], status: [sent]}}, first: 50%s) '
                         '{ edges { node { %s metrics { type value } metricsUpdatedAt%s } } pageInfo { hasNextPage endCursor } } }') % (
                         org["id"], ch["id"], (', after: "%s"' % after) if after else "", " ".join(want_post), assets)
                    try: r = common.gql(q, key)["posts"]
                    except Exception as e:
                        if assets and "assets" in str(e): assets = ""; continue      # retry once without thumbnails
                        out["errors"].append(f"{ch.get('service')} {ch.get('name')}: {str(e)[:200]}"); break
                    if os.environ.get("DEBUG") and pages == 0: log("DEBUG", ch.get("name"), json.dumps(r)[:600])
                    old = False
                    for ed in r["edges"]:
                        n = ed["node"]; m = {x["type"]: x["value"] for x in (n.get("metrics") or [])}
                        thumb = next((a.get("thumbnail") for a in (n.get("assets") or []) if a and a.get("thumbnail")), None)
                        at = n.get("sentAt") or n.get("dueAt") or n.get("createdAt")
                        if at and at < since: old = True; continue
                        posts.append({"id": n.get("id"), "at": n.get("sentAt") or n.get("dueAt") or n.get("createdAt"),
                                      "text": (n.get("text") or "").split("\n")[0][:140], "link": n.get("externalLink") or n.get("serviceLink") or n.get("permalink") or n.get("link"),
                                      "thumb": thumb, "metrics": m, "metrics_at": n.get("metricsUpdatedAt")})
                    pages += 1
                    if old or not r["pageInfo"]["hasNextPage"]: break
                    after = r["pageInfo"]["endCursor"]; time.sleep(0.3)
                b = brand_for(ch.get("service"), ch.get("name")) or brand_for(ch.get("service"), ch.get("displayName"))
                out["channels"].append({"service": ch.get("service"), "handle": ch.get("name") or ch.get("displayName"), "avatar": ch.get("avatar"),
                                        "brand": b["name"] if b else None, "brand_id": b["id"] if b else None,
                                        "mode": ("manual" if b and b.get("manual") else "off" if b and b.get("off") else "auto" if b else "unlisted"),
                                        "disconnected": bool(ch.get("isDisconnected")), "posts": sorted(posts, key=lambda p: p["at"] or "", reverse=True)})
                log(f"{ch.get('service')} {ch.get('name')}: {len(posts)} sent posts in the last {DAYS} days")
    json.dump(out, open(os.path.join(ROOT, "analytics.json"), "w"), indent=0, ensure_ascii=False)
    log(f"analytics.json written: {len(out['channels'])} channels, {sum(len(c['posts']) for c in out['channels'])} posts, {len(out['errors'])} errors")
    for e in out["errors"]: log("::warning::" + e)
    return 0

if __name__ == "__main__":
    sys.exit(main())
