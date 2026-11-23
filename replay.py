import os, re, time, json, requests, traceback
from datetime import datetime, timedelta, timezone

VERSION = "replay-2.17 (23.11.2026)"

TOKEN = os.environ.get("BOT_TOKEN", "")
# Канал реплея: REPLAY_CHANNEL, если задан, иначе общий CHANNEL
CHANNEL = os.environ.get("REPLAY_CHANNEL") or os.environ.get("CHANNEL", "")
# Адрес Telegram API: через Cloudflare Worker, если задан TG_API_URL
TG_API = os.environ.get("TG_API_URL", "https://api.telegram.org")
# Секрет прокси из воркера (заголовок x-proxy-secret)
TG_PROXY_SECRET = os.environ.get("TG_PROXY_SECRET", "")
# Ключ Jina Reader: страховой режим. Анонимный доступ пробуем первым,
# с ключом — только когда обе анонимные ступени не взяли
JINA_KEY = os.environ.get("JINA_API_KEY", "")
MATCH_URL = "https://ollf.ru/match/5905514"
TABLES_URL = "https://ollf.ru/tournament/1067343/tables"
OUR_KEY = "ITPROVIDER"
VK_TRANSLATION = "https://vkvideo.ru/@club154907309/all"
# Ссылка на трансляцию: из секрета STREAM_URL, если задан,
# иначе — запасная ссылка на канал VK (как в основном боте)
STREAM_URL = os.environ.get("STREAM_URL", VK_TRANSLATION)
STATE_FILE = "test_state.json"
PAUSE = 3  # пауза между постами, сек

# Служебные константы для регулярок: избегаем опасных последовательностей
BS = chr(92)
LB = BS + "["
RB = BS + "]"
LP = BS + "("
RP = BS + ")"
S = BS + "s"

TIME_PAT = re.compile(r"(\d{1,3})'\s*(\d{2})''")
SCORE_END = re.compile(r"(\d{1,2})\s*:\s*(\d{1,2})\s*$")
NAME = r"[А-ЯЁ][а-яё\-]+"
NAME_RE = re.compile(NAME + r"\s+" + NAME)

IMG_MD = re.compile(
    "!" + LB + "[^" + RB + "]*" + RB + LP + "[^" + RP + "]*" + RP)
# Маркдаун-ссылка: [текст](адрес) -> текст
PAT_LINK = re.compile(
    LB + "([^" + RB + "]*)" + RB + LP + "[^" + RP + "]*" + RP)
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

DT_LINE = re.compile(
    r"(\d{1,2})\s+(" + MONTH_RE + r")[^:\n]{0,30}?(\d{1,2}):(\d{2})",
    re.I)
NUM_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b")
TIME_ONLY = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
# Площадка в контексте календаря: 'Манеж Физра', 'Стадион Тасма'
VENUE_CTX = re.compile(
    "(Манеж|Стадион|Арена|Спорткомплекс|ФОК)" + S + "+"
    + "[A-ZА-ЯЁA-Za-z0-9][^" + S + "|,;]*")

OUR_IS_HOME = True
LOCATION = "уточняется"

# Порядок путей загрузки страниц: перебираем по очереди, удачный путь
# запоминаем в состоянии — следующий прогон начнёт с него
PATH_PREF = ["worker", "allorigins", "codetabs", "direct", "jina"]


def tg(method, **p):
    last = None
    for attempt in range(4):
        try:
            r = requests.post(
                TG_API.rstrip("/") + "/bot" + TOKEN + "/" + method,
                data=p, timeout=30,
                headers={"x-proxy-secret": TG_PROXY_SECRET})
            return r.json()
        except Exception as e:
            last = e
            print("Telegram ошибка (попытка", attempt + 1, "из 4):", e)
            time.sleep(5)
    raise last


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send(text):
    res = tg("sendMessage", chat_id=CHANNEL, text=text[:3900],
             parse_mode="HTML")
    if not res.get("ok"):
        print("Telegram error:", res)
    else:
        print("[ОТПРАВЛЕНО] ", text.replace("<b>", "")
              .replace("</b>", "")[:120].replace("\n", " | "))


