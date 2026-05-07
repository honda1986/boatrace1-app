# -*- coding: utf-8 -*-
"""
v17.14 全艇スコア解析アプリ（ST改善点の上限2.0設定版）
"""

import re
import concurrent.futures
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
import lightgbm as lgb
import numpy as np

# 日本時間の設定
JST = timezone(timedelta(hours=+9), 'JST')

# ============================================================
# HTTP設定（超・爆速化のための通信エンジン）
# ============================================================
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Mobile Safari/537.36"}
req_session = requests.Session()
req_session.headers.update(UA)

adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=3)
req_session.mount('https://', adapter)
req_session.mount('http://', adapter)

BOAT_URL = "https://www.boatrace.jp/owpc/pc/race"
JCD_NAME = {
    1:"桐生", 2:"戸田", 3:"江戸川", 4:"平和島", 5:"多摩川", 6:"浜名湖",
    7:"蒲郡", 8:"常滑", 9:"津", 10:"三国", 11:"びわこ", 12:"住之江",
    13:"尼崎", 14:"鳴門", 15:"丸亀", 16:"児島", 17:"宮島", 18:"徳山",
    19:"下関", 20:"若松", 21:"芦屋", 22:"福岡", 23:"唐津", 24:"大村"
}

# ============================================================
# 場別コース別データ
# ============================================================
COURSE_WIN_RATE: Dict[str, List[float]] = {
    "全国":   [55.1, 14.0, 12.8, 11.1, 6.1, 1.8],
    "桐生":   [53.8, 13.2, 12.6, 12.5, 7.2, 1.4],
    "戸田":   [43.9, 15.9, 16.6, 14.5, 7.7, 2.5],
    "江戸川": [45.7, 18.4, 15.1, 12.3, 7.6, 2.6],
    "平和島": [45.1, 17.0, 14.4, 13.1, 7.7, 3.7],
    "多摩川": [52.9, 16.5, 12.5, 11.5, 5.9, 1.9],
    "浜名湖": [50.9, 15.9, 14.4, 11.5, 6.8, 1.6],
    "蒲郡":   [54.4, 11.8, 13.6, 13.7, 6.2, 1.4],
    "常滑":   [57.8, 12.8, 10.9, 10.8, 7.0, 1.6],
    "津":     [57.7, 15.6, 11.9,  9.5, 4.8, 1.4],
    "三国":   [55.2, 14.9, 13.5, 11.0, 5.3, 1.3],
    "びわこ": [56.8, 14.6, 11.8, 11.5, 4.6, 1.6],
    "住之江": [57.9, 14.6, 11.6,  9.8, 5.3, 1.6],
    "尼崎":   [57.6, 12.0, 12.0, 11.9, 5.6, 1.7],
    "鳴門":   [47.5, 14.9, 16.1, 12.2, 7.7, 2.3],
    "丸亀":   [56.2, 15.2, 11.7, 10.3, 5.0, 2.5],
    "児島":   [55.6, 12.9, 12.1, 12.3, 6.1, 2.0],
    "宮島":   [57.0, 13.1, 12.9,  9.6, 6.3, 2.0],
    "徳山":   [65.9, 12.8,  9.2,  6.6, 4.7, 1.1],
    "下関":   [59.6, 10.6, 10.9, 10.9, 6.2, 2.6],
    "若松":   [56.8, 11.8, 12.9, 11.2, 6.4, 2.0],
    "芦屋":   [59.1, 11.3, 11.3, 10.8, 6.1, 2.2],
    "福岡":   [56.0, 14.8, 15.2,  9.2, 4.8, 1.0],
    "唐津":   [55.3, 14.2, 13.5, 10.3, 6.6, 1.3],
    "大村":   [61.3, 12.1, 11.3,  9.6, 5.0, 1.3],
}

def venue_course_bonus(v: str, l: int) -> float:
    if v not in COURSE_WIN_RATE: return 0.0
    return round((COURSE_WIN_RATE[v][l-1] - COURSE_WIN_RATE["全国"][l-1]) * 0.1, 2)

def venue_attack_bonus(v: str, l: int) -> float:
    if l < 2 or v not in COURSE_WIN_RATE: return 0.0
    return round((COURSE_WIN_RATE[v][l-1] - COURSE_WIN_RATE["全国"][l-1]) * 0.05, 2)

