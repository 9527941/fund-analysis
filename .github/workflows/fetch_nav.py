#!/usr/bin/env python3
"""
从东方财富历史净值API（主）+ 天天基金JSONP（辅）获取最新净值数据
更新 data/fund-nav.json + index.html HISTORY_RAW + fund-report.html HISTORY_RAW/EMBEDDED_NAV

核心策略：
- 东方财富历史净值API → 获取 dwjz/jzrq（确认净值），最可靠
- 天天基金JSONP → 仅补充 gsz/gszzl/gztime（实时估值），从GitHub Actions可能拿不到最新
- 只有实际数据变化时才 commit（避免无意义写入）
"""
import json
import re
import urllib.request
from datetime import datetime, timedelta

FUND_CODES = ["013841", "002164", "012630", "004937", "024246", "001423", "016020", "016186"]
HISTORY_API = "https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize={size}&startDate={start}&endDate={end}"
JSONP_URL = "https://fundgz.1234567.com.cn/js/{code}.js?rt={timestamp}"
OUTPUT_NAV_FILE = "data/fund-nav.json"
HTML_FILE = "index.html"
REPORT_FILE = "fund-report.html"


def fetch_history_nav(code, start_date, end_date, size=40):
    """从东方财富API获取指定日期范围的历史净值（主数据源，最可靠）"""
    url = HISTORY_API.format(code=code, size=size, start=start_date, end=end_date)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://fund.eastmoney.com/"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        items = data.get("Data", {}).get("LSJZList", [])
        results = []
        for item in items:
            results.append({
                "date": item["FSRQ"],
                "nav": float(item["DWJZ"]),
                "ljjz": float(item.get("LJJZ", item["DWJZ"]))
            })
        return results
    except Exception as e:
        print(f"  [ERROR] {code}: history fetch failed: {e}")
        return []


def fetch_jsonp(code):
    """从天天基金JSONP接口获取实时估值数据（辅助数据源，可能返回旧数据）"""
    url = JSONP_URL.format(code=code, timestamp=int(datetime.now().timestamp() * 1000))
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        text = None
        for enc in ["utf-8", "gbk", "gb2312"]:
            try:
                text = raw.decode(enc)
                if "jsonpgz" in text:
                    break
            except (UnicodeDecodeError, LookupError):
                continue
        if not text or "jsonpgz" not in text:
            return None
        start = text.index("(") + 1
        end = text.rindex(")")
        data = json.loads(text[start:end])
        return {
            "name": data.get("name", ""),
            "code": data.get("fundcode", code),
            "gsz": float(data.get("gsz", 0)),
            "gszzl": float(data.get("gszzl", 0)),
            "dwjz": float(data.get("dwjz", 0)),
            "jzrq": data.get("jzrq", ""),
            "gztime": data.get("gztime", "")
        }
    except Exception as e:
        print(f"  [WARN] {code}: JSONP fetch failed: {e}")
        return None


