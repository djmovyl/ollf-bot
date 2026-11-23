import os, re, time, json, requests, traceback
from datetime import datetime, timedelta, timezone

VERSION = "bot-2.36 (24.11.2026)"

TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL = os.environ.get("CHANNEL", "")
# Адрес Telegram API: через Cloudflare Worker, если задан TG_API_URL
TG_API = os.environ.get("TG_API_URL", "https://api.telegram.org")
# Секрет прокси из воркера (заголовок x-proxy-secret)
TG_PROXY_SECRET = os.environ.get("TG_PROXY_SECRET", "")
# Ключ Jina Reader: страховой режим. Анонимный доступ пробуем первым,
# с ключом — только когда обе анонимные ступени не взяли
JINA_KEY = os.environ.get("JINA_API_KEY", "")
CALENDAR_URL = "https://ollf.ru/tournament/1067343/calendar"
TABLES_URL = "https://ollf.ru/tournament/1067343/tables"
OUR_KEY = "ITPROVIDER"
# PAST_MATCH = True  -> тестовый режим: разбор MATCH_URL, только лог
# PAST_MATCH = False -> боевой режим: календарь + реальный канал
PAST_MATCH = True
MATCH_URL = "https://ollf.ru/match/5905514"
START_H, START_M = 18, 0
DURATION_MIN = 75
# Окно состава растянуто до 20 минут до старта — при редких прогонах
# планировщика не проскочим мимо
LINEUP_CHECK_BEFORE = 20
VK_TRANSLATION = "https://vkvideo.ru/@club154907309/all"
# Ссылка на трансляцию: берём из секрета STREAM_URL, если задан,
# иначе — запасная ссылка на канал VK
STREAM_URL = os.environ.get("STREAM_URL", VK_TRANSLATION)
STATE_FILE = "prod_state.json"

# Речевой слой: постген с клише, милстоунами и сезонной статистикой.
# Если файла нет рядом с ботом — работаем в старом формате постов.
try:
    import postgen as pg
except ImportError:
    pg = None
    print("postgen.py не найден — посты пойдут старым форматом")

# Поля сезонной статистики: переживают ежедневный сброс состояния
STATS_KEYS = ("season_stats", "stats_synced_at", "stats_synced_match_urls")

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
# Автогол: проверяется первым — строка содержит счёт, и без своей
# ветки она уходила бы в обычный гол
WORD_AUTOGOAL = "автогол"

JUNK = ("кубок", "чемпионат", "лига", "турнир", "календарь", "группа",
        "сезон", "тур ", "оллф", "статистика", "таблица", "протокол",
        "события")
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

# Шапка матч-дня: '15 ноября / воскресенье / 20:00'.
# Разделитель нежадный и без двоеточия — не съедает цифру из времени
DT_LINE = re.compile(
    r"(\d{1,2})\s+(" + MONTH_RE + r")[^:\n]{0,30}?(\d{1,2}):(\d{2})",
    re.I)
# Числовой фолбэк: '22.11.2026' и рядом '18:00'
NUM_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b")
TIME_ONLY = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
# Площадка в контексте календаря: 'Манеж Физра', 'Стадион Тасма'
VENUE_CTX = re.compile(
    "(Манеж|Стадион|Арена|Спорткомплекс|ФОК)" + S + "+"
    + "[A-ZА-ЯЁA-Za-z0-9][^" + S + "|,;]*")

OUR_IS_HOME = True
LOCATION = "уточняется"
TIME_STR = "уточняется"

# Порядок путей загрузки страниц: перебираем по очереди, удачный путь
# запоминаем в состоянии — следующий прогон начнёт с него
PATH_PREF = ["worker", "allorigins", "codetabs", "direct", "jina"]


def stream_link():
    """Кликабельная строка 'Ссылка на трансляцию' или пустая строка,
    если ссылка не задана."""
    if not STREAM_URL:
        return ""
    return "📺 <a href=\"" + esc(STREAM_URL) + "\">Ссылка на трансляцию</a>"


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
    if PAST_MATCH:
        print("[ТЕСТ] Сообщение НЕ отправлено в канал:")
        print(text.replace("<b>", "").replace("</b>", ""))
        return
    res = tg("sendMessage", chat_id=CHANNEL, text=text[:3900],
             parse_mode="HTML")
    if not res.get("ok"):
        print("Telegram error:", res)


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