def html_to_md(raw):
    """Сырой HTML в грубый маркдаун — общий конвертер для воркера,
    прокси и прямого запроса (ссылки и списки, как у Jina)."""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw,
               flags=re.I | re.S)
    s = re.sub(r"<a\s+[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
               lambda m: LB + re.sub(r"<[^>]*>", "", m.group(2)).strip()
               + RP + LP + m.group(1) + RP, s, flags=re.I | re.S)
    s = re.sub(r"<(br|/p|/li|/tr|/h[1-6])[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "* ", s, flags=re.I)
    s = re.sub(r"<img[^>]*>", " ", s, flags=re.I)
    s = strip_tags(s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s)


def worker_fetch(url):
    """Путь через наш Cloudflare Worker (/proxy) — у OLLF анти-бот,
    который отсекает даже IP Cloudflare (468), так что сейчас это
    скорее заготовка на случай, если защита ослабнет."""
    try:
        r = requests.get(TG_API.rstrip("/") + "/proxy",
                         params={"url": url}, timeout=40,
                         headers={"x-proxy-secret": TG_PROXY_SECRET})
        print("worker:", url, "->", r.status_code, len(r.text))
        if r.status_code == 200 and r.text.strip():
            return r.text
    except Exception as e:
        print("worker error:", e)
    return ""


def proxy_fetch(url):
    """Путь через публичный прокси allorigins. Возвращает сырой HTML
    или пустую строку."""
    try:
        r = requests.get("https://api.allorigins.win/raw",
                         params={"url": url}, timeout=40)
        print("allorigins:", r.status_code, len(r.text))
        if r.status_code == 200 and r.text.strip():
            return r.text
    except Exception as e:
        print("allorigins error:", e)
    return ""


def codetabs_fetch(url):
    """Путь через публичный прокси codetabs — без регистрации и ключей.
    Возвращает сырой HTML или пустую строку."""
    try:
        r = requests.get("https://api.codetabs.com/v1/proxy",
                         params={"quest": url}, timeout=40)
        print("codetabs:", r.status_code, len(r.text))
        if r.status_code == 200 and r.text.strip():
            return r.text
    except Exception as e:
        print("codetabs error:", e)
    return ""


def direct_fetch(url, html=False):
    """Прямой запрос страницы, без посредников. Сайт OLLF отвечает
    анти-ботом (468) на серверные IP — тогда пустая строка."""
    try:
        r = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0 Safari/537.36"})
        print("direct:", url, "html" if html else "md",
              "->", r.status_code, len(r.text))
        if r.status_code != 200 or not r.text.strip():
            return ""
        if html:
            return r.text
        return html_to_md(r.text)
    except Exception as e:
        print("direct error:", e)
        return ""


def jina_reader(url, html=False):
    """Jina Reader ступенями, ключ — только в крайнем случае:
    1) до 10 анонимных попыток на исходном адресе;
    2) до 10 анонимных попыток с обходом кэша (?r=2);
    3) одна попытка с ключом из секрета JINA_API_KEY.
    401 и «подозрительно мал» HTML переводят на следующую ступень.
    Запросы с ключом помечены звёздочкой в логе."""
    h0 = {"X-Return-Format": "html" if html else "markdown",
          "X-Retain-Images": "none"}
    h1 = dict(h0)
    h1["Authorization"] = "Bearer " + JINA_KEY
    sep = "&" if "?" in url else "?"
    stages = [("исходный", h0, url, 10),
              ("обход кэша", h0, url + sep + "r=2", 10)]
    if JINA_KEY:
        stages.append(("ключ", h1, url, 1))
    for i, (label, h, u, tries) in enumerate(stages):
        with_key = h is h1
        nxt = stages[i + 1][0] if i + 1 < len(stages) else None
        for attempt in range(tries):
            try:
                r = requests.get("https://r.jina.ai/" + u,
                                 headers=h, timeout=60)
                print("jina" + ("*" if with_key else "") + ":",
                      url, "html" if html else "md",
                      "->", r.status_code, len(r.text),
                      "|", label, "| попытка", attempt + 1, "из", tries)
                if r.status_code == 200 and r.text.strip():
                    if html and not with_key and len(r.text) < 30000:
                        print("Анонимный HTML подозрительно мал"
                              + (" — следующая ступень: " + nxt
                                 if nxt else ""))
                        break
                    return r.text
                if r.status_code == 401:
                    print("Jina 401 — доступ закрыт"
                          + (", следующая ступень: " + nxt
                             if nxt else ""))
                    break
                time.sleep(10)
            except Exception as e:
                print("jina error:", e)
                time.sleep(10)
    return ""


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)


