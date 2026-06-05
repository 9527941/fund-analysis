#!/usr/bin/env python3
"""
从天天基金 JSONP 接口获取最新净值数据，更新 data/fund-nav.json
从东方财富历史净值接口获取缺失的历史净值，更新 index.html 中的 HISTORY_RAW
GitHub Actions 自动运行，无需本地电脑
"""
import json
import re
import urllib.request
from datetime import datetime, timedelta

FUND_CODES = ["013841", "002164", "012630", "004937", "024246", "001423", "016020"]
JSONP_URL = "https://fundgz.1234567.com.cn/js/{code}.js?rt={timestamp}"
HISTORY_API = "https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize={size}&startDate={start}&endDate={end}"
OUTPUT_NAV_FILE = "data/fund-nav.json"
HTML_FILE = "index.html"
REPORT_FILE = "fund-report.html"


def fetch_nav(code):
    """从天天基金JSONP接口获取基金净值数据"""
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
            print(f"  [WARN] {code}: no JSONP data")
            return None
        start = text.index("(") + 1
        end = text.rindex(")")
        json_str = text[start:end]
        data = json.loads(json_str)
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
        print(f"  [ERROR] {code}: {e}")
    return None


def fetch_history_nav(code, start_date, end_date):
    """从东方财富API获取指定日期范围的历史净值"""
    url = HISTORY_API.format(code=code, size=40, start=start_date, end=end_date)
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
        print(f"  [WARN] {code}: history fetch failed: {e}")
        return []


def _do_update_history_raw(filepath):
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

    for code in FUND_CODES:
        arr = history_data["funds"].get(code, [])
        if not arr:
            continue

        # 找到最新日期
        existing_dates = {d["date"] for d in arr}
        latest_date = max(existing_dates)

        # 从最新日期的下一天到今天，获取缺失的历史净值
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

        # 重新排序（最新在前）
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


def update_history_raw():
    """更新 index.html 中嵌入的 HISTORY_RAW 数据"""
    return _do_update_history_raw(HTML_FILE)


def update_report_history_raw():
    """更新 fund-report.html 中嵌入的 HISTORY_RAW 数据"""
    return _do_update_history_raw(REPORT_FILE)


def main():
    # 1. 更新 fund-nav.json（实时净值缓存）
    try:
        with open(OUTPUT_NAV_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {"funds": {}, "updated": ""}

    funds = cache.get("funds", {})
    updated_count = 0
    today = datetime.now().strftime("%Y-%m-%d")

    print(f"=== Fund NAV Update: {today} ===")

    for code in FUND_CODES:
        print(f"  Fetching {code}...", end=" ")
        data = fetch_nav(code)
        if data:
            funds[code] = data
            updated_count += 1
            print(f"OK (dwjz={data['dwjz']}, jzrq={data['jzrq']})")
        else:
            print("FAILED (keeping cached data)")

    result = {
        "funds": funds,
        "updated": today
    }

    with open(OUTPUT_NAV_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"=== Updated {updated_count}/{len(FUND_CODES)} funds (fund-nav.json) ===")

    # 2. 更新 index.html 中的 HISTORY_RAW（历史净值）
    print("=== Updating HISTORY_RAW in index.html ===")
    history_updated = update_history_raw()
    if not history_updated:
        print("  No history updates needed for index.html")

    # 2b. 更新 fund-report.html 中的 HISTORY_RAW（历史净值）
    print("=== Updating HISTORY_RAW in fund-report.html ===")
    report_history_updated = update_report_history_raw()
    if not report_history_updated:
        print("  No history updates needed for fund-report.html")

    # 3. 更新 fund-report.html 中的 EMBEDDED_NAV（内嵌实时净值）
    print("=== Updating EMBEDDED_NAV in fund-report.html ===")
    report_updated = update_embedded_nav(funds)
    if not report_updated:
        print("  No fund-report.html updates needed")


def update_embedded_nav(funds_data):
    """更新 fund-report.html 中的 EMBEDDED_NAV 数据"""
    try:
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print("  [SKIP] fund-report.html not found")
        return False

    # 匹配 EMBEDDED_NAV = {...};
    match = re.search(r'const EMBEDDED_NAV = (\{.*?\});', content, re.DOTALL)
    if not match:
        print("  [SKIP] EMBEDDED_NAV not found in fund-report.html")
        return False

    # 构建新的 EMBEDDED_NAV
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