def jina(url, html=False, must_contain=None):
    """Общий загрузчик: перебираем пути в запомненном порядке —
    Worker, прокси allorigins, прокси codetabs, прямой запрос,
    Jina Reader. Имя сохранено, чтобы не править вызовы по всему файлу.

    must_contain — маркер настоящей страницы: если его в контенте нет,
    это заглушка анти-бота (прокси отдают её со статусом 200). Такой
    ответ отбрасываем, путь заглушки удачным не считаем."""
    for name in list(PATH_PREF):
        if name == "worker":
            raw = worker_fetch(url)
        elif name == "allorigins":
            raw = proxy_fetch(url)
        elif name == "codetabs":
            raw = codetabs_fetch(url)
        elif name == "direct":
            raw = direct_fetch(url, html=True)
        elif name == "jina":
            raw = jina_reader(url, html)
        else:
            raw = None
        if not raw:
            continue
        md = raw if (name == "jina" or html) else html_to_md(raw)
        if must_contain and must_contain.lower() not in md.lower():
            print(name + ": в контенте нет маркера '" + must_contain
                  + "' — похоже на заглушку анти-бота, идём дальше")
            continue
        remember_path(name)
        return raw if (name == "jina" or html) else md
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
    """Все значки 📍 в тексте: [(позиция, название площадки)].
    Собираем до 3 слов подряд — получаем полное 'Манеж Физра',
    а не обрубок 'Манеж'. Ведущие слова-города отбрасываем."""
    out = []
    i = text.find("📍")
    while i >= 0:
        toks = []
        for w in text[i + 1:].split():
            t = w.strip(".,;:!?()[]|/«»\"'")
            if t.isalpha():
                toks.append(t)
            elif toks:
                break
        toks = toks[:3]
        while toks and toks[0].lower() in CITY_WORDS:
            toks.pop(0)
        if toks:
            out.append((i, " ".join(toks)))
        i = text.find("📍", i + 1)
    return out


def find_location(texts, date_positions, quiet=False):
    """Локация: среди всех 📍 берём ближайшую к дате матча площадку —
    с полным названием. Затем fallback по регэкспу площадки
    в строках текста."""
    best = None
    for text, dpos in zip(texts, date_positions):
        if not text or not dpos:
            continue
        for p, tok in pin_tokens(text):
            dist = min(abs(p - d) for d in dpos)
            if not quiet:
                print("📍 кандидат:", tok, "| дистанция до даты:", dist)
            if best is None or dist < best[0]:
                best = (dist, tok)
    if best and best[0] <= 3000:
        return best[1]
    for text in texts:
        if not text:
            continue
        for line in text.splitlines():
            m = VENUE_CTX.search(line)
            if m:
                return m.group(0).strip()
    return "уточняется"


def extract_match_info(md, html, t1, t2, quiet=False):
    """Дата/время/локация со страницы матча (шапка матч-дня).
    Шапка, рядом с которой нет ни одного имени наших команд,
    датой матча не считается (защита от чужих шапок).
    Для кандидатов с нулевыми очками печатаем окно — сразу видно,
    почему наши имена рядом не нашлись (quiet отключает печать)."""
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
                if score:
                    cands.append((score, -m.start(), cd, ct))
                    print("Кандидат даты:", m.group(0), "| очки:", score)
                else:
                    print("Кандидат даты (очки 0):", m.group(0),
                          "| окно:", win[:150].replace("\n", " "))
        date_positions.append(positions)
    cands = [c for c in cands if c[0] > 0]
    if not cands:
        if not quiet:
            print("Шапок с нашими командами рядом не найдено")
        return None, None, find_location(texts, date_positions, quiet)
    best = max(cands, key=lambda c: (c[0], c[1]))
    if not quiet:
        print("Выбранная шапка:", best[2], best[3])
    return best[2], best[3], find_location(texts, date_positions, quiet)


