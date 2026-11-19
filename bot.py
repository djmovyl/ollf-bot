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

MONTHS = {"ЯНВ":1,"ФЕВ":2,"МАР":3,"АПР":4,"МАЙ":5,"ИЮН":6,
          "ИЮЛ":7,"АВГ":8,"СЕН":9,"ОКТ":10,"НОЯ":11,"ДЕК":12}

# Строка календаря вида:
# [Группа 1](https://ollf.ru/match/5905503)[15 НОЯБ. / ВС / 20:00 Триумф 3 FC ITPROVIDER 4]
# [Группа 2](https://ollf.ru/match/5905800)[22 НОЯБ. / ВС / 15:20 FC ITPROVIDER - Напитки вместе -]
# Регулярка собрана из коротких кусков через +, чтобы её невозможно было разорвать при вставке
LINE_PAT = re.compile(
    r"\[Группа\s*\d*\]\("
    r"(https://ollf\.ru/match/\d+)"
    r"\)\s*\["
    r"(\d{1,2})\s+([А-Яа-яЁё]{3,4})\."
    r"\s*/\s*[А-Яа-яЁё]{2,3}\s*/\s*"
    r"(\d{1,2}):(\d{2})"
    r"\s+([^\]]+)\]"
)

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
    except Exception:
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
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print("jina html error:", e)
        return ""

def extract_opponent(text):
    """Триумф 3 FC ITPROVIDER 4 -> Триумф; FC ITPROVIDER - Напитки вместе - -> Напитки вместе"""
    text = text.strip()
    if HOME not in text:
        return None
    idx = text.find(HOME)
    before = text[:idx].strip().strip(" -–—").strip()
    after = text[idx + len(HOME):].strip().strip(" -–—").strip()
    opp = before or after
    opp = re.sub(r"^\d+\s*", "", opp)
    opp = re.sub(r"\s+\d+$", "", opp)
    return opp.strip(" -–— ") or None

def find_next_match(st):
    md = jina(TOURNAMENT_URL)
    if not md:
        return None
    now = datetime.now(MSK)

    upcoming = []
    for m in LINE_PAT.finditer(md):
        url, day, mon_s, hh, mm, teams = m.groups()
        mon = MONTHS.get(mon_s[:3].upper())
        if mon is None:
            continue
        opponent = extract_opponent(teams)
        if not opponent:
            continue
        year = now.year if mon >= 7 else now.year + 1
        start = datetime(year, mon, int(day), int(hh), int(mm), tzinfo=MSK)
        # Берём только матчи, которые ещё не прошли (плюс запас на часовой сдвиг)
        if start >= now - timedelta(hours=2):
            upcoming.append({"start": start, "opponent": opponent, "url": url})

    if not upcoming:
        return None
    upcoming.sort(key=lambda x: x["start"])
    nxt = upcoming[0]

    # Ссылка уже пришла из календаря; кэш — на случай, если она вдруг пропадёт
    if not nxt.get("url"):
        key = nxt["opponent"][:12] + nxt["start"].strftime("%d%H")
        if st.get("found_key") == key and st.get("found_url"):
            nxt["url"] = st["found_url"]
            return nxt
        html = jina_html(TOURNAMENT_URL)
        for mid in list(dict.fromkeys(re.findall(r'/match/(\d+)', html)))[:30]:
            t = jina(f"https://ollf.ru/match/{mid}")
            if t and "ITPROVIDER" in t.upper() and nxt["opponent"][:6].upper() in t.upper():
                nxt["url"] = f"https://ollf.ru/match/{mid}"
                break

    if nxt.get("url"):
        st["found_key"] = nxt["opponent"][:12] + nxt["start"].strftime("%d%H")
        st["found_url"] = nxt["url"]
        save_state(st)
    return nxt

# --- События матча (черновой парсер — отрепетируем на матче 5905503) ---
def parse_events(text):
    events = []
    pattern = (r"(\d{1,2})'\s*[-–—]\s*([^\n–—|]+?)\s*[-–—]\s*"
               r"([^\n–—|]*?)\s*[-–—]\s*([^\n]+)")
    for m in re.finditer(pattern, text):
        minute, player, assist, team = m.groups()
        events.append({"minute": int(minute),
                       "player": player.strip(),
                       "assist": (assist or "").strip() or None,
                       "team": team.strip()})
    return events

def is_home(team):
    return "ITPROVIDER" in team.upper()

def post_event(ev, st):
    if is_home(ev["team"]):
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
    save_state(st)   # state.json существует всегда — git не споткнётся

    nxt = find_next_match(st)

    # Диагностика при ручном запуске: всегда отчитываемся в канал
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        if nxt:
            st["calendar_ok"] = True
            save_state(st)
            send(f"✅ <b>Календарь прочитан!</b>\n\n"
                 f"🔍 {HOME} vs {nxt['opponent']}\n"
                 f"🗓 {nxt['start']:%d.%m}, ⏰ {nxt['start']:%H:%M} (МСК)\n"
                 f"🔗 {nxt.get('url') or 'ссылка уточняется'}")
        else:
            md = jina(TOURNAMENT_URL)
            i = md.find("ITPROVIDER")
            frag = md[max(0, i - 300): i + 300] if i > 0 else md[:600]
            send("❌ <b>Матч не найден.</b> Фрагмент календаря:\n\n"
                 f"<pre>{frag.replace('&', '&amp;').replace('<', '&lt;')}</pre>")

    if not nxt:
        print("Матч не найден — тихий выход (обычный запуск)")
        return
    if not nxt.get("url"):
        print("Нет ссылки на матч — тихий выход")
        return

    match_id = nxt["url"].rstrip("/").split("/")[-1]
    if st.get("match_id") != match_id:
        st = {"seen_events": [], "score_home": 0, "score_away": 0,
              "started": False, "final_posted": False,
              "calendar_ok": st.get("calendar_ok", False),
              "found_key": st.get("found_key"), "found_url": nxt["url"],
              "match_id": match_id}

    now = datetime.now(MSK)
    start = nxt["start"]
    in_window = start - timedelta(minutes=10) <= now <= start + timedelta(minutes=115)

    deadline = now + timedelta(minutes=LOOP_MINUTES)
    while True:
        html = jina(nxt["url"])
        if html:
            now = datetime.now(MSK)
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
    try:
        main()
    except Exception:
        send("🚨 <b>Ошибка бота:</b>\n<pre>" +
             traceback.format_exc()[-3500:].replace("&", "&amp;").replace("<", "&lt;") +
             "</pre>")
        raise
