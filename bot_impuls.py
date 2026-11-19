import os
import re
import time
import json
import requests
import traceback
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
CALENDAR_URL = "https://ollf.ru/tournament/1067343/calendar"
OUR_KEY = "ИМПУЛЬС"

# ====== РЕЖИМ РАБОТЫ ======
# PAST_MATCH=True  — тест на конкретном сыгранном матче (MATCH_URL)
# USE_DIRECT_LINK=True — работаем по прямой ссылке на матч (MATCH_URL),
#   дату и время бот берёт со страницы матча сам
# USE_DIRECT_LINK=False — искать наш матч в календаре турнира
PAST_MATCH = False
USE_DIRECT_LINK = True
MATCH_URL = "https://ollf.ru/match/5905494"

# Запасные значения, если время матча не найдём на странице
START_H, START_M = 18, 30
DURATION_MIN = 50  # 2 тайма по 20 минут + перерыв и остановки

TIME_PAT = re.compile(r"(\d{1,3})'\s*(\d{2})''")
SCORE_END = re.compile(r"(\d{1,2})\s*:\s*(\d{1,2})\s*$")

MSK = timezone(timedelta(hours=3))

MONTHS = {
    "января": 1, "янв": 1,
    "февраля": 2, "фев": 2,
    "марта": 3, "мар": 3,
    "апреля": 4, "апр": 4,
    "мая": 5, "май": 5,
    "июня": 6, "июн": 6,
    "июля": 7, "июл": 7,
    "августа": 8, "авг": 8,
    "сентября": 9, "сен": 9, "сент": 9,
    "октября": 10, "окт": 10,
    "ноября": 11, "ноя": 11,
    "декабря": 12, "дек": 12,
}
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_WORD_RE = re.compile(r"(\d{1,2})\s+(" + MONTH_RE + r")\b", re.IGNORECASE)
DATE_NUM_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b")
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
SEASON_RANGE_RE = re.compile(r"\d{4}\s*-\s*\d{4}")

# Заполняется в main: True, если наша команда — хозяева (первая в счёте)
OUR_IS_HOME = True

def tg(method, **params):
    r = requests.post("https://api.telegram.org/bot" + TOKEN + "/" + method,
                      data=params, timeout=20)
    return r.json()

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def send(text):
    res = tg("sendMessage", chat_id=CHANNEL, text=text[:3900],
             parse_mode="HTML")
    if not res.get("ok"):
        print("Telegram error:", res)

def jina(url, html=False):
    headers = {"X-Return-Format": "html", "X-No-Cache": "true"} if html \
        else {"X-No-Cache": "true"}
    for attempt in range(4):
        try:
            r = requests.get("https://r.jina.ai/" + url,
                             headers=headers, timeout=90)
            print("jina:", url, "html" if html else "md",
                  "->", r.status_code, len(r.text))
            if r.status_code == 200 and r.text.strip():
                return r.text
            time.sleep(15)
        except Exception as e:
            print("jina error:", e)
            time.sleep(15)
    return ""

def find_brackets(s):
    """Содержимое всех квадратных скобок в строке (имена игроков и команд)."""
    res = []
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

def event_minute(time_str):
    """Логика минут: 23' 01'' -> 24', 23' 00'' -> 23'."""
    m = TIME_PAT.search(time_str)
    if not m:
        return None
    raw_min = int(m.group(1))
    sec = int(m.group(2))
    return raw_min + 1 if sec > 0 else raw_min

def parse_teams(md):
    idx = md.find("События матча")
    zone = md[:idx] if idx > 0 else md
    names = []
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
        return names[0], names[1]
    return "Хозяева", "Гости"

def parse_html_events(html, team1, team2):
    """Тип события (гол/ЖК/КК) и сторона — из HTML-классов таймлайна."""
    soup = BeautifulSoup(html, "html.parser")
    events = []
    for el in soup.select(".game-timeline__event"):
        cls = el.get("class", [])
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
    """Голы и счёт — из протокола: счёт меняется только в строках с голом."""
    events = []
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
            if new_h > score[0]:
                scoring = "home"
            elif new_a > score[1]:
                scoring = "away"
            score = [new_h, new_a]
        events.append({"minute": minute, "players": players,
                       "score": score[:], "scoring": scoring})
    return events

