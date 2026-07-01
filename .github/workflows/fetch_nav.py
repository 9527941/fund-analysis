#!/usr/bin/env python3
"""
从天天基金 JSONP 接口获取最新净值数据，更新 data/fund-nav.json
同时将新净值追加到 index.html/fund-report.html 的 HISTORY_RAW 中
GitHub Actions 自动运行，无需本地电脑

v4 变更：HISTORY_RAW 不再依赖东方财富 history API（会被 GitHub IP 拦截），
        改为直接从 fund-nav.json 的 dwjz 数据追加。
"""
import json
import re
import urllib.request
from datetime import datetime, timedelta

FUND_CODES = ["013841", "002164", "012630", "004937", "024246", "001423", "016020", "016186", "022718", "024239"]
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


def _do_update_history_raw(filepath, funds_data):
    """用 fund-nav.json 的最新 dwjz 追加到 HISTORY_RAW（不再依赖东方财富 history API）"""
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
    updated = False

    for code in FUND_CODES:
        arr = history_data["funds"].get(code, [])
        if not arr:
            continue

        # 从 fund-nav.json 获取最新 dwjz 和 jzrq
        fund_info = funds_data.get(code, {})
        new_jzrq = fund_info.get("jzrq", "")
        new_dwjz = fund_info.get("dwjz", 0)

        if not new_jzrq or new_dwjz == 0:
            continue

        existing_dates = {d["date"] for d in arr}

        if new_jzrq not in existing_dates:
            arr.append({
                "date": new_jzrq,
                "nav": new_dwjz,
                "ljjz": new_dwjz
            })
            existing_dates.add(new_jzrq)
            arr.sort(key=lambda x: x["date"], reverse=True)
            history_data["funds"][code] = arr
            updated = True
            print(f"    {code}: added {new_jzrq} nav={new_dwjz}")

    if updated:
        new_json = json.dumps(history_data, ensure_ascii=False, separators=(",", ":"))
        old_text = "const HISTORY_RAW = " + match.group(1) + ";"
        new_text = "const HISTORY_RAW = " + new_json + ";"
        content = content.replace(old_text, new_text)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  {filepath} HISTORY_RAW updated")

    return updated


def update_history_raw(funds_data):
    """用 fund-nav.json 数据更新 index.html 中的 HISTORY_RAW"""
    return _do_update_history_raw(HTML_FILE, funds_data)


def update_report_history_raw(funds_data):
    """用 fund-nav.json 数据更新 fund-report.html 中的 HISTORY_RAW"""
    return _do_update_history_raw(REPORT_FILE, funds_data)


def fetch_latest_nav_from_history(code):
    """从东方财富历史净值API获取最近一天的已确认净值（比JSONP更早发布）"""
    today = datetime.now().strftime("%Y-%m-%d")
    # 取最近5天的历史净值，确保能拿到最新已确认的
    start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    url = HISTORY_API.format(code=code, size=5, start=start, end=today)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://fund.eastmoney.com/"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        items = data.get("Data", {}).get("LSJZList", [])
        if items:
            latest = items[0]  # 最新在前
            return {
                "dwjz": float(latest["DWJZ"]),
                "jzrq": latest["FSRQ"],
                "ljjz": float(latest.get("LJJZ", latest["DWJZ"]))
            }
    except Exception as e:
        print(f"  [WARN] {code}: history NAV fetch failed: {e}")
    return None


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
            # 检查JSONP返回的jzrq是否是今天或昨天（工作日）
            # 如果不是，尝试从history API获取更新的已确认净值
            jzrq = data.get("jzrq", "")
            jsonp_date = datetime.strptime(jzrq, "%Y-%m-%d") if jzrq else None
            today_dt = datetime.now()

            # 如果JSONP的jzrq距离今天超过1个工作日(>=1天)，说明净值可能还没更新到最新
            # history API通常比JSONP更早发布当天净值
            # v3修复: 从 >1 改为 >=1，让 fallback 更积极
            if jsonp_date and (today_dt - jsonp_date).days >= 1:
                print(f"jzrq={jzrq} stale, checking history...", end=" ")
                hist = fetch_latest_nav_from_history(code)
                if hist and hist["jzrq"] > jzrq:
                    data["dwjz"] = hist["dwjz"]
                    data["jzrq"] = hist["jzrq"]
                    print(f"upgraded to jzrq={hist['jzrq']} dwjz={hist['dwjz']}")
                else:
                    print(f"OK (dwjz={data['dwjz']}, jzrq={data['jzrq']})")
            else:
                print(f"OK (dwjz={data['dwjz']}, jzrq={data['jzrq']})")

            funds[code] = data
            updated_count += 1
        else:
            print("FAILED (keeping cached data)")

    result = {
        "funds": funds,
        "updated": today
    }

    with open(OUTPUT_NAV_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"=== Updated {updated_count}/{len(FUND_CODES)} funds (fund-nav.json) ===")

    # 2. 用 fund-nav.json 数据更新 index.html 中的 HISTORY_RAW（不再调东方财富 history API）
    print("=== Updating HISTORY_RAW in index.html ===")
    history_updated = update_history_raw(funds)
    if not history_updated:
        print("  No history updates needed for index.html")

    # 2b. 更新 fund-report.html 中的 HISTORY_RAW
    print("=== Updating HISTORY_RAW in fund-report.html ===")
    report_history_updated = update_report_history_raw(funds)
    if not report_history_updated:
        print("  No history updates needed for fund-report.html")

    # 3. 更新 fund-report.html 中的 EMBEDDED_NAV（内嵌实时净值）
    print("=== Updating EMBEDDED_NAV in fund-report.html ===")
    report_updated = update_embedded_nav(funds)
    if not report_updated:
        print("  No fund-report.html updates needed")

    # 4. 更新 index.html 中的 NAV_VERSION（确保 CDN 缓存穿透）
    print("=== Updating NAV_VERSION in index.html ===")
    version_updated = update_nav_version()
    if not version_updated:
        print("  No NAV_VERSION update needed")


def update_nav_version():
    """更新 index.html 中的 NAV_VERSION 常量，用于 CDN 缓存穿透"""
    try:
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print("  [SKIP] index.html not found")
        return False

    # 匹配 const NAV_VERSION = "...";
    match = re.search(r'const NAV_VERSION = "(\d+)";', content)
    if not match:
        print("  [SKIP] NAV_VERSION not found in index.html")
        return False

    # 用当前时间戳作为新版本号 (YYYYMMDDHHMMSS)
    new_version = datetime.now().strftime("%Y%m%d%H%M%S")
    old_text = f'const NAV_VERSION = "{match.group(1)}";'
    new_text = f'const NAV_VERSION = "{new_version}";'

    if old_text == new_text:
        print("  NAV_VERSION unchanged (same timestamp)")
        return False

    content = content.replace(old_text, new_text)

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  NAV_VERSION updated: {match.group(1)} -> {new_version}")
    return True


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
