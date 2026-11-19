import os
import re
import requests
import traceback

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
MATCH_URL = "https://ollf.ru/match/5905503"

CHUNK = 3300

def tg(method, **params):
    r = requests.post("https://api.telegram.org/bot" + TOKEN + "/" + method,
                      data=params, timeout=20)
    return r.json()

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def send(text):
    res = tg("sendMessage", chat_id=CHANNEL, text=text, parse_mode="HTML")
    if not res.get("ok"):
        print("Telegram error:", res)

def jina(url):
    try:
        r = requests.get("https://r.jina.ai/" + url, timeout=60)
        print("jina:", url, "->", r.status_code, len(r.text))
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print("jina error:", e)
        return ""

def main():
    md = jina(MATCH_URL)
    if not md:
        send("ДИАГНОСТИКА: страница не скачалась")
        return

    lines = md.splitlines()

    # Шаблон времени события: 4' 30'' или просто 20'
    time_pat = re.compile(r"\d{1,3}'\s*\d{0,2}''")

    # Слова-заголовки секций протокола
    keywords = ["Голы", "тайм", "Карточк", "Предупрежд",
                "Замены", "Составы", "Запасные"]

    zone = set()
    for i, l in enumerate(lines):
        if time_pat.search(l):
            for j in range(max(0, i - 1), min(len(lines), i + 2)):
                zone.add(j)
        for kw in keywords:
            if kw in l:
                zone.add(max(0, i - 1))
                zone.add(i)
                zone.add(min(len(lines) - 1, i + 1))
        if "application?team_id" in l:
            zone.add(i)

    out = []
    for i in sorted(zone):
        out.append(str(i) + ": " + lines[i].strip()[:170])

    text = "\n".join(out)
    parts = [text[k:k + CHUNK] for k in range(0, len(text), CHUNK)]
    n = 0
    for p in parts:
        n += 1
        if n > 3:
            send("ДИАГНОСТИКА: данных слишком много, показано 3 части из "
                 + str(len(parts)))
            break
        send("ДИАГНОСТИКА протокола, часть " + str(n) + ":\n<pre>"
             + esc(p) + "</pre>")

    print("строк всего:", len(lines), "строк в зоне:", len(zone))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        send("ОШИБКА:\n<pre>" + esc(traceback.format_exc()[-2500:]) + "</pre>")
        raise