# ============================================================
# データ構造・スコアリング
# ============================================================
@dataclass
class Racer:
    name: str = ""
    cls: str = ""
    win_rate: Optional[float] = None
    avg_st: Optional[float] = None
    settle_st: Optional[float] = None
    settle_avg_rank: Optional[float] = None
    motor_2rate: Optional[float] = None
    f_count: int = 0
    exhibit_rank: Optional[int] = None

def score_boat(r: Racer, venue: str, lane: int) -> Dict[str, float]:
    parts: Dict[str, float] = {}

    if r.settle_avg_rank and r.settle_avg_rank > 0:
        parts["節平順"] = round(3.5 / r.settle_avg_rank, 2)
    else:
        parts["節平順"] = 0.0

    # ★変更点: ST改善（点）＝ 0.2 ÷ 節平均ST （※最高2.0点まで）
    if r.settle_st and r.settle_st > 0:
        raw_st_score = round(0.2 / r.settle_st, 2)
        parts["節ST改善"] = min(raw_st_score, 2.0)
    else:
        parts["節ST改善"] = 0.0
    
    exhibit_scores = {1: 1.5, 2: 0.8, 3: 0.3, 4: -0.2, 5: -0.6, 6: -1.0}
    parts["展示"] = exhibit_scores.get(r.exhibit_rank, 0.0)
    
    if r.f_count >= 1: parts["F持ち"] = -1.5 * r.f_count
    
    parts["場×コース"] = venue_course_bonus(venue, lane)
    parts["場×攻め"]   = venue_attack_bonus(venue, lane)

    parts["合計"] = round(sum(parts.values()), 2)
    return parts

# ============================================================
# AI予測・ランキング・買い目生成
# ============================================================
@st.cache_resource
def load_lgb_model():
    try: return lgb.Booster(model_file='lgb_model.txt')
    except: return None

def get_lgb_features(r: Racer, lane: int, venue: str) -> list:
    NAME_TO_JCD = {
        "桐生":1, "戸田":2, "江戸川":3, "平和島":4, "多摩川":5, "浜名湖":6,
        "蒲郡":7, "常滑":8, "津":9, "三国":10, "びわこ":11, "住之江":12,
        "尼崎":13, "鳴門":14, "丸亀":15, "児島":16, "宮島":17, "徳山":18,
        "下関":19, "若松":20, "芦屋":21, "福岡":22, "唐津":23, "大村":24
    }
    jcd = NAME_TO_JCD.get(venue, 1)
    return [float(jcd), float(lane), float(r.win_rate or 0.0), float(r.avg_st or 0.17), float(r.motor_2rate or 0.0)]

def rank_all(racers: List[Racer], venue: str) -> List[Dict]:
    out = []
    lgb_model = load_lgb_model()
    for i, r in enumerate(racers):
        lane = i + 1
        bd = score_boat(r, venue, lane)
        ai_score = 0.0
        if lgb_model:
            ai_pred = lgb_model.predict([get_lgb_features(r, lane, venue)])[0]
            ai_score = round(ai_pred * 10, 2)
            bd["AI加点"] = ai_score 
            
        final_score = round(bd["合計"] + ai_score, 2)
        bd["総合計(AI込)"] = final_score
        out.append({"lane": lane, "racer": r, "score": final_score, "breakdown": bd})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out

def make_bets(ranked: List[Dict], strategy: str = "standard") -> List[str]:
    if len(ranked) < 4: return []
    lanes = [x["lane"] for x in ranked]
    l1, l2, l3, l4 = lanes[0], lanes[1], lanes[2], lanes[3]
    l5 = lanes[4] if len(lanes) >= 5 else l4
    
    if strategy == "safe": 
        return [f"{l1}-{l2}-{l3}", f"{l1}-{l3}-{l2}"]
    elif strategy == "wide": 
        raw = []
        for s in (l2, l3, l4):
            for t in (l2, l3, l4, l5):
                if t != s and t != l1 and s != l1:
                    c = f"{l1}-{s}-{t}"
                    if c not in raw: raw.append(c)
        return raw
    else:
        raw = []
        for s in (l2, l3):
            for t in (l2, l3, l4):
                if t != s and t != l1 and s != l1:
                    c = f"{l1}-{s}-{t}"
                    if c not in raw: raw.append(c)
        return raw

def strategy_label(strategy: str) -> str:
    return {"safe": "安全2点", "standard": "標準4点", "wide": "拡張9点"}.get(strategy, strategy)

