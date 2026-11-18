#!/usr/bin/env python3
"""Writes and renders new Hacker Wei carousels so the queue never runs dry.

Each run: if fewer than TARGET unposted carousels are queued, ask Google Gemini (free tier) for a new one,
check it against fixed rules, render the 7 slides in the house design, and add it to posts/.
Any failure leaves the queue untouched (the daily post still goes out from what is already queued).

Env: GEMINI_API_KEY (free key from Google AI Studio). Optional: MODELS_URL, MODEL_IDS (comma separated), FORCE=1.
Flags: --from-file spec.json (skip the AI, used for tests), --dry-run (do not write into posts/).
"""
import os, sys, re, json, glob, shutil, subprocess, tempfile, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
POSTS = os.path.join(ROOT, "posts")
STATE = os.environ.get("STATE_FILE", os.path.join(ROOT, "state", "posted.json"))
TOPICS = os.environ.get("TOPICS_FILE", os.path.join(ROOT, "state", "topics.json"))
URL = os.environ.get("MODELS_URL", "https://generativelanguage.googleapis.com/v1beta/models").rstrip("/")
MODELS = [m.strip() for m in os.environ.get(
    "MODEL_IDS", "gemini-3.5-flash,gemini-2.5-flash,gemini-3.1-flash-lite,gemini-2.5-flash-lite").split(",") if m.strip()]
TARGET = 5          # keep this many unposted carousels queued
MAX_PER_RUN = 2
ATTEMPTS = 4

def log(*a): print(*a, flush=True)

RULES = """You write Instagram carousels for "Hacker Wei", an account giving UK students and graduates practical job-hunting hacks.
Voice: calm, practical, a little cheeky. British English spelling. Plain words. Short sentences.

Hard rules:
- Practical advice only. No statistics, percentages, salaries, study or survey claims, or anything presented as a researched fact.
- No promises ("guaranteed", "always works"). Use honest wording such as "often", "many", "can".
- No company names except generic tools students already know (LinkedIn, Excel, Zoom, Teams). No links, no @mentions, no emojis inside slides.
- Never use em dashes or en dashes.
- British spelling matters: the verb is "practise" (the noun is "practice"), "organise", "summarise". Write STAR in capitals when you mean the STAR method.
- The closing question must be answerable with a number from 1 to 5, for example "Which one will you try?"
- Advice must be legal, honest and safe. Never suggest lying, faking experience or tricking an employer.
- The topic must be clearly different from every topic in the "already used" list.

Return ONLY a JSON object with exactly these keys:
{
 "topic": "3 to 8 words naming the topic",
 "cmd": "a fake terminal command, lowercase, like: scan --cv  or  send --thank-you (max 26 characters)",
 "head": ["2 to 4 SHORT LINES IN CAPITALS forming the cover headline, each line max 13 characters; wrap ONE key word or phrase in <g></g> to colour it"],
 "pill": "cover sub-label starting with '5 ', e.g. '5 ways to pass them' (max 24 characters)",
 "hacks": [ exactly 5 items, each ["headline, a short imperative sentence ending with a full stop (max 34 characters)", "one sentence saying why it matters (max 75 characters)", "one concrete action to take (max 70 characters)"] ],
 "out": ["closing question to the reader (max 26 characters)", "starts with 'Save this ' (max 30 characters)", "starts with 'Send it to ' (max 32 characters)"],
 "hook": "one or two sentence caption opener (max 140 characters)",
 "hashtags": ["9 lowercase hashtags without the # sign, letters and digits only, mixing broad UK graduate tags and topic tags"]
}"""

BANNED = [r"%", r"£", r"\$", r"€", r"\bper ?cent\b", r"\bguarantee", r"\bstud(y|ies) (show|found|suggest)", r"\bresearch (shows|found|suggests)",
          r"\bsurvey", r"\baccording to\b", r"\bstatistic", r"\b\d+ (in|out of) \d+\b", r"https?://", r"www\.", r"@\w", r"\blie\b", r"\bfake\b",
          r"\b(one|two|three|four|five|six|seven|eight|nine|ten) (in|out of) (two|three|four|five|six|seven|eight|nine|ten|every)\b",
          r"\b(half|most|majority) of (all )?(employers|recruiters|graduates|students|applicants|candidates)\b", r"\b\d{2,}\b"]
ALLOWED_NUMBERS = {"24", "10", "15", "30", "60"}   # times and durations that are advice, not statistics

def clean(t):
    t = str(t).replace("—", ", ").replace("–", " to ").replace("’", "'").replace("‘", "'")
    t = t.replace("“", '"').replace("”", '"').replace("…", "...")
    t = re.sub(r"\b([Pp])ractice (saying|answering|your|the|with|out|each|it|on|in|for|until|before)\b", r"\1ractise \2", t)
    t = re.sub(r"\bstar method\b", "STAR method", t)
    return re.sub(r"\s+", " ", t).strip()

