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

# ──────────────── スコアリング定数 ────────────────
COURSE_BASE = {1: 10, 2: 6, 3: 5, 4: 4, 5: 3, 6: 1}
IN_BOOST_VENUES = {"18", "24", "19"}   # 徳山/大村/下関
IN_PENALTY_VENUES = {"02", "04", "03"} # 戸田/平和島/江戸川
HARD_WATER_VENUES = {"02", "03", "04", "10", "11"} # 難水面

# ──────────────── 追加データ取得 ────────────────

def fetch_beforeinfo(jcd: str, date_str: str, rno: int) -> dict:
    """直前情報ページからモーター2連率・展示タイム・風・波・ST等を取得"""
    info = {
        "motor_2rate": {},    # {boat: float}
        "exhibit_time": {},   # {boat: float}
        "wind_dir": "",       # "追い風" / "向かい風" etc
        "wind_speed": 0,      # m
        "wave_height": 0,     # cm
        "avg_st": {},         # {boat: float} 平均ST
        "f_count": {},        # {boat: int}  F数
        "f_type": {},         # {boat: str}  "スロー"/"ダッシュ"
    }
    try:
        url = f"{BOATRACE_URL}/owpc/pc/race/beforeinfo?rno={rno}&jcd={jcd}&hd={date_str}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 風向・風速・波高
        weather_div = soup.find("div", class_="weather1")
        if not weather_div:
            weather_div = soup  # fallback to full page
        full_text = weather_div.get_text(" ", strip=True) if weather_div else ""

        # 風速
        wm = re.search(r"風速\s*(\d+)m", full_text)
        if wm:
            info["wind_speed"] = int(wm.group(1))
        # 波高
        hm = re.search(r"波高\s*(\d+)cm", full_text)
        if hm:
            info["wave_height"] = int(hm.group(1))
        # 風向
        if "追い風" in full_text or "追" in full_text:
            info["wind_dir"] = "追い風"
        elif "向かい風" in full_text or "向" in full_text:
            info["wind_dir"] = "向かい風"

        # 風向の画像クラスから判定
        wind_img = soup.find("p", class_=re.compile(r"is-wind"))
        if wind_img:
            cls = " ".join(wind_img.get("class", []))
            # is-wind1=北(追い風), is-wind5=南(向かい風) etc - simplified
            if "is-wind1" in cls or "is-wind2" in cls or "is-wind8" in cls:
                info["wind_dir"] = "追い風"
            elif "is-wind4" in cls or "is-wind5" in cls or "is-wind6" in cls:
                info["wind_dir"] = "向かい風"

        # テーブルから各艇データ
        tables = soup.find_all("table", class_=re.compile(r"is-w495|is-w738"))
        # 直前情報のメインテーブル
        for tbl in soup.find_all("table"):
            rows = tbl.find_all("tr")
            for row in rows:
                cells = row.find_all(["th", "td"])
                texts = [c.get_text(strip=True) for c in cells]
                # モーター2連率行を検出
                if any("モータ" in t and "2連率" in t for t in texts):
                    vals = [t for t in texts if re.match(r"^\d+\.\d+$", t)]
                    for i, v in enumerate(vals[:6]):
                        info["motor_2rate"][i + 1] = float(v)
                # 展示タイム
                if any("展示" in t and "タイム" in t for t in texts):
                    vals = [t for t in texts if re.match(r"^\d+\.\d+$", t)]
                    for i, v in enumerate(vals[:6]):
                        info["exhibit_time"][i + 1] = float(v)

        # 選手テーブルからST・F情報
        body_tables = soup.find_all("div", class_=re.compile(r"table1"))
        for bt in body_tables:
            for row in bt.find_all("tr"):
                cells = row.find_all("td")
                texts = [c.get_text(strip=True) for c in cells]
                # 平均STの行
                if any("平均ST" in t for t in texts):
                    vals = [t for t in texts if re.match(r"^0\.\d+$", t)]
                    for i, v in enumerate(vals[:6]):
                        info["avg_st"][i + 1] = float(v)

        # 別のパース: ボディ全体から平均STを探す
        if not info["avg_st"]:
            all_text = soup.get_text()
            st_matches = re.findall(r"平均ST\s*([\d.]+)", all_text)
            # 各選手ブロックから
            player_blocks = soup.find_all("div", class_=re.compile(r"is-boatColor"))
            for i, pb in enumerate(player_blocks[:6]):
                t = pb.parent.get_text() if pb.parent else ""
                sm = re.search(r"平均ST\s*(0\.\d+)", t)
                if sm:
                    info["avg_st"][i + 1] = float(sm.group(1))

        # F数を探す
        for i, pb in enumerate(soup.find_all("div", class_=re.compile(r"is-boatColor"))):
            block = pb.find_parent("div", class_=re.compile(r"table1")) or pb.parent
            if block:
                t = block.get_text()
                fm = re.search(r"F(\d)", t)
                if fm:
                    info["f_count"][i + 1] = int(fm.group(1))

    except Exception as e:
        pass
    return info


