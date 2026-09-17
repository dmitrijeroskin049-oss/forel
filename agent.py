import re
import datetime

# ==========================================
# 1. НАСТРОЙКИ И СЛОВАРИ ДЛЯ АНАЛИТИКИ
# ==========================================

# Исключаем эти даты из остатка (запуски будут видны в логе, но не пойдут в плюс)
# Внимание: Вы писали 2026 год, оставляю как просили. Если опечатка - поменяйте на 2023/2024.
EXCLUDE_STOCK_FROM_BALANCE = {
    "2026-09-04",
    "2026-09-05",
    "2026-09-06",
    "2026-09-07",
    "2026-09-08",
}

# Словари паттернов (используем регулярные выражения)
SPOT_PATTERNS = {
    "Аэратор": [r"\bаэратор\w*\b", r"\bу аэратора\b"],
    "Садки": [r"\bсадк\w*\b", r"\bу садков\b"],
    "Дамба": [r"\bдамб\w*\b", r"\bна дамбе\b"],
    "Левый берег": [r"\bлев(ый|ом)\s+берег\w*\b"],
    "Правый берег": [r"\bправ(ый|ом)\s+берег\w*\b"],
    "Угол": [r"\bугол\b", r"\bв углу\b"],
    "Центр": [r"\bцентр\w*\b", r"\bна центре\b"],
    "Меляк": [r"\bмеляк\w*\b", r"\bна мели\b"],
    "Яма": [r"\bям[аеуы]\b", r"\bна яме\b"],
}

LURE_PATTERNS = {
    "Блесна": [r"\bблесн\w*\b", r"\bколебалк\w*\b", r"\bруни\b", r"\bмагот\b", r"\bдоон\b"],
    "Резина": [r"\bрезин\w*\b", r"\bсиликон\w*\b", r"\bмаггот\w*\b", r"\bпламп\b"],
    "Паста": [r"\bпаст\w*\b", r"\bсырн\w*\b"],
    "Воблер": [r"\bвоблер\w*\b"],
    "Раттлин": [r"\bраттлин\w*\b", r"\bэклипс\w*\b"],
    "Бомбарда": [r"\bбомбард\w*\b"],
}

HORIZON_PATTERNS = {
    "С поверхности": [r"с поверхност", r"поверхностн", r"под пленк"],
    "В верхнем слое": [r"в верхнем слое", r"сверху", r"вверх[уы]"],
    "В полводы": [r"в полводы", r"в среднем слое"],
    "У дна / Со дна": [r"со дна", r"у дна", r"по дну", r"со дна"],
}

TIME_PATTERNS = {
    "Раннее утро (рассвет)": [r"на рассвете", r"с раннего утра", r"до запуска"],
    "Утро (после запуска)": [r"\bутром\b", r"\bс утра\b", r"после запуска"],
    "День": [r"\bднем\b", r"\bдн[её]м\b", r"после обеда", r"в обед"],
    "Вечер": [r"\bвечером\b", r"к вечеру", r"перед уходом"],
    "Ночь": [r"\bночью\b", r"в темноте"],
}

POSITIVE_RX = re.compile(
    r"поймал|поймали|взял|взяла|взяли|"
    r"клюнул|клюнула|клевало|сработал|"
    r"разловил|уговорил|лифтанул|успех|норму",
    re.I,
)

NEGATIVE_RX = re.compile(
    r"не клевало|без поклевок|ноль|0\b|"
    r"болт|тишина|пролет|не увидел поклев|"
    r"сходы|сход|оторвал",
    re.I,
)

# ==========================================
# 2. ТЕСТОВЫЕ ДАННЫЕ (Имитация парсинга)
# ==========================================
# Замените этот массив на ваши реальные данные из БД/файлов
raw_posts = [
    {"date": "2026-09-03", "kind": "stock", "kg": 150, "text": "Запуск форели 150 кг"},
    {"date": "2026-09-03", "kind": "catch", "kg": 80, "text": "Вылов за день 80 кг"},
    
    # Этот запуск будет исключен из баланса (но попадет в историю)
    {"date": "2026-09-04", "kind": "stock", "kg": 204, "text": "Запуск форели 204 кг (исключается из баланса)"},
    {"date": "2026-09-04", "kind": "catch", "kg": 50, "text": "Вылов за день 50 кг"},
    
    # Отчеты рыбаков
    {"date": "2026-09-04", "kind": "report", "text": "Приехали на рассвете. Встали у аэратора. С утра клевало отлично, поймал 5 штук. Работала резина, особенно белый маггот. Все поклевки у дна."},
    {"date": "2026-09-04", "kind": "report", "text": "Пошли в левый угол. Полная тишина, ни одной поклевки, полный болт. Кидали блесны, меняли цвета - ноль. В обед переместились на дамбу и взяли одну на пасту в полводы."},
    {"date": "2026-09-05", "kind": "report", "text": "Ловили на дамбе. Вечером включился клев на воблер. Взяли норму! Рыба гуляет с поверхности, под пленкой."},
    {"date": "2026-09-05", "kind": "report", "text": "Снова аэратор порадовал. Поймали хорошо. Днем работала бомбарда и резина."},
]