def page_datetime(md, html, t1, t2):
    """Числовой фолбэк: '22.11.2026' и рядом '18:00' —
    для страницы предстоящего матча, где шапки матч-дня ещё нет."""
    texts = [md] + ([strip_tags(html)] if html else [])
    for text in texts:
        if not text:
            continue
        for m in NUM_DATE.finditer(text):
            win = text[max(0, m.start() - 400): m.end() + 500]
            if not any(p in win for p in t1.split()) \
                    and not any(p in win for p in t2.split()):
                continue
            tm = TIME_ONLY.search(win)
            if not tm:
                continue
            d, mo = int(m.group(1)), int(m.group(2))
            y = int(m.group(3)) if m.group(3) else datetime.now(MSK).year
            print("Числовой кандидат на странице:",
                  m.group(0), tm.group(0))
            return (y, mo, d), (int(tm.group(1)), int(tm.group(2)))
    return None, None


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


# Маркеры конца зоны составов — за ними идёт футер/боковая панель
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
        if WORD_AUTOGOAL in low:
            et = "autogoal"
        elif any(w in low for w in CARD_RED):
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


def final_score_from_page(md):
    """Фолбэк итогового счёта из шапки страницы матча (зона до
    'События матча'). Берём последний правдоподобный счёт: каждая
    цифра не больше 15, чтобы не принять за счёт время '20:00'."""
    if not md:
        return None
    idx = md.find("События матча")
    zone = md[:idx] if idx > 0 else md
    best = None
    for m in re.finditer(r"(\d{1,2})\s*:\s*(\d{1,2})", zone):
        a, b = int(m.group(1)), int(m.group(2))
        if a <= 15 and b <= 15:
            best = [a, b]
    if best:
        print("Счёт из шапки страницы:", best[0], ":", best[1])
    return best


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
    if ev["et"] == "autogoal":
        cur = ev["score"]
        our, opp = (cur[0], cur[1]) if OUR_IS_HOME else (cur[1], cur[0])
        if ev["ours"]:
            return ("⚽ <b>Автогол — в нашу пользу!</b>\n\n"
                    "На " + str(m) + "' минуте счёт: <b>"
                    + str(our) + ":" + str(opp) + "</b>")
        return ("🥅 <b>Автогол в наши ворота</b>\n\n"
                "На " + str(m) + "' минуте счёт: <b>"
                + str(our) + ":" + str(opp) + "</b>")
    return None


def build_events(md, html, proto, lineup):
    """Сборка событий матча: тип, минута, счёт, наши/соперник.
    Для голов и автоголов направление определяется по счёту протокола,
    для автогола ours = «гол в нашу пользу»."""
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
        if ev["et"] in ("goal", "autogoal") and e["scoring"]:
            ev["ours"] = OUR_IS_HOME == (e["scoring"] == "home")
        else:
            ev["ours"] = any(p in our_names for p in e["players"])
        events.append(ev)
    return events