def fetch_racelist_detail(jcd: str, date_str: str, rno: int) -> dict:
    """出走表ページから勝率・当地勝率・モーター2連率・展示タイム等を取得"""
    detail = {
        "national_rate": {},   # {boat: float} 全国勝率
        "local_rate": {},      # {boat: float} 当地勝率
        "motor_2rate": {},     # {boat: float}
        "national_2rate": {},  # {boat: float} 全国2連率
        "exhibit_time": {},    # {boat: float}
        "avg_st": {},          # {boat: float}
        "f_count": {},         # {boat: int}
        "names": {},
        "is_first_day": False,
        "is_final": False,
        "session_results": {},  # {boat: [着順list]}
        "session_st": {},       # {boat: [ST list]}
    }
    try:
        url = f"{BOATRACE_URL}/owpc/pc/race/racelist?rno={rno}&jcd={jcd}&hd={date_str}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 初日/優勝戦判定
        page_text = soup.get_text()
        if "初日" in page_text:
            detail["is_first_day"] = True
        if "優勝戦" in page_text:
            detail["is_final"] = True

        # 選手ブロック
        player_bodies = soup.find_all("tbody", class_=re.compile(r"is-fs"))
        if not player_bodies:
            player_bodies = soup.find_all("tbody")

        for boat_no, tbody in enumerate(player_bodies[:6], 1):
            rows = tbody.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                texts = [c.get_text(strip=True) for c in cells]

                # 選手名
                name_cell = row.find("a", href=re.compile(r"toJinData"))
                if name_cell:
                    detail["names"][boat_no] = name_cell.get_text(strip=True)

                # 全国勝率/2連率
                for ci, t in enumerate(texts):
                    if re.match(r"^\d\.\d{2}$", t):
                        val = float(t)
                        if boat_no not in detail["national_rate"] and 3.0 < val < 10.0:
                            detail["national_rate"][boat_no] = val
                        elif boat_no not in detail["national_2rate"]:
                            if 10 < val < 80:
                                detail["national_2rate"][boat_no] = val

                # モーター2連率
                for ci, t in enumerate(texts):
                    if re.match(r"^\d{2}\.\d+$", t):
                        val = float(t)
                        if boat_no not in detail["motor_2rate"] and 15 < val < 75:
                            detail["motor_2rate"][boat_no] = val

            # 節間成績を探す (着順リスト)
            tbody_text = tbody.get_text()
            results_match = re.findall(r"(\d)着", tbody_text)
            if results_match:
                detail["session_results"][boat_no] = [int(x) for x in results_match]

            # 節間STを探す
            st_matches = re.findall(r"(?:F?\s*)?(\.\d{2})", tbody_text)
            if st_matches:
                detail["session_st"][boat_no] = [float(f"0{x}") for x in st_matches if 0.01 < float(f"0{x}") < 0.30]

        # 展示タイム・平均ST は beforeinfo から取る方が正確なのでここではスキップ

    except Exception:
        pass
    return detail


# ──────────────── スコアリングエンジン ────────────────

