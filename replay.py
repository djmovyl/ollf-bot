import os, re, time, requests, traceback
from datetime import datetime, timedelta, timezone

VERSION = "2.8 (20.11.2026)"

# ===== НАСТРОЙКИ ТЕСТА =====
# TEST_SEND = True  -> посты уходят в CHAT_ID (сейчас: тестовая группа)
# TEST_SEND = False -> только печать в лог (безопасно)
TEST_SEND = True
CHAT_ID = "-1003949616458"
MATCH_URL = "https://ollf.ru/match/5905503"   # матч с Триумфом
OUR_KEY = "ITPROVIDER"

TOKEN = os.environ.get("BOT_TOKEN", "")

MONTHS_RU = ("января февраля марта апреля мая июня "
             "июля августа сентября октября ноября декабря").split()
WEEKDAYS_RU = ("понедельник вторник среда четверг "
               "пятница суббота воскресенье").split()
MSK = timezone(timedelta(hours=3))
MONTH_RE = "|".join(MONTHS_RU)

# Константы для сборки регулярок, которые ломались при копировании
BS = chr(92)
LB = BS + "["
RB = BS + "]"
LP = BS + "("
RP = BS + ")"

TIME_PAT = re.compile(r"(\d{1,3})'\s*(\d{2})''")
SCORE_END = re.compile(r"(\d{1,2})\s*:\s*(\d{1,2})\s*$")
NAME = r"[А-ЯЁ][а-яё\-]+"
NAME_RE = re.compile(NAME + r"\s+" + NAME)
IMG_MD = re.compile(
    "!" + LB + "[^" + RB + "]*" + RB + LP + "[^" + RP + "]*" + RP)
# Паттерны состава — дословно из версии 2.5.1, где они находили
# 10 игроков при том же размере протокола (22845 байт)
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

# Города, которые нельзя выдавать за локацию матча
CITY_WORDS = ("нижнекамск", "казань", "альметьевск", "чебоксары",
              "уфа", "нижний", "новгород", "набережные", "челны",
              "москва", "татарстан")

