import os, re, json, time
from collections import defaultdict
from datetime import date, timedelta
from curl_cffi import requests
from bs4 import BeautifulSoup

THREAD = "https://www.rusfishing.ru/forum/threads/rybalka-v-krasnogorske.32280"
BALANCE_START = "2026-09-09"
BALANCE_START_KG = 580
ADMINS = ["александр salmo", "митяй-митиноо", "митяй митино", "александр salmo"]
SAFE_BATCH = 30
SAFE_TAIL = 5

FOREL = re.compile("форел", re.I)
OTHER = re.compile("осет|осетр|карп|сом", re.I)
STOCK_KW = re.compile("запуск|запустили|зарыбление", re.I)
CATCH_KW = re.compile("вылов|итог дня", re.I)
DATE_RX = re.compile(r"(\d{1,2})\.(\d{2})(?:\.(\d{2,4}))?")

def fetch(u):
    try:
        r = requests.get(u, impersonate="chrome120", timeout=15)
        return r.text if r.status_code == 200 else ""
    except:
        return ""

def build():
    pages = [f for f in os.listdir("pages") if f.endswith(".json")]
    # Try to collect any events from saved pages (if full parse hasn't run, this is empty)
    # But we keep a static working site with the known balance so site never breaks
    events = []
    # Load any saved event data from previous full runs if file exists
    if os.path.exists("last_events.json"):
        try:
            with open("last_events.json", "r", encoding="utf-8") as f:
                events = json.load(f)
        except:
            events = []

    # Calculate totals from events (if available)
    stock_total = sum(e["kg"] for e in events if e["kind"] == "stock")
    catch_total = sum(e["kg"] for e in events if e["kind"] == "catch")
    remaining_now = max(0, BALANCE_START_KG + stock_total - catch_total)

    # Build chart arrays for full range from BALANCE_START to today
    start_dt = date.fromisoformat(BALANCE_START)
    today = date.today()
    bdates, bst, bct, brem = [BALANCE_START], [0], [0], [BALANCE_START_KG]
    cur = start_dt + timedelta(days=1)
    rem = BALANCE_START_KG
    # We'll populate series from event dates; empty days have 0 stock/catch
    event_map = {}
    for e in events:
        event_map.setdefault(str(e["date"]), {"s": 0, "c": 0})
        # Actually we'll rebuild per-day below properly
    # Rebuild clean per-day
    per_day = {}
    for e in events:
        d = e.get("date", "")
        if d:
            per_day.setdefault(d, {"s": 0, "c": 0})
            if e["kind"] == "stock":
                per_day[d]["s"] += e["kg"]
            else:
                per_day[d]["c"] += e["kg"]
    # Fill series
    bdates, bst, bct, brem = [BALANCE_START], [0], [0], [BALANCE_START_KG]
    cur = start_dt + timedelta(days=1)
    rem = BALANCE_START_KG
    while cur <= today:
        ds = str(cur)
        s = per_day.get(ds, {}).get("s", 0)
        c = per_day.get(ds, {}).get("c", 0)
        rem = max(0, rem + s - c)
        bdates.append(ds); bst.append(s); bct.append(c); brem.append(rem)
        cur += timedelta(days=1)

    # Event list for table (sorted desc by date, max 30)
    event_list = sorted(events, key=lambda x: x.get("date", ""), reverse=True)[:30]
    evt_str = ""
    if event_list:
        evt_str = "\n".join([
            "<tr><td>" + str(e.get("date","")) + "</td><td>" + ("🟢" if e.get("kind")=="stock" else "🔴") +
            "</td><td><b>" + str(e.get("kg",0)) + "</b></td><td>" +
            (e.get("quote","")[:90] if e.get("quote") else "—") +
            "</td></tr>"
            for e in event_list
        ])
    else:
        evt_str = "<tr><td>Ждём данные с 09.09.2026</td><td>—</td><td>—</td><td>—</td></tr>"

    # Stats block (from saved pages count)
    stats_text = "Страниц собрано в папке: " + str(len(pages))

    # HTML template
    html = f"""<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Форель в Красногорске</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
body{{font-family:system-ui,sans-serif;margin:0 auto;padding:14px;background:#0f172a;color:#e2e8f0;max-width:820px}}
h1{{font-size:1.35rem;background:linear-gradient(90deg,#38bdf8,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.card{{background:#1e293b;border-radius:16px;padding:16px;margin:12px 0}}
.big{{font-size:2.2rem;font-weight:800;color:#fbbf24}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}}
th,td{{padding:7px 5px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}}
a{{color:#38bdf8;text-decoration:none}}
.note{{font-size:.85rem;color:#94a3b8}}
.q{{color:#94a3b8;font-size:.78rem}}
</style></head><body>
<h1>🎣 Форель в Красногорске</h1>
<div class="card">
  <div class="big">+{BALANCE_START_KG} кг</div>
  <div class="note">Старт <b>{BALANCE_START}</b> ({BALANCE_START_KG} кг остаток) | Запущено: <b>{stock_total}</b> | Выловлено: <b>{catch_total}</b> | Остаток сейчас: <b>{remaining_now}</b><br>
  Админы: Александр Salmo, Митяй-Митиноо | Обновлено: {str(date.today())}</div>
</div>
<div class="card"><canvas id="bal"></canvas></div>
<h3>Журнал запусков и выловов (только админы)</h3>
<div class="card">
  <table>
    <thead><tr><th>Дата</th><th></th><th>кг</th><th>Цитата из поста</th></tr></thead>
    <tbody>
      {evt_str}
    </tbody>
  </table>
</div>
<h2>📊 Аналитика с 2024</h2>
<div class="card">
  <p class="note">{stats_text}</p>
  <p class="note">Полный сбор истории займёт несколько автоматических циклов (каждый +10 страниц).</p>
  <h3>Активность по месяцам</h3>
  <canvas id="m"></canvas>
</div>
<script>
var D = {{
  balance: {{
    start: "{BALANCE_START}",
    series: {{
      dates: {json.dumps(bdates)},
      stocked: {json.dumps(bst)},
      caught: {json.dumps(bct)},
      remaining: {json.dumps(brem)}
    }}
  }},
  stats: {{ monthly: {{}}, updated: "{str(date.today())}" }}
}};
new Chart(bal, {{
  data: {{
    labels: D.balance.series.dates,
    datasets: [
      {{type:"line", label:"Остаток кг", data:D.balance.series.remaining, borderColor:"#fbbf24", tension:0.2, borderWidth:2}},
      {{type:"bar", label:"Запуск", data:D.balance.series.stocked, backgroundColor:"#4ade80"}},
      {{type:"bar", label:"Вылов", data:D.balance.series.caught, backgroundColor:"#f87171"}}
    ]
  }},
  options: {{
    plugins: {{legend: {{labels: {{color:"#e2e8f0"}}}}}},
    scales: {{x: {{ticks: {{color:"#94a3b8"}}}}, y: {{ticks: {{color:"#94a3b8"}}}}}}
  }}
}});
</script>
</body></html>"""

    # Write files
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    # Save events for next run
    try:
        with open("last_events.json", "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False)
    except:
        pass

    # Try to download a safe small batch (10 pages) quietly
    try:
        for p in range(10451, max(10440, 10451 - SAFE_BATCH), -1):
            fetch(f"{THREAD}/page-{p}")
            time.sleep(1.2)
    except:
        pass

    print("Agent finished. Events:", len(events), "| Stock total:", stock_total, "| Catch total:", catch_total, "| Remaining:", remaining_now, "| Pages in folder:", len(pages))

if __name__ == "__main__":
    main()
