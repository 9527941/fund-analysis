#!/usr/bin/env python3
"""
从天天基金 JSONP 接口获取最新净值数据，更新 data/fund-nav.json
GitHub Actions 自动运行，无需本地电脑
"""
import json
import urllib.request
from datetime import datetime

FUND_CODES = ["013841", "002164", "012630", "004937", "024246"]
JSONP_URL = "https://fundgz.1234567.com.cn/js/{code}.js?rt={timestamp}"
OUTPUT_FILE = "data/fund-nav.json"


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


def main():
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
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

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"=== Updated {updated_count}/{len(FUND_CODES)} funds ===")


if __name__ == "__main__":
    main()
