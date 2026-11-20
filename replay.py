import os, re, time, requests, traceback
from datetime import datetime, timedelta, timezone

VERSION = "2.4 (20.11.2026)"

# ===== НАСТРОЙКИ ТЕСТА =====
TEST_SEND = True
CHAT_ID = "-1003949616458"
MATCH_URL = "https://ollf.ru/match/5905503"
OUR_KEY = "ITPROVIDER"

TOKEN = os.environ.get("BOT_TOKEN", "")

MONTHS_RU = ("января февраля марта апреля мая июня "
             "июля августа сентября октября ноября декабря").split()
WEEKDAYS_RU = ("понедельник вторник среда четверг "
               "пятница суббота воскресенье").split()
MSK = timezone(timedelta(hours=3))
MONTH_RE = "|".join(MONTHS_RU)
WEEK_RE = "|".join(WEEKDAYS_RU)

BS = chr(92)
LB = BS + "["
RB = BS + "]"
LP = BS + "("
RP = BS + ")"

# Регулярки для поиска данных со страницы (как на скриншоте)
# Ищем паттерн: "15 ноября / воскресенье / 20:00"
MATCH_DATE_TIME_LOC = re.compile(
    r"(\d{1,2})\s+(" + MONTH_RE + r")\s*/\s*(" + WEEK_RE + r")\s*/\s*(\d{1,2}:\d{2})", re.I)
# Ищем локацию рядом с датой (на скриншоте это "Тасма" под значком геолокации)
VENUE_PATTERN = re.compile(r"📍\s*([А-ЯЁа-яё\s\-]+)|Тасма|Манеж|ФОК|СК", re.I)

TIME_PAT = re.compile(r"(\d{1,3})'\s*(\d{2})''")
SCORE_END = re.compile(r"(\d{1,2})\s*:\s*(\d{1,2})\s*\$")
NAME = r"[А-ЯЁ][а-яё\-]+"
NAME_RE = re.compile(NAME + r"\s+" + NAME)
IMG_MD = re.compile(
    "!" + LB + "[^" + RB + "]*" + RB + LP + "[^" + RP + "]*" + RP)
PAT_P = re.compile(
    r"\*\s+(\d{1,2})\s+" + LB + r"\s*"
    + "(" + NAME + r")\s+(" + NAME + r")\s*"
    + "(" + LP + "К" + RP + "|ВР)?"
    + RB + LP + r"\s*https://ollf\.ru/player/", re.I)
PAT_TEAM = re.compile(
    LB + r"([^" + LB + RB + "!]+?)" + RB + LP
    + r"https://ollf\.ru/tournament/\d+/teams/application\?team_id=\d+",
    re.I)

# Маркеры карточек в HTML/Markdown
CARD_RED_MARKERS = ("card-red", "card_red", "redcard", "удал", "красная карточка", "🟥", "КК")
CARD_YELLOW_MARKERS = ("card-yellow", "card_yellow", "yellowcard", "жк", "жёлт", "желт", "🟨", "ЖК")

JUNK = ("кубок", "чемпионат", "лига", "турнир", "календарь", "группа",
        "сезон", "тур ", "оллф", "статистика", "таблица", "протокол",
        "события", "автогол")

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def send(text):
    if not TEST_SEND:
        print("[ТЕСТ] Сообщение НЕ отправлено:")
        print(text.replace("<b>", "").replace("</b>", ""))
        return
    try:
        r = requests.post("https://api.telegram.org/bot" + TOKEN + "/sendMessage",
                          data={"chat_id": CHAT_ID, "text": text[:3900],
                                "parse_mode": "HTML"}, timeout=20)
        print("Отправлено:", r.json().get("ok"))
    except Exception as e:
        print("Ошибка отправки:", e)

def jina(url, html=False):
    h = {"X-Return-Format": "html" if html else "markdown"}
    for _ in range(4):
        try:
            r = requests.get("https://r.jina.ai/" + url,
                             headers=h, timeout=90)
            if r.status_code == 200 and r.text.strip():
                return r.text
            time.sleep(10)
        except Exception as e:
            print("jina error:", e)
            time.sleep(10)
    return ""

