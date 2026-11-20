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

# ====== РЕЖИМ ТЕСТА НА ПРОШЕДШЕМ МАТЧЕ ======
# True  — тест на матче с Триумфом: только лог, в канал ничего не уходит.
# False — боевой режим. ПЕРЕД ВОСКРЕСЕНЬЕМ ВЕРНИ False!
PAST_MATCH = True
MATCH_URL = "https://ollf.ru/match/5905503"

START_H, START_M = 18, 0
DURATION_MIN = 75
LINEUP_CHECK_BEFORE = 5

VK_TRANSLATION = "https://vkvideo.ru/@club154907309/all"

TIME_PAT = re.compile(r"(\d{1,3})'\s*(\d{2})''")
SCORE_END = re.compile(r"(\d{1,2})\s*:\s*(\d{1,2})\s*$")

MSK = timezone(timedelta(hours=3))

OUR_IS_HOME = True
LOCATION = "уточняется"
TIME_STR = "18:00"
STATE_FILE = "prod_state.json"

MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]
WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг",
               "пятница", "суббота", "воскресенье"]

# ================= TELEGRAM =================
def tg(method, **params):
    r = requests.post("https://api.telegram.org/bot" + TOKEN + "/" + method,
                      data=params, timeout=20)
    return r.json()

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def send(text):
    if PAST_MATCH:
        print("[ТЕСТ] Сообщение НЕ отправлено в канал:")
        print(text.replace("<b>", "").replace("</b>", ""))
        return
    res = tg("sendMessage", chat_id=CHANNEL, text=text[:3900],
             parse_mode="HTML")
    if not res.get("ok"):
        print("Telegram error:", res)

# ================= JINA =================
def jina(url, html=False):
    headers = {"X-Return-Format": "html" if html else "markdown"}
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

# ================= ОБЩИЙ ПАРСИНГ =================
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
    found = []
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
        print("Будущих дат на странице не найдено")
        return None, None
    found.sort()
    for _, _, _, d_, frag in found[:5]:
        print("Кандидат даты:", d_, "| фрагмент:", frag[:90])
    _, _, e, d, _ = found[0]
    tm = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", md[e:e + 200])
    if tm:
        return d, (int(tm.group(1)), int(tm.group(2)))
    tm = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", md[max(0, e - 150):e])
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

# Слова, которые никогда не являются именами игроков
JUNK_WORDS = ("кубок", "чемпионат", "лига", "турнир", "календарь",
              "группа", "сезон", "тур ", "оллф", "статистика",
              "таблица", "протокол", "события", "автогол")

def _is_junk_name(name):
    low = name.lower()
    return any(w in low for w in JUNK_WORDS)

def lineup_side_is_right(md, team1, team2):
    """Запасной способ: наша колонка справа в таблице составов?"""
    up = md.upper()
    head_idx = up.find("СТАРТОВЫЕ СОСТАВЫ")
    if head_idx < 0:
        head_idx = up.find("СОСТАВ")
    if head_idx >= 0:
        head = up[head_idx: head_idx + 600]
        p_ours = head.find(OUR_KEY.upper())
        other = team2 if OUR_KEY.upper() in team1.upper() else team1
        p_other = head.find(other.upper())
        if p_ours >= 0 and p_other >= 0:
            print("Шапка составов: наш =", p_ours, ", соперник =", p_other)
            return p_ours > p_other
    return not OUR_IS_HOME

def parse_lineups(md, ours_is_right):
    """Разбор раздела СТАРТОВЫЕ СОСТАВЫ.
    Формат OLLF: игроки в ссылках на страницы игроков, у части —
    фото-обёртка перед именем. Пометки ВР и (К) идут после фамилии.
    Сторону определяем по заголовку команды над списком игроков."""
    up = md.upper()
    idx = up.find("СТАРТОВЫЕ СОСТАВЫ")
    if idx < 0:
        print("Раздел СОСТАВЫ не найден в этом тексте")
        return None
    zone = md[idx: idx + 8000]

    # Игрок с фото:  * 1 [![Image ...](фото) Семёнов Александр ВР](ссылка)
    PAT_P1 = re.compile(
        r"\*\s+(\d{1,2})\s+
$$
!Image[^]*
$$
$[^)]*$\s*"
        r"(" + NAME_TOKEN + r")\s+(" + NAME_TOKEN + r")\s*($К$|ВР)?\]"
        r"
