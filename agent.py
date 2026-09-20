import os
import re
import json
import time
import random
import glob
import sqlite3
from collections import defaultdict
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

ADMIN_AUTHORS = [
    "Александр SALMO",
    "Митяй-Митинооо",
]

IGNORE_STOCK_DAYS = {
    "2026-09-04", "2026-09-05", "2026-09-06", "2026-09-07", "2026-09-08",
}

BATCH = 150
REFRESH_TAIL = 15

# Рыба
FOREL_RX = re.compile(r"форел", re.I)
OTHER_FISH = re.compile(
    r"осет|осётр|карп|сом\b|щук|белуг|стерляд|карас|"
    r"окун|судак|сиг\b|налим|амур|толстолоб|линь", re.I,
)

# Дата
DATE_RX = re.compile(r"(?<!\d)(\d{1,2})\.(\d{2})(?:\.(\d{2,4}))?(?!\d)")

# Вес
KG_RX = re.compile(
    r"(\d+(?:[.,]\d+)?)(?:\s*[-–—]\s*(\d+(?:[.,]\d+)?))?\s*(кг|килограмм\w*|тонн\w*|т)\b", re.I,
)

# Запуск/вылов
STOCK_KW_RX = re.compile(r"запуск|запустили|зарыбление|зарыбили|завезли|завоз|выпустили", re.I)
CATCH_KW_RX = re.compile(r"вылов\w*|итог дня|итого", re.I)
FUTURE_RX = re.compile(r"сделаем|будет|будут|планиру|анонс|ожидается|собираемся|намечает", re.I)

STOCK_NOUNIT_RX = re.compile(r"(запуск\w*|запустили|зарыбление\w*)\s*[:\-–—]?\s*(\d{2,4})\b", re.I)
CATCH_NOUNIT_RX = re.compile(r"(вылов\w*|итог\w*)\s*[:\-–—]?\s*(\d{1,4})\b", re.I)

NABECKA_RX = re.compile(r"навеск", re.I)

# Точки на водоёме (расширено)
LOCATION_RX = re.compile(
    r"основной водо[её]м|дальний угол|у плотин\w*|у коряг\w*|у входа|у выхода|центр\w*|мелководь\w*|"
    r"глубок\w* участок|у берега|у причала|у мостка|у дамбы|у стены|у кустов|у травы|у тростника|"
    r"у затопленн\w* дерев\w*|у ямы|у бровки|у сваи|у трубы|у слива|у аэратора|у кормушк\w*|"
    r"у обрыва|у отмели|у переката|у залива|у бухты|понтон\w*|пантон\w*|старый понтон|новый пантон|"
    r"новый понтон|старый пантон|переходной серый мост|бабий угол|женский угол|пляж|под дубами|под ивой|"
    r"под администрацией|под стадионом|на запуске|на спорт зоне|старая спорт зона", re.I,
)

# Приманки (расширено)
LURE_RX = re.compile(
    r"вертушк\w*|воблер\w*|резин\w*|мушк\w*|блесна|черв\w*|опарыш\w*|мотыл\w*|пенопласт|тесто|сыр|"
    r"бойл\w*|поппер\w*|цикад\w*|колебалк\w*|вращалк\w*|силикон\w*|твистер\w*|виброхвост\w*|рапал\w*|"
    r"минноу|кренк\w*|джерк\w*|спининг\w*|донк\w*|фидер\w*|поплавочн\w*|мормышк\w*|балда|стример\w*|"
    r"нимф\w*|сухая мушка|мокрая мушка|личинк\w*|мотылёк|ручейник|магот\w*|светонакоп\w*|"
    r"светонакопительный|стрейч|бобриный хвост|пламп\w*|Биг Джуниор", re.I,
)

TIME_RX = re.compile(r"утро|вечер|ночь|рассвет|закат|день|с (\d{1,2}) до (\d{1,2})|после (\d{1,2})|до (\d{1,2})", re.I)
DEPTH_RX = re.compile(r"дно|полвод\w*|поверхност\w*|у дна|в полвод\w*|верхний слой|средний слой|придонный слой|у поверхност\w*|под берегом|на глубин[еу] (\d+)\s*м|на (\d+)\s*м", re.I)
SENTENCE_RX = re.compile(r"[.!?…]")
BAD_BETWEEN_RX = re.compile(r"корм|прикорм|пеллет|смес", re.I)

