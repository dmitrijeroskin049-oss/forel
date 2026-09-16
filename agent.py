import os, re, json, time, random
from collections import defaultdict
from datetime import date, timedelta
from curl_cffi import requests
from bs4 import BeautifulSoup

THREAD = "https://www.rusfishing.ru/forum/threads/rybalka-v-krasnogorske.32280"
START_DATE = "2024-01-01"
BALANCE_START = "2026-09-09"       # Дата первого известного остатка (+-580кг)
BALANCE_START_KG = 580             # Стартовый остаток в этот день
ADMIN_AUTHORS = ["Александр Salmo", "Митяй-Митиноо", "Митяй Митино", "митяй-митиноо", "александр salmo"]
BATCH = 150
REFRESH_TAIL = 100

FOREL_RX = re.compile(r"форел", re.I)
OTHER_FISH = re.compile(r"осет|осётр|карп|сом\b|щук|белуг|стерляд|карас|окун|судак|сиг\b|налим|амур|толстолоб|линь", re.I)
DATE_RX = re.compile(r"(?<!\d)(\d{1,2})\.(\d{2})(?:\.(\d{2,4}))?(?!\d)")
KG_RX = re.compile(r"(\d+(?:[.,]\d+)?)(?:\s*[-–—]\s*(\d+(?:[.,]\d+)?))?\s*(кг|килограмм\w*|тонн\w*|т)\b", re.I)
STOCK_KW_RX = re.compile(r"запуск|запустили|зарыбление|зарыбили|завезли|завоз|выпустили", re.I)
CATCH_KW_RX = re.compile(r"вылов\w*|итог дня|итого", re.I)
FUTURE_RX = re.compile(r"сделаем|будет|будут|планиру|анонс|ожидается|собирается|намечает", re.I)
NABECKA_RX = re.compile(r"навеска", re.I)

TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Форель Красногорск</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
body{font-family:system-ui,-apple-system,sans-serif;margin:0 auto;padding:12px;background:#0f172a;color:#e2e8f0;max-width:820px}
h1{font-size:1.4rem;background:linear-gradient(90deg,#38bdf8,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:#1e293b;border-radius:14px;padding:14px;margin:10px 0}
.big{font-size:1.8rem;font-weight:800;color:#fbbf24}
table{width:100%;border-collapse:collapse;font-size:.8rem}
td,th{padding:6px 4px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}
a{color:#7dd3fc;text-decoration:none}
.note{font-size:.8rem;color:#94a3b8}
.q{color:#94a3b8;font-size:.75rem}
</style></head><body>
<h1>🎣 Форель в Красногорске</h1>
<h2>🐟 Остаток форели в водоёме</h2>
<div class="card"><div class="big" id="rem">—</div>
<div class="note">запущено <b id="st">0</b> кг − выловлено <b id="ct">0</b> кг • отсчёт с <span id="bs"></span> (старт ≈<span id="startkg">580</span> кг)<br>
последний запуск: <span id="dsl">—</span> • обновлено <span id="upd2"></span></div></div>
<div class="card" id="balbox"><canvas id="bal"></canvas></div>
<h3>Журнал запусков и выловов (только админы)</h3>
<div class="card"><table id="ev"></table></div>
<div class="note">Данные берутся только из постов администраторов: Александр Salmo, Митяй-Митиноо. Анонсы будущих запусков относятся на их дату и заменяются фактами при подтверждении.</div>

<h2>📊 Активность обсуждений с 2024</h2>
<div class="card"><div class="note" id="prog"></div><div class="big" style="color:#38bdf8" id="total">0</div>
<div class="note">постов про форель за <span id="days">0</span> активных дней</div></div>
<h3>Активность по месяцам (постов/день)</h3><div class="card"><canvas id="m"></canvas></div>
<h3>Клёв vs давление</h3><div class="card"><canvas id="p"></canvas></div>
<h3>Последние активные дни</h3><div class="card"><table id="t"></table></div>
<script>
try {
const D=__DATA__;
const B=D.balance||{};
document.getElementById('bs').textContent=B.start||'2026-09-09';
document.getElementById('startkg').textContent=B.start_kg||580;
document.getElementById('st').textContent=B.total_stocked||0;
document.getElementById('ct').textContent=B.total_caught||0;
document.getElementById('rem').textContent=(B.events&&B.events.length)?('≈ '+(B.remaining||0)+' кг'):'Ожидание данных...';
document.getElementById('dsl').textContent=(B.days_since_stock!==null&&B.days_since_stock!==undefined)?(B.days_since_stock+' дн. назад'):'нет данных';
document.getElementById('upd2').textContent=(D.stats&&D.stats.updated)||'';
if(B.series&&B.series.dates&&B.series.dates.length>0){
new Chart(document.getElementById('bal'),{data:{labels:B.series.dates,datasets:[
{type:'line',label:'Остаток кг',data:B.series.remaining,borderColor:'#fbbf24',tension:0.3,pointRadius:0,borderWidth:2},
{type:'bar',label:'Запуск',data:B.series.stocked,backgroundColor:'#4ade80'},
{type:'bar',label:'Вылов',data:B.series.caught,backgroundColor:'#f87171'}]},
options:{plugins:{legend:{labels:{color:'#e2e8f0',boxWidth:12}}},scales:{x:{ticks:{maxTicksLimit:8,color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'}}}}});
}else{
document.getElementById('balbox').innerHTML='<div class="note">Отчёты появятся начиная с '+((B.start||'2026-09-09'))+'.</div>';
}
if(B.events&&B.events.length>0){
document.getElementById('ev').innerHTML='<tr><th>Дата</th><th></th><th>кг</th><th>Цитата</th></tr>'+
B.events.map(e=>`<tr><td>${e.day}</td><td>${e.type==='запуск'?'🟢':'🔴'}</td><td><b>${e.kg}</b></td><td class="q"><a href="${e.url}" target="_blank">${e.quote}</a></td></tr>`).join('');
}else{
document.getElementById('ev').innerHTML='<tr><td class="note">Пока нет записей.</td></tr>';
}
if(D.stats){
document.getElementById('prog').textContent='Собрано страниц: '+(D.stats.collected||0)+' из ~'+(D.stats.need||0)+' ('+(D.stats.pct||0)+'%)';
document.getElementById('total').textContent=D.stats.total_posts||0;
document.getElementById('days').textContent=D.stats.active_days||0;
if(D.stats.monthly&&Object.keys(D.stats.monthly).length>0) new Chart(document.getElementById('m'),{type:'bar',data:{labels:Object.keys(D.stats.monthly),datasets:[{data:Object.values(D.stats.monthly),backgroundColor:'#38bdf8'}]},options:{plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'}}}}});
if(D.stats.pressure&&Object.keys(D.stats.pressure).length>0) new Chart(document.getElementById('p'),{type:'bar',data:{labels:Object.keys(D.stats.pressure),datasets:[{data:Object.values(D.stats.pressure),backgroundColor:'#4ade80'}]},options:{plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'}}}}});
}
if(D.table&&D.table.length>0) document.getElementById('t').innerHTML='<tr><th>Дата</th><th>П</th><th>t°</th><th>Давл</th><th>Осадки</th><th></th></tr>'+D.table.map(r=>`<tr><td>${r.day}</td><td>${r.posts}</td><td>${r.temp??'—'}</td><td>${r.pressure??'—'}</td><td>${r.precip??'—'}</td><td>${(r.links||[]).map((u,i)=>`<a href="${u}" target="_blank">#${i+1}</a>`).join(' ')}</td></tr>`).join('');
}catch(err){console.error(err);}
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
        time.sleep(3*(i+1))
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

def snippet(text, pos, width=80):
    a = max(0, pos-15)
    b = min(len(text), pos+width)
    return "…" + re.sub(r"\s+", " ", text[a:b]).strip() + "…"

def resolve_event_date(text, s, e, post_dt):
    post_date = (post_dt or "")[:10]
    try:
        post_year = int(post_date[:4])
    except:
        post_year = date.today().year
    line_start = text.rfind("\n", 0, s)
    line_start = 0 if line_start == -1 else line_start+1
    line_end = text.find("\n", e)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    for scope in (line, text[max(0,s-40):min(len(text),e+40)]):
        m = DATE_RX.search(scope)
        if m:
            try:
                d = int(m.group(1)); mo = int(m.group(2))
                yraw = m.group(3)
                if yraw:
                    if len(yraw) == 2:
                        yy = int(yraw)
                        y = 2000+yy if yy < 50 else 1900+yy
                    else:
                        y = int(yraw)
                else:
                    y = post_year
                if 1 <= d <= 31 and 1 <= mo <= 12:
                    return f"{y:04d}-{mo:02d}-{d:02d}", True
            except:
                pass
    if "завтра" in line.lower():
        try:
            pd = date.fromisoformat(post_date)
            return str(pd+timedelta(days=1)), True
        except:
            pass
    return post_date, False

def find_stock_catch(text, post_dt):
    post_date = (post_dt or "")[:10]
    if not text:
        return []
    results = []
    
    # Новый компактный паттерн: "Запуск X кг вылов Y кг" (как у админа 09.09)
    compact = re.finditer(
        r'(?:запуск\w*\s*[:\-–]?)\s*(\d+)\s*(?:кг)\s*[,\s]*(?:вылов(?:\w*)\s*[:\-–]?)\s*(\d+)\s*(?:кг)',
        text, re.I
    )
    for cm in compact:
        s, e = cm.span()
        try:
            stock_kg = int(cm.group(1))
            catch_kg = int(cm.group(2))
        except:
            continue
        if FOREL_RX.search(text[max(0,s-200):min(len(text),e+200)]) and not OTHER_FISH.search(text[max(0,s-50):min(len(text),e+50)]):
            ev_date, _ = resolve_event_date(text, s, e, post_dt)
            hh = post_dt[11:16] if len(post_dt)>=16 else ""
            pd_short = post_dt[5:10] if len(post_dt)>=10 else ""
            if ev_date >= BALANCE_START:
                results.append({"kind":"stock","kg":stock_kg,"event_date":ev_date,"is_dated":True,
                    "quote":snippet(text,s),"dt":post_dt})
                results.append({"kind":"catch","kg":catch_kg,"event_date":ev_date,"is_dated":True,
                    "quote":snippet(text,cm.start(2)),"dt":post_dt})

    # Основные паттерны
    kg_spans = []
    for m in KG_RX.finditer(text):
        s, e = m.span()
        kg_spans.append((s,e))
        ctx60 = text[max(0,s-60):min(len(text),e+60)]
        if NABECKA_RX.search(ctx60):
            continue
        if OTHER_FISH.search(text[max(0,s-50):min(len(text),e+50)]):
            continue
        win_a = max(0,s-120); win_b = min(len(text),e+120)
        win = text[win_a:win_b]
        has_stock = bool(STOCK_KW_RX.search(win))
        has_catch = bool(CATCH_KW_RX.search(win))
        if not has_stock and not has_catch:
            continue
        if has_stock and has_catch:
            num_c = (s+e)/2
            def closest(pat):
                best = 1e9
                for km in pat.finditer(win):
                    kc = win_a+(km.start()+km.end())/2
                    dd = abs(kc-num_c)
                    if dd < best: best = dd
                return best
            kind = "stock" if closest(STOCK_KW_RX)<=closest(CATCH_KW_RX) else "catch"
        elif has_stock:
            kind = "stock"
        else:
            kind = "catch"
        try:
            n1 = float(m.group(1).replace(",","."))
            n2raw = m.group(2)
            val = (n1+float(n2raw.replace(",",".")))/2 if n2raw else n1
            unit = (m.group(3) or "").lower()
            if unit.startswith("тон") or unit=="т":
                val *= 1000
            kg = int(round(val))
        except:
            continue
        if kind=="stock" and not (30<=kg<=20000): continue
        if kind=="catch" and not (5<=kg<=20000): continue
        if kind=="stock":
            if not FOREL_RX.search(text[max(0,s-250):min(len(text),e+250)]):
                continue
            ev_date,is_dated=resolve_event_date(text,s,e,post_dt)
            before=text[max(0,s-60):s].lower()
            if not is_dated and FUTURE_RX.search(before):
                continue
        else:
            ev_date,is_dated=post_date,False
        results.append({"kind":kind,"kg":kg,"event_date":ev_date,"is_dated":is_dated,"quote":snippet(text,s),"pos":s})
        
    def overlap(s,e):
        for a,b in kg_spans:
            if not(e<a or s>b): return True
        return False
        
    for pat,kind in [(re.compile(r"(запуск\w*|запушили|зарыбление\w*)\s*[:\-–]?\s*(\d{2,4})\b",re.I),"stock"),
                      (re.compile(r"(вылов\w*|итог\w*)\s*[:\-–]?\s*(\d{1,4})\b",re.I),"catch")]:
        for m in pat.finditer(text):
            s,e=m.span()
            if overlap(s,e): continue
            try: kg=int(m.group(2))
            except: continue
            ctx60=text[max(0,s-60):min(len(text),e+60)]
            if NABECKA_RX.search(ctx60): continue
            if OTHER_FISH.search(text[max(0,s-50):min(len(text),e+50)]): continue
            if kind=="stock" and not(30<=kg<=20000): continue
            if kind=="catch" and not(5<=kg<=20000): continue
            if kind=="stock":
                if not FOREL_RX.search(text[max(0,s-250):min(len(text),e+250)]):
                    continue
                ev_date,is_dated=resolve_event_date(text,s,e,post_dt)
                before=text[max(0,s-60):s].lower()
                if not is_dated and FUTURE_RX.search(before): continue
            else:
                ev_date,is_dated=post_date,False
            results.append({"kind":kind,"kg":kg,"event_date":ev_date,"is_dated":is_dated,"quote":snippet(text,s),"pos":s})

    dated_stock=[r for r in results if r["kind"]=="stock" and r["is_dated"]]
    if dated_stock:
        results=[r for r in results if not(r["kind"]=="stock" and not r["is_dated"])]
    return results

def main():
    os.makedirs("pages", exist_ok=True)
    import sqlite3
    DB = sqlite3.connect("fishing.db")
    DB.execute("DROP TABLE IF EXISTS posts")
    DB.execute("CREATE TABLE posts (post_id TEXT PRIMARY KEY, page INT, author TEXT, post_dt TEXT, text TEXT)")
    state = load_state()
    print("Проверяю форум...")
    html1 = fetch(page_url(1))
    if not html1:
        raise SystemExit("Форум не ответил")
    last = total_pages(html1)
    print(f"Всего страниц: {last}")
    if not state.get("start_page"):
        print("Ищу 2024 год...")
        lo,hi=1,last
        while lo<hi:
            mid=(lo+hi)//2
            h=fetch(page_url(mid))
            d=first_date(h) if h else ""
            print(f" стр.{mid}: {d or '?'}")
            time.sleep(1.5)
            if not d or d>=START_DATE: hi=mid
            else: lo=mid+1
        state["start_page"]=max(1,lo-1)
        state["cursor"]=last
        state["newest"]=last
    start_page=state["start_page"]
    to_do=[]
    if last>state.get("newest",last):
        for p in range(state["newest"]+1,last+1): to_do.append(p)
        state["newest"]=last
    p=state.get("cursor",last)
    added=[]
    while len(added)<BATCH and p>=start_page:
        fn=f"pages/page_{p:06d}.json"
        if not os.path.exists(fn): added.append(p)
        p-=1
    state["cursor"]=p
    tail=list(range(max(start_page,last-REFRESH_TAIL+1),last+1))
    to_do=sorted(set(to_do+added+tail))
    print(f"Загружаю {len(to_do)} страниц...")
    for i,pg in enumerate(to_do):
        h=fetch(page_url(pg))
        if h:
            posts=parse_posts(h,pg)
            json.dump(posts,open(f"pages/page_{pg:06d}.json","w",encoding="utf-8"),ensure_ascii=False)
            print(f" {i+1}/{len(to_do)} стр.{pg}: {len(posts)} постов")
        time.sleep(random.uniform(1.5,2.5))
        if(i+1)%20==0: json.dump(state,open("state.json","w"),ensure_ascii=False)
    for fn in os.listdir("pages"):
        if not fn.endswith(".json"): continue
        try:
            posts=json.load(open(f"pages/{fn}",encoding="utf-8"))
            for post in posts:
                dtv=post.get("post_dt") or post.get("post_date") or ""
                DB.execute("INSERT OR IGNORE INTO VALUES (?,?,?,?,?)",
                    (post.get("post_id",""),post.get("page",0),post.get("author",""),dtv,post.get("text","")))
            DB.commit()
        except: continue
    json.dump(state,open("state.json","w"),ensure_ascii=False)
    build(DB,state,last)
    print("Готово!")

def build(DB,state,last):
    days=defaultdict(list)
    day_stock_cand=defaultdict(list)
    day_catch_cand=defaultdict(list)
    admin_names_lower=[a.lower() for a in ADMIN_AUTHORS]
    for pid,pg,author,pdt,text in DB.execute("SELECT post_id,page,author,post_dt,text FROM posts"):
        d=(pdt or "")[:10]
        url=f"{THREAD}/page-{pg}#post-{pid}" if pid else f"{THREAD}/page-{pg}"
        if d and FOREL_RX.search(text or "") and d>=START_DATE: days[d].append(url)
        if not pdt or not d: continue
        if d<BALANCE_START:
            try:
                if(date.fromisoformat(BALANCE_START)-date.fromisoformat(d)).days>10: continue
            except: continue
        if ADMIN_AUTHORS and (author or "").lower() not in admin_names_lower: continue
        try: evs=find_stock_catch(text or "",pdt)
        except Exception as ex: print(f"parse err: {ex}"); continue
        for ev in evs:
            ed=ev["event_date"]
            if not ed or ed<BALANCE_START: continue
            hh=pdt[11:16] if len(pdt)>=16 else ""
            pd_short=pdt[5:10] if len(pdt)>=10 else ""
            rec={"kg":ev["kg"],"url":url,"quote":f"пост {pd_short} {hh} {ev['quote']}"[:150],"dt":pdt,"is_fact":(pdt[:10]==ed)}
            if ev["kind"]=="stock": day_stock_cand[ed].append(rec)
            else: day_catch_cand[ed].append(rec)

    day_stock={}
    for dd,lst in day_stock_cand.items():
        facts=[r for r in lst if r["is_fact"]]
        pool=facts if facts else lst
        if facts: best=sorted(pool,key=lambda x:x["dt"])[0]
        else: best=sorted(pool,key=lambda x:x["dt"])[-1]
        day_stock[dd]=best
    day_catch={}
    for dd,lst in day_catch_cand.items():
        best=sorted(lst,key=lambda x:x["dt"])[-1]
        day_catch[dd]=best
    day_ev={}
    for dd,r in day_stock.items(): day_ev.setdefault(dd,{})["stock"]=r
    for dd,r in day_catch.items(): day_ev.setdefault(dd,{})["catch"]=r

    weather={}
    try:
        w=requests.get("https://archive-api.open-meteo.com/v1/archive",params={
            "latitude":55.82,"longitude":37.33,"start_date":START_DATE,
            "end_date":str(date.today()-timedelta(days=5)),
            "daily":"temperature_2m_mean,precipitation_sum,pressure_msl_mean",
            "timezone":"Europe/Moscow"},timeout=30).json()["daily"]
        for i,day in enumerate(w["time"]):
            pr=w["pressure_msl_mean"][i]
            weather[day]={"temp":w["temperature_2m_mean"][i],"precip":w["precipitation_sum"][i],
                "pressure":round(pr*0.75006,1) if pr else None}
    except Exception as e: print("Погода недоступна:",e)

    month_act=defaultdict(list)
    press={"<745":[],"745-760":[],">760":[]}
    for dd,urls in days.items():
        month_act[dd[:7]].append(len(urls))
        pw=(weather.get(dd) or {}).get("pressure")
        if pw:
            k="<745" if pw<745 else "745-760" if pw<=760 else ">760"
            press[k].append(len(urls))
    avg=lambda l:round(sum(l)/len(l),2) if l else 0
    import glob
    collected=len(glob.glob("pages/*.json"))
    need=state.get("newest",last)-state.get("start_page",last)+1
    stats={"monthly":{m:avg(v) for m,v in sorted(month_act.items())},
        "pressure":{k:avg(v) for k,v in press.items()},
        "total_posts":sum(len(v) for v in days.values()),
        "active_days":len(days),
        "collected":collected,"need":max(need,1),
        "pct":round(collected/max(need,1)*100,1),
        "updated":str(date.today())}
    table=[]
    for dd in sorted(days,reverse=True)[:60]:
        wv=weather.get(dd) or {}
        table.append({"day":dd,"posts":len(days[dd]),"temp":wv.get("temp"),
            "pressure":wv.get("pressure"),"precip":wv.get("precip"),"links":days[dd][:5]})

    bdates,bst,bct,brem=[],[],[],[]
    total_s,total_c=0,BAL,BAC=0,0
    last_stock_day=None
    
    # Начальная точка: 09.09.2026 = 580 кг
    start_dt=date.fromisoformat(BALANCE_START)
    cur=start_dt
    today=date.today()
    
    # Если до старта есть события — накопим их отдельно
    pre_stock,pre_catch={},{}
    for dd,r in day_ev.items():
        ed=date.fromisoformat(dd)
        if ed<start_dt:
            pre_stock[dd]=r.get("stock",{}).get("kg",0)
            pre_catch[dd]=r.get("catch",{}).get("kg",0)
    
    # Баланс от начала отсчёта
    rem=BALANCE_START_KG  # стартовый остаток
    bdates.append(str(start_dt)); bst.append(0); bct.append(0); brem.append(rem)
    
    cur+=timedelta(days=1)
    while cur<=today:
        ds=str(cur)
        ev=day_ev.get(ds,{})
        s=ev.get("stock",{}).get("kg",0)
        c=ev.get("catch",{}).get("kg",0)
        total_s+=s; total_c+=c; BAL+=s; BAC+=c
        rem=max(0,rem+s-c)
        if s: last_stock_day=ds
        bdates.append(ds); bst.append(s); bct.append(c); brem.append(rem)
        cur+=timedelta(days=1)
    
    remaining=brem[-1] if brem else 0
    days_since=(today-date.fromisoformat(last_stock_day)).days if last_stock_day else None
    events=[]
    for dd in sorted(day_ev,reverse=True)[:50]:
        for kind in ("stock","catch"):
            if kind in day_ev[dd]:
                e=day_ev[dd][kind]
                events.append({"day":dd,"type":"запуск" if kind=="stock" else "вылов",
                    "kg":e["kg"],"url":e["url"],"quote":e["quote"]})
    balance={"start":BALANCE_START,"start_kg":BALANCE_START_KG,
        "total_stocked":total_s,"total_caught":total_c,
        "remaining":remaining,"days_since_stock":days_since,
        "series":{"dates":bdates,"stocked":bst,"caught":bct,"remaining":brem},"events":events}

    payload=json.dumps({"stats":stats,"table":table,"balance":balance},ensure_ascii=False)
    payload=payload.replace("</","<\\/")
    open("index.html","w",encoding="utf-8").write(TEMPLATE.replace("__DATA__",payload))
    print(f"Сайт собран: остаток {remaining} кг (запущено {total_s}, выловлено {total_c})")

if __name__=="__main__":
    main()