$$
\s*https://ollf\.ru/player/", re.IGNORECASE)    # Игрок без фото:  * 9 [Семёнов Николай](ссылка)    PAT_P2 = re.compile(        r"\*\s+(\d{1,2})\s+"        r"(" + NAME_TOKEN + r")\s+(" + NAME_TOKEN + r")\s*(К|ВР)?"        r"\s*https://ollf\.ru/player/", re.IGNORECASE)    # Заголовок команды в разделе составов    PAT_TEAM = re.compile(        r"([^!]+?)https://ollf\.ru/tournament/\d+/teams"        r"/application\?team_id=\d+", re.IGNORECASE)    sections = []  # [(имя команды, [(номер, имя, пометка), ...])]    current = None    for line in zone.splitlines():        tm = PAT_TEAM.search(line)        if tm:            current = tm.group(1).strip()            sections.append((current, []))            continue        pm = PAT_P1.search(line) or PAT_P2.search(line)        if pm and current is not None:            num = int(pm.group(1))            name = (pm.group(2) + " " + pm.group(3)).strip()            if _is_junk_name(name):                continue            mark = pm.group(4) or ""            if all(p[0] != num or p[1] != name for p in sections[-1][1]):                sections[-1][1].append((num, name, mark))    left = sections[0][1] if len(sections) > 0 else []    right = sections[1][1] if len(sections) > 1 else []    print("Команды в разделе:", [s[0] for s in sections])    print("Состав LEFT :", left)    print("Состав RIGHT:", right)    # Наша секция: та, где больше всего наших игроков    candidates = [plist for tname, plist in sections                  if OUR_KEY.upper() in tname.upper()]    if candidates:        ours = max(candidates, key=len)    else:        ours = right if ours_is_right else left    if len(ours) >= 5:        return ours    # Не набралось — печатаем сырые строки раздела для подстройки    print("---- СЫРЫЕ СТРОКИ РАЗДЕЛА СОСТАВОВ (до 60) ----")    shown = 0    for line in zone.splitlines():        s = line.strip()        if not s:            continue        print("|", s[:160])        shown += 1        if shown >= 60:            break    print("---- КОНЕЦ СЫРЫХ СТРОК ----")    return Nonedef dump_lineup_diagnostics(md):    up = md.upper()    idx = up.find("СТАРТОВЫЕ СОСТАВЫ")    if idx < 0:        idx = up.find("СОСТАВ")    zone = md[idx: idx + 4000] if idx >= 0 else md    shown = 0    for line in zone.splitlines():        s = line.strip()        if not s or shown >= 30:            break        if re.search(r"\d{1,2}[\s.]{1,3}[А-Яа-яЁё]", s) or "/player/" in s:            print("Строка состава? ", s[:120])            shown += 1def get_lineup_from_sources(match_url, md, ours_is_right):    """Пробуем состав на основной странице и во вкладках протокола/событий."""    sources = [("основная", md)]    for param in ("protocol", "events"):        tmd = jina(match_url + "?active=" + param)        if tmd:            sources.append(("?active=" + param, tmd))    for label, text in sources:        print("Пробуем состав из:", label)        players = parse_lineups(text, ours_is_right)        if players:            return players, label    return None, Nonedef send_lineup(players):    lines = []    for num, name, mark in players:        s = "№" + str(num) + " " + name        if mark == "ВР":            s += " 🧤"        elif mark == "(К)":            s += " 🅺"        lines.append(esc(s))    send("📋 <b>Наш состав на сегодняшнюю игру</b>\n\n"         + "\n".join(lines) + "\n\nВ бой, ITPROVIDER! 💪")# ================= ТРАНСЛЯЦИЯ =================def find_stream_url(html, md):    for text in (html, md):        if not text:            continue        # 1) VK-плеер во врезке: video_ext.php?oid=..&id=..        for m in re.finditer(                r"https?://[^\s\"'<>()\*video_ext\.php[^\s\"'<>()\*",                text):            u = m.group(0).replace("&amp;", "&")            om = re.search(r"oid=(-?\d+)", u)            im = re.search(r"\bid=(\d+)", u)            if om and im:                return "https://vkvideo.ru/video" + om.group(1) + "_" + im.group(1)        # 2) прямые ссылки на видео или эфир VK        for m in re.finditer(                r"https?://[^\s\"'<>()\
$$
*(?:vkvideo\.ru|vk\.com|vk\.ru)"
                r"/(?:video|live)-?\d+_\d+[^\s\"'<>()\\]*", text):
            return m.group(0).replace("&amp;", "&")
    return None