# ==========================================
# 3. ОСНОВНАЯ ЛОГИКА (Аналитика и Баланс)
# ==========================================

def calculate_analytics(posts):
    # Статистика
    stats = {
        "spots": {k: {"mentions": 0, "success": 0, "fail": 0} for k in SPOT_PATTERNS},
        "lures": {k: {"mentions": 0, "success": 0, "fail": 0} for k in LURE_PATTERNS},
        "horizons": {k: 0 for k in HORIZON_PATTERNS},
        "times": {k: 0 for k in TIME_PATTERNS}
    }
    
    balance_history = []
    current_balance = 0

    for post in posts:
        date = post["date"]
        kind = post["kind"]
        text = post.get("text", "")
        
        # --- 3.1. БЛОК БАЛАНСА ---
        if kind in ["stock", "catch"]:
            kg = post.get("kg", 0)
            exclude = (kind == "stock" and date in EXCLUDE_STOCK_FROM_BALANCE)
            
            if kind == "stock" and not exclude:
                current_balance += kg
            elif kind == "catch":
                current_balance -= kg
                
            balance_history.append({
                "date": date,
                "type": "Запуск" if kind == "stock" else "Вылов",
                "kg": kg,
                "balance": current_balance,
                "excluded": exclude,
                "text": text[:50] + "..."
            })
            
        # --- 3.2. БЛОК АНАЛИТИКИ (только по отчетам) ---
        if kind == "report":
            is_pos = bool(POSITIVE_RX.search(text))
            is_neg = bool(NEGATIVE_RX.search(text))
            
            # Точки
            for spot, patterns in SPOT_PATTERNS.items():
                if any(re.search(p, text, re.IGNORECASE) for p in patterns):
                    stats["spots"][spot]["mentions"] += 1
                    if is_pos: stats["spots"][spot]["success"] += 1
                    if is_neg: stats["spots"][spot]["fail"] += 1
                    
            # Приманки
            for lure, patterns in LURE_PATTERNS.items():
                if any(re.search(p, text, re.IGNORECASE) for p in patterns):
                    stats["lures"][lure]["mentions"] += 1
                    if is_pos: stats["lures"][lure]["success"] += 1
                    if is_neg: stats["lures"][lure]["fail"] += 1
                    
            # Горизонт
            for hor, patterns in HORIZON_PATTERNS.items():
                if any(re.search(p, text, re.IGNORECASE) for p in patterns):
                    stats["horizons"][hor] += 1
                    
            # Время суток
            for t, patterns in TIME_PATTERNS.items():
                if any(re.search(p, text, re.IGNORECASE) for p in patterns):
                    stats["times"][t] += 1

    # --- 3.3. ПОДГОТОВКА ДАННЫХ ДЛЯ ОТОБРАЖЕНИЯ (Рейтинг) ---
    def calc_rating(item):
        # Формула рейтинга: успехи - неудачи * 0.7
        return item["success"] - (item["fail"] * 0.7)

    # Фильтруем пустые и сортируем по рейтингу/количеству
    best_spots = sorted(
        [{"name": k, **v, "rating": calc_rating(v)} for k, v in stats["spots"].items() if v["mentions"] > 0],
        key=lambda x: x["rating"], reverse=True
    )
    
    best_lures = sorted(
        [{"name": k, **v, "rating": calc_rating(v)} for k, v in stats["lures"].items() if v["mentions"] > 0],
        key=lambda x: x["rating"], reverse=True
    )
    
    best_horizons = sorted(
        [{"name": k, "count": v} for k, v in stats["horizons"].items() if v > 0],
        key=lambda x: x["count"], reverse=True
    )
    
    best_times = sorted(
        [{"name": k, "count": v} for k, v in stats["times"].items() if v > 0],
        key=lambda x: x["count"], reverse=True
    )

    return balance_history, best_spots, best_lures, best_horizons, best_times, current_balance


