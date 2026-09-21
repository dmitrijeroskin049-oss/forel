Да, конечно. Диагностику пропускаем — просто **полностью заменим 2 файла** на заведомо рабочие версии. С телефона это делается через сайт GitHub, минут за 10.

---

## Шаг 1. Заменить main.py

1. Откройте **github.com** в браузере телефона → ваш репозиторий.
2. Нажмите на файл **main.py** (или как называется ваш скрипт).
3. Нажмите иконку **карандаша** ✏️ (если её не видно — нажмите ⋯ → Edit file).
4. Нажмите в текст, выделите всё (долгое нажатие → «Выделить всё») и **удалите**.
5. В этом чате нажмите кнопку **копирования** на блоке кода ниже и **вставьте** в файл.
6. Нажмите зелёную кнопку **Commit changes** (дважды).

```python
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
REPORT_START = "2026-09-01"

# ============ LLM (опционально) ============
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_API_URL = os.environ.get("LLM_API_URL", "https://openrouter.ai/api/v1/chat/completions").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini").strip()
LLM_MAX_POSTS = int(os.environ.get("LLM_MAX_POSTS", "40"))

if LLM_API_KEY:
    print(f"LLM: ключ найден ({LLM_API_KEY[:6]}...{LLM_API_KEY[-4:]}), модель {LLM_MODEL}")
else:
    print("LLM: ключ НЕ задан — анализ времени клёва будет пропущен (это не ошибка).")

LLM_PROMPT = """Ты анализируешь отчёт рыбака с платного форелевого пруда в Красногорске.
Определи по смыслу текста, в какие периоды суток форель КЛЕВАЛА, а в какие НЕ клевала.
Периоды строго из списка: "утро", "день", "вечер", "ночь".
Учитывай отрицания: «утром тишина, зато вечером раздача» = утро НЕ клевало, вечер клевало.
Если рыбак пишет про будущее, планы или пересказывает чужие слова — не учитывай.
Ответь СТРОГО одним JSON без пояснений и без markdown:
{"bite": ["вечер"], "no_bite": ["утро"], "confident": true}
Если из текста нельзя ничего понять про время клёва:
{"bite": [], "no_bite": [], "confident": false}

Текст отчёта:
"""

ADMIN_AUTHORS = [
    "Александр SALMO",
    "Митяй-Митинооо",
]

IGNORE_STOCK_DAYS = {
    "2026-09-04",
    "2026-09-05",
    "2026-09-06",
    "2026-09-07",
    "2026-09-08",
}

BATCH = 150
REFRESH_TAIL = 15

FOREL_RX = re.compile(r"форел", re.I)
OTHER_FISH = re.compile(
    r"осет|осётр|карп|сом\b|щук|белуг|стерляд|карас|"
    r"окун|судак|сиг\b|налим|амур|толстолоб|линь",
    re.I,
)

DATE_RX = re.compile(r"(?<!\d)(\d{1,2})\.(\d{2})(?:\.(\d{2,4}))?(?!\d)")

KG_RX = re.compile(
    r"(\d+(?:[.,]\d+)?)"
    r"(?:\s*[-–—]\s*(\d+(?:[.,]\d+)?))?"
    r"\s*(кг|килограмм\w*|тонн\w*|т)\b",
    re.I,
)

STOCK_KW_RX = re.compile(
    r"запуск|запустили|зарыбление|зарыбили|завезли|завоз|выпустили",
    re.I,
)
CATCH_KW_RX = re.compile(r"вылов\w*|итог дня|итого", re.I)
FUTURE_RX = re.compile(
    r"сделаем|будет|будут|планиру|анонс|ожидается|собираемся|намечает",
    re.I,
)

STOCK_NOUNIT_RX = re.compile(
    r"(запуск\w*|запустили|зарыбление\w*)\s*[:\-–—]?\s*(\d{2,4})\b",
    re.I,
)
CATCH_NOUNIT_RX = re.compile(
    r"(вылов\w*|итог\w*)\s*[:\-–—]?\s*(\d{1,4})\b",
    re.I,
)

NABECKA_RX = re.compile(r"навеск", re.I)

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

LURE_RX = re.compile(
    r"вертушк\w*|воблер\w*|резин\w*|мушк\w*|блесна|"
    r"черв\w*|опарыш\w*|мотыл\w*|пенопласт|тесто|сыр|"
    r"бойл\w*|поппер\w*|цикад\w*|колебалк\w*|вращалк\w*|"
    r"силикон\w*|твистер\w*|виброхвост\w*|рапал\w*|"
    r"минноу|кренк\w*|джерк\w*|"
    r"мормышк\w*|балда|стример\w*|"
    r"нимф\w*|сухая мушка|мокрая мушка|личинк\w*|"
    r"ручейник|магот\w*|светонакоп\w*|"
    r"стрейч|бобриный хвост|"
    r"пламп\w*|Биг Джуниор|паста|креветк\w*|кукуруз\w*",
    re.I,
)

SUCCESS_RX = re.compile(
    r"поймал|словил|взял|вытащил|выловил|отловил|"
    r"клевал|клюнул|клёв был|отлично отловил|в улове|"
    r"на счету|результат|доловил|реализовал",
    re.I,
)

TIME_HINT_RX = re.compile(
    r"утр|днём|днем|вечер|ноч|рассвет|закат|обед|"
    r"клев|клёв|с \d{1,2} до \d{1,2}|после \d{1,2}",
    re.I,
)

SENTENCE_RX = re.compile(r"[.!?…]")
BAD_BETWEEN_RX = re.compile(r"корм|прикорм|пеллет|смес", re.I)

WIND_DIRS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]

MOON_ORDER = [
    "🌑 новолуние", "🌒 растущий серп", "🌓 первая четверть", "🌔 растущая",
    "🌕 полнолуние", "🌖 убывающая", "🌗 последняя четверть", "🌘 убывающий серп",
]

TIME_PERIODS = ["утро", "день", "вечер", "ночь"]

TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Форель Красногорск</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
html,body{height:auto;min-height:100%}
body{font-family:system-ui,-apple-system,sans-serif;margin:0 auto;padding:12px;background:#0f172a;color:#e2e8f0;max-width:860px;overflow-x:hidden;overflow-y:auto;-webkit-overflow-scrolling:touch}
h1{font-size:1.4rem;background:linear-gradient(90deg,#38bdf8,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
h3{font-size:1rem;margin:8px 0}
.card{background:#1e293b;border-radius:0;padding:14px;margin:0}
.big{font-size:1.8rem;font-weight:800;color:#fbbf24}
table{width:100%;border-collapse:collapse;font-size:.78rem;min-width:520px}
td,th{padding:6px 4px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}
a{color:#7dd3fc;text-decoration:none}
a:hover{text-decoration:underline}
.note{font-size:.8rem;color:#94a3b8}
.q{color:#94a3b8;font-size:.75rem}
.scrollx{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}
.scrollx table.narrow{min-width:0}
.chartbox{position:relative;height:260px;width:100%}
details{margin:10px 0;border-radius:14px;border:1px solid #334155;overflow:hidden;background:#1e293b}
summary{cursor:pointer;padding:12px 14px;font-weight:800;color:#38bdf8;background:linear-gradient(90deg,#0f172a,#1e293b);list-style:none;user-select:none;font-size:1rem}
summary:hover{background:#334155}
summary::marker,summary::-webkit-details-marker{display:none}
summary::after{content:"▾";float:right;color:#64748b;transition:transform .2s}
details:not([open])>summary::after{transform:rotate(-90deg)}
#topbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;font-size:.9rem;background:#1e293b;border-radius:14px;padding:12px 14px;margin:10px 0}
#topbar b{color:#fbbf24}
@media (max-width:520px){
  body{padding:8px}
  .big{font-size:1.4rem}
  table{font-size:.7rem}
  .chartbox{height:220px}
  #topbar{font-size:.8rem;gap:8px}
}
</style>
</head>
<body>
<h1>🎣 Форель в Красногорске</h1>

<div id="topbar">
  <span><b>📅</b> <span id="curDate">—</span></span>
  <span><b>⏰</b> <span id="curTime">—</span></span>
  <span><b>🌤</b> <span id="curTemp">—</span>°C • <span id="curPress">—</span> мм рт.ст. • осадки <span id="curPrecip">—</span> мм</span>
  <span><b>🌙</b> <span id="curMoon">—</span></span>
</div>

<details open data-key="terms">
<summary>🎟 Условия рыбалки</summary>
<div class="card">
  <div class="scrollx"><table class="narrow">
    <tr><td>06:00–19:00</td><td><b>4000 ₽</b></td></tr>
    <tr><td>12:00–19:00</td><td><b>2200 ₽</b></td></tr>
    <tr><td>18:00–06:00</td><td><b>4000 ₽</b></td></tr>
    <tr><td>Сутки</td><td><b>5000 ₽</b></td></tr>
    <tr><td>Приоритетный час</td><td><b>300 ₽</b></td></tr>
    <tr><td>Дополнительная снасть</td><td><b>500 ₽</b></td></tr>
  </table></div>
  <p>
    🎣 Две снасти, не более двух крючков на каждой.<br>
    👩 Женщина и ребёнок до 13 лет — бесплатно на снасти рыбака.<br>
    🐟 Нормы вылова нет. ✅ Спиннинг разрешён.<br>
    ⛔ Пеллетс и блёсны с тройниками запрещены.
  </p>
  <p>
    <b>Координаты:</b>
    <a href="https://yandex.ru/maps/?pt=37.322979,55.840619&z=15&l=map" target="_blank" rel="noopener">55.840619, 37.322979</a><br>
    <b>Телефон:</b> <a href="tel:+79852620637">+7 985 262-06-37</a>
  </p>
  <div class="note">⚠️ Блок статический, обновляется вручную. Актуально на 13.09.2026. Перед поездкой уточняйте по телефону.</div>
</div>
</details>

<details open data-key="rem">
<summary>🐟 Остаток форели в водоёме</summary>
<div class="card">
  <div class="big" id="rem">—</div>
  <div class="note">
    запущено <b id="st">0</b> кг − выловлено <b id="ct">0</b> кг • отсчёт с <span id="bs"></span><br>
    последний запуск: <span id="dsl">—</span> • обновлено <span id="upd2"></span>
  </div>
</div>
</details>

<details open data-key="bal">
<summary>📈 Баланс</summary>
<div class="card" id="balbox"><div class="chartbox"><canvas id="bal"></canvas></div></div>
</details>

<details open data-key="journal">
<summary>📓 Журнал запусков и выловов</summary>
<div class="card"><div class="scrollx"><table id="ev"></table></div>
<div class="note">Дата = дата события из текста, а не дата поста.</div></div>
</details>

<details data-key="llmtime">
<summary>⏰ Когда клюёт (анализ отчётов LLM)</summary>
<div class="card">
  <div class="note" id="llmnote"></div>
  <div class="chartbox"><canvas id="llmchart"></canvas></div>
  <div class="note">Каждый отчёт рыбака прочитан языковой моделью: «утром тишина, вечером раздача»
  учитывается корректно — утро попадает в «не клевало», вечер в «клевало».</div>
</div>
</details>

<details data-key="moon">
<summary>🌙 Луна и клёв</summary>
<div class="card">
  <div class="chartbox"><canvas id="moonchart"></canvas></div>
  <div class="note">Средняя активность отчётов (постов про форель в день) в каждой фазе луны с 2024 года.
  Это косвенный показатель: больше отчётов ≈ активнее ловля.</div>
</div>
</details>

<details data-key="act">
<summary>📊 Активность обсуждений с 2024</summary>
<div class="card">
  <div class="note" id="prog"></div>
  <div class="big" style="color:#38bdf8" id="total">0</div>
  <div class="note">постов про форель за <span id="days">0</span> активных дней</div>
  <h3>По месяцам (постов/день)</h3>
  <div class="chartbox"><canvas id="m"></canvas></div>
  <h3>Клёв vs Атмосферное давление</h3>
  <div class="chartbox"><canvas id="p"></canvas></div>
  <div class="note" id="pnote">Среднее количество отчётов в день при разном давлении.</div>
  <h3>Последние активные дни</h3>
  <div class="scrollx"><table id="t"></table></div>
  <div class="note">t°день = максимум, t°ночь = минимум за сутки. Данные Open-Meteo, луна — астрономический расчёт.</div>
</div>
</details>

<details data-key="reports">
<summary>🗺 Где и на что ловят (отчёты с 01.09.2026)</summary>
<div class="card">
  <h3>Сводка по точкам</h3>
  <div class="scrollx"><table id="toploc" class="narrow"></table></div>
  <h3>Сводка по приманкам</h3>
  <div class="chartbox"><canvas id="lure"></canvas></div>
  <h3>Отчёты рыбаков</h3>
  <div class="scrollx"><table id="reports"></table></div>
  <div class="note">⚠️ Точки и приманки извлекаются по ключевым словам — открывайте ссылку и читайте пост целиком.
  🐟 = в тексте есть явные слова про улов.</div>
</div>
</details>

<script type="application/json" id="sitedata">__DATA__</script>
<script>
let D = {};
try { D = JSON.parse(document.getElementById('sitedata').textContent); }
catch (e) { console.error('Данные битые:', e); }
try {
    document.querySelectorAll('details[data-key]').forEach(d => {
        const k = 'fold_' + d.dataset.key;
        const saved = localStorage.getItem(k);
        if (saved === '1') d.open = true;
        if (saved === '0') d.open = false;
        d.addEventListener('toggle', () => localStorage.setItem(k, d.open ? '1' : '0'));
    });

    const CHOPT = { responsive: true, maintainAspectRatio: false };

    function renderTop() {
        const now = new Date();
        document.getElementById('curDate').textContent = now.toLocaleDateString('ru-RU', {day:'numeric', month:'long', year:'numeric'});
        document.getElementById('curTime').textContent = now.toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit'});
        const cw = (D.current_weather || {});
        document.getElementById('curTemp').textContent = (cw.temp ?? '—');
        document.getElementById('curPress').textContent = (cw.pressure ?? '—');
        document.getElementById('curPrecip').textContent = (cw.precip ?? '—');
        document.getElementById('curMoon').textContent = (cw.moon ?? '—');
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
            options: { ...CHOPT, plugins: { legend: { labels: { color: '#e2e8f0', boxWidth: 12 } } }, scales: { x: { ticks: { maxTicksLimit: 8, color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' } } } }
        });
    } else { document.getElementById('balbox').innerHTML = '<div class="note">Отчёты появятся начиная с ' + (B.start || '2026-09-01') + '.</div>'; }

    if (B.events && B.events.length > 0) {
        document.getElementById('ev').innerHTML = '<tr><th>Дата</th><th></th><th>кг</th><th>Цитата</th></tr>' + B.events.map(e => `<tr><td>${e.day}</td><td>${e.type === 'запуск' ? '🟢' : '🔴'}</td><td><b>${e.kg}</b></td><td class="q"><a href="${e.url}" target="_blank" rel="noopener">${e.quote}</a></td></tr>`).join('');
    } else { document.getElementById('ev').innerHTML = '<tr><td class="note">Пока нет записей.</td></tr>'; }

    const LT = D.llm_time || {};
    if (LT.enabled && LT.labels && LT.labels.length > 0 && (LT.analyzed || 0) > 0) {
        document.getElementById('llmnote').textContent = 'Проанализировано отчётов: ' + (LT.analyzed || 0) + ' (модель: ' + (LT.model || '?') + ')';
        new Chart(document.getElementById('llmchart'), {
            type: 'bar',
            data: {
                labels: LT.labels,
                datasets: [
                    { label: 'Клевало', data: LT.bite, backgroundColor: '#4ade80' },
                    { label: 'Не клевало', data: LT.no_bite, backgroundColor: '#f87171' }
                ]
            },
            options: { ...CHOPT, plugins: { legend: { labels: { color: '#e2e8f0', boxWidth: 12 } } }, scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' }, beginAtZero: true } } }
        });
    } else {
        document.getElementById('llmnote').textContent = LT.enabled
            ? 'Пока нет проанализированных отчётов — данные появятся после следующих запусков сборки.'
            : 'LLM-анализ отключён. Задайте LLM_API_KEY в секретах и перезапустите сборку.';
        document.getElementById('llmchart').parentNode.style.display = 'none';
    }

    const M = D.moon_stats || {};
    if (M.labels && M.labels.length > 0) {
        new Chart(document.getElementById('moonchart'), {
            type: 'bar',
            data: { labels: M.labels, datasets: [{ label: 'Постов/день', data: M.values, backgroundColor: '#a78bfa' }] },
            options: { ...CHOPT, plugins: { legend: { display: false }, tooltip: { callbacks: { afterLabel: (ctx) => 'дней в выборке: ' + (M.days[ctx.dataIndex] || 0) } } }, scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' }, beginAtZero: true } } }
        });
    }

    if (D.stats) {
        document.getElementById('prog').textContent = 'Собрано страниц: ' + (D.stats.collected || 0) + ' из ~' + (D.stats.need || 0) + ' (' + (D.stats.pct || 0) + '%)';
        document.getElementById('total').textContent = D.stats.total_posts || 0;
        document.getElementById('days').textContent = D.stats.active_days || 0;
        if (D.stats.monthly && Object.keys(D.stats.monthly).length > 0) {
            new Chart(document.getElementById('m'), { type: 'bar', data: { labels: Object.keys(D.stats.monthly), datasets: [{ data: Object.values(D.stats.monthly), backgroundColor: '#38bdf8' }] }, options: { ...CHOPT, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#94a3b8', maxTicksLimit: 12 } }, y: { ticks: { color: '#94a3b8' } } } } });
        }
        if (D.stats.pressure && Object.keys(D.stats.pressure).length > 0) {
            new Chart(document.getElementById('p'), {
                type: 'bar',
                data: { labels: Object.keys(D.stats.pressure), datasets: [{ label: 'Отчётов/день', data: Object.values(D.stats.pressure), backgroundColor: ['#ef4444', '#eab308', '#22c55e'] }] },
                options: { ...CHOPT, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#94a3b8' }, title: { display: true, text: 'мм рт.ст.', color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' }, beginAtZero: true } } }
            });
        } else {
            document.getElementById('pnote').textContent = 'Недостаточно данных о погоде.';
        }
    }

    if (D.table && D.table.length > 0) {
        document.getElementById('t').innerHTML =
            '<tr><th>Дата</th><th>П</th><th>t°день</th><th>t°ночь</th><th>Ветер</th><th>Давл</th><th>Осадки</th><th>Луна</th><th></th></tr>' +
            D.table.map(r => `<tr><td>${r.day}</td><td>${r.posts}</td><td>${r.t_day ?? '—'}</td><td>${r.t_night ?? '—'}</td><td>${r.wind ?? '—'}</td><td>${r.pressure ?? '—'}</td><td>${r.precip ?? '—'}</td><td>${r.moon ?? '—'}</td><td>${(r.links || []).map((u, i) => `<a href="${u}" target="_blank" rel="noopener">#${i + 1}</a>`).join(' ')}</td></tr>`).join('');
    }

    if (D.top_locations && Object.keys(D.top_locations).length > 0) {
        document.getElementById('toploc').innerHTML = '<tr><th>Точка</th><th>Упоминаний</th></tr>' +
            Object.entries(D.top_locations).map(([k, v]) => `<tr><td>${k}</td><td><b>${v}</b></td></tr>`).join('');
    } else { document.getElementById('toploc').innerHTML = '<tr><td class="note">Пока нет данных.</td></tr>'; }

    if (D.top_lures && Object.keys(D.top_lures).length > 0) {
        new Chart(document.getElementById('lure'), {
            type: 'bar',
            data: { labels: Object.keys(D.top_lures), datasets: [{ label: 'Упоминаний', data: Object.values(D.top_lures), backgroundColor: '#38bdf8' }] },
            options: { ...CHOPT, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' }, beginAtZero: true } } }
        });
    }

    if (D.reports && D.reports.length > 0) {
        document.getElementById('reports').innerHTML =
            '<tr><th>Дата</th><th></th><th>Автор</th><th>Точка</th><th>Приманка</th><th>Цитата</th></tr>' +
            D.reports.map(r => `<tr><td>${r.day}</td><td>${r.success ? '🐟' : ''}</td><td>${r.author || '—'}</td><td>${r.location || '—'}</td><td>${r.lure || '—'}</td><td class="q"><a href="${r.url}" target="_blank" rel="noopener">${r.quote}</a></td></tr>`).join('');
    } else { document.getElementById('reports').innerHTML = '<tr><td class="note">Пока нет отчётов.</td></tr>'; }

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


def wind_dir_name(degrees):
    if degrees is None:
        return None
    return WIND_DIRS[int((degrees + 22.5) // 45) % 8]


def moon_phase(day_str):
    try:
        d = date.fromisoformat(day_str)
    except (TypeError, ValueError):
        return None
    age = ((d - date(2000, 1, 6)).days) % 29.530588853
    if age < 1.85:
        return MOON_ORDER[0]
    if age < 5.54:
        return MOON_ORDER[1]
    if age < 9.23:
        return MOON_ORDER[2]
    if age < 12.92:
        return MOON_ORDER[3]
    if age < 16.61:
        return MOON_ORDER[4]
    if age < 20.30:
        return MOON_ORDER[5]
    if age < 23.99:
        return MOON_ORDER[6]
    if age < 27.68:
        return MOON_ORDER[7]
    return MOON_ORDER[0]


def llm_chat(prompt_text):
    try:
        response = requests.post(
            LLM_API_URL,
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "temperature": 0,
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt_text}],
            },
            timeout=90,
        )
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as error:
        print(f"LLM ошибка: {error}")
        return None


def parse_llm_json(raw):
    if not raw:
        return None
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    bite = [p for p in (data.get("bite") or []) if p in TIME_PERIODS]
    no_bite = [p for p in (data.get("no_bite") or []) if p in TIME_PERIODS]
    return {"bite": bite, "no_bite": no_bite, "confident": bool(data.get("confident"))}


def run_llm_time_analysis(database, candidates):
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_time_cache (
            post_id TEXT PRIMARY KEY,
            day TEXT,
            result TEXT
        )
        """
    )
    database.commit()

    cached = {
        row[0]: row[1]
        for row in database.execute("SELECT post_id, result FROM llm_time_cache")
    }

    new_posts = [c for c in candidates if c[0] not in cached]

    if LLM_API_KEY and new_posts:
        to_analyze = new_posts[:LLM_MAX_POSTS]
        print(f"LLM: анализирую {len(to_analyze)} новых отчётов "
              f"(в кэше {len(cached)}, лимит {LLM_MAX_POSTS})...")

        for index, (post_id, day, text) in enumerate(to_analyze):
            raw = llm_chat(LLM_PROMPT + text[:2000])
            result = parse_llm_json(raw)
            if result is None:
                result = {"bite": [], "no_bite": [], "confident": False}
            database.execute(
                "INSERT OR REPLACE INTO llm_time_cache VALUES (?, ?, ?)",
                (post_id, day, json.dumps(result, ensure_ascii=False)),
            )
            database.commit()
            cached[post_id] = json.dumps(result, ensure_ascii=False)
            print(f"  {index + 1}/{len(to_analyze)}: "
                  f"клевало={result['bite']} не клевало={result['no_bite']}")
            time.sleep(1.0)
    elif not LLM_API_KEY:
        print(f"LLM: ключа нет — использую только кэш ({len(cached)} записей).")

    aggregate = {p: {"bite": 0, "no_bite": 0} for p in TIME_PERIODS}
    analyzed = 0
    candidate_ids = {c[0] for c in candidates}

    for post_id, raw_result in cached.items():
        if post_id not in candidate_ids:
            continue
        try:
            result = json.loads(raw_result)
        except json.JSONDecodeError:
            continue
        if not result.get("confident"):
            continue
        used = False
        for period in result.get("bite", []):
            if period in aggregate:
                aggregate[period]["bite"] += 1
                used = True
        for period in result.get("no_bite", []):
            if period in aggregate:
                aggregate[period]["no_bite"] += 1
                used = True
        if used:
            analyzed += 1

    return aggregate, analyzed


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


def extract_report(post_day, author, text, post_url):
    if not FOREL_RX.search(text or ""):
        return None

    loc_match = LOCATION_RX.search(text)
    lure_match = LURE_RX.search(text)
    if not loc_match and not lure_match:
        return None

    anchor = loc_match or lure_match
    return {
        "day": post_day,
        "author": author,
        "location": loc_match.group(0).lower() if loc_match else None,
        "lure": lure_match.group(0).lower() if lure_match else None,
        "success": bool(SUCCESS_RX.search(text)),
        "url": post_url,
        "quote": snippet(text, anchor.start(), 120)[:170],
    }


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
                "daily": (
                    "temperature_2m_max,temperature_2m_min,"
                    "precipitation_sum,pressure_msl_mean,"
                    "windspeed_10m_max,winddirection_10m_dominant"
                ),
                "timezone": "Europe/Moscow",
            },
            timeout=60,
        )
        daily = response.json().get("daily") or {}
        t_max = daily.get("temperature_2m_max") or []
        t_min = daily.get("temperature_2m_min") or []
        precips = daily.get("precipitation_sum") or []
        pressures = daily.get("pressure_msl_mean") or []
        wind_speeds = daily.get("windspeed_10m_max") or []
        wind_dirs = daily.get("winddirection_10m_dominant") or []

        for index, day in enumerate(daily.get("time") or []):
            pressure_hpa = pressures[index] if index < len(pressures) else None
            wind_speed = wind_speeds[index] if index < len(wind_speeds) else None
            wind_deg = wind_dirs[index] if index < len(wind_dirs) else None
            weather[day] = {
                "t_day": t_max[index] if index < len(t_max) else None,
                "t_night": t_min[index] if index < len(t_min) else None,
                "precip": precips[index] if index < len(precips) else None,
                "pressure": round(pressure_hpa * 0.75006, 1) if pressure_hpa is not None else None,
                "wind_speed": round(wind_speed / 3.6, 1) if wind_speed is not None else None,
                "wind_dir": wind_dir_name(wind_deg),
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
                "hourly": "temperature_2m,precipitation,pressure_msl,windspeed_10m,winddirection_10m",
                "timezone": "Europe/Moscow",
            },
            timeout=60,
        )
        hourly = response.json().get("hourly") or {}
        times = hourly.get("time") or []
        temps = hourly.get("temperature_2m") or []
        precips = hourly.get("precipitation") or []
        pressures = hourly.get("pressure_msl") or []
        wind_speeds = hourly.get("windspeed_10m") or []
        wind_dirs = hourly.get("winddirection_10m") or []

        buckets = defaultdict(list)
        for index, stamp in enumerate(times):
            buckets[stamp[:10]].append(index)

        for day, indexes in buckets.items():
            day_temps = [temps[i] for i in indexes if i < len(temps) and temps[i] is not None]
            day_precips = [precips[i] for i in indexes if i < len(precips) and precips[i] is not None]
            day_pressures = [pressures[i] for i in indexes if i < len(pressures) and pressures[i] is not None]
            day_winds = [wind_speeds[i] for i in indexes if i < len(wind_speeds) and wind_speeds[i] is not None]

            noon_dir = None
            for i in indexes:
                if i < len(times) and times[i][11:13] == "12" and i < len(wind_dirs):
                    noon_dir = wind_dirs[i]
                    break
            if noon_dir is None and indexes:
                mid = indexes[len(indexes) // 2]
                if mid < len(wind_dirs):
                    noon_dir = wind_dirs[mid]

            record = weather.get(day) or {}
            if day_temps:
                if record.get("t_day") is None:
                    record["t_day"] = round(max(day_temps), 1)
                if record.get("t_night") is None:
                    record["t_night"] = round(min(day_temps), 1)
            if day_precips and record.get("precip") is None:
                record["precip"] = round(sum(day_precips), 1)
            if day_pressures and record.get("pressure") is None:
                record["pressure"] = round(sum(day_pressures) / len(day_pressures) * 0.75006, 1)
            if day_winds and record.get("wind_speed") is None:
                record["wind_speed"] = round(max(day_winds) / 3.6, 1)
            if noon_dir is not None and record.get("wind_dir") is None:
                record["wind_dir"] = wind_dir_name(noon_dir)
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
                print(f" стр.{page_number}: 0 постов — пропуск")
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
                    "INSERT OR REPLACE INTO posts VALUES (?, ?, ?, ?, ?)",
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
    reports = []
    llm_candidates = []

    query = "SELECT post_id, page, author, post_dt, text FROM posts"

    for post_id, page_number, author, post_datetime, text in database.execute(query):
        post_day = (post_datetime or "")[:10]
        post_url = f"{THREAD}/page-{page_number}#post-{post_id}" if post_id else f"{THREAD}/page-{page_number}"

        if post_day and FOREL_RX.search(text or "") and post_day >= START_DATE:
            days[post_day].append(post_url)

        if not post_datetime or not post_day:
            continue

        if post_day >= REPORT_START and (author or "") not in ADMIN_AUTHORS:
            report = extract_report(post_day, author or "", text or "", post_url)
            if report:
                reports.append(report)

            if FOREL_RX.search(text or "") and TIME_HINT_RX.search(text or ""):
                llm_candidates.append((post_id, post_day, text or ""))

        if post_day < BALANCE_START:
            try:
                distance = (date.fromisoformat(BALANCE_START) - date.fromisoformat(post_day)).days
                if distance > 10:
                    continue
            except (TypeError, ValueError):
                continue

        if ADMIN_AUTHORS and (author or "") not in ADMIN_AUTHORS:
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

    llm_candidates.sort(key=lambda c: c[1], reverse=True)
    llm_aggregate, llm_analyzed = run_llm_time_analysis(database, llm_candidates)
    llm_time = {
        "enabled": bool(LLM_API_KEY) or llm_analyzed > 0,
        "model": LLM_MODEL if LLM_API_KEY else "кэш",
        "analyzed": llm_analyzed,
        "labels": TIME_PERIODS,
        "bite": [llm_aggregate[p]["bite"] for p in TIME_PERIODS],
        "no_bite": [llm_aggregate[p]["no_bite"] for p in TIME_PERIODS],
    }

    moon_buckets = defaultdict(list)
    for day_value, urls in days.items():
        phase = moon_phase(day_value)
        if phase:
            moon_buckets[phase].append(len(urls))
    moon_stats = {
        "labels": [p for p in MOON_ORDER if p in moon_buckets],
        "values": [round(sum(moon_buckets[p]) / len(moon_buckets[p]), 2) for p in MOON_ORDER if p in moon_buckets],
        "days": [len(moon_buckets[p]) for p in MOON_ORDER if p in moon_buckets],
    }

    monthly_activity = defaultdict(list)
    pressure_groups = {"<745": [], "745-760": [], ">760": []}

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
            pressure_groups[group].append(len(urls))

    def average(values):
        return round(sum(values) / len(values), 2) if values else 0

    collected_pages = len(glob.glob(f"{PAGES_DIR}/*.json"))
    needed_pages = state.get("newest", last_page) - state.get("start_page", last_page) + 1

    statistics = {
        "monthly": {month: average(vals) for month, vals in sorted(monthly_activity.items())},
        "pressure": {group: average(vals) for group, vals in pressure_groups.items()},
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
        wind = None
        if w.get("wind_speed") is not None:
            wind = f"{w.get('wind_dir') or '?'} {w['wind_speed']} м/с"
        table.append({
            "day": day_value,
            "posts": len(days[day_value]),
            "t_day": w.get("t_day"),
            "t_night": w.get("t_night"),
            "wind": wind,
            "pressure": w.get("pressure"),
            "precip": w.get("precip"),
            "moon": moon_phase(day_value),
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

    reports.sort(key=lambda r: r["day"], reverse=True)
    top_locations = defaultdict(int)
    top_lures = defaultdict(int)
    for report in reports:
        if report["location"]:
            top_locations[report["location"]] += 1
        if report["lure"]:
            top_lures[report["lure"]] += 1

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
                "temp": current_weather.get("t_day"),
                "pressure": current_weather.get("pressure"),
                "precip": current_weather.get("precip"),
                "moon": moon_phase(today_str),
            },
            "llm_time": llm_time,
            "moon_stats": moon_stats,
            "reports": reports[:80],
            "top_locations": dict(sorted(top_locations.items(), key=lambda item: -item[1])[:12]),
            "top_lures": dict(sorted(top_lures.items(), key=lambda item: -item[1])[:12]),
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")

    if "__DATA__" not in TEMPLATE:
        raise SystemExit("ОШИБКА: в TEMPLATE нет метки __DATA__!")

    final_html = TEMPLATE.replace("__DATA__", payload)

    if "__DATA__" in final_html:
        raise SystemExit("ОШИБКА: замена __DATA__ не сработала!")

    with open("index.html", "w", encoding="utf-8") as file:
        file.write(final_html)

    print(f"Сайт собран: остаток {remaining} кг, отчётов: {len(reports)}, LLM: {llm_analyzed}")


if __name__ == "__main__":
    main()
```