# ============================================================
# スクレイピング関数群
# ============================================================
def get_html(url: str) -> Optional[str]:
    try:
        r = req_session.get(url, timeout=10)
        r.encoding = r.apparent_encoding
        return r.text if r.status_code == 200 else None
    except: return None

@st.cache_data(ttl=600)
def boatrace_venues(dstr: str) -> List[int]:
    html = get_html(f"{BOAT_URL}/index?hd={dstr}")
    if not html: return []
    return sorted({int(m.group(1)) for m in re.finditer(r'jcd=(\d+)', html)})

def fetch_race_detail(jcd: int, rno: int, dstr: str) -> Optional[List[Racer]]:
    html = get_html(f"{BOAT_URL}/racelist?rno={rno}&jcd={jcd:02d}&hd={dstr}")
    if not html: return None
    soup = BeautifulSoup(html, "html.parser")
    
    target = None
    for tbl in soup.find_all("table"):
        head = tbl.get_text(" ", strip=True)
        if all(k in head for k in ["ボートレーサー", "全国", "当地", "モーター"]):
            target = tbl
            break
    if not target: return None

    racers = []
    rows = target.find_all("tr")
    lane_map = {"１":1,"２":2,"３":3,"４":4,"５":5,"６":6,"1":1,"2":2,"3":3,"4":4,"5":5,"6":6}

    main_rows = []
    seen_lanes = set()
    for tr in rows:
        a_test = tr.find("a", href=re.compile(r"profile\?toban=\d+"))
        if not a_test: continue
        cells = tr.find_all(["td", "th"])
        if not cells: continue
        first_text = cells[0].get_text(strip=True)
        if first_text in lane_map and lane_map[first_text] not in seen_lanes:
            lane = lane_map[first_text]
            main_rows.append((lane, tr))
            seen_lanes.add(lane)
            if len(main_rows) >= 6: break

    if len(main_rows) < 6: return None
    main_rows.sort(key=lambda x: x[0])

    all_trs = list(target.find_all("tr"))
    main_tr_indices = {}
    for lane, tr in main_rows:
        try: main_tr_indices[lane] = all_trs.index(tr)
        except ValueError: pass

    for lane, tr in main_rows:
        full_text = tr.get_text(" ", strip=True)
        full_text = re.sub(r"\s+", " ", full_text)
        
        a_tag = tr.find("a", href=re.compile(r"profile\?toban=\d+"))
        name = a_tag.get_text(strip=True).replace(" ", "").replace("　", "") if a_tag else f"選手{lane}"

        fl_match = re.search(r"F\s*(\d+)\s+L\s*(\d+)", full_text)
        f_count = int(fl_match.group(1)) if fl_match else 0

        avg_st = 0.17
        win_rate = 0.0
        motor_2rate = 0.0

        if fl_match:
            tail = full_text[fl_match.end():]
            nums = re.findall(r"-?\d+\.\d+|\d+", tail)
            try: avg_st = float(nums[0]) if "." in nums[0] else 0.17
            except: pass
            try: win_rate = float(nums[1])
            except: pass
            try:
                m2v = float(nums[8])
                motor_2rate = m2v / 100.0 if m2v > 1.0 else m2v
            except: pass

        settle_st = None
        settle_avg_rank = None
        idx = main_tr_indices.get(lane)
        if idx is not None and idx + 3 < len(all_trs):
            st_tr = all_trs[idx + 2]
            fn_tr = all_trs[idx + 3]

            def cells_text(t): return [td.get_text(strip=True) for td in t.find_all(["td", "th"])]

            st_cells = cells_text(st_tr)
            fn_cells = cells_text(fn_tr)

            st_vals = []
            for c in st_cells:
                if re.search(r"[FLK失]", c): continue
                if re.fullmatch(r"\.\d+", c):
                    try: st_vals.append(float("0" + c))
                    except: pass
                elif re.fullmatch(r"0\.\d+", c):
                    try: st_vals.append(float(c))
                    except: pass
            if st_vals: settle_st = round(sum(st_vals) / len(st_vals), 3)

            zen_to_han = str.maketrans("１２３４５６", "123456")
            ranks = []
            for c in fn_cells:
                c_norm = c.translate(zen_to_han)
                if re.fullmatch(r"[1-6]", c_norm): ranks.append(int(c_norm))
            if ranks: settle_avg_rank = round(sum(ranks) / len(ranks), 2)

        racers.append(Racer(
            name=name,
            win_rate=win_rate,
            avg_st=avg_st,
            settle_st=settle_st,
            settle_avg_rank=settle_avg_rank,
            motor_2rate=motor_2rate,
            f_count=f_count
        ))

    return racers

