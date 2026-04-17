"""
🚤 ボートレース予想アプリ v15.1 (荒れレース・ハンター / 本物の荒れだけに絞る)
━━━━━━━━━━━━━━━━━━━━━━━━
データソース: uchisankaku.sakura.ne.jp（コース別・節間・全選手データ・決まり手）
             boatrace.jp（開催場一覧・直前情報・レース結果）

v15.0 → v15.1 変更点:
  【問題】1週間434件抽出、的中率21.4%、回収率66.2%
         → 抽出多すぎ & ガチガチ決着（1-2-3系）を拾いすぎて配当が低い

  【改善】以下の追加条件で「本物の荒れ」だけに絞る:
   ★ 上位3艇に 5号艇 or 6号艇 を含む、OR 1号艇が上位3艇圏外
     → これで「1-2-3決着」系の低配当レースを除外
   ・スコア差閾値 3.0 → 2.5 (より厳密な混戦)
   ・A級2艇以上 → 3艇以上 (強豪密度UP)
   ・平均勝率 4.5 → 5.0 (低レベル混戦を除外)
"""
import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import itertools
from datetime import date, timedelta
import time

VENUES = {
    "01":"桐生","02":"戸田","03":"江戸川","04":"平和島","05":"多摩川",
    "06":"浜名湖","07":"蒲郡","08":"常滑","09":"津","10":"三国",
    "11":"びわこ","12":"住之江","13":"尼崎","14":"鳴門","15":"丸亀",
    "16":"児島","17":"宮島","18":"徳山","19":"下関","20":"若松",
    "21":"芦屋","22":"福岡","23":"唐津","24":"大村",
}

EXCLUDED_VENUES = {"18", "24", "21"}  # 徳山、大村、芦屋

UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"}

@st.cache_data(ttl=180)
def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.encoding = "utf-8"
        return r.text
    except:
        return ""

def get_active_venues(ds):
    hd=ds.replace("-","")
    try:
        soup=BeautifulSoup(fetch(f"https://www.boatrace.jp/owpc/pc/race/index?hd={hd}"),"html.parser")
        seen,out=set(),[]
        for a in soup.find_all("a",href=True):
            if "raceindex" in a["href"] and f"hd={hd}" in a["href"]:
                m=re.search(r"jcd=(\d{2})",a["href"])
                if m and m.group(1) in VENUES and m.group(1) not in seen:
                    j=m.group(1); seen.add(j)
                    out.append({"jcd":j,"name":VENUES[j]})
        return out
    except: return []

def get_race_times(jcd,ds):
    hd=ds.replace("-",""); times={}
    try:
        text=BeautifulSoup(fetch(f"https://www.boatrace.jp/owpc/pc/race/raceindex?jcd={jcd}&hd={hd}"),"html.parser").get_text()
        v=[]
        for t in re.findall(r'(\d{1,2}:\d{2})',text):
            if 8<=int(t.split(":")[0])<=21 and t not in v: v.append(t)
        for i,t in enumerate(v[:12]): times[i+1]=t
    except: pass
    return times

def get_official_result(jcd, ds, rno):
    hd = ds.replace("-", "")
    url = f"https://www.boatrace.jp/owpc/pc/race/raceresult?rno={rno}&jcd={jcd}&hd={hd}"
    try:
        html = fetch(url)
        if "3連単" not in html: return None
        soup = BeautifulSoup(html, "html.parser")
        sanrentan = ""
        ranks = []
        payout_val = 0
        for tr in soup.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) >= 3:
                header = tds[0].get_text(strip=True)
                if "3連単" in header:
                    combo = tds[1].get_text(strip=True) 
                    payout_str = tds[2].get_text(strip=True) 
                    sanrentan = f"{combo}  {payout_str}"
                    if "円" not in sanrentan: sanrentan += "円"
                    m_combo = re.findall(r'([1-6])', combo)
                    if len(m_combo) >= 3: ranks = [int(x) for x in m_combo[:3]]
                    m_payout = re.sub(r'[^\d]', '', payout_str)
                    if m_payout: payout_val = int(m_payout)
                    break
        if sanrentan and ranks: 
            return {"sanrentan": sanrentan, "ranks": ranks, "payout": payout_val}
    except: pass
    return None