# Ключевые слова для отчётов об улове
CATCH_REPORT_RX = re.compile(r"поймал|выловил|улов|взял|штук|кг.*форел|форел.*кг|клюёт|клёв|сработал|отличн", re.I)

TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
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
  <span><b>🌤 Погода:</b> <span id="curTemp">—</span>°C • <span id="curPress">—</span> мм рт.ст. • осадки <span id="curPrecip">—</span> мм</span>
</div>

<details open>
<summary>🎟 Условия рыбалки</summary>
<div class="card">
  <h2>🎟 Условия рыбалки</h2>
  <table>
    <tr><td>06:00–19:00</td><td><b>4000 ₽</b></td></tr>
    <tr><td>12:00–19:00</td><td><b>2200 ₽</b></td></tr>
    <tr><td>18:00–06:00</td><td><b>4000 ₽</b></td></tr>
    <tr><td>Сутки</td><td><b>5000 ₽</b></td></tr>
    <tr><td>Приоритетный час</td><td><b>300 ₽</b></td></tr>
    <tr><td>Дополнительная снасть</td><td><b>500 ₽</b></td></tr>
  </table>
  <p>🎣 Разрешено ловить на две снасти, не более двух крючков на каждой.<br>
    👩 Женщина и ребёнок до 13 лет ловят бесплатно на снасти рыбака.<br>
    🐟 Нормы вылова нет. ✅ Спиннинг разрешён. ⛔ Пеллетс и блёсны с тройниками запрещены.</p>
  <p><b>Координаты:</b> <a href="https://yandex.ru/maps/?pt=37.322979,55.840619&z=15&l=map" target="_blank" rel="noopener">55.840619, 37.322979</a><br>
    <b>Телефон:</b> <a href="tel:+79852620637">+7 985 262-06-37</a></p>
  <div class="note">Проверено по сообщению администрации от 13.09.2026. Перед поездкой уточняйте условия.</div>
</div>
</details>

<details open>
<summary>🐟 Остаток форели в водоёме</summary>
<div class="card">
  <div class="big" id="rem">—</div>
  <div class="note">запущено <b id="st">0</b> кг − выловлено <b id="ct">0</b> кг • отсчёт с <span id="bs"></span><br>
    последний запуск: <span id="dsl">—</span> • обновлено <span id="upd2"></span></div>
</div>
</details>

<details open>
<summary>📈 Баланс</summary>
<div class="card" id="balbox"><canvas id="bal"></canvas></div>
</details>

<details open>
<summary>📓 Журнал запусков и выловов</summary>
<div class="card"><table id="ev"></table></div>
</details>
<div class="note">Дата в таблице = дата события из текста, а не дата поста.</div>

<details open>
<summary>📊 Активность обсуждений с 2024</summary>
<div class="card">
  <div class="note" id="prog"></div>
  <div class="big" style="color:#38bdf8" id="total">0</div>
  <div class="note">постов про форель за <span id="days">0</span> активных дней</div>
</div>
<h3>Активность по месяцам (постов/день)</h3>
<div class="card"><canvas id="m"></canvas></div>
<h3>Клёв vs давление (по отчётам)</h3>
<div class="card"><canvas id="p"></canvas></div>
<div class="note">Среднее количество постов и упоминаний улова в сутки при разном атмосферном давлении. Данные: Open-Meteo + форум.</div>
<h3>Последние активные дни</h3>
<div class="card"><table id="t"></table></div>
<div class="note">Температура — средняя за сутки (Open-Meteo).</div>
</details>

<details open>
<summary>🎣 Перспективные точки и приманки</summary>
<div class="card">
  <h3>Где лучше клюёт</h3>
  <div class="note">По отчётам рыбаков с начала 2024 года</div>
  <table id="locs"></table>
</div>
<div class="card">
  <h3>Какая приманка лучше работает</h3>
  <canvas id="lure"></canvas>
</div>
<div class="card">
  <h3>В какое время лучше клюёт</h3>
  <canvas id="time"></canvas>
</div>
</details>