# ==========================================
# 4. ГЕНЕРАЦИЯ HTML
# ==========================================
def generate_html(history, spots, lures, horizons, times, current_balance):
    html_template = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Аналитика Рыбалки</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f4f7f6; color: #333; margin: 0; padding: 20px; }
            h1, h2 { color: #2c3e50; }
            .container { max-width: 1200px; margin: 0 auto; }
            
            /* Блок баланса */
            .balance-box { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 30px; }
            .balance-huge { font-size: 32px; font-weight: bold; color: #27ae60; }
            table { width: 100%; border-collapse: collapse; margin-top: 15px; }
            th, td { text-align: left; padding: 10px; border-bottom: 1px solid #ddd; }
            th { background-color: #f8f9fa; }
            .excluded { color: #e74c3c; font-size: 12px; font-weight: bold; background: #fadbd8; padding: 2px 6px; border-radius: 4px;}
            
            /* Дашборд аналитики */
            .dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; }
            .card { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
            .card h3 { margin-top: 0; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
            
            .item-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px dashed #eee; }
            .item-name { font-weight: 500; }
            .item-stats { font-size: 14px; color: #7f8c8d; }
            .success { color: #27ae60; font-weight: bold; }
            .fail { color: #c0392b; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎣 Статистика и Аналитика водоёма</h1>
            
            <!-- БАЛАНС И ИСТОРИЯ -->
            <div class="balance-box">
                <h2>Расчетный остаток водоема: <span class="balance-huge">{current_balance} кг</span></h2>
                <p><em>* Запуски с 4 по 8 сентября включены в журнал, но исключены из расчёта остатка.</em></p>
                
                <table>
                    <tr><th>Дата</th><th>Событие</th><th>КГ</th><th>Остаток</th><th>Примечание</th></tr>
                    {history_rows}
                </table>
            </div>

            <h2>📊 Аналитика по отчетам рыбаков (Нейросети не нужны!)</h2>
            <div class="dashboard">
                
                <!-- ТОЧКИ -->
                <div class="card">
                    <h3>📍 Перспективные точки</h3>
                    {spots_rows}
                </div>

                <!-- ПРИМАНКИ -->
                <div class="card">
                    <h3>🐟 Рабочие приманки</h3>
                    {lures_rows}
                </div>

                <!-- ГОРИЗОНТ -->
                <div class="card">
                    <h3>🌊 Горизонт воды</h3>
                    {horizons_rows}
                </div>

                <!-- ВРЕМЯ -->
                <div class="card">
                    <h3>⏰ Время клёва</h3>
                    {times_rows}
                </div>

            </div>
        </div>
    </body>
    </html>
    """

    # Формируем строки таблиц
    history_rows = ""
    for h in history:
        exc_badge = "<span class='excluded'>ИСКЛЮЧЕНО ИЗ ОСТАТКА</span>" if h['excluded'] else ""
        history_rows += f"<tr><td>{h['date']}</td><td>{h['type']}</td><td>{h['kg']}</td><td>{h['balance']}</td><td>{exc_badge}</td></tr>"

    def render_analytics_row(item):
        return f"""
        <div class="item-row">
            <span class="item-name">{item['name']}</span>
            <span class="item-stats">
                Упом: {item['mentions']} 
                (<span class="success">+{item['success']}</span> / <span class="fail">-{item['fail']}</span>)
            </span>
        </div>"""

    def render_simple_row(item):
        return f"""
        <div class="item-row">
            <span class="item-name">{item['name']}</span>
            <span class="item-stats">Упоминаний: {item['count']}</span>
        </div>"""

    spots_rows = "".join([render_analytics_row(s) for s in spots]) or "<p>Нет данных</p>"
    lures_rows = "".join([render_analytics_row(l) for l in lures]) or "<p>Нет данных</p>"
    horizons_rows = "".join([render_simple_row(h) for h in horizons]) or "<p>Нет данных</p>"
    times_rows = "".join([render_simple_row(t) for t in times]) or "<p>Нет данных</p>"

    # Собираем итоговый HTML
    final_html = html_template.format(
        current_balance=current_balance,
        history_rows=history_rows,
        spots_rows=spots_rows,
        lures_rows=lures_rows,
        horizons_rows=horizons_rows,
        times_rows=times_rows
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(final_html)
    print("✅ Файл index.html успешно создан! Откройте его в браузере.")


# ==========================================
# 5. ЗАПУСК
# ==========================================
if __name__ == "__main__":
    # 1. Считаем всю математику
    history, best_spots, best_lures, best_horizons, best_times, balance = calculate_analytics(raw_posts)
    
    # 2. Отрисовываем HTML
    generate_html(history, best_spots, best_lures, best_horizons, best_times, balance)