@st.cache_data(ttl=120)
def get_uchi_data(jcd, ds):
    jcode = str(int(jcd)) 
    hd = ds.replace("-","")
    url = f"https://uchisankaku.sakura.ne.jp/racelist.php?jcode={jcode}&date={hd}"
    return fetch(url)

def parse_uchi_race(html, race_no):
    soup = BeautifulSoup(html, "html.parser")
    racers = []
    target_h3 = None
    for h3 in soup.find_all("h3"):
        if re.search(rf'{race_no}R', h3.get_text(strip=True)):
            target_h3 = h3
            break
    if not target_h3: return []
    tbl = target_h3.find_next("table")
    if not tbl: return []
    rows = tbl.find_all("tr")
    row_map = {}

    for tr in rows:
        cells = tr.find_all(["td","th"])
        texts = [c.get_text(strip=True) for c in cells]
        if len(texts) < 7: continue
        data6 = texts[-6:]
        label = ""
        for t in texts[:-6]:
            t = t.replace("　"," ").strip()
            if t and t not in ("選手情報","成績","コース別/直近６カ月","決り手","モーター","今節成績","","枠"):
                label = t
                break
        if not label and len(texts) > 7:
            for t in texts[:3]:
                t = t.strip()
                if t and t not in ("","選手情報","成績"):
                    label = t
                    break
        if label: row_map[label] = data6

    for i in range(6):
        r = {"course": i+1}
        def gv(label, idx=i):
            return row_map.get(label, ["","","","","",""])[idx].strip() if label in row_map else ""

        r["name"] = gv("氏名")
        r["class"] = gv("級別") or "B1"
        r["national_rate"] = 5.0
        
        f_s = gv("F数").replace("F", "")
        r["f_count"] = int(f_s) if f_s.isdigit() else 0
        
        in_national = False
        nat_rate = None
        for tr in rows:
            cells = tr.find_all(["td","th"])
            texts2 = [c.get_text(strip=True) for c in cells]
            joined = " ".join(texts2)
            if "全国" in joined: in_national = True
            elif "当地" in joined or "コース別" in joined: in_national = False
            if len(texts2) >= 7:
                data = texts2[-6:]
                label2 = " ".join(texts2[:-6]).strip()
                if "勝率" in label2:
                    val = data[i]
                    if re.match(r'^\d+\.\d+$', val):
                        if in_national and nat_rate is None: 
                            nat_rate = float(val)
        
        if nat_rate is not None:
            r["national_rate"] = nat_rate
        else:
            nr_s = gv("勝率")
            if re.match(r'^\d+\.\d+$', nr_s): r["national_rate"] = float(nr_s)

        in_motor = False
        motor_2ren = 33.0
        for tr in rows:
            cells = tr.find_all(["td","th"])
            texts2 = [c.get_text(strip=True) for c in cells]
            joined = " ".join(texts2)
            if "モーター" in joined or "ター" in joined: in_motor = True
            elif "今節成績" in joined: in_motor = False
            if in_motor and len(texts2) >= 7:
                data = texts2[-6:]
                label2 = " ".join(texts2[:-6]).strip()
                if "2連率" in label2:
                    val = data[i]
                    if re.match(r'^[\d.]+$', val) and float(val) > 0:
                        motor_2ren = float(val)
                        break
        r["motor_2ren"] = motor_2ren

        st_s = gv("ST")
        r["avg_st"] = float(st_s) if re.match(r'^0\.\d+$', st_s) else 0.15

        in_session = False
        session_st = 0.15
        for tr in rows:
            cells = tr.find_all(["td","th"])
            texts2 = [c.get_text(strip=True) for c in cells]
            joined = " ".join(texts2)
            if "今節成績" in joined: in_session = True
            elif in_session and len(texts2) >= 7:
                data = texts2[-6:]
                label2 = " ".join(texts2[:-6]).strip()
                val = data[i]
                if not val or val == "-": continue
                if "ST" in label2 and re.match(r'^[\d.]+$', val): 
                    session_st = float(val)
        r["session_st"] = session_st
        racers.append(r)
    return racers

