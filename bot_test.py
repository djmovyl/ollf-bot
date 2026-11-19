import os
import re
import requests
import traceback

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
MATCH_URL = "https://ollf.ru/match/5905503"

CHUNK = 3200

def tg(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", data=params, timeout=20)
    return r.json()

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def send(text):
    res = tg("sendMessage", chat_id=CHANNEL, text=text[:3900], parse_mode="HTML")
    if not res.get("ok"):
        print("Telegram error:", res)

def push(label, text, max_msgs=3):
    parts = [text[k:k+CHUNK] for k in range(0, len(text), CHUNK)]
    if not parts:
        return
    total = len(parts)
    for i, p in enumerate(parts[:max_msgs], 1):
        send(label + " (" + str(i) + "/" + str(total) + "):\n<pre>" + esc(p) + "</pre>")
    if total > max_msgs:
        send(label + ": показано " + str(max_msgs) + " из " + str(total) + " частей")

def jina(url, html=False):
    try:
        headers = {}
        if html:
            headers["X-Return-Format"] = "html"
        r = requests.get("https://r.jina.ai/" + url, headers=headers, timeout=60)
        print("jina:", url, "html" if html else "md", "->", r.status_code, len(r.text))
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print("jina error:", e)
        return ""

def main():
    md = jina(MATCH_URL)
    if not md:
        send("ДИАГНОСТИКА-2: страница не скачалась")
        return

    lines = md.splitlines()

    # 1) Протокол целиком, без обрезки строк — тут могут вылезти иконки карточек
    lo = max(0, 118)
    hi = min(len(lines), 156)
    frag = "\n".join(str(i) + ": " + lines[i] for i in range(lo, hi))
    push("ПРОТОКОЛ целиком", frag, 3)

    # 2) Поиск карточек и других событий по словам
    keys = ["карточ", "жёлт", "желт", "красн", "удал", "автогол",
            "пеналь", "замена", "ЖК", "КК", "yellow", "red card"]
    found = []
    for k in keys:
        for m in re.finditer(re.escape(k), md):
            i = m.start()
            ctx = md[max(0, i - 100): i + 160].replace("\n", " | ")
            found.append("[" + k + "] ..." + ctx + "...")
    if found:
        push("КЛЮЧЕВЫЕ СЛОВА (" + str(len(found)) + ")", "\n\n".join(found[:14]), 3)
    else:
        send("КЛЮЧЕВЫЕ СЛОВА: ни одного вхождения не найдено")

    # 3) HTML вокруг «странных» строк (без счёта) — там видно, чем карточка
    #    помечена в разметке: иконка, класс, alt-текст картинки
    html = jina(MATCH_URL, html=True)
    if html:
        for t in ["18' 06", "38' 27", "39' 31"]:
            i = html.find(t)
            if i > 0:
                push("HTML вокруг «" + t + "»", html[max(0, i - 700): i + 700], 1)
            else:
                send("HTML: фрагмент «" + t + "» не найден")
    else:
        send("HTML-версия не скачалась")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        send("ОШИБКА:\n<pre>" + esc(traceback.format_exc()[-2500:]) + "</pre>")
        raise
