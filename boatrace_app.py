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
import streamlit.components.v1 as components

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


def fetch_race_result(jcd: str, date_str: str, rno: int) -> dict:
    """レース結果ページから着順と払戻金を取得"""
    result = {"order": [], "trifecta_payout": 0, "trio_payout": 0, "debug": ""}
    try:
        url = f"{BOATRACE_URL}/owpc/pc/race/raceresult?rno={rno}&jcd={jcd}&hd={date_str}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        full_text = soup.get_text(" ", strip=True)

        if "ただいま集計中" in full_text or "準備中" in full_text:
            result["debug"] = "結果未確定"
            return result

        # ── 着順取得: is-boatColor クラスから ──
        for el in soup.find_all(class_=re.compile(r"is-boatColor\d")):
            cls_str = " ".join(el.get("class", []))
            m = re.search(r"is-boatColor(\d)", cls_str)
            if m:
                boat = int(m.group(1))
                # 着順テーブル内のものだけ拾う (親にtableがある)
                parent_tbl = el.find_parent("table")
                if parent_tbl:
                    parent_text = " ".join(parent_tbl.find("tr").get_text(" ", strip=True) if parent_tbl.find("tr") else "")
                    # 出走表テーブルは除外 (着順テーブルは行が少ない)
                    rows_in_tbl = parent_tbl.find_all("tr")
                    if len(rows_in_tbl) <= 8 and boat not in result["order"]:
                        result["order"].append(boat)

        # ── フォールバック1: tbody行を順番に読む ──
        if len(result["order"]) < 3:
            result["order"] = []
            for tbl in soup.find_all("table"):
                tbl_html = str(tbl)
                # 着順テーブルの特徴: "着" ヘッダがある
                ths = [th.get_text(strip=True) for th in tbl.find_all("th")]
                if not any("着" in h for h in ths):
                    continue
                for row in tbl.find_all("tr"):
                    tds = row.find_all("td")
                    if len(tds) < 2:
                        continue
                    # 各セルを調べて枠番(boatColor)を探す
                    for td in tds:
                        bc = td.find(class_=re.compile(r"is-boatColor(\d)"))
                        if bc:
                            m2 = re.search(r"is-boatColor(\d)", " ".join(bc.get("class", [])))
                            if m2:
                                b = int(m2.group(1))
                                if b not in result["order"]:
                                    result["order"].append(b)
                                break
                if len(result["order"]) >= 3:
                    break

        # ── フォールバック2: 全テーブルからtd[0]=1-6の連番パターン ──
        if len(result["order"]) < 3:
            result["order"] = []
            for tbl in soup.find_all("table"):
                temp_order = []
                for row in tbl.find_all("tr"):
                    tds = row.find_all("td")
                    if len(tds) >= 3:
                        texts = [td.get_text(strip=True) for td in tds]
                        if re.match(r"^[1-6]$", texts[0]):
                            rank = int(texts[0])
                            if rank == len(temp_order) + 1:
                                # 2番目のセルが枠番
                                for t in texts[1:4]:
                                    if re.match(r"^[1-6]$", t):
                                        temp_order.append(int(t))
                                        break
                if len(temp_order) >= 3:
                    result["order"] = temp_order
                    break

        # ── 払戻金 ──
        # テーブルから払戻を探す
        for tbl in soup.find_all("table"):
            tbl_text = tbl.get_text(" ", strip=True)
            if "3連単" in tbl_text or "三連単" in tbl_text:
                for row in tbl.find_all("tr"):
                    cells = row.find_all("td")
                    row_text = row.get_text(" ", strip=True)
                    if ("3連単" in row_text or "三連単" in row_text) and result["trifecta_payout"] == 0:
                        # 金額を探す
                        for cell in cells:
                            ct = cell.get_text(strip=True).replace(",", "").replace("円", "").replace("¥", "")
                            if re.match(r"^\d{3,}$", ct):
                                result["trifecta_payout"] = int(ct)
                                break

        # テキストからフォールバック
        if result["trifecta_payout"] == 0:
            for pat in [r"3連単.*?([\d,]+)\s*円", r"三連単.*?([\d,]+)\s*円"]:
                m = re.search(pat, full_text)
                if m:
                    result["trifecta_payout"] = int(m.group(1).replace(",", ""))
                    break

        result["debug"] = f"着順{len(result['order'])}件, 払戻{result['trifecta_payout']}円"

    except Exception as e:
        result["debug"] = f"Error: {str(e)[:100]}"
    return result


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

COMMON_CSS = """
<style>
    body { background: transparent; color: #eee; font-family: sans-serif; margin: 0; padding: 0; }
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
"""

