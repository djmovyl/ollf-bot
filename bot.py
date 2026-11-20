import os
import re
import time
import json
import requests
import traceback
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

# ================= НАСТРОЙКИ =================
TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
CALENDAR_URL = "https://ollf.ru/tournament/1067343/calendar"
OUR_KEY = "ITPROVIDER"

# РЕЖИМ ТЕСТА НА ПРОШЕДШЕМ МАТЧЕ
# True  — тест на матче с Триумфом (только логи, без постов в канал).
# False — боевой режим (для воскресенья).
PAST_MATCH = True 
MATCH_URL = "https://ollf.ru/match/5905514"  # Матч Триумф vs FC ITPROVIDER

# Резервные время и длительность, если парсинг даты не сработает
START_H, START_M = 15, 20
DURATION_MIN = 75

# Ссылка на постоянную трансляцию (если нет прямой ссылки на матч)
VK_TRANSLATION = "https://vkvideo.ru/@club154907309/all"

# Регулярки для парсинга времени и счёта
TIME_PAT = re.compile(r"(\d{1,3})'\s*(\d{2})''")
SCORE_END = re.compile(r"(\d{1,2})\s*:\s*(\d{1,2})\s*\$")

MSK = timezone(timedelta(hours=3))

# Глобальные переменные, заполняются в main
OUR_IS_HOME = True
LOCATION = "уточняется"
TIME_STR = "15:20"
STATE_FILE = "bot_state.json"

MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]
WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг",
               "пятница", "суббота", "воскресенье"]

# ================= TELEGRAM API =================
def tg(method, **params):
    r = requests.post("https://api.telegram.org/bot" + TOKEN + "/" + method,
                      data=params, timeout=20)
    return r.json()

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def send(text):
    # Если в тестовом режиме - не отправляем
    if PAST_MATCH:
        print("[ТЕСТ] Сообщение НЕ отправлено в канал (режим теста):")
        print(text)
        return
    
    res = tg("sendMessage", chat_id=CHANNEL, text=text[:3900],
             parse_mode="HTML")
    if not res.get("ok"):
        print("Telegram error:", res)

# ================= JINA AI (PARSING) =================
def jina(url, html=False):
    headers = {"X-Return-Format": "html"} if html else {}
    for attempt in range(4):
        try:
            r = requests.get("https://r.jina.ai/" + url,
                             headers=headers, timeout=90)
            if r.status_code == 200 and r.text.strip():
                return r.text
            time.sleep(15)
        except Exception as e:
            print("jina error:", e)
            time.sleep(15)
    return ""

def find_brackets(s):
    res = 
    i = 0
    while True:
        a = s.find("[", i)
        if a < 0:
            break
        b = s.find("]", a + 1)
        if b < 0:
            break
        res.append(s[a + 1:b])
        i = b + 1
    return res

# ================= ДАТЫ И ВРЕМЯ =================
def event_minute(time_str):
    m = TIME_PAT.search(time_str)
    if not m:
        return None
    raw_min = int(m.group(1))
    sec = int(m.group(2))
    return raw_min + 1 if sec > 0 else raw_min

def parse_teams(md):
    idx = md.find("События матча")
    zone = md[:idx] if idx > 0 else md
    names = 
    for line in zone.splitlines():
        if "teams/application?team_id=" not in line:
            continue
        for content in find_brackets(line):
            c = content.strip()
            if not c or c.startswith("!") or "Image" in c or ".png" in c:
                continue
            if c not in names:
                names.append(c)
    if len(names) >= 2:
        return names, names
    return "Хозяева", "Гости"

def parse_location(md):
    m = re.search(
        r"(Манеж|Стадион|Арена|Спорткомплекс|ФОК)\s+"
        r"([A-ZА-ЯЁA-Za-z0-9][\w\-]*(?:\s+[A-ZА-ЯЁA-Za-z0-9][\w\-]*)?)",
        md)
    if m:
        return (m.group(1) + " " + m.group(2)).strip()
    return "уточняется"