# ━━━━━━━━━━━ v15.1 荒れレース検出 ━━━━━━━━━━━

COURSE_BOOST = {1: 3.0, 2: 1.5, 3: 1.0, 4: 0.5, 5: 0.0, 6: -0.5}
CLASS_BOOST = {"A1": 2.0, "A2": 1.0, "B1": 0.0, "B2": -1.0}

def get_eff_st(r):
    s = r.get("session_st", 0)
    return s if (s > 0 and s != 0.15) else r.get("avg_st", 0.15)

def calculate_boat_score(r):
    course = r["course"]
    nr = r.get("national_rate", 5.0)
    st = get_eff_st(r)
    motor = r.get("motor_2ren", 33.0)
    cl = r.get("class", "B1")
    f_count = r.get("f_count", 0)
    
    score = 0.0
    score += nr * 1.0
    score += max(0, (0.20 - st) * 20)
    score += max(0, (motor - 33) * 0.05)
    score += CLASS_BOOST.get(cl, 0.0)
    score += COURSE_BOOST.get(course, 0.0)
    if f_count >= 2:
        score -= 2.0
    elif f_count == 1:
        score -= 1.0
    
    return round(score, 2)

def evaluate_chaos_race(racers, jcd):
    if jcd in EXCLUDED_VENUES:
        return None
    
    scored = [(r["course"], calculate_boat_score(r), r) for r in racers]
    scored_sorted = sorted(scored, key=lambda x: x[1], reverse=True)
    
    top3 = scored_sorted[:3]
    top3_courses = [c for c, _, _ in top3]
    top3_scores = [s for _, s, _ in top3]
    
    # ━━━ 厳格な混戦条件 v15.1 ━━━
    
    # 1. 上位3艇のスコア差 ≤ 2.5 (v15.0: 3.0)
    score_spread = top3_scores[0] - top3_scores[2]
    if score_spread > 2.5:
        return None
    
    # 2. A1/A2が3艇以上 (v15.0: 2艇)
    classes = [r.get("class", "B1") for r in racers]
    a_count = sum(1 for c in classes if c in ["A1", "A2"])
    if a_count < 3:
        return None
    
    # 3. 平均勝率 ≥ 5.0 (v15.0: 4.5)
    avg_rate = sum(r.get("national_rate", 5.0) for r in racers) / 6
    if avg_rate < 5.0:
        return None
    
    # ★ 4. 本物の荒れ条件（v15.1 新規）:
    #    上位3艇に 5号艇 or 6号艇 を含む、OR 1号艇が上位3艇圏外
    has_outside = (5 in top3_courses) or (6 in top3_courses)
    no_inner_1 = (1 not in top3_courses)
    if not (has_outside or no_inner_1):
        return None  # 1-2-3系のガチガチ決着は除外
    
    # 5. 1号艇が圧倒的でない（既存条件、維持）
    if top3_courses[0] == 1 and (top3_scores[0] - top3_scores[1]) > 2.0:
        return None
    
    # 荒れスコア（高いほど狙い目）
    chaos_score = (
        (2.5 - score_spread)
        + a_count * 0.5
        + (avg_rate - 5.0)
    )
    # 5or6絡み or 1C圏外 には追加ボーナス
    if has_outside:
        chaos_score += 1.0
    if no_inner_1:
        chaos_score += 1.5
    
    # 上位3艇の3連単BOX
    top3_sorted_nums = sorted(top3_courses)
    buy_patterns = [list(p) for p in itertools.permutations(top3_sorted_nums, 3)]
    pred_str = f"{top3_sorted_nums[0]}={top3_sorted_nums[1]}={top3_sorted_nums[2]} 3連単BOX (6点)"
    sanrenpuku_str = f"{top3_sorted_nums[0]}={top3_sorted_nums[1]}={top3_sorted_nums[2]} (1点)"
    
    stars = "★★★" if chaos_score >= 4.0 else "★★☆" if chaos_score >= 2.5 else "★☆☆"
    
    reasons = [
        f"A級{a_count}艇",
        f"上位差{score_spread:.1f}",
        f"平均{avg_rate:.1f}",
    ]
    if no_inner_1:
        reasons.append("1C圏外★")
    elif has_outside:
        reasons.append("5/6C絡み★")
    
    all_scores = sorted(scored, key=lambda x: x[0])
    score_info = " ".join(f"{c}C({s:.1f})" for c, s, _ in all_scores)
    
    return {
        "top3_courses": top3_sorted_nums,
        "score": round(chaos_score, 2),
        "stars": stars,
        "reasons": reasons,
        "score_info": score_info,
        "pw_info": " ".join(f"{r['course']}C({r.get('national_rate',5.0):.1f}{r.get('class','B1')})" for r in racers),
        "pred_str": pred_str,
        "sanrenpuku_str": sanrenpuku_str,
        "buy_patterns": buy_patterns,
    }

