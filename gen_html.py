#!/usr/bin/env python3
"""
gen_html.py — 自动更新 HTML 中的嵌入数据

功能：
1. 读取 data/fund-data.json → 更新 fund-report.html / index.html 中的 EMBEDDED_FUND_DATA
2. 读取 data/fund-nav.json → 更新 fund-report.html / index.html 中的 EMBEDDED_NAV
3. 读取 data/fund-nav.json → 更新 EMBEDDED_NAV_VERSION（最新净值日期）
4. 确保 Cache-Control meta 标签存在

用法：python gen_html.py
在每次 push 前运行此脚本，确保 HTML 中的嵌入数据是最新的。
"""

import json
import re
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"⚠️  {filename} not found at {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def update_html_file(filepath, fund_data_json, fund_nav_json):
    """更新单个 HTML 文件"""
    if not os.path.exists(filepath):
        print(f"⚠️  File not found: {filepath}")
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    modified = False

    # 1. 更新 EMBEDDED_FUND_DATA
    if fund_data_json:
        fd_str = json.dumps(fund_data_json, ensure_ascii=False, indent=2)
        # 匹配 const EMBEDDED_FUND_DATA = { ... };
        pattern_fd = r'(const EMBEDDED_FUND_DATA\s*=\s*)\{[^}]*\}(\s*;)'  # won't work for nested
        # 改用更精确的匹配：从 EMBEDDED_FUND_DATA = 到下一个 };
        # 使用非贪婪匹配跨行
        pattern_fd2 = r'(const EMBEDDED_FUND_DATA\s*=\s*)\{[\s\S]*?\n\};'
        match_fd = re.search(pattern_fd2, content)
        if match_fd:
            new_fd = f'{match_fd.group(1)}{fd_str};'
            content = content.replace(match_fd.group(0), new_fd)
            modified = True
            print(f"  ✅ EMBEDDED_FUND_DATA updated")
        else:
            print(f"  ⚠️  EMBEDDED_FUND_DATA pattern not found")

    # 2. 更新 EMBEDDED_NAV
    if fund_nav_json:
        # 构建 EMBEDDED_NAV: 扁平化，每个基金一个条目
        funds = fund_nav_json.get("funds", {})

        nav_obj = {}
        for code, info in funds.items():
            nav_obj[code] = {
                "name": info.get("name", ""),
                "gsz": info.get("gsz", 0),
                "dwjz": info.get("dwjz", 0),
                "gszzl": info.get("gszzl", 0),
                "gztime": info.get("gztime", ""),
                "jzrq": info.get("jzrq", "")
            }

        nav_str = json.dumps(nav_obj, ensure_ascii=False)

        pattern_nav = r'const EMBEDDED_NAV\s*=\s*\{[\s\S]*?\};'
        match_nav = re.search(pattern_nav, content)
        if match_nav:
            new_nav = f'const EMBEDDED_NAV = {nav_str};'
            content = content.replace(match_nav.group(0), new_nav)
            modified = True
            print(f"  ✅ EMBEDDED_NAV updated ({len(nav_obj)} funds)")
        else:
            print(f"  ⚠️  EMBEDDED_NAV pattern not found")

        # 3. 更新 EMBEDDED_NAV_VERSION
        # 从 fund_nav_json 中提取最晚的 jzrq 或 updated 字段
        latest_jzrq = fund_nav_json.get("updated", "")
        if not latest_jzrq:
            jzrq_dates = [v.get("jzrq", "") for v in funds.values() if v.get("jzrq")]
            latest_jzrq = max(jzrq_dates) if jzrq_dates else ""

        if latest_jzrq:
            pattern_ver = r'const EMBEDDED_NAV_VERSION\s*=\s*"[^"]*";'
            new_ver = f'const EMBEDDED_NAV_VERSION = "{latest_jzrq}";'

            if re.search(pattern_ver, content):
                content = re.sub(pattern_ver, new_ver, content)
                print(f"  ✅ EMBEDDED_NAV_VERSION updated → {latest_jzrq}")
            else:
                # 在 EMBEDDED_NAV 之后插入 VERSION
                content = content.replace(
                    f'const EMBEDDED_NAV = {nav_str};',
                    f'const EMBEDDED_NAV = {nav_str};\nconst EMBEDDED_NAV_VERSION = "{latest_jzrq}";'
                )
                print(f"  ✅ EMBEDDED_NAV_VERSION added → {latest_jzrq}")
            modified = True

    # 4. 确保 Cache-Control meta 标签存在
    if 'Cache-Control' not in content[:500]:
        # 在第一个 <meta charset 之后添加
        cc_meta = '\n<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">\n<meta http-equiv="Pragma" content="no-cache">\n<meta http-equiv="Expires" content="0">'
        content = content.replace(
            '<meta charset="UTF-8">',
            '<meta charset="UTF-8">' + cc_meta
        )
        modified = True
        print(f"  ✅ Cache-Control meta tags added")

    if modified:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  💾 Saved: {filepath}")
    else:
        print(f"  ℹ️  No changes needed")

    return modified

def main():
    print("=" * 60)
    print("gen_html.py — 更新 HTML 嵌入数据")
    print("=" * 60)

    # 加载数据
    fund_data = load_json("fund-data.json")
    fund_nav = load_json("fund-nav.json")

    if not fund_data and not fund_nav:
        print("❌ No data files found. Aborting.")
        sys.exit(1)

    # 打印数据摘要
    if fund_nav:
        funds = fund_nav.get("funds", {})
        print(f"\n📊 fund-nav.json: {len(funds)} funds, updated={fund_nav.get('updated','?')}")
        for code, info in funds.items():
            print(f"   {code} {info.get('name','')}: jzrq={info.get('jzrq','?')} dwjz={info.get('dwjz','?')}")

    if fund_data:
        funds = fund_data.get("funds", {})
        total_txns = sum(len(f.get("transactions", [])) for f in funds.values())
        print(f"\n📋 fund-data.json: {len(funds)} funds, {total_txns} transactions")

    # 更新文件
    print("\n--- Updating fund-report.html ---")
    update_html_file(os.path.join(BASE_DIR, "fund-report.html"), fund_data, fund_nav)

    print("\n--- Updating index.html ---")
    update_html_file(os.path.join(BASE_DIR, "index.html"), fund_data, fund_nav)

    print(f"\n{'='*60}")
    print("✅ Done! HTML embed data is now in sync with data/*.json")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
