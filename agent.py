import os, re, json, time
from collections import defaultdict
from datetime import date, timedelta
from curl_cffi import requests
from bs4 import BeautifulSoup

THREAD = "https://www.rusfishing.ru/forum/threads/rybalka-v-krasnogorske.32280"
BALANCE_START = "2026-09-09"
START_KG = 580
ADMINS = ["александр salmo", "митяй-митиноо", "митяй митино", "александр salmo"]

def fetch(u):
    try:
        r = requests.get(u, impersonate="chrome120", timeout=10)
        return r.text if r.status_code == 200 else ""
    except:
        return ""

def main():
    events = []  # (date_str, kind, kg, quote_snippet)
    # Try last pages where admin posts should be
    for p in range(10451, 10440, -1):
        h = fetch(THREAD if p == 1 else f"{THREAD}/page-{p}")
        if not h:
            continue
        soup = BeautifulSoup(h, "lxml")
        for msg in soup.select("article.message"):
            auth_raw = msg.get("data-author", "").lower()
            if not any(a in auth_raw for a in ADMINS):
                continue
            dt_raw = msg.select_one("time")
            post_dt = (dt_raw.get("datetime") or "")[:19] if dt_raw else ""
            post_date = post_dt[:10] if post_dt else ""
            if not post_date or post_date < BALANCE_START:
                continue
            b = msg.select_one(".bbWrapper")
            if not b:
                continue
            text = b.get_text(" ", strip=True)
            # Simple regex for admin format
            # Pattern: Запуск X кг ... вылов Y кг, or separate lines
            # We'll extract all numbers near keywords
            for m in re.finditer(r"(?:запуск\w*|зарыбление)\D{0,30}?(\d+)\s*(?:кг|кг\.?)", text, re.I):
                val = int(m.group(1))
                if 30 <= val <= 20000:
                    events.append((post_date, "stock", val, text[:120]))
            for m in re.finditer(r"(?:вылов\w*|итог)\D{0,30}?(\d+)\s*(?:кг|кг\.?)", text, re.I):
                val = int(m.group(1))
                if 5 <= val <= 20000:
                    events.append((post_date, "catch", val, text[:120]))
        time.sleep(1)
        print(f"Processed page {p}")

    # Deduplicate by date+kind, keep max for stock (or first), max for catch
    best_stock = {}
    best_catch = {}
    for d, k, v, q in events:
        if k == "stock":
            if d not in best_stock or v > best_stock[d][1]:
                best_stock[d] = (q, v)
        else:
            if d not in best_catch or v > best_catch[d][1]:
                best_catch[d] = (q, v)

    # Build balance from start date
    days = []
    current = date.fromisoformat(BALANCE_START)
    today = date.today()
    rem = START_KG
    bdates = [BALANCE_START]
    bstock = [0]
    bcatch = [0]
    brem = [START_KG]
    while current <= today:
        ds = str(current)
        s = best_stock.get(ds, (None, 0))[1]
        c = best_catch.get(ds, (None, 0))[1]
        rem = max(0, rem + s - c)
        bdates.append(ds); bstock.append(s); bcatch.append(c); brem.append(rem)
        current += timedelta(days=1)

    # Build events list sorted by date desc
    event_list = []
    for d in sorted(best_stock, reverse=True)[:30]:
        event_list.append({"day": d, "t": "запуск", "kg": best_stock[d][1], "u": THREAD, "q": best_stock[d][0]})
    for d in sorted(best_catch, reverse=True)[:30]:
        event_list.append({"day": d, "t": "вылов", "kg": best_catch[d][1], "u": THREAD, "q": best_catch[d][0]})
    event_list.sort(key=lambda x: x["day"], reverse=True)

    # Write HTML
    balance_json = json.dumps({
        "start": BALANCE_START,
        "start_kg": START_KG,
        "ts": sum(best_stock.values(), 0) if False else sum(v for _,v in best_stock.values()),
        "tc": sum(v for _,v in best_catch.values()),
        "rem": brem[-1] if brem else START_KG,
        "dss": (today - date.fromisoformat(list(best_stock.keys())[-1])).days if best_stock else None,
        "sr": {"dates": bdates, "stk": bstock, "ctc": bcatch, "rem": brem},
        "ev": event_list
    })

    stats_simple = {
        "monthly": {},
        "pressure": {},
        "total_posts": len(events),
        "active_days": len({d for d,_,_,_ in events}),
        "collected": len(events),
        "need": 10451,
        "pct": round(len(events)/10451*100, 1) if 10451 else 0,
        "updated": str(today)
    }

    html_template = """<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Форель Красногорск</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
body{font-family:system-ui,sans-serif;margin:0 auto;padding:14px;background:#0f172a;color:#e2e8f0;max-width:820px}
h1{font-size:1.35rem;background:linear-gradient(90deg,#38bdf8,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:#1e293b;border-radius:16px;padding:16px;margin:12px 0}
.big{font-size:2rem;font-weight:800;color:#fbbf24}
table{width:100%;border-collapse:collapse;font-size:.85rem}
td,th{padding:7px 5px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}
a{color:#38bdf8;text-decoration:none}
.note{font-size:.85rem;color:#94a3b8}
</style></head><body>
<h1>🎣 Форель в Красногорске</h1>
<h2>🐟 Остаток форели</h2>
<div class="card"><div class="big">+580 кг</div>
<div class="note">Старт <b>2026-09-09</b> (580 кг остаток) | Запущено: <b>__ST__</b> | Выловлено: <b>__CT__</b> | Остаток сейчас: <b>__REM__</b></div></div>
<div class="card"><canvas id="bal"></canvas></div>
<h3>Журнал (админы)</h3><div class="card"><table><thead><tr><th>Дата</th><th></th><th>кг</th><th>Цитата</th></tr></thead><tbody>__EVT__</tbody></table></div>
<h2>📊 Аналитика с 2024</h2><div class="card"><h3>Активность по месяцам</h3><canvas id="m"></canvas></div>
<div class="card"><h3>Клёв vs давление</h3><canvas id="p"></canvas></div>
<script>
const D=__DATA__;
document.querySelector(".card:first-of-type .note").innerHTML+="<br>Обновлено: "+D.st.updated;
var evtRows = "";
if(D.ev && D.ev.length){
  evtRows = D.ev.map(function(e){
    return "<tr><td>"+e.day+"</td><td>"+(e.t==="запуск"?"🟢":"🔴")+"</td><td><b>"+e.kg+"</b></td><td><a href='"+e.u+"' target='_blank'>"+e.q+"</a></td></tr>";
  }).join("");
} else {
  evtRows = "<tr><td>Ждём данные с 09.09.2026</td><td>—</td><td>—</td><td>—</td></tr>";
}
document.querySelector("tbody").innerHTML = evtRows;

if(D.bal && D.bal.sr && D.bal.sr.dates && D.bal.sr.dates.length){
  new Chart(bal, {data:{labels:D.bal.sr.dates,datasets:[
    {type:"line",label:"Остаток",data:D.bal.sr.rem,borderColor:"#fbbf24",tension:.2,borderWidth:2},
    {type:"bar",label:"Запуск",data:D.bal.sr.stk,backgroundColor:"#4ade80"},
    {type:"bar",label:"Вылов",data:D.bal.sr.ctc,backgroundColor:"#f87171"}
  ]},options:{plugins:{legend:{labels:{color:"#e2e8f0"}}},scales:{x:{ticks:{color:"#94a3b8"}},y:{ticks:{color:"#94a3b8"}}}}});
}
</script></body></html>"""

    evt_str = ""
    if event_list:
        evt_str = "\n".join(["<tr><td>"+e["day"]+"</td><td>"+("🟢" if e["t"]=="запуск" else "🔴")+"</td><td><b>"+str(e["kg"])+"</b></td><td><a href='"+e["u"]+"' target='_blank'>"+str(e["q"])[:100]+"</a></td></tr>" for e in event_list])
    else:
        evt_str = "<tr><td>Ждём данные</td><td>—</td><td>—</td><td>—</td></tr>"

    # Fix total values
    ts = sum(v for _,v in best_stock.values())
    tc = sum(v for _,v in best_catch.values())
    rem_now = brem[-1] if brem else START_KG

    html_filled = html_template.replace("__ST__", str(ts)).replace("__CT__", str(tc)).replace("__REM__", str(rem_now)).replace("__EVT__", evt_str).replace("__DATA__", balance_json)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_filled)

    print("Site built. Stock:", best_stock)
    print("Catch:", best_catch)
    print("Remaining:", rem_now)

if __name__ == "__main__":
    main()
