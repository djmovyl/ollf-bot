import os, re, time, json, requests, traceback
from datetime import datetime, timedelta, timezone

TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL = os.environ.get("CHANNEL", "")
CALENDAR_URL = "https://ollf.ru/tournament/1067343/calendar"
OUR_KEY = "ITPROVIDER"
# PAST_MATCH = True  -> тестовый режим: разбор MATCH_URL, только лог
# PAST_MATCH = False -> боевой режим: календарь + реальный канал
PAST_MATCH = False
MATCH_URL = "https://ollf.ru/match/5905503"
START_H, START_M = 18, 0
DURATION_MIN = 75
LINEUP_CHECK_BEFORE = 5
VK_TRANSLATION = "https://vkvideo.ru/@club154907309/all"
STATE_FILE = "prod_state.json"

# Служебные константы для регулярок: избегаем опасных последовательностей
BS = chr(92)
LB = BS + "["
RB = BS + "]"
LP = BS + "("
RP = BS + ")"
D = BS + "d"
S = BS + "s"
GL = "("
GR = ")"

TIME_PAT = re.compile(r"(\d{1,3})'\s*(\d{2})''")
SCORE_END = re.compile(r"(\d{1,2})\s*:\s*(\d{1,2})\s*$")
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

CARD_RED = ("кк", "красн", "🟥", "red card", "удал",
            "card-red", "card_red", "redcard")
CARD_YELLOW = ("жк", "жёлт", "желт", "жолт", "🟨", "yellow card",
               "предупреждение", "card-yellow", "card_yellow",
               "yellowcard")

JUNK = ("кубок", "чемпионат", "лига", "турнир", "календарь", "группа",
        "сезон", "тур ", "оллф", "статистика", "таблица", "протокол",
        "события", "автогол")
MONTHS_RU = ("января февраля марта апреля мая июня "
             "июля августа сентября октября ноября декабря").split()
WEEKDAYS_RU = ("понедельник вторник среда четверг "
               "пятница суббота воскресенье").split()
MSK = timezone(timedelta(hours=3))
MONTH_RE = "|".join(MONTHS_RU)

CITY_WORDS = ("нижнекамск", "казань", "альметьевск", "чебоксары",
              "уфа", "нижний", "новгород", "набережные", "челны",
              "москва", "татарстан", "чемпионат", "лига", "турнир",
              "матч", "соперник", "емпионат")

# Между месяцем и временем — всё, кроме двоеточия и перевода строки,
# и нежадно: разделитель не может съесть цифру из времени
DT_LINE = re.compile(
    r"(\d{1,2})\s+(" + MONTH_RE + r")[^:\n]{0,30}?(\d{1,2}):(\d{2})",
    re.I)

OUR_IS_HOME = True
LOCATION = "уточняется"
TIME_STR = "18:00"


def tg(method, **p):
    r = requests.post("https://api.telegram.org/bot" + TOKEN + "/" + method,
                      data=p, timeout=20)
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


def jina(url, html=False):
    h = {"X-Return-Format": "html" if html else "markdown"}
    for _ in range(3):
        try:
            r = requests.get("https://r.jina.ai/" + url,
                             headers=h, timeout=60)
            print("jina:", url, "html" if html else "md",
                  "->", r.status_code, len(r.text))
            if r.status_code == 200 and r.text.strip():
                return r.text
            time.sleep(10)
        except Exception as e:
            print("jina error:", e)
            time.sleep(10)
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


def strip_tags(html):
    return re.sub("<[^>]*>", " ", html)


def pin_tokens(text):
    """Все значки 📍 в тексте: [(позиция, первое слово после значка)]."""
    out = []
    i = text.find("📍")
    while i >= 0:
        toks = []
        for w in text[i + 1:].split():
            t = w.strip(".,;:!?()[]|/")
            if t.isalpha():
                toks.append(t)
            elif toks:
                break
        if toks:
            out.append((i, toks[0]))
        i = text.find("📍", i + 1)
    return out