def post_events(events, st, match_url, do_send=True):
    """Публикация событий: голы, автоголы и карточки — через postgen,
    при сбое — откат в старый формат render_post. Здесь же копится
    статистика матча: вход для сезонных цифр и милстоунов. Автоголы
    в статистику не идут."""
    counts = {}
    prev_our, prev_opp = 0, 0
    prev_goal, prev_goal_min, we_led = None, None, False
    for ev in events:
        # Счётчики матча обновляем ДО поста: сезонная цифра в посте
        # должна включать и текущий гол/пас
        if ev["et"] == "goal" and ev["ours"]:
            c = counts.setdefault(ev["player"],
                                  {"goals": 0, "assists": 0, "yellow": 0})
            c["goals"] += 1
            if ev.get("assist"):
                counts.setdefault(ev["assist"],
                                  {"goals": 0, "assists": 0,
                                   "yellow": 0})["assists"] += 1
        if ev["et"] == "yellow":
            counts.setdefault(ev["player"],
                              {"goals": 0, "assists": 0,
                               "yellow": 0})["yellow"] += 1
        eid = str(ev["minute"]) + "-" + ev["et"] + "-" + ev["player"]
        if eid not in st["seen"]:
            post = None
            try:
                if pg is None:
                    raise RuntimeError("postgen недоступен")
                if ev["et"] == "goal":
                    cur = ev["score"]
                    our, opp = ((cur[0], cur[1]) if OUR_IS_HOME
                                else (cur[1], cur[0]))
                    post = pg.build_goal_post(
                        st, scored=ev["ours"], scorer=ev["player"],
                        assister=ev.get("assist"), minute=ev["minute"],
                        our=our, opp=opp,
                        prev_our=prev_our, prev_opp=prev_opp,
                        prev_goal=prev_goal, we_led_before=we_led,
                        minutes_since=(ev["minute"] - prev_goal_min)
                        if prev_goal_min is not None else None,
                        scorer_match_goals=counts.get(ev["player"], {})
                        .get("goals", 0),
                        assister_match_assists=(
                            counts.get(ev["assist"], {})
                            .get("assists", 0) if ev.get("assist") else 0),
                        match_url=match_url)
                elif ev["et"] == "autogoal":
                    cur = ev["score"]
                    our, opp = ((cur[0], cur[1]) if OUR_IS_HOME
                                else (cur[1], cur[0]))
                    post = pg.build_autogoal_post(st, ev["ours"],
                                                  ev["minute"], our, opp)
                elif ev["et"] in ("yellow", "red"):
                    post = pg.build_card_post(
                        st, ev["et"], ev["ours"], ev["player"],
                        ev["minute"],
                        yellow_before=counts.get(ev["player"], {})
                        .get("yellow", 0))
            except Exception:
                print("Постген не сработал — fallback в старый формат:")
                print(traceback.format_exc())
                post = render_post(ev)
            if post:
                if do_send:
                    time.sleep(2)
                    send(post)
                else:
                    print("---- ПОСТ ----")
                    print(post.replace("<b>", "").replace("</b>", ""))
            st["seen"].append(eid)
        # Контекст для классификатора — после поста
        if ev["et"] in ("goal", "autogoal"):
            cur = ev["score"]
            o, p = (cur[0], cur[1]) if OUR_IS_HOME else (cur[1], cur[0])
            if o > p:
                we_led = True
            prev_our, prev_opp = o, p
            prev_goal = "scored" if ev["ours"] else "conceded"
            prev_goal_min = ev["minute"]


def sync_stats_safe(st, force=False, match_url=""):
    """Синк сезонной статистики со страницы заявки. Сбой не роняет
    бот — посты просто выйдут без сезонных цифр."""
    if pg is None:
        return
    try:
        pg.sync_season_stats(st, fetch=jina, force=force,
                             match_url=match_url)
    except Exception:
        print("Синк статистики не удался (продолжаем):")
        print(traceback.format_exc())


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
    """Ищем наш матч в календаре. Время и площадка — в соседних ячейках,
    дата — в ближайшем заголовке секции выше строки матча."""
    cands = []
    lines = cal_md.splitlines()
    for i, raw in enumerate(lines):
        s = raw.strip()
        if OUR_KEY not in s or "ollf.ru/match/" not in s:
            continue
        m = re.search(r"match/(\d+)", s)
        if not m:
            continue
        near = [x.strip() for x in lines[max(0, i - 2): i + 3]
                if x.strip()]
        wide = [x.strip() for x in lines[max(0, i - 4): i + 5]
                if x.strip()]
        ctx = " | ".join(near)
        dctx = " | ".join(wide)
        tm = re.search(r"\b(\d{1,2}):(\d{2})\b", ctx)
        vm = VENUE_CTX.search(dctx)
        date = None
        for j in range(i, max(-1, i - 16), -1):
            date = line_date(lines[j].strip(), today)
            if date:
                break
        cands.append({"url": "https://ollf.ru/match/" + m.group(1),
                      "line": s, "context": ctx,
                      "date": date,
                      "time": (int(tm.group(1)), int(tm.group(2)))
                              if tm else None,
                      "venue": vm.group(0).strip() if vm else None,
                      "upcoming": "- : -" in ctx})
    if not cands:
        return "", None, None, None
    tk = (today.year, today.month, today.day)
    pool = ([c for c in cands if c["date"] == tk]
            or [c for c in cands if c["date"] is None])
    if not pool:
        return "", None, None, None
    pick = ([c for c in pool if c["upcoming"]] or pool)[0]
    print("Строка календаря:", pick["line"][:300])
    print("Контекст строки:", pick["context"][:400])
    print("Дата из календаря:", pick["date"],
          "| время:", pick["time"], "| площадка:", pick["venue"])
    return (pick["url"], pick["date"], pick["time"], pick["venue"])


