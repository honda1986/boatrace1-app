"""
ボートレース 全国勝率フィルター (Streamlit版)

条件: 全国勝率が 1号艇 > 2号艇 の順で、両方とも上位3位以内のレースを抽出
過去日付の場合: レース結果 + 三連単 全-1,2-1,2 購入時の回収率を表示

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
                    m = re.search(r"(\d{1,2}:\d{2})", txt)
                    if m:
                        race_times[rno] = m.group(1)
        if not race_times:
            full = soup.get_text(" ", strip=True)
            for m in re.finditer(r"(\d{1,2})\s*R\s+(\d{1,2}:\d{2})", full):
                race_times[int(m.group(1))] = m.group(2)
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
        text = h3.get_text(strip=True)
        m = re.search(r"(\d{1,2})R", text)
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
                for i, n in enumerate(texts[idx+1:idx+7]):
                    if n:
                        names[i+1] = n
            if "全国" in texts:
                in_zenkoku = True
            if "当地" in texts:
                in_zenkoku = False
            if in_zenkoku and "勝率" in texts and not win_rates:
                idx = texts.index("勝率")
                vals = texts[idx+1:idx+7]
                if len(vals) == 6:
                    try:
                        win_rates = {i+1: float(vals[i]) for i in range(6)}
                    except ValueError:
                        pass
        if win_rates:
            results.append({
                "venue": venue_name, "jcd": jcode.zfill(2),
                "race_no": race_no, "race_time": race_time,
                "win_rates": win_rates, "names": names,
            })
    return results


def fetch_race_result(jcd, date_str, rno):
    """
    boatrace.jp から着順と三連単払戻を取得。
    戻り値: {"finish_order": [2,1,6,3,4,5], "trifecta_combo": "2-1-6",
             "trifecta_payout": 29960, "error": None}
    """
    info = {"finish_order": [], "trifecta_combo": "", "trifecta_payout": 0, "error": None}
    try:
        url = (f"{BOATRACE_URL}/owpc/pc/race/raceresult"
               f"?rno={rno}&jcd={jcd}&hd={date_str}")
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        page_text = soup.get_text()

        # ── 着順を取得 ──
        # 着順テーブル: 着 | 枠 | ボートレーサー | レースタイム
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["th", "td"])
                texts = [c.get_text(strip=True) for c in cells]
                # ヘッダ行判定
                if any("着" in t and "枠" in " ".join(texts) for t in texts):
                    continue
                # 着順の数字行: "１","2","5328 ..."
                if len(texts) >= 3:
                    # 枠番 (2番目のセル) を取得
                    waku_text = texts[1] if len(texts) >= 2 else ""
                    # 着順 (1番目のセル)
                    chaku_text = texts[0]
                    # 全角数字→半角
                    chaku_text = chaku_text.translate(str.maketrans("１２３４５６７８９０", "1234567890"))
                    waku_text = waku_text.translate(str.maketrans("１２３４５６７８９０", "1234567890"))
                    if chaku_text.isdigit() and waku_text.isdigit():
                        info["finish_order"].append(int(waku_text))

        # ── 三連単払戻を取得 ──
        # 勝式 | 組番 | 払戻金 | 人気
        found_3t = False
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["th", "td"])
                texts = [c.get_text(strip=True) for c in cells]
                if "3連単" in texts:
                    found_3t = True
                    # 組番と払戻金を取得
                    idx = texts.index("3連単")
                    remaining = texts[idx+1:]
                    if len(remaining) >= 2:
                        combo = remaining[0]  # "2-1-6"
                        payout_str = remaining[1]  # "¥29,960"
                        payout_str = payout_str.replace("¥", "").replace(",", "").replace("￥", "").strip()
                        info["trifecta_combo"] = combo
                        try:
                            info["trifecta_payout"] = int(payout_str)
                        except ValueError:
                            info["trifecta_payout"] = 0

        if not info["finish_order"]:
            info["error"] = "結果未取得"

    except Exception as e:
        info["error"] = str(e)

    return info


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
    .race-card-hit {
        background: #1a1a2e; color: #eee; border-radius: 12px;
        padding: 16px; margin-bottom: 16px; border-left: 4px solid #43A047;
    }
    .race-card-miss {
        background: #1a1a2e; color: #eee; border-radius: 12px;
        padding: 16px; margin-bottom: 16px; border-left: 4px solid #E53935;
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
    .result-box { background: #16213e; border-radius: 8px; padding: 12px;
                  margin-top: 10px; }
    .result-hit { color: #43A047; font-weight: bold; font-size: 1.1em; }
    .result-miss { color: #E53935; font-weight: bold; font-size: 1.1em; }
    .summary-table { width: 100%; border-collapse: collapse; font-size: 14px; }
    .summary-table th { background: #0f3460; color: #eee; padding: 8px; text-align: left; }
    .summary-table td { padding: 8px; border-bottom: 1px solid #333; }
    .roi-box { background: #0f3460; border-radius: 12px; padding: 20px;
               text-align: center; margin: 16px 0; }
    .roi-value { font-size: 2em; font-weight: bold; }
    .roi-positive { color: #43A047; }
    .roi-negative { color: #E53935; }
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
    is_past = selected_date < date.today()

    with st.spinner("会場一覧を取得中..."):
        venues = get_venues(date_str)

    if not venues:
        st.warning("開催中の会場がありません。")
        st.stop()

    st.info(f"開催会場: {', '.join(v['name'] for v in venues)} ({len(venues)}場)"
            + ("　📊 過去日付のため結果・回収率も表示" if is_past else ""))

    hit_list = []
    progress = st.progress(0, text="出走表を解析中...")

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

    # ── 過去日付ならレース結果を取得 ──
    if is_past:
        progress2 = st.progress(0, text="レース結果を取得中...")
        for ri, race in enumerate(hit_list):
            progress2.progress((ri + 1) / len(hit_list),
                               text=f"{race['venue']} {race['race_no']}R の結果取得中...")
            result = fetch_race_result(race["jcd"], date_str, race["race_no"])
            race["result"] = result
            _time.sleep(0.4)
        progress2.empty()

    # ── 回収率計算 (過去日付のみ) ──
    if is_past:
        # 三連単 全-1,2-1,2 = X-1-2, X-2-1 (X=3,4,5,6) の8点 × 100円 = 800円/レース
        bet_per_race = 800
        total_invest = bet_per_race * len(hit_list)
        total_payout = 0
        hit_count = 0

        for race in hit_list:
            res = race.get("result", {})
            fo = res.get("finish_order", [])
            payout = res.get("trifecta_payout", 0)
            # 2着と3着が1号艇・2号艇(順不同)なら的中
            if len(fo) >= 3 and set(fo[1:3]) == {1, 2}:
                total_payout += payout
                race["is_hit"] = True
                hit_count += 1
            else:
                race["is_hit"] = False

        roi = (total_payout / total_invest * 100) if total_invest > 0 else 0
        roi_class = "roi-positive" if roi >= 100 else "roi-negative"

        st.markdown(f"""
        <div class="roi-box">
            <div style="color:#aaa;font-size:0.9em;">三連単 全-1,2-1,2 (8点×100円) 回収率</div>
            <div class="roi-value {roi_class}">{roi:.1f}%</div>
            <div style="color:#888;font-size:0.85em;margin-top:6px;">
                投資: ¥{total_invest:,} ({len(hit_list)}R × ¥800)　
                回収: ¥{total_payout:,}　
                的中: {hit_count}/{len(hit_list)}R
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── サマリーテーブル ──
    if is_past:
        header = "<tr><th>時刻</th><th>会場</th><th>R</th><th>1号艇</th><th>2号艇</th><th>結果</th><th>払戻</th></tr>"
    else:
        header = "<tr><th>時刻</th><th>会場</th><th>R</th><th>1号艇</th><th>2号艇</th></tr>"

    rows_html = ""
    for r in hit_list:
        wr = r["win_rates"]
        if is_past:
            res = r.get("result", {})
            fo = res.get("finish_order", [])
            finish_str = "-".join(str(x) for x in fo[:3]) if fo else "---"
            payout = res.get("trifecta_payout", 0)
            is_hit = r.get("is_hit", False)
            payout_str = f"¥{payout:,}" if is_hit and payout else "---"
            if is_hit:
                result_style = 'style="color:#43A047;font-weight:bold;"'
            else:
                result_style = 'style="color:#E53935;"'
            rows_html += f"""<tr>
                <td><span class="race-time">{r['race_time']}</span></td>
                <td><strong>{r['venue']}</strong></td>
                <td>{r['race_no']}R</td>
                <td>{wr[1]:.2f}</td>
                <td>{wr[2]:.2f}</td>
                <td {result_style}>{finish_str}</td>
                <td {result_style}>{payout_str}</td>
            </tr>"""
        else:
            rows_html += f"""<tr>
                <td><span class="race-time">{r['race_time']}</span></td>
                <td><strong>{r['venue']}</strong></td>
                <td>{r['race_no']}R</td>
                <td>{wr[1]:.2f}</td>
                <td>{wr[2]:.2f}</td>
            </tr>"""

    st.markdown(f"""
    <table class="summary-table">
        {header}
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
            bg = BOAT_BG[boat]
            tc = BOAT_TX[boat]
            pct = (rate / max_rate * 100) if max_rate else 0
            marker = ' <span class="hit-marker">◀</span>' if boat in (1, 2) else ""
            detail_rows += f"""
            <div style="display:flex;align-items:center;margin:4px 0;">
                <span style="width:30px;color:#888;">{rank}位</span>
                <span class="boat-badge" style="background:{bg};color:{tc};">{boat}</span>
                <span style="width:100px;">{name}</span>
                <div class="rate-bar" style="flex:1;">
                    <div class="rate-fill" style="width:{pct}%;background:{bg};">{rate:.2f}</div>
                </div>
                {marker}
            </div>"""

        # 結果セクション (過去日付のみ)
        result_html = ""
        if is_past:
            res = race.get("result", {})
            fo = res.get("finish_order", [])
            payout = res.get("trifecta_payout", 0)
            is_hit = race.get("is_hit", False)

            if is_hit:
                judge = f'<span class="result-hit">◎ 的中！ 払戻 ¥{payout:,}</span>'
            else:
                judge = '<span class="result-miss">✗ ハズレ</span>'

            # 着順を枠番色バッジで表示
            finish_badges = ""
            for i, boat_no in enumerate(fo[:3]):
                if 1 <= boat_no <= 6:
                    fbg = BOAT_BG[boat_no]
                    ftc = BOAT_TX[boat_no]
                    finish_badges += f'<span class="boat-badge" style="background:{fbg};color:{ftc};">{boat_no}</span>'
                    if i < 2:
                        finish_badges += '<span style="color:#888;">→</span>'

            result_html = f"""
            <div class="result-box">
                <div style="margin-bottom:6px;">
                    <span style="color:#aaa;">着順: </span>{finish_badges}
                </div>
                <div>{judge}</div>
            </div>"""

        # カードスタイル選択
        if is_past:
            card_class = "race-card-hit" if race.get("is_hit") else "race-card-miss"
        else:
            card_class = "race-card"

        st.markdown(f"""
        <div class="{card_class}">
            <div class="race-header">
                【{race['venue']}】 {race['race_no']}R
                &nbsp;&nbsp; <span class="race-time">締切 {race['race_time']}</span>
            </div>
            {detail_rows}
            {result_html}
        </div>
        """, unsafe_allow_html=True)