def dump_stream_diagnostics(html, md):
    for text, label in ((md, "MD"), (html, "HTML")):
        if not text:
            continue
        for kw in ("iframe", "player", "video", "VK Video", "vkvideo"):
            m = re.search(re.escape(kw), text, re.IGNORECASE)
            if m:
                frag = text[max(0, m.start() - 120):m.end() + 200]
                frag = frag.replace("\n", " ")
                print("[" + label + " «" + kw + "»]:", frag[:280])
    if md and len(md) < 6000:
        print("---- MD ВКЛАДКИ ТРАНСЛЯЦИИ ЦЕЛИКОМ ----")
        print(md)
        print("---- КОНЕЦ MD ----")

def get_stream(match_url, html, md):
    burl = match_url + "?active=broadcast"
    bmd = jina(burl)
    bhtml = jina(burl, html=True)
    surl = find_stream_url(bhtml, bmd)
    if surl:
        return surl
    surl = find_stream_url(html, md)
    if surl:
        return surl
    print("=== ДИАГНОСТИКА ТРАНСЛЯЦИИ ===")
    dump_stream_diagnostics(bhtml, bmd)
    return None

# ================= СОБЫТИЯ МАТЧА =================
def parse_html_events(html, team1, team2):
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

# ================= STATE =================
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)

# ================= КАЛЕНДАРЬ =================
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
    pick = (upcoming or pool)[0]
    print("Строка календаря:", pick["line"][:200])
    return pick["url"], pick["date"], pick["time"]

