"""Carousel renderer for every account.
Usage: python3 make_carousel.py specs.json out_dir [post numbers]     (theme comes from the THEME env var: hacker, pirate or only)
Each spec: head (list of lines, <g>word</g> = accent colour), pill, hacks (5 x [headline, grey line, boxed line]), out (title, bullet1, bullet2),
plus cmd (hacker), tag (pirate) or quote {text, who, source} (only).
Renders "Post N/1.jpg" to "7.jpg" at 1080x1350 and layout.json (text extents, used to reject overflowing text).
Needs: pip install playwright, chromium, and the Inter, DejaVu and Playfair Display fonts."""
import asyncio, base64, html, os, sys, json
from playwright.async_api import async_playwright
HERE = os.path.dirname(os.path.abspath(__file__))
THEME = os.environ.get("THEME", "hacker")
def b64(name):
    p = os.path.join(HERE, name)
    return base64.b64encode(open(p, "rb").read()).decode() if os.path.exists(p) else ""

T = {
 "hacker": dict(name="HACKER WEI", bg="#0c0a17", glow="rgba(66,36,112,.75)", ink="#fff", soft="#c9c3e6", acc="#b8ff4f", pill="#a259d9", pilltx="#fff",
                box="#1f1838", boxline="#a259d9", baroff="#3c345b", dot="#ec6fc3", grid="rgba(6,4,14,.38)", label="&gt; hack_0{n}", boxlabel="DO THIS",
                cta="Comment the number. Follow for a new hack every day.", font="'Inter'", headw=900, assets="asset_"),
 "pirate": dict(name="PIRATE WEI", bg="#0a1118", glow="rgba(150,28,36,.55)", ink="#fdf6e3", soft="#b9c4cf", acc="#ffc83d", pill="#d7263d", pilltx="#fff",
                box="#141f2b", boxline="#ffc83d", baroff="#26323f", dot="#d7263d", grid="rgba(255,255,255,.035)", label="EXHIBIT {n}", boxlabel="THE TRUTH",
                cta="Comment the number. Follow for a daily rant.", font="'Inter'", headw=900, assets="asset_pirate_"),
 "only":   dict(name="THE ONLY WEI", bg="#f3ede2", glow="rgba(196,160,92,.28)", ink="#15120e", soft="#5d554a", acc="#9a6b12", pill="#15120e", pilltx="#f3ede2",
                box="#fffaf0", boxline="#15120e", baroff="#d9cfbd", dot="#9a6b12", grid="rgba(21,18,14,.045)", label="LESSON {n}", boxlabel="APPLY IT",
                cta="Comment the number. Follow for one idea a day.", font="'Inter'", headw=800, assets="asset_only_"),
}[THEME]
if os.environ.get("BRAND"): T["name"] = html.escape(os.environ["BRAND"])
if T["name"] != {"hacker": "HACKER WEI", "pirate": "PIRATE WEI", "only": "THE ONLY WEI"}[THEME]: T["assets"] = "asset_none_"   # another account borrowing the design gets no mascot
BIG, ICON, CIRC = b64(T["assets"] + "big.png"), b64(T["assets"] + "icon.png"), b64(T["assets"] + "circ.png")
POSTS = json.load(open(sys.argv[1])); OUT = sys.argv[2]
SERIF = "'Playfair Display','DejaVu Serif',serif"
CSS = f"""
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1350px;position:relative;overflow:hidden;background:{T['bg']};font-family:{T['font']};color:{T['ink']}}}
.bg{{position:absolute;inset:0;background:radial-gradient(ellipse 900px 640px at 1000px 20px, {T['glow']}, transparent 100%), {T['bg']}}}
.grid{{position:absolute;inset:0;background-image:linear-gradient(to right, {T['grid']} 1px, transparent 1px),linear-gradient(to bottom, {T['grid']} 1px, transparent 1px);background-size:90px 90px}}
.pill{{position:absolute;left:60px;top:60px;height:52px;padding:0 17px;border-radius:26px;background:{T['pill']};color:{T['pilltx']};display:flex;align-items:center;font-weight:800;font-size:26px;letter-spacing:.2px}}
.d{{display:inline-block;width:11px;height:11px;background:{T['pilltx']};transform:rotate(45deg);margin-right:9px;border-radius:2px}}
.mono{{font-family:'DejaVu Sans Mono';font-weight:700;color:{T['acc']};position:absolute;left:60px}}
.g{{color:{T['acc']}}} g{{color:{T['acc']}}}
.bar{{position:absolute;top:1280px;height:9px;border-radius:5px;width:130px}}
.swipe{{position:absolute;right:62px;top:1224px;font-family:'DejaVu Sans Mono';font-weight:700;font-size:30px;color:{T['soft']};letter-spacing:1px}}
.icon{{position:absolute;left:905px;top:44px;width:112px;height:112px}}
"""
def img(data, style, cls=""):
    return f'<img {"class=" + cls if cls else ""} src="data:image/png;base64,{data}" style="{style}">' if data else ""
def bars(n):
    return "".join(f'<div class="bar" style="left:{60+i*139}px;background:{T["acc"] if i < n else T["baroff"]}"></div>' for i in range(7))
def top():
    return f'<div class=bg></div><div class=grid></div><div class=pill><span class=d></span>{T["name"]}</div>'
def subpill(text, y):
    return f'<div class=pill style="top:{y}px;height:68px;border-radius:34px;font-size:34px;padding:0 22px"><span class=d style="width:14px;height:14px"></span>{text}</div>'

