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
OUR_KEY = "ITPROVIDER"

# ====== РЕЖИМ ТЕСТА НА ПРОШЕДШЕМ МАТЧЕ ======
PAST_MATCH = False
MATCH_URL = "https://ollf.ru/match/5905503"

# Время и дата матча теперь берутся из календаря автоматически.
# Эти значения — только запасной вариант, если время в календаре не нашлось.
START_H, START_M = 18, 0
DURATION_MIN = 75

TIME_PAT = re.compile(r"(\d{1,3})'\s*(\d{2})''")
SCORE_END = re.compile(r"(\d{1,2})\s*:\s*(\d{1,2})\s*$")

MSK = timezone(timedelta(hours=3))

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
    headers = {"X-Return-Format": "html"} if html else {}
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

def parse_date_from_line(s):
    """Дата из строки календаря: '22.11.2026' или '22.11'.
    Возвращает (year, month, day); год может быть None."""
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
    """Время из строки календаря: '15:20', '9:30'. Возвращает (h, mm) или (None, None)."""
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
    if not m:
        return None, None
    h = int(m.group(1))
    mm = int(m.group(2))
    if 0 <= h <= 23 and 0 <= mm <= 59:
        return h, mm
    return None, None

def find_our_match(cal_md, today):
    """Ищем наш матч в календаре.
    Возвращает (url, date, time):
      date — (year, month, day) или None,
      time — (hour, minute) или None.
    Приоритет: матч с '- : -' (ещё не сыгран/идёт), затем остальные наши."""
    candidates = []
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
            y = today.year  # год в календаре не указан — берём текущий
        candidates.append({
            "url": url,
            "date": (y, mo, d) if (y and mo and d) else None,
            "time": (h, mm) if h is not None else None,
            "upcoming": "- : -" in s,
        })
    if not candidates:
        return "", None, None
    # Сначала матчи, у которых дата совпадает с сегодняшней
    today_key = (today.year, today.month, today.day)
    pool = [c for c in candidates if c["date"] == today_key]
    if not pool:
        # Если даты не разобрались ни у кого — берём как есть
        pool = [c for c in candidates if c["date"] is None]
    if not pool:
        return "", None, None
    upcoming = [c for c in pool if c["upcoming"]]
    pick = (upcoming or pool)[0]
    return pick["url"], pick["date"], pick["time"]

def main():
    global STATE_FILE, OUR_IS_HOME, START_H, START_M
    now = datetime.now(MSK)

    if PAST_MATCH:
        match_url = MATCH_URL
        START_H, START_M = 15, 20
        STATE_FILE = "test_state.json"
    else:
        cal = jina(CALENDAR_URL)
        if not cal:
            send("🧪 Диагностика: календарь не скачался")
            return

        match_url, mdate, mtime = find_our_match(cal, now.date())
        if not match_url:
            print("Наш матч на сегодня не найден — выходим")
            return

        # Проверяем дату: работаем только в день матча
        today_key = (now.year, now.month, now.day)
        if mdate and mdate != today_key:
            print("Наш матч не сегодня:", mdate, "— выходим")
            return

        if mtime:
            START_H, START_M = mtime
        else:
            START_H, START_M = 18, 0
            print("Время матча не найдено, ставим по умолчанию 18:00")

        STATE_FILE = "prod_state.json"

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