def calc_scores(race_data: dict, before_info: dict, detail: dict, jcd: str) -> dict:
    """
    10項目スコアリング。race_data は既存の parse_racelist 結果。
    Returns {boat: {total, items: {①〜⑩: val}}}
    """
    scores = {}
    boats = range(1, 7)

    # 展示タイム情報
    et = before_info.get("exhibit_time", {})
    if et:
        et_sorted = sorted(et.values())
        et_best = et_sorted[0] if et_sorted else None
        et_worst = et_sorted[-1] if et_sorted else None
    else:
        et_best = et_worst = None

    for b in boats:
        items = {}

        # ① コース基礎点
        base = COURSE_BASE[b]
        if detail.get("is_final") and b == 1:
            base = 12
        items["①コース基礎"] = base

        # ② 場別イン補正
        venue_adj = 0
        if b == 1:
            if jcd in IN_BOOST_VENUES:
                venue_adj = 3
            elif jcd in IN_PENALTY_VENUES:
                venue_adj = -3
        items["②場別補正"] = venue_adj

        # ③ 風速・波高補正
        wind_adj = 0
        ws = before_info.get("wind_speed", 0)
        wd = before_info.get("wind_dir", "")
        wv = before_info.get("wave_height", 0)
        if wd == "追い風" and ws >= 5:
            if b == 1:
                wind_adj -= 2.5
            elif b == 2:
                wind_adj += 1.5
        if wd == "向かい風" and ws >= 5:
            if b == 1:
                wind_adj -= 2.5
            elif b == 4:
                wind_adj += 1.5
        if wv >= 8 and b == 1:
            wind_adj -= 3.0
        items["③風波補正"] = wind_adj

        # ④ モーター2連率
        m2 = before_info.get("motor_2rate", {}).get(b) or detail.get("motor_2rate", {}).get(b)
        motor_adj = 0
        if m2 is not None:
            if m2 > 50:
                motor_adj = 3.0
            elif m2 >= 40:
                motor_adj = 1.5
            elif m2 < 25:
                motor_adj = -2.0
        # 初日は0.5倍に減衰
        if detail.get("is_first_day"):
            motor_adj *= 0.5
        items["④モーター"] = motor_adj

        # ⑤ 展示タイム
        et_adj = 0
        bt_et = et.get(b)
        if bt_et is not None and et_best is not None and et_worst is not None:
            if bt_et <= et_best and et_worst - bt_et >= 0.07:
                et_adj = 2.0
            if bt_et >= et_worst and bt_et - et_best >= 0.07:
                et_adj = -2.0
        items["⑤展示タイム"] = et_adj

        # ⑥ 平均ST（⑥-2 節間ST補正を優先）
        st_adj = 0
        sess_st = detail.get("session_st", {}).get(b, [])
        avg_st_val = before_info.get("avg_st", {}).get(b)
        nat_rate = detail.get("national_rate", {}).get(b)

        has_session_st = len(sess_st) >= 2
        if has_session_st:
            # ⑥-2 節間ST補正
            sess_avg = sum(sess_st) / len(sess_st)
            # 全国平均STの代理: avg_st (出走表の平均ST)
            ref_st = avg_st_val if avg_st_val else 0.15
            if sess_avg < ref_st - 0.05:
                st_adj += 1.5
            elif sess_avg > ref_st + 0.05:
                st_adj -= 1.5
            # 安定性: 3走連続0.15以内
            if len(sess_st) >= 3 and all(s <= 0.15 for s in sess_st[-3:]):
                st_adj += 1.0
            # 不安定: 直近0.20以上が2回
            recent_slow = sum(1 for s in sess_st[-3:] if s >= 0.20)
            if recent_slow >= 2:
                st_adj -= 1.0
        else:
            # 通常の⑥
            if avg_st_val is not None:
                if avg_st_val <= 0.10:
                    st_adj = 2.0
                elif avg_st_val >= 0.20:
                    st_adj = -2.0
        items["⑥ST補正"] = st_adj

        # ⑦ Fペナルティ
        f_adj = 0
        fc = before_info.get("f_count", {}).get(b) or detail.get("f_count", {}).get(b, 0)
        if fc >= 2:
            f_adj = -3.0
        elif fc == 1:
            # ダッシュ/スロー判定 (簡略: コース4-6はダッシュ)
            if b >= 4:
                f_adj = -2.0
            else:
                f_adj = -1.0
        # F持ち選手の⑦半減条件 (節間STが平均ST同等)
        if fc >= 1 and has_session_st and avg_st_val:
            sess_avg = sum(sess_st) / len(sess_st)
            if abs(sess_avg - avg_st_val) < 0.02:
                f_adj *= 0.5
        items["⑦Fペナ"] = f_adj

        # ⑧ 選手力
        player_adj = 0
        wr = race_data.get("win_rates", {}).get(b) or detail.get("national_rate", {}).get(b)
        if wr is not None:
            if wr >= 7.5:
                player_adj = 3.0
            elif wr >= 6.5:
                player_adj = 2.0
            elif wr >= 5.5:
                player_adj = 1.0
            elif wr >= 4.5:
                player_adj = 0.0
            elif wr >= 3.5:
                player_adj = -1.0
            else:
                player_adj = -2.0
        # 難水面当地補正
        local_wr = detail.get("local_rate", {}).get(b)
        if jcd in HARD_WATER_VENUES:
            if local_wr and local_wr > 5.0:
                player_adj += 1.0
            elif local_wr and local_wr < 3.5:
                player_adj -= 1.0
        items["⑧選手力"] = player_adj

        # ⑨ 節間動態 (⑨-2 強化版)
        sess_adj = 0
        sess_res = detail.get("session_results", {}).get(b, [])
        if len(sess_res) >= 3:
            # 3走連続改善
            last3 = sess_res[-3:]
            if last3[0] > last3[1] > last3[2]:
                sess_adj += 1.5
            # 3走連続悪化
            if last3[0] < last3[1] < last3[2]:
                sess_adj -= 1.5
            # 3走連続着外
            if all(r >= 4 for r in last3):
                sess_adj -= 2.0
        if len(sess_res) >= 2:
            last2 = sess_res[-2:]
            # 直近2走連続1着
            if all(r == 1 for r in last2):
                sess_adj += 2.0
            # 直近2走連続2着以内
            elif all(r <= 2 for r in last2):
                sess_adj += 1.0
        if len(sess_res) >= 1:
            # 直近1走6着＋展示タイム下位
            if sess_res[-1] == 6:
                if bt_et is not None and et_worst is not None and bt_et >= et_worst:
                    sess_adj -= 1.5
        # 今節2連率 vs 全国2連率
        if sess_res:
            sess_2rate = sum(1 for r in sess_res if r <= 2) / len(sess_res) * 100
            nat_2r = detail.get("national_2rate", {}).get(b, 40)
            if sess_2rate > nat_2r + 10:
                sess_adj += 1.0
            elif sess_2rate < nat_2r - 15:
                sess_adj -= 1.0
        items["⑨節間動態"] = sess_adj

        # ⑩ 進入変動 (簡易: データ不足時は0)
        entry_adj = 0
        items["⑩進入変動"] = entry_adj

        total = sum(items.values())
        scores[b] = {"total": round(total, 1), "items": items}

    return scores