def find_location(texts, date_positions):
    """Локация по всей странице: среди всех 📍 берём ближайший
    к позиции даты матча в том же тексте. Города и слова-обломки
    отбрасываем. Затем fallback по названиям площадок."""
    best = None
    for text, dpos in zip(texts, date_positions):
        if not text or not dpos:
            continue
        for p, tok in pin_tokens(text):
            if tok.lower() in CITY_WORDS:
                print("📍 пропущен (город/мусор):", tok)
                continue
            dist = min(abs(p - d) for d in dpos)
            print("📍 кандидат:", tok, "| дистанция до даты:", dist)
            if best is None or dist < best[0]:
                best = (dist, tok)
    if best and best[0] <= 3000:
        return best[1]
    for text in texts:
        if not text:
            continue
        for kw in ("Тасма", "Манеж", "Стадион", "Арена", "ФОК",
                   "Спорткомплекс"):
            for line in text.splitlines():
                if kw.lower() in line.lower():
                    toks = [w for w in line.split()
                            if w.isalpha()
                            and w.lower() not in CITY_WORDS]
                    if toks:
                        return toks[0]
    return "уточняется"


def extract_match_info(md, html, t1, t2):
    """Дата/время/локация со страницы матча.
    Формат: '15 ноября / воскресенье / 20:00'.
    Из кандидатов выбирается тот, рядом с которым обе команды."""
    texts = [md]
    if html:
        texts.append(strip_tags(html))
    cands = []
    date_positions = []
    for text in texts:
        positions = []
        if text:
            for m in DT_LINE.finditer(text):
                positions.append(m.start())
                win = text[max(0, m.start() - 300): m.end() + 600]
                score = 0
                for name in (t1, t2):
                    if any(p in win for p in name.split()):
                        score += 1
                cd = (datetime.now(MSK).year,
                      MONTHS_RU.index(m.group(2).lower()) + 1,
                      int(m.group(1)))
                ct = (int(m.group(3)), int(m.group(4)))
                cands.append((score, -m.start(), cd, ct))
                print("Кандидат даты:", m.group(0), "| очки:", score)
        date_positions.append(positions)
    if cands:
        best = max(cands, key=lambda c: (c[0], c[1]))
        print("Выбранная шапка:", best[2], best[3])
        return best[2], best[3], find_location(texts, date_positions)
    print("Строк с датой/временем не найдено")
    return None, None, "уточняется"


def parse_teams(md):
    idx = md.find("События матча")
    zone = md[:idx] if idx > 0 else md
    names = []
    for line in zone.splitlines():
        if "teams/application?team_id=" not in line:
            continue
        for c in find_brackets(line):
            c = c.strip()
            if (c and not c.startswith("!") and "Image" not in c
                    and ".png" not in c and c not in names):
                names.append(c)
    if len(names) >= 2:
        return names[0], names[1]
    return "Хозяева", "Гости"


def is_junk(name):
    low = name.lower()
    return any(w in low for w in JUNK)


def parse_lineups(md):
    idx = md.upper().find("СТАРТОВЫЕ СОСТАВЫ")
    if idx < 0:
        return None
    sections = []
    cur = None
    for raw in md[idx: idx + 8000].splitlines():
        line = IMG_MD.sub(" ", raw)
        m = PAT_TEAM.search(line)
        if m:
            cur = m.group(1).strip()
            sections.append((cur, []))
            continue
        pm = PAT_P.search(line)
        if pm and cur is not None:
            num = int(pm.group(1))
            name = (pm.group(2) + " " + pm.group(3)).strip()
            if is_junk(name):
                continue
            mark = pm.group(4) or ""
            pl = sections[-1][1]
            if all(p[0] != num or p[1] != name for p in pl):
                pl.append((num, name, mark))
    return sections or None


def our_lineup(md, proto):
    for label, text in (("protocol", proto), ("main", md)):
        if not text:
            continue
        secs = parse_lineups(text)
        if not secs:
            continue
        print("Составы из", label, ":", [s[0] for s in secs])
        cand = [pl for t, pl in secs if OUR_KEY.upper() in t.upper()]
        if cand:
            best = max(cand, key=len)
            if len(best) >= 5:
                return best
    if proto:
        print("---- СЫРЫЕ СТРОКИ СОСТАВОВ ----")
        idx = proto.upper().find("СТАРТОВЫЕ СОСТАВЫ")
        shown = 0
        for line in proto[idx: idx + 4000].splitlines():
            s = line.strip()
            if s:
                print("|", s[:160])
                shown += 1
            if shown >= 40:
                break
    return None