def init_path_pref():
    """Восстановить порядок путей загрузки из состояния прошлого прогона."""
    global PATH_PREF
    try:
        st = load_state()
        p = st.get("fetch_path")
        if p and set(p) == set(PATH_PREF):
            PATH_PREF = list(p)
            print("Порядок загрузки из состояния:", " -> ".join(PATH_PREF))
    except Exception:
        pass


def remember_path(name):
    """Удачный путь становится первым — следующие запросы идут с него."""
    global PATH_PREF
    if not PATH_PREF or PATH_PREF[0] == name:
        return
    PATH_PREF.remove(name)
    PATH_PREF.insert(0, name)
    print("Порядок загрузки теперь:", " -> ".join(PATH_PREF))
    try:
        st = load_state()
        st["fetch_path"] = list(PATH_PREF)
        save_state(st)
    except Exception:
        pass


def jina(url, html=False):
    """Общий загрузчик: перебираем пути в запомненном порядке —
    Worker, прокси allorigins, прокси codetabs, прямой запрос,
    Jina Reader. Имя сохранено, чтобы не править вызовы по всему файлу."""
    for name in list(PATH_PREF):
        if name == "worker":
            raw = worker_fetch(url)
            if raw:
                remember_path("worker")
                return raw if html else html_to_md(raw)
        elif name == "allorigins":
            raw = proxy_fetch(url)
            if raw:
                remember_path("allorigins")
                return raw if html else html_to_md(raw)
        elif name == "codetabs":
            raw = codetabs_fetch(url)
            if raw:
                remember_path("codetabs")
                return raw if html else html_to_md(raw)
        elif name == "direct":
            d = direct_fetch(url, html=True)
            if d:
                remember_path("direct")
                return d if html else html_to_md(d)
        elif name == "jina":
            r = jina_reader(url, html)
            if r:
                remember_path("jina")
                return r
    return ""


def jina_full_html(url):
    """Полный HTML: пути в запомненном порядке, у каждого — проверка
    на 'подозрительно мал' (защита от заглушек). Для Jina обход кэша
    и ключ уже встроены в jina_reader — здесь просто один вызов."""
    best = ""
    for name in list(PATH_PREF):
        if name == "worker":
            raw = worker_fetch(url)
        elif name == "allorigins":
            raw = proxy_fetch(url)
        elif name == "codetabs":
            raw = codetabs_fetch(url)
        elif name == "direct":
            raw = direct_fetch(url, html=True)
        else:
            raw = jina_reader(url, html=True)
        if len(raw) >= 50000:
            remember_path(name)
            return raw
        if len(raw) > len(best):
            best = raw
        print("Полный HTML мал (", len(raw),
              "байт) у пути", name, "— пробуем следующий")
    if best:
        remember_path("jina" if PATH_PREF[-1] == "jina" else PATH_PREF[0])
    return best


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


def html_text(html):
    """HTML в текст: выкидываем script/style, снимаем теги."""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html,
               flags=re.I | re.S)
    return strip_tags(s)


def tables_text():
    """Текст страницы таблиц: приоритет — полный HTML (порядок
    колонок сохраняется), маркдаун — запасной вариант:
    он может терять числовые колонки у первой таблицы."""
    html = jina_full_html(TABLES_URL)
    if len(html) >= 50000:
        return html_text(html)
    return jina(TABLES_URL) or html_text(html)