def merge_events(md_events, html_events):
    merged = []
    pool = list(html_events)
    for e in md_events:
        p0 = e["players"][0] if e["players"] else ""
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
            assist = e["players"][1] if len(e["players"]) > 1 else None
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
    """Текст счёта с учётом того, хозяева мы или гости.
    sc — счёт [хозяева, гости]."""
    if OUR_IS_HOME:
        our, opp = sc[0], sc[1]
    else:
        our, opp = sc[1], sc[0]
    shown = str(sc[0]) + " : " + str(sc[1])
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

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)

def date_from_words(s, today):
    """Дата из словесного формата: '21 ноября, суббота' или '01 нояб., вс'.
    Возвращает (year, month, day) или None."""
    m = DATE_WORD_RE.search(s)
    if not m:
        return None
    d = int(m.group(1))
    mo = MONTHS.get(m.group(2).lower())
    if not mo or d < 1 or d > 31:
        return None
    return (today.year, mo, d)

def date_from_numeric(s, today):
    """Числовой формат: '21.11' или '21.11.2026'."""
    m = DATE_NUM_RE.search(s)
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    if mo < 1 or mo > 12 or d < 1 or d > 31:
        return None
    y = int(m.group(3)) if m.group(3) else today.year
    return (y, mo, d)

def time_from_line(s):
    """Время из строки: '19:40'. Возвращает (h, mm) или None."""
    m = TIME_RE.search(s)
    if not m:
        return None
    h, mm = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mm <= 59:
        return (h, mm)
    return None

def parse_match_datetime(md, today):
    """Дата и время матча — со страницы самого матча (прямая ссылка).
    Игнорируем строки со сезонным диапазоном вида '2026-2027'.
    Возвращает (date, time); любой элемент может быть None."""
    idx = md.find("События матча")
    zone = md[:idx] if idx > 0 else md[:4000]
    lines = [l.strip() for l in zone.splitlines()]
    mdate = None
    date_idx = None
    for i, s in enumerate(lines):
        if SEASON_RANGE_RE.search(s):
            continue  # строки вида '03 октября 2026 - 11 апреля 2027'
        d = date_from_words(s, today) or date_from_numeric(s, today)
        if d:
            mdate = d
            date_idx = i
            break
    if not mdate:
        return None, None
    # Ищем время рядом с датой: та же строка или +-3 строки
    mtime = None
    for j in range(max(0, date_idx - 1), min(len(lines), date_idx + 4)):
        t = time_from_line(lines[j])
        if t:
            mtime = t
            break
    return mdate, mtime

def find_our_match(cal_md, today):
    """Запасной путь: ищем наш матч в календаре (если USE_DIRECT_LINK=False).
    Возвращает (url, date, time)."""
    candidates = []
    cur_date = None
    for raw in cal_md.splitlines():
        s = raw.strip()
        ls = s.lower()

        # Заголовок-дата: короткая строка без ссылки и без нашей команды
        if ("ollf.ru/match/" not in s and OUR_KEY not in s.upper()
                and len(s) < 60):
            dm = date_from_words(s, today) or date_from_numeric(s, today)
            if dm:
                cur_date = dm
                continue
            if ls.startswith("не задано"):
                cur_date = None
                continue

        if OUR_KEY not in s.upper() or "ollf.ru/match/" not in s:
            continue
        m = re.search(r"match/(\d+)", s)
        if not m:
            continue
        url = "https://ollf.ru/match/" + m.group(1)
        date = date_from_words(s, today) or date_from_numeric(s, today) \
            or cur_date
        candidates.append({
            "url": url,
            "date": date,
            "time": time_from_line(s),
            "upcoming": "- : -" in s,
        })
    if not candidates:
        return "", None, None
    today_key = (today.year, today.month, today.day)
    pool = [c for c in candidates if c["date"] == today_key]
    if not pool:
        return "", None, None
    upcoming = [c for c in pool if c["upcoming"]]
    pick = (upcoming or pool)[0]
    return pick["url"], pick["date"], pick["time"]