<script>
try {
    const D = __DATA__;

    function renderTop() {
        const now = new Date();
        document.getElementById('curDate').textContent = now.toLocaleDateString('ru-RU', {day:'numeric', month:'long', year:'numeric'});
        document.getElementById('curTime').textContent = now.toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit'});
        const cw = (D.current_weather || {});
        document.getElementById('curTemp').textContent = (cw.temp !== undefined && cw.temp !== null) ? cw.temp : '—';
        document.getElementById('curPress').textContent = (cw.pressure !== undefined && cw.pressure !== null) ? cw.pressure : '—';
        document.getElementById('curPrecip').textContent = (cw.precip !== undefined && cw.precip !== null) ? cw.precip : '—';
    }
    renderTop();
    setInterval(renderTop, 30000);

    const B = D.balance || {};
    document.getElementById('bs').textContent = B.start || '2026-09-01';
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
                    { type: 'line', label: 'Остаток кг', data: B.series.remaining, borderColor: '#fbbf24', tension: 0.3, pointRadius: 0, borderWidth: 2 },
                    { type: 'bar', label: 'Запуск', data: B.series.stocked, backgroundColor: '#4ade80' },
                    { type: 'bar', label: 'Вылов', data: B.series.caught, backgroundColor: '#f87171' }
                ]
            },
            options: { plugins: { legend: { labels: { color: '#e2e8f0', boxWidth: 12 } } }, scales: { x: { ticks: { maxTicksLimit: 8, color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' } } } }
        });
    } else { document.getElementById('balbox').innerHTML = '<div class="note">Отчёты появятся начиная с ' + (B.start || '2026-09-01') + '.</div>'; }

    if (B.events && B.events.length > 0) {
        document.getElementById('ev').innerHTML = '<tr><th>Дата</th><th></th><th>кг</th><th>Цитата</th></tr>' + B.events.map(e => `<tr><td>${e.day}</td><td>${e.type === 'запуск' ? '🟢' : '🔴'}</td><td><b>${e.kg}</b></td><td class="q"><a href="${e.url}" target="_blank" rel="noopener">${e.quote}</a></td></tr>`).join('');
    } else { document.getElementById('ev').innerHTML = '<tr><td class="note">Пока нет записей.</td></tr>'; }

    if (D.stats) {
        document.getElementById('prog').textContent = 'Собрано страниц: ' + (D.stats.collected || 0) + ' из ~' + (D.stats.need || 0) + ' (' + (D.stats.pct || 0) + '%)';
        document.getElementById('total').textContent = D.stats.total_posts || 0;
        document.getElementById('days').textContent = D.stats.active_days || 0;
        if (D.stats.monthly && Object.keys(D.stats.monthly).length > 0) {
            new Chart(document.getElementById('m'), { type: 'bar', data: { labels: Object.keys(D.stats.monthly), datasets: [{ data: Object.values(D.stats.monthly), backgroundColor: '#38bdf8' }] }, options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' } } } } });
        }
        if (D.stats.pressure_chart) {
            new Chart(document.getElementById('p'), {
                type: 'bar',
                data: {
                    labels: D.stats.pressure_chart.labels,
                    datasets: [
                        { label: 'Постов/день', data: D.stats.pressure_chart.posts, backgroundColor: '#38bdf8' },
                        { label: 'Отчётов об улове/день', data: D.stats.pressure_chart.catches, backgroundColor: '#4ade80' }
                    ]
                },
                options: {
                    plugins: { legend: { labels: { color: '#e2e8f0' } } },
                    scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' }, beginAtZero: true } }
                }
            });
        }
    }

    if (D.table && D.table.length > 0) {
        document.getElementById('t').innerHTML = '<tr><th>Дата</th><th>П</th><th>t° (средн.)</th><th>Давл</th><th>Осадки</th><th></th></tr>' + D.table.map(r => `<tr><td>${r.day}</td><td>${r.posts}</td><td>${r.temp ?? '—'}</td><td>${r.pressure ?? '—'}</td><td>${r.precip ?? '—'}</td><td>${(r.links || []).map((u, i) => `<a href="${u}" target="_blank" rel="noopener">#${i + 1}</a>`).join(' ')}</td></tr>`).join('');
    }

    if (D.locations && D.locations.length > 0) {
        document.getElementById('locs').innerHTML = '<tr><th>Дата</th><th>Точка</th><th>Приманка</th><th>Время</th><th>Горизонт</th><th>Улов</th><th>Цитата</th></tr>' + D.locations.map(r => `<tr><td>${r.day}</td><td>${r.location || '—'}</td><td>${r.lure || '—'}</td><td>${r.time || '—'}</td><td>${r.depth || '—'}</td><td>${r.catch || '—'}</td><td class="q"><a href="${r.url}" target="_blank" rel="noopener">${r.quote}</a></td></tr>`).join('');
    } else { document.getElementById('locs').innerHTML = '<tr><td class="note">Пока нет отчётов.</td></tr>'; }

    if (D.lure_stats) {
        new Chart(document.getElementById('lure'), { type: 'bar', data: { labels: Object.keys(D.lure_stats), datasets: [{ label: 'Успешных случаев', data: Object.values(D.lure_stats), backgroundColor: '#38bdf8' }] }, options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' } } } } });
    }
    if (D.time_stats) {
        new Chart(document.getElementById('time'), { type: 'bar', data: { labels: Object.keys(D.time_stats), datasets: [{ label: 'Успешных случаев', data: Object.values(D.time_stats), backgroundColor: '#4ade80' }] }, options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' } } } } });
    }

    // Автоматическое сворачивание блоков
    document.querySelectorAll('.card').forEach(function(card){
        if (card.closest('details') || card.id === 'topbar' || card.id === 'balbox') return;
        var d = document.createElement('details');
        d.open = true;
        var s = document.createElement('summary');
        var h = card.querySelector('h2, h3');
        s.textContent = h ? h.textContent.trim() : 'Блок';
        card.parentNode.insertBefore(d, card);
        d.appendChild(s);
        d.appendChild(card);
    });
} catch (err) { console.error(err); }
</script>
</body>
</html>"""

def page_url(page_number):
    return THREAD if page_number == 1 else f"{THREAD}/page-{page_number}"

def fetch(url, tries=3):
    for attempt in range(tries):
        try:
            response = requests.get(url, impersonate="chrome120", timeout=25, headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"})
            if response.status_code == 200:
                html = response.text
                if "article class=" not in html and "article.message" not in html:
                    print(f"Похоже, получена не страница форума (антибот?): {url}")
                    time.sleep(3 * (attempt + 1))
                    continue
                return html
            print(f"Status {response.status_code} on {url}")
        except Exception as error:
            print(f"Retry {attempt + 1}: {error}")
        time.sleep(3 * (attempt + 1))
    return None

def parse_posts(html, page):
    soup = BeautifulSoup(html, "lxml")
    posts = []
    for message in soup.select("article.message"):
        raw_id = message.get("id", "")
        id_match = re.search(r"(\d+)", raw_id)
        post_id = id_match.group(1) if id_match else f"p{page}_{len(posts)}"
        time_element = message.select_one("time")
        body = message.select_one(".bbWrapper")
        if not body: continue
        for quote in body.select("blockquote"): quote.decompose()
        posts.append({"post_id": post_id, "page": page, "author": message.get("data-author", ""),
                      "post_dt": time_element.get("datetime") or "" if time_element else "",
                      "text": body.get_text("\n", strip=True)})
    return posts

def total_pages(html):
    soup = BeautifulSoup(html, "lxml")
    nav = soup.select_one(".pageNav")
    if nav and nav.get("data-last"):
        try: return int(nav["data-last"])
        except: pass
    nums = [int(a.get_text(strip=True).replace(" ","")) for a in soup.select(".pageNav a") if a.get_text(strip=True).replace(" ","").isdigit()]
    return max(nums) if nums else 10451

def first_date(html):
    if not html: return ""
    t = BeautifulSoup(html, "lxml").select_one("article.message time")
    return (t.get("datetime") or "")[:10] if t else ""

def load_state():
    if not os.path.exists(STATE_FILE): return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f: return json.load(f)
    except: return {}

def snippet(text, pos, width=80):
    s, e = max(0, pos-15), min(len(text), pos+width)
    return "…" + re.sub(r"\s+", " ", text[s:e]).strip() + "…"

def resolve_event_date(text, start, end, post_dt):
    post_date = (post_dt or "")[:10]
    try: post_year = int(post_date[:4])
    except: post_year = date.today().year
    ls = text.rfind("\n", 0, start); ls = 0 if ls == -1 else ls + 1
    le = text.find("\n", end); le = len(text) if le == -1 else le
    line = text[ls:le]
    for scope in (line, text[max(0,start-40):min(len(text),end+40)]):
        m = DATE_RX.search(scope)
        if not m: continue
        try:
            d, mo, yr = int(m.group(1)), int(m.group(2)), m.group(3)
            if yr: yr = 2000+int(yr) if len(yr)==2 and int(yr)<50 else (1900+int(yr) if len(yr)==2 else int(yr))
            else: yr = post_year
            if 1<=d<=31 and 1<=mo<=12: return (f"{yr:04d}-{mo:02d}-{d:02d}", True)
        except: pass
    if "завтра" in line.lower():
        try: return (str(date.fromisoformat(post_date) + timedelta(days=1)), True)
        except: pass
    return post_date, False

def is_weight_of_size(text, start):
    return bool(re.search(r"навеск\w*[^0-9]{0,25}$", text[max(0,start-45):start].lower(), re.I))

def build_keyword_index(text):
    kw = [(m.start(), m.end(), "stock") for m in STOCK_KW_RX.finditer(text)]
    kw += [(m.start(), m.end(), "catch") for m in CATCH_KW_RX.finditer(text)]
    kw.sort(key=lambda x: x[0])
    return kw

def keyword_kind_for(text, keywords, start, end):
    lefts = [k for k in keywords if k[1] <= start]
    if lefts:
        _, ke, kind = lefts[-1]
        if start - ke <= 200 and not BAD_BETWEEN_RX.search(text[ke:start]): return kind
    rights = [k for k in keywords if k[0] >= end]
    if rights:
        ks, _, kind = rights[0]
        if ks - end <= 200 and not SENTENCE_RX.search(text[end:ks]) and not BAD_BETWEEN_RX.search(text[end:ks]): return kind
    return None

def find_stock_catch(text, post_dt):
    if not text: return []
    res, kg_spans, kw_idx = [], [], build_keyword_index(text)
    for m in KG_RX.finditer(text):
        s, e = m.span(); kg_spans.append((s,e))
        if is_weight_of_size(text, s): continue
        if OTHER_FISH.search(text[max(0,s-25):min(len(text),e+25)]): continue
        kind = keyword_kind_for(text, kw_idx, s, e)
        if not kind: continue
        try:
            v1 = float(m.group(1).replace(",","."))
            v2 = float(m.group(2).replace(",",".")) if m.group(2) else None
            val = (v1+v2)/2 if v2 else v1
            if (m.group(3) or "").lower().startswith("тон") or (m.group(3) or "").lower() == "т": val *= 1000
            kg = int(round(val))
        except: continue
        if kind=="stock" and not (30<=kg<=20000): continue
        if kind=="catch" and not (5<=kg<=20000): continue
        if kind=="stock":
            ctx = text[max(0,s-250):min(len(text),e+250)]
            if not FOREL_RX.search(ctx) and OTHER_FISH.search(ctx): continue
            ed, is_d = resolve_event_date(text, s, e, post_dt)
            if not is_d and FUTURE_RX.search(text[max(0,s-60):s].lower()): continue
        else: ed, is_d = (post_dt or "")[:10], False
        res.append({"kind":kind, "kg":kg, "event_date":ed, "is_dated":is_d, "quote":snippet(text,s), "pos":s})

    def overlaps(s,e): return any(not (e<ks or s>ke) for ks,ke in kg_spans)
    for pat, kind in [(STOCK_NOUNIT_RX,"stock"), (CATCH_NOUNIT_RX,"catch")]:
        for m in pat.finditer(text):
            s,e = m.span()
            if overlaps(s,e) or is_weight_of_size(text,s): continue
            try: kg = int(m.group(2))
            except: continue
            if kind=="stock" and not (30<=kg<=20000): continue
            if kind=="catch" and not (5<=kg<=20000): continue
            if kind=="stock":
                ctx = text[max(0,s-250):min(len(text),e+250)]
                if not FOREL_RX.search(ctx) and OTHER_FISH.search(ctx): continue
                ed, is_d = resolve_event_date(text, s, e, post_dt)
                if not is_d and FUTURE_RX.search(text[max(0,s-60):s].lower()): continue
            else: ed, is_d = (post_dt or "")[:10], False
            res.append({"kind":kind, "kg":kg, "event_date":ed, "is_dated":is_d, "quote":snippet(text,s), "pos":s})
    dated = [r for r in res if r["kind"]=="stock" and r["is_dated"]]
    if dated: res = [r for r in res if not (r["kind"]=="stock" and not r["is_dated"])]
    return res

def extract_location(text): m = LOCATION_RX.search(text); return m.group(0) if m else None
def extract_lure(text): m = LURE_RX.search(text); return m.group(0) if m else None
def extract_time(text):
    m = TIME_RX.search(text)
    if not m: return None
    if m.group(1): return f"{m.group(1)}–{m.group(2)}"
    if m.group(3): return f"после {m.group(3)}"
    if m.group(4): return f"до {m.group(4)}"
    return m.group(0)
def extract_depth(text):
    m = DEPTH_RX.search(text)
    if not m: return None
    if m.group(1): return f"{m.group(1)} м"
    if m.group(2): return f"{m.group(2)} м"
    return m.group(0)
def extract_catch(text):
    m = re.compile(r"(?:поймал[аи]?|выловил[аи]?|в улове|взял[аи]?|итого)\s*(?:(\d+)\s*(?:штук|экземпляр|рыб|форел|кг))|(?:(\d+)\s*форел)|(?:форел[ьи]\s*(\d+))", re.I).search(text)
    if m:
        for g in m.groups():
            if g: return g + " шт."
    return None

def load_weather():
    weather = {}
    today = date.today()
    try:
        r = requests.get("https://archive-api.open-meteo.com/v1/archive", params={
            "latitude":55.82, "longitude":37.33, "start_date":START_DATE,
            "end_date":str(today-timedelta(days=1)),
            "daily":"temperature_2m_mean,precipitation_sum,pressure_msl_mean", "timezone":"Europe/Moscow"}, timeout=60)
        d = r.json().get("daily") or {}
        for i, day in enumerate(d.get("time") or []):
            weather[day] = {
                "temp": (d.get("temperature_2m_mean") or [])[i] if i < len(d.get("temperature_2m_mean") or []) else None,
                "precip": (d.get("precipitation_sum") or [])[i] if i < len(d.get("precipitation_sum") or []) else None,
                "pressure": round((d.get("pressure_msl_mean") or [])[i]*0.75006, 1) if i < len(d.get("pressure_msl_mean") or []) and (d.get("pressure_msl_mean") or [])[i] else None
            }
    except Exception as e: print("Архив погоды:", e)
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude":55.82, "longitude":37.33,
            "start_date":str(today-timedelta(days=2)), "end_date":str(today+timedelta(days=2)),
            "hourly":"temperature_2m,precipitation,pressure_msl", "timezone":"Europe/Moscow"}, timeout=60)
        h = r.json().get("hourly") or {}
        buckets = defaultdict(list)
        for i, t in enumerate(h.get("time") or []): buckets[t[:10]].append(i)
        for day, idxs in buckets.items():
            rec = weather.get(day) or {}
            ts = [h["temperature_2m"][i] for i in idxs if i<len(h["temperature_2m"]) and h["temperature_2m"][i] is not None]
            ps = [h["precipitation"][i] for i in idxs if i<len(h["precipitation"]) and h["precipitation"][i] is not None]
            pr = [h["pressure_msl"][i] for i in idxs if i<len(h["pressure_msl"]) and h["pressure_msl"][i] is not None]
            if ts and rec.get("temp") is None: rec["temp"] = round(sum(ts)/len(ts), 1)
            if ps and rec.get("precip") is None: rec["precip"] = round(sum(ps), 1)
            if pr and rec.get("pressure") is None: rec["pressure"] = round(sum(pr)/len(pr)*0.75006, 1)
            weather[day] = rec
    except Exception as e: print("Прогноз погоды:", e)
    return weather

def main():
    os.makedirs(PAGES_DIR, exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    db.execute("CREATE TABLE IF NOT EXISTS posts (post_id TEXT PRIMARY KEY, page INT, author TEXT, post_dt TEXT, text TEXT)")
    state = load_state()
    print("Проверяю форум...")
    html1 = fetch(page_url(1))
    if not html1: raise SystemExit("Форум не ответил")
    last_page = total_pages(html1)
    print(f"Всего страниц: {last_page}")
    if not state.get("start_page"):
        print("Ищу 2024 год...")
        lo, hi = 1, last_page
        while lo < hi:
            mid = (lo+hi)//2
            fd = first_date(fetch(page_url(mid)))
            print(f" стр.{mid}: {fd or '?'}"); time.sleep(1.5)
            if not fd or fd >= START_DATE: hi = mid
            else: lo = mid + 1
        state.update({"start_page": max(1, lo-1), "cursor": last_page, "newest": last_page})
    start_page = state["start_page"]
    to_dl = []
    if last_page > state.get("newest", last_page):
        to_dl.extend(range(state["newest"]+1, last_page+1))
        state["newest"] = last_page
    cursor = state.get("cursor", last_page)
    added = []
    while len(added) < BATCH and cursor >= start_page:
        if not os.path.exists(f"{PAGES_DIR}/page_{cursor:06d}.json"): added.append(cursor)
        cursor -= 1
    state["cursor"] = cursor
    to_dl = sorted(set(to_dl + added + list(range(max(start_page, last_page-REFRESH_TAIL+1), last_page+1))))
    print(f"Загружаю {len(to_dl)} страниц...")
    for i, p in enumerate(to_dl):
        h = fetch(page_url(p))
        if h:
            posts = parse_posts(h, p)
            if not posts: print(f" стр.{p}: 0 постов — пропуск"); continue
            with open(f"{PAGES_DIR}/page_{p:06d}.json", "w", encoding="utf-8") as f: json.dump(posts, f, ensure_ascii=False)
            print(f" {i+1}/{len(to_dl)} стр.{p}: {len(posts)} постов")
        time.sleep(random.uniform(1.5, 2.5))
        if (i+1)%20==0:
            with open(STATE_FILE, "w", encoding="utf-8") as f: json.dump(state, f, ensure_ascii=False)
    for fn in os.listdir(PAGES_DIR):
        if not fn.endswith(".json"): continue
        try:
            with open(f"{PAGES_DIR}/{fn}", encoding="utf-8") as f: posts = json.load(f)
            for p in posts:
                dt = p.get("post_dt") or p.get("post_date") or ""
                db.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?)", (p.get("post_id",""), p.get("page",0), p.get("author",""), dt, p.get("text","")))
            db.commit()
        except Exception as e: print(f"Ошибка чтения {fn}: {e}")
    with open(STATE_FILE, "w", encoding="utf-8") as f: json.dump(state, f, ensure_ascii=False)
    build(db, state, last_page)
    db.close()
    print("Готово!")

def build(db, state, last_page):
    days = defaultdict(list)
    day_catch_counts = defaultdict(int)
    day_stock_cand = defaultdict(list)
    day_catch_cand = defaultdict(list)
    locations = []

    for pid, pg, auth, pdt, txt in db.execute("SELECT post_id, page, author, post_dt, text FROM posts"):
        pd = (pdt or "")[:10]
        url = f"{THREAD}/page-{pg}#post-{pid}" if pid else f"{THREAD}/page-{pg}"
        if pd and FOREL_RX.search(txt or "") and pd >= START_DATE:
            days[pd].append(url)
            if CATCH_REPORT_RX.search(txt or ""):
                day_catch_counts[pd] += 1
        if not pdt or not pd: continue
        if pd < BALANCE_START:
            try:
                if (date.fromisoformat(BALANCE_START) - date.fromisoformat(pd)).days > 10: continue
            except: continue
        if ADMIN_AUTHORS and (auth or "") not in ADMIN_AUTHORS:
            if FOREL_RX.search(txt or ""):
                loc, lur, tm, dep, cat = extract_location(txt), extract_lure(txt), extract_time(txt), extract_depth(txt), extract_catch(txt)
                if loc or lur or tm or dep or cat:
                    locations.append({"day":pd, "location":loc, "lure":lur, "time":tm, "depth":dep, "catch":cat, "url":url, "quote":snippet(txt,0,120)})
            continue
        try: evs = find_stock_catch(txt or "", pdt)
        except Exception as e: print(f"parse err: {e}"); continue
        for ev in evs:
            ed = ev["event_date"]
            if not ed or ed < BALANCE_START: continue
            if ed in IGNORE_STOCK_DAYS and ev["kind"]=="stock": continue
            rec = {"kg":ev["kg"], "url":url, "quote":(f"пост {pdt[5:10]} {pdt[11:16] if len(pdt)>=16 else ''} {ev['quote']}")[:150],
                   "dt":pdt, "is_fact":(pdt[:10]==ed), "pos":ev.get("pos",0)}
            if ev["kind"]=="stock": day_stock_cand[ed].append(rec)
            else: day_catch_cand[ed].append(rec)

    day_stock = {d: max((r for r in rs if r["is_fact"]) or rs, key=lambda r:(r["dt"],r.get("pos",0))) for d,rs in day_stock_cand.items()}
    day_catch = {d: max(rs, key=lambda r:(r["dt"],r.get("pos",0))) for d,rs in day_catch_cand.items()}
    day_events = {}
    for d,r in day_stock.items(): day_events.setdefault(d,{})["stock"] = r
    for d,r in day_catch.items(): day_events.setdefault(d,{})["catch"] = r

    weather = load_weather()
    monthly = defaultdict(list)
    for d, urls in days.items(): monthly[d[:7]].append(len(urls))

    # Аналитика давления
    p_groups = {"Низкое (<745)": [], "Норма (745-758)": [], "Высокое (>758)": []}
    p_catches = {"Низкое (<745)": [], "Норма (745-758)": [], "Высокое (>758)": []}
    for d in days:
        p = (weather.get(d) or {}).get("pressure")
        if p is None: continue
        grp = "Низкое (<745)" if p < 745 else ("Норма (745-758)" if p <= 758 else "Высокое (>758)")
        p_groups[grp].append(len(days[d]))
        p_catches[grp].append(day_catch_counts.get(d, 0))

    avg = lambda lst: round(sum(lst)/len(lst), 2) if lst else 0
    pressure_chart = {
        "labels": list(p_groups.keys()),
        "posts": [avg(p_groups[k]) for k in p_groups],
        "catches": [avg(p_catches[k]) for k in p_catches]
    }

    collected = len(glob.glob(f"{PAGES_DIR}/*.json"))
    needed = max(state.get("newest", last_page) - state.get("start_page", last_page) + 1, 1)
    stats = {
        "monthly": {m: avg(v) for m,v in sorted(monthly.items())},
        "pressure_chart": pressure_chart,
        "total_posts": sum(len(v) for v in days.values()),
        "active_days": len(days),
        "collected": collected, "need": needed, "pct": round(collected/needed*100, 1),
        "updated": str(date.today())
    }

    table = [{"day":d, "posts":len(days[d]), "temp":(weather.get(d) or {}).get("temp"),
              "pressure":(weather.get(d) or {}).get("pressure"), "precip":(weather.get(d) or {}).get("precip"),
              "links":days[d][:5]} for d in sorted(days, reverse=True)[:60]]

    bal_dates, bal_st, bal_ct, bal_rem = [], [], [], []
    tot_st = tot_ct = rem = 0
    last_st_day = None
    if day_events:
        cur = date.fromisoformat(min(day_events))
        end = date.fromisoformat(max(max(day_events), str(date.today())))
        while cur <= end:
            ds = str(cur)
            ev = day_events.get(ds, {})
            s = ev.get("stock",{}).get("kg",0)
            c = ev.get("catch",{}).get("kg",0)
            tot_st += s; tot_ct += c; rem = max(0, rem + s - c)
            if s: last_st_day = ds
            bal_dates.append(ds); bal_st.append(s); bal_ct.append(c); bal_rem.append(rem)
            cur += timedelta(days=1)

    rem = bal_rem[-1] if bal_rem else 0
    dss = (date.today() - date.fromisoformat(last_st_day)).days if last_st_day else None
    events = []
    for d in sorted(day_events, reverse=True)[:40]:
        for k in ("stock","catch"):
            if k in day_events[d]:
                e = day_events[d][k]
                events.append({"day":d, "type":"запуск" if k=="stock" else "вылов", "kg":e["kg"], "url":e["url"], "quote":e["quote"]})

    lure_st, time_st = defaultdict(int), defaultdict(int)
    for r in locations:
        if r["lure"]: lure_st[r["lure"]] += 1
        if r["time"]: time_st[r["time"]] += 1

    today_w = weather.get(str(date.today())) or {}
    payload = json.dumps({
        "stats": stats, "table": table,
        "balance": {"start":BALANCE_START, "total_stocked":tot_st, "total_caught":tot_ct, "remaining":rem,
                    "days_since_stock":dss, "series":{"dates":bal_dates,"stocked":bal_st,"caught":bal_ct,"remaining":bal_rem}, "events":events},
        "current_weather": {"temp":today_w.get("temp"), "pressure":today_w.get("pressure"), "precip":today_w.get("precip")},
        "locations": locations[:50],
        "lure_stats": dict(sorted(lure_st.items(), key=lambda x:-x[1])[:10]),
        "time_stats": dict(sorted(time_st.items(), key=lambda x:-x[1])[:10])
    }, ensure_ascii=False).replace("</", "<\\/")

    with open("index.html", "w", encoding="utf-8") as f: f.write(TEMPLATE.replace("__DATA__", payload))
    print(f"Сайт собран: остаток {rem} кг")

if __name__ == "__main__":
    main()
