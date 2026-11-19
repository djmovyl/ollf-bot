import os
import re
import time
import requests
import traceback
from bs4 import BeautifulSoup

# === ТЕСТОВЫЕ НАСТРОЙКИ (в финальном боте вместо этого — календарь и окно матча) ===
TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
MATCH_URL = "https://ollf.ru/match/5905503"
OUR_KEY = "ITPROVIDER"
STATE_FILE = "test_state.json"

TIME_PAT = re.compile(r"(\d{1,3})'\s*(\d{2})''")
SCORE_END = re.compile(r"(\d{1,2})\s*:\s*(\d{1,2})\s*$")
PLAYER_PAT = re.compile(r"
$$
([^
$$
]+)\]")
TEAM_PAT = re.compile(
    r"
$$
([^
$$
]+)\]
