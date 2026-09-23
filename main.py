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

LLM_PROMPT = "Ты анализируешь отчёт рыбака с форелевого пруда.\nОпредели, в какие периоды суток форель КЛЕВАЛА, а в какие НЕ клевала.\nПериоды строго: \"утро\", \"день\", \"вечер\", \"ночь\".\nУчитывай отрицания: «утром тишина, вечером раздача» = утро не клевало, вечер клевало.\nОтветь строго одним JSON без пояснений:\n{\"bite\": [\"вечер\"], \"no_bite\": [\"утро\"], \"confident\": true}\nЕсли ничего не понятно про время клёва:\n{\"bite\": [], \"no_bite\": [], \"confident\": false}\n\nТекст отчёта:\n"

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
BALANCE_KW_RX = re.compile(r"подушк\w*|накоплени", re.I)
LOCATION_RX = re.compile(r"основной водо[её]м|дальний угол|у плотин\w*|у коряг\w*|у входа|у выхода|мелководь\w*|у берега|у причала|у мостка|у дамбы|у кустов|у травы|понтон\w*|пантон\w*|бабий угол|женский угол|пляж|под дубами|под ивой|под администрацией|под стадионом|на запуске|спорт зон\w*", re.I)
LURE_RX = re.compile(r"вертушк\w*|воблер\w*|резин\w*|мушк\w*|блесна|черв\w*|опарыш\w*|мотыл\w*|пенопласт|тесто|сыр|бойл\w*|силикон\w*|твистер\w*|виброхвост\w*|мормышк\w*|магот\w*|светонакоп\w*|стрейч|бобриный хвост|пламп\w*|паста|креветк\w*|кукуруз\w*", re.I)
SUCCESS_RX = re.compile(r"поймал|словил|взял|вытащил|выловил|отловил|клевал|клюнул|в улове", re.I)
TIME_HINT_RX = re.compile(r"утр|днём|днем|вечер|ноч|рассвет|закат|клев|клёв", re.I)
BAD_BETWEEN_RX = re.compile(r"корм|прикорм|пеллет|смес", re.I)
SENTENCE_RX = re.compile(r"[.!?]")

WIND_DIRS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]
MOON_ORDER = ["новолуние", "растущий серп", "первая четверть", "растущая", "полнолуние", "убывающая", "последняя четверть", "убывающий серп"]
TIME_PERIODS = ["утро", "день", "вечер", "ночь"]


def norm_loc(s):
    s = (s or "").lower().strip()
    if "понтон" in s or "пантон" in s:
        return "понтон"
    if "стадион" in s:
        return "под стадионом"
    if "дуб" in s:
        return "под дубами"
    if "запуск" in s:
        return "на запуске"
    if "спорт" in s:
        return "спорт зона"
    if "угол" in s:
        return "дальний угол"
    return s

def norm_lure(s):
    s = (s or "").lower().strip()
    if "резин" in s:
        return "резина"
    if "светонакоп" in s:
        return "стрейч (светонакопительный)"
    if "стрейч" in s:
        return "стрейч"
    if "магот" in s:
        return "магот"
    if "паста" in s or "сыр" in s:
        return "паста (сыр)"
    if "кукуруз" in s:
        return "кукуруза"
    if "черв" in s:
        return "червь"
    if "пламп" in s:
        return "пламп"
    if "опарыш" in s:
        return "опарыш"
    return s


TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0b1221">
<title>Форель Красногорск</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#x1F41F;</text></svg>">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box}
html{background:#0b1221}
body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;margin:0 auto;padding:18px 12px 40px;color:#e2e8f0;max-width:860px;background:radial-gradient(700px 340px at 88% -60px,rgba(56,189,248,.14),transparent 70%),radial-gradient(560px 300px at -70px 220px,rgba(167,139,250,.10),transparent 70%),radial-gradient(600px 320px at 110% 65%,rgba(251,191,36,.06),transparent 70%);background-attachment:fixed}
a{color:#7dd3fc;text-decoration:none}
a:hover{text-decoration:underline}
.note{font-size:.75rem;color:#94a3b8;line-height:1.55}
.card{padding:14px}
.big{font-size:2.1rem;font-weight:900;color:#fbbf24;text-shadow:0 0 24px rgba(251,191,36,.35);letter-spacing:.5px;margin:2px 0 8px}
.hero{margin:4px 2px 16px}
.ttl{display:flex;align-items:center;gap:12px}
h1{margin:0;font-size:1.75rem;font-weight:900;letter-spacing:.3px;background:linear-gradient(92deg,#7dd3fc 0%,#38bdf8 35%,#a78bfa 70%,#fbbf24 100%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:#7dd3fc}
.hero p{margin:7px 0 0;color:#94a3b8;font-size:.83rem;letter-spacing:.4px}
details{margin:12px 0;border:1px solid rgba(148,163,184,.16);border-radius:16px;overflow:hidden;background:linear-gradient(180deg,rgba(30,41,59,.92),rgba(21,31,52,.92));box-shadow:0 10px 30px rgba(2,6,23,.45);transition:border-color .2s}
details[open]{border-color:rgba(56,189,248,.30)}
summary{position:relative;padding:13px 42px 13px 15px;font-weight:800;color:#7dd3fc;cursor:pointer;list-style:none;user-select:none;background:linear-gradient(90deg,rgba(56,189,248,.09),transparent 65%)}
summary:hover{color:#bae6fd}
summary::-webkit-details-marker{display:none}
summary::after{content:"\\25BE";position:absolute;right:15px;top:50%;transform:translateY(-50%);color:#64748b;transition:transform .25s}
details[open] summary::after{transform:translateY(-50%) rotate(180deg);color:#38bdf8}
#topbar{display:flex;flex-direction:column;background:linear-gradient(180deg,rgba(30,41,59,.95),rgba(21,31,52,.95));border:1px solid rgba(148,163,184,.16);border-radius:16px;padding:4px 15px;margin:0 0 14px;box-shadow:0 10px 30px rgba(2,6,23,.45)}
.trow{display:flex;align-items:center;gap:12px;padding:10px 0}
.trow+.trow{border-top:1px dashed rgba(148,163,184,.15)}
.ticon{width:38px;height:38px;flex:none;display:flex;align-items:center;justify-content:center;font-size:1.1rem;border-radius:12px;background:rgba(56,189,248,.10);border:1px solid rgba(56,189,248,.22)}
.tlabel{color:#94a3b8;font-size:.74rem;text-transform:uppercase;letter-spacing:.8px;width:88px;flex:none}
.trow b{font-size:.95rem;color:#f1f5f9;font-weight:700}
.badge{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;font-weight:900;font-size:.7rem;color:#fff;vertical-align:middle}
.badge.z{background:linear-gradient(135deg,#34d399,#16a34a);box-shadow:0 0 10px rgba(52,211,153,.45)}
.badge.v{background:linear-gradient(135deg,#fb7185,#dc2626);box-shadow:0 0 10px rgba(248,113,113,.45)}
.badge-success{display:inline-block;background:rgba(16,185,129,.15);color:#34d399;border:1px solid rgba(16,185,129,.35);padding:2px 7px;border-radius:5px;font-weight:800;font-size:.66rem;letter-spacing:.4px;white-space:nowrap}
.price{display:inline-block;background:rgba(251,191,36,.10);border:1px solid rgba(251,191,36,.30);color:#fbbf24;font-weight:800;padding:4px 12px;border-radius:999px;font-size:.82rem;white-space:nowrap}
.pricelist td{padding:9px 6px}
.pr{text-align:right;white-space:nowrap}
.rules{list-style:none;margin:12px 0 2px;padding:0;display:grid;gap:7px;font-size:.84rem}
.rules li{background:rgba(148,163,184,.06);border:1px solid rgba(148,163,184,.12);border-radius:11px;padding:9px 12px;line-height:1.45}
.rules b{color:#fbbf24}
.btnrow{display:flex;gap:10px;flex-wrap:wrap;margin-top:13px}
.btn{display:inline-flex;align-items:center;gap:8px;padding:10px 15px;border-radius:12px;font-weight:800;font-size:.85rem;text-decoration:none;transition:transform .15s}
.btn:hover{transform:translateY(-1px);text-decoration:none}
.btn-call{background:linear-gradient(135deg,#0ea5e9,#38bdf8);color:#04263f;box-shadow:0 6px 16px rgba(56,189,248,.30)}
.btn-map{background:rgba(56,189,248,.10);border:1px solid rgba(56,189,248,.35);color:#7dd3fc}
table{width:100%;border-collapse:collapse;font-size:.75rem;min-width:480px;background:rgba(15,23,42,.35)}
td,th{padding:7px 6px;border-bottom:1px solid rgba(51,65,85,.7);text-align:left;vertical-align:middle}
th{background:rgba(30,41,59,.85);color:#93c5fd;font-size:.7rem;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover td{background:rgba(56,189,248,.05)}
.scrollx{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid rgba(148,163,184,.14);border-radius:10px;margin:4px 0}
.scrollx::-webkit-scrollbar{height:8px}
.scrollx::-webkit-scrollbar-thumb{background:#334155;border-radius:4px}
.narrow{min-width:0}
.chartbox{position:relative;height:240px;width:100%}
footer{margin-top:20px;text-align:center}
</style>
</head>
<body>
<header class="hero">
<div class="ttl"><h1>&#x1F41F; Форель в Красногорске</h1></div>
<p>погода &#8226; запуски &#8226; баланс водоёма &#8226; отчёты рыбаков</p>
</header>
<div id="topbar">
<div class="trow"><span class="ticon">&#x1F4C5;</span><span class="tlabel">Дата</span><b id="curDate">-</b></div>
<div class="trow"><span class="ticon">&#x23F0;</span><span class="tlabel">Время</span><b id="curTime">-</b></div>
<div class="trow"><span class="ticon">&#x1F321;</span><span class="tlabel">Погода</span><b><span id="curTemp">-</span> &#x2103;</b></div>
<div class="trow"><span class="ticon">&#x1F4CA;</span><span class="tlabel">Давление</span><b><span id="curPress">-</span> мм рт. ст.</b></div>
<div class="trow"><span class="ticon">&#x1F319;</span><span class="tlabel">Луна</span><b id="curMoon">-</b></div>
</div>
<details open><summary>&#x1F3AB; Условия рыбалки и цены</summary><div class="card">
<div class="scrollx"><table class="narrow pricelist">
<tr><td>&#x1F305; 07:00 &#x2013; 18:00</td><td class="pr"><span class="price">4 000 &#x20BD;</span></td></tr>
<tr><td>&#x1F307; 12:00 &#x2013; 18:00</td><td class="pr"><span class="price">2 200 &#x20BD;</span></td></tr>
<tr><td>&#x1F319; 18:00 &#x2013; 06:00</td><td class="pr"><span class="price">4 000 &#x20BD;</span></td></tr>
<tr><td>&#x23F3; Сутки &#x2014; 24 часа с момента прибытия</td><td class="pr"><span class="price">5 000 &#x20BD;</span></td></tr>
<tr><td>&#x2B50; Приоритетный час</td><td class="pr"><span class="price">300 &#x20BD;</span></td></tr>
<tr><td>&#x2795; Дополнительная снасть (1 шт.)</td><td class="pr"><span class="price">500 &#x20BD;</span></td></tr>
</table></div>
<ul class="rules">
<li>Разрешено <b>2 снасти</b>, на каждой не более 2 крючков</li>
<li>Спиннинг разрешён</li>
<li>Нормы вылова нет</li>
<li>Женщина и ребёнок до 13 лет ловят <b>бесплатно</b> &#x2014; на снасти рыбака, оплатившего путёвку</li>
<li>На запуске форели ловит <b>1 человек из семьи</b>, остальные &#x2014; вне зоны запуска</li>
<li>Пеллетс и блёсна с тройниками запрещены</li>
</ul>
<div class="btnrow">
<a class="btn btn-call" href="tel:+79852620637">&#x1F4DE; +7 985 262-06-37</a>
<a class="btn btn-map" href="https://yandex.ru/maps/?pt=37.322979,55.840619&amp;z=15&amp;l=map" target="_blank">&#x1F4CD; 55.840619, 37.322979</a>
</div>
<p class="note" style="margin-top:11px">Цены и правила обновляются вручную.</p>
</div></details>
<details open><summary>&#x1F41F; Остаток форели в водоёме</summary><div class="card">
<div class="big" id="rem">-</div>
<div class="note">запущено <b id="st" style="color:#4ade80">0</b> кг &#8226; выловлено <b id="ct" style="color:#f87171">0</b> кг &#8226; отсчёт с <span id="bs"></span><br>последний запуск: <span id="dsl">-</span> &#8226; обновлено <span id="upd"></span><span id="pend"></span></div>
<div class="note" style="margin-top:6px">Сегодняшний запуск учитывается в остатке только после отчёта о вылове за день.</div>
</div></details>
<details open><summary>&#x1F4CA; Баланс</summary><div class="card" id="balbox"><div class="chartbox"><canvas id="bal"></canvas></div></div></details>
<details><summary>&#x1F4D3; Журнал запусков и выловов</summary><div class="card">
<div class="scrollx"><table id="ev"></table></div>
<div class="note" style="margin-top:10px"><span class="badge z">З</span> &#x2014; запуск форели &#8226; <span class="badge v">В</span> &#x2014; вылов за день</div>
</div></details>
<details><summary>Когда клюёт (анализ LLM)</summary><div class="card">
<div class="note" id="llmnote"></div><div class="chartbox"><canvas id="llmchart"></canvas></div>
<div class="note">Отчёты прочитаны языковой моделью.</div>
</div></details>
<details><summary>Луна и клёв</summary><div class="card">
<div class="chartbox"><canvas id="moonchart"></canvas></div>
<div class="note">Средняя активность отчётов в каждой фазе луны с 2024 года.</div>
</div></details>
<details><summary>Активность обсуждений с 2024</summary><div class="card">
<div class="note" id="prog"></div>
<div class="big" style="color:#38bdf8;text-shadow:0 0 24px rgba(56,189,248,.35)" id="total">0</div>
<div class="note">постов про форель за <span id="days">0</span> дней</div>
<h3 style="font-size:.9rem;color:#7dd3fc">По месяцам</h3><div class="chartbox"><canvas id="m"></canvas></div>
<h3 style="font-size:.9rem;color:#7dd3fc">Клёв и давление</h3><div class="chartbox"><canvas id="p"></canvas></div>
<h3 style="font-size:.9rem;color:#7dd3fc">Последние активные дни</h3><div class="scrollx"><table id="t"></table></div>
<div class="note">t день &#x2014; максимум, t ночь &#x2014; минимум за сутки.</div>
</div></details>
<details open><summary>Где и на что ловят (точки и приманки)</summary><div class="card">
<h3 style="font-size:.9rem;color:#93c5fd;margin:2px 0 6px">Популярные локации</h3><div class="scrollx"><table id="toploc" style="min-width:100%"></table></div>
<h3 style="font-size:.9rem;color:#93c5fd;margin:14px 0 6px">Топ рабочих приманок</h3><div class="chartbox"><canvas id="lure"></canvas></div>
<h3 style="font-size:.9rem;color:#93c5fd;margin:14px 0 6px">Последние отчёты с водоёма</h3><div class="scrollx"><table id="reports"></table></div>
<div class="note">Кликните по тексту отчёта, чтобы открыть оригинальное сообщение на форуме Rusfishing.</div>
</div></details>
<footer><p class="note">Данные собираются с форума rusfishing.ru</p></footer>
<script type="application/json" id="sitedata">__DATA__</script>
<script>
var D={};
try{D=JSON.parse(document.getElementById('sitedata').textContent)}catch(e){console.error(e)}
try{
if(window.Chart){Chart.defaults.color='#94a3b8';Chart.defaults.borderColor='rgba(51,65,85,.5)';Chart.defaults.font.family="system-ui,-apple-system,'Segoe UI',sans-serif"}
function topInfo(){
var now=new Date();
document.getElementById('curDate').textContent=now.toLocaleDateString('ru-RU',{weekday:'short',day:'numeric',month:'long',year:'numeric'});
var cw=D.current_weather||{};
document.getElementById('curTemp').textContent=(cw.temp==null?'-':cw.temp);
document.getElementById('curPress').textContent=(cw.pressure==null?'-':cw.pressure);
document.getElementById('curMoon').textContent=(cw.moon==null?'-':cw.moon)}
function tick(){document.getElementById('curTime').textContent=new Date().toLocaleTimeString('ru-RU')}
topInfo();tick();setInterval(tick,1000);setInterval(topInfo,60000);
var B=D.balance||{};
document.getElementById('bs').textContent=B.start||'';
document.getElementById('st').textContent=B.total_stocked||0;
document.getElementById('ct').textContent=B.total_caught||0;
document.getElementById('rem').textContent=(B.events&&B.events.length)?('Примерно '+(B.remaining||0)+' кг'):'нет данных';
var dss=B.days_since_stock;
document.getElementById('dsl').textContent=(dss==null)?'нет данных':(dss<=0?'сегодня':dss+' дн. назад');
document.getElementById('upd').textContent=(D.stats&&D.stats.updated)||'';
var tps=B.today_pending_stock||0;
document.getElementById('pend').textContent=(tps>0)?(' • сегодня запущено '+tps+' кг, в остаток попадёт после отчёта о вылове'):'';
if(B.series&&B.series.dates&&B.series.dates.length){
new Chart(document.getElementById('bal'),{data:{labels:B.series.dates,datasets:[
{type:'line',label:'Остаток, кг',data:B.series.remaining,borderColor:'#fbbf24',backgroundColor:'rgba(251,191,36,.10)',fill:true,pointRadius:0,borderWidth:2,tension:.35},
{type:'bar',label:'Запуск',data:B.series.stocked,backgroundColor:'#34d399',borderRadius:3,maxBarThickness:20},
{type:'bar',label:'Вылов',data:B.series.caught,backgroundColor:'#f87171',borderRadius:3,maxBarThickness:20}]},
options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{color:'#e2e8f0',boxWidth:12}}},scales:{x:{ticks:{color:'#94a3b8',maxTicksLimit:8}},y:{ticks:{color:'#94a3b8'}}}}})
}else{document.getElementById('balbox').innerHTML='<div class="note">Пока нет данных о запусках.</div>'}
if(B.events&&B.events.length){
document.getElementById('ev').innerHTML='<thead><tr><th>Дата</th><th style="text-align:center">Тип</th><th>кг</th><th>Комментарий</th></tr></thead><tbody>'+B.events.map(function(e){
var z=e.type==='запуск';
return '<tr><td style="white-space:nowrap"><b>'+e.day+'</b></td><td style="text-align:center"><span class="badge '+(z?'z':'v')+'">'+(z?'З':'В')+'</span></td><td><b style="color:'+(z?'#4ade80':'#f87171')+'">'+e.kg+' кг</b></td><td class="note"><a href="'+e.url+'" target="_blank">'+e.quote+'</a></td></tr>'
}).join('')+'</tbody>'
}else{document.getElementById('ev').innerHTML='<tr><td class="note">Пока нет записей.</td></tr>'}
var LT=D.llm_time||{};
if(LT.analyzed>0){
document.getElementById('llmnote').textContent='Проанализировано отчётов: '+LT.analyzed;
new Chart(document.getElementById('llmchart'),{type:'bar',data:{labels:LT.labels,datasets:[
{label:'Клевало',data:LT.bite,backgroundColor:'#4ade80',borderRadius:4},
{label:'Не клевало',data:LT.no_bite,backgroundColor:'#f87171',borderRadius:4}]},
options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#e2e8f0',boxWidth:12}}},scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'},beginAtZero:true}}}})
}else{
document.getElementById('llmnote').textContent=LT.enabled?'Отчёты ещё не проанализированы.':'LLM отключён (нет ключа).';
document.getElementById('llmchart').parentNode.style.display='none'}
var M=D.moon_stats||{};
if(M.labels&&M.labels.length){new Chart(document.getElementById('moonchart'),{type:'bar',data:{labels:M.labels,datasets:[{label:'Постов в день',data:M.values,backgroundColor:'#a78bfa',borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'},beginAtZero:true}}}})}
if(D.stats){
document.getElementById('prog').textContent='Собрано страниц: '+D.stats.collected+' из '+D.stats.need+' ('+D.stats.pct+'%)';
document.getElementById('total').textContent=D.stats.total_posts||0;
document.getElementById('days').textContent=D.stats.active_days||0;
if(D.stats.monthly){new Chart(document.getElementById('m'),{type:'bar',data:{labels:Object.keys(D.stats.monthly),datasets:[{data:Object.values(D.stats.monthly),backgroundColor:'#38bdf8',borderRadius:3,maxBarThickness:14}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#94a3b8',maxTicksLimit:12}},y:{ticks:{color:'#94a3b8'}}}}})}
if(D.stats.pressure){new Chart(document.getElementById('p'),{type:'bar',data:{labels:Object.keys(D.stats.pressure),datasets:[{data:Object.values(D.stats.pressure),backgroundColor:['#ef4444','#eab308','#22c55e'],borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'},beginAtZero:true}}}})}
}
if(D.table&&D.table.length){
document.getElementById('t').innerHTML='<thead><tr><th>Дата</th><th>Постов</th><th>t день</th><th>t ночь</th><th>Ветер</th><th>Давл.</th><th>Осадки</th><th>Луна</th><th>Ссылки</th></tr></thead><tbody>'+D.table.map(function(r){
var links=(r.links||[]).map(function(u,i){return '<a href="'+u+'" target="_blank">#'+(i+1)+'</a>'}).join(' ');
return '<tr><td><b>'+r.day+'</b></td><td>'+r.posts+'</td><td>'+(r.t_day==null?'-':r.t_day)+'</td><td>'+(r.t_night==null?'-':r.t_night)+'</td><td>'+(r.wind||'-')+'</td><td>'+(r.pressure==null?'-':r.pressure)+'</td><td>'+(r.precip==null?'-':r.precip)+'</td><td>'+(r.moon||'-')+'</td><td>'+links+'</td></tr>'
}).join('')+'</tbody>'}
if(D.top_locations&&Object.keys(D.top_locations).length){
document.getElementById('toploc').innerHTML='<thead><tr><th>Локация / зона на водоёме</th><th style="text-align:right">Упоминаний</th></tr></thead><tbody>'+Object.keys(D.top_locations).map(function(k){
return '<tr><td>'+k+'</td><td style="text-align:right"><b style="color:#38bdf8">'+D.top_locations[k]+'</b></td></tr>'}).join('')+'</tbody>'
}else{document.getElementById('toploc').innerHTML='<tr><td class="note">Пока нет данных.</td></tr>'}
if(D.top_lures&&Object.keys(D.top_lures).length){new Chart(document.getElementById('lure'),{type:'bar',data:{labels:Object.keys(D.top_lures),datasets:[{data:Object.values(D.top_lures),backgroundColor:'#38bdf8',borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#94a3b8'}},y:{ticks:{color:'#94a3b8'},beginAtZero:true}}}})}
if(D.reports&&D.reports.length){
document.getElementById('reports').innerHTML='<thead><tr><th>Дата</th><th>Успех</th><th>Рыбак</th><th>Точка</th><th>Приманка</th><th>Отчёт</th></tr></thead><tbody>'+D.reports.map(function(r){
var st=r.success?'<span class="badge-success">УЛОВ</span>':'<span style="color:#64748b">-</span>';
return '<tr><td style="white-space:nowrap">'+r.day+'</td><td>'+st+'</td><td><b>'+(r.author||'-')+'</b></td><td>'+(r.location||'-')+'</td><td>'+(r.lure||'-')+'</td><td class="note"><a href="'+r.url+'" target="_blank">'+r.quote+'</a></td></tr>'
}).join('')+'</tbody>'
}else{document.getElementById('reports').innerHTML='<tr><td class="note">Пока нет отчётов.</td></tr>'}
}catch(err){console.error(err)}
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
        out.append({"post_id": pid, "page": page, "author": m.get("data-author", ""),
                    "post_dt": (t.get("datetime") or "") if t else "",
                    "text": body.get_text("\n", strip=True)})
    return out

def total_pages(html):
    soup = BeautifulSoup(html, "lxml")
    nav = soup.select_one(".pageNav")
    if nav and nav.get("data-last"):
        try: return int(nav["data-last"])
        except Exception: pass
    nums = []
    for a in soup.select(".pageNav a"):
        s = a.get_text(strip=True).replace(" ", "")
        if s.isdigit(): nums.append(int(s))
    return max(nums) if nums else 1

def first_date(html):
    if not html: return ""
    soup = BeautifulSoup(html, "lxml")
    t = soup.select_one("article.message time")
    return (t.get("datetime") or "")[:10] if t else ""

def load_state():
    if not os.path.exists(STATE_FILE): return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False)

def snippet(text, pos, width=90):
    a = max(0, pos - 15); b = min(len(text), pos + width)
    return re.sub(r"\s+", " ", text[a:b]).strip()

def wind_dir_name(deg):
    if deg is None: return None
    return WIND_DIRS[int((deg + 22.5) // 45) % 8]

def moon_phase(day_str):
    try: d = date.fromisoformat(day_str)
    except Exception: return None
    age = ((d - date(2000, 1, 6)).days) % 29.530588853
    return MOON_ORDER[min(7, int(age / 3.6913))]

def llm_chat(prompt):
    try:
        r = requests.post(LLM_API_URL,
            headers={"Authorization": "Bearer " + LLM_API_KEY, "Content-Type": "application/json"},
            json={"model": LLM_MODEL, "temperature": 0, "max_tokens": 200,
                  "messages": [{"role": "user", "content": prompt}]}, timeout=90)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print("LLM error:", e); return None

def parse_llm_json(raw):
    if not raw: return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m: return None
    try: d = json.loads(m.group(0))
    except Exception: return None
    return {"bite": [p for p in (d.get("bite") or []) if p in TIME_PERIODS],
            "no_bite": [p for p in (d.get("no_bite") or []) if p in TIME_PERIODS],
            "confident": bool(d.get("confident"))}

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
            if res is None: res = {"bite": [], "no_bite": [], "confident": False}
            db.execute("INSERT OR REPLACE INTO llm_cache VALUES (?,?,?)",
                       (pid, day, json.dumps(res, ensure_ascii=False)))
            db.commit()
            cached[pid] = json.dumps(res, ensure_ascii=False)
            print("  " + str(i + 1) + "/" + str(len(todo)))
            time.sleep(1.0)
    agg = {}
    for p in TIME_PERIODS: agg[p] = {"bite": 0, "no_bite": 0}
    ids = set(c[0] for c in cands); n = 0
    for pid, raw in cached.items():
        if pid not in ids: continue
        try: res = json.loads(raw)
        except Exception: continue
        if not res.get("confident"): continue
        used = False
        for p in res.get("bite", []):
            if p in agg: agg[p]["bite"] += 1; used = True
        for p in res.get("no_bite", []):
            if p in agg: agg[p]["no_bite"] += 1; used = True
        if used: n += 1
    return agg, n

def resolve_event_date(text, start, end, post_dt):
    pd = (post_dt or "")[:10]
    try: py = int(pd[:4])
    except Exception: py = date.today().year
    ls = text.rfind("\n", 0, start); ls = 0 if ls == -1 else ls + 1
    le = text.find("\n", end)
    if le == -1: le = len(text)
    line = text[ls:le]
    for scope in (line, text[max(0, start - 40):min(len(text), end + 40)]):
        m = DATE_RX.search(scope)
        if not m: continue
        try:
            dd = int(m.group(1)); mm = int(m.group(2)); ry = m.group(3)
            if ry:
                yy = int(ry)
                y = 2000 + yy if len(ry) == 2 and yy < 50 else (1900 + yy if len(ry) == 2 else yy)
            else: y = py
            if 1 <= dd <= 31 and 1 <= mm <= 12:
                return ("%04d-%02d-%02d" % (y, mm, dd), True)
        except Exception: pass
    return pd, False

def kind_for(text, kws, start, end):
    lefts = [k for k in kws if k[1] <= start]
    if lefts:
        ks, ke, kind = lefts[-1]
        if start - ke <= 200 and not BAD_BETWEEN_RX.search(text[ke:start]): return kind
    rights = [k for k in kws if k[0] >= end]
    if rights:
        ks, ke, kind = rights[0]
        between = text[end:ks]
        if ks - end <= 200 and not SENTENCE_RX.search(between) and not BAD_BETWEEN_RX.search(between): return kind
    return None

def find_events(text, post_dt):
    if not text: return []
    pd = (post_dt or "")[:10]
    kws = []
    for m in STOCK_KW_RX.finditer(text): kws.append((m.start(), m.end(), "stock"))
    for m in CATCH_KW_RX.finditer(text): kws.append((m.start(), m.end(), "catch"))
    kws.sort()
    out = []
    for m in KG_RX.finditer(text):
        s, e = m.span()
        before = text[max(0, s - 45):s].lower()
        if re.search(r"\u043D\u0430\u0432\u0435\u0441\u043A\w*[^0-9]{0,25}$", before): continue
        if OTHER_FISH.search(text[max(0, s - 25):min(len(text), e + 25)]): continue
        if BALANCE_KW_RX.search(text[max(0, s - 80):s]): continue
        kind = kind_for(text, kws, s, e)
        if kind is None: continue
        try:
            v1 = float(m.group(1).replace(",", ".")); v2 = m.group(2)
            val = (v1 + float(v2.replace(",", "."))) / 2 if v2 else v1
            unit = (m.group(3) or "").lower()
            if unit.startswith("тон") or unit == "т": val *= 1000
            kg = int(round(val))
        except Exception: continue
        if kind == "stock" and not (30 <= kg <= 20000): continue
        if kind == "catch" and not (5 <= kg <= 20000): continue
        if kind == "stock":
            ctx = text[max(0, s - 250):min(len(text), e + 250)]
            if not FOREL_RX.search(ctx) and OTHER_FISH.search(ctx): continue
            ed, dated = resolve_event_date(text, s, e, post_dt)
            if not dated:
                # Смотрим, что написано перед цифрой: «завтра» или «сегодня».
                pre = text[max(0, s - 70):s].lower()
                pos_z = pre.rfind("завтра")
                pos_s = pre.rfind("сегодня")
                if pos_z != -1 and pos_z > pos_s:
                    # Анонс на завтра: датируем завтрашним днём.
                    # Сегодня в баланс он не попадёт (d > today), учтётся завтра.
                    try:
                        ed = str(date.fromisoformat(pd) + timedelta(days=1))
                        dated = True
                    except Exception:
                        continue
                elif FUTURE_RX.search(pre):
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
        tmax = r.get("temperature_2m_max") or []; tmin = r.get("temperature_2m_min") or []
        pr = r.get("precipitation_sum") or []; ps = r.get("pressure_msl_mean") or []
        ws = r.get("windspeed_10m_max") or []; wd = r.get("winddirection_10m_dominant") or []
        for i, d in enumerate(r.get("time") or []):
            w[d] = {"t_day": tmax[i] if i < len(tmax) else None, "t_night": tmin[i] if i < len(tmin) else None,
                    "precip": pr[i] if i < len(pr) else None,
                    "pressure": round(ps[i] * 0.75006, 1) if i < len(ps) and ps[i] is not None else None,
                    "wind_speed": round(ws[i] / 3.6, 1) if i < len(ws) and ws[i] is not None else None,
                    "wind_dir": wind_dir_name(wd[i] if i < len(wd) else None)}
    except Exception as e: print("archive weather:", e)
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast",
            params={"latitude": 55.82, "longitude": 37.33,
                    "start_date": str(today - timedelta(days=2)), "end_date": str(today + timedelta(days=1)),
                    "hourly": "temperature_2m,precipitation,pressure_msl,windspeed_10m,winddirection_10m",
                    "timezone": "Europe/Moscow"}, timeout=60).json().get("hourly") or {}
        times = r.get("time") or []; tt = r.get("temperature_2m") or []; pp = r.get("precipitation") or []
        ss = r.get("pressure_msl") or []; vv = r.get("windspeed_10m") or []; dd = r.get("winddirection_10m") or []
        buckets = defaultdict(list)
        for i, s in enumerate(times): buckets[s[:10]].append(i)
        for day, idx in buckets.items():
            temps = [tt[i] for i in idx if i < len(tt) and tt[i] is not None]
            precs = [pp[i] for i in idx if i < len(pp) and pp[i] is not None]
            press = [ss[i] for i in idx if i < len(ss) and ss[i] is not None]
            winds = [vv[i] for i in idx if i < len(vv) and vv[i] is not None]
            rec = w.get(day) or {}
            if temps:
                if rec.get("t_day") is None: rec["t_day"] = round(max(temps), 1)
                if rec.get("t_night") is None: rec["t_night"] = round(min(temps), 1)
            if precs and rec.get("precip") is None: rec["precip"] = round(sum(precs), 1)
            if press and rec.get("pressure") is None: rec["pressure"] = round(sum(press) / len(press) * 0.75006, 1)
            if winds and rec.get("wind_speed") is None: rec["wind_speed"] = round(max(winds) / 3.6, 1)
            if rec.get("wind_dir") is None and idx:
                mid = idx[len(idx) // 2]
                if mid < len(dd): rec["wind_dir"] = wind_dir_name(dd[mid])
            w[day] = rec
    except Exception as e: print("forecast weather:", e)
    return w

def download(db, state):
    html = fetch(page_url(1))
    if not html: print("Forum ne otvetil"); return state.get("newest", 1)
    last = total_pages(html); print("Vsego stranic:", last)
    if not state.get("start_page"):
        print("Ischu 2024 god...")
        lo, hi = 1, last
        while lo < hi:
            mid = (lo + hi) // 2; h = fetch(page_url(mid)); fd = first_date(h) if h else ""
            print(" str." + str(mid) + ": " + (fd or "?")); time.sleep(1.5)
            if not fd or fd >= START_DATE: hi = mid
            else: lo = mid + 1
        state["start_page"] = max(1, lo - 1); state["cursor"] = last; state["newest"] = last
    start_page = state["start_page"]; todo = []
    if last > state.get("newest", last): todo += list(range(state["newest"] + 1, last + 1))
    state["newest"] = last
    cur = state.get("cursor", last); added = []
    while len(added) < BATCH and cur >= start_page:
        if not os.path.exists(PAGES_DIR + "/page_%06d.json" % cur): added.append(cur)
        cur -= 1
    state["cursor"] = cur
    tail = list(range(max(start_page, last - REFRESH_TAIL + 1), last + 1))
    todo = sorted(set(todo + added + tail)); print("Zagruzhau " + str(len(todo)) + " stranic")
    for i, p in enumerate(todo):
        h = fetch(page_url(p))
        if h:
            posts = parse_posts(h, p)
            if posts:
                with open(PAGES_DIR + "/page_%06d.json" % p, "w", encoding="utf-8") as f: json.dump(posts, f, ensure_ascii=False)
                print(" " + str(i + 1) + "/" + str(len(todo)) + " str." + str(p) + ": " + str(len(posts)))
        time.sleep(random.uniform(1.2, 2.0))
        if (i + 1) % 20 == 0: save_state(state)
    for fn in os.listdir(PAGES_DIR):
        if not fn.endswith(".json"): continue
        try:
            with open(PAGES_DIR + "/" + fn, encoding="utf-8") as f:
                for post in json.load(f):
                    db.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?)",
                               (post.get("post_id", ""), post.get("page", 0),
                                post.get("author", ""), post.get("post_dt", ""), post.get("text", "")))
            db.commit()
        except Exception as e: print("file err", fn, e)
    save_state(state); return last

def build(db, state, last_page):
    days = defaultdict(list)
    stock_c = defaultdict(list)
    catch_c = defaultdict(list)
    reports = []
    llm_cands = []

    # Разбор всех постов
    for pid, page, author, dt, text in db.execute(
        "SELECT post_id, page, author, post_dt, text FROM posts"
    ):
        day = (dt or "")[:10]
        url = THREAD + "/page-" + str(page) + "#post-" + str(pid)
        text = text or ""

        # Посты про форель для общей статистики
        if day and day >= START_DATE and FOREL_RX.search(text):
            days[day].append(url)

        if not day:
            continue

        # Отчёты обычных рыбаков (для точек/приманок и LLM)
        if (
            day >= REPORT_START
            and (author or "") not in ADMIN_AUTHORS
            and FOREL_RX.search(text)
        ):
            loc = LOCATION_RX.search(text)
            lure = LURE_RX.search(text)
            if loc or lure:
                anchor = loc or lure
                reports.append(
                    {
                        "day": day,
                        "author": author or "",
                        "location": norm_loc(loc.group(0)) if loc else None,
                        "lure": norm_lure(lure.group(0)) if lure else None,
                        "success": bool(SUCCESS_RX.search(text)),
                        "url": url,
                        "quote": snippet(text, anchor.start(), 110)[:150],
                    }
                )
            if TIME_HINT_RX.search(text):
                llm_cands.append((pid, day, text))

        # Ниже — только админы (запуски/баланс)
        if (author or "") not in ADMIN_AUTHORS:
            continue

        # Отсекаем сильно «старые» события до BALANCE_START
        if day < BALANCE_START:
            try:
                if (
                    date.fromisoformat(BALANCE_START) - date.fromisoformat(day)
                ).days > 10:
                    continue
            except Exception:
                continue

        # Парсим события запуск/вылов
        for ev in find_events(text, dt):
            d = ev["day"]
            if not d or d < BALANCE_START:
                continue

            # Не учитываем будущие (анонсированные) даты в балансе:
            # анонс «на завтра» сюда и попадает, сегодня он в расчёт не идёт
            if d > str(date.today()):
                continue

            if ev["kind"] == "stock" and d in IGNORE_STOCK_DAYS:
                continue

            rec = {
                "kg": ev["kg"],
                "url": url,
                "dt": dt,
                "pos": ev["pos"],
                "is_fact": (dt[:10] == d),
                "quote": (
                    "пост " + dt[5:10] + " " + dt[11:16] + " " + ev["quote"]
                )[:150],
            }

            if ev["kind"] == "stock":
                stock_c[d].append(rec)
            else:
                catch_c[d].append(rec)

    # По одному «лучшему» запуску/вылову в день
    day_events = {}
    for d, recs in stock_c.items():
        pool = [r for r in recs if r["is_fact"]] or recs
        day_events.setdefault(d, {})["stock"] = max(
            pool, key=lambda r: (r["dt"], r["pos"])
        )
    for d, recs in catch_c.items():
        day_events.setdefault(d, {})["catch"] = max(
            recs, key=lambda r: (r["dt"], r["pos"])
        )

    # Погода
    weather = load_weather()

    # LLM-анализ
    llm_cands.sort(key=lambda c: c[1], reverse=True)
    agg, analyzed = run_llm(db, llm_cands)
    llm_time = {
        "enabled": bool(LLM_API_KEY),
        "analyzed": analyzed,
        "labels": TIME_PERIODS,
        "bite": [agg[p]["bite"] for p in TIME_PERIODS],
        "no_bite": [agg[p]["no_bite"] for p in TIME_PERIODS],
    }

    # Луна, месяцы, давление
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
    moon_stats = {
        "labels": moon_labels,
        "values": [avg(moon_b[p]) for p in moon_labels],
        "days": [len(moon_b[p]) for p in moon_labels],
    }

    collected = len([f for f in os.listdir(PAGES_DIR) if f.endswith(".json")])
    need = max(
        1, state.get("newest", last_page) - state.get("start_page", last_page) + 1
    )

    stats = {
        "monthly": dict((k, avg(v)) for k, v in sorted(monthly.items())),
        "pressure": dict((k, avg(v)) for k, v in press_g.items()),
        "total_posts": sum(len(v) for v in days.values()),
        "active_days": len(days),
        "collected": collected,
        "need": need,
        "pct": round(collected / need * 100, 1),
        "updated": str(date.today()),
    }

    # Таблица последних активных дней
    table = []
    for d in sorted(days, reverse=True)[:60]:
        w = weather.get(d) or {}
        wind = None
        if w.get("wind_speed") is not None:
            wind = (w.get("wind_dir") or "?") + " " + str(w["wind_speed"]) + " м/с"
        table.append(
            {
                "day": d,
                "posts": len(days[d]),
                "t_day": w.get("t_day"),
                "t_night": w.get("t_night"),
                "wind": wind,
                "pressure": w.get("pressure"),
                "precip": w.get("precip"),
                "moon": moon_phase(d),
                "links": days[d][:5],
            }
        )

    # Ряд баланса по дням: только до сегодняшнего дня
    dates, st_l, ct_l, rm_l = [], [], [], []
    total_st = total_ct = 0
    last_stock = None

    if day_events:
        cur = date.fromisoformat(min(day_events))  # первый день с событием
        rem = 0
        today_obj = date.today()

        # Идём от первого события до сегодняшней даты включительно
        while cur <= today_obj:
            ds = str(cur)
            ev = day_events.get(ds, {})
            s = ev.get("stock", {}).get("kg", 0)
            c = ev.get("catch", {}).get("kg", 0)

            # Сегодняшний запуск в остаток не идём, пока за сегодня нет
            # отчёта о вылове. Появится вечерний отчёт («вылов X») —
            # учтём и запуск, и вылов, и остаток станет понятен.
            if cur == today_obj and s and not c:
                s = 0

            # «Последний запуск» показываем по факту события, даже если
            # сегодняшний запуск ещё не учтён в остатке.
            if ev.get("stock"):
                last_stock = ds

            total_st += s
            total_ct += c

            # Честный net, без max(0, ...): если вылов больше запуска,
            # остаток уходит в минус и вычитается из общего остатка.
            rem = rem + s - c

            dates.append(ds)
            st_l.append(s)
            ct_l.append(c)
            rm_l.append(rem)

            cur += timedelta(days=1)

    # Сколько кг сегодняшнего запуска ещё не учтено в остатке
    tev = day_events.get(str(date.today()), {}) if day_events else {}
    today_pending_stock = (
        tev["stock"]["kg"] if (tev.get("stock") and not tev.get("catch")) else 0
    )

    # Журнал запусков/выловов
    events = []
    for d in sorted(day_events, reverse=True)[:40]:
        for k in ("stock", "catch"):
            if k in day_events[d]:
                e = day_events[d][k]
                events.append(
                    {
                        "day": d,
                        "type": "запуск" if k == "stock" else "вылов",
                        "kg": e["kg"],
                        "url": e["url"],
                        "quote": e["quote"],
                    }
                )

    # Топ локаций и приманок
    reports.sort(key=lambda r: r["day"], reverse=True)
    tl = defaultdict(int)
    tu = defaultdict(int)
    for r in reports:
        if r["location"]:
            tl[norm_loc(r["location"])] += 1
        if r["lure"]:
            tu[norm_lure(r["lure"])] += 1

    cw = weather.get(str(date.today())) or {}

    balance = {
        "start": BALANCE_START,
        "total_stocked": total_st,
        "total_caught": total_ct,
        # Остаток может быть отрицательным — это честный net (запуск - вылов)
        "remaining": rm_l[-1] if rm_l else 0,
        "today_pending_stock": today_pending_stock,
        "days_since_stock": (
            (date.today() - date.fromisoformat(last_stock)).days if last_stock else None
        ),
        "series": {
            "dates": dates,
            "stocked": st_l,
            "caught": ct_l,
            "remaining": rm_l,
        },
        "events": events,
    }

    payload = json.dumps(
        {
            "stats": stats,
            "table": table,
            "balance": balance,
            "current_weather": {
                "temp": cw.get("t_day"),
                "pressure": cw.get("pressure"),
                "precip": cw.get("precip"),
                "moon": moon_phase(str(date.today())),
            },
            "llm_time": llm_time,
            "moon_stats": moon_stats,
            "reports": reports[:80],
            "top_locations": dict(
                sorted(tl.items(), key=lambda x: -x[1])[:12]
            ),
            "top_lures": dict(
                sorted(tu.items(), key=lambda x: -x[1])[:12]
            ),
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(TEMPLATE.replace("__DATA__", payload))

    print(
        "Sait sobran. Ostatok "
        + str(balance["remaining"])
        + " kg, otchetov "
        + str(len(reports))
        + ", LLM "
        + str(analyzed)
    )
    if today_pending_stock:
        print(
            "Segodnyashniy zapusk "
            + str(today_pending_stock)
            + " kg otlojen do vechernego otcheta o vylove"
        )

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