def send_lineup(players):
    lines = []
    for num, name, mark in players:
        s = "№" + str(num) + " " + name
        if mark == "ВР":
            s += " 🧤"
        elif "К" in mark:
            s += " 🅺"
        lines.append(esc(s))
    send("📋 <b>Наш состав на сегодняшнюю игру</b>\n\n"
         + "\n".join(lines) + "\n\nВ бой, ITPROVIDER! 💪")


def cut_num(s, key):
    start = 0
    while True:
        i = s.find(key, start)
        if i < 0:
            return None
        if i > 0 and s[i - 1].isalnum():
            start = i + 1
            continue
        out = ""
        for ch in s[i + len(key):]:
            if ch.isdigit() or (ch == "-" and not out):
                out += ch
            else:
                break
        if out:
            return out
        start = i + 1


def find_stream_url(texts):
    for text in texts:
        if not text:
            continue
        t = text.replace("&amp;", "&")
        for tok in (t.replace('"', " ").replace("'", " ")
                    .replace("<", " ").replace(">", " ").split()):
            low = tok.lower()
            if "video_ext.php" in low:
                oid = cut_num(tok, "oid=")
                vid = cut_num(tok, "id=")
                if oid and vid:
                    return "https://vkvideo.ru/video" + oid + "_" + vid
            if low.startswith("http"):
                for key in ("vkvideo.ru/video", "vkvideo.ru/live",
                            "vk.com/video", "vk.ru/video"):
                    if key in low:
                        return tok.rstrip(",;)]}.")
    return None


def get_stream(match_url, md):
    burl = match_url + "?active=broadcast"
    for attempt in range(3):
        surl = find_stream_url([jina(burl, html=True), jina(burl), md])
        if surl:
            return surl
        print("Трансляция не найдена, попытка", attempt + 1, "из 3")
        time.sleep(10)
    return None


def md_events(md):
    out, score = [], [0, 0]
    for raw in md.splitlines():
        s = raw.strip()
        if not s.startswith("*"):
            continue
        m = TIME_PAT.search(s)
        if not m:
            continue
        minute = int(m.group(1)) + (1 if int(m.group(2)) > 0 else 0)
        tstr = m.group(0)
        players = [c.strip() for c in find_brackets(s)
                   if NAME_RE.fullmatch(c.strip())]
        low = s.lower()
        scoring = None
        ms = SCORE_END.search(s)
        if ms:
            nh, na = int(ms.group(1)), int(ms.group(2))
            if nh > score[0]:
                scoring = "home"
            elif na > score[1]:
                scoring = "away"
            score = [nh, na]
        if any(w in low for w in CARD_RED):
            et = "red"
        elif any(w in low for w in CARD_YELLOW):
            et = "yellow"
        elif scoring:
            et = "goal"
        elif players:
            et = "card"
        else:
            et = "unknown"
            print("НЕОПОЗНАННОЕ СОБЫТИЕ (для отладки):", s[:220])
        out.append({"et": et, "minute": minute, "tstr": tstr,
                    "players": players, "score": score[:],
                    "scoring": scoring})
    return out


def merge_events(md, proto):
    evs = []
    seen = set()
    sources = [md_events(md)]
    if proto:
        sources.append(md_events(proto))
    for src in sources:
        for e in src:
            if e["et"] == "unknown":
                continue
            key = (e["minute"], e["et"], tuple(e["players"]))
            if key in seen:
                continue
            seen.add(key)
            evs.append(e)
    evs.sort(key=lambda e: e["minute"])
    return evs


def classify_card(html, tstr, player):
    if not html:
        return "yellow", ""
    frags = []
    for m in re.finditer(re.escape(tstr), html):
        frag = html[max(0, m.start() - 600): m.end() + 600]
        if player and player.split()[0] not in frag:
            continue
        frags.append(frag)
    if not frags:
        for m in re.finditer(re.escape(tstr), html):
            frags.append(html[max(0, m.start() - 600): m.end() + 600])
    for frag in frags:
        low = frag.lower()
        if any(w in low for w in CARD_RED):
            return "red", frag
        if any(w in low for w in CARD_YELLOW):
            return "yellow", frag
    frag = frags[0] if frags else ""
    if frag:
        print("ОКНО КАРТОЧКИ (для отладки):",
              frag[:400].replace("\n", " "))
    return "yellow", frag