def flatten_table_md(s):
    """Чистим маркдаун таблицы: убираем картинки, ссылки, черты
    таблиц и звёздочки списков — Jina разбивает таблицы на списки,
    и цифры между | и * ломали разбор строки команды."""
    s = IMG_MD.sub(" ", s)
    s = PAT_LINK.sub(lambda m: m.group(1), s)
    s = s.replace("|", " ").replace("*", " ")
    return re.sub(r"\s+", " ", s)


def team_row(clean, name):
    """Строка таблицы: 'место Имя И В Н П МЗ - МП О'.
    Перебираем все вхождения имени — берём то, где цифры сошлись."""
    tries = [name]
    if " Казань" in name:
        tries.append(name.replace(" Казань", ""))
    last_seen = None
    for cand in tries:
        for m in re.finditer(re.escape(cand), clean):
            last_seen = m.start()
            before = clean[max(0, m.start() - 8): m.start()]
            pm = re.search(r"(\d{1,2})\s*$", before)
            place = int(pm.group(1)) if pm else None
            after = clean[m.end(): m.end() + 150]
            fm = re.match(
                r"\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})"
                r"\s+(\d{1,3})\s*-\s*(\d{1,3})\s+(\d{1,3})", after)
            if fm:
                return {"place": place,
                        "games": int(fm.group(1)),
                        "pts": int(fm.group(7)),
                        "gf": int(fm.group(5)),
                        "ga": int(fm.group(6))}
    if last_seen is not None:
        print("СТРОКА НЕ РАСПОЗНАНА (для отладки), окно вокруг имени:",
              clean[max(0, last_seen - 60): last_seen + 150])
    return None


def parse_standings(tmd, t1, t2):
    clean = flatten_table_md(tmd)
    res = {}
    for team in (t1, t2):
        row = team_row(clean, team)
        if row:
            res[team] = row
            print("Таблица:", team, "->", row)
        else:
            print("Таблица: строка не найдена для", team)
    return res


def plural(n, one, few, many):
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def standings_block(standings, t1, t2):
    if not standings:
        return ""
    our_team = t1 if OUR_KEY in t1.upper() else t2
    opp_team = t2 if our_team == t1 else t1
    our = standings.get(our_team)
    opp = standings.get(opp_team)
    if not our or not opp:
        return ""

    def ln(team, d):
        s = (esc(team) + " — <b>" + str(d["place"]) + "-е место</b>, "
             + str(d["pts"]) + " "
             + plural(d["pts"], "очко", "очка", "очков"))
        if d.get("gf") is not None:
            s += (" (" + str(d["games"]) + " "
                  + plural(d["games"], "игра", "игры", "игр")
                  + ", голы " + str(d["gf"]) + ":" + str(d["ga"]) + ")")
        else:
            s += (" (" + str(d["games"]) + " "
                  + plural(d["games"], "игра", "игры", "игр") + ")")
        return "• " + s

    return ("📊 <b>Турнирное положение</b>\n\n🔵 " + ln(our_team, our)
            + "\n⚪ " + ln(opp_team, opp))


def pin_tokens(text):
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
    """Дата/время/локация со страницы матча (шапка матч-дня).
    Шапка, рядом с которой нет ни одного имени наших команд,
    датой матча не считается (защита от чужих шапок) — как в
    основном боте."""
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
    cands = [c for c in cands if c[0] > 0]
    if not cands:
        print("Шапок с нашими командами рядом не найдено")
        return None, None, "уточняется"
    best = max(cands, key=lambda c: (c[0], c[1]))
    print("Выбранная шапка:", best[2], best[3])
    return best[2], best[3], find_location(texts, date_positions)


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


LINEUP_STOP = ("распечатать протокол", "турнирная таблица",
               "о турнире", "календарь")


