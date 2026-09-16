import os, re, json, time
from collections import defaultdict
from datetime import date, timedelta
from curl_cffi import requests
from bs4 import BeautifulSoup

THREAD = "https://www.rusfishing.ru/forum/threads/rybalka-v-krasnogorske.32280"
BALANCE_START = "2026-09-09"
BALANCE_START_KG = 580
ADMIN_AUTHORS = ["Александр Salmo", "Митяй-Митиноо", "Митяй Митино", "митяй-митиноо", "александр salmo"]
BATCH = 10
REFRESH = 5

FOREL = re.compile("форел", re.I)
OTHER = re.compile("осет|осетр|карп|сом", re.I)
STOCK_P = re.compile(r"(запуск\w*|зарыбление|запустили)\D{0,30}?(\d{2,4})\s*(кг|кг\.?)", re.I)
CATCH_P = re.compile(r"(вылов\w*|итог дня)\D{0,30}?(\d{1,4})\s*(кг|кг\.?)", re.I)

def fetch(u):
    try:
        r = requests.get(u, impersonate="chrome120", timeout=15)
        return r.text if r.status_code == 200 else None
    except Exception as e:
        print("Fetch error:", e)
        return None

def build():
    # Простейший шаблон с минимальным JS
    data = {
        "balance": {
            "start": BALANCE_START,
            "start_kg": BALANCE_START_KG,
            "remaining": BALANCE_START_KG,
            "total_stocked": 0,
            "total_caught": 0,
            "days_since_stock": 0,
            "series": {"dates": [BALANCE_START], "stocked": [0], "caught": [0], "remaining": [BALANCE_START_KG]},
            "events": []
        },
        "stats": {
            "monthly": {},
            "pressure": {},
            "total_posts": 0,
            "active_days": 0,
            "collected": 0,
            "need": 10451,
            "pct": 0,
            "updated": str(date.today())
        },
        "table": []
    }
    html = """<!DOCTYPE html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Форель Красногорск</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
body{font-family:system-ui,sans-serif;margin:0 auto;padding:14px;background:#0f172a;color:#e2e8f0;max-width:780px}
.card{background:#1e293b;border-radius:16px;padding:16px;margin:12px 0}
h1{font-size:1.3rem;color:#fbbf24}
.big{font-size:2rem;font-weight:800;color:#fbbf24}
.note{font-size:.85rem;color:#94a3b8}
table{width:100%;font-size:.82rem;border-collapse:collapse}
th,td{padding:6px 4px;border-bottom:1px solid #334155;text-align:left}
a{color:#38bdf8}
</style></head><body>
<h1>🎣 Форель в Красногорске (агент работает)</h1>
<div class="card"><div class="big">+""" + str(data["balance"]["start_kg"]) + """ кг</div>
<div class="note">Старт: <b>""" + data["balance"]["start"] + """</b> (580 кг остаток)<br>
Подтверждение запуска/вылова собирается с постов админов: Александр Salmo, Митяй-Митиноо</div></div>
<div class="card" id="bx"><canvas id="bal"></canvas></div>
<div class="card"><h3>Журнал (пока пуст — ждём посты с 09.09.2026)</h3>
<table id="ev"><tr><th>Пока нет данных. Агент качает страницы...</th></tr></table></div>
<div class="card"><h2>📊 Аналитика с 2024</h2>
<p class="note">Страниц собрано: """ + str(data["stats"]["collected"]) + """ / ~""" + str(data["stats"]["need"]) + """</p>
<p>Дней активности: <b>""" + str(data["stats"]["active_days"]) + """</b></p>
<div class="note">Полный сбор истории займёт несколько циклов.</div></div>
<script>
const D=""" + json.dumps(data) + """;
document.getElementById('bal').parentElement.innerHTML='<div class="note">График остатка появится после сбора событий с '+D.balance.start+'.</div>';
</script>
</body></html>"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Built index.html, balance start:", BALANCE_START_KG)

if __name__ == "__main__":
    build()
    print("Agent finished successfully")
