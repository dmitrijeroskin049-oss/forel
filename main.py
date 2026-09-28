def find_events(text, post_dt):
    """Исправленная версия: агрегаты за период (неделя/месяц) полностью игнорируются,
    'за сегодня' имеет приоритет."""
    if not text:
        return []
    pd = (post_dt or "")[:10]
    kws = []
    for m in STOCK_KW_RX.finditer(text):
        kws.append((m.start(), m.end(), "stock"))
    for m in CATCH_KW_RX.finditer(text):
        kws.append((m.start(), m.end(), "catch"))
    kws.sort()

    # Находим все предложения, где идёт речь о периоде (неделя/месяц/итого)
    # и запоминаем диапазоны этих предложений, чтобы полностью их игнорировать.
    period_spans = []
    for pm in re.finditer(r"[^.!?\n]*?(за\s+(прошедш\w*|прошл\w*|минувш\w*|эт\w*)\s*"
                          r"(недел\w*|месяц\w*|сутк\w*|период\w*)|"
                          r"итого\s+за|в\s+сумме\s+за|всего\s+за)[^.!?\n]*", text, re.I):
        period_spans.append((pm.start(), pm.end()))

    def in_period(pos):
        for a, b in period_spans:
            if a <= pos < b:
                return True
        return False

    today_positions = [m.start() for m in TODAY_RX.finditer(text)]

    out = []
    for m in KG_RX.finditer(text):
        s, e = m.span()
        before = text[max(0, s - 45):s].lower()
        if re.search(r"навеск\w*[^0-9]{0,25}$", before):
            continue
        if OTHER_FISH.search(text[max(0, s - 25):min(len(text), e + 25)]):
            continue

        # --- ЖЁСТКО отсекаем всё, что попадает в предложение про период ---
        if in_period(s):
            # Исключение: если рядом "за сегодня" и она ближе, чем границы периода
            if not today_positions:
                continue
            nearest_today = min((abs(s - tp) for tp in today_positions), default=10**9)
            if nearest_today > 50:
                continue

        # --- Проверка "подушки" ---
        bal_zone = text[max(0, s - 80):s]
        bal_hit = None
        for bm in BALANCE_KW_RX.finditer(bal_zone):
            bal_hit = bm
        if bal_hit:
            between_bal = bal_zone[bal_hit.end():]
            if not (STOCK_KW_RX.search(between_bal) or CATCH_KW_RX.search(between_bal)):
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

        is_today = any(abs(s - tp) <= 40 for tp in today_positions)

        if kind == "stock":
            ctx = text[max(0, s - 250):min(len(text), e + 250)]
            if not FOREL_RX.search(ctx) and OTHER_FISH.search(ctx):
                continue
            ed, dated = resolve_event_date(text, s, e, post_dt)
            if not dated:
                pre = text[max(0, s - 70):s].lower()
                pos_z = pre.rfind("завтра")
                pos_s = pre.rfind("сегодня")
                if pos_z != -1 and pos_z > pos_s:
                    try:
                        ed = str(date.fromisoformat(pd) + timedelta(days=1))
                        dated = True
                    except Exception:
                        continue
                elif FUTURE_RX.search(pre):
                    continue
        else:
            ed, dated = pd, False
            pre = text[max(0, s - 80):s].lower()
            if "вчера" in pre and not is_today:
                try:
                    ed = str(date.fromisoformat(pd) - timedelta(days=1))
                    dated = True
                except Exception:
                    pass

        out.append({
            "kind": kind,
            "kg": kg,
            "day": ed,
            "dated": dated,
            "is_today": is_today,
            "quote": snippet(text, s),
            "pos": s,
        })

    dated_stock = [r for r in out if r["kind"] == "stock" and r["dated"]]
    if dated_stock:
        out = [r for r in out if not (r["kind"] == "stock" and not r["dated"])]

    # Среди catch за один день выбираем "за сегодня", если есть
    catch_by_day = {}
    others = []
    for r in out:
        if r["kind"] == "catch":
            catch_by_day.setdefault(r["day"], []).append(r)
        else:
            others.append(r)

    result = list(others)
    for d, recs in catch_by_day.items():
        todays = [r for r in recs if r["is_today"]]
        pool = todays if todays else recs
        pool.sort(key=lambda r: r["pos"])
        result.append(pool[-1] if len(pool) == 1 else pool[0])
    return result
