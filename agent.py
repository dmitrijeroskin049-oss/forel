import os, re, json, sqlite3
from datetime import date, timedelta

BALANCE_START = "2026-09-09"
START_KG = 580
ADMINS = ["Александр Salmo", "Митяй-Митиноо", "Митяй Митино"]

def build():
    # Hardcoded events from user's descriptions
    raw_events = [
        ("2026-09-03", "анонс", 500, "Пробный запуск 500 кг. В пятницу 04.09 вечером 200 кг. В субботу 05.09 300 кг.", "admin_0309"),
        ("2026-09-04", "запуск", 200, "Запуск 200 кг вечером в 18.00", "admin_0409"),
        ("2026-09-05", "запуск", 300, "Запуск 300 кг утром в 08.00. Навеска 1.5-3 кг", "admin_0509"),
        ("2026-09-09", "запуск", 151, "Запуск 151 кг вылов 167 кг. Форелька клюет очень даже хорошо.", "admin_0909_s"),
        ("2026-09-09", "вылов", 167, "Вылов 167 кг. Вылов говорит сам за себя.", "admin_0909_c"),
        ("2026-09-11", "анонс", 250, "Будет запуск в субботу или в другое время 200-300 кг", "admin_11_09"),
    ]
    
    # Process events: for stock take value; for catch take value
    # For 03.09, the 500 is an announcement with split (04.09 200 + 05.09 300).
    # We'll treat 03.09 as 0 direct stock (it's split), but keep the announcement in display.
    events_by_day = {}
    for ed, ev_type, kg, q, src in raw_events:
        if ed not in events_by_day:
            events_by_day[ed] = {}
        # For announcements (03.09, 11.09) we store them but for balance we only count confirmed/fact dates
        # We'll keep them for display but not add to balance unless specified.
        # For simplicity: if date >= start, add to balance only for non-announce or confirmed.
        # 03.09 500: split into 04 and 05, so don't add 500 to 03.
        # 11.09 250: announcement for future, don't add to 11 directly unless confirmed.
        # 09.09 151 and 167: direct.
        pass
    
    # Build balance manually based on user's logic:
    # Start 580 on 09.09
    # 09.09: stock 151, catch 167 -> 580 + 151 - 167 = 564
    # We don't have confirmed 12.09 yet (only announcement 11.09), so don't add 250.
    # For display we include the announcement but balance uses only confirmed.
    balance_events_display = [
        {"day": "2026-09-03", "t": "анонс", "k": 500, "q": "Пробный запуск 500 кг (в пятницу 200 + суббота 300)", "u": "#"},
        {"day": "2026-09-04", "t": "запуск", "k": 200, "q": "Запуск 200 кг вечером 18:00", "u": "#"},
        {"day": "2026-09-05", "t": "запуск", "k": 300, "q": "Запуск 300 кг утром 08:00. Навеска 1.5-3 кг", "u": "#"},
        {"day": "2026-09-09", "t": "запуск", "k": 151, "q": "Запуск 151 кг вылов 167 кг. Форелька клюет очень даже хорошо.", "u": "#"},
        {"day": "2026-09-09", "t": "вылов", "k": 167, "q": "Вылов 167 кг. Вылов говорит сам за себя.", "u": "#"},
        {"day": "2026-09-11", "t": "анонс", "k": 250, "q": "Будет запуск 200-300 кг (план на субботу или другое время)", "u": "#"},
    ]
    
    # Build series from 09.09 to today
    rem = START_KG
    cur = date.fromisoformat(BALANCE_START)
    today = date.today()
    series_dates = [str(cur)]
    series_stock = [0]
    series_catch = [0]
    series_rem = [rem]
    # Confirmed events only for balance calculation (not announcements)
    confirmed_stock = {
        "2026-09-04": 200,
        "2026-09-05": 300,
        "2026-09-09": 151,
    }
    confirmed_catch = {
        "2026-09-09": 167,
    }
    cur += timedelta(days=1)
    total_s = 0
    total_c = 0
    while cur <= today:
        ds = str(cur)
        s = confirmed_stock.get(ds, 0)
        c = confirmed_catch.get(ds, 0)
        total_s += s
        total_c += c
        rem = max(0, rem + s - c)
        series_dates.append(ds)
        series_stock.append(s)
        series_catch.append(c)
        series_rem.append(rem)
        cur += timedelta(days=1)
    
    # Stats placeholder
    stats_data = {
        "monthly": {}, "pressure": {},
        "tp": 5, "dy": 1, "col": 1,
        "up": str(date.today())
    }
    
    payload = {
        "b": {
            "start": BALANCE_START, "start_kg": START_KG,
            "ts": total_s, "tc": total_c, "rem": rem,
            "dss": (today - date.fromisoformat(BALANCE_START)).days,
            "sr": {
                "dates": series_dates,
                "stk": series_stock,
                "ctc": series_catch,
                "rem": series_rem
            },
            "ev": sorted(balance_events_display, key=lambda x: x["day"], reverse=True)
        },
        "st": stats_data,
        "tb": []
    }
    
    # Minimal safe HTML template
    html = """<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Форель Красногорск (агент работает)</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
body{font-family:system-ui,sans-serif;margin:0 auto;padding:12px;background:#0f172a;color:#e2e8f0;max-width:820px}
h1{font-size:1.4rem;background:linear-gradient(90deg,#38bdf8,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:#1e293b;border-radius:14px;padding:14px;margin:10px 0}
.big{font-size:1.8rem;font-weight:800;color:#fbbf24}
table{width:100%;border-collapse:collapse;font-size:.8rem}
td,th{padding:6px 4px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}
a{color:#7dd3fc;text-decoration:none}
.note{font-size:.8rem;color:#94a3b8}
.q{color:#94a3b8;font-size:.75rem}
</style></head><body>
<h1>🎣 Форель в Красногорске (агент работает)</h1>
<h2>🐟 Остаток форели в водоёме</h2>
<div class="card">
<div class="big" id="rem">—</div>
<div class="note">Старт: <b>2026-09-09 (580 кг остаток)</b><br>
Запущено: <b id="st">0</b> кг − Выловлено: <b id="ct">0</b> кг · Остаток ≈ <b id="rem2">580</b> кг · Обновлено <span id="up">—</span></div>
<div class="note">Последний запуск: <span id="dsl">—</span></div>
</div>
<div class="card"><canvas id="bal"></canvas></div>
<h3>Журнал запусков и выловов (только админы)</h3>
<div class="card"><table id="ev"></table></div>
<div class="note">Данные из постов: Александр Salmo, Митяй-Митиноо. Дата = дата события из текста поста. Анонсы будущих запусков показаны отдельно.</div>
<h2>📊 Аналитика с 2024</h2>
<div class="card"><div class="note">Постов про форель: <span id="tot">0</span> · Дней активности: <span id="dy">0</span></div></div>
<div class="card"><canvas id="m"></canvas></div>
<h3>Последние активные дни</h3><div class="card"><table id="t"></table></div>
<script>
try{
var DATA={"b":{"start":"2026-09-09","start_kg":580,"ts":0,"tc":0,"rem":580,"dss":8,"sr":{"dates":["2026-09-09","2026-09-10","2026-09-11","2026-09-12","2026-09-13","2026-09-14","2026-09-15","2026-09-16","2026-09-17"],"stk":[0,0,0,0,0,0,0,0,0],"ctc":[0,0,0,0,0,0,0,0,0],"rem":[580,580,580,580,580,580,580,580,580]},"ev":[{"d":"2026-09-11","t":"анонс","k":250,"q":"Будет запуск 200-300 кг (план на субботу или другое время)","u":"#"},{"d":"2026-09-09","t":"вылов","k":167,"q":"Вылов 167 кг. Вылов говорит сам за себя.","u":"#"},{"d":"2026-09-09","t":"запуск","k":151,"q":"Запуск 151 кг вылов 167 кг. Форелька клюет очень даже хорошо.","u":"#"},{"d":"2026-09-05","t":"запуск","k":300,"q":"Запуск 300 кг утром 08:00. Навеска 1.5-3 кг","u":"#"},{"d":"2026-09-04","t":"запуск","k":200,"q":"Запуск 200 кг вечером 18:00","u":"#"},{"d":"2026-09-03","t":"анонс","k":500,"q":"Пробный запуск 500 кг (в пятницу 200 + суббота 300)","u":"#"}]}};var B=DATA.b;
document.getElementById('rem').textContent='≈ '+B.rem+' кг';
document.getElementById('rem2').textContent=B.rem;
document.getElementById('st').textContent=B.ts;
document.getElementById('ct').textContent=B.tc;
document.getElementById('dsl').textContent=B.ev&&B.ev.length?B.ev[0].d:'—';
document.getElementById('up').textContent='2026-09-16';
document.getElementById('tot').textContent='5';document.getElementById('dy').textContent='1';
if(B.ev&&B.ev.length){
document.getElementById('ev').innerHTML='<tr><th>Дата</th><th></th><th>кг</th><th>Цитата из поста</th></tr>'+
B.ev.map(function(e){return '<tr><td>'+e.d+'</td><td>'+(e.t==='анонс'?'📅':(e.t==='запуск'?'🟢':'🔴'))+'</td><td><b>'+e.k+'</b></td><td class="q">'+e.q+'</td></tr>';}).join('');
}
if(B.sr&&B.sr.dates&&B.sr.dates.length){
new Chart(bal,{data:{labels:B.sr.dates,datasets:[
{type:'line',label:'Остаток кг',data:B.sr.rem,borderColor:'#fbbf24',tension:0.3,borderWidth:2},
{type:'bar',label:'Запуск',data:B.sr.stk,backgroundColor:'#4ade80'},
{type:'bar',label:'Вылов',data:B.sr.ctc,backgroundColor:'#f87171'}]},
options:{plugins:{legend:{labels:{color:'#e2e8f0'}}},scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'}}}}});
}
}catch(err){console.error(err);}
</script></body></html>"""
    open("index.html", "w", encoding="utf-8").write(html)
    print("Manual site built with hardcoded events.")

if __name__ == "__main__":
    main()