---

## Шаг 2. Заменить workflow

1. В репозитории откройте папку **.github/workflows** → файл с расширением **.yml** → карандаш ✏️.
2. Удалите всё, вставьте это, нажмите **Commit changes**:

```yaml
name: build

on:
  schedule:
    - cron: "0 */6 * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - run: pip install curl_cffi beautifulsoup4 lxml

      - name: Build site
        env:
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
          LLM_MODEL: "openai/gpt-4o-mini"
          LLM_MAX_POSTS: "40"
        run: python main.py

      - name: Commit results
        run: |
          git config user.name "bot"
          git config user.email "bot@users.noreply.github.com"
          git add -A
          git commit -m "update" || echo "no changes"
          git push
```

⚠️ Если ваш скрипт называется не `main.py` — исправьте строку `run: python main.py` на ваше имя файла.

## Шаг 3. Запустить

1. В репозитории вкладка **Actions** → слева **build** → кнопка **Run workflow** → зелёная **Run workflow**.
2. Ждите **зелёную галочку** (10–20 минут — скрипт качает страницы форума не спеша).
3. Откройте сайт **в режиме инкогнито** (чтобы не мешал кэш): в браузере ⋮ → «Новая вкладка инкогнито».

## Что вы должны увидеть

- Дата и время в шапке показываются **всегда**, даже если данные ещё пустые — это признак, что страница исправна.
- Цифры (посты, баланс) будут расти с каждым запуском: за один запуск качается ~165 страниц форума, а их тысячи. Это нормально — прогресс виден в блоке «Активность» («Собрано страниц: X из Y»).

Если после этого что-то не так — сфотографируйте/скопируйте **красные строки из вкладки Actions** (нажмите на упавший запуск → на шаг с ❌) и пришлите мне.
