import os, re, json, time, random
from collections import defaultdict
from datetime import date, timedelta
from curl_cffi import requests
from bs4 import BeautifulSoup

THREAD = "https://www.rusfishing.ru/forum/threads/rybalka-v-krasnogorske.32280"
START_DATE = "2024-01-01"        # Общая аналитика постов с 2024 года
BALANCE_START = "2026-09-01"     # Отсчет остатка форели СТРОГО с 01.09.2026
ADMIN_AUTHORS = []               # Ники админов (если нужно ограничить)
BATCH = 150
REFRESH_TAIL = 100

FOREL_RX = re.compile(r"форел", re.I)
OTHER_FISH = re.compile(r"осет|осётр|карп|сом\b|щук|белуг|стерляд|карас|окун|судак|сиг\b|налим|амур|толстолоб|линь", re.I)

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
<div class="card">
  <div class="big" id="rem">—</div>
  <div class="note">запущено <b id="st">0</b> кг − выловлено <b id="ct">0</b> кг • отсчёт с <span id="bs"></span><br>
  последний запуск: <span id="dsl">—</span> • обновлено <span id="upd2"></span></div>
</div>
<div class="card" id="balbox"><canvas id="bal"></canvas></div>

<h3>Журнал запусков и выловов</h3>
<div class="card"><table id="ev"></table></div>

<h2>📊 Активность обсуждений с 2024</h2>
<div class="card">
  <div class="note" id="prog"></div>
  <div class="big" style="color:#38bdf8" id="total">0</div>
  <div class="note">постов про форель за <span id="days">0</span> активных дней</div>
</div>

<h3>Активность по месяцам (постов/день)</h3>
<div class="card"><canvas id="m"></canvas></div>

<h3>Клёв vs давление</h3>
<div class="card"><canvas id="p"></canvas></div>

<h3>Последние активные дни</h3>
<div class="card"><table id="t"></table></div>