def parse_lineups(md):
    idx = md.upper().find("СТАРТОВЫЕ СОСТАВЫ")
    if idx < 0:
        return None
    sections = []
    cur = None
    for raw in md[idx: idx + 8000].splitlines():
        line = IMG_MD.sub(" ", raw)
        low = line.lower()
        if any(k in low for k in LINEUP_STOP):
            break
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
        print("Составы из", label, ":", [s[0] for s in secs][:8], "...")
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
        # Убираем картинки: в лайв-протоколе имена идут простым текстом
        clean = IMG_MD.sub(" ", s)
        players = [c.strip() for c in find_brackets(clean)
                   if NAME_RE.fullmatch(c.strip())]
        if not players:
            # Лайв-формат: пары Имя Фамилия простым текстом после времени
            players = [p.group(0) for p in NAME_RE.finditer(clean[m.end():])]
        low = s.lower()
        scoring = None
        ms = SCORE_END.search(s)
        if not ms:
            # В лайве счёт может быть не в конце строки — ищем в любом месте
            for ms in re.finditer(r"(\d{1,2})\s*:\s*(\d{1,2})", clean):
                pass
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
        elif len(players) == 2:
            et = "subst"  # две фамилии без счёта — вероятная замена
        elif len(players) == 1:
            # Одна фамилия без счёта: возможно, карточка — решит HTML
            et = "card"
        else:
            et = "unknown"
            print("НЕОПОЗНАННОЕ СОБЫТИЕ (для отладки):", s[:500])
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
            if e["et"] in ("unknown", "subst"):
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
                    "⚽ <b>" + p + " ЗАБИВАЕТ!</b> 🌟\n" + pas
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


def announcement(opponent, mdate, time_str, loc, standings_text=""):
    ds = "уточняется"
    if mdate:
        y, mo, d = mdate
        ds = str(d) + " " + MONTHS_RU[mo - 1] + ", "
        ds += WEEKDAYS_RU[datetime(y, mo, d).weekday()]
    body = ("🔴 <b>FC ITPROVIDER — ДЕНЬ МАТЧА</b> 🔴\n\n"
            "🆚 Соперник: «" + esc(opponent) + "»\n"
            "🗓 Дата: " + ds + "\n"
            "⏱ Старт: " + time_str + " (МСК)\n"
            "🗺 Локация: " + esc(loc) + "\n\n"
            "🔗 Трансляция: " + esc(STREAM_URL) + "\n\n"
            "Следите за обновлениями в этом чате.")
    if standings_text:
        body += "\n\n" + standings_text
    return body


def hour_reminder(opponent, time_str, loc):
    return ("⏰ <b>Через час — ИГРА!</b>\n\n"
            "🆚 Соперник: <b>«" + esc(opponent) + "»</b>\n\n"
            "⏱ Начало в <b>" + time_str + "</b> (МСК)\n\n"
            "📍 <b>" + esc(loc) + "</b>")