def parse_match_datetime_from_page(md, now):
    today_ord = now.date().toordinal()
    found = 
    for m in re.finditer(
            r"(\d{1,2})\s+(" + "|".join(MONTHS_RU) + r")", md, re.IGNORECASE):
        day = int(m.group(1))
        mo = MONTHS_RU.index(m.group(2).lower()) + 1
        try:
            d_ = datetime(now.year, mo, day)
        except ValueError:
            continue
        if d_.date().toordinal() >= today_ord:
            frag = md[max(0, m.start() - 40):m.end() + 60].replace("\n", " ")
            found.append((d_.date().toordinal(), m.start(), m.end(),
                          (now.year, mo, day), frag))
    if not found:
        return None, None
    found.sort()
    for _, _, _, d_, frag in found[:5]:
        print("Кандидат даты:", d_, "| фрагмент:", frag[:90])
    _, _, e, d, _ = found
    tm = re.search(r"\b(?\d|2[0-3]):([0-5]\d)\b", md[e:e + 200])
    if tm:
        return d, (int(tm.group(1)), int(tm.group(2)))
    tm = re.search(r"\b(?\d|2[0-3]):([0-5]\d)\b", md[max(0, e - 150):e])
    if tm:
        return d, (int(tm.group(1)), int(tm.group(2)))
    return d, None

def build_announcement(opponent, mdate, time_str):
    if mdate:
        y, mo, d = mdate
        date_str = str(d) + " " + MONTHS_RU[mo - 1]
        try:
            wd = WEEKDAYS_RU[datetime(y, mo, d).weekday()]
            date_str += ", " + wd
        except Exception:
            pass
    else:
        date_str = "уточняется"

    return ("🔴 <b>FC ITPROVIDER — ДЕНЬ МАТЧА</b> 🔴\n\n"
            "🆚 Соперник: «" + esc(opponent) + "»\n"
            "🗓 Дата: " + date_str + "\n"
            "⏱ Старт: " + time_str + " (МСК)\n"
            "🗺 Локация: " + esc(LOCATION) + "\n\n"
            "🔗 Трансляция: " + VK_TRANSLATION + "\n\n"
            "Следите за обновлениями в этом чате.")

# ================= СОСТАВЫ =================
NAME_TOKEN = r"[А-ЯЁ][а-яё\-]+"
# Паттерн: Номер в начале строки/слова, потом имя
PAT_NUM_FIRST = re.compile(
    r"(?<![\w.])(\d{1,2})[.\)]?\s+(?:$К$|ВР)?\s*"
    + NAME_TOKEN + r"\s+" + NAME_TOKEN)
# Паттерн: Имя, потом номер в конце
PAT_NUM_LAST = re.compile(
    NAME_TOKEN + r"\s+" + NAME_TOKEN + r"[.,]?\s*(?:$К$|ВР)?\s*(\d{1,2})(?!\d)")

def _mark_around(line, start, span):
    window = line[max(0, start - 12): start + span + 12]
    if "(К)" in window:
        return "(К)"
    if "ВР" in window:
        return "ВР"
    return ""

def lineup_side_is_right(md, team1, team2):
    idx = md.find("СТАРТОВЫЕ СОСТАВЫ")
    if idx >= 0:
        head = md[idx: idx + 600].upper()
        p_ours = head.find(OUR_KEY.upper())
        other = team2 if OUR_KEY.upper() in team1.upper() else team1
        p_other = head.find(other.upper())
        if p_ours >= 0 and p_other >= 0:
            return p_ours > p_other
    return not OUR_IS_HOME

