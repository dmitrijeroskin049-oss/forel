import os, re, json, time, random
from collections import defaultdict
from datetime import date, timedelta
import requests
from bs4 import BeautifulSoup

THREAD = "https://www.rusfishing.ru/forum/threads/rybalka-v-krasnogorske.32280"
START_DATE = "2024-01-01"
BATCH = 250
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Форель Красногорск</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
body{font-family:system-ui,sans-serif;margin:0 auto;padding:12px;background:#0f172a;color:#e2e8f0;max-width:820px}
h1{font-size:1.4rem;background:linear-gradient(90deg,#38bdf8,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:#1e293b;border-radius:14px;padding:14px;margin:10px 0}
.big{font-size:1.7rem;font-weight:800;color:#38bdf8}
table{width:100%;border-collapse:collapse;font-size:.82rem}
td,th{padding:6px 4px;border-bottom:1px solid #334155;text-align:left}
a{color:#7dd3fc;text-decoration:none}
.note{font-size:.8rem;color:#94a3b8}
</style></head><body>
<h1>🎣 Форель в Красногорске с 2024</h1>
<div class="card"><div class="note" id="prog"></div><div class="big" id="total"></div>
<div class="note">постов про форель за <span id="days"></span> дней • обновлено <span id="upd"></span></div></div>
<h3>Активность по месяцам (постов/день)</h3><div class="card"><canvas id="m"></canvas></div>
<h3>Клёв vs давление</h3><div class="card"><canvas id="p"></canvas></div>
<h3>Последние активные дни</h3><div class="card"><table id="t"></table></div>
<div class="note">Ссылки ведут на форум. Агент докачивает историю постепенно, свежие даты появляются первыми.</div>
<script>
const D=__DATA__;
document.getElementById('prog').textContent='Собрано страниц: '+D.stats.collected+' из ~'+D.stats.need+' ('+D.stats.pct+'%)';
document.getElementById('total').textContent=D.stats.total_posts;
document.getElementById('days').textContent=D.stats.active_days;
document.getElementById('upd').textContent=D.stats.updated;
new Chart(document.getElementById('m'),{type:'bar',data:{labels:Object.keys(D.stats.monthly),datasets:[{data:Object.values(D.stats.monthly),backgroundColor:'#38bdf8'}]},options:{plugins:{legend:{display:false}}}});
new Chart(document.getElementById('p'),{type:'bar',data:{labels:Object.keys(D.stats.pressure),datasets:[{data:Object.values(D.stats.pressure),backgroundColor:'#4ade80'}]},options:{plugins:{legend:{display:false}}}});
document.getElementById('t').innerHTML='<tr><th>Дата</th><th>П</th><th>t°</th><th>Давл</th><th>Осадки</th><th></th></tr>'+D.table.map(r=>`<tr><td>${r.day}</td><td>${r.posts}</td><td>${r.temp??'—'}</td><td>${r.pressure??'—'}</td><td>${r.precip??'—'}</td><td>${r.links.map((u,i)=>`<a href="${u}" target="_blank">#${i+1}</a>`).join(' ')}</td></tr>`).join('');
</script></body></html>"""

def page_url(p):
    return THREAD if p == 1 else f"{THREAD}/page-{p}"

def fetch(url, tries=4):
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:
            print(f"retry {i+1}: {e}")
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
            "post_date": (t.get("datetime") or "")[:10] if t else "",
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

def main():
    os.makedirs("pages", exist_ok=True)
    import sqlite3
    DB = sqlite3.connect("fishing.db")
    DB.execute("CREATE TABLE IF NOT EXISTS posts (post_id TEXT PRIMARY KEY, page INT, author TEXT, post_date TEXT, text TEXT)")
    state = load_state()
    print("качаю первую страницу...")
    html1 = fetch(page_url(1))
    if not html1:
        raise SystemExit("forum no answer")
    last = total_pages(html1)
    print(f"всего страниц: {last}")

    if not state.get("start_page"):
        print("ищу начало 2024...")
        lo, hi = 1, last
        while lo < hi:
            mid = (lo + hi)//2
            h = fetch(page_url(mid))
            d = first_date(h) if h else ""
            print(f" стр.{mid}: {d or '?'}")
            time.sleep(1)
            if not d or d >= START_DATE:
                hi = mid
            else:
                lo = mid + 1
        state["start_page"] = max(1, lo-1)
        state["cursor"] = last
        state["newest"] = last
        print(f"старт с {state['start_page']}")

    start_page = state["start_page"]
    to_do = []
    if last > state.get("newest", last):
        for p in range(state["newest"]+1, last+1):
            fn = f"pages/page_{p:06d}.json"
            if not os.path.exists(fn):
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
    to_do = sorted(set(to_do + added))
    print(f"качаю {len(to_do)} стр., курсор {state['cursor']}")

    for i, pg in enumerate(to_do):
        h = fetch(page_url(pg))
        if h:
            posts = parse_posts(h, pg)
            json.dump(posts, open(f"pages/page_{pg:06d}.json", "w", encoding="utf-8"), ensure_ascii=False)
            print(f" {i+1}/{len(to_do)} стр.{pg}: {len(posts)} постов")
            for post in posts:
                DB.execute("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?)",
                    (post["post_id"], post["page"], post["author"], post["post_date"], post["text"]))
            DB.commit()
        time.sleep(random.uniform(1.2, 2.2))
        if (i+1) % 20 == 0:
            json.dump(state, open("state.json", "w"), ensure_ascii=False)

    # догружаем старые файлы в базу для анализа
    for fn in os.listdir("pages"):
        if not fn.endswith(".json"):
            continue
        try:
            posts = json.load(open(f"pages/{fn}", encoding="utf-8"))
            for post in posts:
                DB.execute("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?)",
                    (post.get("post_id",""), post.get("page",0), post.get("author",""), post.get("post_date",""), post.get("text","")))
            DB.commit()
        except:
            continue

    json.dump(state, open("state.json", "w"), ensure_ascii=False)
    build(DB, state, last)
    print("ГОТОВО")

def build(DB, state, last):
    FOREL = re.compile("форел", re.I)
    days = defaultdict(list)
    for pid, pg, dt, text in DB.execute("SELECT post_id, page, post_date, text FROM posts"):
        if FOREL.search(text or ""):
            d = (dt or "")[:10]
            if d >= START_DATE:
                url = f"{THREAD}/page-{pg}#post-{pid}" if pid else f"{THREAD}/page-{pg}"
                days[d].append(url)
    weather = {}
    try:
        w = requests.get("https://archive-api.open-meteo.com/v1/archive", params={
            "latitude": 55.82, "longitude": 37.33,
            "start_date": START_DATE,
            "end_date": str(date.today() - timedelta(days=5)),
            "daily": "temperature_2m_mean,precipitation_sum,pressure_msl_mean",
            "timezone": "Europe/Moscow"}, timeout=60).json()["daily"]
        for i, day in enumerate(w["time"]):
            pr = w["pressure_msl_mean"][i]
            weather[day] = {"temp": w["temperature_2m_mean"][i],
                "precip": w["precipitation_sum"][i],
                "pressure": round(pr*0.75006, 1) if pr else None}
    except Exception as e:
        print("weather fail:", e)

    month_act = defaultdict(list)
    press = {"<745": [], "745-760": [], ">760": []}
    for d, urls in days.items():
        month_act[d[:7]].append(len(urls))
        pw = (weather.get(d) or {}).get("pressure")
        if pw:
            k = "<745" if pw < 745 else "745-760" if pw <= 760 else ">760"
            press[k].append(len(urls))
    avg = lambda l: round(sum(l)/len(l), 2) if l else 0
    need = state.get("newest", last) - state.get("start_page", last) + 1
    import glob
    collected = len(glob.glob("pages/*.json"))
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
    payload = json.dumps({"stats": stats, "table": table}, ensure_ascii=False)
    open("index.html", "w", encoding="utf-8").write(TEMPLATE.replace("__DATA__", payload))
    print(f"site done: {stats['total_posts']} posts")

if __name__ == "__main__":
    main()