def words(t): return {w for w in re.findall(r"[a-z]{4,}", t.lower())}

def validate(sp, used):
    """Returns a list of problems (empty when the spec is acceptable)."""
    p = []
    need = {"topic": str, "cmd": str, "head": list, "pill": str, "hacks": list, "out": list, "hook": str, "hashtags": list}
    for k, typ in need.items():
        if not isinstance(sp.get(k), typ): p.append(f"missing or wrong type: {k}")
    if p: return p
    sp["topic"], sp["cmd"], sp["pill"], sp["hook"] = clean(sp["topic"]), clean(sp["cmd"]), clean(sp["pill"]), clean(sp["hook"])
    sp["head"] = [clean(x).upper().replace("<G>", "<g>").replace("</G>", "</g>") for x in sp["head"]]
    sp["out"] = [clean(x) for x in sp["out"]]
    if not (2 <= len(sp["head"]) <= 4): p.append("head must have 2 to 4 lines")
    for l in sp["head"]:
        if len(re.sub(r"</?g>", "", l)) > 13: p.append(f"head line too long (max 13 characters): {l}")
        if re.sub(r"</?g>", "", l) != re.sub(r"<[^>]*>", "", l) or l.count("<g>") != l.count("</g>"): p.append(f"bad tags in head line: {l}")
    if not re.fullmatch(r"[a-z]+( --?[a-z-]+){1,2}", sp["cmd"]) or len(sp["cmd"]) > 26: p.append("cmd must look like: verb --flag (max 26 characters)")
    lim = 24 if len(sp["head"]) == 4 else 34
    if len(sp["pill"]) > lim or not sp["pill"].startswith("5 "): p.append(f"pill must start with '5 ' and be max {lim} characters")
    if len(sp["hacks"]) != 5: p.append("hacks must have exactly 5 items")
    for i, h in enumerate(sp["hacks"]):
        if not (isinstance(h, list) and len(h) == 3 and all(isinstance(x, str) for x in h)):
            p.append(f"hack {i+1} must be a list of 3 strings"); continue
        h[:] = [clean(x) for x in h]
        for j, (name, mx) in enumerate((("headline", 36), ("why line", 80), ("action", 75))):
            if not (8 <= len(h[j]) <= mx): p.append(f"hack {i+1} {name} must be 8 to {mx} characters: {h[j]}")
        if not h[0].endswith((".", "?", "!")): h[0] += "."
    if len(sp["out"]) != 3: p.append("out must have 3 items")
    else:
        for x, mx in zip(sp["out"], (28, 32, 34)):
            if not (6 <= len(x) <= mx): p.append(f"out line must be 6 to {mx} characters: {x}")
    if not (20 <= len(sp["hook"]) <= 160): p.append("hook must be 20 to 160 characters")
    tags = [re.sub(r"[^a-z0-9]", "", str(t).lower()) for t in sp["hashtags"]]
    tags = [t for i, t in enumerate(tags) if 3 <= len(t) <= 30 and t not in tags[:i] and t != "hackerwei"][:9]
    if len(tags) < 5: p.append("need at least 5 valid hashtags")
    sp["hashtags"] = tags
    text = " ".join([sp["topic"], sp["pill"], sp["hook"], *sp["head"], *sp["out"], *[x for h in sp["hacks"] if isinstance(h, list) for x in h]])
    if re.search(r"[–—]", text): p.append("contains a dash character")
    if re.search(r"[^\x00-\x7f]", re.sub(r"</?g>", "", text)): p.append("slides and hook must use plain characters only (no emojis or symbols)")
    low = re.sub(r"</?g>", "", text).lower()
    for b in BANNED:
        for m in re.finditer(b, low):
            if m.group(0).strip() in ALLOWED_NUMBERS: continue
            p.append(f"banned content (statistics, money, promises, links or dishonest advice): '{m.group(0)}'")
    mine = words(sp["topic"] + " " + " ".join(sp["head"]))
    for u in used:
        other = words(u)
        if mine and other and len(mine & other) / min(len(mine), len(other)) >= 0.6:
            p.append(f"too similar to an already used topic: {u}"); break
    return p