@st.cache_data(ttl=3600)
def fetch_result_and_payoff(jcd: int, rno: int, dstr: str) -> Tuple[Dict[int, str], str, int]:
    html = get_html(f"{BOAT_URL}/raceresult?rno={rno}&jcd={jcd:02d}&hd={dstr}")
    if not html or "まだ結果がありません" in html or "発売中" in html:
        return {}, "", 0
        
    soup = BeautifulSoup(html, "html.parser")
    lane_to_rank = {}
    
    for tbody in soup.select("div.table1 table tbody"):
        for tr in tbody.find_all("tr"):
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(tds) >= 2:
                r_str = tds[0].translate(str.maketrans('１２３４５６７８９０', '1234567890'))
                l_str = tds[1].translate(str.maketrans('１２３４５６７８９０', '1234567890'))
                if l_str.isdigit() and int(l_str) not in lane_to_rank:
                    lane_to_rank[int(l_str)] = r_str

    win_combo = ""
    payoff = 0
    for tr in soup.find_all("tr"):
        row_text = tr.get_text(strip=True)
        if "3連単" in row_text or "３連単" in row_text:
            cells = tr.find_all("td")
            if len(cells) >= 2:
                for td in cells:
                    txt = td.get_text(strip=True).replace(",", "").replace("¥", "").replace("円", "")
                    if txt.isdigit():
                        payoff = int(txt)
                        break
            if payoff > 0:
                break
                
    try:
        r1 = next((k for k, v in lane_to_rank.items() if v == "1"), None)
        r2 = next((k for k, v in lane_to_rank.items() if v == "2"), None)
        r3 = next((k for k, v in lane_to_rank.items() if v == "3"), None)
        if r1 and r2 and r3:
            win_combo = f"{r1}-{r2}-{r3}"
    except:
        pass
        
    return lane_to_rank, win_combo, payoff

# ============================================================
# メインUI
# ============================================================
st.set_page_config(page_title="v17.14 超・爆速解析", layout="wide")
st.title("🚤 v17.14 全艇スコア解析")
st.caption("AI一本化 ＆ フルデータ開示 ＆ 超・爆速15並列エンジン搭載")

tab1, tab2 = st.tabs(["🔍 1レース解析", "📊 バックテスト"])

# ----------------------------------------------------
# タブ1: 1レース解析
# ----------------------------------------------------
with tab1:
    st.subheader("🔍 1レース解析")
    col1, col2 = st.columns(2)
    with col1:
        d_input = st.date_input("日付", value=datetime.now(JST).date())
    with col2:
        v_idx = st.selectbox("場", options=list(JCD_NAME.keys()), format_func=lambda x: JCD_NAME[x])
        
    r_idx = st.selectbox("レース", options=list(range(1, 13)))
    
    if st.button("🔍 解析開始", type="primary", use_container_width=True):
        dstr = d_input.strftime("%Y%m%d")
        racers = fetch_race_detail(v_idx, r_idx, dstr)
        if racers:
            venue_name = JCD_NAME[v_idx]
            ranked = rank_all(racers, venue_name)
            
            st.success("解析完了！")
            
            df_disp = []
            for item in ranked:
                racer = item["racer"]
                bd = item["breakdown"]
                
                df_disp.append({
                    "予想順": len(df_disp) + 1,
                    "枠": item["lane"],
                    "選手名": racer.name,
                    "総合スコア": item["score"],
                    
                    "AI加点": bd.get("AI加点", 0.0),
                    
                    "勝率": round(racer.win_rate, 2) if racer.win_rate else 0.0,
                    "平均ST": round(racer.avg_st, 2) if racer.avg_st else 0.0,
                    "モーター": round(racer.motor_2rate, 2) if racer.motor_2rate else 0.0,
                    "節平均順位": round(racer.settle_avg_rank, 2) if racer.settle_avg_rank else "-",
                    "節平均ST": round(racer.settle_st, 2) if racer.settle_st else "-",
                    "F数": racer.f_count,
                    
                    "節平順(点)": bd.get("節平順", 0.0),
                    "ST改善(点)": bd.get("節ST改善", 0.0),
                    "F持ち(点)": bd.get("F持ち", 0.0),
                    "場×コース(点)": bd.get("場×コース", 0.0),
                    "場×攻め(点)": bd.get("場×攻め", 0.0)
                })
            
            st.dataframe(pd.DataFrame(df_disp), use_container_width=True)
            
            st.subheader("💡 おすすめ買い目")
            bets_safe = make_bets(ranked, "safe")
            bets_std = make_bets(ranked, "standard")
            bets_wide = make_bets(ranked, "wide")
            st.write(f"**安全2点**: {', '.join(bets_safe) if bets_safe else 'なし'}")
            st.write(f"**標準4点**: {', '.join(bets_std) if bets_std else 'なし'}")
            st.write(f"**拡張9点**: {', '.join(bets_wide) if bets_wide else 'なし'}")
        else:
            st.error("出走表が取得できませんでした。")

