import os, requests
from curl_cffi import requests as crequests

TOKEN   = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]

def send(text):
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                     params={"chat_id": CHANNEL, "text": text[:3900]}, timeout=20)
    print(r.text[:150])

URLS = {
    "турнир": "https://ollf.ru/tournament/1067343",
    "матч":   "https://ollf.ru/match/5905503",
}

report = []

def probe(name, url, method):
    try:
        if method == "cffi":
            r = crequests.get(url, impersonate="chrome", timeout=30)
            body = r.text
        else:
            r = requests.get(f"https://r.jina.ai/{url}", timeout=60)
            body = r.text
        report.append(
            f"{name} [{method}]\n"
            f"  статус: {r.status_code}, размер: {len(body)}\n"
            f"  есть ITPROVIDER: {'ITPROVIDER' in body}\n"
            f"  есть События: {'События' in body}\n"
            f"  есть Протокол: {'Протокол' in body}"
        )
        i = body.find("События")
        if i > 0:
            report.append("  фрагмент: " + body[i:i+250].replace("\n", " "))
    except Exception as e:
        report.append(f"{name} [{method}]  ОШИБКА: {e}")

for label, url in URLS.items():
    probe(label, url, "cffi")
    probe(label, url, "jina")

send("📋 Диагностика 2:\n\n" + "\n\n".join(report))
