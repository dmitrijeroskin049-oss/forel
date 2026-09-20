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

# Учитываем запуски и официальные выловы только от администрации.
ADMIN_AUTHORS = [
    "Александр SALMO",
    "Митяй-Митинооо",
]

# Игнорируем запуски в эти дни (4–8 сентября 2026).
IGNORE_STOCK_DAYS = {
    "2026-09-04",
    "2026-09-05",
    "2026-09-06",
    "2026-09-07",
    "2026-09-08",
}

BATCH = 150
REFRESH_TAIL = 15

# Рыба
FOREL_RX = re.compile(r"форел", re.I)
OTHER_FISH = re.compile(
    r"осет|осётр|карп|сом\b|щук|белуг|стерляд|карас|"
    r"окун|судак|сиг\b|налим|амур|толстолоб|линь",
    re.I,
)

# Дата
DATE_RX = re.compile(
    r"(?<!\d)(\d{1,2})\.(\d{2})(?:\.(\d{2,4}))?(?!\d)"
)

# Вес
KG_RX = re.compile(
    r"(\d+(?:[.,]\d+)?)"
    r"(?:\s*[-–—]\s*(\d+(?:[.,]\d+)?))?"
    r"\s*(кг|килограмм\w*|тонн\w*|т)\b",
    re.I,
)

# Запуск/вылов
STOCK_KW_RX = re.compile(
    r"запуск|запустили|зарыбление|зарыбили|"
    r"завезли|завоз|выпустили",
    re.I,
)
CATCH_KW_RX = re.compile(
    r"вылов\w*|итог дня|итого",
    re.I,
)
FUTURE_RX = re.compile(
    r"сделаем|будет|будут|планиру|анонс|"
    r"ожидается|собираемся|намечает",
    re.I,
)

# Без единиц
STOCK_NOUNIT_RX = re.compile(
    r"(запуск\w*|запустили|зарыбление\w*)"
    r"\s*[:\-–—]?\s*(\d{2,4})\b",
    re.I,
)
CATCH_NOUNIT_RX = re.compile(
    r"(вылов\w*|итог\w*)"
    r"\s*[:\-–—]?\s*(\d{1,4})\b",
    re.I,
)

# Навеска
NABECKA_RX = re.compile(r"навеск", re.I)

# Точки на водоёме (расширено)
LOCATION_RX = re.compile(
    r"основной водо[её]м|дальний угол|у плотин\w*|"
    r"у коряг\w*|у входа|у выхода|центр\w*|мелководь\w*|"
    r"глубок\w* участок|у берега|у причала|у мостка|"
    r"у дамбы|у стены|у кустов|у травы|у тростника|"
    r"у затопленн\w* дерев\w*|у ямы|у бровки|у сваи|"
    r"у трубы|у слива|у аэратора|у кормушк\w*|"
    r"у обрыва|у отмели|у переката|у залива|у бухты|"
    r"понтон\w*|пантон\w*|старый понтон|новый пантон|"
    r"новый понтон|старый пантон|переходной серый мост|"
    r"бабий угол|женский угол|пляж|под дубами|под ивой|"
    r"под администрацией|под стадионом|на запуске|"
    r"на спорт зоне|старая спорт зона",
    re.I,
)

# Приманки (расширено)
LURE_RX = re.compile(
    r"вертушк\w*|воблер\w*|резин\w*|мушк\w*|блесна|"
    r"черв\w*|опарыш\w*|мотыл\w*|пенопласт|тесто|сыр|"
    r"бойл\w*|поппер\w*|цикад\w*|колебалк\w*|вращалк\w*|"
    r"силикон\w*|твистер\w*|виброхвост\w*|рапал\w*|"
    r"минноу|кренк\w*|джерк\w*|спининг\w*|донк\w*|"
    r"фидер\w*|поплавочн\w*|мормышк\w*|балда|стример\w*|"
    r"нимф\w*|сухая мушка|мокрая мушка|личинк\w*|"
    r"мотылёк|ручейник|магот\w*|светонакоп\w*|"
    r"светонакопительный|стрейч|бобриный хвост|"
    r"пламп\w*|Биг Джуниор",
    re.I,
)