def score_text_for(sc):
    our, opp = (sc[0], sc[1]) if OUR_IS_HOME else (sc[1], sc[0])
    shown = str(sc[0]) + " : " + str(sc[1])
    if our > opp:
        return "Счёт: <b>" + shown + "</b> в нашу пользу! 🎉"
    if our < opp:
        return "Счёт: <b>" + shown + "</b>. Не сдаёмся! 💪"
    return "Счёт: <b>" + shown + "</b>. На табло ничья!"


def render_post(ev):
    m, p, a = ev["minute"], ev["player"], ev.get("assist")
    if ev["et"] == "goal":
        st = score_text_for(ev["score"])
        if ev["ours"]:
            pas = "🎯 Голевой пас: " + a + "\n" if a else ""
            return ("🔥⚽️ <b>Г-О-О-О-Л! 🔥⚽️</b>\n\n"
                    "⚽ <b>АВТОР ГОЛА: " + p + "</b> 🌟\n" + pas
                    + "⏱ На " + str(m) + "' минуте!\n\n" + st)
        return ("😢 <b>Пропускаем...</b> 😢\n\n"
                "На " + str(m) + "' минуте соперник забивает.\n\n" + st)
    if ev["et"] == "yellow":
        if ev["ours"]:
            return ("🟡 <b>ЖЁЛТАЯ КАРТОЧКА у нас</b>\n\n🟡 " + p
                    + "\n⏱ На " + str(m) + "' минуте.")
        return ("🟡 <b>Жёлтая карточка у соперника</b>\n\n⏱ На "
                + str(m) + "' минуте.")
    if ev["et"] == "red":
        if ev["ours"]:
            return ("🚨 <b>КРАСНАЯ КАРТОЧКА — УДАЛЕНИЕ У НАС</b>\n\n🔴 "
                    + p + "\n⏱ На " + str(m) + "' минуте.")
        return ("🚨 <b>КРАСНАЯ КАРТОЧКА У СОПЕРНИКА!</b>\n\n⏱ На "
                + str(m) + "' минуте.")
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


def line_date(s, today):
    dm = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b", s)
    if dm:
        return (int(dm.group(3)) if dm.group(3) else today.year,
                int(dm.group(2)), int(dm.group(1)))
    dm = re.search(r"\b(\d{1,2})\s+(" + "|".join(MONTHS_RU) + r")\b",
                   s, re.I)
    if dm:
        return (today.year, MONTHS_RU.index(dm.group(2).lower()) + 1,
                int(dm.group(1)))
    return None


def find_our_match(cal_md, today):
    cands = []
    for raw in cal_md.splitlines():
        s = raw.strip()
        if OUR_KEY not in s or "ollf.ru/match/" not in s:
            continue
        m = re.search(r"match/(\d+)", s)
        if not m:
            continue
        tm = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
        cands.append({"url": "https://ollf.ru/match/" + m.group(1),
                      "line": s, "date": line_date(s, today),
                      "time": (int(tm.group(1)), int(tm.group(2)))
                              if tm else None,
                      "upcoming": "- : -" in s})
    if not cands:
        return "", None, None
    tk = (today.year, today.month, today.day)
    pool = ([c for c in cands if c["date"] == tk]
            or [c for c in cands if c["date"] is None])
    if not pool:
        return "", None, None
    pick = ([c for c in pool if c["upcoming"]] or pool)[0]
    print("Строка календаря:", pick["line"][:200])
    return pick["url"], pick["date"], pick["time"]