def main():
    global OUR_IS_HOME, LOCATION
    print("ВЕРСИЯ КОДА:", VERSION)
    print("Telegram API через:", TG_API.rstrip("/"))
    print("Ключ Jina:", "задан (страховой режим активен)"
          if JINA_KEY else "не задан — только анонимный Jina")
    if os.environ.get("REPLAY_RESET") in ("yes", "true", "1"):
        try:
            os.remove(STATE_FILE)
            print("Состояние реплея сброшено")
        except Exception:
            pass
    init_path_pref()
    st = load_state()
    if st.get("done"):
        print("Реплей уже был отыгран. Для повторного прогона "
              "запусти с параметром reset=yes")
        return
    old = st
    st = {"seen": []}
    if old.get("fetch_path"):
        st["fetch_path"] = old["fetch_path"]

    md = jina(MATCH_URL)
    if not md:
        print("Страница матча не скачалась")
        return
    html = jina_full_html(MATCH_URL)

    proto = jina(MATCH_URL + "?active=protocol")
    t1, t2 = parse_teams(md)
    OUR_IS_HOME = OUR_KEY in t1.upper()
    print("Команды:", t1, "vs", t2, "| Мы хозяева:", OUR_IS_HOME)

    mdate, mtime, LOCATION = extract_match_info(md, html, t1, t2)
    time_str = "уточняется"
    if mtime:
        time_str = format(mtime[0], "02d") + ":" + format(mtime[1], "02d")
    print("Шапка: дата", mdate, "| время", time_str,
          "| локация", LOCATION)

    opponent = t2 if OUR_IS_HOME else t1

    print("=== 1/7 Анонс ===")
    standings_text = ""
    try:
        tmd = tables_text()
        if tmd:
            standings = parse_standings(tmd, t1, t2)
            standings_text = standings_block(standings, t1, t2)
    except Exception:
        print("Ошибка блока таблиц (продолжаем):")
        print(traceback.format_exc())
    send(announcement(opponent, mdate, time_str, LOCATION, standings_text))
    time.sleep(PAUSE)

    print("=== 2/7 Напоминание за час ===")
    send(hour_reminder(opponent, time_str, LOCATION))
    time.sleep(PAUSE)

    print("=== 3/7 Состав ===")
    lineup = our_lineup(md, proto)
    if lineup:
        print("Найдено игроков:", len(lineup))
        send_lineup(lineup)
    else:
        print("Состав не найден — пост пропускаем")
    time.sleep(PAUSE)

    print("=== 4/7 Трансляция ===")
    try:
        surl = get_stream(MATCH_URL, md)
        if surl:
            send("📺 <b>А вот и ссылка на игру!</b>\n\n" + surl)
        else:
            print("Ссылка не найдена — пост пропускаем")
    except Exception:
        print("Ошибка блока трансляции (продолжаем):")
        print(traceback.format_exc())
    time.sleep(PAUSE)

    print("=== 5/7 МАТЧ НАЧАЛСЯ ===")
    send("🏟️ <b>МАТЧ НАЧАЛСЯ!</b> 🏟️\n\n🆚 <b>" + t1 + " vs " + t2
         + "</b>\n\nДержим кулаки за команду! 👊")
    time.sleep(PAUSE)

    print("=== 6/7 События ===")
    our_names = set(n for _, n, _ in lineup) if lineup else set()
    if not our_names:
        print("ВНИМАНИЕ: состав пуст — карточки могут "
              "неверно определить «наши/соперник»")
    events = []
    for e in merge_events(md, proto):
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
        eid = str(ev["minute"]) + "-" + ev["et"] + "-" + ev["player"]
        if eid in st["seen"]:
            continue
        events.append(ev)
        st["seen"].append(eid)
    for ev in events:
        post = render_post(ev)
        if post:
            print("ПОСТ:", str(ev["minute"]) + "'", ev["et"])
            send(post)
            time.sleep(PAUSE)
    if events:
        st["score"] = events[-1]["score"]

    print("=== 7/7 Итог ===")
    sc = st.get("score", [0, 0])
    our, opp = (sc[0], sc[1]) if OUR_IS_HOME else (sc[1], sc[0])
    if our > opp:
        verdict = "🎉 <b>ПОБЕДА!</b> 🎉"
    elif our < opp:
        verdict = "😔 <b>ПОРАЖЕНИЕ</b> 😔"
    else:
        verdict = "🤝 <b>НИЧЬЯ</b> 🤝"
    send("🏁 <b>МАТЧ ЗАВЕРШЁН!</b> 🏁\n\n📊 Итоговый счёт: <b>"
         + str(sc[0]) + " : " + str(sc[1]) + "</b>\n\n" + verdict
         + "\n\nСпасибо за игру, команду! 🤝")

    st["done"] = True
    st["fetch_path"] = list(PATH_PREF)
    save_state(st)
    print("РЕПЛЕЙ ЗАВЕРШЁН. Всего событий запостено:", len(events))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
        try:
            send("🚨 Ошибка реплея:\n<pre>"
                 + esc(traceback.format_exc()[-2500:]) + "</pre>")
        except Exception:
            print("Не удалось отправить отчёт об ошибке")
        raise
