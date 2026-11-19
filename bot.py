import os, re, json, time, requests
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
        return {"seen_events": [], "score_home": 0, "score_away": 0,
                "started": False, "final_posted": False}

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)

def jina(url):
    try:
        r = requests.get("https://r.jina.ai/" + url, timeout=60)
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print("jina error:", e)
        return ""

# --- Календарь: точная регулярка под реальный формат «22 НОЯБ. / ВС / 15:20» ---
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
        year = now.year if mon >= 8 else now.year + 1   # сезон 2026/27: лето-осень — 2026, зима-весна — 2027
        start = datetime(year, mon, int(m.group(1)), int(m.group(3)), int(m.group(4)), tzinfo=MSK)
        if start >= now - timedelta(hours=3):
            upcoming.append({"start": start, "opponent": m.group(5).strip()})
    if not upcoming:
        return None
    upcoming.sort(key=lambda x: x["start"])
    nxt = upcoming[0]

    # Ссылка на матч: берём из HTML-версии страницы, кэшируем до следующего матча
    key = nxt["opponent"] + nxt["start"].strftime("%d%H")
    if st.get("found_key") == key and st.get("found_url"):
        nxt["url"] = st["found_url"]
        return nxt

    html = ""
    try:
        r = requests.get("https://r.jina.ai/" + TOURNAMENT_URL,
                         headers={"X-Return-Format": "html", "x-respond-with": "html"},
                         timeout=60)
        if r.status_code == 200:
            html = r.text
    except Exception:
        pass
    ids = list(dict.fromkeys(re.findall(r'/match/(\d+)', html))) if html else []

    url = None
    for mid in ids[:20]:
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

# --- События матча (черновой парсер, отрепетируем отдельно) ---
def parse_events(html):
    events = []
    pattern = (r'(\d{1,2})\'\s*[-–—]\s*([^–—\n|]+?)\s*[-–—]\s*(?:([^–—\n|]+?)\s*[-–—]\s*)?'
               r'(FC ITPROVIDER|[^\n]+)$')
    for m in re.finditer(pattern, html, re.MULTILINE):
        events.append({"minute": int(m.group(1)),
                       "player": (m.group(2) or "").strip(),
                       "assist": (m.group(3) or "").strip() or None,
                       "team": (m.group(4) or "").strip()})
    return events

def is_home(team):
    return "ITPROVIDER" in team.upper()

def post_event(ev, st):
    if is_home(ev.get("team", "")):
        st["score_home"] += 1
        text = (f"🔥⚽️ <b>Г-О-О-О-Л! 🔥⚽️</b>\n\n"
                f"⚽ <b>АВТОР ГОЛА: {ev['player']}</b> 🌟\n"
                + (f"🎯 Ассист: {ev['assist']}\n" if ev["assist"] else "")
                + f"⏱ На {ev['minute']}' минуте!\n\n"
                f"Счёт: <b>{st['score_home']} : {st['score_away']}</b> в нашу пользу! 🎉")
    else:
        st["score_away"] += 1
        text = (f"😢 <b>Пропускаем...</b> 😢\n\n"
                f"На {ev['minute']}' минуте соперник забивает.\n\n"
                f"Счёт: <b>{st['score_home']} : {st['score_away']}</b>. Не сдаёмся! 💪")
    send(text)

def main():
    st = load_state()
    now = datetime.now(MSK)
    nxt = find_next_match(st)
    if not nxt:
        print("Матч не найден")
        return

    if not st.get("calendar_ok"):          # разовая проверка календаря — то самое «раз и навсегда»
        st["calendar_ok"] = True
        save_state(st)
        send(f"✅ <b>Календарь прочитан!</b>\n\n"
             f"🔍 {HOME} vs {nxt['opponent']}\n"
             f"🗓 {nxt['start']:%d.%m}, ⏰ {nxt['start']:%H:%M} (МСК)\n"
             f"🔗 {nxt.get('url') or 'ссылка уточняется'}")

    if not nxt.get("url"):
        print("Нет ссылки на матч")
        return

    match_id = nxt["url"].rstrip("/").split("/")[-1]
    if st.get("match_id") != match_id:
        st = {"seen_events": [], "score_home": 0, "score_away": 0,
              "started": False, "final_posted": False,
              "calendar_ok": st.get("calendar_ok", False),
              "found_key": st.get("found_key"), "found_url": nxt["url"],
              "match_id": match_id}

    start = nxt["start"]
    in_window = start - timedelta(minutes=10) <= now <= start + timedelta(minutes=115)

    deadline = now + timedelta(minutes=LOOP_MINUTES)
    while True:
        now = datetime.now(MSK)
        html = jina(nxt["url"])
        if html:
            if not st["started"] and now >= start:
                st["started"] = True
                send(f"🏟️ <b>МАТЧ НАЧАЛСЯ!</b> 🏟️\n\n"
                     f"🆚 <b>{HOME} vs {nxt['opponent']}</b>\n\n"
                     f"Держим кулаки за команду! 👊")
            for ev in parse_events(html):
                eid = f"{ev['minute']}-{ev['player']}"
                if eid in st["seen_events"]:
                    continue
                if st["started"]:
                    post_event(ev, st)
                st["seen_events"].append(eid)
            if st["started"] and not st["final_posted"] and "матч завершён" in html.lower():
                st["final_posted"] = True
                send(f"🏁 <b>МАТЧ ЗАВЕРШЁН!</b> 🏁\n\n"
                     f"📊 Итоговый счёт: <b>{st['score_home']} : {st['score_away']}</b>\n\n"
                     f"Спасибо за игру, команда! 🤝")
        save_state(st)
        if in_window and datetime.now(MSK) < deadline and not st.get("final_posted"):
            time.sleep(POLL_SECONDS)
        else:
            break

if __name__ == "__main__":
    main()
