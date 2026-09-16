import os, re, json, time
from datetime import date, timedelta
from curl_cffi import requests
from bs4 import BeautifulSoup

THREAD = "https://www.rusfishing.ru/forum/threads/rybalka-v-krasnogorske.32280"
BALANCE_START = "2026-09-09"
START_KG = 580
ADMINS = ["александр salmo", "митяй-митиноо", "митяй митино"]
SAFE_BATCH = 10

FOREL = re.compile("форел", re.I)
STOCK_KW = re.compile("запуск|запустили|зарыбление|зарыбили", re.I)
CATCH_KW = re.compile("вылов|итог дня|итого", re.I)
DATE_RX = re.compile(r"(\d{1,2})\.(\d{2})(?:\.(\d{2,4}))?")

def fetch(u):
    try:
        r = requests.get(u, impersonate="chrome120", timeout=15)
        return r.text if r.status_code == 200 else ""
    except:
        return ""

def main():
    events = []
    if os.path.exists("last_events.json"):
        try:
            with open("last_events.json", "r", encoding="utf-8") as f:
                events = json.load(f)
        except:
            events = []

    # Small safe download
    try:
        for p in range(10451, max(10440, 10451 - SAFE_BATCH), -1):
            h = fetch(THREAD if p == 1 else f"{THREAD}/page-{p}")
            if h:
                soup = BeautifulSoup(h, "lxml")
                for msg in soup.select("article.message"):
                    auth = (msg.get("data-author") or "").lower()
                    if not any(a in auth for a in ADMINS):
                        continue
                    dt_tag = msg.select_one("time")
                    post_dt = (dt_tag.get("datetime") or "") if dt_tag else ""
                    if not post_dt:
                        continue
                    post_date = post_dt[:10]
                    if post_date < BALANCE_START:
                        continue
                    b = msg.select_one(".bbWrapper")
                    if not b:
                        continue
                    text = b.get_text(" ", strip=True)
                    for m in re.finditer(r"(?:запуск\w*|зарыбление)\D{0,40}?(\d{2,4})\s*(?:кг|кг\.?)", text, re.I):
                        val = int(m.group(1))
                        if 30 <= val <= 20000:
                            ed_match = DATE_RX.search(text[max(0, m.start()-40):m.end()+40])
                            ev_date = post_date
                            if ed_match:
                                try:
                                    d, mo = int(ed_match.group(1)), int(ed_match.group(2))
                                    yy = int(ed_match.group(3)) if ed_match.group(3) else int(post_date[:4])
                                    if len(str(yy)) == 2:
                                        yy = 2000 + yy if yy < 50 else 1900 + yy
                                    ev_date = f"{yy:04d}-{mo:02d}-{d:02d}"
                                except:
                                    pass
                            events.append({"date": ev_date, "kind": "stock", "kg": val, "quote": text[:90], "post_dt": post_dt})
                    for m in re.finditer(r"(?:вылов\w*|итог)\D{0,40}?(\d{1,4})\s*(?:кг|кг\.?)", text, re.I):
                        val = int(m.group(1))
                        if 5 <= val <= 20000:
                            events.append({"date": post_date, "kind": "catch", "kg": val, "quote": text[:90], "post_dt": post_dt})
            time.sleep(1.5)
    except Exception as e:
        print("Download interrupted:", e)

    with open("last_events.json", "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False)

    # Deduplicate per day: max stock, max catch
    best_stock = {}
    best_catch = {}
    for e in events:
        d = e.get("date", "")
        if d >= BALANCE_START:
            if e["kind"] == "stock":
                if d not in best_stock or e["kg"] > best_stock[d]["kg"]:
                    best_stock[d] = e
            else:
                if d not in best_catch or e["kg"] > best_catch[d]["kg"]:
                    best_catch[d] = e

    stock_total = sum(e["kg"] for e in best_stock.values())
    catch_total = sum(e["kg"] for e in best_catch.values())

    # Build series
    start_dt = __import__("datetime").date.fromisoformat(BALANCE_START)
    today = __import__("datetime").date.today()
    bdates = [BALANCE_START]
    bst = [0]
    bct = [0]
    brem = [START_KG]
    rem = START_KG
    cur = start_dt + __import__("datetime").timedelta(days=1)
    while cur <= today:
        ds = str(cur)
        s = best_stock.get(ds, {}).get("kg", 0)
        c = best_catch.get(ds, {}).get("kg", 0)
        rem = max(0, rem + s - c)
        bdates.append(ds); bst.append(s); bct.append(c); brem.append(rem)
        cur += __import__("datetime").timedelta(days=1)

    # Events rows sorted desc
    ev_rows = ""
    ev_list = sorted([{**e, "t": "запуск" if e["kind"]=="stock" else "вылов"} for e in list(best_stock.values()) + list(best_catch.values())], key=lambda x: x["date"], reverse=True)[:30]
    for e in ev_list:
        ev_rows += f"<tr><td>{e['date']}</td><td>{'🟢' if e['t']=='запуск' else '🔴'}</td><td><b>{e['kg']}</b></td><td class='q'>{e['quote'][:80]}</td></tr>"

    # Safe HTML without f-string braces conflict
    html = """<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Форель Красногорск</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
body{font-family:system-ui,sans-serif;margin:0 auto;padding:14px;background:#0f172a;color:#e2e8f0;max-width:820px}
h1{font-size:1.3rem;background:linear-gradient(90deg,#38bdf8,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:#1e293b;border-radius:16px;padding:16px;margin:12px 0}
.big{font-size:2.2rem;font-weight:800;color:#fbbf24}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th,td{padding:7px 5px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}
a{color:#38bdf8;text-decoration:none}
.note{font-size:.85rem;color:#94a3b8}
</style></head><body>
<h1>🎣 Форель в Красногорске</h1>
<div class="card">
<div class="big">+{start_kg} кг</div>
<div class="note">Старт <b>{start}</b> ({start_kg} кг остаток) | Запущено: <b>{stk}</b> | Выловлено: <b>{ctk}</b> | Остаток сейчас: <b>{rem_now}</b><br>
Админы: Александр Salmo, Митяй-Митиноо | Обновлено: {today}</div>
</div>
<div class="card"><canvas id="bal"></canvas></div>
<h3>Журнал запусков и выловов (только админы)</h3>
<div class="card"><table>
<thead><tr><th>Дата</th><th></th><th>кг</th><th>Цитата из поста</th></tr></thead>
<tbody>
{rows}
</tbody>
</table></div>
<h2>📊 Аналитика с 2024</h2>
<div class="card"><h3>Активность по месяцам</h3><canvas id="m"></canvas></div>
<div class="card"><p class="note">Страниц собрано в папке: {pages} | Событий: {events}</p></div>
<script>
var D = {json_str};
new Chart(bal, {{
  data: {{
    labels: D.sr.dates,
    datasets: [
      {{type:"line",label:"Остаток",data:D.sr.rem,borderColor:"#fbbf24",tension:0.2,borderWidth:2}},
      {{type:"bar",label:"Запуск",data:D.sr.stk,backgroundColor:"#4ade80"}},
      {{type:"bar",label:"Вылов",data:D.sr.ctc,backgroundColor:"#f87171"}}
    ]
  }},
  options: {{
    plugins: {{legend: {{labels: {{color:"#e2e8f0"}}}}}},
    scales: {{x: {{ticks: {{color:"#94a3b8"}}}},y: {{ticks: {{color:"#94a3b8"}}}}}}
  }}
}});
</script>
</body></html>"""

    pages = [f for f in os.listdir("pages") if f.endswith(".json")]
    data_for_json = {
        "sr": {
            "dates": bdates,
            "stk": bst,
            "ctc": bct,
            "rem": brem
        }
    }
    # Replace safely without f-string braces
    filled = html.format(
        start_kg=START_KG,
        start=BALANCE_START,
        stk=stock_total,
        ctk=catch_total,
        rem_now=brem[-1] if brem else START_KG,
        today=str(date.today()),
        rows=ev_rows,
        pages=str(len(pages)),
        events=str(len(events)),
        json_str=json.dumps(data_for_json).replace("</script>", "<\\/script>")
    )
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(filled)

    with open("last_events.json", "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False)

    print("Agent done. Events:", len(events), "Stock:", stock_total, "Catch:", catch_total, "Rem:", brem[-1] if brem else START_KG, "Pages:", len(pages))

if __name__ == "__main__":
    main()
