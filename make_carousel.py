"""Hacker Wei carousel generator.
Usage: python3 make_carousel.py specs/my_posts.json out_dir
Each spec: cmd, head (list of lines, <g>word</g> = lime), pill, hacks (5 x [headline, grey line, DO THIS line]), out (title, bullet1, bullet2).
Renders Post N/1.jpg to 7.jpg at 1080x1350. Needs: pip install playwright, chromium, Inter font."""
import asyncio, base64, os, sys, json
from playwright.async_api import async_playwright
HERE=os.path.dirname(os.path.abspath(__file__)); A=HERE+'/asset_'
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
BIG=b64(A+'big.png'); ICON=b64(A+'icon.png'); CIRC=b64(A+'circ.png')
POSTS=json.load(open(sys.argv[1])); OUT=sys.argv[2]
CSS=f"""
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1350px;position:relative;overflow:hidden;background:#0c0a17;font-family:'Inter';color:#fff}}
.bg{{position:absolute;inset:0;background:
 radial-gradient(ellipse 900px 640px at 1000px 20px, rgba(66,36,112,.75), rgba(66,36,112,0) 100%),
 #0c0a17}}
.grid{{position:absolute;inset:0;background-image:
 linear-gradient(to right, rgba(6,4,14,.38) 1px, transparent 1px),
 linear-gradient(to bottom, rgba(6,4,14,.38) 1px, transparent 1px);
 background-size:90px 90px;background-position:0 0}}
.pill{{position:absolute;left:60px;top:60px;height:52px;padding:0 17px;border-radius:26px;background:#a259d9;display:flex;align-items:center;font-weight:800;font-size:26px;letter-spacing:.2px}}
.d{{display:inline-block;width:11px;height:11px;background:#fff;transform:rotate(45deg) ;margin-right:9px;border-radius:2px}}
.mono{{font-family:'DejaVu Sans Mono';font-weight:700;color:#b8f04a;position:absolute;left:60px}}
.g{{color:#b8ff4f}} g{{color:#b8ff4f}}
.bar{{position:absolute;top:1280px;height:9px;border-radius:5px;width:130px}}
.swipe{{position:absolute;right:62px;top:1224px;font-family:'DejaVu Sans Mono';font-weight:700;font-size:30px;color:#c9c3e6;letter-spacing:1px}}
.icon{{position:absolute;left:905px;top:44px;width:112px;height:112px}}
"""
def bars(n):
    s=''
    for i in range(7):
        col='#c0ff58' if i<n else '#3c345b'
        s+=f'<div class="bar" style="left:{60+i*139}px;background:{col}"></div>'
    return s
def cover(p):
    lines=''.join(f'<div>{l}</div>' for l in p['head'])
    return f"""<div class=bg></div><div class=grid></div>
{bars(1)}
<img src="data:image/png;base64,{BIG}" style="position:absolute;left:380px;top:690px">
<div class=pill><span class=d></span>HACKER WEI</div>
<div class=mono style="top:198px;font-size:30px">wei@careerville:~$ {p['cmd']}</div>
<div id="m" style="position:absolute;left:60px;top:285px;font-weight:900;font-size:116px;line-height:128px;letter-spacing:-2px;white-space:nowrap">{lines}</div>
<div class=pill style="top:{285+128*len(p['head'])+36}px;height:68px;border-radius:34px;font-size:34px;padding:0 22px;position:absolute"><span class=d style="width:14px;height:14px"></span>{p['pill']}</div>"""
def hack(p,i):
    h,sub,do=p['hacks'][i]
    return f"""<div class=bg></div><div class=grid></div>
<div class=pill><span class=d></span>HACKER WEI</div>
<img class=icon src="data:image/png;base64,{ICON}">
<div class=mono style="top:200px;font-size:34px">&gt; hack_0{i+1}</div>
<div id="m" style="position:absolute;left:60px;top:290px;width:960px">
 <div style="font-weight:800;font-size:92px;line-height:112px;letter-spacing:-1.5px"><span style="display:inline;position:relative">{h}</span></div>
 <div style="width:220px;height:10px;border-radius:5px;background:#b8ff4f;margin-top:8px"></div>
 <div style="font-weight:500;font-size:52px;line-height:68px;color:#c9c3e6;margin-top:46px;width:900px">{sub}</div>
 <div style="margin-top:40px;border:2px solid #a259d9;border-radius:38px;background:#1f1838;padding:24px 40px 34px">
  <div class=pill style="position:static;display:inline-flex;height:48px;font-size:24px;border-radius:24px;padding:0 16px"><span class=d style="width:10px;height:10px"></span>DO THIS</div>
  <div style="font-weight:800;font-size:52px;line-height:68px;margin-top:14px;letter-spacing:-.5px">{do}</div>
 </div></div>
<div class=swipe>swipe &nbsp;&gt;</div>{bars(i+2)}"""
def outro(p):
    t,b1,b2=p['out']
    dot='<span class=d style="background:#ec6fc3;width:20px;height:20px;margin-right:26px"></span>'
    return f"""<div class=bg></div><div class=grid></div>
<div class=pill><span class=d></span>HACKER WEI</div>
<img src="data:image/png;base64,{CIRC}" style="position:absolute;left:628px;top:826px;width:420px">
<div id="m" style="position:absolute;left:60px;top:230px;width:960px">
<div style="font-weight:900;font-size:96px;line-height:114px;letter-spacing:-1.5px">{t}</div>
<div style="margin-top:30px;font-weight:800;font-size:50px;line-height:68px;color:#b8ff4f">Comment the number. Follow for a new hack every day.</div>
<div style="margin-top:34px;font-weight:600;font-size:40px;line-height:70px;white-space:nowrap"><div>{dot}{b1}</div><div>{dot}{b2}</div></div></div>
{bars(7)}"""
LAYOUT=[]
async def main():
    only=sys.argv[3:]
    async with async_playwright() as pw:
        br=await pw.chromium.launch(); pg=await br.new_page(viewport={'width':1080,'height':1350})
        for pi,p in enumerate(POSTS,1):
            if only and str(pi) not in only: continue
            os.makedirs(f'{OUT}/Post {pi}',exist_ok=True)
            bodies=[cover(p)]+[hack(p,i) for i in range(5)]+[outro(p)]
            for si,b in enumerate(bodies,1):
                await pg.set_content(f'<html><head><style>{CSS}</style></head><body>{b}</body></html>')
                await pg.wait_for_timeout(150)
                await pg.screenshot(path=f'{OUT}/Post {pi}/{si}.jpg',type='jpeg',quality=92)
                r=await pg.evaluate("(()=>{const e=document.getElementById('m');const b=e.getBoundingClientRect();return {bottom:b.bottom,right:b.left+e.scrollWidth}})()")
                LAYOUT.append({'post':pi,'slide':si,'bottom':r['bottom'],'right':r['right']})
        await br.close()
    json.dump(LAYOUT,open(f'{OUT}/layout.json','w'))
asyncio.run(main())
