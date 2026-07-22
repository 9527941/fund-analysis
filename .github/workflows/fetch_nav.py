#!/usr/bin/env python3
"""
获取基金最新净值数据，更新 data/fund-nav.json
同时将新净值追加到 index.html/fund-report.html 的 HISTORY_RAW 中
GitHub Actions 自动运行，无需本地电脑

v5 变更：fundgz.1234567.com.cn JSONP API 已下线(2026-07)，
        数据源全面切换到东方财富 history API。
        对于非QDII基金，dwjz/jzrq 取 history API；
        QDII 基金(024239)用 fundmobapi 备用接口获取最新净值。
"""
import json
import re
import urllib.request
from datetime import datetime, timedelta

FUND_CODES = ["013841", "002164", "012630", "004937", "024246", "001423", "016020", "016186", "022718", "024239"]
QDII_CODES = {"024239"}  # QDII 基金，净值 T+2 延迟，需特殊处理
JSONP_URL = "https://fundgz.1234567.com.cn/js/{code}.js?rt={timestamp}"
HISTORY_API = "https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize={size}&startDate={start}&endDate={end}"
FUND_INFO_URL = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNNBasicInformation?FCODE={code}&deviceid=web&plat=web"
SINA_API = "https://hq.sinajs.cn/list="
OUTPUT_NAV_FILE = "data/fund-nav.json"
HTML_FILE = "index.html"
REPORT_FILE = "fund-report.html"


def fetch_from_eastmoney(code):
    """从东方财富 history API 获取最新净值（主数据源）"""
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    url = HISTORY_API.format(code=code, size=3, start=start, end=today)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"https://fundf10.eastmoney.com/jjjz_{code}.html"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        items = data.get("Data", {}).get("LSJZList", [])
        if not items:
            print(f"  [WARN] {code}: no history data")
            return None
        latest = items[0]
        dwjz = float(latest["DWJZ"])
        jzrq = latest["FSRQ"]
        jzzzl = float(latest.get("JZZZL", 0))
        # 如果最新一条数据超过2天（比如周五的数据到了周一还没更新），尝试取更早的
        jzrq_dt = datetime.strptime(jzrq, "%Y-%m-%d")
        if (datetime.now() - jzrq_dt).days > 2 and len(items) > 1:
            prev = items[1]
            prev_jzrq = datetime.strptime(prev["FSRQ"], "%Y-%m-%d")
            if prev_jzrq > jzrq_dt:
                dwjz = float(prev["DWJZ"])
                jzrq = prev["FSRQ"]
                jzzzl = float(prev.get("JZZZL", 0))

        result = {
            "dwjz": dwjz,
            "jzrq": jzrq,
            "gszzl": jzzzl,
            "gsz": dwjz  # 非交易时段，估算值=单位净值
        }
        return result
    except Exception as e:
        print(f"  [ERROR] {code}: eastmoney history API failed: {e}")
    return None


def fetch_qdii_nav(code):
    """获取 QDII 基金的最新净值（使用 fundmobapi 备用接口）"""
    try:
        url = FUND_INFO_URL.format(code=code)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://fundmobapi.eastmoney.com/"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        datas = data.get("Datas", {})
        dwjz = float(datas.get("DWJZ", 0))
        jzrq = datas.get("FSRQ", "")
        if dwjz and jzrq:
            return {
                "dwjz": dwjz,
                "jzrq": jzrq,
                "gszzl": 0,
                "gsz": dwjz
            }
    except Exception as e:
        print(f"  [ERROR] {code}: QDII API failed: {e}")
    return None


def fetch_nav(code):
    """从天天基金JSONP接口获取基金净值数据（已废弃，作为备用）"""
    url = JSONP_URL.format(code=code, timestamp=int(datetime.now().timestamp() * 1000))
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
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
            print(f"  [WARN] {code}: fundgz API returned no data (likely deprecated)")
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
        print(f"  [WARN] {code}: fundgz API error: {e}")
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


def get_fund_name(code, cached_info):
    """从缓存或 API 获取基金名称"""
    if cached_info and cached_info.get("name"):
        return cached_info["name"]
    return ""  # 如果缓存也没有名字，后续会从 fundmobapi 获取


def fetch_from_sina():
    """从新浪财经 API 获取所有基金的实时估值（一次请求）"""
    url = SINA_API + ",".join(f"fu_{c}" for c in FUND_CODES)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn/"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
        text = raw.decode("gbk", errors="replace")
    except Exception as e:
        print(f"  [ERROR] Sina API failed: {e}")
        return {}

    result = {}
    for code in FUND_CODES:
        for line in text.strip().split("\n"):
            if f"fu_{code}" not in line:
                continue
            parts = line.split('"')
            if len(parts) < 2:
                continue
            data = parts[1].split(",")
            if len(data) < 7:
                continue
            try:
                gsz = float(data[2]) if data[2] else 0
                gszzl = float(data[6]) if data[6] else 0
                # data[7]=日期(如 2026-07-22), data[1]=时间(如 10:47:00)
                gztime = (data[7] + " " + data[1]) if len(data) > 7 and data[7] else data[1]
            except (ValueError, IndexError):
                continue
            if gsz and gztime:
                result[code] = {"gsz": gsz, "gszzl": gszzl, "gztime": gztime}
            break
    return result


def is_trading_hours():
    """判断当前是否在 A 股交易时段（周一至周五 9:30-15:00 北京时间）

    注意：GitHub Actions 运行器时区为 UTC，必须显式转换为 Asia/Shanghai，
    否则 datetime.now() 取到的是 UTC 时间，交易时段判断会整体偏移 8 小时。
    """
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
    except Exception:
        now = datetime.now()
    weekday = now.weekday()
    hour = now.hour
    minute = now.minute
    if weekday >= 5:  # 周六日
        return False
    if hour < 9 or hour > 15:
        return False
    if hour == 9 and minute < 30:
        return False
    if hour == 15 and minute > 0:
        return False
    return True


