import os, re, json, time, requests, traceback
from datetime import datetime, timedelta, timezone

TOKEN   = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
TOURNAMENT_URL = "https://ollf.ru/tournament/1067343"
HOME = "FC ITPROVIDER"
STATE_FILE = "state.json"

MSK = timezone(timedelta(hours=3))
POLL_SECONDS = 60
LOOP_MINUTES = 4

MONTHS = {"ЯНВ":1,"ФЕВ":2,"МАР":3,"АПР":4,"МАЙ":5,"ИЮН":6,"ИЮЛ":7,
          "АВГ":8,"СЕН":9,"ОКТ":10,"НОЯ":11,"ДЕК":12}

def tg(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}",
                      data=params, timeout=20)
    return r.json()

def send(text):
    res = tg("sendMessage", chat_id=CHANNEL, text=text[:3900], parse_mode="HTML")
    if not res.get("ok"):
        print("Telegram error:", res)

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)

def jina(url):
    try:
        r = requests.get("https://r.jina.ai/" + url, timeout=60)
        print("jina:", url, "->", r.status_code, len(r.text))
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print("jina error:", e)
        return ""

def jina_html(url):
    try:
        r = requests.get("https://r.jina.ai/" + url,
                         headers={"X-Return-Format": "html"}, timeout=60)
        print("jina html:", r.status_code, len(r.text))
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print("jina html error:", e)
        return ""

# --- Календарь: формат «22 НОЯБ. / ВС / 15:20 FC ITPROVIDER - Соперник -» ---
def find_next_match(st):
    md = jina(TOURNAMENT_URL)
    if not md:
        return None
    now = datetime.now(MSK)
    pat = re.compile(
        r"(\d{1,2})\s+([А-Яа-яЁё]{3})\.\s*/\s*[А-Яа-яЁё]{2,3}\s*/\s*"
        r"(\d{1,2}):(\d{2})\s+FC ITPROVIDER\s*[-–—]\s*(.+?)\s*[-–—]")
    upcoming = []
    for m in pat.finditer(md):
        mon = MONTHS.get(m.group(2).upper())
        if mon is None:
            continue
        year = now.year if mon >= 7 else now.year + 1
        start = datetime(year, mon, int(m.group(1)),
                         int(m.group(3)), int(m.group(4)), tzinfo=MSK)
        if start >= now - timedelta(hours=3):
            upcoming.append({"start": start, "opponent": m.group(5).strip()})
    if not upcoming:
        return None
    upcoming.sort(key=lambda x: x["start"])
    nxt = upcoming[0]

    # Ссылку на матч кэшируем в state, чтобы не искать каждый раз
    key = nxt["opponent"][:12] + nxt["start"].strftime("%d")
    if st.get("found_key") == key and st.get("found_url"):
        nxt["url"] = st["found_url"]
        return nxt

    ids = list(dict.fromkeys(re.findall(r'/match/(\d+)', jina_html(TOURNAMENT_URL))))[:20]
    url = None
    for mid in ids:
        t = jina(f"https://ollf.ru/match/{mid}")
        if "ITPROVIDER" in t.upper() and nxt["opponent"][:6].upper() in t.upper():
            url = f"https://ollf.ru/match/{mid}"
            break
    nxt["url"] = url
    if url:
        st["found_key"] = key
        st["found_url"] = url
        save_state(st)
    return nxt

# --- События матча (черновой парсер — отрепетируем отдельно) ---
def parse_events(text):
    events = []
    pattern = (r"(\d{1,2})'\d{0,2}''?\s*[-–—]\s*([^\n–—|]+?)\s*[-–—]\s*"
               r"([^\n–—|]+?)\s*[-–—]\s*([^\n]+)")
    for m in re.finditer(pattern, text):
        events.append({"minute": int(m.group(1)),
                       "player": m.group(2).strip(),
                       "assist": m.group(3).strip(),
                       "team":
