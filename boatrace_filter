"""
ボートレース 全国勝率フィルター

uchisankaku.sakura.ne.jp の出走表を解析し、
全国勝率が「1号艇 > 2号艇」の順で、かつ両方とも
そのレースの全国勝率上位3位以内に入っているレースを抽出する。

出走時刻は boatrace.jp 公式サイトから取得。

使い方:
  pip install requests beautifulsoup4
  python boatrace_filter.py              # 今日
  python boatrace_filter.py 20260410     # 日付指定
"""

import sys
import re
import time as _time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from datetime import datetime

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


# ──────────────── 会場一覧取得 ────────────────
def get_venues(date_str: str) -> list[dict]:
    """raceindex.php から開催中の会場リンクを収集"""
    url = f"{BASE_URL}/raceindex.php?date={date_str}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    venues = []
    seen = set()
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


# ──────────────── 出走時刻取得 (boatrace.jp) ────────────────
def fetch_race_times(jcd: str, date_str: str) -> dict[int, str]:
    """
    boatrace.jp の番組表ページから各レースの締切予定時刻を取得。
    戻り値: {1: "10:30", 2: "11:02", ...}
    """
    race_times: dict[int, str] = {}
    try:
        url = f"{BOATRACE_URL}/owpc/pc/race/raceindex?jcd={jcd}&hd={date_str}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 方法1: レースリンクの行から時刻を抽出
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

        # 方法2: ページ全体から "NR HH:MM" パターン
        if not race_times:
            full = soup.get_text(" ", strip=True)
            for m in re.finditer(r"(\d{1,2})\s*R\s+(\d{1,2}:\d{2})", full):
                race_times[int(m.group(1))] = m.group(2)

        # 方法3: td を走査して NR → 時刻 のペアを探す
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

    except Exception as e:
        print(f"    ⚠ 時刻取得失敗 ({jcd}): {e}")

    return race_times


# ──────────────── 出走表解析 (uchisankaku) ────────────────
def parse_racelist(jcode: str, date_str: str, venue_name: str,
                   race_times: dict[int, str]) -> list[dict]:
    """racelist.php を解析し、各レースの全国勝率・選手名を返す"""
    url = f"{BASE_URL}/racelist.php?jcode={jcode}&date={date_str}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for h3 in soup.find_all("h3"):
        race_label = h3.get_text(strip=True)  # 例: "1R　 一般"

        # レース番号を抽出
        m = re.search(r"(\d{1,2})R", race_label)
        if not m:
            continue
        race_no = int(m.group(1))

        # 出走時刻
        race_time = race_times.get(race_no, "--:--")

        # 直後のテーブルを取得
        table = h3.find_next("table")
        if not table:
            continue

        names = {}
        win_rates = {}
        in_zenkoku = False

        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            texts = [c.get_text(strip=True) for c in cells]

            # 氏名行
            if "氏名" in texts:
                idx = texts.index("氏名")
                for i, n in enumerate(texts[idx + 1: idx + 7]):
                    if n:
                        names[i + 1] = n

            # 「全国」セクション開始
            if "全国" in texts:
                in_zenkoku = True

            # 「当地」セクション開始 → 全国を抜ける
            if "当地" in texts:
                in_zenkoku = False

            # 全国セクション内の最初の「勝率」行を取得
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
                "race_label": race_label,
                "race_no": race_no,
                "race_time": race_time,
                "win_rates": win_rates,
                "names": names,
            })

    return results


# ──────────────── 条件判定 ────────────────
def meets_condition(wr: dict[int, float]) -> bool:
    """
    条件:
      1) 1号艇の全国勝率 > 2号艇の全国勝率
      2) 1号艇・2号艇ともに6艇中の全国勝率 上位3位以内
    """
    if 1 not in wr or 2 not in wr:
        return False
    if wr[1] <= wr[2]:
        return False
    sorted_vals = sorted(wr.values(), reverse=True)
    top3_min = sorted_vals[2]  # 3位の値
    return wr[1] >= top3_min and wr[2] >= top3_min


# ──────────────── 結果表示 ────────────────
def print_race(race: dict):
    wr = race["win_rates"]
    sorted_boats = sorted(wr.items(), key=lambda x: x[1], reverse=True)

    print(f"  ┌───────────────────────────────────────────────")
    race_num = f"{race['race_no']}R"
    print(f"  │ 【{race['venue']}】 {race_num}   締切予定: {race['race_time']}")
    print(f"  │")
    print(f"  │   順位  枠番  選手名            全国勝率")
    print(f"  │  ──────────────────────────────────────────")
    for rank, (boat, rate) in enumerate(sorted_boats, 1):
        name = race["names"].get(boat, "---")
        mark = " ◀" if boat in (1, 2) else ""
        print(f"  │   {rank}位   {boat}号艇  {name:<12s}  {rate:.2f}{mark}")
    print(f"  └───────────────────────────────────────────────\n")


# ──────────────── メイン ────────────────
def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")

    disp_date = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}"
    print()
    print("=" * 52)
    print("  ボートレース 全国勝率フィルター")
    print(f"  対象日: {disp_date}")
    print("  条件 : 全国勝率 1号艇>2号艇 かつ両方とも上位3位以内")
    print("=" * 52)
    print()

    # 1) 会場一覧を取得
    venues = get_venues(date_str)
    if not venues:
        print("  開催中の会場がありません。")
        return

    print(f"  開催会場: {', '.join(v['name'] for v in venues)} ({len(venues)}場)")
    print()

    hit_list = []

    for v in venues:
        print(f"  ▶ {v['name']} を解析中...")

        # 2) boatrace.jp から出走時刻を取得
        race_times = fetch_race_times(v["jcd"], date_str)
        if race_times:
            print(f"    → 時刻取得OK ({len(race_times)}R分)")
        else:
            print(f"    → 時刻取得できず (--:-- で表示)")
        _time.sleep(0.5)

        # 3) uchisankaku から出走表を解析
        try:
            races = parse_racelist(v["jcode"], date_str, v["name"], race_times)
            print(f"    → {len(races)} レース取得")
        except Exception as e:
            print(f"    ✗ エラー: {e}")
            continue

        # 4) 条件に合うレースを抽出
        venue_hits = 0
        for race in races:
            if meets_condition(race["win_rates"]):
                hit_list.append(race)
                venue_hits += 1

        if venue_hits:
            print(f"    ★ 該当 {venue_hits} レース")
        print()
        _time.sleep(0.5)

    # ──── 結果出力 ────
    print("=" * 52)
    print(f"  ★ 該当レース合計: {len(hit_list)} 件")
    print("=" * 52)
    print()

    if not hit_list:
        print("  条件に合致するレースはありませんでした。")
        return

    # 出走時刻順にソート ("--:--" は末尾へ)
    hit_list.sort(key=lambda r: r["race_time"] if r["race_time"] != "--:--" else "99:99")

    for race in hit_list:
        print_race(race)

    # サマリーテーブル
    print("── サマリー ─────────────────────────────────────")
    print(f"  {'会場':<6s}  {'レース':<6s}  {'時刻':<6s}  "
          f"{'1号艇勝率':>9s}  {'2号艇勝率':>9s}")
    print("  " + "-" * 46)
    for r in hit_list:
        wr = r["win_rates"]
        race_num = f"{r['race_no']}R"
        print(f"  {r['venue']:<6s}  {race_num:<6s}  "
              f"{r['race_time']:<6s}  {wr[1]:>8.2f}   {wr[2]:>8.2f}")
    print()


if __name__ == "__main__":
    main()