def main():
    global STATE_FILE, OUR_IS_HOME, START_H, START_M
    now = datetime.now(MSK)
    today_key = (now.year, now.month, now.day)
    match_url = ""
    mtime = None

    if PAST_MATCH:
        match_url = MATCH_URL
        START_H, START_M = 19, 40
        STATE_FILE = "impuls_test_state.json"
    elif USE_DIRECT_LINK:
        STATE_FILE = "impuls_state.json"
        match_url = MATCH_URL
        md = jina(match_url)
        if not md:
            send("🧪 Диагностика: страница матча не скачалась (md пустой)")
            return
        team1, team2 = parse_teams(md)
        if OUR_KEY not in team1.upper() and OUR_KEY not in team2.upper():
            send("🧪 Диагностика: на странице матча нет ИМПУЛЬСА ("
                 + team1 + " vs " + team2 + ")")
            return
        mdate, mtime = parse_match_datetime(md, now.date())
        if not mdate:
            print("Дату матча на странице не нашли "
                  "(матч ещё не назначен?) — выходим")
            return
        if mdate != today_key:
            print("Наш матч не сегодня:", mdate, "— выходим")
            return
        print("Матч сегодня! Дата со страницы:", mdate)
        if mtime:
            START_H, START_M = mtime
            print("Время матча со страницы:", START_H, ":", START_M)
        else:
            print("Время матча на странице не нашли, оставляем",
                  START_H, START_M)
    else:
        cal = jina(CALENDAR_URL)
        if not cal:
            send("🧪 Диагностика: календарь не скачался")
            return

        match_url, mdate, mtime = find_our_match(cal, now.date())
        if not match_url:
            print("Наш матч на сегодня не найден — выходим")
            return
        if mdate and mdate != today_key:
            print("Наш матч не сегодня:", mdate, "— выходим")
            return
        if not mdate:
            print("ВНИМАНИЕ: дату матча в календаре не нашли, "
                  "работаем по умолчанию")
        if mtime:
            START_H, START_M = mtime
            print("Время матча из календаря:", START_H, ":", START_M)
        else:
            print("Время в календаре не найдено")

        STATE_FILE = "impuls_state.json"
        md = jina(match_url)
        if not md:
            send("🧪 Диагностика: страница матча не скачалась (md пустой)")
            return

    time.sleep(5)
    html = jina(match_url, html=True)

    team1, team2 = parse_teams(md)
    if OUR_KEY not in team1.upper() and OUR_KEY not in team2.upper():
        print("Это не наш матч:", team1, team2)
        return

    # Ключевое: определяем, хозяева мы или гости
    OUR_IS_HOME = OUR_KEY in team1.upper()

    st = load_state()
    if PAST_MATCH:
        st = {"seen": [], "started": False, "final": False, "score": [0, 0]}

    html_events = parse_html_events(html, team1, team2) if html else []
    md_events = parse_md_events(md)
    events = merge_events(md_events, html_events)

    if events and not st.get("started"):
        st["started"] = True
        save_state(st)
        send("🏟️ <b>МАТЧ НАЧАЛСЯ!</b> 🏟️\n\n"
             "🆚 <b>" + team1 + " vs " + team2 + "</b>\n\n"
             "Держим кулаки за команду! 👊")

    last_score = st.get("score", [0, 0])
    for ev in events:
        eid = str(ev["minute"]) + "-" + ev["type"] + "-" + ev["player"]
        if eid in st["seen"]:
            continue
        if ev["type"] != "unknown":
            post = render_post(ev)
            if post:
                time.sleep(2)
                send(post)
        if ev["type"] == "goal":
            last_score = ev["score"]
        st["seen"].append(eid)

    st["score"] = last_score
    save_state(st)

    # Финальный пост: сравниваем НАШИ голы с голами соперника
    end_time = now.replace(hour=START_H, minute=START_M, second=0,
                           microsecond=0) + timedelta(minutes=DURATION_MIN)
    if now > end_time and st.get("started") and not st.get("final"):
        st["final"] = True
        save_state(st)
        sc = st["score"]
        if OUR_IS_HOME:
            our, opp = sc[0], sc[1]
        else:
            our, opp = sc[1], sc[0]

        if our > opp:
            verdict = "🎉 <b>ПОБЕДА!</b> 🎉"
        elif our < opp:
            verdict = "😔 <b>ПОРАЖЕНИЕ</b> 😔"
        else:
            verdict = "🤝 <b>НИЧЬЯ</b> 🤝"

        send("🏁 <b>МАТЧ ЗАВЕРШЁН!</b> 🏁\n\n"
             "📊 Итоговый счёт: <b>" + str(sc[0]) + " : " + str(sc[1])
             + "</b>\n\n"
             + verdict + "\n\n"
             "Спасибо за игру, команда! 🤝")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        send("🚨 Ошибка:\n<pre>"
             + esc(traceback.format_exc()[-2500:]) + "</pre>")
        raise