def parse_lineups(md, ours_is_right):
    idx = md.find("СТАРТОВЫЕ СОСТАВЫ")
    if idx < 0:
        print("Раздел СТАРТОВЫЕ СОСТАВЫ не найден")
        return None
    zone = md[idx: idx + 8000]
    left, right = , 

    for line in zone.splitlines()[1:]:
        clean = line.replace("|", " ").strip()
        if not clean or len(clean) > 400:
            continue
        found = 
        for m in PAT_NUM_FIRST.finditer(clean):
            name = m.group(2) + " " + m.group(3)
            mark = _mark_around(clean, m.start(), len(name) + len(m.group(1)))
            found.append(("L", m.start(), int(m.group(1)), name, mark))
        for m in PAT_NUM_LAST.finditer(clean):
            name = m.group(1) + " " + m.group(2)
            mark = _mark_around(clean, m.start(), len(name) + len(m.group(3)))
            found.append(("R", m.start(), int(m.group(3)), name, mark))
        if not found:
            continue
        found.sort(key=lambda x: x)
        for side, _, num, name, mark in found:
            bucket = left if side == "L" else right
            if (num, name) not in [(a, b) for a, b, _ in bucket]:
                bucket.append((num, name, mark))

    print("Состав LEFT :", left)
    print("Состав RIGHT:", right)

    ours = right if ours_is_right else left
    if len(ours) >= 5:
        return ours
    return None

def send_lineup(players):
    lines = 
    for num, name, mark in players:
        s = f"№{num} {name}"
        
        if mark == "ВР":
            s += " 🧤"  # Перчатки
        elif mark == "(К)":
            s += " 🅺"  # Буква К в стиле эмодзи
        
        lines.append(esc(s))
    
    msg = ("📋 <b>Наш состав на сегодняшнюю игру</b>\n\n"
           + "\n".join(lines) + "\n\nВ бой, ITPROVIDER! 💪")
    send(msg)

# ================= ТРАНСЛЯЦИЯ =================
def find_stream_url(html, md):
    for text in (html, md):
        if not text:
            continue
        # Ищем ссылки вида video_ext.php?oid=...&id=...
        for m in re.finditer(
                r"https?://[^\s\"'<>()\\]*video_ext\.php[^\s\"'<>()\\]*", text):
            u = m.group(0).replace("&amp;", "&")
            om = re.search(r"oid=(-?\d+)", u)
            im = re.search(r"\bid=(\d+)", u)
            if om and im:
                return "https://vkvideo.ru/video" + om.group(1) + "_" + im.group(2)
        # Ищем прямые ссылки VK Video
        for m in re.finditer(
                r"https?://[^\s\"'<>()\\]*(?:vkvideo\.ru|vk\.com|vk\.ru)"
                r"/(?:video|live)-?\d+_\d+[^\s\"'<>()\\]*", text):
            return m.group(0).replace("&amp;", "&")
    
    # Если ничего не нашли, возвращаем заглушку
    return None

# ================= СОБЫТИЯ МАТЧА =================
def parse_html_events(html, team1, team2):
    soup = BeautifulSoup(html, "html.parser")
    events = 
    for el in soup.select(".game-timeline__event"):
        cls = el.get("class", )
        if "yellow-card" in cls:
            etype = "yellow"
        elif "red-card" in cls:
            etype = "red"
        elif "goal" in cls:
            etype = "goal"
        else:
            continue
        minute = event_minute(el.get("data-time", ""))
        if minute is None:
            continue
        if "team1" in cls:
            side = team1
        elif "team2" in cls:
            side = team2
        else:
            side = "?"
        events.append({
            "type": etype,
            "minute": minute,
            "player": el.get("data-player-first", "?"),
            "assist": el.get("data-player-second") or None,
            "side": side,
        })
    return events

def parse_md_events(md):
    events = 
    score = [0, 0]
    for raw in md.splitlines():
        s = raw.strip()
        if not s.startswith("*"):
            continue
        m = TIME_PAT.search(s)
        if not m:
            continue
        minute = int(m.group(1)) + 1 if int(m.group(2)) > 0 else int(m.group(1))
        players = find_brackets(s)
        ms = SCORE_END.search(s)
        scoring = None
        if ms:
            new_h = int(ms.group(1))
            new_a = int(ms.group(2))
            if new_h > score:
                scoring = "home"
            elif new_a > score:
                scoring = "away"
            score = [new_h, new_a]
        events.append({"minute": minute, "players": players,
                       "score": score[:], "scoring": scoring})
    return events