# Время суток
TIME_RX = re.compile(
    r"утро|вечер|ночь|рассвет|закат|день|"
    r"с (\d{1,2}) до (\d{1,2})|после (\d{1,2})|до (\d{1,2})",
    re.I,
)

# Горизонт воды
DEPTH_RX = re.compile(
    r"дно|полвод\w*|поверхност\w*|у дна|в полвод\w*|"
    r"верхний слой|средний слой|придонный слой|"
    r"у поверхност\w*|под берегом|на глубин[еу] (\d+)\s*м|"
    r"на (\d+)\s*м",
    re.I,
)

# Конец предложения
SENTENCE_RX = re.compile(r"[.!?…]")

# Запрещённые слова между ключевым словом и числом
BAD_BETWEEN_RX = re.compile(r"корм|прикорм|пеллет|смес", re.I)

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
/* --- сворачиваемые блоки --- */
details{margin:10px 0;border-radius:14px;border:1px solid #334155;overflow:hidden;background:#1e293b}
summary{cursor:pointer;padding:10px 14px;font-weight:800;color:#38bdf8;background:linear-gradient(90deg,#0f172a,#1e293b);list-style:none;user-select:none}
summary:hover{background:#334155}
summary::marker{display:none}
details>.card{margin:0;border-radius:0;border:none;padding:14px}
/* --- верхний бар --- */
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
<summary style="cursor:pointer; list-style:none; font-weight:800; font-size:1.2rem; color:#38bdf8; padding:8px 14px;">🎟 Условия рыбалки</summary>
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
  <p>
    🎣 Разрешено ловить на две снасти, не более двух крючков на каждой.<br>
    👩 Женщина и ребёнок до 13 лет ловят бесплатно на снасти рыбака.<br>
    🐟 Нормы вылова нет.<br>
    ✅ Спиннинг разрешён.<br>
    ⛔ Пеллетс и блёсны с тройниками запрещены.
  </p>
  <p>
    <b>Координаты:</b>
    <a href="https://yandex.ru/maps/?pt=37.322979,55.840619&z=15&l=map" target="_blank" rel="noopener">55.840619, 37.322979</a><br>
    <b>Телефон администрации:</b> <a href="tel:+79852620637">+7 985 262-06-37</a>
  </p>
  <div class="note">Проверено по сообщению администрации от 13.09.2026. Перед поездкой рекомендуется уточнить условия.</div>
</div>
</details>

<details open>
<summary style="cursor:pointer; list-style:none; font-weight:800; font-size:1.2rem; color:#38bdf8; padding:8px 14px;">🐟 Остаток форели в водоёме</summary>
<div class="card">
  <div class="big" id="rem">—</div>
  <div class="note">
    запущено <b id="st">0</b> кг − выловлено <b id="ct">0</b> кг • отсчёт с <span id="bs"></span><br>
    последний запуск: <span id="dsl">—</span> • обновлено <span id="upd2"></span>
  </div>
</div>
</details>

<details open>
<summary style="cursor:pointer; list-style:none; font-weight:800; font-size:1.2rem; color:#38bdf8; padding:8px 14px;">📈 Баланс</summary>
<div class="card" id="balbox"><canvas id="bal"></canvas></div>
</details>

<details open>
<summary style="cursor:pointer; list-style:none; font-weight:800; font-size:1.2rem; color:#38bdf8; padding:8px 14px;">📓 Журнал запусков и выловов</summary>
<div class="card"><table id="ev"></table></div>
</details>
<div class="note">Дата в таблице = дата события из текста, а не дата поста.</div>

<details open>
<summary style="cursor:pointer; list-style:none; font-weight:800; font-size:1.2rem; color:#38bdf8; padding:8px 14px;">📊 Активность обсуждений с 2024</summary>

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
<div class="note">Температура в таблице — средняя температура воздуха за сутки (по данным Open-Meteo).</div>
</details>

<details open>
<summary style="cursor:pointer; list-style:none; font-weight:800; font-size:1.2rem; color:#38bdf8; padding:8px 14px;">🎣 Перспективные точки и приманки</summary>

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

    /* --- верхняя строка: дата, время, текущая погода --- */
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
        if (D.stats.pressure && Object.keys(D.stats.pressure).length > 0) {
            new Chart(document.getElementById('p'), { type: 'bar', data: { labels: Object.keys(D.stats.pressure), datasets: [{ data: Object.values(D.stats.pressure), backgroundColor: '#4ade80' }] }, options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' } } } } });
        }
    }
    if (D.table && D.table.length > 0) {
        document.getElementById('t').innerHTML = '<tr><th>Дата</th><th>П</th><th>t° (средн.)</th><th>Давл</th><th>Осадки</th><th></th></tr>' + D.table.map(r => `<tr><td>${r.day}</td><td>${r.posts}</td><td>${r.temp ?? '—'}</td><td>${r.pressure ?? '—'}</td><td>${r.precip ?? '—'}</td><td>${(r.links || []).map((u, i) => `<a href="${u}" target="_blank" rel="noopener">#${i + 1}</a>`).join(' ')}</td></tr>`).join('');
    }
    if (D.locations && D.locations.length > 0) {
        document.getElementById('locs').innerHTML = '<tr><th>Дата</th><th>Точка</th><th>Приманка</th><th>Время</th><th>Горизонт</th><th>Улов</th><th>Цитата</th></tr>' + D.locations.map(r => `<tr><td>${r.day}</td><td>${r.location || '—'}</td><td>${r.lure || '—'}</td><td>${r.time || '—'}</td><td>${r.depth || '—'}</td><td>${r.catch || '—'}</td><td class="q"><a href="${r.url}" target="_blank" rel="noopener">${r.quote}</a></td></tr>`).join('');
    } else { document.getElementById('locs').innerHTML = '<tr><td class="note">Пока нет отчётов.</td></tr>'; }
    if (D.lure_stats) {
        new Chart(document.getElementById('lure'), {
            type: 'bar',
            data: {
                labels: Object.keys(D.lure_stats),
                datasets: [{
                    label: 'Успешных случаев',
                    data: Object.values(D.lure_stats),
                    backgroundColor: '#38bdf8'
                }]
            },
            options: {
                plugins: { legend: { display: false } },
                scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' } } }
            }
        });
    }
    if (D.time_stats) {
        new Chart(document.getElementById('time'), {
            type: 'bar',
            data: {
                labels: Object.keys(D.time_stats),
                datasets: [{
                    label: 'Успешных случаев',
                    data: Object.values(D.time_stats),
                    backgroundColor: '#4ade80'
                }]
            },
            options: {
                plugins: { legend: { display: false } },
                scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' } } }
            }
        });
    }

    /* --- сворачиваем/разворачиваем информационные блоки --- */
    document.querySelectorAll('.card').forEach(function(card){
        if (card.closest('details') || card.id === 'topbar') return;
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
    if page_number == 1:
        return THREAD
    return f"{THREAD}/page-{page_number}"

def fetch(url, tries=3):
    for attempt in range(tries):
        try:
            response = requests.get(
                url,
                impersonate="chrome120",
                timeout=25,
                headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
            )
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
        if not body:
            continue
        for quote in body.select("blockquote"):
            quote.decompose()
        posts.append({
            "post_id": post_id,
            "page": page,
            "author": message.get("data-author", ""),
            "post_dt": time_element.get("datetime") or "" if time_element else "",
            "text": body.get_text("\n", strip=True),
        })
    return posts

def total_pages(html):
    soup = BeautifulSoup(html, "lxml")
    navigation = soup.select_one(".pageNav")
    if navigation and navigation.get("data-last"):
        try:
            return int(navigation["data-last"])
        except (TypeError, ValueError):
            pass
    numbers = []
    for link in soup.select(".pageNav a"):
        text = link.get_text(strip=True).replace(" ", "")
        if text.isdigit():
            numbers.append(int(text))
    return max(numbers) if numbers else 10451

def first_date(html):
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    time_element = soup.select_one("article.message time")
    if not time_element:
        return ""
    return (time_element.get("datetime") or "")[:10]

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}

def snippet(text, position, width=80):
    start = max(0, position - 15)
    end = min(len(text), position + width)
    clean_text = re.sub(r"\s+", " ", text[start:end]).strip()
    return "…" + clean_text + "…"

def resolve_event_date(text, start, end, post_dt):
    post_date = (post_dt or "")[:10]
    try:
        post_year = int(post_date[:4])
    except (TypeError, ValueError):
        post_year = date.today().year

    line_start = text.rfind("\n", 0, start)
    line_start = 0 if line_start == -1 else line_start + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]

    scopes = (line, text[max(0, start - 40):min(len(text), end + 40)])
    for scope in scopes:
        match = DATE_RX.search(scope)
        if not match:
            continue
        try:
            day_number = int(match.group(1))
            month_number = int(match.group(2))
            raw_year = match.group(3)
            if raw_year:
                if len(raw_year) == 2:
                    short_year = int(raw_year)
                    year = 2000 + short_year if short_year < 50 else 1900 + short_year
                else:
                    year = int(raw_year)
            else:
                year = post_year
            if 1 <= day_number <= 31 and 1 <= month_number <= 12:
                return (f"{year:04d}-{month_number:02d}-{day_number:02d}", True)
        except (TypeError, ValueError):
            pass

    if "завтра" in line.lower():
        try:
            parsed_post_date = date.fromisoformat(post_date)
            return (str(parsed_post_date + timedelta(days=1)), True)
        except (TypeError, ValueError):
            pass

    return post_date, False

def is_weight_of_size(text, start):
    before = text[max(0, start - 45):start].lower()
    return bool(re.search(r"навеск\w*[^0-9]{0,25}$", before, re.I))

def build_keyword_index(text):
    keywords = []
    for match in STOCK_KW_RX.finditer(text):
        keywords.append((match.start(), match.end(), "stock"))
    for match in CATCH_KW_RX.finditer(text):
        keywords.append((match.start(), match.end(), "catch"))
    keywords.sort(key=lambda item: item[0])
    return keywords

def keyword_kind_for(text, keywords, start, end):
    lefts = [k for k in keywords if k[1] <= start]
    if lefts:
        kw_start, kw_end, kind = lefts[-1]
        between = text[kw_end:start]
        if start - kw_end <= 200 and not BAD_BETWEEN_RX.search(between):
            return kind

    rights = [k for k in keywords if k[0] >= end]
    if rights:
        kw_start, kw_end, kind = rights[0]
        between = text[end:kw_start]
        if (
            kw_start - end <= 200
            and not SENTENCE_RX.search(between)
            and not BAD_BETWEEN_RX.search(between)
        ):
            return kind

    return None

def find_stock_catch(text, post_dt):
    post_date = (post_dt or "")[:10]
    if not text:
        return []

    results = []
    kg_spans = []
    keywords = build_keyword_index(text)

    for match in KG_RX.finditer(text):
        start, end = match.span()
        kg_spans.append((start, end))

        if is_weight_of_size(text, start):
            continue

        fish_context = text[max(0, start - 25):min(len(text), end + 25)]
        if OTHER_FISH.search(fish_context):
            continue

        kind = keyword_kind_for(text, keywords, start, end)
        if kind is None:
            continue

        try:
            first_value = float(match.group(1).replace(",", "."))
            second_raw = match.group(2)
            if second_raw:
                second_value = float(second_raw.replace(",", "."))
                value = (first_value + second_value) / 2
            else:
                value = first_value
            unit = (match.group(3) or "").lower()
            if unit.startswith("тон") or unit == "т":
                value *= 1000
            kg = int(round(value))
        except (TypeError, ValueError):
            continue

        if kind == "stock" and not (30 <= kg <= 20000):
            continue
        if kind == "catch" and not (5 <= kg <= 20000):
            continue

        if kind == "stock":
            forel_context = text[max(0, start - 250):min(len(text), end + 250)]
            if not FOREL_RX.search(forel_context) and OTHER_FISH.search(forel_context):
                continue
            event_date, is_dated = resolve_event_date(text, start, end, post_dt)
            before = text[max(0, start - 60):start].lower()
            if not is_dated and FUTURE_RX.search(before):
                continue
        else:
            event_date = post_date
            is_dated = False

        results.append({
            "kind": kind,
            "kg": kg,
            "event_date": event_date,
            "is_dated": is_dated,
            "quote": snippet(text, start),
            "pos": start,
        })

    def overlaps_existing_kg(start, end):
        for kg_start, kg_end in kg_spans:
            if not (end < kg_start or start > kg_end):
                return True
        return False

    patterns = [(STOCK_NOUNIT_RX, "stock"), (CATCH_NOUNIT_RX, "catch")]

    for pattern, kind in patterns:
        for match in pattern.finditer(text):
            start, end = match.span()
            if overlaps_existing_kg(start, end):
                continue
            try:
                kg = int(match.group(2))
            except (TypeError, ValueError):
                continue

            if is_weight_of_size(text, start):
                continue

            fish_context = text[max(0, start - 25):min(len(text), end + 25)]
            if OTHER_FISH.search(fish_context):
                continue

            if kind == "stock" and not (30 <= kg <= 20000):
                continue
            if kind == "catch" and not (5 <= kg <= 20000):
                continue

            if kind == "stock":
                forel_context = text[max(0, start - 250):min(len(text), end + 250)]
                if not FOREL_RX.search(forel_context) and OTHER_FISH.search(forel_context):
                    continue
                event_date, is_dated = resolve_event_date(text, start, end, post_dt)
                before = text[max(0, start - 60):start].lower()
                if not is_dated and FUTURE_RX.search(before):
                    continue
            else:
                event_date = post_date
                is_dated = False

            results.append({
                "kind": kind,
                "kg": kg,
                "event_date": event_date,
                "is_dated": is_dated,
                "quote": snippet(text, start),
                "pos": start,
            })

    dated_stock = [r for r in results if r["kind"] == "stock" and r["is_dated"]]
    if dated_stock:
        results = [r for r in results if not (r["kind"] == "stock" and not r["is_dated"])]

    return results

def extract_location(text):
    match = LOCATION_RX.search(text)
    return match.group(0) if match else None

def extract_lure(text):
    match = LURE_RX.search(text)
    return match.group(0) if match else None

def extract_time(text):
    match = TIME_RX.search(text)
    if match:
        if match.group(1):  # "с X до Y"
            return f"{match.group(1)}–{match.group(2)}"
        elif match.group(3):  # "после X"
            return f"после {match.group(3)}"
        elif match.group(4):  # "до X"
            return f"до {match.group(4)}"
        else:
            return match.group(0)
    return None

def extract_depth(text):
    match = DEPTH_RX.search(text)
    if match:
        if match.group(1):  # "на глубине X м"
            return f"{match.group(1)} м"
        elif match.group(2):  # "на X м"
            return f"{match.group(2)} м"
        else:
            return match.group(0)
    return None

def extract_catch(text):
    """Ищет упоминания улова: '3 форели', '5 штук', 'два килограмма'."""
    catch_rx = re.compile(
        r"(?:поймал[аи]?|выловил[аи]?|в улове|уловил[аи]?|взял[аи]?|на улов|в сумме|итого)\s*"
        r"(?:(\d+)\s*(?:штук|экземпляр|рыб|форел|кг|килограмм))|"
        r"(?:(\d+)\s*форел)|"
        r"(?:форел[ьи]\s*(\d+))",
        re.I,
    )
    match = catch_rx.search(text)
    if match:
        for group in match.groups():
            if group:
                return group + " шт."
    return None

def load_weather():
    weather = {}
    today = date.today()

    try:
        response = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": 55.82,
                "longitude": 37.33,
                "start_date": START_DATE,
                "end_date": str(today - timedelta(days=1)),
                "daily": "temperature_2m_mean,precipitation_sum,pressure_msl_mean",
                "timezone": "Europe/Moscow",
            },
            timeout=60,
        )
        daily = response.json().get("daily") or {}
        temps = daily.get("temperature_2m_mean") or []
        precips = daily.get("precipitation_sum") or []
        pressures = daily.get("pressure_msl_mean") or []

        for index, day in enumerate(daily.get("time") or []):
            pressure_hpa = pressures[index] if index < len(pressures) else None
            weather[day] = {
                "temp": temps[index] if index < len(temps) else None,
                "precip": precips[index] if index < len(precips) else None,
                "pressure": (
                    round(pressure_hpa * 0.75006, 1)
                    if pressure_hpa is not None
                    else None
                ),
            }
    except Exception as error:
        print("Архив погоды недоступен:", error)

    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 55.82,
                "longitude": 37.33,
                "start_date": str(today - timedelta(days=2)),
                "end_date": str(today + timedelta(days=2)),
                "hourly": "temperature_2m,precipitation,pressure_msl",
                "timezone": "Europe/Moscow",
            },
            timeout=60,
        )
        hourly = response.json().get("hourly") or {}
        times = hourly.get("time") or []
        temps = hourly.get("temperature_2m") or []
        precips = hourly.get("precipitation") or []
        pressures = hourly.get("pressure_msl") or []

        buckets = defaultdict(list)
        for index, stamp in enumerate(times):
            buckets[stamp[:10]].append(index)

        for day, indexes in buckets.items():
            day_temps = [temps[i] for i in indexes if i < len(temps) and temps[i] is not None]
            day_precips = [precips[i] for i in indexes if i < len(precips) and precips[i] is not None]
            day_pressures = [pressures[i] for i in indexes if i < len(pressures) and pressures[i] is not None]

            record = weather.get(day) or {}
            if day_temps and record.get("temp") is None:
                record["temp"] = round(sum(day_temps) / len(day_temps), 1)
            if day_precips and record.get("precip") is None:
                record["precip"] = round(sum(day_precips), 1)
            if day_pressures and record.get("pressure") is None:
                record["pressure"] = round(sum(day_pressures) / len(day_pressures) * 0.75006, 1)
            weather[day] = record
    except Exception as error:
        print("Свежая погода недоступна:", error)

    return weather

def main():
    os.makedirs(PAGES_DIR, exist_ok=True)
    database = sqlite3.connect(DB_FILE)

    database.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            post_id TEXT PRIMARY KEY,
            page INT,
            author TEXT,
            post_dt TEXT,
            text TEXT
        )
        """
    )

    state = load_state()
    print("Проверяю форум...")

    first_page_html = fetch(page_url(1))
    if not first_page_html:
        raise SystemExit("Форум не ответил")

    last_page = total_pages(first_page_html)
    print(f"Всего страниц: {last_page}")

    if not state.get("start_page"):
        print("Ищу 2024 год...")
        low = 1
        high = last_page
        while low < high:
            middle = (low + high) // 2
            html = fetch(page_url(middle))
            found_date = first_date(html) if html else ""
            print(f" стр.{middle}: {found_date or '?'}")
            time.sleep(1.5)
            if not found_date or found_date >= START_DATE:
                high = middle
            else:
                low = middle + 1
        state["start_page"] = max(1, low - 1)
        state["cursor"] = last_page
        state["newest"] = last_page

    start_page = state["start_page"]
    pages_to_download = []

    if last_page > state.get("newest", last_page):
        for page_number in range(state["newest"] + 1, last_page + 1):
            pages_to_download.append(page_number)
        state["newest"] = last_page

    cursor = state.get("cursor", last_page)
    added_pages = []
    while len(added_pages) < BATCH and cursor >= start_page:
        filename = f"{PAGES_DIR}/page_{cursor:06d}.json"
        if not os.path.exists(filename):
            added_pages.append(cursor)
        cursor -= 1
    state["cursor"] = cursor

    tail_pages = list(range(max(start_page, last_page - REFRESH_TAIL + 1), last_page + 1))
    pages_to_download = sorted(set(pages_to_download + added_pages + tail_pages))

    print(f"Загружаю {len(pages_to_download)} страниц...")

    for index, page_number in enumerate(pages_to_download):
        html = fetch(page_url(page_number))
        if html:
            posts = parse_posts(html, page_number)
            if not posts:
                print(f" стр.{page_number}: 0 постов — пропуск (сбой или антибот)")
                continue

            filename = f"{PAGES_DIR}/page_{page_number:06d}.json"
            with open(filename, "w", encoding="utf-8") as file:
                json.dump(posts, file, ensure_ascii=False)

            print(f" {index + 1}/{len(pages_to_download)} стр.{page_number}: {len(posts)} постов")

        time.sleep(random.uniform(1.5, 2.5))

        if (index + 1) % 20 == 0:
            with open(STATE_FILE, "w", encoding="utf-8") as file:
                json.dump(state, file, ensure_ascii=False)

    for filename in os.listdir(PAGES_DIR):
        if not filename.endswith(".json"):
            continue
        try:
            with open(f"{PAGES_DIR}/{filename}", encoding="utf-8") as file:
                posts = json.load(file)

            for post in posts:
                post_datetime = post.get("post_dt") or post.get("post_date") or ""
                database.execute(
                    """
                    INSERT OR REPLACE INTO posts
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        post.get("post_id", ""),
                        post.get("page", 0),
                        post.get("author", ""),
                        post_datetime,
                        post.get("text", ""),
                    ),
                )
            database.commit()
        except Exception as error:
            print(f"Не удалось прочитать {filename}: {error}")

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False)

    build(database, state, last_page)
    database.close()
    print("Готово!")