def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)

# ━━━━━━━━━━━ UI ━━━━━━━━━━━
def main():
    st.set_page_config(page_title="🚤 荒れレース・ハンター v15.1",page_icon="🌊",layout="wide",initial_sidebar_state="collapsed")
    st.markdown("""<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700;900&display=swap');
    .stApp{background:linear-gradient(135deg,#0a0a1a,#0d1b2a 40%,#1b2838);font-family:'Noto Sans JP',sans-serif}
    .hdr{background:linear-gradient(90deg,#1B6DB5,#0D47A1);padding:16px 24px;border-radius:12px;display:flex;align-items:center;gap:14px;box-shadow:0 4px 20px rgba(27,109,181,0.35);margin-bottom:16px}
    .hdr h1{color:#FFF!important;font-size:22px!important;font-weight:900!important;letter-spacing:3px;margin:0!important;padding:0!important}
    .hdr .sub{color:#BBDEFB;font-size:11px;letter-spacing:1px}
    .card{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:16px;margin-bottom:12px}
    .sl{font-size:12px;font-weight:700;color:#1B6DB5;letter-spacing:2px;margin-bottom:8px}
    </style>""",unsafe_allow_html=True)
    
    st.markdown('<div class="hdr"><span style="font-size:32px">🌊</span><div><h1>BOAT RACE AI</h1><div class="sub">v15.1 ─ 本物の荒れレースのみ（5/6C絡み or 1C圏外）</div></div></div>',unsafe_allow_html=True)

    st.markdown('<div class="card"><div class="sl">STEP 1 ─ 対象期間（最大31日）</div>',unsafe_allow_html=True)
    sel_dates = st.date_input("対象期間", value=(date.today(), date.today()), label_visibility="collapsed")
    
    if isinstance(sel_dates, tuple):
        if len(sel_dates) == 2:
            s_date, e_date = sel_dates
        elif len(sel_dates) == 1:
            s_date = e_date = sel_dates[0]
        else:
            s_date = e_date = date.today()
    else:
        s_date = e_date = sel_dates
        
    st.markdown('</div>',unsafe_allow_html=True)

    if st.button(f"🌊 指定期間をまとめて解析（荒れハンター v15.1）", type="primary", use_container_width=True):
        date_list = list(daterange(s_date, e_date))
        total_days = len(date_list)
        
        if total_days > 31:
            st.error("⚠️ 検索期間が長すぎます。サーバー負荷を防ぐため、31日以内で指定してください。")
            return

        with st.spinner(f"対象期間（計{total_days}日分）のレースを解析中..."):
            matches = []
            invested = 0
            returned = 0
            finished_count = 0
            
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, current_date in enumerate(date_list):
                ds = current_date.strftime("%Y-%m-%d")
                status_text.text(f"🔍 解析中: {ds} ({i+1}/{total_days}日目)")
                
                venues = get_active_venues(ds)
                if not venues:
                    progress_bar.progress((i + 1) / total_days)
                    continue

                for v in venues:
                    jcd = v["jcd"]
                    html = get_uchi_data(jcd, ds)
                    if not html: continue
                    rtimes = get_race_times(jcd, ds)

                    for rno in range(1, 13):
                        racers = parse_uchi_race(html, rno)
                        if len(racers) < 6: continue

                        ev = evaluate_chaos_race(racers, jcd)
                        if not ev: continue
                        
                        race_info = {
                            "date": ds,
                            "jcd": jcd, "name": v["name"], "rno": rno,
                            "time": rtimes.get(rno, "--:--"),
                            "top3_courses": ev["top3_courses"],
                            "pred_str": ev["pred_str"],
                            "sanrenpuku_str": ev["sanrenpuku_str"],
                            "buy_patterns": ev["buy_patterns"],
                            "score_info": ev["score_info"],
                            "pw_info": ev["pw_info"],
                            "score": ev["score"],
                            "stars": ev["stars"],
                            "reasons": ev["reasons"],
                            "is_finished": False,
                            "hit": False,
                            "result_str": "未確定",
                            "payout": 0,
                        }

                        res = get_official_result(jcd, ds, rno)
                        if res and res.get("ranks"):
                            race_info["is_finished"] = True
                            race_info["result_str"] = res["sanrentan"]
                            finished_count += 1
                            invested += len(race_info["buy_patterns"]) * 100

                            if res["ranks"] in race_info["buy_patterns"]:
                                race_info["hit"] = True
                                race_info["payout"] = res["payout"]
                                race_info["result_str"] = f"🎯 {res['sanrentan']}"
                                returned += res["payout"]

                        matches.append(race_info)
                        
                progress_bar.progress((i + 1) / total_days)
                
            status_text.text(f"✅ 解析完了（計{total_days}日分）")
            time.sleep(1)
            status_text.empty()
            progress_bar.empty()

            matches.sort(key=lambda x: x["score"], reverse=True)

            st.session_state["search_matches"] = matches
            st.session_state["search_invested"] = invested
            st.session_state["search_returned"] = returned
            st.session_state["search_finished"] = finished_count
            st.session_state["search_done"] = True

    if st.session_state.get("search_done"):
        matches = st.session_state.get("search_matches", [])
        inv = st.session_state.get("search_invested", 0)
        ret = st.session_state.get("search_returned", 0)
        fin = st.session_state.get("search_finished", 0)
        roi = (ret / inv * 100) if inv > 0 else 0
        
        hit_count = sum(1 for m in matches if m["hit"])
        hit_rate = (hit_count / fin * 100) if fin > 0 else 0
        avg_payout = (ret / hit_count) if hit_count > 0 else 0

        st.markdown('<div style="background:rgba(27, 109, 181, 0.1); padding:16px; border-radius:12px; border:1px solid #1B6DB5; margin-bottom:16px;">', unsafe_allow_html=True)
        date_range_str = f"{s_date.strftime('%m/%d')} 〜 {e_date.strftime('%m/%d')}" if s_date != e_date else f"{s_date.strftime('%m/%d')}"
        st.markdown(f"<h3 style='margin-bottom:4px;'>🌊 荒れレース一覧 ({date_range_str}): 計 {len(matches)} 件</h3>", unsafe_allow_html=True)
        
        roi_color = "#2D8C3C" if roi >= 100 else "#F5C518" if roi >= 80 else "#E8212A"
        hit_color = "#2D8C3C" if hit_rate >= 20 else "#F5C518" if hit_rate >= 15 else "#E8212A"

        dash_html = (
            f"<div style='display:flex; justify-content:space-around; background:rgba(0,0,0,0.3); padding:16px; border-radius:8px; margin-top:12px; margin-bottom:20px; border:1px solid rgba(255,255,255,0.1); flex-wrap:wrap; gap:8px;'>"
            f"<div style='text-align:center;'><span style='font-size:12px;color:#aaa;'>終了</span><br><span style='font-size:20px;font-weight:bold;'>{fin}<span style='font-size:13px;'>件</span></span></div>"
            f"<div style='text-align:center;'><span style='font-size:12px;color:#aaa;'>的中</span><br><span style='font-size:20px;font-weight:bold;color:{hit_color};'>{hit_count}<span style='font-size:13px;'>件 ({hit_rate:.1f}%)</span></span></div>"
            f"<div style='text-align:center;'><span style='font-size:12px;color:#aaa;'>平均配当</span><br><span style='font-size:20px;font-weight:bold;color:#F5C518;'>{int(avg_payout):,}<span style='font-size:13px;'>円</span></span></div>"
            f"<div style='text-align:center;'><span style='font-size:12px;color:#aaa;'>投資</span><br><span style='font-size:20px;font-weight:bold;'>{inv:,}<span style='font-size:13px;'>円</span></span></div>"
            f"<div style='text-align:center;'><span style='font-size:12px;color:#aaa;'>払戻</span><br><span style='font-size:20px;font-weight:bold;color:{roi_color};'>{ret:,}<span style='font-size:13px;'>円</span></span></div>"
            f"<div style='text-align:center;'><span style='font-size:12px;color:#aaa;'>回収率</span><br><span style='font-size:22px;font-weight:900;color:{roi_color};'>{roi:.1f}<span style='font-size:15px;'>%</span></span></div>"
            f"</div>"
        )
        st.markdown(dash_html, unsafe_allow_html=True)

        if matches:
            for m in matches:
                bg_color = "rgba(45, 140, 60, 0.2)" if m["hit"] else "rgba(255,255,255,0.03)"
                border_s = "border:1px solid #2D8C3C;" if m["hit"] else "border:1px solid rgba(255,255,255,0.1);"
                hit_badge = "<span style='background:#2D8C3C; color:#fff; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold;'>的中🎯</span>" if m["hit"] else ""
                miss_badge = ""
                if m["is_finished"] and not m["hit"]:
                    miss_badge = "<span style='background:#E8212A; color:#fff; padding:2px 6px; border-radius:4px; font-size:11px;'>不的中</span>"

                sc_color = "#F5C518" if m["score"] >= 4.0 else "#1B6DB5"

                reason_tags = " ".join(
                    f"<span style='background:rgba(255,255,255,0.08);padding:1px 6px;border-radius:3px;font-size:11px;color:#ccc;margin-right:4px;'>{r}</span>"
                    for r in m["reasons"]
                )

                top3 = m["top3_courses"]
                top3_badge = f"<span style='background:#1B6DB5;color:#fff; padding:3px 8px; border-radius:4px; font-weight:bold; font-size:13px; margin-right:8px;'>{'='.join(map(str,top3))} BOX</span>"
                
                race_date_str = m['date'][5:].replace("-", "/")

                card_html = (
                    f"<div style='background:{bg_color}; padding:12px 16px; border-radius:8px; {border_s} margin-bottom:10px;'>"
                    f"<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;'>"
                    f"<div>{top3_badge}<span style='color:#1B6DB5;font-weight:bold;font-size:16px;'>[{race_date_str}] {m['name']} {m['rno']}R</span>"
                    f"<span style='color:#ccc; font-size:13px; margin-left:8px;'>🕒 {m['time']}</span></div>"
                    f"<div style='display:flex;align-items:center;gap:8px;'>"
                    f"<span style='color:{sc_color};font-weight:900;font-size:18px;'>{m['stars']}</span>"
                    f"{hit_badge}{miss_badge}</div></div>"
                    f"<div style='font-size:11px; color:#888; margin-bottom:2px;'>Score: {m['score_info']}</div>"
                    f"<div style='font-size:11px; color:#888; margin-bottom:4px;'>勝率: {m['pw_info']}</div>"
                    f"<div style='margin-bottom:6px;'>{reason_tags}</div>"
                    f"<div style='display:flex; justify-content:space-between; align-items:center; font-size:15px; padding-top:4px; border-top:1px dashed rgba(255,255,255,0.1);'>"
                    f"<div style='color:#F5C518;'><span style='font-size:12px; color:#aaa;'>買い目:</span> "
                    f"<span style='font-weight:900; font-size:15px; letter-spacing:1px;'>{m['pred_str']}</span></div>"
                    f"<div style='text-align:right;'><span style='font-size:12px; color:#aaa;'>結果:</span> "
                    f"<span style='font-weight:bold;'>{m['result_str']}</span></div>"
                    f"</div></div>"
                )
                st.markdown(card_html, unsafe_allow_html=True)
        else:
            st.warning("指定された期間に条件に合致するレースはありませんでした。")

        if st.button("✖ 検索結果を閉じる", key="close_search"):
            st.session_state["search_done"] = False
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

if __name__=="__main__":
    main()
