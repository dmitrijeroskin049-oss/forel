import os, re, json, time, random, sqlite3
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

LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_API_URL = os.environ.get("LLM_API_URL", "https://openrouter.ai/api/v1/chat/completions").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "meta-llama/llama-3.3-70b-instruct:free").strip()
LLM_MAX_POSTS = int(os.environ.get("LLM_MAX_POSTS", "20"))

if LLM_API_KEY:
    print("LLM: kluch naiden, model " + LLM_MODEL)
else:
    print("LLM: kluch ne zadan")

LLM_PROMPT = """Ты анализируешь отчёт рыбака с форелевого пруда.
Определи, в какие периоды суток форель КЛЕВАЛА, а в какие НЕ клевала.
Периоды строго: "утро", "день", "вечер", "ночь".
Учитывай отрицания: «утром тишина, вечером раздача» = утро не клевало, вечер клевало.
Ответь строго одним JSON без пояснений:
{"bite": ["вечер"], "no_bite": ["утро"], "confident": true}
Если ничего не понятно про время клёва:
{"bite": [], "no_bite": [], "confident": false}

Текст отчёта:
"""

ADMIN_AUTHORS = ["Александр SALMO", "Митяй-Митинооо"]
IGNORE_STOCK_DAYS = {"2026-09-04", "2026-09-05", "2026-09-06", "2026-09-07", "2026-09-08"}
BATCH = 120
REFRESH_TAIL = 12

FOREL_RX = re.compile(r"форел", re.I)
OTHER_FISH = re.compile(r"осет|карп|сом\b|щук|белуг|стерляд|карас|окун|судак|налим|амур|толстолоб|линь", re.I)
DATE_RX = re.compile(r"(?<!\d)(\d{1,2})\.(\d{2})(?:\.(\d{2,4}))?(?!\d)")
KG_RX = re.compile(r"(\d+(?:[.,]\d+)?)(?:\s*[-]\s*(\d+(?:[.,]\d+)?))?\s*(кг|килограмм\w*|тонн\w*|т)\b", re.I)
STOCK_KW_RX = re.compile(r"запуск|запустили|зарыбление|зарыбили|завезли|завоз|выпустили", re.I)
CATCH_KW_RX = re.compile(r"вылов\w*|итог дня|итого", re.I)
FUTURE_RX = re.compile(r"сделаем|будет|будут|планиру|анонс|ожидается|собираемся", re.I)
LOCATION_RX = re.compile(r"основной водо[её]м|дальний угол|у плотин\w*|у коряг\w*|у входа|у выхода|мелководь\w*|у берега|у причала|у мостка|у дамбы|у кустов|у травы|понтон\w*|пантон\w*|бабий угол|женский угол|пляж|под дубами|под ивой|под администрацией|под стадионом|на запуске|спорт зон\w*", re.I)
LURE_RX = re.compile(r"вертушк\w*|воблер\w*|резин\w*|мушк\w*|блесна|черв\w*|опарыш\w*|мотыл\w*|пенопласт|тесто|сыр|бойл\w*|силикон\w*|твистер\w*|виброхвост\w*|мормышк\w*|магот\w*|светонакоп\w*|стрейч|бобриный хвост|пламп\w*|паста|креветк\w*|кукуруз\w*", re.I)
SUCCESS_RX = re.compile(r"поймал|словил|взял|вытащил|выловил|отловил|клевал|клюнул|в улове", re.I)
TIME_HINT_RX = re.compile(r"утр|днём|днем|вечер|ноч|рассвет|закат|клев|клёв", re.I)
BAD_BETWEEN_RX = re.compile(r"корм|прикорм|пеллет|смес", re.I)
SENTENCE_RX = re.compile(r"[.!?]")

WIND_DIRS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]
MOON_ORDER = ["новолуние", "растущий серп", "первая четверть", "растущая", "полнолуние", "убывающая", "последняя четверть", "убывающий серп"]
TIME_PERIODS = ["утро", "день", "вечер", "ночь"]

TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Форель Красногорск</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;margin:0 auto;padding:10px;background:#0f172a;color:#e2e8f0;max-width:860px}
h1{font-size:1.3rem;color:#38bdf8}
h3{font-size:.95rem;margin:10px 0 6px}
.card{background:#1e293b;padding:12px;margin:0}
.big{font-size:1.6rem;font-weight:800;color:#fbbf24}
table{width:100%;border-collapse:collapse;font-size:.75rem;min-width:480px}
td,th{padding:5px 4px;border-bottom:1px solid #334155;text-align:left;vertical-align:top}
a{color:#7dd3fc;text-decoration:none}
.note{font-size:.75rem;color:#94a3b8}
.scrollx{overflow-x:auto}
.narrow{min-width:0}
.chartbox{position:relative;height:230px;width:100%}
details{margin:8px 0;border:1px solid #334155;border-radius:10px;overflow:hidden;background:#1e293b}
summary{padding:11px 12px;font-weight:800;color:#38bdf8;cursor:pointer;list-style:none}
summary::-webkit-details-marker{display:none}
#topbar{display:flex;gap:10px;flex-wrap:wrap;background:#1e293b;padding:11px;border-radius:10px;font-size:.82rem;margin:8px 0}
#topbar b{color:#fbbf24}
</style>
</head>
<body>
<h1>Форель в Красногорске</h1>

<div id="topbar">
<span><b>Дата:</b> <span id="curDate">-</span></span>
<span><b>Время:</b> <span id="curTime">-</span></span>
<span><b>Погода:</b> <span id="curTemp">-</span>C, <span id="curPress">-</span> мм</span>
<span><b>Луна:</b> <span id="curMoon">-</span></span>
</div>

<details open><summary>Условия рыбалки</summary><div class="card">
<div class="scrollx"><table class="narrow">
<tr><td>06:00-19:00</td><td><b>4000 Р</b></td></tr>
<tr><td>12:00-19:00</td><td><b>2200 Р</b></td></tr>
<tr><td>18:00-06:00</td><td><b>4000 Р</b></td></tr>
<tr><td>Сутки</td><td><b>5000 Р</b></td></tr>
<tr><td>Приоритетный час</td><td><b>300 Р</b></td></tr>
<tr><td>Доп. снасть</td><td><b>500 Р</b></td></tr>
</table></div>
<p class="note">Две снасти, до двух крючков. Женщина и ребёнок до 13 лет бесплатно. Нормы вылова нет. Спиннинг разрешён. Пеллетс и тройники запрещены.<br>
Телефон: <a href="tel:+79852620637">+7 985 262-06-37</a><br>
<a href="https://yandex.ru/maps/?pt=37.322979,55.840619&z=15&l=map" target="_blank">55.840619, 37.322979</a><br>
Блок обновляется вручную. Актуально на 13.09.2026.</p>
</div></details>

<details open><summary>Остаток форели в водоёме</summary><div class="card">
<div class="big" id="rem">-</div>
<div class="note">запущено <b id="st">0</b> кг, выловлено <b id="ct">0</b> кг, отсчёт с <span id="bs"></span><br>
последний запуск: <span id="dsl">-</span>, обновлено <span id="upd"></span></div>
</div></details>

<details open><summary>Баланс</summary><div class="card" id="balbox">
<div class="chartbox"><canvas id="bal"></canvas></div>
</div></details>

<details><summary>Журнал запусков и выловов</summary><div class="card">
<div class="scrollx"><table id="ev"></table></div>
</div></details>

<details><summary>Когда клюёт (анализ LLM)</summary><div class="card">
<div class="note" id="llmnote"></div>
<div class="chartbox"><canvas id="llmchart"></canvas></div>
<div class="note">Отчёты прочитаны языковой моделью: «утром тишина, вечером раздача» учитывается верно.</div>
</div></details>

<details><summary>Луна и клёв</summary><div class="card">
<div class="chartbox"><canvas id="moonchart"></canvas></div>
<div class="note">Средняя активность отчётов в каждой фазе луны с 2024 года.</div>
</div></details>

<details><summary>Активность обсуждений с 2024</summary><div class="card">
<div class="note" id="prog"></div>
<div class="big" style="color:#38bdf8" id="total">0</div>
<div class="note">постов про форель за <span id="days">0</span> дней</div>
<h3>По месяцам</h3>
<div class="chartbox"><canvas id="m"></canvas></div>
<h3>Клёв и давление</h3>
<div class="chartbox"><canvas id="p"></canvas></div>
<h3>Последние активные дни</h3>
<div class="scrollx"><table id="t"></table></div>
<div class="note">t день - максимум, t ночь - минимум за сутки.</div>
</div></details>

<details open><summary>Где и на что ловят</summary><div class="card">
<h3>Топ точек</h3>
<div class="scrollx"><table id="toploc" class="narrow"></table></div>
<h3>Топ приманок</h3>
<div class="chartbox"><canvas id="lure"></canvas></div>
<h3>Отчёты рыбаков</h3>
<div class="scrollx"><table id="reports"></table></div>
<div class="note">Точки и приманки найдены по ключевым словам, открывайте ссылку и читайте пост целиком.</div>
</div></details>

<script type="application/json" id="sitedata">__DATA__</script>
<script>
var D = {};
try { D = JSON.parse(document.getElementById('sitedata').textContent); } catch (e) { console.error(e); }
try {
var CH = { responsive: true, maintainAspectRatio: false };

function top() {
  var now = new Date();
  document.getElementById('curDate').textContent = now.toLocaleDateString('ru-RU');
  document.getElementById('curTime').textContent = now.toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit'});
  var cw = D.current_weather || {};
  document.getElementById('curTemp').textContent = (cw.temp == null ? '-' : cw.temp);
  document.getElementById('curPress').textContent = (cw.pressure == null ? '-' : cw.pressure);
  document.getElementById('curMoon').textContent = (cw.moon == null ? '-' : cw.moon);
}
top(); setInterval(top, 30000);

var B = D.balance || {};
document.getElementById('bs').textContent = B.start || '';
document.getElementById('st').textContent = B.total_stocked || 0;
document.getElementById('ct').textContent = B.total_caught || 0;
document.getElementById('rem').textContent = (B.events && B.events.length) ? ('около ' + (B.remaining || 0) + ' кг') : 'нет данных';
document.getElementById('dsl').textContent = (B.days_since_stock == null) ? 'нет данных' : (B.days_since_stock + ' дн. назад');
document.getElementById('upd').textContent = (D.stats && D.stats.updated) || '';

if (B.series && B.series.dates && B.series.dates.length) {
  new Chart(document.getElementById('bal'), {
    data: { labels: B.series.dates, datasets: [
      { type:'line', label:'Остаток кг', data:B.series.remaining, borderColor:'#fbbf24', pointRadius:0, borderWidth:2, tension:0.3 },
      { type:'bar', label:'Запуск', data:B.series.stocked, backgroundColor:'#4ade80' },
      { type:'bar', label:'Вылов', data:B.series.caught, backgroundColor:'#f87171' } ] },
    options: { responsive:true, maintainAspectRatio:false, plugins:{legend:{labels:{color:'#e2e8f0',boxWidth:12}}}, scales:{x:{ticks:{color:'#94a3b8',maxTicksLimit:8}},y:{ticks:{color:'#94a3b8'}}} }
  });
} else { document.getElementById('balbox').innerHTML = '<div class="note">Пока нет данных о запусках.</div>'; }

if (B.events && B.events.length) {
  document.getElementById('ev').innerHTML = '<tr><th>Дата</th><th></th><th>кг</th><th>Цитата</th></tr>' + B.events.map(function(e){
    return '<tr><td>' + e.day + '</td><td>' + (e.type === 'запуск' ? 'З' : 'В') + '</td><td><b>' + e.kg + '</b></td><td class="note"><a href="' + e.url + '" target="_blank">' + e.quote + '</a></td></tr>'; }).join('');
} else { document.getElementById('ev').innerHTML = '<tr><td class="note">Пока нет записей.</td></tr>'; }

var LT = D.llm_time || {};
if (LT.analyzed > 0) {
  document.getElementById('llmnote').textContent = 'Проанализировано отчётов: ' + LT.analyzed;
  new Chart(document.getElementById('llmchart'), {
    type: 'bar',
    data: { labels: LT.labels, datasets: [
      { label:'Клевало', data:LT.bite, backgroundColor:'#4ade80' },
      { label:'Не клевало', data:LT.no_bite, backgroundColor:'#f87171' } ] },
    options: { responsive:true, maintainAspectRatio:false, plugins:{legend:{labels:{color:'#e2e8f0',boxWidth:12}}}, scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'},beginAtZero:true}} }
  });
} else {
  document.getElementById('llmnote').textContent = LT.enabled ? 'Отчёты ещё не проанализированы, данные появятся после следующих запусков.' : 'LLM-анализ отключён (нет ключа).';
  document.getElementById('llmchart').parentNode.style.display = 'none';
}

var M = D.moon_stats || {};
if (M.labels && M.labels.length) {
  new Chart(document.getElementById('moonchart'), {
    type:'bar',
    data:{ labels:M.labels, datasets:[{ label:'Постов в день', data:M.values, backgroundColor:'#a78bfa' }] },
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'},beginAtZero:true}} }
  });
}

if (D.stats) {
  document.getElementById('prog').textContent = 'Собрано страниц: ' + D.stats.collected + ' из ' + D.stats.need + ' (' + D.stats.pct + '%)';
  document.getElementById('total').textContent = D.stats.total_posts || 0;
  document.getElementById('days').textContent = D.stats.active_days || 0;
  if (D.stats.monthly) {
    new Chart(document.getElementById('m'), { type:'bar',
      data:{ labels:Object.keys(D.stats.monthly), datasets:[{ data:Object.values(D.stats.monthly), backgroundColor:'#38bdf8' }] },
      options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{ticks:{color:'#94a3b8',maxTicksLimit:12}},y:{ticks:{color:'#94a3b8'}}} } });
  }
  if (D.stats.pressure) {
    new Chart(document.getElementById('p'), { type:'bar',
      data:{ labels:Object.keys(D.stats.pressure), datasets:[{ data:Object.values(D.stats.pressure), backgroundColor:['#ef4444','#eab308','#22c55e'] }] },
      options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'},beginAtZero:true}} } });
  }
}

if (D.table && D.table.length) {
  document.getElementById('t').innerHTML = '<tr><th>Дата</th><th>П</th><th>t день</th><th>t ночь</th><th>Ветер</th><th>Давл</th><th>Осадки</th><th>Луна</th><th></th></tr>' + D.table.map(function(r){
    var links = (r.links || []).map(function(u,i){ return '<a href="' + u + '" target="_blank">#' + (i+1) + '</a>'; }).join(' ');
    return '<tr><td>' + r.day + '</td><td>' + r.posts + '</td><td>' + (r.t_day == null ? '-' : r.t_day) + '</td><td>' + (r.t_night == null ? '-' : r.t_night) + '</td><td>' + (r.wind || '-') + '</td><td>' + (r.pressure == null ? '-' : r.pressure) + '</td><td>' + (r.precip == null ? '-' : r.precip) + '</td><td>' + (r.moon || '-') + '</td><td>' + links + '</td></tr>'; }).join('');
}

if (D.top_locations && Object.keys(D.top_locations).length) {
  document.getElementById('toploc').innerHTML = '<tr><th>Точка</th><th>Упоминаний</th></tr>' + Object.keys(D.top_locations).map(function(k){
    return '<tr><td>' + k + '</td><td><b>' + D.top_locations[k] + '</b></td></tr>'; }).join('');
} else { document.getElementById('toploc').innerHTML = '<tr><td class="note">Пока нет данных.</td></tr>'; }

if (D.top_lures && Object.keys(D.top_lures).length) {
  new Chart(document.getElementById('lure'), { type:'bar',
    data:{ labels:Object.keys(D.top_lures), datasets:[{ data:Object.values(D.top_lures), backgroundColor:'#38bdf8' }] },
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'},beginAtZero:true}} } });
}

if (D.reports && D.reports.length) {
  document.getElementById('reports').innerHTML = '<tr><th>Дата</th><th></th><th>Автор</th><th>Точка</th><th>Приманка</th><th>Цитата</th></tr>' + D.reports.map(function(r){
    return '<tr><td>' + r.day + '</td><td>' + (r.success ? 'ДА' : '') + '</td><td>' + (r.author || '-') + '</td><td>' + (r.location || '-') + '</td><td>' + (r.lure || '-') + '</td><td class="note"><a href="' + r.url + '" target="_blank">' + r.quote + '</a></td></tr>'; }).join('');
} else { document.getElementById('reports').innerHTML = '<tr><td class="note">Пока нет отчётов.</td></tr>'; }

} catch (err) { console.error(err); }
</script>
</body>
</html>"""


def page_url(p):
    return THREAD if p == 1 else THREAD + "/page-" + str(p)


def fetch(url, tries=3):
    for a in range(tries):
        try:
            r = requests.get(url, impersonate="chrome120", timeout=25,
                             headers={"Accept-Language": "ru-RU,ru;q=0.9"})
            if r.status_code == 200 and "article" in r.text:
                return r.text
        except Exception as e:
            print("retry", a + 1, e)
        time.sleep(3 * (a + 1))
    return None


def parse_posts(html, page):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for m in soup.select("article.message"):
        raw = m.get("id", "")
        found = re.search(r"(\d+)", raw)
        pid = found.group(1) if found else "p%d_%d" % (page, len(out))
        t = m.select_one("time")
        body = m.select_one(".bbWrapper")
        if not body:
            continue
        for q in body.select("blockquote"):
            q.decompose()
        out.append({
            "post_id": pid,
            "page": page,
            "author": m.get("data-author", ""),
            "post_dt": (t.get("datetime") or "") if t else "",
            "text": body.get_text("\n", strip=True),
        })
    return out


def total_pages(html):
    soup = BeautifulSoup(html, "lxml")
    nav = soup.select_one(".pageNav")
    if nav and nav.get("data-last"):
        try:
            return int(nav["data-last"])
        except Exception:
            pass
    nums = []
    for a in soup.select(".pageNav a"):
        s = a.get_text(strip=True).replace(" ", "")
        if s.isdigit():
            nums.append(int(s))
    return max(nums) if nums else 1


def first_date(html):
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    t = soup.select_one("article.message time")
    return (t.get("datetime") or "")[:10] if t else ""


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)


def snippet(text, pos, width=90):
    a = max(0, pos - 15)
    b = min(len(text), pos + width)
    return re.sub(r"\s+", " ", text[a:b]).strip()


def wind_dir_name(deg):
    if deg is None:
        return None
    return WIND_DIRS[int((deg + 22.5) // 45) % 8]


def moon_phase(day_str):
    try:
        d = date.fromisoformat(day_str)
    except Exception:
        return None
    age = ((d - date(2000, 1, 6)).days) % 29.530588853
    return MOON_ORDER[min(7, int(age / 3.6913))]


def llm_chat(prompt):
    try:
        r = requests.post(LLM_API_URL,
                          headers={"Authorization": "Bearer " + LLM_API_KEY,
                                   "Content-Type": "application/json"},
                          json={"model": LLM_MODEL, "temperature": 0, "max_tokens": 200,
                                "messages": [{"role": "user", "content": prompt}]},
                          timeout=90)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print("LLM error:", e)
        return None


def parse_llm_json(raw):
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    return {
        "bite": [p for p in (d.get("bite") or []) if p in TIME_PERIODS],
        "no_bite": [p for p in (d.get("no_bite") or []) if p in TIME_PERIODS],
        "confident": bool(d.get("confident")),
    }


def run_llm(db, cands):
    db.execute("CREATE TABLE IF NOT EXISTS llm_cache (post_id TEXT PRIMARY KEY, day TEXT, result TEXT)")
    db.commit()
    cached = {}
    for pid, res in db.execute("SELECT post_id, result FROM llm_cache"):
        cached[pid] = res
    fresh = [c for c in cands if c[0] not in cached]
    if LLM_API_KEY and fresh:
        todo = fresh[:LLM_MAX_POSTS]
        print("LLM: analiz " + str(len(todo)) + " novyh otchetov")
        for i, (pid, day, text) in enumerate(todo):
            res = parse_llm_json(llm_chat(LLM_PROMPT + text[:2000]))
            if res is None:
                res = {"bite": [], "no_bite": [], "confident": False}
            db.execute("INSERT OR REPLACE INTO llm_cache VALUES (?,?,?)",
                       (pid, day, json.dumps(res, ensure_ascii=False)))
            db.commit()
            cached[pid] = json.dumps(res, ensure_ascii=False)
            print("  " + str(i + 1) + "/" + str(len(todo)) + " " + str(res["bite"]) + " / " + str(res["no_bite"]))
            time.sleep(1.0)
    agg = {}
    for p in TIME_PERIODS:
        agg[p] = {"bite": 0, "no_bite": 0}
    ids = set(c[0] for c in cands)
    n = 0
    for pid, raw in cached.items():
        if pid not in ids:
            continue
        try:
            res = json.loads(raw)
        except Exception:
            continue
        if not res.get("confident"):
            continue
        used = False
        for p in res.get("bite", []):
            if p in agg:
                agg[p]["bite"] += 1
                used = True
        for p in res.get("no_bite", []):
            if p in agg:
                agg[p]["no_bite"] += 1
                used = True
        if used:
            n += 1
    return agg, n


def resolve_event_date(text, start, end, post_dt):
    pd = (post_dt or "")[:10]
    try:
        py = int(pd[:4])
    except Exception:
        py = date.today().year
    ls = text.rfind("\n", 0, start)
    ls = 0 if ls == -1 else ls + 1
    le = text.find("\n", end)
    if le == -1:
        le = len(text)
    line = text[ls:le]
    for scope in (line, text[max(0, start - 40):min(len(text), end + 40)]):
        m = DATE_RX.search(scope)
        if not m:
            continue
        try:
            dd = int(m.group(1))
            mm = int(m.group(2))
            ry = m.group(3)
            if ry:
                yy = int(ry)
                y = 2000 + yy if len(ry) == 2 and yy < 50 else (1900 + yy if len(ry) == 2 else yy)
            else:
                y = py
            if 1 <= dd <= 31 and 1 <= mm <= 12:
                return ("%04d-%02d-%02d" % (y, mm, dd), True)
        except Exception:
            pass
    if "завтра" in line.lower():
        try:
            return (str(date.fromisoformat(pd) + timedelta(days=1)), True)
        except Exception:
            pass
    return pd, False


def kind_for(text, kws, start, end):
    lefts = [k for k in kws if k[1] <= start]
    if lefts:
        ks, ke, kind = lefts[-1]
        if start - ke <= 200 and not BAD_BETWEEN_RX.search(text[ke:start]):
            return kind
    rights = [k for k in kws if k[0] >= end]
    if rights:
        ks, ke, kind = rights[0]
        between = text[end:ks]
        if ks - end <= 200 and not SENTENCE_RX.search(between) and not BAD_BETWEEN_RX.search(between):
            return kind
    return None


def find_events(text, post_dt):
    if not text:
        return []
    pd = (post_dt or "")[:10]
    kws = []
    for m in STOCK_KW_RX.finditer(text):
        kws.append((m.start(), m.end(), "stock"))
    for m in CATCH_KW_RX.finditer(text):
        kws.append((m.start(), m.end(), "catch"))
    kws.sort()
    out = []
    for m in KG_RX.finditer(text):
        s, e = m.span()
        before = text[max(0, s - 45):s].lower()
        if re.search(r"навеск\w*[^0-9]{0,25}$", before):
            continue
        if OTHER_FISH.search(text[max(0, s - 25):min(len(text), e + 25)]):
            continue
        kind = kind_for(text, kws, s, e)
        if kind is None:
            continue
        try:
            v1 = float(m.group(1).replace(",", "."))
            v2 = m.group(2)
            val = (v1 + float(v2.replace(",", "."))) / 2 if v2 else v1
            unit = (m.group(3) or "").lower()
            if unit.startswith("тон") or unit == "т":
                val *= 1000
            kg = int(round(val))
        except Exception:
            continue
        if kind == "stock" and not (30 <= kg <= 20000):
            continue
        if kind == "catch" and not (5 <= kg <= 20000):
            continue
        if kind == "stock":
            ctx = text[max(0, s - 250):min(len(text), e + 250)]
            if not FOREL_RX.search(ctx) and OTHER_FISH.search(ctx):
                continue
            ed, dated = resolve_event_date(text, s, e, post_dt)
            if not dated and FUTURE_RX.search(text[max(0, s - 60):s].lower()):
                continue
        else:
            ed, dated = pd, False
        out.append({"kind": kind, "kg": kg, "day": ed, "dated": dated,
                    "quote": snippet(text, s), "pos": s})
    dated_stock = [r for r in out if r["kind"] == "stock" and r["dated"]]
    if dated_stock:
        out = [r for r in out if not (r["kind"] == "stock" and not r["dated"])]
    return out


def load_weather():
    w = {}
    today = date.today()
    try:
        r = requests.get("https://archive-api.open-meteo.com/v1/archive",
                         params={"latitude": 55.82, "longitude": 37.33,
                                 "start_date": START_DATE, "end_date": str(today - timedelta(days=1)),
                                 "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,pressure_msl_mean,windspeed_10m_max,winddirection_10m_dominant",
                                 "timezone": "Europe/Moscow"}, timeout=60).json().get("daily") or {}
        tmax = r.get("temperature_2m_max") or []
        tmin = r.get("temperature_2m_min") or []
        pr = r.get("precipitation_sum") or []
        ps = r.get("pressure_msl_mean") or []
        ws = r.get("windspeed_10m_max") or []
        wd = r.get("winddirection_10m_dominant") or []
        for i, d in enumerate(r.get("time") or []):
            w[d] = {
                "t_day": tmax[i] if i < len(tmax) else None,
                "t_night": tmin[i] if i < len(tmin) else None,
                "precip": pr[i] if i < len(pr) else None,
                "pressure": round(ps[i] * 0.75006, 1) if i < len(ps) and ps[i] is not None else None,
                "wind_speed": round(ws[i] / 3.6, 1) if i < len(ws) and ws[i] is not None else None,
                "wind_dir": wind_dir_name(wd[i] if i < len(wd) else None),
            }
    except Exception as e:
        print("archive weather:", e)
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast",
                         params={"latitude": 55.82, "longitude": 37.33,
                                 "start_date": str(today - timedelta(days=2)),
                                 "end_date": str(today + timedelta(days=1)),
                                 "hourly": "temperature_2m,precipitation,pressure_msl,windspeed_10m,winddirection_10m",
                                 "timezone": "Europe/Moscow"}, timeout=60).json().get("hourly") or {}
        times = r.get("time") or []
        tt = r.get("temperature_2m") or []
        pp = r.get("precipitation") or []
        ss = r.get("pressure_msl") or []
        vv = r.get("windspeed_10m") or []
        dd = r.get("winddirection_10m") or []
        buckets = defaultdict(list)
        for i, s in enumerate(times):
            buckets[s[:10]].append(i)
        for day, idx in buckets.items():
            temps = [tt[i] for i in idx if i < len(tt) and tt[i] is not None]
            precs = [pp[i] for i in idx if i < len(pp) and pp[i] is not None]
            press = [ss[i] for i in idx if i < len(ss) and ss[i] is not None]
            winds = [vv[i] for i in idx if i < len(vv) and vv[i] is not None]
            rec = w.get(day) or {}
            if temps:
                if rec.get("t_day") is None:
                    rec["t_day"] = round(max(temps), 1)
                if rec.get("t_night") is None:
                    rec["t_night"] = round(min(temps), 1)
            if precs and rec.get("precip") is None:
                rec["precip"] = round(sum(precs), 1)
            if press and rec.get("pressure") is None:
                rec["pressure"] = round(sum(press) / len(press) * 0.75006, 1)
            if winds and rec.get("wind_speed") is None:
                rec["wind_speed"] = round(max(winds) / 3.6, 1)
            if rec.get("wind_dir") is None and idx:
                mid = idx[len(idx) // 2]
                if mid < len(dd):
                    rec["wind_dir"] = wind_dir_name(dd[mid])
            w[day] = rec
    except Exception as e:
        print("forecast weather:", e)
    return w


def download(db, state):
    html = fetch(page_url(1))
    if not html:
        print("Forum ne otvetil")
        return state.get("newest", 1)
    last = total_pages(html)
    print("Vsego stranic:", last)

    if not state.get("start_page"):
        print("Ischu 2024 god...")
        lo, hi = 1, last
        while lo < hi:
            mid = (lo + hi) // 2
            h = fetch(page_url(mid))
            fd = first_date(h) if h else ""
            print(" str." + str(mid) + ": " + (fd or "?"))
            time.sleep(1.5)
            if not fd or fd >= START_DATE:
                hi = mid
            else:
                lo = mid + 1
        state["start_page"] = max(1, lo - 1)
        state["cursor"] = last
        state["newest"] = last

    start_page = state["start_page"]
    todo = []
    if last > state.get("newest", last):
        todo += list(range(state["newest"] + 1, last + 1))
    state["newest"] = last

    cur = state.get("cursor", last)
    added = []
    while len(added) < BATCH and cur >= start_page:
        if not os.path.exists(PAGES_DIR + "/page_%06d.json" % cur):
            added.append(cur)
        cur -= 1
    state["cursor"] = cur

    tail = list(range(max(start_page, last - REFRESH_TAIL + 1), last + 1))
    todo = sorted(set(todo + added + tail))
    print("Zagruzhau " + str(len(todo)) + " stranic")

    for i, p in enumerate(todo):
        h = fetch(page_url(p))
        if h:
            posts = parse_posts(h, p)
            if posts:
                with open(PAGES_DIR + "/page_%06d.json" % p, "w", encoding="utf-8") as f:
                    json.dump(posts, f, ensure_ascii=False)
                print(" " + str(i + 1) + "/" + str(len(todo)) + " str." + str(p) + ": " + str(len(posts)))
        time.sleep(random.uniform(1.2, 2.0))
        if (i + 1) % 20 == 0:
            save_state(state)

    for fn in os.listdir(PAGES_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(PAGES_DIR + "/" + fn, encoding="utf-8") as f:
                for post in json.load(f):
                    db.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?)",
                               (post.get("post_id", ""), post.get("page", 0),
                                post.get("author", ""), post.get("post_dt", ""),
                                post.get("text", "")))
            db.commit()
        except Exception as e:
            print("file err", fn, e)

    save_state(state)
    return last


def build(db, state, last_page):
    days = defaultdict(list)
    stock_c = defaultdict(list)
    catch_c = defaultdict(list)
    reports = []
    llm_cands = []

    for pid, page, author, dt, text in db.execute("SELECT post_id, page, author, post_dt, text FROM posts"):
        day = (dt or "")[:10]
        url = THREAD + "/page-" + str(page) + "#post-" + str(pid)
        text = text or ""
        if day and day >= START_DATE and FOREL_RX.search(text):
            days[day].append(url)
        if not day:
            continue

        if day >= REPORT_START and (author or "") not in ADMIN_AUTHORS and FOREL_RX.search(text):
            loc = LOCATION_RX.search(text)
            lure = LURE_RX.search(text)
            if loc or lure:
                anchor = loc or lure
                reports.append({
                    "day": day, "author": author or "",
                    "location": loc.group(0).lower() if loc else None,
                    "lure": lure.group(0).lower() if lure else None,
                    "success": bool(SUCCESS_RX.search(text)),
                    "url": url, "quote": snippet(text, anchor.start(), 110)[:150],
                })
            if TIME_HINT_RX.search(text):
                llm_cands.append((pid, day, text))

        if (author or "") not in ADMIN_AUTHORS:
            continue
        if day < BALANCE_START:
            try:
                if (date.fromisoformat(BALANCE_START) - date.fromisoformat(day)).days > 10:
                    continue
            except Exception:
                continue

        for ev in find_events(text, dt):
            d = ev["day"]
            if not d or d < BALANCE_START:
                continue
            if ev["kind"] == "stock" and d in IGNORE_STOCK_DAYS:
                continue
            rec = {"kg": ev["kg"], "url": url, "dt": dt, "pos": ev["pos"],
                   "is_fact": (dt[:10] == d),
                   "quote": ("пост " + dt[5:10] + " " + dt[11:16] + " " + ev["quote"])[:150]}
            if ev["kind"] == "stock":
                stock_c[d].append(rec)
            else:
                catch_c[d].append(rec)

    day_events = {}
    for d, recs in stock_c.items():
        pool = [r for r in recs if r["is_fact"]] or recs
        day_events.setdefault(d, {})["stock"] = max(pool, key=lambda r: (r["dt"], r["pos"]))
    for d, recs in catch_c.items():
        day_events.setdefault(d, {})["catch"] = max(recs, key=lambda r: (r["dt"], r["pos"]))

    weather = load_weather()

    llm_cands.sort(key=lambda c: c[1], reverse=True)
    agg, analyzed = run_llm(db, llm_cands)
    llm_time = {"enabled": bool(LLM_API_KEY), "analyzed": analyzed, "labels": TIME_PERIODS,
                "bite": [agg[p]["bite"] for p in TIME_PERIODS],
                "no_bite": [agg[p]["no_bite"] for p in TIME_PERIODS]}

    moon_b = defaultdict(list)
    monthly = defaultdict(list)
    press_g = {"ниже 745": [], "745-760": [], "выше 760": []}
    for d, urls in days.items():
        monthly[d[:7]].append(len(urls))
        ph = moon_phase(d)
        if ph:
            moon_b[ph].append(len(urls))
        pr = (weather.get(d) or {}).get("pressure")
        if pr is not None:
            g = "ниже 745" if pr < 745 else ("745-760" if pr <= 760 else "выше 760")
            press_g[g].append(len(urls))

    def avg(v):
        return round(sum(v) / len(v), 2) if v else 0

    moon_labels = [p for p in MOON_ORDER if p in moon_b]
    moon_stats = {"labels": moon_labels, "values": [avg(moon_b[p]) for p in moon_labels],
                  "days": [len(moon_b[p]) for p in moon_labels]}

    collected = len([f for f in os.listdir(PAGES_DIR) if f.endswith(".json")])
    need = max(1, state.get("newest", last_page) - state.get("start_page", last_page) + 1)

    stats = {"monthly": dict((k, avg(v)) for k, v in sorted(monthly.items())),
             "pressure": dict((k, avg(v)) for k, v in press_g.items()),
             "total_posts": sum(len(v) for v in days.values()),
             "active_days": len(days), "collected": collected, "need": need,
             "pct": round(collected / need * 100, 1), "updated": str(date.today())}

    table = []
    for d in sorted(days, reverse=True)[:60]:
        w = weather.get(d) or {}
        wind = None
        if w.get("wind_speed") is not None:
            wind = (w.get("wind_dir") or "?") + " " + str(w["wind_speed"]) + " м/с"
        table.append({"day": d, "posts": len(days[d]), "t_day": w.get("t_day"),
                      "t_night": w.get("t_night"), "wind": wind, "pressure": w.get("pressure"),
                      "precip": w.get("precip"), "moon": moon_phase(d), "links": days[d][:5]})

    dates, st_l, ct_l, rm_l = [], [], [], []
    total_st = total_ct = 0
    last_stock = None
    if day_events:
        cur = date.fromisoformat(min(day_events))
        end = date.fromisoformat(max(max(day_events), str(date.today())))
        rem = 0
        while cur <= end:
            ds = str(cur)
            ev = day_events.get(ds, {})
            s = ev.get("stock", {}).get("kg", 0)
            c = ev.get("catch", {}).get("kg", 0)
            total_st += s
            total_ct += c
            rem = max(0, rem + s - c)
            if s:
                last_stock = ds
            dates.append(ds)
            st_l.append(s)
            ct_l.append(c)
            rm_l.append(rem)
            cur += timedelta(days=1)

    events = []
    for d in sorted(day_events, reverse=True)[:40]:
        for k in ("stock", "catch"):
            if k in day_events[d]:
                e = day_events[d][k]
                events.append({"day": d, "type": "запуск" if k == "stock" else "вылов",
                               "kg": e["kg"], "url": e["url"], "quote": e["quote"]})

    reports.sort(key=lambda r: r["day"], reverse=True)
    tl = defaultdict(int)
    tu = defaultdict(int)
    for r in reports:
        if r["location"]:
            tl[r["location"]] += 1
        if r["lure"]:
            tu[r["lure"]] += 1

    cw = weather.get(str(date.today())) or {}
    balance = {"start": BALANCE_START, "total_stocked": total_st, "total_caught": total_ct,
               "remaining": rm_l[-1] if rm_l else 0,
               "days_since_stock": (date.today() - date.fromisoformat(last_stock)).days if last_stock else None,
               "series": {"dates": dates, "stocked": st_l, "caught": ct_l, "remaining": rm_l},
               "events": events}

    payload = json.dumps({
        "stats": stats, "table": table, "balance": balance,
        "current_weather": {"temp": cw.get("t_day"), "pressure": cw.get("pressure"),
                            "precip": cw.get("precip"), "moon": moon_phase(str(date.today()))},
        "llm_time": llm_time, "moon_stats": moon_stats, "reports": reports[:80],
        "top_locations": dict(sorted(tl.items(), key=lambda x: -x[1])[:12]),
        "top_lures": dict(sorted(tu.items(), key=lambda x: -x[1])[:12]),
    }, ensure_ascii=False).replace("</", "<\\/")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(TEMPLATE.replace("__DATA__", payload))
    print("Sait sobran. Ostatok " + str(balance["remaining"]) + " kg, otchetov " + str(len(reports)) + ", LLM " + str(analyzed))


def main():
    os.makedirs(PAGES_DIR, exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    db.execute("CREATE TABLE IF NOT EXISTS posts (post_id TEXT PRIMARY KEY, page INT, author TEXT, post_dt TEXT, text TEXT)")
    state = load_state()
    last = download(db, state)
    build(db, state, last)
    db.close()
    print("Gotovo!")


main()
