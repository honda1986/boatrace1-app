"""
ボートレース 全国勝率フィルター (Streamlit版)

条件: 全国勝率が 1号艇 > 2号艇 の順で、両方とも上位3位以内のレースを抽出
過去日付の場合: レース結果 + 三連単 1-全-2 購入時の回収率を表示

使い方:
  pip install streamlit requests beautifulsoup4
  streamlit run boatrace_app.py
"""

import re
import time as _time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from datetime import datetime, date
import streamlit as st

# ──────────────── 定数 ────────────────
BASE_URL = "https://uchisankaku.sakura.ne.jp"
BOATRACE_URL = "https://www.boatrace.jp"

VENUE_NAMES = {
    "01": "桐生",  "02": "戸田",  "03": "江戸川", "04": "平和島",
    "05": "多摩川", "06": "浜名湖", "07": "蒲郡",  "08": "常滑",
    "09": "津",    "10": "三国",  "11": "びわこ", "12": "住之江",
    "13": "尼崎",  "14": "鳴門",  "15": "丸亀",   "16": "児島",
    "17": "宮島",  "18": "徳山",  "19": "下関",   "20": "若松",
    "21": "芦屋",  "22": "福岡",  "23": "唐津",   "24": "大村",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
}

BOAT_BG = {1:"#FFFFFF",2:"#333333",3:"#E53935",4:"#1E88E5",5:"#FDD835",6:"#43A047"}
BOAT_TX = {1:"#000000",2:"#FFFFFF",3:"#FFFFFF",4:"#FFFFFF",5:"#000000",6:"#FFFFFF"}


# ──────────────── データ取得 ────────────────
def get_venues(date_str):
    url = f"{BASE_URL}/raceindex.php?date={date_str}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    venues, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "racelist.php" in href and "jcode=" in href:
            qs = parse_qs(urlparse(href).query)
            jcode = qs.get("jcode", [None])[0]
            if jcode and jcode not in seen:
                seen.add(jcode)
                jcd = jcode.zfill(2)
                name = VENUE_NAMES.get(jcd, f"会場{jcode}")
                venues.append({"jcode": jcode, "jcd": jcd, "name": name})
    return venues


def fetch_race_times(jcd, date_str):
    race_times = {}
    try:
        url = f"{BOATRACE_URL}/owpc/pc/race/raceindex?jcd={jcd}&hd={date_str}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "racelist" in href and "rno=" in href:
                qs = parse_qs(urlparse(href).query)
                rno_str = qs.get("rno", [None])[0]
                if not rno_str:
                    continue
                rno = int(rno_str)
                tr = a.find_parent("tr")
                if tr:
                    txt = tr.get_text(" ", strip=True)
                    m = re
