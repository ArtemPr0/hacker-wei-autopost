#!/usr/bin/env python3
"""Loads a content batch into the vaults, so the engine schedules it.

    python3 vault_import.py "<batch folder>" [--dry-run] [--replace]

The batch folder is what the MARKETING chat produces:
    TikTok/<N>_<Account_Name>/<HHMM>_TikTok_<Account>_<DayDDMon>_<Title>.mp4            a video
    TikTok/<N>_<Account_Name>/<HHMM>_TikTok_<Account>_<DayDDMon>_<Title>/slide_1.png    a carousel (a folder of slides)
    .../<same name>_CAPTION.txt     the caption; anything after a line of "---" is notes, and a "Sound:" note is kept
    Instagram/<handle>/<HHMM>_Instagram_<handle>_<DayDDMon>_<Title>.mp4
    BACKUP_if_not_filmed_<name>.mp4 is used when <name> has a caption but no video.
Times are UK time. Each post becomes vault/<account>/<YYYYMMDD-HHMM-platform-title>.* with a _meta.json holding its time.
A carousel whose sound note starts with "Add in-app" is held for a founder to post by hand with that song (TikTok songs cannot be attached automatically).
--replace first removes that account's vault posts that have not gone out yet."""
import os, re, sys, json, shutil, datetime
from zoneinfo import ZoneInfo
import common

UK = ZoneInfo("Europe/London")
MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}

def account_for(folder_name, accounts):
    key = re.sub(r"[^a-z0-9]", "", re.sub(r"^\d+_", "", folder_name).lower())
    for a in accounts:
        names = {re.sub(r"[^a-z0-9]", "", str(a.get(k, "")).lower()) for k in ("id", "name", "handle", "tiktok", "instagram")} - {""}
        if key in names or any(key.startswith(n) or n.startswith(key) for n in names if len(n) > 5): return a
    return None

def parse(stem):
    m = re.match(r"(\d{2})(\d{2})_(TikTok|Instagram)_[^_]+_[A-Za-z]{3}(\d{1,2})([A-Za-z]{3})_(.+)$", stem)
    if not m: return None
    hh, mm, plat, day, mon, title = m.groups()
    now = datetime.datetime.now(UK)
    when = datetime.datetime(now.year, MONTHS[mon.lower()], int(day), int(hh), int(mm), tzinfo=UK)
    if when < now - datetime.timedelta(days=180): when = when.replace(year=now.year + 1)
    return when, plat.lower(), title

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry, replace = "--dry-run" in sys.argv, "--replace" in sys.argv
    if not args: print(__doc__); return 1
    batch = args[0]; accounts = common.accounts(); cleared = set(); n = 0
    for plat_dir in ("TikTok", "Instagram"):
        base = os.path.join(batch, plat_dir)
        if not os.path.isdir(base): continue
        for acc_dir in sorted(os.listdir(base)):
            folder = os.path.join(base, acc_dir)
            if not os.path.isdir(folder): continue
            a = account_for(acc_dir, accounts)
            if not a: print(f"SKIPPED {plat_dir}/{acc_dir}: no account with that name in accounts.json"); continue
            vdir = common.vault_dir(a)
            if replace and a["id"] not in cleared and not dry:
                cleared.add(a["id"]); done = {p["post"] for p in common.load_state(a)["posted"]}
                for i in common._items(vdir, "vault/"):
                    if i["key"] in done: continue
                    for f in os.listdir(vdir):
                        if f.startswith(i["name"] + "_") or os.path.splitext(f)[0] == i["name"]: os.remove(os.path.join(vdir, f))
            for cap in sorted(f for f in os.listdir(folder) if f.endswith("_CAPTION.txt")):
                stem = cap[:-len("_CAPTION.txt")]; p = parse(stem)
                if not p: print(f"SKIPPED {cap}: the name is not HHMM_Platform_Account_DayDDMon_Title"); continue
                when, plat, title = p
                raw = open(os.path.join(folder, cap), encoding="utf8").read()
                text, _, notes = raw.partition("\n---")
                sound = (re.search(r"^Sound:\s*(.+)$", notes, re.M) or [None, ""])[1].strip()
                slides = os.path.join(folder, stem)
                video = next((os.path.join(folder, f) for f in (stem + ".mp4", stem + ".mov", "BACKUP_if_not_filmed_" + stem + ".mp4") if os.path.exists(os.path.join(folder, f))), None)
                name = f"{when:%Y%m%d-%H%M}-{'tt' if plat == 'tiktok' else 'ig'}-{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40]}"
                meta = {"at": when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "platform": plat, "title": title, "sound": sound}
                if os.path.isdir(slides):
                    pics = sorted((f for f in os.listdir(slides) if re.match(r"slide_\d+\.(png|jpe?g)$", f, re.I)), key=lambda f: int(re.search(r"\d+", f)[0]))
                    kind = f"carousel, {len(pics)} slides"
                    # Buffer cannot add TikTok music, so carousels are posted without a song rather than held for one
                elif video:
                    pics = []; kind = "video" + (" (BACKUP, the planned video was not in the batch)" if "BACKUP_" in video else "")
                    if "BACKUP_" in video: meta["note"] = "Backup video. The plan was to film this one; see the script in the batch."
                else:
                    print(f"SKIPPED {stem}: caption but no video or slides"); continue
                print(f"{a['name']:<20} {when:%a %d %b %H:%M} UK  {plat:<9} {kind:<24} {'HELD for a song: ' + sound if meta.get('hold') else ''}")
                n += 1
                if dry: continue
                os.makedirs(vdir, exist_ok=True)
                if pics:
                    from PIL import Image
                    for k, f in enumerate(pics, 1):
                        im = Image.open(os.path.join(slides, f)).convert("RGB")
                        if max(im.size) > 1920: im.thumbnail((1920, 1920))
                        im.save(os.path.join(vdir, f"{name}_{k}.jpg"), "JPEG", quality=92)
                else:
                    shutil.copy(video, os.path.join(vdir, name + os.path.splitext(video)[1].lower()))
                open(os.path.join(vdir, name + "_caption.txt"), "w", encoding="utf8").write(text.strip() + "\n")
                json.dump(meta, open(os.path.join(vdir, name + "_meta.json"), "w", encoding="utf8"), indent=1, ensure_ascii=False)
    print(f"{n} posts {'found' if dry else 'added to the vaults'}.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