def find_brackets(s):
    res = 
    i = 0
    while True:
        a = s.find("[", i)
        if a < 0: break
        b = s.find("]", a + 1)
        if b < 0: break
        res.append(s[a + 1:b])
        i = b + 1
    return res

def parse_teams(md):
    idx = md.find("События матча")
    zone = md[:idx] if idx > 0 else md
    names = 
    for line in zone.splitlines():
        if "teams/application?team_id=" not in line: continue
        for c in find_brackets(line):
            c = c.strip()
            if (c and not c.startswith("!") and "Image" not in c
                    and ".png" not in c and c not in names):
                names.append(c)
    if len(names) >= 2: return names, names
    return "Хозяева", "Гости"

def is_junk(name):
    low = name.lower()
    return any(w in low for w in JUNK)

def parse_lineups(md):
    idx = md.upper().find("СТАРТОВЫЕ СОСТАВЫ")
    if idx < 0: return None
    sections = 
    cur = None
    for raw in md[idx: idx + 8000].splitlines():
        line = IMG_MD.sub(" ", raw)
        m = PAT_TEAM.search(line)
        if m:
            cur = m.group(1).strip()
            sections.append((cur, ))
            continue
        pm = PAT_P.search(line)
        if pm and cur is not None:
            num = int(pm.group(1))
            name = (pm.group(2) + " " + pm.group(3)).strip()
            if is_junk(name): continue
            mark = pm.group(4) or ""
            pl = sections[-1]
            if all(p != num or p != name for p in pl):
                pl.append((num, name, mark))
    return sections or None

def get_lineup(proto):
    secs = parse_lineups(proto) if proto else None
    if not secs: return 
    cand = [pl for t, pl in secs if OUR_KEY.upper() in t.upper()]
    return max(cand, key=len) if cand else 

def send_lineup(players):
    lines = 
    for num, name, mark in players:
        s = "№" + str(num) + " " + name
        if mark == "ВР": s += " 🧤"
        elif mark == "(К)": s += " 🅺"
        lines.append(esc(s))
    send("📋 <b>Наш состав на игру</b>\n\n"
         + "\n".join(lines) + "\n\nВ бой, ITPROVIDER! 💪")

def extract_match_info(html_content):
    """Вытаскивает дату, время и локацию из HTML, как на скриншоте."""
    # 1. Ищем дату/время по паттерну "15 ноября / воскресенье / 20:00"
    m = MATCH_DATE_TIME_LOC.search(html_content)
    mdate, mtime = None, None
    if m:
        d = int(m.group(1))
        mo = MONTHS_RU.index(m.group(2).lower()) + 1
        mdate = (datetime.now(MSK).year, mo, d)
        t_str = m.group(4)
        parts = t_str.split(":")
        mtime = (int(parts), int(parts))
    
    # 2. Ищем локацию. На скриншоте это "Тасма" или текст после значка 📍
    loc = "уточняется"
    # Сначала пробуем найти явную локацию после значка
    vm = VENUE_PATTERN.search(html_content)
    if vm:
        loc = vm.group(1).strip() if vm.group(1) else "Тасма" # fallback если просто слово Тасма
    
    # Если не нашли, ищем в контексте даты
    if m and not loc or loc == "уточняется":
        # Берем кусок текста вокруг даты и ищем слова типа "Тасма", "Манеж"
        context = html_content[max(0, m.start()-200): m.end()+200]
        vm2 = re.search(r"(Тасма|Манеж|ФОК|СК|Стадион)\s*([А-ЯЁа-яё\-]+)", context, re.I)
        if vm2:
            loc = vm2.group(0).strip()
            
    return mdate, mtime, loc