# Между месяцем и временем — всё, кроме двоеточия и перевода строки,
# и нежадно: разделитель не может сожрать цифру из времени
DT_LINE = re.compile(
    r"(\d{1,2})\s+(" + MONTH_RE + r")[^:\n]{0,30}?(\d{1,2}):(\d{2})",
    re.I)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send(text):
    if not TEST_SEND:
        print("[ТЕСТ] Сообщение НЕ отправлено:")
        print(text.replace("<b>", "").replace("</b>", ""))
        return
    try:
        r = requests.post(
            "https://api.telegram.org/bot" + TOKEN + "/sendMessage",
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


def loc_from_window(win, at):
    """Локация из окна шапки. Перебираем все значки 📍 и берём
    ближайший к найденной дате (с приоритетом тех, что после даты).
    Токены-города пропускаем, из значка берём ровно одно слово."""
    best = None
    i = win.find("📍")
    while i >= 0:
        toks = []
        for w in win[i + 1:].split():
            t = w.strip(".,;:!?()[]")
            if t.isalpha():
                toks.append(t)
            elif toks:
                break
        if toks and toks[0].lower() not in CITY_WORDS:
            dist = i - at if i >= at else (at - i) * 2
            if best is None or dist < best[0]:
                best = (dist, toks[0])
        i = win.find("📍", i + 1)
    if best:
        return best[1]
    # Запасной ход: известные названия площадок в окне
    for kw in ("Тасма", "Манеж", "Стадион", "Арена", "ФОК",
               "Спорткомплекс"):
        for line in win.splitlines():
            if kw.lower() in line.lower():
                toks = [w for w in line.split()
                        if w.isalpha() and w.lower() not in CITY_WORDS]
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
    for text in texts:
        if not text:
            continue
        for m in DT_LINE.finditer(text):
            win_start = max(0, m.start() - 300)
            win = text[win_start: m.end() + 600]
            score = 0
            for name in (t1, t2):
                if any(p in win for p in name.split()):
                    score += 1
            cd = (datetime.now(MSK).year,
                  MONTHS_RU.index(m.group(2).lower()) + 1,
                  int(m.group(1)))
            ct = (int(m.group(3)), int(m.group(4)))
            cands.append((score, -m.start(), cd, ct,
                          m.start() - win_start, win))
            print("Кандидат даты:", m.group(0), "| очки:", score)
    if cands:
        best = max(cands, key=lambda c: (c[0], c[1]))
        print("Выбранная шапка:", best[2], best[3])
        print("ОКНО ШАПКИ (для отладки):",
              best[5][:300].replace("\n", " | "))
        return best[2], best[3], loc_from_window(best[5], best[4])
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


def get_lineup(proto):
    secs = parse_lineups(proto) if proto else None
    if not secs:
        return []
    cand = [pl for t, pl in secs if OUR_KEY.upper() in t.upper()]
    return max(cand, key=len) if cand else []


def dump_protocol(proto):
    """Печатает сырые строки протокола — чтобы увидеть реальный
    формат состава, если регулярка его не взяла."""
    print("---- СЫРЫЕ СТРОКИ ПРОТОКОЛА (для отладки) ----")
    idx = proto.upper().find("СОСТАВ")
    start = max(0, idx - 200) if idx >= 0 else 0
    zone = proto[start: start + 4500]
    for line in zone.splitlines():
        s = line.strip()
        if s and ("[" in s or s.startswith("*") or s.isdigit()):
            print("|", s[:200])


def send_lineup(players):
    lines = []
    for num, name, mark in players:
        s = "№" + str(num) + " " + name
        if mark == "ВР":
            s += " 🧤"
        elif "К" in mark:
            s += " 🅺"
        lines.append(esc(s))
    send("📋 <b>Наш состав на игру</b>\n\n"
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


def get_stream(match_url):
    burl = match_url + "?active=broadcast"
    for attempt in range(4):
        surl = find_stream_url([jina(burl, html=True), jina(burl)])
        if surl:
            return surl
        print("Трансляция не найдена, попытка", attempt + 1, "из 4")
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


def announcement(opponent, mdate, mtime, loc):
    ds = "уточняется"
    if mdate:
        y, mo, d = mdate
        ds = str(d) + " " + MONTHS_RU[mo - 1] + ", "
        ds += WEEKDAYS_RU[datetime(y, mo, d).weekday()]
    ts = "уточняется"
    if mtime:
        ts = format(mtime[0], "02d") + ":" + format(mtime[1], "02d")
    return ("🔴 <b>FC ITPROVIDER — ДЕНЬ МАТЧА</b> 🔴\n\n"
            "🆚 Соперник: «" + esc(opponent) + "»\n"
            "🗓 Дата: " + ds + "\n"
            "⏱ Старт: " + ts + " (МСК)\n"
            "🗺 Локация: " + esc(loc) + "\n\n"
            "Следите за обновлениями в нашей группе.")


def main():
    global OUR_IS_HOME
    print("ВЕРСИЯ КОДА:", VERSION)
    md = jina(MATCH_URL)
    if not md:
        print("Страница матча не скачалась")
        return
    html = jina(MATCH_URL, html=True)
    t1, t2 = parse_teams(md)
    OUR_IS_HOME = OUR_KEY in t1.upper()
    print("Команды:", t1, "vs", t2, "| Мы хозяева:", OUR_IS_HOME)

    # --- АНОНС ---
    try:
        mdate, mtime, loc = extract_match_info(md, html, t1, t2)
        print("Шапка матча: дата", mdate, "| время", mtime,
              "| локация", loc)
    except Exception:
        mdate, mtime, loc = None, None, "уточняется"
        print("Ошибка разбора шапки (продолжаем):")
        print(traceback.format_exc())
    send(announcement(t2 if OUR_IS_HOME else t1, mdate, mtime, loc))

    # --- СОСТАВ ---
    proto = jina(MATCH_URL + "?active=protocol")
    lineup = get_lineup(proto)
    if lineup:
        print("ТЕСТ СОСТАВ — найдено", len(lineup), "игроков")
        send_lineup(lineup)
    else:
        print("ТЕСТ СОСТАВ — не найден, сырой протокол:")
        dump_protocol(proto)

    # --- ТРАНСЛЯЦИЯ (отдельным постом) ---
    try:
        surl = get_stream(MATCH_URL)
        if surl:
            send("📺 <b>А вот и ссылка на игру!</b>\n\n" + surl)
        else:
            print("ТЕСТ ТРАНСЛЯЦИЯ — не найдена")
    except Exception:
        print("Ошибка блока трансляции (продолжаем):")
        print(traceback.format_exc())

    # --- СОБЫТИЯ ---
    raw_evs = merge_events(md, proto)
    if not raw_evs:
        print("События не распознаны")
        return
    our_names = set(n for _, n, _ in lineup)
    evs = []
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
        evs.append(ev)
    send("🏟️ <b>МАТЧ НАЧАЛСЯ!</b> 🏟️\n\n🆚 <b>" + t1 + " vs " + t2
         + "</b>\n\nДержим кулаки за команду! 👊")
    for ev in evs:
        post = render_post(ev)
        if post:
            print("---- СОБЫТИЕ:", ev["et"], str(ev["minute"]) + "' ----")
            send(post)

    # --- ИТОГ ---
    sc = evs[-1]["score"]
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


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
        raise
