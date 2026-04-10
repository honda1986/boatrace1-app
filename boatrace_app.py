"""
ボートレース 全国勝率フィルター (Streamlit版)

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

# 枠番の色
BOAT_COLORS = {
    1: "#FFFFFF",  # 白
    2: "#000000",  # 黒
    3: "#E53935",  # 赤
    4: "#1E88E5",  # 青
    5: "#FDD835",  # 黄
    6: "#43A047",  # 緑
}
BOAT_BG_COLORS = {
    1: "#FFFFFF",
    2: "#333333",
    3: "#E53935",
    4: "#1E88E5",
    5: "#FDD835",
    6: "#43A047",
}
BOAT_TEXT_COLORS = {
    1: "#000000",
    2: "#FFFFFF",
    3: "#FFFFFF",
    4: "#FFFFFF",
    5: "#000000",
    6: "#FFFFFF",
}


# ──────────────── データ取得関数 ────────────────
def get_venues(date_str: str) -> list[dict]:
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


def fetch_race_times(jcd: str, date_str: str) -> dict[int, str]:
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
                    m = re.search(r"(\d{1,2}:\d{2})", txt)
                    if m:
                        race_times[rno] = m.group(1)
        if not race_times:
            full = soup.get_text(" ", strip=True)
            for m in re.finditer(r"(\d{1,2})\s*R\s+(\d{1,2}:\d{2})", full):
                race_times[int(m.group(1))] = m.group(2)
        if not race_times:
            tds = soup.find_all("td")
            for i, td in enumerate(tds):
                txt = td.get_text(strip=True)
                rm = re.match(r"^(\d{1,2})R$", txt)
                if rm and i + 1 < len(tds):
                    rno = int(rm.group(1))
                    next_txt = tds[i + 1].get_text(strip=True)
                    tm = re.search(r"(\d{1,2}:\d{2})", next_txt)
                    if tm:
                        race_times[rno] = tm.group(1)
    except Exception:
        pass
    return race_times


def parse_racelist(jcode, date_str, venue_name, race_times):
    url = f"{BASE_URL}/racelist.php?jcode={jcode}&date={date_str}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for h3 in soup.find_all("h3"):
        race_label = h3.get_text(strip=True)
        m = re.search(r"(\d{1,2})R", race_label)
        if not m:
            continue
        race_no = int(m.group(1))
        race_time = race_times.get(race_no, "--:--")
        table = h3.find_next("table")
        if not table:
            continue
        names, win_rates, in_zenkoku = {}, {}, False
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            texts = [c.get_text(strip=True) for c in cells]
            if "氏名" in texts:
                idx = texts.index("氏名")
                for i, n in enumerate(texts[idx + 1: idx + 7]):
                    if n:
                        names[i + 1] = n
            if "全国" in texts:
                in_zenkoku = True
            if "当地" in texts:
                in_zenkoku = False
            if in_zenkoku and "勝率" in texts and not win_rates:
                idx = texts.index("勝率")
                vals = texts[idx + 1: idx + 7]
                if len(vals) == 6:
                    try:
                        win_rates = {i + 1: float(vals[i]) for i in range(6)}
                    except ValueError:
                        pass
        if win_rates:
            results.append({
                "venue": venue_name,
                "race_no": race_no,
                "race_time": race_time,
                "win_rates": win_rates,
                "names": names,
            })
    return results


def meets_condition(wr):
    if 1 not in wr or 2 not in wr:
        return False
    if wr[1] <= wr[2]:
        return False
    sorted_vals = sorted(wr.values(), reverse=True)
    top3_min = sorted_vals[2]
    return wr[1] >= top3_min and wr[2] >= top3_min


# ──────────────── Streamlit UI ────────────────
st.set_page_config(page_title="ボートレース 勝率フィルター", page_icon="🚤", layout="centered")

st.markdown("""
<style>
    .race-card {
        background: #1a1a2e; color: #eee; border-radius: 12px;
        padding: 16px; margin-bottom: 16px; border-left: 4px solid #0f3460;
    }
    .race-header { font-size: 1.1em; font-weight: bold; margin-bottom: 8px; }
    .race-time { color: #e94560; font-weight: bold; }
    .boat-badge {
        display: inline-block; width: 28px; height: 28px; line-height: 28px;
        text-align: center; border-radius: 50%; font-weight: bold; font-size: 14px;
        margin-right: 6px;
    }
    .rate-bar { background: #16213e; border-radius: 4px; height: 22px; margin: 2px 0; }
    .rate-fill { height: 22px; border-radius: 4px; line-height: 22px;
                 padding-left: 6px; font-size: 12px; color: #fff; }
    .hit-marker { color: #e94560; font-weight: bold; }
    .summary-table { width: 100%; border-collapse: collapse; font-size: 14px; }
    .summary-table th { background: #0f3460; color: #eee; padding: 8px; text-align: left; }
    .summary-table td { padding: 8px; border-bottom: 1px solid #333; }
</style>
""", unsafe_allow_html=True)

st.title("🚤 ボートレース 全国勝率フィルター")
st.caption("全国勝率が 1号艇 > 2号艇 の順で、両方とも上位3位以内のレースを抽出")

col1, col2 = st.columns([2, 1])
with col1:
    selected_date = st.date_input("対象日", value=date.today())
with col2:
    st.write("")
    st.write("")
    run = st.button("🔍 検索", use_container_width=True, type="primary")

if run:
    date_str = selected_date.strftime("%Y%m%d")

    with st.spinner("会場一覧を取得中..."):
        venues = get_venues(date_str)

    if not venues:
        st.warning("開催中の会場がありません。")
        st.stop()

    st.info(f"開催会場: {', '.join(v['name'] for v in venues)} ({len(venues)}場)")

    hit_list = []
    progress = st.progress(0, text="解析中...")

    for vi, v in enumerate(venues):
        progress.progress((vi + 1) / len(venues), text=f"{v['name']} を解析中...")
        race_times = fetch_race_times(v["jcd"], date_str)
        _time.sleep(0.3)
        try:
            races = parse_racelist(v["jcode"], date_str, v["name"], race_times)
        except Exception:
            continue
        for race in races:
            if meets_condition(race["win_rates"]):
                hit_list.append(race)
        _time.sleep(0.3)

    progress.empty()

    # 出走時刻順ソート
    hit_list.sort(key=lambda r: r["race_time"] if r["race_time"] != "--:--" else "99:99")

    st.markdown(f"### ★ 該当レース: {len(hit_list)} 件")

    if not hit_list:
        st.warning("条件に合致するレースはありませんでした。")
        st.stop()

    # ── サマリーテーブル ──
    rows_html = ""
    for r in hit_list:
        wr = r["win_rates"]
        rows_html += f"""<tr>
            <td><span class="race-time">{r['race_time']}</span></td>
            <td><strong>{r['venue']}</strong></td>
            <td>{r['race_no']}R</td>
            <td>{wr[1]:.2f}</td>
            <td>{wr[2]:.2f}</td>
        </tr>"""

    st.markdown(f"""
    <table class="summary-table">
        <tr><th>時刻</th><th>会場</th><th>R</th><th>1号艇</th><th>2号艇</th></tr>
        {rows_html}
    </table>
    """, unsafe_allow_html=True)

    st.markdown("---")
    # ── 各レース詳細カード ──
    for race in hit_list:
        wr = race["win_rates"]
        sorted_boats = sorted(wr.items(), key=lambda x: x[1], reverse=True)
        max_rate = max(wr.values())

        detail_rows = ""
        for rank, (boat, rate) in enumerate(sorted_boats, 1):
            name = race["names"].get(boat, "---")
            bg = BOAT_BG_COLORS[boat]
            tc = BOAT_TEXT_COLORS[boat]
            pct = (rate / max_rate * 100) if max_rate else 0
            marker = ' <span class="hit-marker">◀</span>' if boat in (1, 2) else ""
            
            # HTMLタグの先頭の空白を無くします
            detail_rows += f"""<div style="display:flex;align-items:center;margin:4px 0;">
<span style="width:30px;color:#888;">{rank}位</span>
<span class="boat-badge" style="background:{bg};color:{tc};">{boat}</span>
<span style="width:100px;">{name}</span>
<div class="rate-bar" style="flex:1;">
<div class="rate-fill" style="width:{pct}%;background:{bg};">{rate:.2f}</div>
</div>
{marker}
</div>"""

        # ここも先頭の空白を無くします
        st.markdown(f"""<div class="race-card">
<div class="race-header">
【{race['venue']}】 {race['race_no']}R
&nbsp;&nbsp; <span class="race-time">締切 {race['race_time']}</span>
</div>
{detail_rows}
</div>""", unsafe_allow_html=True)