<script>
try {
  const D = __DATA__;
  const B = D.balance || {};
  
  // 1. Блок баланса
  document.getElementById('bs').textContent = B.start || '01.09.2026';
  document.getElementById('st').textContent = B.total_stocked || 0;
  document.getElementById('ct').textContent = B.total_caught || 0;
  document.getElementById('rem').textContent = (B.events && B.events.length) ? ('≈ ' + (B.remaining || 0) + ' кг') : 'Ожидание 01.09.2026';
  document.getElementById('dsl').textContent = (B.days_since_stock !== null && B.days_since_stock !== undefined) ? (B.days_since_stock + ' дн. назад') : 'нет данных';
  document.getElementById('upd2').textContent = (D.stats && D.stats.updated) || '';
  
  if (B.series && B.series.dates && B.series.dates.length > 0) {
    new Chart(document.getElementById('bal'), {
      data: {
        labels: B.series.dates,
        datasets: [
          {type: 'line', label: 'Остаток кг', data: B.series.remaining, borderColor: '#fbbf24', tension: 0.3, pointRadius: 0, borderWidth: 2},
          {type: 'bar', label: 'Запуск', data: B.series.stocked, backgroundColor: '#4ade80'},
          {type: 'bar', label: 'Вылов', data: B.series.caught, backgroundColor: '#f87171'}
        ]
      },
      options: {
        plugins: {legend: {labels: {color: '#e2e8f0', boxWidth: 12}}},
        scales: {x: {ticks: {maxTicksLimit: 8, color: '#94a3b8'}}, y: {ticks: {color: '#94a3b8'}}}
      }
    });
  } else {
    document.getElementById('balbox').innerHTML = '<div class="note">Отчёты по запускам и выловам будут отображаться здесь начиная с даты старта (' + (B.start || '01.09.2026') + ').</div>';
  }

  if (B.events && B.events.length > 0) {
    document.getElementById('ev').innerHTML = '<tr><th>Дата</th><th></th><th>кг</th><th>Цитата</th></tr>' +
      B.events.map(e => `<tr><td>${e.day}</td><td>${e.type==='запуск'?'🟢':'🔴'}</td><td><b>${e.kg}</b></td><td class="q"><a href="${e.url}" target="_blank">${e.quote}</a></td></tr>`).join('');
  } else {
    document.getElementById('ev').innerHTML = '<tr><td class="note">Пока нет записей о зарыблении за выбранный период.</td></tr>';
  }

  // 2. Блок статистики с 2024
  if (D.stats) {
    document.getElementById('prog').textContent = 'Собрано страниц: ' + (D.stats.collected || 0) + ' из ~' + (D.stats.need || 0) + ' (' + (D.stats.pct || 0) + '%)';
    document.getElementById('total').textContent = D.stats.total_posts || 0;
    document.getElementById('days').textContent = D.stats.active_days || 0;

    if (D.stats.monthly && Object.keys(D.stats.monthly).length > 0) {
      new Chart(document.getElementById('m'), {
        type: 'bar',
        data: {
          labels: Object.keys(D.stats.monthly),
          datasets: [{data: Object.values(D.stats.monthly), backgroundColor: '#38bdf8'}]
        },
        options: {plugins: {legend: {display: false}}, scales: {x: {ticks: {color: '#94a3b8'}}, y: {ticks: {color: '#94a3b8'}}}}
      });
    }

    if (D.stats.pressure && Object.keys(D.stats.pressure).length > 0) {
      new Chart(document.getElementById('p'), {
        type: 'bar',
        data: {
          labels: Object.keys(D.stats.pressure),
          datasets: [{data: Object.values(D.stats.pressure), backgroundColor: '#4ade80'}]
        },
        options: {plugins: {legend: {display: false}}, scales: {x: {ticks: {color: '#94a3b8'}}, y: {ticks: {color: '#94a3b8'}}}}
      });
    }
  }

  // 3. Таблица активных дней
  if (D.table && D.table.length > 0) {
    document.getElementById('t').innerHTML = '<tr><th>Дата</th><th>П</th><th>t°</th><th>Давл</th><th>Осадки</th><th></th></tr>' +
      D.table.map(r => `<tr><td>${r.day}</td><td>${r.posts}</td><td>${r.temp??'—'}</td><td>${r.pressure??'—'}</td><td>${r.precip??'—'}</td><td>${(r.links||[]).map((u,i)=>`<a href="${u}" target="_blank">#${i+1}</a>`).join(' ')}</td></tr>`).join('');
  }
} catch (err) {
  console.error("Render error:", err);
}
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

STOCK_PATTERNS = [
    re.compile(r"(запустили|запуск|зарыбили|зарыбление|завезли|завоз|выпустили)\D{0,40}?(\d{2,5})\s*(кг|килограмм\w*|тонн\w*|т)\b", re.I),
    re.compile(r"(\d{2,5})\s*(кг|килограмм\w*|тонн\w*|т)\b\D{0,40}(запустили|запуск|зарыбление|завезли|выпустили)", re.I),
]
CATCH_PATTERNS = [
    re.compile(r"(вылов\w*|итог дня|итого)\D{0,40}?(\d{1,5})\s*(кг|килограмм\w*)", re.I),
    re.compile(r"(\d{1,5})\s*(кг|килограмм\w*)\D{0,40}(вылов\w*)", re.I),
]

def to_kg(num_s, unit_s):
    try:
        v = int(num_s)
    except:
        return 0
    if unit_s.lower().startswith("т"):
        v *= 1000
    return v

def snippet(text, pos, width=80):
    a = max(0, pos - 15)
    b = min(len(text), pos + width)
    return "…" + re.sub(r"\s+", " ", text[a:b]).strip() + "…"

def _near(text, pos, rx, rad):
    a = max(0, pos - rad); b = min(len(text), pos + rad)
    return bool(rx.search(text[a:b]))

def find_events(text):
    out = []
    for pat, kind in [(p, "stock") for p in STOCK_PATTERNS] + [(p, "catch") for p in CATCH_PATTERNS]:
        for m in pat.finditer(text):
            num = next((g for g in m.groups() if g and g.isdigit()), None)
            unit = next((g for g in m.groups() if g and re.fullmatch(r"(кг|килограмм\w*|тонн\w*|т)", g, re.I)), None)
            if not num or not unit:
                continue
            kg = to_kg(num, unit)
            pos = m.start()
            other = _near(text, pos, OTHER_FISH, 50)
            forel = _near(text, pos, FOREL_RX, 160)
            if kind == "stock":
                if not (50 <= kg <= 20000): continue
                if other or not forel: continue
            else:
                if not (10 <= kg <= 20000): continue
                if other: continue
            out.append((kind, kg, snippet(text, pos)))
    return out

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
        lo, hi = 1, last
        while lo < hi:
            mid = (lo + hi)//2
            h = fetch(page_url(mid))
            d = first_date(h) if h else ""
            print(f" стр.{mid}: {d or '?'}")
            time.sleep(1.5)
            if not d or d >= START_DATE:
                hi = mid
            else:
                lo = mid + 1
        state["start_page"] = max(1, lo-1)
        state["cursor"] = last
        state["newest"] = last

    start_page = state["start_page"]
    to_do = []
    if last > state.get("newest", last):
        for p in range(state["newest"]+1, last+1):
            to_do.append(p)
        state["newest"] = last

    p = state.get("cursor", last)
    added = []
    while len(added) < BATCH and p >= start_page:
        fn = f"pages/page_{p:06d}.json"
        if not os.path.exists(fn):
            added.append(p)
        p -= 1
    state["cursor"] = p

    tail = list(range(max(start_page, last - REFRESH_TAIL + 1), last + 1))
    to_do = sorted(set(to_do + added + tail))
    print(f"Загружаю {len(to_do)} страниц...")

    for i, pg in enumerate(to_do):
        h = fetch(page_url(pg))
        if h:
            posts = parse_posts(h, pg)
            json.dump(posts, open(f"pages/page_{pg:06d}.json", "w", encoding="utf-8"), ensure_ascii=False)
            print(f" {i+1}/{len(to_do)} стр.{pg}: {len(posts)} постов")
        time.sleep(random.uniform(1.5, 2.5))
        if (i+1) % 20 == 0:
            json.dump(state, open("state.json", "w"), ensure_ascii=False)

    for fn in os.listdir("pages"):
        if not fn.endswith(".json"):
            continue
        try:
            posts = json.load(open(f"pages/{fn}", encoding="utf-8"))
            for post in posts:
                dtv = post.get("post_dt") or post.get("post_date") or ""
                DB.execute("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?)",
                    (post.get("post_id",""), post.get("page",0), post.get("author",""), dtv, post.get("text","")))
            DB.commit()
        except:
            continue

    json.dump(state, open("state.json", "w"), ensure_ascii=False)
    build(DB, state, last)
    print("Успешно завершено!")

def build(DB, state, last):
    days = defaultdict(list)
    day_stock = {}
    day_catch = {}
    for pid, pg, author, pdt, text in DB.execute("SELECT post_id, page, author, post_dt, text FROM posts"):
        d = (pdt or "")[:10]
        url = f"{THREAD}/page-{pg}#post-{pid}" if pid else f"{THREAD}/page-{pg}"
        if FOREL_RX.search(text or "") and d >= START_DATE:
            days[d].append(url)
        if d >= BALANCE_START and pdt:
            if ADMIN_AUTHORS and (author or "") not in ADMIN_AUTHORS:
                continue
            hh = pdt[11:16] if len(pdt) >= 16 else ""
            for kind, kg, quote in find_events(text or ""):
                rec = {"kg": kg, "url": url, "quote": (hh + " " + quote).strip()[:130], "dt": pdt}
                if kind == "stock":
                    if d not in day_stock or pdt < day_stock[d]["dt"]:
                        day_stock[d] = rec
                else:
                    if d not in day_catch or pdt > day_catch[d]["dt"]:
                        day_catch[d] = rec

    day_ev = {}
    for d, r in day_stock.items():
        day_ev.setdefault(d, {})["stock"] = r
    for d, r in day_catch.items():
        day_ev.setdefault(d, {})["catch"] = r

    weather = {}
    try:
        w = requests.get("https://archive-api.open-meteo.com/v1/archive", params={
            "latitude": 55.82, "longitude": 37.33,
            "start_date": START_DATE,
            "end_date": str(date.today() - timedelta(days=5)),
            "daily": "temperature_2m_mean,precipitation_sum,pressure_msl_mean",
            "timezone": "Europe/Moscow"}, timeout=30).json()["daily"]
        for i, day in enumerate(w["time"]):
            pr = w["pressure_msl_mean"][i]
            weather[day] = {"temp": w["temperature_2m_mean"][i],
                "precip": w["precipitation_sum"][i],
                "pressure": round(pr*0.75006, 1) if pr else None}
    except Exception as e:
        print("Погода недоступна:", e)

    month_act = defaultdict(list)
    press = {"<745": [], "745-760": [], ">760": []}
    for d, urls in days.items():
        month_act[d[:7]].append(len(urls))
        pw = (weather.get(d) or {}).get("pressure")
        if pw:
            k = "<745" if pw < 745 else "745-760" if pw <= 760 else ">760"
            press[k].append(len(urls))
    avg = lambda l: round(sum(l)/len(l), 2) if l else 0
    import glob
    collected = len(glob.glob("pages/*.json"))
    need = state.get("newest", last) - state.get("start_page", last) + 1
    stats = {"monthly": {m: avg(v) for m, v in sorted(month_act.items())},
        "pressure": {k: avg(v) for k, v in press.items()},
        "total_posts": sum(len(v) for v in days.values()),
        "active_days": len(days),
        "collected": collected, "need": max(need, 1),
        "pct": round(collected/max(need,1)*100, 1),
        "updated": str(date.today())}
    table = []
    for d in sorted(days, reverse=True)[:60]:
        wv = weather.get(d) or {}
        table.append({"day": d, "posts": len(days[d]), "temp": wv.get("temp"),
            "pressure": wv.get("pressure"), "precip": wv.get("precip"),
            "links": days[d][:5]})

    bdates, bst, bct, brem = [], [], [], []
    total_s = total_c = 0
    last_stock_day = None
    if day_ev:
        d0 = min(day_ev)
        d1 = max(max(day_ev), str(date.today()))
        cur_d = date.fromisoformat(d0)
        end_d = date.fromisoformat(d1)
        rem = 0
        while cur_d <= end_d:
            ds = str(cur_d)
            ev = day_ev.get(ds, {})
            s = ev.get("stock", {}).get("kg", 0)
            c = ev.get("catch", {}).get("kg", 0)
            total_s += s
            total_c += c
            rem = max(0, rem + s - c)
            if s:
                last_stock_day = ds
            bdates.append(ds); bst.append(s); bct.append(c); brem.append(rem)
            cur_d += timedelta(days=1)
    remaining = brem[-1] if brem else 0
    days_since = (date.today() - date.fromisoformat(last_stock_day)).days if last_stock_day else None
    events = []
    for d in sorted(day_ev, reverse=True)[:40]:
        for kind in ("stock", "catch"):
            if kind in day_ev[d]:
                e = day_ev[d][kind]
                events.append({"day": d,
                    "type": "запуск" if kind == "stock" else "вылов",
                    "kg": e["kg"], "url": e["url"], "quote": e["quote"]})
    balance = {"start": BALANCE_START, "total_stocked": total_s, "total_caught": total_c,
        "remaining": remaining, "days_since_stock": days_since,
        "series": {"dates": bdates, "stocked": bst, "caught": bct, "remaining": brem},
        "events": events}

    payload = json.dumps({"stats": stats, "table": table, "balance": balance}, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")
    open("index.html", "w", encoding="utf-8").write(TEMPLATE.replace("__DATA__", payload))
    print(f"Сайт собран: остаток {remaining} кг")

if __name__ == "__main__":
    main()
