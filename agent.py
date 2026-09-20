import os
import re
import json
import time
import random
import glob
import sqlite3
from collections import defaultdict, Counter
from datetime import date, timedelta

from curl_cffi import requests
from bs4 import BeautifulSoup

THREAD_ID = "32280"
THREAD = f"https://www.rusfishing.ru/forum/threads/rybalka-v-krasnogorske.{THREAD_ID}"

PAGES_DIR = f"pages_{THREAD_ID}"
STATE_FILE = f"state_{THREAD_ID}.json"
DB_FILE = f"fishing_{THREAD_ID}.db"

START_DATE = "2024-01-01"
BALANCE_START = "2026-09-01"
ANALYTICS_START = "2026-09-01"

ADMIN_AUTHORS = [
    "Александр SALMO",
    "Митяй-Митинооо",
]

IGNORE_STOCK_DAYS = {
    "2026-09-04","2026-09-05","2026-09-06","2026-09-07","2026-09-08",
}

BATCH = 150
REFRESH_TAIL = 15

FOREL_RX = re.compile(r"форел", re.I)
OTHER_FISH = re.compile(r"осет|осётр|карп|сом\b|щук|белуг|стерляд|карас|окун|судак|сиг\b|налим|амур|толстолоб|линь", re.I)
DATE_RX = re.compile(r"(?<!\d)(\d{1,2})\.(\d{2})(?:\.(\d{2,4}))?(?!\d)")
KG_RX = re.compile(r"(\d+(?:[.,]\d+)?)(?:\s*[-–—]\s*(\d+(?:[.,]\d+)?))?\s*(кг|килограмм\w*|тонн\w*|т)\b", re.I)
STOCK_KW_RX = re.compile(r"запуск|запустили|зарыбление|зарыбили|завезли|завоз|выпустили", re.I)
CATCH_KW_RX = re.compile(r"вылов\w*|итог дня|итого", re.I)
FUTURE_RX = re.compile(r"сделаем|будет|будут|планиру|анонс|ожидается|собираемся|намечает", re.I)
STOCK_NOUNIT_RX = re.compile(r"(запуск\w*|запустили|зарыбление\w*)\s*[:\-–—]?\s*(\d{2,4})\b", re.I)
CATCH_NOUNIT_RX = re.compile(r"(вылов\w*|итог\w*)\s*[:\-–—]?\s*(\d{1,4})\b", re.I)
NABECKA_RX = re.compile(r"навеск", re.I)

LOCATION_RX = re.compile(r"основной водо[её]м|дальний угол|у плотин\w*|у коряг\w*|у входа|у выхода|центр\w*|мелководь\w*|глубок\w* участок|у берега|у причала|у мостка|у дамбы|у стены|у кустов|у травы|у тростника|у затопленн\w* дерев\w*|у ямы|у бровки|у сваи|у трубы|у слива|у аэратора|у кормушк\w*|у обрыва|у отмели|у переката|у залива|у бухты|понтон\w*|пантон\w*|старый понтон|новый понтон|переходной серый мост|бабий угол|женский угол|пляж|под дубами|под ивой|под администрацией|под стадионом|на запуске|на спорт зоне|старая спорт зона", re.I)
LURE_RX = re.compile(r"вертушк\w*|воблер\w*|резин\w*|мушк\w*|блесна|черв\w*|опарыш\w*|мотыл\w*|пенопласт|тесто|сыр|бойл\w*|поппер\w*|цикад\w*|колебалк\w*|вращалк\w*|силикон\w*|твистер\w*|виброхвост\w*|рапал\w*|минноу|кренк\w*|джерк\w*|спининг\w*|донк\w*|фидер\w*|поплавочн\w*|мормышк\w*|балда|стример\w*|нимф\w*|сухая мушка|мокрая мушка|личинк\w*|мотылёк|ручейник|магот\w*|светонакоп\w*|светонакопительный|стрейч|бобриный хвост|пламп\w*|Биг Джуниор", re.I)
TIME_RX = re.compile(r"утро|вечер|ночь|рассвет|закат|день|с (\d{1,2}) до (\d{1,2})|после (\d{1,2})|до (\d{1,2})", re.I)
DEPTH_RX = re.compile(r"дно|полвод\w*|поверхност\w*|у дна|в полвод\w*|верхний слой|средний слой|придонный слой|у поверхност\w*|под берегом|на глубин[еу] (\d+)\s*м|на (\d+)\s*м", re.I)
SENTENCE_RX = re.compile(r"[.!?…]")
BAD_BETWEEN_RX = re.compile(r"корм|прикорм|пеллет|смес", re.I)

PRICE_LINE_RX = re.compile(r"(06:00\s*[–—-]\s*19:00|12:00\s*[–—-]\s*19:00|18:00\s*[–—-]\s*06:00|Сутки|Приоритетный час|Дополнительная снасть)[^\d\n]{0,30}(\d{3,4})\s*₽", re.I)

DEFAULT_CONDITIONS = [
    {"label": "06:00–19:00", "price": "4000"},
    {"label": "12:00–19:00", "price": "2200"},
    {"label": "18:00–06:00", "price": "4000"},
    {"label": "Сутки", "price": "5000"},
    {"label": "Приоритетный час", "price": "300"},
    {"label": "Дополнительная снасть", "price": "500"},
]

TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Форель Красногорск</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
body{font-family:system-ui,-apple-system,sans-serif;margin:0 auto;padding:12px;background:#0f172a;color:#e2e8f0;max-width:900px}
h1{font-size:1.4rem;background:linear-gradient(90deg,#38bdf8,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:#1e293b;border-radius:14px;padding:14px;margin:10px 0}
.big{font-size:1.8rem;font-weight:800;color:#fbbf24}
table{width:100%;border-collapse:collapse;font-size:.8rem}
td,th{padding:6px 4px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}
a{color:#7dd3fc;text-decoration:none}
a:hover{text-decoration:underline}
.note{font-size:.8rem;color:#94a3b8}
.q{color:#94a3b8;font-size:.75rem}
details{margin:10px 0;border-radius:14px;border:1px solid #334155;overflow:hidden;background:#1e293b}
summary{cursor:pointer;padding:10px 14px;font-weight:800;color:#38bdf8;background:linear-gradient(90deg,#0f172a,#1e293b);list-style:none;user-select:none}
summary:hover{background:#334155}
summary::marker{display:none}
details>.card{margin:0;border-radius:0;border:none;padding:14px}
#topbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;font-size:.95rem}
#topbar b{color:#fbbf24}
</style>
</head>
<body>
<h1>🎣 Форель в Красногорске</h1>

<div class="card" id="topbar">
  <span><b>📅 Сегодня:</b> <span id="curDate">—</span></span>
  <span><b>⏰ Время:</b> <span id="curTime">—</span></span>
  <span><b>🌤 Погода:</b> <span id="curTemp">—</span>°C • <span id="curPress">—</span> мм • осадки <span id="curPrecip">—</span> мм</span>
  <span><b>💨 Ветер:</b> <span id="curWind">—</span></span>
</div>

<details open>
<summary>🎟 Условия рыбалки</summary>
<div class="card">
  <table id="cond_table"></table>
  <p>🎣 Разрешено ловить на две снасти, не более двух крючков на каждой.<br>👩 Женщина и ребёнок до 13 лет ловят бесплатно на снасти рыбака.<br>🐟 Нормы вылова нет.<br>✅ Спиннинг разрешён.<br>⛔ Пеллетс и блёсны с тройниками запрещены.</p>
  <p><b>Координаты:</b> <a href="https://yandex.ru/maps/?pt=37.322979,55.840619&z=15&l=map" target="_blank">55.840619, 37.322979</a><br><b>Телефон:</b> <a href="tel:+79852620637">+7 985 262-06-37</a></p>
  <div class="note">Источник: <a id="cond_link" href="#" target="_blank">администрация</a> от <span id="cond_date">—</span>. Авто-парсинг последнего поста с ценами. Проверяйте перед поездкой.</div>
</div>
</details>

<details open>
<summary>🐟 Остаток форели в водоёме</summary>
<div class="card">
  <div class="big" id="rem">—</div>
  <div class="note">запущено <b id="st">0</b> кг − выловлено <b id="ct">0</b> кг • отсчёт с <span id="bs"></span><br>последний запуск: <span id="dsl">—</span> • обновлено <span id="upd2"></span></div>
</div>
</details>

<details open><summary>📈 Баланс</summary><div class="card" id="balbox"><canvas id="bal"></canvas></div></details>
<details open><summary>📓 Журнал запусков и выловов</summary><div class="card"><table id="ev"></table></div></details>
<div class="note">Дата в таблице = дата события из текста, а не дата поста.</div>

<details open>
<summary>📊 Активность обсуждений с 2024</summary>
<div class="card"><div class="note" id="prog"></div><div class="big" style="color:#38bdf8" id="total">0</div><div class="note">постов про форель за <span id="days">0</span> активных дней</div></div>
<h3>Активность по месяцам (постов/день)</h3><div class="card"><canvas id="m"></canvas></div>
<h3>Клёв vs Давление</h3><div class="card"><canvas id="p"></canvas></div>
<h3>Последние активные дни (день/ночь + ветер + луна)</h3><div class="card" style="overflow:auto"><table id="t"></table></div>
</details>

<details open>
<summary>🎣 Разбор отчётов с сентября 2026 — где и на что ловят</summary>
<div class="card">
  <h3>Топ точек</h3><table id="top_locs"></table>
  <h3>Топ приманок</h3><table id="top_lures"></table>
  <div class="note">Считается только с 01.09.2026, только посты рыбаков (не админы), где упоминается форель и есть хотя бы точка/приманка/улов. Парсится регулярками LOCATION_RX / LURE_RX / TIME_RX.</div>
</div>
<div class="card" style="overflow:auto"><table id="reports"></table></div>
</details>

<script>
try{
const D=__DATA__;
function renderTop(){
  const now=new Date();
  document.getElementById('curDate').textContent=now.toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'});
  document.getElementById('curTime').textContent=now.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
  const cw=D.current_weather||{};
  document.getElementById('curTemp').textContent=cw.temp??cw.temp_max??'—';
  document.getElementById('curPress').textContent=cw.pressure??'—';
  document.getElementById('curPrecip').textContent=cw.precip??'—';
  const wind=cw.wind_speed!=null?`${cw.wind_speed} м/с ${cw.wind_dir_str||''} ${cw.wind_dir!=null?'('+cw.wind_dir+'°)':''}`:'—';
  document.getElementById('curWind').textContent=wind;
}
renderTop(); setInterval(renderTop,30000);

// Условия
const cond=D.conditions;
if(cond && cond.items){
  document.getElementById('cond_table').innerHTML=cond.items.map(i=>`<tr><td>${i.label}</td><td><b>${i.price} ₽</b></td></tr>`).join('');
  document.getElementById('cond_date').textContent=cond.date||'—';
  document.getElementById('cond_link').href=cond.url||'#';
}

const B=D.balance||{};
document.getElementById('bs').textContent=B.start||'2026-09-01';
document.getElementById('st').textContent=B.total_stocked||0;
document.getElementById('ct').textContent=B.total_caught||0;
document.getElementById('rem').textContent=(B.events&&B.events.length)?('≈ '+(B.remaining||0)+' кг'):'Ожидание 01.09.2026';
document.getElementById('dsl').textContent=(B.days_since_stock!=null)?(B.days_since_stock+' дн. назад'):'нет данных';
document.getElementById('upd2').textContent=(D.stats&&D.stats.updated)||'';
if(B.series&&B.series.dates&&B.series.dates.length>0){
  new Chart(document.getElementById('bal'),{data:{labels:B.series.dates,datasets:[{type:'line',label:'Остаток кг',data:B.series.remaining,borderColor:'#fbbf24',tension:0.3,pointRadius:0,borderWidth:2},{type:'bar',label:'Запуск',data:B.series.stocked,backgroundColor:'#4ade80'},{type:'bar',label:'Вылов',data:B.series.caught,backgroundColor:'#f87171'}]},options:{plugins:{legend:{labels:{color:'#e2e8f0',boxWidth:12}}},scales:{x:{ticks:{maxTicksLimit:8,color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'}}}}});
}else{document.getElementById('balbox').innerHTML='<div class="note">Отчёты появятся начиная с '+(B.start||'2026-09-01')+'.</div>';}
if(B.events&&B.events.length>0){document.getElementById('ev').innerHTML='<tr><th>Дата</th><th></th><th>кг</th><th>Цитата</th></tr>'+B.events.map(e=>`<tr><td>${e.day}</td><td>${e.type==='запуск'?'🟢':'🔴'}</td><td><b>${e.kg}</b></td><td class="q"><a href="${e.url}" target="_blank">${e.quote}</a></td></tr>`).join('');}

if(D.stats){
  document.getElementById('prog').textContent='Собрано страниц: '+(D.stats.collected||0)+' из ~'+(D.stats.need||0)+' ('+(D.stats.pct||0)+'%)';
  document.getElementById('total').textContent=D.stats.total_posts||0;
  document.getElementById('days').textContent=D.stats.active_days||0;
  if(D.stats.monthly&&Object.keys(D.stats.monthly).length>0){new Chart(document.getElementById('m'),{type:'bar',data:{labels:Object.keys(D.stats.monthly),datasets:[{data:Object.values(D.stats.monthly),backgroundColor:'#38bdf8'}]},options:{plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'}}}}});}
  if(D.stats.pressure&&Object.keys(D.stats.pressure).length>0){new Chart(document.getElementById('p'),{type:'bar',data:{labels:Object.keys(D.stats.pressure),datasets:[{label:'Среднее кол-во отчетов/день',data:Object.values(D.stats.pressure),backgroundColor:['#ef4444','#eab308','#22c55e']}]},options:{plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#94a3b8'},title:{display:true,text:'Давление (мм рт.ст.)',color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'},beginAtZero:true}}}});}
}

if(D.table&&D.table.length>0){
  document.getElementById('t').innerHTML='<tr><th>Дата</th><th>П</th><th>День</th><th>Ночь</th><th>Давл</th><th>Осадки</th><th>Ветер</th><th>Луна</th><th></th></tr>'+D.table.map(r=>{
    const wind=r.wind_speed!=null?`${r.wind_speed} м/с ${r.wind_gust!=null?'/ порыв '+r.wind_gust:''} ${r.wind_dir_str||''} ${r.wind_dir!=null?'('+r.wind_dir+'°)':''}`:'—';
    const moon=r.moon?`${r.moon.icon} ${r.moon.name}`:'—';
    return `<tr><td>${r.day}</td><td>${r.posts}</td><td>${r.temp_max??'—'}°</td><td>${r.temp_min??'—'}°</td><td>${r.pressure??'—'}</td><td>${r.precip??'—'}</td><td>${wind}</td><td>${moon}</td><td>${(r.links||[]).map((u,i)=>`<a href="${u}" target="_blank">#${i+1}</a>`).join(' ')}</td></tr>`;
  }).join('');
}

if(D.reports){
  if(D.report_stats){
    const tl=D.report_stats.top_locations||{};
    document.getElementById('top_locs').innerHTML='<tr><th>Точка</th><th>упом.</th></tr>'+Object.entries(tl).map(([k,v])=>`<tr><td>${k}</td><td>${v}</td></tr>`).join('')||'<tr><td>нет данных</td></tr>';
    const tu=D.report_stats.top_lures||{};
    document.getElementById('top_lures').innerHTML='<tr><th>Приманка</th><th>упом.</th></tr>'+Object.entries(tu).map(([k,v])=>`<tr><td>${k}</td><td>${v}</td></tr>`).join('')||'<tr><td>нет данных</td></tr>';
  }
  document.getElementById('reports').innerHTML='<tr><th>Дата</th><th>Автор</th><th>Точка</th><th>Приманка</th><th>Время</th><th>Горизонт</th><th>Улов</th><th>Цитата</th></tr>'+D.reports.map(r=>`<tr><td>${r.day}</td><td>${r.author||'—'}</td><td>${r.location||'—'}</td><td>${r.lure||'—'}</td><td>${r.time||'—'}</td><td>${r.depth||'—'}</td><td>${r.catch||'—'}</td><td class="q"><a href="${r.url}" target="_blank">${r.quote}</a></td></tr>`).join('');
}
}catch(err){console.error(err);}
</script>
</body>
</html>"""

def page_url(n): return THREAD if n==1 else f"{THREAD}/page-{n}"

def fetch(url,tries=3):
    for attempt in range(tries):
        try:
            r=requests.get(url,impersonate="chrome120",timeout=25,headers={"Accept-Language":"ru-RU,ru;q=0.9,en;q=0.8"})
            if r.status_code==200:
                html=r.text
                if "article class=" not in html and "article.message" not in html:
                    print(f"Антибот? {url}"); time.sleep(3*(attempt+1)); continue
                return html
            print(f"Status {r.status_code} on {url}")
        except Exception as e: print(f"Retry {attempt+1}: {e}")
        time.sleep(3*(attempt+1))
    return None

def parse_posts(html,page):
    soup=BeautifulSoup(html,"lxml"); posts=[]
    for msg in soup.select("article.message"):
        raw=msg.get("id",""); m=re.search(r"(\d+)",raw); pid=m.group(1) if m else f"p{page}_{len(posts)}"
        te=msg.select_one("time"); body=msg.select_one(".bbWrapper")
        if not body: continue
        for q in body.select("blockquote"): q.decompose()
        posts.append({"post_id":pid,"page":page,"author":msg.get("data-author",""),"post_dt":te.get("datetime") or "" if te else "","text":body.get_text("\n",strip=True)})
    return posts

def total_pages(html):
    soup=BeautifulSoup(html,"lxml"); nav=soup.select_one(".pageNav")
    if nav and nav.get("data-last"):
        try: return int(nav["data-last"])
        except: pass
    nums=[]
    for a in soup.select(".pageNav a"):
        t=a.get_text(strip=True).replace(" ","")
        if t.isdigit(): nums.append(int(t))
    return max(nums) if nums else 10451

def first_date(html):
    if not html: return ""
    soup=BeautifulSoup(html,"lxml"); te=soup.select_one("article.message time")
    return (te.get("datetime") or "")[:10] if te else ""

def load_state():
    if not os.path.exists(STATE_FILE): return {}
    try:
        with open(STATE_FILE,encoding="utf-8") as f: return json.load(f)
    except: return {}

def snippet(text,pos,width=80):
    s=max(0,pos-15); e=min(len(text),pos+width)
    clean=re.sub(r"\s+"," ",text[s:e]).strip()
    return "…"+clean+"…"

def resolve_event_date(text,start,end,post_dt):
    post_date=(post_dt or "")[:10]
    try: post_year=int(post_date[:4])
    except: post_year=date.today().year
    ls=text.rfind("\n",0,start); ls=0 if ls==-1 else ls+1
    le=text.find("\n",end); le=len(text) if le==-1 else le
    line=text[ls:le]
    for scope in (line,text[max(0,start-40):min(len(text),end+40)]):
        m=DATE_RX.search(scope)
        if not m: continue
        try:
            d=int(m.group(1)); mo=int(m.group(2)); ry=m.group(3)
            if ry:
                if len(ry)==2: sy=int(ry); y=2000+sy if sy<50 else 1900+sy
                else: y=int(ry)
            else: y=post_year
            if 1<=d<=31 and 1<=mo<=12: return (f"{y:04d}-{mo:02d}-{d:02d}",True)
        except: pass
    if "завтра" in line.lower():
        try: return (str(date.fromisoformat(post_date)+timedelta(days=1)),True)
        except: pass
    return post_date,False

def is_weight_of_size(text,start):
    before=text[max(0,start-45):start].lower()
    return bool(re.search(r"навеск\w*[^0-9]{0,25}$",before,re.I))

def build_keyword_index(text):
    kws=[]
    for m in STOCK_KW_RX.finditer(text): kws.append((m.start(),m.end(),"stock"))
    for m in CATCH_KW_RX.finditer(text): kws.append((m.start(),m.end(),"catch"))
    kws.sort(key=lambda x:x[0]); return kws

def keyword_kind_for(text,kws,start,end):
    lefts=[k for k in kws if k[1]<=start]
    if lefts:
        ks,ke,kind=lefts[-1]; bet=text[ke:start]
        if start-ke<=200 and not BAD_BETWEEN_RX.search(bet): return kind
    rights=[k for k in kws if k[0]>=end]
    if rights:
        ks,ke,kind=rights[0]; bet=text[end:ks]
        if ks-end<=200 and not SENTENCE_RX.search(bet) and not BAD_BETWEEN_RX.search(bet): return kind
    return None

def find_stock_catch(text,post_dt):
    post_date=(post_dt or "")[:10]
    if not text: return []
    results=[]; kg_spans=[]; kws=build_keyword_index(text)
    for m in KG_RX.finditer(text):
        s,e=m.span(); kg_spans.append((s,e))
        if is_weight_of_size(text,s): continue
        ctx=text[max(0,s-25):min(len(text),e+25)]
        if OTHER_FISH.search(ctx): continue
        kind=keyword_kind_for(text,kws,s,e)
        if kind is None: continue
        try:
            v1=float(m.group(1).replace(",",".")); sr=m.group(2)
            v=float(m.group(2).replace(",",".")) if sr else v1
            if sr: v=(v1+v)/2
            unit=(m.group(3) or "").lower()
            if unit.startswith("тон") or unit=="т": v*=1000
            kg=int(round(v))
        except: continue
        if kind=="stock" and not (30<=kg<=20000): continue
        if kind=="catch" and not (5<=kg<=20000): continue
        if kind=="stock":
            fctx=text[max(0,s-250):min(len(text),e+250)]
            if not FOREL_RX.search(fctx) and OTHER_FISH.search(fctx): continue
            ed,dated=resolve_event_date(text,s,e,post_dt)
            before=text[max(0,s-60):s].lower()
            if not dated and FUTURE_RX.search(before): continue
        else: ed=post_date; dated=False
        results.append({"kind":kind,"kg":kg,"event_date":ed,"is_dated":dated,"quote":snippet(text,s),"pos":s})
    def overlaps(s,e):
        for a,b in kg_spans:
            if not (e<a or s>b): return True
        return False
    for pat,kind in [(STOCK_NOUNIT_RX,"stock"),(CATCH_NOUNIT_RX,"catch")]:
        for m in pat.finditer(text):
            s,e=m.span()
            if overlaps(s,e): continue
            try: kg=int(m.group(2))
            except: continue
            if is_weight_of_size(text,s): continue
            ctx=text[max(0,s-25):min(len(text),e+25)]
            if OTHER_FISH.search(ctx): continue
            if kind=="stock" and not (30<=kg<=20000): continue
            if kind=="catch" and not (5<=kg<=20000): continue
            if kind=="stock":
                fctx=text[max(0,s-250):min(len(text),e+250)]
                if not FOREL_RX.search(fctx) and OTHER_FISH.search(fctx): continue
                ed,dated=resolve_event_date(text,s,e,post_dt)
                before=text[max(0,s-60):s].lower()
                if not dated and FUTURE_RX.search(before): continue
            else: ed=post_date; dated=False
            results.append({"kind":kind,"kg":kg,"event_date":ed,"is_dated":dated,"quote":snippet(text,s),"pos":s})
    dated_stock=[r for r in results if r["kind"]=="stock" and r["is_dated"]]
    if dated_stock: results=[r for r in results if not (r["kind"]=="stock" and not r["is_dated"])]
    return results

def extract_location(t): m=LOCATION_RX.search(t); return m.group(0) if m else None
def extract_lure(t): m=LURE_RX.search(t); return m.group(0) if m else None
def extract_time(t):
    m=TIME_RX.search(t)
    if not m: return None
    if m.group(1): return f"{m.group(1)}–{m.group(2)}"
    if m.group(3): return f"после {m.group(3)}"
    if m.group(4): return f"до {m.group(4)}"
    return m.group(0)
def extract_depth(t):
    m=DEPTH_RX.search(t)
    if not m: return None
    if m.group(1): return f"{m.group(1)} м"
    if m.group(2): return f"{m.group(2)} м"
    return m.group(0)
def extract_catch(t):
    rx=re.compile(r"(?:поймал[аи]?|выловил[аи]?|в улове|уловил[аи]?|взял[аи]?|на улов|в сумме|итого)\s*(?:(\d+)\s*(?:штук|экземпляр|рыб|форел|кг|килограмм))|(?:(\d+)\s*форел)|(?:форел[ьи]\s*(\d+))",re.I)
    m=rx.search(t)
    if m:
        for g in m.groups():
            if g: return g+" шт."
    return None
def extract_conditions_table(text):
    items=[]
    for m in PRICE_LINE_RX.finditer(text):
        items.append({"label":m.group(1).strip(),"price":m.group(2).strip()})
    return items if items else None

def get_moon_phase(d: date):
    known=date(2000,1,6); diff=(d-known).days; L=29.53058867; phase=(diff % L)/L
    if phase<0.03 or phase>0.97: name,icon="Новолуние","🌑"
    elif phase<0.22: name,icon="Растущий серп","🌒"
    elif phase<0.28: name,icon="Первая четверть","🌓"
    elif phase<0.47: name,icon="Растущая луна","🌔"
    elif phase<0.53: name,icon="Полнолуние","🌕"
    elif phase<0.72: name,icon="Убывающая луна","🌖"
    elif phase<0.78: name,icon="Последняя четверть","🌗"
    else: name,icon="Убывающий серп","🌘"
    return {"name":name,"icon":icon,"phase":round(phase,2)}

def deg_to_compass(deg):
    if deg is None: return ""
    dirs=["С","СВ","В","ЮВ","Ю","ЮЗ","З","СЗ"]; return dirs[int((deg+22.5)//45)%8]

def load_weather():
    weather={}; today=date.today()
    try:
        r=requests.get("https://archive-api.open-meteo.com/v1/archive",params={"latitude":55.82,"longitude":37.33,"start_date":START_DATE,"end_date":str(today-timedelta(days=1)),"daily":"temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum,pressure_msl_mean,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant","timezone":"Europe/Moscow"},timeout=60)
        daily=r.json().get("daily") or {}; times=daily.get("time") or []
        tmax=daily.get("temperature_2m_max") or []; tmin=daily.get("temperature_2m_min") or []; tmean=daily.get("temperature_2m_mean") or []
        prec=daily.get("precipitation_sum") or []; press=daily.get("pressure_msl_mean") or []
        ws=daily.get("wind_speed_10m_max") or []; wg=daily.get("wind_gusts_10m_max") or []; wd=daily.get("wind_direction_10m_dominant") or []
        for i,day in enumerate(times):
            try: moon=get_moon_phase(date.fromisoformat(day))
            except: moon=None
            pm=round(press[i]*0.75006,1) if i<len(press) and press[i] is not None else None
            weather[day]={"temp_max":tmax[i] if i<len(tmax) else None,"temp_min":tmin[i] if i<len(tmin) else None,"temp":tmean[i] if i<len(tmean) else None,"precip":prec[i] if i<len(prec) else None,"pressure":pm,"wind_speed":ws[i] if i<len(ws) else None,"wind_gust":wg[i] if i<len(wg) else None,"wind_dir":wd[i] if i<len(wd) else None,"wind_dir_str":deg_to_compass(wd[i]) if i<len(wd) and wd[i] is not None else "","moon":moon}
    except Exception as e: print("Архив погоды недоступен:",e)
    try:
        r=requests.get("https://api.open-meteo.com/v1/forecast",params={"latitude":55.82,"longitude":37.33,"start_date":str(today-timedelta(days=2)),"end_date":str(today+timedelta(days=2)),"daily":"temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum,pressure_msl_mean,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant","timezone":"Europe/Moscow"},timeout=60)
        daily=r.json().get("daily") or {}; times=daily.get("time") or []
        tmax=daily.get("temperature_2m_max") or []; tmin=daily.get("temperature_2m_min") or []; tmean=daily.get("temperature_2m_mean") or []
        prec=daily.get("precipitation_sum") or []; press=daily.get("pressure_msl_mean") or []
        ws=daily.get("wind_speed_10m_max") or []; wg=daily.get("wind_gusts_10m_max") or []; wd=daily.get("wind_direction_10m_dominant") or []
        for i,day in enumerate(times):
            rec=weather.get(day) or {}
            if rec.get("temp_max") is None and i<len(tmax): rec["temp_max"]=tmax[i]
            if rec.get("temp_min") is None and i<len(tmin): rec["temp_min"]=tmin[i]
            if rec.get("temp") is None and i<len(tmean): rec["temp"]=tmean[i]
            if rec.get("precip") is None and i<len(prec): rec["precip"]=prec[i]
            if rec.get("pressure") is None and i<len(press) and press[i] is not None: rec["pressure"]=round(press[i]*0.75006,1)
            if rec.get("wind_speed") is None and i<len(ws): rec["wind_speed"]=ws[i]
            if rec.get("wind_gust") is None and i<len(wg): rec["wind_gust"]=wg[i]
            if rec.get("wind_dir") is None and i<len(wd): rec["wind_dir"]=wd[i]; rec["wind_dir_str"]=deg_to_compass(wd[i]) if wd[i] is not None else ""
            if rec.get("moon") is None:
                try: rec["moon"]=get_moon_phase(date.fromisoformat(day))
                except: pass
            weather[day]=rec
    except Exception as e: print("Свежая погода недоступна:",e)
    return weather

def main():
    os.makedirs(PAGES_DIR,exist_ok=True); db=sqlite3.connect(DB_FILE)
    db.execute("CREATE TABLE IF NOT EXISTS posts (post_id TEXT PRIMARY KEY, page INT, author TEXT, post_dt TEXT, text TEXT)")
    state=load_state(); print("Проверяю форум...")
    first_html=fetch(page_url(1))
    if not first_html: raise SystemExit("Форум не ответил")
    last_page=total_pages(first_html); print(f"Всего страниц: {last_page}")
    if not state.get("start_page"):
        print("Ищу 2024 год..."); low=1; high=last_page
        while low<high:
            mid=(low+high)//2; html=fetch(page_url(mid)); fd=first_date(html) if html else ""; print(f" стр.{mid}: {fd or '?'}"); time.sleep(1.5)
            if not fd or fd>=START_DATE: high=mid
            else: low=mid+1
        state["start_page"]=max(1,low-1); state["cursor"]=last_page; state["newest"]=last_page
    start_page=state["start_page"]; pages_to_download=[]
    if last_page>state.get("newest",last_page):
        for p in range(state["newest"]+1,last_page+1): pages_to_download.append(p)
        state["newest"]=last_page
    cursor=state.get("cursor",last_page); added=[]
    while len(added)<BATCH and cursor>=start_page:
        fn=f"{PAGES_DIR}/page_{cursor:06d}.json"
        if not os.path.exists(fn): added.append(cursor)
        cursor-=1
    state["cursor"]=cursor
    tail=list(range(max(start_page,last_page-REFRESH_TAIL+1),last_page+1))
    pages_to_download=sorted(set(pages_to_download+added+tail))
    print(f"Загружаю {len(pages_to_download)} страниц...")
    for idx,p in enumerate(pages_to_download):
        html=fetch(page_url(p))
        if html:
            posts=parse_posts(html,p)
            if not posts: print(f" стр.{p}: 0 постов — пропуск"); continue
            fn=f"{PAGES_DIR}/page_{p:06d}.json"
            with open(fn,"w",encoding="utf-8") as f: json.dump(posts,f,ensure_ascii=False)
            print(f" {idx+1}/{len(pages_to_download)} стр.{p}: {len(posts)} постов")
        time.sleep(random.uniform(1.5,2.5))
        if (idx+1)%20==0:
            with open(STATE_FILE,"w",encoding="utf-8") as f: json.dump(state,f,ensure_ascii=False)
    for fn in os.listdir(PAGES_DIR):
        if not fn.endswith(".json"): continue
        try:
            with open(f"{PAGES_DIR}/{fn}",encoding="utf-8") as f: posts=json.load(f)
            for po in posts:
                pdt=po.get("post_dt") or po.get("post_date") or ""
                db.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?)",(po.get("post_id",""),po.get("page",0),po.get("author",""),pdt,po.get("text","")))
            db.commit()
        except Exception as e: print(f"Не удалось прочитать {fn}: {e}")
    with open(STATE_FILE,"w",encoding="utf-8") as f: json.dump(state,f,ensure_ascii=False)
    build(db,state,last_page); db.close(); print("Готово!")

def build(database,state,last_page):
    days=defaultdict(list); day_stock_candidates=defaultdict(list); day_catch_candidates=defaultdict(list)
    detailed_reports=[]; cond_candidates=[]
    for post_id,page_number,author,post_datetime,text in database.execute("SELECT post_id, page, author, post_dt, text FROM posts"):
        post_day=(post_datetime or "")[:10]; post_url=f"{THREAD}/page-{page_number}#post-{post_id}" if post_id else f"{THREAD}/page-{page_number}"
        if post_day and FOREL_RX.search(text or "") and post_day>=START_DATE: days[post_day].append(post_url)
        if not post_datetime or not post_day: continue
        if post_day>=BALANCE_START and author in ADMIN_AUTHORS:
            items=extract_conditions_table(text or "")
            if items: cond_candidates.append({"date":post_day,"dt":post_datetime,"url":post_url,"items":items})
        if post_day<BALANCE_START:
            try:
                if (date.fromisoformat(BALANCE_START)-date.fromisoformat(post_day)).days>10: 
                    # все равно собираем аналитику с сентября ниже
                    pass
            except: pass
        # аналитика отчетов с сентября
        if post_day>=ANALYTICS_START and FOREL_RX.search(text or "") and author not in ADMIN_AUTHORS:
            loc=extract_location(text or ""); lure=extract_lure(text or ""); t=extract_time(text or ""); dpth=extract_depth(text or ""); cat=extract_catch(text or "")
            if loc or lure or cat or dpth:
                detailed_reports.append({"day":post_day,"author":author,"location":loc,"lure":lure,"time":t,"depth":dpth,"catch":cat,"url":post_url,"quote":snippet(text or "",0,120)})
        if post_day<BALANCE_START: 
            try:
                if (date.fromisoformat(BALANCE_START)-date.fromisoformat(post_day)).days>10: continue
            except: continue
        if ADMIN_AUTHORS and (author or "") not in ADMIN_AUTHORS: continue
        try: events=find_stock_catch(text or "",post_datetime)
        except Exception as e: print(f"parse err: {e}"); continue
        for ev in events:
            ed=ev["event_date"]
            if not ed or ed<BALANCE_START: continue
            if ed in IGNORE_STOCK_DAYS and ev["kind"]=="stock": continue
            pt=post_datetime[11:16] if len(post_datetime)>=16 else ""; spd=post_datetime[5:10] if len(post_datetime)>=10 else ""
            rec={"kg":ev["kg"],"url":post_url,"quote":(f"пост {spd} {pt} {ev['quote']}")[:150],"dt":post_datetime,"is_fact":(post_datetime[:10]==ed),"pos":ev.get("pos",0)}
            if ev["kind"]=="stock": day_stock_candidates[ed].append(rec)
            else: day_catch_candidates[ed].append(rec)
    day_stock={}
    for d,recs in day_stock_candidates.items():
        factual=[r for r in recs if r["is_fact"]]; pool=factual or recs; day_stock[d]=max(pool,key=lambda r:(r["dt"],r.get("pos",0)))
    day_catch={}
    for d,recs in day_catch_candidates.items(): day_catch[d]=max(recs,key=lambda r:(r["dt"],r.get("pos",0)))
    day_events={}
    for d,r in day_stock.items(): day_events.setdefault(d,{})["stock"]=r
    for d,r in day_catch.items(): day_events.setdefault(d,{})["catch"]=r
    weather=load_weather()
    monthly=defaultdict(list); pressure_groups={"<745":[],"745-760":[],">760":[]}
    for dv,urls in days.items():
        monthly[dv[:7]].append(len(urls))
        pr=(weather.get(dv) or {}).get("pressure")
        if pr is not None:
            if pr<745: g="<745"
            elif pr<=760: g="745-760"
            else: g=">760"
            pressure_groups[g].append(len(urls))
    def avg(v): return round(sum(v)/len(v),2) if v else 0
    collected=len(glob.glob(f"{PAGES_DIR}/*.json")); need=state.get("newest",last_page)-state.get("start_page",last_page)+1
    stats={"monthly":{m:avg(vals) for m,vals in sorted(monthly.items())},"pressure":{g:avg(vals) for g,vals in pressure_groups.items()},"total_posts":sum(len(vals) for vals in days.values()),"active_days":len(days),"collected":collected,"need":max(need,1),"pct":round(collected/max(need,1)*100,1),"updated":str(date.today())}
    table=[]
    for dv in sorted(days,reverse=True)[:60]:
        w=weather.get(dv) or {}
        table.append({"day":dv,"posts":len(days[dv]),"temp_max":w.get("temp_max"),"temp_min":w.get("temp_min"),"temp":w.get("temp"),"pressure":w.get("pressure"),"precip":w.get("precip"),"wind_speed":w.get("wind_speed"),"wind_gust":w.get("wind_gust"),"wind_dir":w.get("wind_dir"),"wind_dir_str":w.get("wind_dir_str"),"moon":w.get("moon"),"links":days[dv][:5]})
    balance_dates=[]; balance_stocked=[]; balance_caught=[]; balance_remaining=[]; total_stocked=total_caught=0; last_stock=None
    if day_events:
        first_day=min(day_events); last_day=max(max(day_events),str(date.today())); cur=date.fromisoformat(first_day); end=date.fromisoformat(last_day); rem=0
        while cur<=end:
            ds=str(cur); ev=day_events.get(ds,{}); st=ev.get("stock",{}).get("kg",0); ca=ev.get("catch",{}).get("kg",0)
            total_stocked+=st; total_caught+=ca; rem=max(0,rem+st-ca)
            if st: last_stock=ds
            balance_dates.append(ds); balance_stocked.append(st); balance_caught.append(ca); balance_remaining.append(rem); cur+=timedelta(days=1)
    remaining=balance_remaining[-1] if balance_remaining else 0; days_since=(date.today()-date.fromisoformat(last_stock)).days if last_stock else None
    events=[]
    for ed in sorted(day_events,reverse=True)[:40]:
        for kind in ("stock","catch"):
            if kind in day_events[ed]:
                e=day_events[ed][kind]; events.append({"day":ed,"type":"запуск" if kind=="stock" else "вылов","kg":e["kg"],"url":e["url"],"quote":e["quote"]})
    detailed_reports_sorted=sorted(detailed_reports,key=lambda x:x["day"],reverse=True)[:80]
    top_locs=dict(Counter([r["location"] for r in detailed_reports if r["location"]]).most_common(10))
    top_lures=dict(Counter([r["lure"] for r in detailed_reports if r["lure"]]).most_common(10))
    top_times=dict(Counter([r["time"] for r in detailed_reports if r["time"]]).most_common(10))
    # условия
    if cond_candidates:
        latest=max(cond_candidates,key=lambda x:x["dt"])
        conditions=latest
    else:
        conditions={"date":"13.09.2026 (дефолт)","url":THREAD,"items":DEFAULT_CONDITIONS}
    today_str=str(date.today()); cw=weather.get(today_str) or {}
    balance={"start":BALANCE_START,"total_stocked":total_stocked,"total_caught":total_caught,"remaining":remaining,"days_since_stock":days_since,"series":{"dates":balance_dates,"stocked":balance_stocked,"caught":balance_caught,"remaining":balance_remaining},"events":events}
    payload=json.dumps({"stats":stats,"table":table,"balance":balance,"current_weather":{"temp":cw.get("temp"),"temp_max":cw.get("temp_max"),"temp_min":cw.get("temp_min"),"pressure":cw.get("pressure"),"precip":cw.get("precip"),"wind_speed":cw.get("wind_speed"),"wind_dir":cw.get("wind_dir"),"wind_dir_str":cw.get("wind_dir_str")},"conditions":conditions,"reports":detailed_reports_sorted,"report_stats":{"top_locations":top_locs,"top_lures":top_lures,"top_times":top_times}},ensure_ascii=False).replace("</","<\\/")
    final=TEMPLATE.replace("__DATA__",payload)
    with open("index.html","w",encoding="utf-8") as f: f.write(final)
    print(f"Сайт собран: остаток {remaining} кг, отчетов с сентября {len(detailed_reports)}")

if __name__=="__main__": main()