def ask_ai(used, feedback):
    key = os.environ["GEMINI_API_KEY"].strip()
    ask = ("Already used topics (do not repeat or closely overlap):\n- " + "\n- ".join(used[-80:]) +
           "\n\nWrite one new carousel. Pick a topic UK students or graduates search for during job hunting, "
           "internships, applications, interviews or starting a first job.")
    if feedback:
        ask += ("\n\nYour previous attempt was rejected for these reasons. Fix every one and return the full JSON again:\n- "
                + "\n- ".join(feedback[:12]))
    body = json.dumps({"system_instruction": {"parts": [{"text": RULES}]},
                       "contents": [{"role": "user", "parts": [{"text": ask}]}],
                       "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"}}).encode()
    last = None
    for model in MODELS:
        req = urllib.request.Request(f"{URL}/{model}:generateContent", data=body, method="POST", headers={
            "x-goog-api-key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read().decode(errors="replace")
                meta = f"status {r.status}, type {r.headers.get('Content-Type')}"
            try:
                txt = "".join(p.get("text", "") for p in json.loads(raw)["candidates"][0]["content"]["parts"])
            except Exception as e:
                raise ValueError(f"unexpected API response ({meta}): {raw[:300]!r}") from e
            m = re.search(r"\{.*\}", txt, re.S)
            if not m: raise ValueError(f"no JSON object in the reply: {txt[:200]!r}")
            try:
                sp = json.loads(m.group(0))
            except Exception as e:
                raise ValueError(f"reply was not valid JSON: {txt[:300]!r}") from e
            log(f"AI reply from {model}")
            return sp
        except urllib.error.HTTPError as e:
            last = f"{model}: HTTP {e.code} {e.read().decode(errors='replace')[:300]}"
        except Exception as e:
            last = f"{model}: {e!r}"
        log("model failed:", last)
    raise RuntimeError(f"all models failed, last error: {last}")

def render(sp, outdir):
    """Renders the 7 slides, returns layout problems."""
    spec = {k: sp[k] for k in ("cmd", "head", "pill", "hacks", "out")}
    f = os.path.join(outdir, "spec.json"); json.dump([spec], open(f, "w"))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "make_carousel.py"), f, outdir], capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError("render failed: " + r.stderr[-400:])
    p = []
    for x in json.load(open(os.path.join(outdir, "layout.json"))):
        s = x["slide"]
        if s == 1 and x["right"] > 1030: p.append("a cover headline line is too wide, use shorter words")
        if 2 <= s <= 6 and (x["bottom"] > 1195 or x["right"] > 1022): p.append(f"hack {s-1} has too much text, shorten its three lines")
        if s == 7 and (x["bottom"] > 815 or x["right"] > 1030): p.append("the closing question or its two lines are too long")
    return p

def caption(sp):
    head = re.sub(r"</?g>", "", " ".join(sp["head"])).capitalize()
    lines = [sp["hook"], "", sp["pill"] + ":"] + [f"{i+1}. {h[0].rstrip('.')}" for i, h in enumerate(sp["hacks"])]
    lines += ["", sp["out"][0] + " Comment the number \U0001F447", "Save this and follow for a new hack every day.", "",
              " ".join("#" + t for t in sp["hashtags"] + ["hackerwei"])]
    return "\n".join(lines)

def main():
    dry = "--dry-run" in sys.argv
    src = sys.argv[sys.argv.index("--from-file") + 1] if "--from-file" in sys.argv else None
    try: done = {p["post"] for p in json.load(open(STATE))["posted"]}
    except FileNotFoundError: done = set()
    ids = sorted({f.split("_")[0] for f in os.listdir(POSTS) if f.endswith("_caption.txt")})
    waiting = len([i for i in ids if i not in done])
    topics = json.load(open(TOPICS)) if os.path.exists(TOPICS) else {"used": []}
    want = 1 if os.environ.get("FORCE") == "1" else min(MAX_PER_RUN, max(0, TARGET - waiting))
    if not src and not os.environ.get("GEMINI_API_KEY", "").strip():
        want = 0
    if "--need" in sys.argv:
        print(want); return 0
    log(f"{waiting} carousels waiting, generating {want}")
    made = 0
    for _ in range(want):
        feedback, ok = [], None
        for attempt in range(1, ATTEMPTS + 1):
            sp = json.load(open(src)) if src else ask_ai(topics["used"], feedback)
            probs = validate(sp, topics["used"])
            tmp = tempfile.mkdtemp()
            if not probs: probs = render(sp, tmp)
            if not probs: ok = (sp, tmp); break
            log(f"attempt {attempt} rejected:", "; ".join(probs[:6])); feedback = probs
            if src: break
        if not ok:
            log("::warning::Could not produce an acceptable carousel this run."); break
        sp, tmp = ok
        new = f"{(max(int(i) for i in ids) + 1 if ids else 1):03d}"
        log(f"accepted carousel {new}: {sp['topic']}")
        if not dry:
            for i in range(1, 8): shutil.copy(os.path.join(tmp, "Post 1", f"{i}.jpg"), os.path.join(POSTS, f"{new}_{i}.jpg"))
            open(os.path.join(POSTS, f"{new}_caption.txt"), "w", encoding="utf8").write(caption(sp))
            topics["used"].append(sp["topic"]); json.dump(topics, open(TOPICS, "w"), indent=1)
        else:
            log(caption(sp)); log("slides in", os.path.join(tmp, "Post 1"))
        ids.append(new); made += 1
    log(f"made {made}")
    return 0

if __name__ == "__main__":
    try: sys.exit(main())
    except Exception as e:
        log(f"::warning::generation skipped: {e}"); sys.exit(0)
