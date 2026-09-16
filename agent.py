import os, re, json, time, random
from collections import defaultdict
from datetime import date, timedelta
from curl_cffi import requests
from bs4 import BeautifulSoup

THREAD = "https://www.rusfishing.ru/forum/threads/rybalka-v-krasnogorske.32280"
START_DATE = "2024-01-01"
BALANCE_START = "2026-09-09"
BALANCE_START_KG = 580
ADMIN_AUTHORS = ["Александр Salmo", "Митяй-Митиноо", "Митяй Митино", "митяй-митиноо", "александр salmo"]
BATCH = 150
REFRESH_TAIL = 100

FOREL_RX = re.compile(r"форел", re.I)
OTHER_FISH = re.compile(r"осет|осётр|карп|сом\b|щук|белуг|стерляд|карас|окун|судак|сиг\b|налим|амур|толстолоб|линь", re.I)
DATE_RX = re.compile(r"(?<!\d)(\d{1,2})\.(\d{2})(?:\.(\d{2,4}))?(?!\d)")
KG_RX = re.compile(r"(\d+(?:[.,]\d+)?)(?:\s*[-–—]\s*(\d+(?:[.,]\d+)?))?\s*(кг|килограмм\w*|тонн\w*|т)\b", re.I)
STOCK_KW = re.compile(r"запуск|запустили|зарыбление|зарыбили|завезли|завоз|выпустили", re.I)
CATCH_KW = re.compile(r"вылов\w*|итог дня|итого", re.I)
FUTURE_KW = re.compile(r"сделаем|будет|будут|планир|анонс|ожидается", re.I)

TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Форель Красногорск</title><script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script><style>
body{font-family:system-ui,sans-serif;margin:0 auto;padding:12px;background:#0f172a;color:#e2e8f0;max-width:820px}
h1{font-size:1.4rem;background:linear-gradient(90deg,#38bdf8,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:#1e293b;border-radius:14px;padding:14px;margin:10px 0}.big{font-size:1.8rem;font-weight:800;color:#fbbf24}
table{width:100%;border-collapse:collapse;font-size:.8rem}td,th{padding:6px 4px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}
a{color:#7dd3fc;text-decoration:none}.note{font-size:.8rem;color:#94a3b8}.q{color:#94a3b8;font-size:.75rem}</style></head><body>
<h1>🎣 Форель в Красногорске</h1>
<h2>🐟 Остаток форели</h2><div class="card"><div class="big" id="r">—</div>
<div class="note">запущено <b id="s">0</b> − выловлено <b id="c">0</b> кг • с <span id="bs"></span> (старт <span id="sk">580</span>)<br>последний запуск: <span id="dsl">—</span> • <span id="up"></span></div></div>
<div class="card" id="bx"><canvas id="bal"></canvas></div>
<h3>Журнал запусков и выловов (только админы)</h3><div class="card"><table id="ev"></table></div><div class="note">Данные только от админов. Анонсы → дата анонса, при подтверждении заменяются.</div>
<h2>📊 Активность с 2024</h2><div class="card"><div class="note" id="pg"></div><div class="big" style="color:#38bdf8" id="tot">0</div><div class="note">постов за <span id="dy">0</span> дней</div></div>
<h3>По месяцам</h3><div class="card"><canvas id="m"></canvas></div>
<h3>Клёв vs давление</h3><div class="card"><canvas id="p"></canvas></div>
<h3>Последние дни</h3><div class="card"><table id="t"></table></div>
<script>
try{
var D=__DATA__;var B=D.balance||{};
document.getElementById('bs').textContent=B.start||'2026-09-09';document.getElementById('sk').textContent=B.start_kg||580;
document.getElementById('s').textContent=B.ts||0;document.getElementById('c').textContent=B.tc||0;
document.getElementById('r').textContent=(B.ev&&B.ev.length)?('≈ '+(B.rem||0)+' кг'):'ждём данных...';
document.getElementById('dsl').textContent=(B.dss!=null)?B.dss+' дн. назад':'нет';
document.getElementById('up').textContent=(D.st&&D.st.up)||'';
if(B.sr&&B.sr.dates&&B.sr.dates.length){new Chart(bal,{data:{labels:B.sr.dates,datasets:[
{type:'line',label:'Остаток',data:B.sr.rem,borderColor:'#fbbf24',tension:0.3,pointRadius:0,borderWidth:2},
{type:'bar',label:'Запуск',data:B.sr.stk,backgroundColor:'#4ade80'},{type:'bar',label:'Вылов',data:B.sr.ctc,backgroundColor:'#f87171'}]},
options:{plugins:{legend:{labels:{color:'#e2e8f0',boxWidth:12}}},scales:{x:{ticks:{maxTicksLimit:8,color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'}}}});}
else document.getElementById('bx').innerHTML='<div class="note">Данные появятся с '+((B.start||'2026-09-09'))+'</div>';
if(B.ev&&B.ev.length) document.getElementById('ev').innerHTML='<tr><th>Дата</th><th></th><th>кг</th><th>Цитата</th></tr>'+B.ev.map(function(e){return '<tr><td>'+e.day+'</td><td>'+(e.t=='s'?'🟢':'🔴')+'</td><td><b>'+e.kg+'</b></td><td class="q"><a href="'+e.u+'" target="_blank">'+e.q+'</a></td></tr>';}).join('');
else document.getElementById('ev').innerHTML='<tr><td class="note">Пока нет записей.</td></tr>';
if(D.st){document.getElementById('pg').textContent='Страниц: '+(D.st.col||0)+'/'+(D.st.need||0);document.getElementById('tot').textContent=D.st.tp||0;document.getElementById('dy').textContent=D.st.dy||0;
if(D.st.mo) new Chart(m,{type:'bar',data:{labels:Object.keys(D.st.mo),datasets:[{data:Object.values(D.st.mo),backgroundColor:'#38bdf8'}]},options:{plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'}}}});
if(D.st.pr) new Chart(p,{type:'bar',data:{labels:Object.keys(D.st.pr),datasets:[{data:Object.values(D.st.pr),backgroundColor:'#4ade80'}]},options:{plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'}}}});}
if(D.tb) document.getElementById('t').innerHTML='<tr><th>Дата</th><th>П</th><th>t°</th><th>Давл</th><th>Осадки</th><th></th></tr>'+D.tb.map(function(r){return '<tr><td>'+r.d+'</td><td>'+r.p+'</td><td>'+(r.t||'—')+'</td><td>'+(r.prs||'—')+'</td><td>'+(r.pc||'—')+'</td><td>'+(r.l||[]).map(function(u,i){return '<a href="'+u+'" target="_blank">#'+(i+1)+'</a>'}).join(' ')+'</td></tr>';}).join('');
}catch(e){console.error(e);}
</script></body></html>"""

def page_url(p):
    return THREAD if p == 1 else f"{THREAD}/page-{p}"

def fetch(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, impersonate="chrome120", timeout=25)
            if r.status_code == 200:
                return r.text
            print(f"Status {r.status_code} on {url}")
        except Exception as e:
            print(f"Retry {i+1}: {e}")
        time.sleep(3 * (i + 1))
    return None

def parse_posts(html, page):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for msg in soup.select("article.message"):
        raw = msg.get("id", "")
        m = re.search(r"(\d+)", raw)
        pid = m.group(1) if m else f"p{page}_{len(out)}"
        t = msg.select_one("time")
        b = msg.select_one(".bbWrapper")
        if not b:
            continue
        for q in b.select("blockquote"):
            q.decompose()
        out.append({"post_id": pid, "page": page,
            "author": msg.get("data-author", ""),
            "post_dt": (t.get("datetime") or "") if t else "",
            "text": b.get_text("\n", strip=True)})
    return out

def total_pages(html):
    soup = BeautifulSoup(html, "lxml")
    nav = soup.select_one(".pageNav")
    if nav and nav.get("data-last"):
        try:
            return int(nav["data-last"])
        except:
            pass
    nums = []
    for a in soup.select(".pageNav a"):
        tt = a.get_text(strip=True).replace(" ", "")
        if tt.isdigit():
            nums.append(int(tt))
    return max(nums) if nums else 10451

def first_date(html):
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    t = soup.select_one("article.message time")
    return (t.get("datetime") or "")[:10] if t else ""

def load_state():
    if os.path.exists("state.json"):
        try:
            return json.load(open("state.json", encoding="utf-8"))
        except:
            return {}
    return {}

def snip(text, pos, w=70):
    a = max(0, pos - 12)
    b = min(len(text), pos + w)
    s = re.sub(r"\s+", " ", text[a:b]).strip()
    if a > 0:
        s = "…" + s
    if b < len(text):
        s = s + "…"
    return s

def resolve_dt(text, s, e, post_dt):
    pd = (post_dt or "")[:10]
    try:
        py = int(pd[:4])
    except:
        py = date.today().year
    ls = text.rfind("\n", 0, s)
    ls = 0 if ls < 0 else ls + 1
    le = text.find("\n", e)
    le = len(text) if le < 0 else le
    ln = text[ls:le]
    for scope in (ln, text[max(0,s-40):min(len(text),e+40)]):
        m = DATE_RX.search(scope)
        if m:
            try:
                d = int(m.group(1)); mo = int(m.group(2))
                yr = m.group(3)
                if yr:
                    yl = len(yr)
                    if yl == 2:
                        yy = int(yr)
                        yy = 2000 + yy if yy < 50 else 1900 + yy
                    else:
                        yy = int(yr)
                else:
                    yy = py
                if 1 <= d <= 31 and 1 <= mo <= 12:
                    return f"{yy:04d}-{mo:02d}-{d:02d}", True
            except:
                pass
    if "завтра" in ln.lower():
        try:
            pdd = date.fromisoformat(pd)
            return str(pdd + timedelta(days=1)), True
        except:
            pass
    return pd, False

def find_events(text, post_dt):
    results = []
    pd = (post_dt or "")[:10]

    # Compact pattern: "Запуск X кг вылов Y кг"
    for cm in re.finditer(
        r'(?:запуск\w*\s*[:\-–]?)\s*(\d+)\s*(?:кг)\s*[,\s]*(?:вылов(?:\w*)\s*[:\-–]?)\s*(\d+)\s*(?:кг)',
        text, re.I
    ):
        s, e = cm.span()
        try:
            sk = int(cm.group(1))
            ck = int(cm.group(2))
        except:
            continue
        ctx = text[max(0,s-200):min(len(text),e+200)]
        if FOREL_RX.search(ctx) and not OTHER_FISH.search(text[max(0,s-50):min(len(text),e+50)]):
            ed, _ = resolve_dt(text, s, e, post_dt)
            hh = post_dt[11:16] if len(post_dt) >= 16 else ""
            pds = post_dt[5:10] if len(post_dt) >= 10 else ""
            if ed >= BALANCE_START:
                results.append({"kind": "s", "kg": sk, "dt": ed, "quote": snip(text, s), "pdt": post_dt})
                results.append({"kind": "c", "kg": ck, "dt": ed, "quote": snip(text, cm.start(2)), "pdt": post_dt})

    # Standard patterns
    spans = []
    for m in KG_RX.finditer(text):
        s, e = m.span()
        spans.append((s, e))

    def ov(s, e):
        for a, b in spans:
            if not (e < a or s > b):
                return True
        return False

    for m in KG_RX.finditer(text):
        s, e = m.span()
        if ov(s, e):
            continue
        win_a = max(0, s - 120)
        win_b = min(len(text), e + 120)
        win = text[win_a:win_b]
        hs = bool(STOCK_KW.search(win))
        hc = bool(CATCH_KW.search(win))
        if not hs and not hc:
            continue
        kind = None
        if hs and hc:
            nc = (s + e) / 2
            def cp(pat):
                best = 99999
                for km in pat.finditer(win):
                    kc = win_a + (km.start() + km.end()) / 2
                    dd = abs(kc - nc)
                    if dd < best:
                        best = dd
                return best
            kind = "s" if cp(STOCK_KW) <= cp(CATCH_KW) else "c"
        elif hs:
            kind = "s"
        else:
            kind = "c"
        try:
            n1 = float(m.group(1).replace(",", "."))
            n2 = m.group(2)
            val = (n1 + float(n2.replace(",", "."))) / 2 if n2 else n1
            unit = (m.group(3) or "").lower()
            if unit.startswith("тон") or unit == "т":
                val *= 1000
            kg = int(round(val))
        except:
            continue
        if kind == "s" and not (30 <= kg <= 20000):
            continue
        if kind == "c" and not (5 <= kg <= 20000):
            continue
        if kind == "s":
            if not FOREL_RX.search(text[max(0,s-250):min(len(text),e+250)]):
                continue
            ed, idt = resolve_dt(text, s, e, post_dt)
            before = text[max(0,s-60):s].lower()
            if not idt and FUTURE_KW.search(before):
                continue
        else:
            ed, idt = pd, False
        results.append({"kind": kind, "kg": kg, "dt": ed, "quote": snip(text, s), "pdt": post_dt})

    # No-unit patterns
    for pat, kind in [
        (re.compile(r"(запуск\w*|запушили|зарыбление\w*)\s*[:\-–]?\s*(\d{2,4})\b", re.I), "s"),
        (re.compile(r"(вылов\w*|итог\w*)\s*[:\-–]?\s*(\d{1,4})\b", re.I), "c"),
    ]:
        for m in pat.finditer(text):
            s, e = m.span()
            if ov(s, e):
                continue
            try:
                kg = int(m.group(2))
            except:
                continue
            if kind == "s" and not (30 <= kg <= 20000):
                continue
            if kind == "c" and not (5 <= kg <= 20000):
                continue
            if kind == "s":
                if not FOREL_RX.search(text[max(0,s-250):min(len(text),e+250)]):
                    continue
                ed, idt = resolve_dt(text, s, e, post_dt)
                before = text[max(0,s-60):s].lower()
                if not idt and FUTURE_KW.search(before):
                    continue
            else:
                ed, idt = pd, False
            results.append({"kind": kind, "kg": kg, "dt": ed, "quote": snip(text, s), "pdt": post_dt})

    dated_s = [r for r in results if r["kind"] == "s" and r["dt"] != (r.get("pdt") or "")[:10]]
    if dated_s:
        results = [r for r in results if not (r["kind"] == "s" and r["dt"] == (r.get("pdt") or "")[:10])]
    return results

def main():
    os.makedirs("pages", exist_ok=True)
    import sqlite3
    DB = sqlite3.connect("fishing.db")
    DB.execute("DROP TABLE IF EXISTS posts")
    DB.execute("CREATE TABLE posts (id TEXT PRIMARY KEY, pg INT, auth TEXT, dt TEXT, tx TEXT)")
    state = load_state()
    print("Checking forum...")
    h1 = fetch(page_url(1))
    if not h1:
        raise SystemExit("Forum unreachable")
    last = total_pages(h1)
    print(f"Total pages: {last}")

    if not state.get("sp"):
        print("Finding 2024...")
        lo, hi = 1, last
        while lo < hi:
            mid = (lo + hi) // 2
            h = fetch(page_url(mid))
            d = first_date(h) if h else ""
            print(f"  pg.{mid}: {d or '?'}")
            time.sleep(1.5)
            if not d or d >= START_DATE:
                hi = mid
            else:
                lo = mid + 1
        state["sp"] = max(1, lo - 1)
        state["cur"] = last
        state["nw"] = last

    sp = state["sp"]
    td = []
    if last > state.get("nw", last):
        for p in range(state["nw"] + 1, last + 1):
            td.append(p)
        state["nw"] = last

    p = state.get("cur", last)
    add = []
    while len(add) < BATCH and p >= sp:
        fn = f"pages/page_{p:06d}.json"
        if not os.path.exists(fn):
            add.append(p)
        p -= 1
    state["cur"] = p

    tail = list(range(max(sp, last - REFRESH_TAIL + 1), last + 1))
    todo = sorted(set(td + add + tail))
    print(f"Downloading {len(todo)} pages...")

    for i, pg in enumerate(todo):
        h = fetch(page_url(pg))
        if h:
            ps = parse_posts(h, pg)
            json.dump(ps, open(f"pages/page_{pg:06d}.json", "w", encoding="utf-8"), ensure_ascii=False)
            print(f" {i+1}/{len(todo)} pg.{pg}: {len(ps)} posts")
        time.sleep(random.uniform(1.5, 2.5))
        if (i + 1) % 20 == 0:
            json.dump(state, open("state.json", "w"), ensure_ascii=False)

    for fn in os.listdir("pages"):
        if not fn.endswith(".json"):
            continue
        try:
            ps = json.load(open(f"pages/{fn}", encoding="utf-8"))
            for po in ps:
                dtv = po.get("post_dt") or po.get("post_date") or ""
                DB.execute("INSERT OR IGNORE INTO VALUES (?,?,?,?,?)",
                          (po.get("post_id",""), po.get("pg",0), po.get("auth",""), dtv, po.get("tx","")))
            DB.commit()
        except:
            continue

    json.dump(state, open("state.json", "w"), ensure_ascii=False)
    try:
        build(DB, state, last)
        print("DONE ✅")
    except Exception as ex:
        print(f"BUILD ERROR: {ex}")
        import traceback
        traceback.print_exc()
        raise

def build(DB, state, last):
    days = defaultdict(list)
    dsc = defaultdict(list)  # day stock candidates
    dcc = defaultdict(list)  # day catch candidates
    al = [a.lower() for a in ADMIN_AUTHORS]

    for pid, pg, auth, pdt, tx in DB.execute("SELECT id,pg,auth,dt,tx FROM posts"):
        d = (pdt or "")[:10]
        url = f"{THREAD}/page-{pg}#post-{pid}" if pid else f"{THREAD}/page-{pg}"
        if d and FOREL_RX.search(tx or "") and d >= START_DATE:
            days[d].append(url)
        if not pdt or not d:
            continue
        if d < BALANCE_START:
            try:
                if (date.fromisoformat(BALANCE_START) - date.fromisoformat(d)).days > 10:
                    continue
            except:
                continue
        if ADMIN_AUTHORS and (auth or "").lower() not in al:
            continue
        try:
            evs = find_events(tx or "", pdt)
        except Exception as ex:
            print(f"Parse err on {d}: {ex}")
            continue
        for ev in evs:
            ed = ev["dt"]
            if not ed or ed < BALANCE_START:
                continue
            hh = pdt[11:16] if len(pdt) >= 16 else ""
            pds = pdt[5:10] if len(pdt) >= 10 else ""
            rec = {"kg": ev["kg"], "u": url, "q": f"post {pds} {hh} {ev['quote']}"[:140], "pdt": pdt,
                   "fact": (pdt[:10] == ed)}
            if ev["kind"] == "s":
                dsc[ed].append(rec)
            else:
                dcc[ed].append(rec)

    ds = {}  # final day stock
    for dd, lst in dsc.items():
        facts = [r for r in lst if r["fact"]]
        pool = facts if facts else lst
        if facts:
            ds[dd] = sorted(pool, key=lambda x: x["pdt"])[0]
        else:
            ds[dd] = sorted(pool, key=lambda x: x["pdt"])[-1]

    dc = {}  # final day catch
    for dd, lst in dcc.items():
        dc[dd] = sorted(lst, key=lambda x: x["pdt"])[-1]

    dev = {}
    for dd, r in ds.items():
        dev.setdefault(dd, {})["s"] = r
    for dd, r in dc.items():
        dev.setdefault(dd, {})["c"] = r

    weather = {}
    try:
        w = requests.get("https://archive-api.open-meteo.com/v1/archive", params={
            "latitude": 55.82, "longitude": 37.33,
            "start_date": START_DATE,
            "end_date": str(date.today() - timedelta(days=5)),
            "daily": "temperature_2m_mean,precipitation_sum,pressure_msl_mean",
            "timezone": "Europe/Moscow"}, timeout=30).json()["daily"]
        for i, dy in enumerate(w["time"]):
            pr = w["pressure_msl_mean"][i]
            weather[dy] = {
                "tmp": w["temperature_2m_mean"][i],
                "prc": w["precipitation_sum"][i],
                "prs": round(pr * 0.75006, 1) if pr else None
            }
    except Exception as e:
        print(f"Weather fail: {e}")

    ma = defaultdict(list)
    pr = {"<745": [], "745-760": [], ">760": []}
    for dd, urls in days.items():
        ma[dd[:7]].append(len(urls))
        pw = (weather.get(dd) or {}).get("prs")
        if pw:
            k = "<745" if pw < 745 else "745-760" if pw <= 760 else ">760"
            pr[k].append(len(urls))

    avg = lambda l: round(sum(l)/len(l), 2) if l else 0
    import glob
    col = len(glob.glob("pages/*.json"))
    need = state.get("nw", last) - state.get("sp", last) + 1
    stats = {
        "mo": {m: avg(v) for m, v in sorted(ma.items())},
        "pr": {k: avg(v) for k, v in pr.items()},
        "tp": sum(len(v) for v in days.values()),
        "dy": len(days),
        "col": col, "need": max(need, 1),
        "pc": round(col / max(need,1) * 100, 1),
        "up": str(date.today())
    }
    tbl = []
    for dd in sorted(days, reverse=True)[:60]:
        wv = weather.get(dd) or {}
        tbl.append({
            "d": dd, "p": len(days[dd]),
            "t": wv.get("tmp"), "prs": wv.get("prs"),
            "pc": wv.get("prc"), "l": days[dd][:5]
        })

    # === BALANCE ===
    bds, bst, bct, brm = [], [], [], []
    ts = tc = 0
    rem = BALANCE_START_KG
    lsd = None
    sd = date.fromisoformat(BALANCE_START)
    today = date.today()

    bds.append(str(sd)); bst.append(0); bct.append(0); brm.append(rem)
    cur = sd + timedelta(days=1)
    while cur <= today:
        ds_str = str(cur)
        ev = dev.get(ds_str, {})
        s = ev.get("s", {}).get("kg", 0)
        c = ev.get("c", {}).get("kg", 0)
        ts += s; tc += c
        rem = max(0, rem + s - c)
        if s:
            lsd = ds_str
        bds.append(ds_str); bst.append(s); bct.append(c); brm.append(rem)
        cur += timedelta(days=1)

    dss = (today - date.fromisoformat(lsd)).days if lsd else None
    ev_list = []
    for dd in sorted(dev, reverse=True)[:50]:
        for k in ("s", "c"):
            if k in dev[dd]:
                e = dev[dd][k]
                ev_list.append({"day": dd, "t": k, "kg": e["kg"], "u": e["u"], "q": e["q"]})

    balance = {
        "start": BALANCE_START, "start_kg": BALANCE_START_KG,
        "ts": ts, "tc": tc, "rem": brm[-1] if brm else 0,
        "dss": dss,
        "sr": {"dates": bds, "stk": bst, "ctc": bct, "rem": brm},
        "ev": ev_list
    }

    payload = json.dumps({"st": stats, "tb": tbl, "balance": balance}, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")
    open("index.html", "w", encoding="utf-8").write(TEMPLATE.replace("__DATA__", payload))
    print(f"Site built: remaining {brm[-1] if brm else 0} kg ({ts} stocked / {tc} caught)")

if __name__ == "__main__":
    main()