def main():
    # 1. 更新 fund-nav.json
    try:
        with open(OUTPUT_NAV_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {"funds": {}, "updated": ""}

    cached_funds = cache.get("funds", {})
    funds = {}
    updated_count = 0
    today = datetime.now().strftime("%Y-%m-%d")

    print(f"=== Fund NAV Update: {today} ===")

    # 交易时段预加载新浪实时估值
    in_trading = is_trading_hours()
    sina_data = {}
    if in_trading:
        print("  [INFO] Trading hours detected, fetching Sina real-time estimates...")
        sina_data = fetch_from_sina()
        print(f"  [INFO] Sina returned data for {len(sina_data)} funds")

    def _has_live_sina_estimate(cached_info):
        """判断缓存中是否已有今日交易时段的新浪实时估值，且尚未过期"""
        if not cached_info or not cached_info.get("gsz") or not cached_info.get("dwjz"):
            return False
        gsz = cached_info.get("gsz", 0)
        dwjz = cached_info.get("dwjz", 0)
        gztime = cached_info.get("gztime", "")
        # gsz != dwjz 说明是实时估值，且 gztime 是时间格式（如 "13:46:00"）
        if not (abs(gsz - dwjz) > 0.0001 and ":" in str(gztime) and len(str(gztime)) < 12):
            return False
        # 缓存更新日期必须是今天
        if cache.get("updated", "") != today:
            return False
        # 检查估值时间是否仍有效：交易时段后超过2小时视为过期
        try:
            parts = str(gztime).split(":")
            est_hour = int(parts[0])
            est_min = int(parts[1]) if len(parts) > 1 else 0
            now = datetime.now()
            if now.hour > est_hour + 2 or (now.hour == est_hour + 2 and now.minute > est_min):
                return False
        except (ValueError, IndexError):
            return False
        return True

    for code in FUND_CODES:
        cached_info = cached_funds.get(code, {})
        print(f"  Fetching {code}...", end=" ")

        # Step 1: 尝试 JSONP（已废弃）
        data = fetch_nav(code)

        # Step 2: 东方财富 history API（主数据源，获取 dwjz/jzrq）
        if not data or not data.get("dwjz"):
            if not data:
                print("fundgz dead, using eastmoney...", end=" ")
            em_data = fetch_from_eastmoney(code)
            if not em_data and code in QDII_CODES:
                print("QDII fallback...", end=" ")
                em_data = fetch_qdii_nav(code)

            if em_data:
                name = get_fund_name(code, cached_info)
                data = {
                    "name": name,
                    "code": code,
                    "gsz": em_data.get("gsz", em_data.get("dwjz", 0)),
                    "gszzl": em_data.get("gszzl", 0),
                    "dwjz": em_data.get("dwjz", 0),
                    "jzrq": em_data.get("jzrq", ""),
                    "gztime": em_data.get("jzrq", "") + " 15:00"
                }
                print(f"OK (dwjz={data['dwjz']}, jzrq={data['jzrq']})")
            elif code in QDII_CODES:
                qdii = fetch_qdii_nav(code)
                if qdii:
                    name = get_fund_name(code, cached_info)
                    data = {
                        "name": name,
                        "code": code,
                        "gsz": qdii.get("dwjz", 0),
                        "gszzl": qdii.get("gszzl", 0),
                        "dwjz": qdii.get("dwjz", 0),
                        "jzrq": qdii.get("jzrq", ""),
                        "gztime": qdii.get("jzrq", "") + " 15:00"
                    }
                    print(f"QDII OK (dwjz={data['dwjz']}, jzrq={data['jzrq']})")
        else:
            print(f"OK (dwjz={data['dwjz']}, jzrq={data['jzrq']})")

        # Step 3: 交易时段用新浪实时估值覆盖 gsz/gszzl/gztime
        if data and code in sina_data:
            sd = sina_data[code]
            # 仅当新浪返回的时间戳是“今天”才采用，避免 QDII 等无实时数据的基金
            # 拿到陈旧的估值（例如 024239 曾返回 2026-04-21 的脏数据）
            sina_date = sd.get("gztime", "").split(" ")[0]
            try:
                from zoneinfo import ZoneInfo
                today_bjt = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
            except Exception:
                today_bjt = datetime.now().strftime("%Y-%m-%d")
            if sina_date == today_bjt and -15 <= sd["gszzl"] <= 15:
                data["gsz"] = sd["gsz"]
                data["gszzl"] = sd["gszzl"]
                data["gztime"] = sd["gztime"]
                print(f"  -> Sina estimate: gsz={sd['gsz']}, gszzl={sd['gszzl']}%, time={sd['gztime']}")
            else:
                print(f"  -> Sina estimate skipped (date={sina_date} != today or out of range)")

        # Step 4: 非交易时段，保留缓存中的新浪实时估值（防止定时任务覆盖）
        if data and not in_trading and _has_live_sina_estimate(cached_info):
            data["gsz"] = cached_info["gsz"]
            data["gszzl"] = cached_info["gszzl"]
            data["gztime"] = cached_info["gztime"]
            print(f"  -> Preserved cached live estimate: gsz={cached_info['gsz']}, gszzl={cached_info['gszzl']}%")

        if data and data.get("dwjz") and data.get("jzrq"):
            funds[code] = data
            updated_count += 1
        else:
            print("FAILED, keeping cached")
            if cached_info:
                funds[code] = cached_info

    try:
        from zoneinfo import ZoneInfo
        updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = {
        "funds": funds,
        "updated": today,
        "updated_at": updated_at
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