def _do_update_history_raw(filepath, fund_codes):
    """更新指定文件中嵌入的 HISTORY_RAW 数据（通用逻辑）"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"  [SKIP] {filepath} not found")
        return False

    match = re.search(r'const HISTORY_RAW = (\{.*?\});', content, re.DOTALL)
    if not match:
        print(f"  [SKIP] HISTORY_RAW not found in {filepath}")
        return False

    history_data = json.loads(match.group(1))
    today = datetime.now()
    updated = False

    for code in fund_codes:
        arr = history_data["funds"].get(code, [])
        if not arr:
            continue

        existing_dates = {d["date"] for d in arr}
        latest_date = max(existing_dates)

        latest_dt = datetime.strptime(latest_date, "%Y-%m-%d")
        start_dt = latest_dt + timedelta(days=1)

        if start_dt > today:
            continue

        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = today.strftime("%Y-%m-%d")

        print(f"  Fetching history {code}: {start_str} ~ {end_str}")
        new_entries = fetch_history_nav(code, start_str, end_str)

        added = 0
        for entry in new_entries:
            if entry["date"] not in existing_dates:
                arr.append(entry)
                existing_dates.add(entry["date"])
                added += 1

        arr.sort(key=lambda x: x["date"], reverse=True)
        history_data["funds"][code] = arr

        if added > 0:
            updated = True
            print(f"    Added {added} entries for {code}")
        else:
            print(f"    No new entries for {code}")

    if updated:
        new_json = json.dumps(history_data, ensure_ascii=False, separators=(",", ":"))
        old_text = "const HISTORY_RAW = " + match.group(1) + ";"
        new_text = "const HISTORY_RAW = " + new_json + ";"
        content = content.replace(old_text, new_text)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  {filepath} HISTORY_RAW updated")

    return updated


def main():
    # 1. 加载现有缓存
    try:
        with open(OUTPUT_NAV_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {"funds": {}, "updated": ""}

    old_funds = cache.get("funds", {})
    new_funds = {}
    today = datetime.now().strftime("%Y-%m-%d")
    today_dt = datetime.now()

    print(f"=== Fund NAV Update: {today} ===")
    print(f"Strategy: History API (primary for dwjz/jzrq) + JSONP (supplement for gsz/gszzl)")

    # 2. 从东方财富历史API获取最新确认净值（主数据源）
    print(f"\n--- Step 1: Fetch confirmed NAV from Eastmoney History API ---")
    start = (today_dt - timedelta(days=10)).strftime("%Y-%m-%d")
    end = today

    confirmed_nav = {}  # code -> {dwjz, jzrq, ljjz}
    for code in FUND_CODES:
        entries = fetch_history_nav(code, start, end, size=10)
        if entries:
            latest = entries[0]  # 最新在前
            confirmed_nav[code] = {
                "dwjz": latest["nav"],
                "jzrq": latest["date"],
                "ljjz": latest.get("ljjz", latest["nav"])
            }
            print(f"  {code}: confirmed jzrq={latest['date']} dwjz={latest['nav']}")
        else:
            print(f"  {code}: FAILED to get confirmed NAV")

    # 3. 从JSONP获取实时估值（辅助数据源）
    print(f"\n--- Step 2: Fetch real-time estimate from JSONP (supplementary) ---")
    jsonp_data = {}
    for code in FUND_CODES:
        data = fetch_jsonp(code)
        if data:
            jsonp_data[code] = data
            print(f"  {code}: JSONP jzrq={data['jzrq']} gsz={data['gsz']} gszzl={data['gszzl']}% gztime={data['gztime']}")
        else:
            print(f"  {code}: JSONP failed (will use confirmed data only)")

    # 4. 合并数据：confirmed NAV (主) + JSONP estimate (辅)
    print(f"\n--- Step 3: Merge data (confirmed NAV as primary) ---")
    for code in FUND_CODES:
        confirmed = confirmed_nav.get(code)
        jsonp = jsonp_data.get(code)

        if confirmed and jsonp:
            # 两者都有：用confirmed的dwjz/jzrq，用jsonp的gsz/gszzl/gztime
            # 但如果jsonp的jzrq更新（理论上不会，但以防万一）
            name = jsonp.get("name", old_funds.get(code, {}).get("name", ""))
            jzrq = confirmed["jzrq"]
            dwjz = confirmed["dwjz"]

            # 如果JSONP的jzrq比confirmed还新，使用JSONP的数据
            if jsonp["jzrq"] > jzrq:
                jzrq = jsonp["jzrq"]
                dwjz = jsonp["dwjz"]
                print(f"  {code}: JSONP jzrq ({jsonp['jzrq']}) > confirmed ({confirmed['jzrq']}), using JSONP")

            new_funds[code] = {
                "name": name,
                "code": code,
                "gsz": jsonp["gsz"],
                "gszzl": jsonp["gszzl"],
                "dwjz": dwjz,
                "jzrq": jzrq,
                "gztime": jsonp["gztime"]
            }
        elif confirmed:
            # 只有confirmed：没有实时估值数据
            name = old_funds.get(code, {}).get("name", "")
            new_funds[code] = {
                "name": name,
                "code": code,
                "gsz": old_funds.get(code, {}).get("gsz", 0),
                "gszzl": old_funds.get(code, {}).get("gszzl", 0),
                "dwjz": confirmed["dwjz"],
                "jzrq": confirmed["jzrq"],
                "gztime": old_funds.get(code, {}).get("gztime", "")
            }
            print(f"  {code}: JSONP unavailable, using confirmed NAV only")
        elif jsonp:
            # 只有JSONP（不太可能但也处理）
            new_funds[code] = jsonp
            print(f"  {code}: confirmed NAV unavailable, using JSONP only")
        else:
            # 都没有：保留旧缓存
            if code in old_funds:
                new_funds[code] = old_funds[code]
                print(f"  {code}: ALL FAILED, keeping cached data")
            else:
                print(f"  {code}: ALL FAILED, no cached data available")

    # 5. 检查是否有实际数据变化
    actual_change = False
    for code in FUND_CODES:
        new_info = new_funds.get(code)
        old_info = old_funds.get(code)
        if not new_info:
            continue
        if not old_info:
            actual_change = True
            break
        # 比较 jzrq 和 dwjz（关键字段）
        if new_info.get("jzrq") != old_info.get("jzrq") or new_info.get("dwjz") != old_info.get("dwjz"):
            actual_change = True
            print(f"  {code}: DATA CHANGED jzrq {old_info.get('jzrq')} → {new_info.get('jzrq')} dwjz {old_info.get('dwjz')} → {new_info.get('dwjz')}")

    if not actual_change:
        # 即使无变化也更新，但标记
        print(f"\n  ⚠️ No actual NAV data change detected (jzrq/dwjz unchanged)")

    # 6. 写入 fund-nav.json
    result = {
        "funds": new_funds,
        "updated": today
    }
    with open(OUTPUT_NAV_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n=== fund-nav.json written (updated={today}) ===")

    # 7. 更新 index.html HISTORY_RAW
    print("\n=== Updating HISTORY_RAW in index.html ===")
    history_updated = _do_update_history_raw(HTML_FILE, FUND_CODES)
    if not history_updated:
        print("  No history updates needed for index.html")

    # 8. 更新 fund-report.html HISTORY_RAW + EMBEDDED_NAV
    print("\n=== Updating HISTORY_RAW in fund-report.html ===")
    report_history_updated = _do_update_history_raw(REPORT_FILE, FUND_CODES)
    if not report_history_updated:
        print("  No history updates needed for fund-report.html")

    print("\n=== Updating EMBEDDED_NAV in fund-report.html ===")
    report_updated = update_embedded_nav(new_funds)
    if not report_updated:
        print("  No fund-report.html EMBEDDED_NAV updates needed")

    # 9. 输出变化摘要供 workflow 判断
    if actual_change:
        print("\n[RESULT] NAV_DATA_CHANGED=true")
    else:
        print("\n[RESULT] NAV_DATA_CHANGED=false")


def update_embedded_nav(funds_data):
    """更新 fund-report.html 中的 EMBEDDED_NAV 数据"""
    try:
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print("  [SKIP] fund-report.html not found")
        return False

    match = re.search(r'const EMBEDDED_NAV = (\{.*?\});', content, re.DOTALL)
    if not match:
        print("  [SKIP] EMBEDDED_NAV not found in fund-report.html")
        return False

    new_nav = {}
    for code, info in funds_data.items():
        new_nav[code] = {
            "name": info.get("name", ""),
            "gsz": info.get("gsz", 0),
            "dwjz": info.get("dwjz", 0),
            "gszzl": info.get("gszzl", 0),
            "gztime": info.get("gztime", ""),
            "jzrq": info.get("jzrq", "")
        }

    new_json = json.dumps(new_nav, ensure_ascii=False, separators=(",", ":"))
    old_text = "const EMBEDDED_NAV = " + match.group(1) + ";"
    new_text = "const EMBEDDED_NAV = " + new_json + ";"

    if old_text == new_text:
        print("  EMBEDDED_NAV unchanged")
        return False

    content = content.replace(old_text, new_text)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print("  fund-report.html EMBEDDED_NAV updated")
    return True


if __name__ == "__main__":
    main()