def render_html(html_content: str, height: int = 300):
    """components.html でHTMLを確実にレンダリング"""
    full = f"<html><head>{COMMON_CSS}</head><body>{html_content}</body></html>"
    components.html(full, height=height, scrolling=False)

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

    table_height = 50 + len(hit_list) * 40
    render_html(f"""
    <table class="summary-table">
        <tr><th>時刻</th><th>会場</th><th>R</th><th>1号艇</th><th>2号艇</th></tr>
        {rows_html}
    </table>
    """, height=table_height)

    st.markdown("---")

    # 過去日判定（当日も含む＝結果が出ている可能性）
    is_past = selected_date <= date.today()

    # 回収率集計用
    total_bet_cost = 0
    total_payout = 0
    hit_count = 0
    result_count = 0

    # ── 各レース詳細カード + スコアリング ──
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

        num_boats = len(sorted_boats)
        card_height = 60 + num_boats * 36
        render_html(f"""
        <div class="race-card">
            <div class="race-header">
                【{race['venue']}】 {race['race_no']}R
                &nbsp;&nbsp; <span class="race-time">締切 {race['race_time']}</span>
            </div>
            {detail_rows}
        </div>
        """, height=card_height)

        # ── スコアリング＆予想 ──
        jcd_for_race = None
        for v in venues:
            if v["name"] == race["venue"]:
                jcd_for_race = v["jcd"]
                break
        if not jcd_for_race:
            continue

        with st.spinner(f"{race['venue']} {race['race_no']}R スコアリング中..."):
            try:
                before_info = fetch_beforeinfo(jcd_for_race, date_str, race["race_no"])
                _time.sleep(0.3)
                detail_info = fetch_racelist_detail(jcd_for_race, date_str, race["race_no"])
                _time.sleep(0.3)
            except Exception:
                before_info = {}
                detail_info = {}

            scores = calc_scores(race, before_info, detail_info, jcd_for_race)
            scenario = predict_scenario(scores, before_info, detail_info)

        # スコア一覧表示
        score_rows = ""
        for b in sorted(scores.keys(), key=lambda x: scores[x]["total"], reverse=True):
            s = scores[b]
            bg = BOAT_BG_COLORS[b]
            tc = BOAT_TEXT_COLORS[b]
            name = race["names"].get(b, detail_info.get("names", {}).get(b, "---"))
            bar_w = max(0, min(100, (s["total"] + 20) / 47.5 * 100))
            score_rows += f"""
            <div style="display:flex;align-items:center;margin:3px 0;">
                <span class="boat-badge" style="background:{bg};color:{tc};font-size:12px;">{b}</span>
                <span style="width:80px;font-size:13px;">{name}</span>
                <div style="flex:1;background:#16213e;border-radius:4px;height:20px;margin:0 8px;">
                    <div style="width:{bar_w}%;background:{'#e94560' if b == 1 else '#2a6496'};height:20px;border-radius:4px;"></div>
                </div>
                <span style="font-weight:bold;font-size:14px;width:50px;text-align:right;color:{'#e94560' if s['total'] >= 15 else '#eee'};">
                    {s['total']:.1f}
                </span>
            </div>"""

        # 展開シナリオ
        pattern = scenario.get("pattern", "不明")
        bets = scenario.get("trifecta_bets", [])
        bets_str = " / ".join(f"{a}-{b2}-{c}" for a, b2, c in bets[:6])
        cands_2 = scenario.get("candidates_2nd", [])
        cands_3 = scenario.get("candidates_3rd", [])

        # スコア差判定
        s_vals = sorted([scores[b]["total"] for b in range(1, 7)], reverse=True)
        gap = s_vals[0] - s_vals[1] if len(s_vals) >= 2 else 0
        if gap >= 3:
            conf = "◎ 明確な実力差"
        elif gap >= 1:
            conf = "○ やや優位"
        else:
            conf = "△ 混戦"

        render_html(f"""
        <div style="background:#0f3460;border-radius:8px;padding:12px;margin:0;">
            <div style="font-weight:bold;margin-bottom:8px;color:#e94560;">📊 スコアリング結果</div>
            {score_rows}
            <div style="margin-top:10px;padding-top:8px;border-top:1px solid #444;">
                <div style="font-size:13px;color:#aaa;">
                    🎯 展開予測: <strong style="color:#fff;">{pattern}</strong>
                    &nbsp;|&nbsp; 信頼度: <strong style="color:#fff;">{conf}</strong> (差 {gap:.1f}pt)
                </div>
                <div style="font-size:13px;color:#aaa;margin-top:4px;">
                    🏁 2着候補: <strong style="color:#FDD835;">{', '.join(str(c)+'号艇' for c in cands_2)}</strong>
                </div>
                <div style="font-size:13px;margin-top:6px;color:#aaa;">
                    🎰 三連単（1着1号艇固定）:
                </div>
                <div style="font-size:15px;font-weight:bold;color:#e94560;margin-top:2px;">
                    {bets_str}
                </div>
            </div>
        </div>
        """, height=380)

        # ── 過去レースの結果表示 ──
        if is_past:
            with st.spinner(f"{race['venue']} {race['race_no']}R 結果取得中..."):
                race_result = fetch_race_result(jcd_for_race, date_str, race["race_no"])
                _time.sleep(0.2)

            order = race_result.get("order", [])
            tri_pay = race_result.get("trifecta_payout", 0)
            debug_msg = race_result.get("debug", "")

            if len(order) >= 3:
                result_count += 1
                # 的中判定
                actual_top3 = tuple(order[:3])
                bet_hit = actual_top3 in [(a, b2, c) for a, b2, c in bets[:6]]
                bet_cost = len(bets[:6]) * 100  # 各100円
                total_bet_cost += bet_cost

                if bet_hit:
                    hit_count += 1
                    total_payout += tri_pay

                # 着順表示
                order_badges = ""
                for rank_i, ob in enumerate(order[:6], 1):
                    obg = BOAT_BG_COLORS.get(ob, "#555")
                    otc = BOAT_TEXT_COLORS.get(ob, "#fff")
                    oname = race["names"].get(ob, detail_info.get("names", {}).get(ob, "---"))
                    order_badges += f"""
                    <div style="display:flex;align-items:center;margin:2px 0;">
                        <span style="width:30px;color:#888;font-size:13px;">{rank_i}着</span>
                        <span class="boat-badge" style="background:{obg};color:{otc};width:24px;height:24px;line-height:24px;font-size:12px;">{ob}</span>
                        <span style="font-size:13px;margin-left:4px;">{oname}</span>
                    </div>"""

                hit_label = '<span style="color:#FDD835;font-weight:bold;font-size:16px;">🎉 的中！</span>' if bet_hit else '<span style="color:#888;">✗ 不的中</span>'
                pay_text = f"3連単 {tri_pay:,}円" if tri_pay else "払戻情報なし"

                render_html(f"""
                <div style="background:#1a1a2e;border-radius:8px;padding:12px;margin:0;border-left:4px solid {'#FDD835' if bet_hit else '#555'};">
                    <div style="font-weight:bold;margin-bottom:8px;color:#4fc3f7;">🏁 レース結果</div>
                    {order_badges}
                    <div style="margin-top:8px;padding-top:8px;border-top:1px solid #333;">
                        {hit_label}
                        <span style="margin-left:12px;color:#aaa;font-size:13px;">{pay_text}</span>
                    </div>
                </div>
                """, height=280)
            else:
                st.caption(f"⚠️ 結果取得不可 ({debug_msg})")

    # ── 全体回収率サマリー ──
    if is_past and result_count > 0:
        st.markdown("---")
        roi = (total_payout / total_bet_cost * 100) if total_bet_cost > 0 else 0
        roi_color = "#FDD835" if roi >= 100 else "#e94560"
        render_html(f"""
        <div style="background:#1a1a2e;border-radius:12px;padding:16px;border:2px solid {roi_color};">
            <div style="font-weight:bold;font-size:16px;margin-bottom:12px;color:{roi_color};">📈 本日の回収率サマリー</div>
            <div style="display:flex;justify-content:space-around;text-align:center;">
                <div>
                    <div style="color:#888;font-size:12px;">対象レース</div>
                    <div style="color:#fff;font-size:20px;font-weight:bold;">{result_count}</div>
                </div>
                <div>
                    <div style="color:#888;font-size:12px;">的中</div>
                    <div style="color:#FDD835;font-size:20px;font-weight:bold;">{hit_count}</div>
                </div>
                <div>
                    <div style="color:#888;font-size:12px;">投資</div>
                    <div style="color:#fff;font-size:20px;font-weight:bold;">{total_bet_cost:,}円</div>
                </div>
                <div>
                    <div style="color:#888;font-size:12px;">回収</div>
                    <div style="color:#fff;font-size:20px;font-weight:bold;">{total_payout:,}円</div>
                </div>
                <div>
                    <div style="color:#888;font-size:12px;">回収率</div>
                    <div style="color:{roi_color};font-size:20px;font-weight:bold;">{roi:.1f}%</div>
                </div>
            </div>
        </div>
        """, height=130)