def predict_scenario(scores: dict, before_info: dict, detail: dict) -> dict:
    """展開シナリオと買い目を生成"""
    scenario = {}

    # 1着は1号艇固定
    first = 1
    s1 = scores[1]["total"]

    # ST情報から隊形予測
    avg_sts = before_info.get("avg_st", {})
    sess_sts = detail.get("session_st", {})

    # 1号艇のST力評価
    st1 = avg_sts.get(1, 0.15)
    # 他艇のST
    fast_starters = []
    for b in range(2, 7):
        st_b = avg_sts.get(b, 0.18)
        if st_b < st1 - 0.03:
            fast_starters.append(b)

    # 決まり手予測
    if not fast_starters or s1 >= max(scores[b]["total"] for b in range(2, 7)) + 3:
        pattern = "逃げ"
    elif any(b in fast_starters for b in [2, 3]):
        # 内側からの攻め → 差し
        pattern = "差し"
    elif any(b in fast_starters for b in [4, 5, 6]):
        pattern = "まくり"
    else:
        pattern = "逃げ"

    scenario["pattern"] = pattern

    # 2着予測
    sorted_others = sorted(
        [(b, scores[b]["total"]) for b in range(2, 7)],
        key=lambda x: x[1], reverse=True
    )

    if pattern == "逃げ":
        # 2C 34.3%, 3C 27.1%
        candidates_2nd = [2, 3, sorted_others[0][0]]
    elif pattern == "差し":
        # 差し決着 → 1号艇2着率60% → 差した艇が1着にならないので1着固定なら2着は差し艇隣
        candidates_2nd = [2, 3, sorted_others[0][0]]
    elif pattern == "まくり":
        # まくり艇の1つ外側
        makuri_boat = fast_starters[0] if fast_starters else 4
        outer = min(makuri_boat + 1, 6)
        candidates_2nd = [makuri_boat, outer, sorted_others[0][0]]
    elif pattern == "まくり差し":
        candidates_2nd = [2, 3, sorted_others[0][0]]
    else:
        candidates_2nd = [sorted_others[0][0], sorted_others[1][0]]

    # 重複除去・1を除去
    seen = set()
    unique_2nd = []
    for c in candidates_2nd:
        if c != 1 and c not in seen:
            seen.add(c)
            unique_2nd.append(c)
    if not unique_2nd:
        unique_2nd = [sorted_others[0][0]]

    scenario["candidates_2nd"] = unique_2nd[:3]

    # 3着: スコア上位から
    all_used = {1} | set(unique_2nd[:2])
    candidates_3rd = [b for b, _ in sorted_others if b not in all_used][:3]
    # 2着候補の残りも3着候補に
    for c in unique_2nd:
        if c not in all_used and c not in candidates_3rd:
            candidates_3rd.append(c)

    scenario["candidates_3rd"] = candidates_3rd[:4]

    # 三連単買い目生成 (1着=1号艇固定)
    bets = []
    for sec in unique_2nd[:3]:
        thirds = [b for b in range(2, 7) if b != sec]
        # スコア順でソート
        thirds.sort(key=lambda b: scores[b]["total"], reverse=True)
        for trd in thirds[:2]:
            bets.append((1, sec, trd))

    scenario["trifecta_bets"] = bets
    return scenario


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
            full = so