def merge_events(md_events, html_events):
    merged = 
    pool = list(html_events)
    for e in md_events:
        p0 = e["players"] if e["players"] else ""
        match = None
        for he in pool:
            if he["minute"] == e["minute"] and he["player"] == p0:
                match = he
                break
        if match is None:
            for he in pool:
                if he["minute"] == e["minute"]:
                    match = he
                    break
        if match:
            pool.remove(match)
            etype = match["type"]
            side = match["side"]
            assist = match["assist"]
            player = match["player"]
        else:
            assist = e["players"] if len(e["players"]) > 1 else None
            player = p0 or "?"
            if e["scoring"]:
                etype = "goal"
                side = "home" if e["scoring"] == "home" else "away"
            else:
                etype = "unknown"
                side = "?"
        merged.append({
            "type": etype,
            "minute": e["minute"],
            "player": player,
            "assist": assist,
            "side": side,
            "score": e["score"],
            "ours": OUR_KEY in side.upper(),
        })
    return merged

def score_text_for(sc):
    if OUR_IS_HOME:
        our, opp = sc, sc
    else:
        our, opp = sc, sc
    shown = str(sc) + " : " + str(sc)
    if our > opp:
        return "Счёт: <b>" + shown + "</b> в нашу пользу! 🎉"
    if our < opp:
        return "Счёт: <b>" + shown + "</b>. Не сдаёмся! 💪"
    return "Счёт: <b>" + shown + "</b>. На табло ничья!"

def render_post(ev):
    m = ev["minute"]
    p = ev["player"]
    a = ev.get("assist")
    sc = ev["score"]
    ours = ev["ours"]

    if ev["type"] == "goal":
        st = score_text_for(sc)
        if ours:
            pas = "🎯 Голевой пас: " + a + "\n" if a else ""
            return ("🔥⚽️ <b>Г-О-О-О-Л! 🔥⚽️</b>\n\n"
                    "⚽ <b>АВТОР ГОЛА: " + p + "</b> 🌟\n"
                    + pas
                    + "⏱ На " + str(m) + "' минуте!\n\n"
                    + st)
        return ("😢 <b>Пропускаем...</b> 😢\n\n"
                "На " + str(m) + "' минуте соперник забивает.\n\n"
                + st)

    if ev["type"] == "yellow":
        if ours:
            return ("🟡 <b>ЖЁЛТАЯ КАРТОЧКА у нас</b>\n\n"
                    "🟡 " + p + "\n"
                    "⏱ На " + str(m) + "' минуте.")
        return ("🟡 <b>Жёлтая карточка у соперника</b>\n\n"
                "⏱ На " + str(m) + "' минуте.")

    if ev["type"] == "red":
        if ours:
            return ("🚨 <b>КРАСНАЯ КАРТОЧКА — УДАЛЕНИЕ У НАС</b>\n\n"
                    "🔴 " + p + "\n"
                    "⏱ На " + str(m) + "' минуте.")
        return ("🚨 <b>КРАСНАЯ КАРТОЧКА У СОПЕРНИКА!</b>\n\n"
                "⏱ На " + str(m) + "' минуте.")
    return None

# ================= КАЛЕНДАРЬ И ПОИСК МАТЧА =================
def parse_date_from_line(s):
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b", s)
    if not m:
        return None, None, None
    d = int(m.group(1))
    mo = int(m.group(2))
    y = int(m.group(3)) if m.group(3) else None
    if mo < 1 or mo > 12 or d < 1 or d > 31:
        return None, None, None
    return y, mo, d

def parse_time_from_line(s):
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
    if not m:
        return None, None
    h = int(m.group(1))
    mm = int(m.group(2))
    if 0 <= h <= 23 and 0 <= mm <= 59:
        return h, mm
    return None, None