def announcement(opponent, mdate, time_str, loc, standings_text=""):
    ds = "уточняется"
    if mdate:
        y, mo, d = mdate
        ds = str(d) + " " + MONTHS_RU[mo - 1] + ", "
        ds += WEEKDAYS_RU[datetime(y, mo, d).weekday()]
    body = ("🔥⚽️ <b>FC ITPROVIDER — ДЕНЬ МАТЧА!</b> 🔥⚽️\n\n"
            "🆚 Соперник: «" + esc(opponent) + "»\n"
            "🗓 Дата: " + ds + "\n"
            "⏱ Старт: " + time_str + " (МСК)\n"
            "🗺 Локация: " + esc(loc))
    if standings_text:
        body += "\n\n" + standings_text
    if STREAM_URL:
        body += "\n\n" + stream_link()
    return body + "\n\nСледите за обновлениями в нашей группе!"


def hour_reminder(time_str, loc):
    if loc and loc != "уточняется":
        loc_line = "📍 <b>" + esc(loc).upper() + "</b>"
    else:
        loc_line = ("📍 <b>Локация уточняется</b> — гляньте в календаре "
                    "турнира: " + esc(CALENDAR_URL))
    return ("⏰ <b>ИГРА УЖЕ СКОРО!</b>\n\n"
            "⏱ Начало в <b>" + time_str + "</b> (МСК)\n\n" + loc_line)


def test_mode():
    """Тестовый прогон на сыгранном матче: только лог."""
    global OUR_IS_HOME
    init_path_pref()
    md = jina(MATCH_URL, must_contain="teams/application")
    if not md:
        print("Страница матча не скачалась")
        return
    html = jina_full_html(MATCH_URL)
    t1, t2 = parse_teams(md)
    print("Команды:", t1, "vs", t2)
    OUR_IS_HOME = OUR_KEY in t1.upper()
    try:
        mdate, mtime, loc = extract_match_info(md, html, t1, t2)
        print("Шапка матча: дата", mdate, "| время", mtime,
              "| локация", loc)
    except Exception:
        print("Ошибка разбора шапки (продолжаем):")
        print(traceback.format_exc())
    tmd = tables_text()
    if tmd:
        parse_standings(tmd, t1, t2)
    proto = jina(MATCH_URL + "?active=protocol")
    lineup = our_lineup(md, proto)
    if lineup:
        print("ТЕСТ СОСТАВ — найдено", len(lineup), "игроков")
    else:
        print("ТЕСТ СОСТАВ — не найден")
    events = build_events(md, html, proto, lineup)
    for e in events:
        info = e["player"]
        if e.get("assist"):
            info += " (пас: " + e["assist"] + ")"
        print("СОБЫТИЕ:", e["et"], str(e["minute"]) + "'",
              info, e["score"], "| наши:", e["ours"])
    fs = final_score_from_page(md)
    print("Фолбэк счёта из шапки:", fs)
    if pg is not None:
        st = {"seen": [], "last_tpl": None, "last_closer": None,
              "season_stats": {}, "stats_synced_match_urls": []}
        sync_stats_safe(st, match_url=MATCH_URL)
        post_events(events, st, MATCH_URL, do_send=False)
    else:
        print("postgen.py не найден — посты не собраны")