# ----------------------------------------------------
# タブ2: バックテスト（超・爆速版）
# ----------------------------------------------------
with tab2:
    st.subheader("📊 期間バックテスト（超・爆速仕様）")
    
    col1, col2 = st.columns(2)
    with col1:
        bt_start = st.date_input("開始日 ", value=datetime.now(JST).date() - timedelta(days=2))
    with col2:
        bt_end = st.date_input("終了日 ", value=datetime.now(JST).date() - timedelta(days=1))
        
    bt_venue_idx = st.selectbox("場を指定", options=[0] + list(JCD_NAME.keys()), format_func=lambda x: "全国（すべて）" if x==0 else JCD_NAME[x])
    bt_strategy = st.radio("買い目戦略", options=["safe", "standard", "wide"], format_func=strategy_label, horizontal=True)

    if st.button("📊 バックテスト実行", type="primary", use_container_width=True):
        days = [(bt_start + timedelta(days=i)).strftime("%Y%m%d") for i in range((bt_end - bt_start).days + 1)]
        matches = []
        prog = st.progress(0.0)
        
        tasks = []
        for dstr in days:
            jcds = boatrace_venues(dstr)
            if bt_venue_idx != 0:
                jcds = [bt_venue_idx] if bt_venue_idx in jcds else []
            for j in jcds:
                for r in range(1, 13):
                    tasks.append((dstr, j, r))
                    
        st.write(f"全 {len(tasks)} レースを15並列で一気に解析中...")
        
        def analyze_race(d, j, r):
            racers = fetch_race_detail(j, r, d)
            if not racers: return None
            
            ranks, actual_result, payoff = fetch_result_and_payoff(j, r, d)
            if not actual_result: return None 
            
            venue_name = JCD_NAME.get(j, "不明")
            ranked = rank_all(racers, venue_name)
            bets = make_bets(ranked, strategy=bt_strategy)
            
            hit = actual_result in bets
            top_score = ranked[0]["score"]
            ai_score = ranked[0]["breakdown"].get("AI加点", 0.0)
            
            return {
                "日付": d,
                "場": venue_name,
                "R": r,
                "買い目": ", ".join(bets),
                "点数": len(bets),
                "結果": actual_result,
                "的中": "🎯" if hit else "❌",
                "払戻金": payoff, 
                "獲得金": payoff if hit else 0, 
                "スコア": top_score,
                "AI加点": ai_score
            }
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            future_to_task = {executor.submit(analyze_race, d, j, r): (d, j, r) for d, j, r in tasks}
            done_count = 0
            for future in concurrent.futures.as_completed(future_to_task):
                done_count += 1
                prog.progress(done_count / len(tasks) if len(tasks) > 0 else 1.0)
                res = future.result()
                if res:
                    matches.append(res)
                    
        if matches:
            df_bt = pd.DataFrame(matches)
            hits = df_bt[df_bt["的中"] == "🎯"]
            
            total_invest = df_bt["点数"].sum() * 100
            total_return = df_bt["獲得金"].sum()
            hit_rate = len(hits) / len(df_bt) * 100 if len(df_bt) > 0 else 0
            ret_rate = total_return / total_invest * 100 if total_invest > 0 else 0
            
            st.success(f"解析完了！ 対象レース: {len(df_bt)}件 / 的中: {len(hits)}件 (的中率 {hit_rate:.1f}%)")
            st.info(f"💰 **総投資**: {total_invest:,}円 / **総回収**: {total_return:,}円 (回収率: {ret_rate:.1f}%)")
            
            disp_cols = ["日付", "場", "R", "買い目", "結果", "的中", "払戻金", "スコア", "AI加点"]
            st.dataframe(df_bt[disp_cols], use_container_width=True)
        else:
            st.warning("解析できるレースがありませんでした（中止または発売前）。")