def test_mode():
    """Тестовый прогон на сыгранном матче: только лог."""
    md = jina(MATCH_URL)
    if not md:
        print("Страница матча не скачалась")
        return
    html = jina(MATCH_URL, html=True)
    t1, t2 = parse_teams(md)
    OUR_IS_HOME = OUR_KEY in t1.upper()
    print("Команды:", t1, "vs", t2, "| Мы хозяева:", OUR_IS_HOME)
    try:
        mdate, mtime, loc = extract_match_info(md, html, t1, t2)
        print("Шапка матча: дата", mdate, "| время", mtime,
              "| локация", loc)
    except Exception:
        print("Ошибка разбора шапки (продолжаем):")
        print(traceback.format_exc())
    proto = jina(MATCH_URL + "?active=protocol")
    lineup = our_lineup(md, proto)
    if lineup:
        print("ТЕСТ СОСТАВ — найдено", len(lineup), "игроков")
        send_lineup(lineup)
    else:
        print("ТЕСТ СОСТАВ — не найден")
    try:
        print("ТЕСТ ТРАНСЛЯЦИЯ:",
              get_stream(MATCH_URL, md) or "не найдена")
    except Exception:
        print("Ошибка блока трансляции (продолжаем):")
        print(traceback.format_exc())
    for e in merge_events(md, proto):
        print("СОБЫТИЕ:", e["et"], str(e["minute"]) + "'",
              e["players"], e["score"])