def find_our_match(cal_md, today):
    candidates = 
    for raw in cal_md.splitlines():
        s = raw.strip()
        if OUR_KEY not in s or "ollf.ru/match/" not in s:
            continue
        m = re.search(r"match/(\d+)", s)
        if not m:
            continue
        url = "https://ollf.ru/match/" + m.group(1)
        y, mo, d = parse_date_from_line(s)
        h, mm = parse_time_from_line(s)
        if y is None and mo is not None:
            y = today.year
        candidates.append({
            "url": url,
            "line": s,
            "date": (y, mo, d) if (y and mo and d) else None,
            "time": (h, mm) if h is not None else None,
            "upcoming": "- : -" in s,
        })
    if not candidates:
        return "", None, None
    today_key = (today.year, today.month, today.day)
    pool = [c for c in candidates if c["date"] == today_key]
    if not pool:
        pool = [c for c in candidates if c["date"] is None]
    if not pool:
        return "", None, None
    upcoming = [c for c in pool if c["upcoming"]]
    pick = (upcoming or pool)
    print("Строка календаря:", pick["line"][:200])
    return pick["url"], pick["date"], pick["time"]

# ================= MAIN =================
def main():
    global OUR_IS_HOME, START_H, START_M, LOCATION, TIME_STR, STATE_FILE
    now = datetime.now(MSK)
    
    # Настройка файла состояния
    if PAST_MATCH:
        STATE_FILE = "test_state.json"
        START_H, START_M = 15, 20
        TIME_STR = "15:20"
    else:
        STATE_FILE = "bot_state.json"

    match_url, mdate, mtime = None, None, None

    if PAST_MATCH:
        match_url = MATCH_URL
    else:
        cal = jina(CALENDAR_URL)
        if not cal:
            send("🧪 Диагностика: календарь не скачался")
            return
        match_url, mdate, mtime = find_our_match(cal, now.date())
        if not match_url:
            print("Наш матч на сегодня не найден — выходим")
            return

    # Парсинг страницы матча
    print("Загружаем страницу матча:", match_url)
    md = jina(match_url)
    html = jina(match_url, html=True)
    
    if not md:
        print("Не удалось получить Markdown версию страницы")
        return

    # Определение хозяев/гостей
    t1, t2 = parse_teams(md)
    print("Команды:", t1, "vs", t2)
    OUR_IS_HOME = OUR_KEY.upper() in t1.upper()
    print("Мы хозяева?", OUR_IS_HOME)

    # Определение даты и времени
    if mdate and mtime:
        START_H, START_M = mtime
        TIME_STR = f"{START_H:02d}:{START_M:02d}"
    else:
        # Попытка вытащить из самой страницы матча, если в календаре пусто
        pd, pt = parse_match_datetime_from_page(md, now)
        if pd and pt:
            START_H, START_M = pt
            TIME_STR = f"{START_H:02d}:{START_M:02d}"

    # Определение локации
    LOCATION = parse_location(md)
    print("Локация:", LOCATION)

    # Проверка состава
    ours_is_right = lineup_side_is_right(md, t1, t2)
    players = parse_lineups(md, ours_is_right)
    
    if players:
        print("Состав успешно распарсен! Отправляем (или логируем в тесте)...")
        send_lineup(players)
    else:
        print("Состав не найден или слишком короткий (<5 игроков).")

    # Проверка трансляции
    stream_url = find_stream_url(html, md)
    if stream_url:
        print("Ссылка на трансляцию найдена:", stream_url)
        # Здесь можно добавить логику отправки ссылки, если нужно
    else:
        print("Ссылка на трансляцию не найдена на странице.")

    # Сохранение состояния (для будущих итераций)
    state = {
        "last_check": now.isoformat(),
        "match_url": match_url,
        "location": LOCATION,
        "time": TIME_STR
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print("Ошибка сохранения состояния:", e)

if __name__ == "__main__":
    main()