def md_events(md):
    out, score = , [0, 0]
    for raw in md.splitlines():
        s = raw.strip()
        if not s.startswith("*"): continue
        m = TIME_PAT.search(s)
        if not m: continue
        
        minute = int(m.group(1)) + (1 if int(m.group(2)) > 0 else 0)
        sec = int(m.group(2))
        tstr = m.group(0)
        players = [c.strip() for c in find_brackets(s)
                   if NAME_RE.fullmatch(c.strip())]
        low = s.lower()
        
        scoring = None
        ms = SCORE_END.search(s)
        if ms:
            nh, na = int(ms.group(1)), int(ms.group(2))
            if nh > score: scoring = "home"
            elif na > score: scoring = "away"
            score = [nh, na]
        
        # Определение типа события
        if any(w in low for w in CARD_RED_MARKERS):
            et = "red"
        elif any(w in low for w in CARD_YELLOW_MARKERS):
            et = "yellow"
        elif scoring:
            et = "goal"
        elif players:
            # Есть игроки и время, но нет счёта и явных маркеров карточки -> помечаем как card для уточнения по HTML
            et = "card"
        else:
            et = "unknown"
            
        out.append({"et": et, "minute": minute, "sec": sec,
                    "tstr": tstr, "players": players,
                    "score": score[:], "scoring": scoring})
    return out

def classify_card_by_html(html, tstr, player_name):
    """Определяет цвет карточки, сканируя HTML вокруг времени события."""
    if not html: return "yellow"
    
    # Ищем фрагмент вокруг времени
    for m in re.finditer(re.escape(tstr), html):
        frag = html[max(0, m.start() - 500): m.end() + 500]
        if player_name and player_name.split() not in frag:
            continue
            
        low = frag.lower()
        if any(w in low for w in CARD_RED_MARKERS):
            return "red"
        if any(w in low for w in CARD_YELLOW_MARKERS):
            return "yellow"
    
    # Если ничего не нашли, возвращаем жёлтый по умолчанию (но в логе будет видно)
    return "yellow"