def main():
    global OUR_IS_HOME, START_H, START_M, TIME_STR
    now = datetime.now(MSK)
    if PAST_MATCH:
        test_mode()
        return
    cal = jina(CALENDAR_URL)
    if not cal:
        print("Календарь не скачался — выходим, повтор через 5 минут")
        return
    match_url, mdate, mtime = find_our_match(cal, now.date())
    if not match_url:
        print("Наш матч на сегодня не найден — выходим")
        return
    if mdate and mdate != (now.year, now.month, now.day):
        print("Наш матч не сегодня:", mdate, "— выходим")
        return
    md = jina(match_url)
    if not md:
        print("Страница матча не скачалась — выходим")
        return
    html = jina(match_url, html=True)
    t1, t2 = parse_teams(md)
    if OUR_KEY not in t1.upper() and OUR_KEY not in t2.upper():
        print("Это не наш матч:", t1, t2)
        return
    OUR_IS_HOME = OUR_KEY in t1.upper()
    print("Команды:", t1, "vs", t2, "| Мы хозяева:", OUR_IS_HOME)

    # Шапка: время из календаря, фолбэк со страницы; локация со страницы
    page_date = page_time = None
    try:
        page_date, page_time, LOCATION = extract_match_info(md, html,
                                                            t1, t2)
    except Exception:
        print("Ошибка разбора шапки (продолжаем):")
        print(traceback.format_exc())
    if mtime:
        START_H, START_M = mtime
        TIME_STR = format(START_H, "02d") + ":" + format(START_M, "02d")
    elif page_time:
        START_H, START_M = page_time
        TIME_STR = format(START_H, "02d") + ":" + format(START_M, "02d")
        mdate = mdate or page_date
    else:
        TIME_STR = "уточняется"
    print("Старт матча:", TIME_STR, "| Локация:", LOCATION)

    proto = jina(match_url + "?active=protocol")
    lineup = our_lineup(md, proto)

    st = load_state()
    st.setdefault("seen", [])
    st.setdefault("started", False)
    st.setdefault("final", False)
    st.setdefault("score", [0, 0])
    tk = now.strftime("%Y-%m-%d")
    if st.get("match_date") != tk:
        st = {"seen": [], "started": False, "final": False,
              "score": [0, 0], "match_date": tk}
        save_state(st)
    if st.get("final"):
        print("Матч уже закрыт в состоянии — выходим")
        return

    t0 = now.replace(hour=START_H, minute=START_M,
                     second=0, microsecond=0)
    tend = t0 + timedelta(minutes=DURATION_MIN)
    win = t0 - timedelta(minutes=LINEUP_CHECK_BEFORE) <= now < tend

    if (now < tend
            and (now >= now.replace(hour=11, minute=0, second=0,
                                    microsecond=0) or now >= t0)
            and st.get("announced") != tk):
        post = announcement(t2 if OUR_IS_HOME else t1,
                            mdate or page_date, TIME_STR, LOCATION)
        print("---- АНОНС ----")
        print(post.replace("<b>", "").replace("</b>", ""))
        send(post)
        st["announced"] = tk
        save_state(st)
    if win and st.get("lineup") != tk and lineup:
        send_lineup(lineup)
        st["lineup"] = tk
        save_state(st)
    if win and st.get("stream") != tk:
        try:
            surl = get_stream(match_url, md)
            if surl:
                send("📺 <b>А вот и ссылка на игру!</b>\n\n" + surl)
                st["stream"] = tk
                save_state(st)
        except Exception:
            print("Ошибка блока трансляции (продолжаем):")
            print(traceback.format_exc())

    our_names = set(n for _, n, _ in lineup) if lineup else set()
    if not our_names:
        print("ВНИМАНИЕ: состав пуст — карточки могут "
              "неверно определить «наши/соперник»")
    raw_evs = merge_events(md, proto)
    events = []
    for e in raw_evs:
        ev = {"et": e["et"], "minute": e["minute"], "score": e["score"],
              "player": e["players"][0] if e["players"] else "?",
              "assist": e["players"][1] if len(e["players"]) > 1 else None}
        if e["et"] == "card":
            ctype, frag = classify_card(html, e["tstr"], ev["player"])
            ev["et"] = ctype
            print("КАРТОЧКА:", ev["player"], "->", ctype)
        if ev["et"] == "goal" and e["scoring"]:
            ev["ours"] = OUR_IS_HOME == (e["scoring"] == "home")
        else:
            ev["ours"] = any(p in our_names for p in e["players"])
        events.append(ev)

    if events and not st.get("started"):
        st["started"] = True
        save_state(st)
        send("🏟️ <b>МАТЧ НАЧАЛСЯ!</b> 🏟️\n\n🆚 <b>" + t1 + " vs " + t2
             + "</b>\n\nДержим кулаки за команду! 👊")
    for ev in events:
        eid = str(ev["minute"]) + "-" + ev["et"] + "-" + ev["player"]
        if eid in st["seen"]:
            continue
        post = render_post(ev)
        if post:
            time.sleep(2)
            send(post)
        st["seen"].append(eid)
    if events:
        st["score"] = events[-1]["score"]
    save_state(st)

    if now > tend and st.get("started") and not st.get("final"):
        st["final"] = True
        save_state(st)
        sc = st["score"]
        our, opp = (sc[0], sc[1]) if OUR_IS_HOME else (sc[1], sc[0])
        if our > opp:
            verdict = "🎉 <b>ПОБЕДА!</b> 🎉"
        elif our < opp:
            verdict = "😔 <b>ПОРАЖЕНИЕ</b> 😔"
        else:
            verdict = "🤝 <b>НИЧЬЯ</b> 🤝"
        send("🏁 <b>МАТЧ ЗАВЕРШЁН!</b> 🏁\n\n📊 Итоговый счёт: <b>"
             + str(sc[0]) + " : " + str(sc[1]) + "</b>\n\n" + verdict
             + "\n\nСпасибо за игру, команда! 🤝")


def announcement(opponent, mdate, time_str, loc):
    ds = "уточняется"
    if mdate:
        y, mo, d = mdate
        ds = str(d) + " " + MONTHS_RU[mo - 1] + ", "
        ds += WEEKDAYS_RU[datetime(y, mo, d).weekday()]
    return ("🔴 <b>FC ITPROVIDER — ДЕНЬ МАТЧА</b> 🔴\n\n"
            "🆚 Соперник: «" + esc(opponent) + "»\n"
            "🗓 Дата: " + ds + "\n"
            "⏱ Старт: " + time_str + " (МСК)\n"
            "🗺 Локация: " + esc(loc) + "\n\n"
            "🔗 Трансляция: " + VK_TRANSLATION + "\n\n"
            "Следите за обновлениями в этом чате.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
        try:
            st = load_state()
            last_err = st.get("last_err_ts", 0)
            if time.time() - last_err > 3600:
                send("🚨 Ошибка бота:\n<pre>"
                     + esc(traceback.format_exc()[-2500:]) + "</pre>")
                st["last_err_ts"] = time.time()
                save_state(st)
        except Exception:
            print("Не удалось отправить отчёт об ошибке")
        raise