def build(database, state, last_page):
    days = defaultdict(list)
    day_stock_candidates = defaultdict(list)
    day_catch_candidates = defaultdict(list)
    locations = []

    query = "SELECT post_id, page, author, post_dt, text FROM posts"

    for post_id, page_number, author, post_datetime, text in database.execute(query):
        post_day = (post_datetime or "")[:10]
        post_url = f"{THREAD}/page-{page_number}#post-{post_id}" if post_id else f"{THREAD}/page-{page_number}"

        if post_day and FOREL_RX.search(text or "") and post_day >= START_DATE:
            days[post_day].append(post_url)

        if not post_datetime or not post_day:
            continue

        if post_day < BALANCE_START:
            try:
                distance = (date.fromisoformat(BALANCE_START) - date.fromisoformat(post_day)).days
                if distance > 10:
                    continue
            except (TypeError, ValueError):
                continue

        if ADMIN_AUTHORS and (author or "") not in ADMIN_AUTHORS:
            # Для аналитики точек и приманок берём ВСЕ посты про форель.
            if FOREL_RX.search(text or ""):
                location = extract_location(text)
                lure = extract_lure(text)
                time_of_day = extract_time(text)
                depth = extract_depth(text)
                catch = extract_catch(text)
                if location or lure or time_of_day or depth or catch:
                    locations.append({
                        "day": post_day,
                        "location": location,
                        "lure": lure,
                        "time": time_of_day,
                        "depth": depth,
                        "catch": catch,
                        "url": post_url,
                        "quote": snippet(text, 0, 120),
                    })
            continue

        try:
            events = find_stock_catch(text or "", post_datetime)
        except Exception as error:
            print(f"parse err: {error}")
            continue

        for event in events:
            event_day = event["event_date"]
            if not event_day or event_day < BALANCE_START:
                continue
            if event_day in IGNORE_STOCK_DAYS and event["kind"] == "stock":
                continue

            post_time = post_datetime[11:16] if len(post_datetime) >= 16 else ""
            short_post_day = post_datetime[5:10] if len(post_datetime) >= 10 else ""

            record = {
                "kg": event["kg"],
                "url": post_url,
                "quote": (f"пост {short_post_day} {post_time} {event['quote']}")[:150],
                "dt": post_datetime,
                "is_fact": (post_datetime[:10] == event_day),
                "pos": event.get("pos", 0),
            }

            if event["kind"] == "stock":
                day_stock_candidates[event_day].append(record)
            else:
                day_catch_candidates[event_day].append(record)

    day_stock = {}
    for event_day, records in day_stock_candidates.items():
        factual_records = [r for r in records if r["is_fact"]]
        pool = factual_records or records
        day_stock[event_day] = max(pool, key=lambda r: (r["dt"], r.get("pos", 0)))

    day_catch = {}
    for event_day, records in day_catch_candidates.items():
        day_catch[event_day] = max(records, key=lambda r: (r["dt"], r.get("pos", 0)))

    day_events = {}
    for event_day, record in day_stock.items():
        day_events.setdefault(event_day, {})["stock"] = record
    for event_day, record in day_catch.items():
        day_events.setdefault(event_day, {})["catch"] = record

    weather = load_weather()

    monthly_activity = defaultdict(list)
    pressure_activity = {"<745": [], "745-760": [], ">760": []}

    for day_value, urls in days.items():
        monthly_activity[day_value[:7]].append(len(urls))
        pressure = (weather.get(day_value) or {}).get("pressure")
        if pressure is not None:
            if pressure < 745:
                group = "<745"
            elif pressure <= 760:
                group = "745-760"
            else:
                group = ">760"
            pressure_activity[group].append(len(urls))

    def average(values):
        return round(sum(values) / len(values), 2) if values else 0

    collected_pages = len(glob.glob(f"{PAGES_DIR}/*.json"))
    needed_pages = state.get("newest", last_page) - state.get("start_page", last_page) + 1

    statistics = {
        "monthly": {month: average(vals) for month, vals in sorted(monthly_activity.items())},
        "pressure": {group: average(vals) for group, vals in pressure_activity.items()},
        "total_posts": sum(len(vals) for vals in days.values()),
        "active_days": len(days),
        "collected": collected_pages,
        "need": max(needed_pages, 1),
        "pct": round(collected_pages / max(needed_pages, 1) * 100, 1),
        "updated": str(date.today()),
    }

    table = []
    for day_value in sorted(days, reverse=True)[:60]:
        w = weather.get(day_value) or {}
        table.append({
            "day": day_value,
            "posts": len(days[day_value]),
            "temp": w.get("temp"),
            "pressure": w.get("pressure"),
            "precip": w.get("precip"),
            "links": days[day_value][:5],
        })

    balance_dates, balance_stocked, balance_caught, balance_remaining = [], [], [], []
    total_stocked = total_caught = 0
    last_stock_day = None

    if day_events:
        first_event_day = min(day_events)
        last_event_day = max(max(day_events), str(date.today()))
        current_day = date.fromisoformat(first_event_day)
        end_day = date.fromisoformat(last_event_day)
        remaining = 0

        while current_day <= end_day:
            day_string = str(current_day)
            event = day_events.get(day_string, {})
            stocked = event.get("stock", {}).get("kg", 0)
            caught = event.get("catch", {}).get("kg", 0)

            total_stocked += stocked
            total_caught += caught
            remaining = max(0, remaining + stocked - caught)
            if stocked:
                last_stock_day = day_string

            balance_dates.append(day_string)
            balance_stocked.append(stocked)
            balance_caught.append(caught)
            balance_remaining.append(remaining)
            current_day += timedelta(days=1)

    remaining = balance_remaining[-1] if balance_remaining else 0
    days_since_stock = (date.today() - date.fromisoformat(last_stock_day)).days if last_stock_day else None

    events = []
    for event_day in sorted(day_events, reverse=True)[:40]:
        for kind in ("stock", "catch"):
            if kind in day_events[event_day]:
                e = day_events[event_day][kind]
                events.append({
                    "day": event_day,
                    "type": "запуск" if kind == "stock" else "вылов",
                    "kg": e["kg"],
                    "url": e["url"],
                    "quote": e["quote"],
                })

    # Статистика приманок и времени суток.
    lure_stats = defaultdict(int)
    time_stats = defaultdict(int)

    for report in locations:
        if report["lure"]:
            lure_stats[report["lure"]] += 1
        if report["time"]:
            time_stats[report["time"]] += 1

    # Текущая погода из загруженных данных для верхней строки
    today_str = str(date.today())
    current_weather = weather.get(today_str) or {}

    balance = {
        "start": BALANCE_START,
        "total_stocked": total_stocked,
        "total_caught": total_caught,
        "remaining": remaining,
        "days_since_stock": days_since_stock,
        "series": {
            "dates": balance_dates,
            "stocked": balance_stocked,
            "caught": balance_caught,
            "remaining": balance_remaining,
        },
        "events": events,
    }

    payload = json.dumps(
        {
            "stats": statistics,
            "table": table,
            "balance": balance,
            "current_weather": {
                "temp": current_weather.get("temp"),
                "pressure": current_weather.get("pressure"),
                "precip": current_weather.get("precip"),
            },
            "locations": locations[:50],
            "lure_stats": dict(sorted(lure_stats.items(), key=lambda item: -item[1])[:10]),
            "time_stats": dict(sorted(time_stats.items(), key=lambda item: -item[1])[:10]),
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")

    final_html = TEMPLATE.replace("__DATA__", payload)

    with open("index.html", "w", encoding="utf-8") as file:
        file.write(final_html)

    print(f"Сайт собран: остаток {remaining} кг")

if __name__ == "__main__":
    main()