# ================= MAIN =================
def main():
    global STATE_FILE, OUR_IS_HOME, START_H, START_M, LOCATION, TIME_STR
    now = datetime.now(MSK)
    LOCATION = "уточняется"
    TIME_STR = format(START_H, "02d") + ":" + format(START_M, "02d")
    mdate, mtime = None, None

    if PAST_MATCH:
        match_url = MATCH_URL
        START_H, START_M = 15, 20
        TIME_STR = "15:20"
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

        if mdate and mdate != (now.year, now.month, now.day):
            print("Наш матч не сегодня:", mdate, "— выходим")
            return

        STATE_FILE = "prod_state.json"

    md = jina(match_url)
    if not md:
        send("🧪 Диагностика: страница матча не скачалась (md пустой)")
        return
    time.sleep(5)
    html = jina(match_url, html=True)

    page_date, page_time = parse_match_datetime_from_page(md, now)
    if mdate is None:
        mdate = page_date
    if mtime is None:
        mtime = page_time

    if not PAST_MATCH:
        if mdate is None:
            print("Дата матча не распознана — анонс не отправляем, выходим")
            return
        if mdate != (now.year, now.month, now.day):
            print("Наш матч не сегодня:", mdate, "— выходим")
            return

        if mtime:
            START_H, START_M = mtime
            TIME_STR = format(START_H, "02d") + ":" + format(START_M, "02d")
        else:
            START_H, START_M = 18, 0
            TIME_STR = "уточняется"
            print("Время не распознано — в анонсе напишем 'уточняется'")

    team1, team2 = parse_teams(md)
    if OUR_KEY not in team1.upper() and OUR_KEY not in team2.upper():
        print("Это не наш матч:", team1, team2)
        return

    OUR_IS_HOME = OUR_KEY in team1.upper()
    print("Команды:", team1, "vs", team2, "| Мы хозяева:", OUR_IS_HOME)

    # ====== ТЕСТОВЫЙ РЕЖИМ: состав и трансляция только в лог ======
    if PAST_MATCH:
        side_right = lineup_side_is_right(md, team1, team2)
        print("Наша колонка справа?", side_right)
        players, src = get_lineup_from_sources(match_url, md, side_right)
        if players:
            print("ТЕСТ СОСТАВ — найдено", len(players), "игроков из", src)
            for num, name, mark in players:
                print("   №", num, name, mark)
            send_lineup(players)
        else:
            print("ТЕСТ СОСТАВ — парсер не нашёл игроков ни в одной вкладке")
        surl = get_stream(match_url, html, md)
        print("ТЕСТ ТРАНСЛЯЦИЯ:", surl if surl else "не найдена")
        return

    st = load_state()

    st.setdefault("seen", [])
    st.setdefault("started", False)
    st.setdefault("final", False)
    st.setdefault("score", [0, 0])

    today_key = now.strftime("%Y-%m-%d")

    if st.get("match_date") != today_key:
        st["seen"] = []
        st["started"] = False
        st["final"] = False
        st["score"] = [0, 0]
        st["match_date"] = today_key
        st.pop("lineup", None)
        st.pop("stream", None)
        save_state(st)

    match_start_dt = now.replace(hour=START_H, minute=START_M,
                                 second=0, microsecond=0)
    match_end_dt = match_start_dt + timedelta(minutes=DURATION_MIN)

    # ====== АНОНС ДНЯ МАТЧА (один раз в день, с 11:00 МСК) ======
    announce_from = now.replace(hour=11, minute=0, second=0, microsecond=0)
    in_window = now < match_end_dt and (now >= announce_from
                                        or now >= match_start_dt)
    if in_window and st.get("announced") != today_key:
        opponent = team2 if OUR_IS_HOME else team1
        LOCATION = parse_location(md)
        post = build_announcement(opponent, mdate, TIME_STR)
        print("---- АНОНС ----")
        print(post.replace("<b>", "").replace("</b>", ""))
        print("---------------")
        send(post)
        st["announced"] = today_key
        save_state(st)

    # ====== СОСТАВ НА ИГРУ (со 'старт - 5 минут') ======
    check_from = match_start_dt - timedelta(minutes=LINEUP_CHECK_BEFORE)
    if check_from <= now < match_end_dt and st.get("lineup") != today_key:
        side_right = lineup_side_is_right(md, team1, team2)
        players, _ = get_lineup_from_sources(match_url, md, side_right)
        if players:
            print("Состав найден:", players)
            send_lineup(players)
            st["lineup"] = today_key
            save_state(st)

    # ====== ССЫЛКА НА ТРАНСЛЯЦИЮ (со 'старт - 5 минут') ======
    if (match_start_dt - timedelta(minutes=LINEUP_CHECK_BEFORE) <= now
            < match_end_dt and st.get("stream") != today_key):
        surl = get_stream(match_url, html, md)
        if surl:
            print("Найдена трансляция:", surl)
            send("📺 <b>А вот и ссылка на игру!</b>\n\n" + surl)
            st["stream"] = today_key
            save_state(st)

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

    if now > match_end_dt and st.get("started") and not st.get("final"):
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