def cover(p):
    if THEME == "only":
        q = p["quote"]; n = len(q["text"])
        size = 104 if n <= 55 else 88 if n <= 85 else 74 if n <= 115 else 62
        return f"""{top()}{bars(1)}{img(BIG, 'position:absolute;left:560px;top:860px;width:460px')}
<div style="position:absolute;left:52px;top:150px;font-family:{SERIF};font-weight:900;font-size:260px;line-height:260px;color:{T['acc']}">&ldquo;</div>
<div id="m" style="position:absolute;left:60px;top:330px;width:940px">
 <div style="font-family:{SERIF};font-weight:800;font-size:{size}px;line-height:{int(size*1.16)}px;letter-spacing:-1px">{html.escape(q['text'])}</div>
 <div style="width:160px;height:8px;background:{T['acc']};margin-top:44px"></div>
 <div style="margin-top:28px;font-weight:800;font-size:46px">{html.escape(q['who'])}</div>
 <div style="margin-top:8px;font-weight:500;font-size:28px;color:{T['soft']}">{html.escape(q['source'])}</div>
 <div class=pill style="position:static;display:inline-flex;margin-top:44px;height:68px;border-radius:34px;font-size:34px;padding:0 22px"><span class=d style="width:14px;height:14px"></span>{p['pill']}</div>
</div>"""
    lines = "".join(f"<div>{l}</div>" for l in p["head"])
    if THEME == "pirate":
        first = f'<div class=mono style="top:198px;font-size:30px;letter-spacing:2px">CAPTAIN\'S LOG / {html.escape(p.get("tag", "CAREERS")).upper()}</div>'
    else:
        first = f'<div class=mono style="top:198px;font-size:30px">wei@careerville:~$ {p["cmd"]}</div>'
    return f"""{top()}{bars(1)}{img(BIG, 'position:absolute;left:380px;top:690px')}{first}
<div id="m" style="position:absolute;left:60px;top:285px;font-weight:900;font-size:116px;line-height:128px;letter-spacing:-2px;white-space:nowrap">{lines}</div>
{subpill(p['pill'], 285+128*len(p['head'])+36)}"""

def hack(p, i):
    h, sub, do = p["hacks"][i]
    hf = f"font-family:{SERIF};font-weight:800;font-size:86px;line-height:104px;letter-spacing:-1px" if THEME == "only" else "font-weight:800;font-size:92px;line-height:112px;letter-spacing:-1.5px"
    return f"""{top()}{img(ICON, '', 'icon')}
<div class=mono style="top:200px;font-size:34px;letter-spacing:{'0' if THEME == 'hacker' else '3px'}">{T['label'].format(n=i+1)}</div>
<div id="m" style="position:absolute;left:60px;top:290px;width:960px">
 <div style="{hf}">{h}</div>
 <div style="width:220px;height:10px;border-radius:5px;background:{T['acc']};margin-top:8px"></div>
 <div style="font-weight:500;font-size:52px;line-height:68px;color:{T['soft']};margin-top:46px;width:900px">{sub}</div>
 <div style="margin-top:40px;border:2px solid {T['boxline']};border-radius:38px;background:{T['box']};padding:24px 40px 34px">
  <div class=pill style="position:static;display:inline-flex;height:48px;font-size:24px;border-radius:24px;padding:0 16px"><span class=d style="width:10px;height:10px"></span>{T['boxlabel']}</div>
  <div style="font-weight:800;font-size:52px;line-height:68px;margin-top:14px;letter-spacing:-.5px">{do}</div>
 </div></div>
<div class=swipe>swipe &nbsp;&gt;</div>{bars(i+2)}"""

def outro(p):
    t, b1, b2 = p["out"]
    dot = f'<span class=d style="background:{T["dot"]};width:20px;height:20px;margin-right:26px"></span>'
    tf = f"font-family:{SERIF};font-weight:900;font-size:92px;line-height:110px;letter-spacing:-1px" if THEME == "only" else "font-weight:900;font-size:96px;line-height:114px;letter-spacing:-1.5px"
    return f"""{top()}{img(CIRC, 'position:absolute;left:628px;top:826px;width:420px')}
<div id="m" style="position:absolute;left:60px;top:230px;width:960px">
<div style="{tf}">{t}</div>
<div style="margin-top:30px;font-weight:800;font-size:50px;line-height:68px;color:{T['acc']}">{T['cta']}</div>
<div style="margin-top:34px;font-weight:600;font-size:40px;line-height:70px;white-space:nowrap"><div>{dot}{b1}</div><div>{dot}{b2}</div></div></div>
{bars(7)}"""

LAYOUT = []
async def main():
    only = sys.argv[3:]
    async with async_playwright() as pw:
        br = await pw.chromium.launch(); pg = await br.new_page(viewport={"width": 1080, "height": 1350})
        for pi, p in enumerate(POSTS, 1):
            if only and str(pi) not in only: continue
            os.makedirs(f"{OUT}/Post {pi}", exist_ok=True)
            bodies = [cover(p)] + [hack(p, i) for i in range(5)] + [outro(p)]
            for si, b in enumerate(bodies, 1):
                await pg.set_content(f"<html><head><style>{CSS}</style></head><body>{b}</body></html>")
                await pg.wait_for_timeout(150)
                await pg.screenshot(path=f"{OUT}/Post {pi}/{si}.jpg", type="jpeg", quality=92)
                r = await pg.evaluate("(()=>{const e=document.getElementById('m');const b=e.getBoundingClientRect();return {bottom:b.bottom,right:b.left+e.scrollWidth}})()")
                LAYOUT.append({"post": pi, "slide": si, "bottom": r["bottom"], "right": r["right"]})
        await br.close()
    json.dump(LAYOUT, open(f"{OUT}/layout.json", "w"))
asyncio.run(main())