def main():
    global OUR_IS_HOME
    print("ВЕРСИЯ КОДА:", VERSION)
    
    # 1. Получаем HTML (для даты, локации и уточнения карточек)
    html = jina(MATCH_URL, html=True)
    if not html:
        print("Не удалось получить HTML страницы")
        return
        
    # 2. Получаем Markdown (для парсинга событий и составов)
    md = jina(MATCH_URL)
    if not md:
        print("Не удалось получить Markdown страницы")
        return

    t1, t2 = parse_teams(md)
    OUR_IS_HOME = OUR_KEY in t1.upper()
    print("Команды:", t1, "vs", t2, "| Мы хозяева:", OUR_IS_HOME)

    # 3. Извлекаем дату, время и локацию из HTML
    mdate, mtime, loc = extract_match_info(html)
    print(f"Извлечено из HTML: Дата={mdate}, Время={mtime}, Локация={loc}")
    
    # Формируем анонс (даже если матч прошел, это полезно для архива)
    ds = "уточняется"
    if mdate:
        y, mo, d = mdate
        ds = str(d) + " " + MONTHS_RU[mo - 1] + ", " + WEEKDAYS_RU[datetime(y, mo, d).weekday()]
    ts = "уточняется"
    if mtime:
        ts = f"{mtime:02d}:{mtime:02d}"
        
    send(f"🔴 <b>FC ITPROVIDER — ДЕНЬ МАТЧА</b> 🔴\n\n"
         f"🆚 Соперник: «{esc(t2 if OUR_IS_HOME else t1)}»\n"
         f"🗓 Дата: {ds}\n"
         f"⏱ Старт: {ts} (МСК)\n"
         f"🗺 Локация: {esc(loc)}\n\n"
         f"Следите за обновлениями!")

    # 4. Состав
    proto = jina(MATCH_URL + "?active=protocol")
    lineup = get_lineup(proto)
    if lineup:
        print("ТЕСТ СОСТАВ — найдено", len(lineup), "игроков")
        send_lineup(lineup)
    else:
        print("ТЕСТ СОСТАВ — не найден")

    # 5. События
    raw_evs = md_events(md)
    if not raw_evs:
        print("События не распознаны")
        return

    our_names = set(n for _, n, _ in lineup)
    final_score = [0, 0]
    
    # Проходим по событиям, уточняем карточки через HTML
    processed_events = 
    for e in raw_evs:
        ev = {
            "et": e["et"], 
            "minute": e["minute"], 
            "score": e["score"],
            "player": e["players"] if e["players"] else "?",
            "assist": e["players"] if len(e["players"]) > 1 else None
        }
        
        # Если тип 'card', уточняем по HTML
        if e["et"] == "card":
            ctype = classify_card_by_html(html, e["tstr"], ev["player"])
            ev["et"] = ctype
            print(f"КАРТОЧКА: {ev['player']} -> {ctype}")
        
        # Определяем, наша ли команда
        if ev["et"] == "goal" and e["scoring"]:
            ev["ours"] = OUR_IS_HOME == (e["scoring"] == "home")
        else:
            ev["ours"] = any(p in our_names for p in e["players"])
            
        processed_events.append(ev)
        
        # Обновляем финальный счёт
        if e["score"] > final_score or e["score"] > final_score:
            final_score = e["score"]

    # Пост о начале (или просто сводка)
    send(f"🏟️ <b>МАТЧ: {t1} vs {t2}</b> 🏟️\n\n"
         f"Держим кулаки за команду! 👊")

    # Вывод событий
    for ev in processed_events:
        if ev["et"] == "goal":
            st = f"{final_score}:{final_score}"
            if ev["ours"]:
                pas = f"🎯 Голевой пас: {ev['assist']}\n" if ev['assist'] else ""
                post = (f"🔥⚽️ <b>Г-О-О-О-Л! 🔥⚽️</b>\n\n"
                        f"⚽ <b>АВТОР ГОЛА: {ev['player']}</b> 🌟\n"
                        f"{pas}"
                        f"⏱ На {ev['minute']}' минуте!\n\n"
                        f"Текущий счёт: <b>{st}</b>")
            else:
                post = (f"😢 <b>Пропускаем...</b> 😢\n\n"
                        f"На {ev['minute']}' минуте соперник забивает.\n\n"
                        f"Текущий счёт: <b>{st}</b>")
            send(post)
            
        elif ev["et"] == "yellow":
            if ev["ours"]:
                send(f"🟡 <b>ЖЁЛТАЯ КАРТОЧКА у нас</b>\n\n🟡 {ev['player']}\n⏱ На {ev['minute']}' минуте.")
            else:
                send(f"🟡 <b>Жёлтая карточка у соперника</b>\n\n⏱ На {ev['minute']}' минуте.")
                
        elif ev["et"] == "red":
            if ev["ours"]:
                send(f"🚨 <b>КРАСНАЯ КАРТОЧКА — УДАЛЕНИЕ У НАС</b>\n\n🔴 {ev['player']}\n⏱ На {ev['minute']}' минуте.")
            else:
                send(f"🚨 <b>КРАСНАЯ КАРТОЧКА У СОПЕРНИКА!</b>\n\n⏱ На {ev['minute']}' минуте.")

    # ИТОГ
    our, opp = (final_score, final_score) if OUR_IS_HOME else (final_score, final_score)
    if our > opp: verdict = "🎉 <b>ПОБЕДА!</b> 🎉"
    elif our < opp: verdict = "😔 <b>ПОРАЖЕНИЕ</b> 😔"
    else: verdict = "🤝 <b>НИЧЬЯ</b> 🤝"
    
    send(f"🏁 <b>МАТЧ ЗАВЕРШЁН!</b> 🏁\n\n"
         f"📊 Итоговый счёт: <b>{final_score} : {final_score}</b>\n\n"
         f"{verdict}\n\n"
         f"Спасибо за игру, команда! 🤝")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
        raise