def main():
    global OUR_IS_HOME, START_H, START_M, TIME_STR
    print("ВЕРСИЯ КОДА:", VERSION)
    print("Режим:", "ТЕСТ (только лог)" if PAST_MATCH else "БОЕВОЙ")
    print("Telegram API через:", TG_API.rstrip("/")
          if TG_API.rstrip("/") != "https://api.telegram.org"
          else "напрямую (TG_API_URL не задан!)")
    print("Ключ Jina:", "задан (страховой режим активен)"
          if JINA_KEY else "не задан — только анонимный Jina")
    init_path_pref()
    now = datetime.now(MSK)
    if PAST_MATCH:
        test_mode()
        return
    tk = now.strftime("%Y-%m-%d")
    # Календарь качаем один раз в день: найденный матч и «пустой день»
    # запоминаем в состоянии, чтобы не жечь запросы на каждом прогоне.
    # Маркер OUR_KEY: заглушка анти-бота, протащенная прокси со статусом
    # 200, не считается скачанным календарём — повторим через 5 минут
    st0 = load_state()
    match_url = ""
    mdate = mtime = cal_venue = None
    if st0.get("match_url") and st0.get("match_url_date") == tk:
        match_url = st0["match_url"]
        md0 = st0.get("match_mdate") or []
        mdate = (int(md0[0]), int(md0[1]), int(md0[2])) \
            if len(md0) == 3 else None
        mt = st0.get("match_time") or []
        mtime = (int(mt[0]), int(mt[1])) if len(mt) == 2 else None
        cal_venue = st0.get("match_venue")
        print("Матч уже найден в состоянии:", match_url)
    elif st0.get("no_match_date") == tk:
        print("Матч на сегодня не найден ранее (кэш) — выходим")
        return
    else:
        cal = jina(CALENDAR_URL, must_contain=OUR_KEY)
        if not cal:
            print("Календарь не скачался — выходим, повтор через 5 минут")
            return
        match_url, mdate, mtime, cal_venue = find_our_match(cal, now.date())
        if not match_url:
            st0["no_match_date"] = tk
            save_state(st0)
            print("Наш матч на сегодня не найден — выходим")
            return
        if mdate and mdate != (now.year, now.month, now.day):
            st0["no_match_date"] = tk
            save_state(st0)
            print("Наш матч не сегодня:", mdate, "— выходим")
            return
        st0["match_url"] = match_url
        st0["match_url_date"] = tk
        if mdate:
            st0["match_mdate"] = list(mdate)
        if mtime:
            st0["match_time"] = list(mtime)
        if cal_venue:
            st0["match_venue"] = cal_venue
        save_state(st0)
    # Страница матча: до двух попыток — источник иногда отдаёт
    # урезанную версию без шапки, тогда дата не распознаётся.
    # Полный HTML на этом этапе НЕ качаем: он нужен только для
    # карточек и уточнения локации, а без подтверждённой даты бот
    # всё равно выйдет. Экономим попытки и ключ Jina.
    # Маркер 'teams/application': без него имена команд всё равно
    # не извлечь, так что такой ответ бесполезен.
    t1 = t2 = None
    md = html = ""
    page_date = page_time = None
    page_loc = "уточняется"
    for attempt in range(2):
        md = jina(match_url, must_contain="teams/application")
        if not md:
            print("Страница матча не скачалась")
            continue
        t1, t2 = parse_teams(md)
        if OUR_KEY not in t1.upper() and OUR_KEY not in t2.upper():
            print("Это не наш матч:", t1, t2)
            return
        OUR_IS_HOME = OUR_KEY in t1.upper()
        print("Команды:", t1, "vs", t2, "| Мы хозяева:", OUR_IS_HOME)
        try:
            page_date, page_time, page_loc = extract_match_info(md, "",
                                                                t1, t2)
        except Exception:
            page_loc = "уточняется"
            print("Ошибка разбора шапки (продолжаем):")
            print(traceback.format_exc())
        if page_time is None:
            try:
                n_date, n_time = page_datetime(md, "", t1, t2)
                if n_time:
                    page_time = n_time
                    page_date = page_date or n_date
            except Exception:
                print("Ошибка числового фолбэка (продолжаем):")
                print(traceback.format_exc())
        if page_date:
            break
        print("Шапка не распознана, попытка", attempt + 1, "из 2")
        time.sleep(5)
    if not md or not t1:
        print("Не удалось получить страницу матча — выходим")
        return
    # Дату должны знать точно: без неё — ни анонса, ни постов
    eff_date = mdate or page_date
    if eff_date is None:
        print("Дату матча определить не удалось — выходим без постов")
        return
    if eff_date != (now.year, now.month, now.day):
        print("Наш матч не сегодня:", eff_date, "— выходим")
        return

    # Дата подтверждена как «сегодня»: теперь качаем полный HTML —
    # он нужен для карточек и уточнения локации
    html = jina_full_html(match_url)
    if html:
        try:
            h_date, h_time, h_loc = extract_match_info(
                md, html, t1, t2, quiet=True)
            if h_time and page_time is None:
                page_time = h_time
                page_date = page_date or h_date
            if h_loc and h_loc != "уточняется":
                page_loc = h_loc
        except Exception:
            print("Ошибка повторного разбора шапки (продолжаем):")
            print(traceback.format_exc())

    # Локация: сначала из календаря ('Манеж Физра'),
    # потом со страницы матча
    LOCATION = cal_venue or page_loc
    if mtime:
        START_H, START_M = mtime
        TIME_STR = format(START_H, "02d") + ":" + format(START_M, "02d")
    elif page_time:
        START_H, START_M = page_time
        TIME_STR = format(START_H, "02d") + ":" + format(START_M, "02d")
    else:
        TIME_STR = "уточняется"
    print("Старт матча:", TIME_STR, "| Локация:", LOCATION)

    proto = jina(match_url + "?active=protocol")
    lineup = our_lineup(md, proto)

    st = load_state()
    if st.get("match_date") != tk:
        # Ежедневный сброс: сезонную статистику сохраняем
        old = {k: st[k] for k in STATS_KEYS if k in st}
        st = {"seen": [], "started": False, "final": False,
              "score": [0, 0], "match_date": tk}
        st.update(old)
        save_state(st)
    st.setdefault("seen", [])
    st.setdefault("started", False)
    st.setdefault("final", False)
    st.setdefault("score", [0, 0])
    st["match_url"] = match_url
    st["match_url_date"] = tk
    if mtime:
        st["match_time"] = list(mtime)
    if cal_venue:
        st["match_venue"] = cal_venue
    save_state(st)

    # Синк сезонной статистики: раз в сутки, со страницы заявки
    sync_stats_safe(st, match_url=match_url)

    if st.get("final"):
        print("Матч уже закрыт в состоянии — выходим")
        return

    # Окна. Если время матча известно: анонс — с 11:00 (для утренних
    # матчей — от T-20), состав — с T-20, старт и итог — по шапке.
    # Если время неизвестно: анонс и состав — с 11:00 до конца дня,
    # «МАТЧ НАЧАЛСЯ» — по первому событию, итог — не раньше, чем через
    # 85 минут после первого события (защита от преждевременного
    # «МАТЧ ЗАВЕРШЁН»).
    end_of_day = now.replace(hour=23, minute=59, second=0,
                             microsecond=0)
    if TIME_STR != "уточняется":
        t0 = now.replace(hour=START_H, minute=START_M,
                         second=0, microsecond=0)
        tend = t0 + timedelta(minutes=DURATION_MIN)
        win_start = t0 - timedelta(minutes=LINEUP_CHECK_BEFORE)
        time_known = True
        ann_from = min(now.replace(hour=11, minute=0, second=0,
                                   microsecond=0), win_start)
        ann_until = tend
    else:
        t0 = now.replace(hour=18, minute=0, second=0, microsecond=0)
        tend = t0 + timedelta(minutes=DURATION_MIN)
        win_start = now.replace(hour=11, minute=0, second=0,
                                microsecond=0)
        time_known = False
        ann_from = win_start
        ann_until = end_of_day
    win = win_start <= now < ann_until

    if now < ann_until and now >= ann_from and st.get("announced") != tk:
        standings_text = ""
        try:
            tmd = tables_text()
            if tmd:
                standings = parse_standings(tmd, t1, t2)
                standings_text = standings_block(standings, t1, t2)
        except Exception:
            print("Ошибка блока таблиц (продолжаем):")
            print(traceback.format_exc())
        post = announcement(t2 if OUR_IS_HOME else t1,
                            eff_date, TIME_STR, LOCATION, standings_text)
        print("---- АНОНС ----")
        print(post.replace("<b>", "").replace("</b>", ""))
        send(post)
        st["announced"] = tk
        save_state(st)
    # Напоминание за час: уходит в первый прогон от старта до T-62,5 —
    # работает даже при редких прогонах планировщика. Если локация ещё
    # не распозналась — откладываем до следующего прогона; последний
    # шанс (за 51 минуту и позже) — шлём с пометкой «уточняется».
    if time_known and st.get("hour1") != tk:
        dt_min = (t0 - now).total_seconds() / 60
        if 0 < dt_min <= 62.5 and LOCATION != "уточняется":
            post = hour_reminder(TIME_STR, LOCATION)
            print("---- НАПОМИНАНИЕ ЗА ЧАС ----")
            print(post.replace("<b>", "").replace("</b>", ""))
            send(post)
            st["hour1"] = tk
            save_state(st)
        elif LOCATION == "уточняется" and 0 < dt_min <= 62.5:
            print("Напоминание за час отложено: локация не распознана,"
                  " до старта", format(dt_min, ".1f"), "минут")
            if dt_min <= 51:
                post = hour_reminder(TIME_STR, "уточняется")
                print("---- НАПОМИНАНИЕ ЗА ЧАС (локация не найдена) ----")
                print(post.replace("<b>", "").replace("</b>", ""))
                send(post)
                st["hour1"] = tk
                save_state(st)
    if win and st.get("lineup") != tk and lineup:
        send_lineup(lineup)
        st["lineup"] = tk
        save_state(st)

    # Сборка событий: тип, минута, счёт, наши/соперник
    events = build_events(md, html, proto, lineup)

    # «МАТЧ НАЧАЛСЯ»: при известном времени — ровно в старт матча
    # по шапке (окно t0..tend), даже если событий в протоколе ещё нет.
    # Если время неизвестно — по первому событию, как раньше.
    start_ok = (t0 <= now < tend) if time_known else bool(events)
    if start_ok and st.get("started") != tk:
        st["started"] = tk
        if events and not st.get("first_ts"):
            st["first_ts"] = time.time()
        save_state(st)
        send("🏟️ <b>МАТЧ НАЧАЛСЯ!</b> 🏟️\n\n🆚 <b>" + esc(t1) + " vs "
             + esc(t2) + "</b>\n\nДержим кулаки за команду! 👊")

    # Публикация: постген с фолбэком в старый формат
    post_events(events, st, match_url)
    if events:
        st["score"] = events[-1]["score"]
    save_state(st)

    # Итог: если время известно — после старта+75 минут;
    # если нет — не раньше, чем через 85 минут после первого события.
    # Счёт: из событий, а если событий не было — фолбэк из шапки
    # страницы матча (защита от ложного '0:0').
    if st.get("started") and not st.get("final"):
        if time_known:
            final_ok = now > tend
        elif st.get("first_ts"):
            final_ok = (time.time() - st["first_ts"]
                        > (DURATION_MIN + 10) * 60)
        else:
            final_ok = False
        if final_ok:
            st["final"] = True
            if not events:
                page_sc = final_score_from_page(md)
                if page_sc:
                    st["score"] = page_sc
            save_state(st)
            sc = st["score"]
            our, opp = (sc[0], sc[1]) if OUR_IS_HOME else (sc[1], sc[0])
            our_team = t1 if OUR_IS_HOME else t2
            opp_team = t2 if our_team == t1 else t1
            if our > opp:
                verdict = "🎉 <b>ПОБЕДА!</b> 🎉"
            elif our < opp:
                verdict = "😔 <b>ПОРАЖЕНИЕ</b> 😔"
            else:
                verdict = "🤝 <b>НИЧЬЯ</b> 🤝"
            send("🏁 <b>МАТЧ ЗАВЕРШЁН!</b> 🏁\n\n📊 Итоговый счёт: <b>"
                 + esc(our_team) + " " + str(our) + ":" + str(opp)
                 + " " + esc(opp_team) + "</b>\n\n" + verdict
                 + "\n\nСпасибо за игру, команду! 🤝")
            # Финальный синк: страница заявки уже включает сыгранный матч
            sync_stats_safe(st, force=True, match_url=match_url)


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
