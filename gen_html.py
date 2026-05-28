# -*- coding: utf-8 -*-
import json, urllib.request, os

codes_info = {
    "013841": "银华集成电路混合C",
    "002164": "汇添富新睿精选灵活配置混合C",
    "012630": "广发半导体芯片ETF联接C",
    "004937": "中航混改精选混合C",
    "024246": "广发科创人工智能ETF联接C"
}

# Use exact values from 养基宝 screenshot (2026-05-28)
nav_overrides = {
    "013841": {"name": "银华集成电路混合C", "gsz": 2.7550, "dwjz": 2.6963, "gszzl": 2.18, "gztime": "2026-05-28 15:00", "jzrq": "2026-05-27"},
    "002164": {"name": "汇添富新睿精选灵活配置混合C", "gsz": 1.8450, "dwjz": 1.8090, "gszzl": 1.99, "gztime": "2026-05-28 15:00", "jzrq": "2026-05-27"},
    "012630": {"name": "广发半导体芯片ETF联接C", "gsz": 1.5113, "dwjz": 1.5066, "gszzl": 0.31, "gztime": "2026-05-28 15:00", "jzrq": "2026-05-27"},
    "004937": {"name": "中航混改精选混合C", "gsz": 0.9681, "dwjz": 0.9660, "gszzl": 0.22, "gztime": "2026-05-28 15:00", "jzrq": "2026-05-27"},
    "024246": {"name": "广发科创人工智能ETF联接C", "gsz": 1.6109, "dwjz": 1.6038, "gszzl": 0.44, "gztime": "2026-05-28 15:00", "jzrq": "2026-05-27"},
}

nav_data = {}
nav_data.update(nav_overrides)

transactions = {
    "013841": [
        {"date":"2026-03-03","type":"买入","amount":500,"shares":275.31,"nav":1.8161},
        {"date":"2026-03-09","type":"买入","amount":500,"shares":280.26,"nav":1.7840},
        {"date":"2026-03-19","type":"买入","amount":1000,"shares":583.60,"nav":1.7135},
    ],
    "002164": [
        {"date":"2026-03-19","type":"买入","amount":1000,"shares":655.74,"nav":1.5250},
    ],
    "012630": [
        {"date":"2026-05-14","type":"买入","amount":1000,"shares":745.38,"nav":1.3416},
        {"date":"2026-05-15","type":"买入","amount":1000,"shares":747.33,"nav":1.3381},
    ],
    "004937": [
        {"date":"2026-05-15","type":"买入","amount":1000,"shares":1065.98,"nav":0.9381},
        {"date":"2026-05-27","type":"买入","amount":1000,"shares":1035.20,"nav":0.9660},
        {"date":"2026-05-28","type":"买入(待确认)","amount":1000,"shares":1032.95,"nav":0.9681,"pending":True},
    ],
    "024246": [
        {"date":"2026-05-27","type":"买入","amount":2000,"shares":1247.04,"nav":1.6038},
    ],
}

# User-specified avg cost overrides (actual brokerage cost basis)
cost_overrides = {
    "013841": 1.7557,
    "002164": 1.5250,
    "024246": 1.6038,
    "012630": 1.3395,
    "004937": 0.9518,
}

meta = {
    "013841": {"sector":"半导体","sectorTag":"半导体/芯片","riskLevel":"高"},
    "002164": {"sector":"灵活配置","sectorTag":"灵活配置","riskLevel":"中高"},
    "012630": {"sector":"半导体","sectorTag":"半导体/芯片","riskLevel":"高"},
    "004937": {"sector":"国企改革","sectorTag":"国企改革","riskLevel":"中高"},
    "024246": {"sector":"AI","sectorTag":"人工智能","riskLevel":"高"},
}

def calc_fund(code):
    txns = transactions[code]
    total_shares = sum(t['shares'] for t in txns if not t.get('pending') and '卖出' not in t['type'])
    total_cost = sum(t['amount'] for t in txns if not t.get('pending'))
    nav = nav_data[code]['gsz']
    avg_cost = total_cost / total_shares if total_shares > 0 else 0
    current_value = total_shares * nav
    pnl = current_value - total_cost
    pnl_rate = (pnl / total_cost) * 100 if total_cost > 0 else 0
    return {
        'total_shares': total_shares,
        'total_cost': total_cost,
        'avg_cost': avg_cost,
        'current_value': current_value,
        'pnl': pnl,
        'pnl_rate': pnl_rate
    }

calcs = {}
for code in codes_info:
    if code in nav_data and nav_data[code]:
        calcs[code] = calc_fund(code)

total_invest = sum(c['total_cost'] for c in calcs.values())
total_value = sum(c['current_value'] for c in calcs.values())
total_pnl = total_value - total_invest
total_rate = (total_pnl / total_invest * 100) if total_invest > 0 else 0

sectors = {}
for code, c in calcs.items():
    sec = meta[code]['sector']
    sectors[sec] = sectors.get(sec, 0) + c['current_value']

sorted_sectors = sorted(sectors.items(), key=lambda x: x[1], reverse=True)

def fmt_money(v):
    return "¥{0:,.2f}".format(v)
def fmt_pct(v):
    return "{0:+.2f}%".format(v)
def ud(v):
    return "up" if v >= 0 else "down"

rows = ""
for code in codes_info:
    if code not in nav_data or not nav_data[code] or code not in calcs:
        continue
    nav = nav_data[code]
    c = calcs[code]
    m = meta[code]
    rows += """
    <tr>
      <td class="fn-name">
        {name}
        <span class="fn-code">{code}</span>
        <span class="fn-sector">{sector}</span>
      </td>
      <td class="nav-val {nav_cls}">{nav_val:.4f}</td>
      <td class="change-val {nav_cls}">{nav_pct}</td>
      <td>{shares:.2f}{unit}</td>
      <td>{avg_cost:.4f}</td>
      <td class="{pnl_cls}">{pnl}</td>
      <td><span class="pnl-badge {pnl_cls}">{pnl_rate}</span></td>
      <td><span class="fn-sector">{sector} · {risk}{risk_text}</span></td>
    </tr>""".format(
        name=codes_info[code], code=code, sector=m['sectorTag'],
        nav_cls=ud(nav['gszzl']), nav_val=nav['gsz'], nav_pct=fmt_pct(nav['gszzl']),
        shares=c['total_shares'], unit="份", avg_cost=cost_overrides.get(code, c['avg_cost']),
        pnl_cls=ud(c['pnl']), pnl=fmt_money(c['pnl']), pnl_rate=fmt_pct(c['pnl_rate']),
        risk=m['riskLevel'], risk_text="风险"
    )

rows += """
  <tr class="summary-row">
    <td>合计</td>
    <td>--</td>
    <td>--</td>
    <td>--</td>
    <td>{total_invest}</td>
    <td class="{total_cls}">{total_pnl}</td>
    <td><span class="pnl-badge {total_cls}">{total_rate}</span></td>
    <td>5只基金</td>
  </tr>""".format(
    total_invest=fmt_money(total_invest),
    total_cls=ud(total_pnl),
    total_pnl=fmt_money(total_pnl),
    total_rate=fmt_pct(total_rate)
)

# Sector donut
sector_colors = {"半导体":"#e74c3c","AI":"#8e44ad","国企改革":"#2980b9","灵活配置":"#27ae60"}
conic_parts = []
legend_html = ""
cum = 0
for sec, val in sorted_sectors:
    pct = val / total_value * 100
    color = sector_colors.get(sec, "#999")
    conic_parts.append("{0} {1}% {2}%".format(color, cum, cum+pct))
    legend_html += '<div class="sl-item"><span class="sl-dot" style="background:{0}"></span><span>{1}</span><span class="sl-val">{2:.0f}%</span></div>'.format(color, sec, pct)
    cum += pct
ring_style = 'background: conic-gradient({0})'.format(','.join(conic_parts)) if conic_parts else 'background: #eee'

concerns_html = ""
semi_pct = (sectors.get("半导体", 0) / total_value * 100)
if semi_pct > 30:
    concerns_html += '<div class="concern-item"><span class="concern-tag risk">风险</span><span>半导体行业占比{0:.0f}%，集中度过高</span></div>'.format(semi_pct)
if total_rate > 20:
    concerns_html += '<div class="concern-item"><span class="concern-tag good">利好</span><span>组合整体盈利{0:.1f}%，表现不错</span></div>'.format(total_rate)
elif total_rate > 0:
    concerns_html += '<div class="concern-item"><span class="concern-tag good">利好</span><span>组合小幅盈利，整体健康</span></div>'
elif total_rate > -10:
    concerns_html += '<div class="concern-item"><span class="concern-tag tip">提醒</span><span>组合整体轻微亏损，基金投资是长期的事</span></div>'
concerns_html += '<div class="concern-item"><span class="concern-tag tip">提醒</span><span>关于红利策略：坚持自己看得懂的赛道</span></div>'

# Read template and inject
template_path = r'C:\Users\87159\WorkBuddy\2026-05-28-22-10-10\fund_analysis_v2.html'
with open(template_path, 'r', encoding='utf-8') as f:
    html = f.read()

html = html.replace(
    '<tbody id="fundTableBody"></tbody>',
    '<tbody id="fundTableBody">{0}</tbody>'.format(rows)
)

html = html.replace(
    '<div class="portfolio-analysis" id="portfolioAnalysis"></div>',
    '''<div class="portfolio-analysis" id="portfolioAnalysis">
      <h3>组合诊断</h3>
      <div class="sector-ring-wrap"><div class="sector-ring" style="{ring}"></div><div class="sector-legend">{legend}</div></div>
      {concerns}
    </div>'''.format(ring=ring_style, legend=legend_html, concerns=concerns_html)
)

from datetime import datetime
now = datetime.now()
date_str = now.strftime("%Y-%m-%d %H:%M")
html = html.replace(
    '<div class="date" id="reportDate">--</div>',
    '<div class="date" id="reportDate">{0} · {1}</div>'.format(date_str, nav_data["013841"]["gztime"])
)

html = html.replace(
    '<span id="navStatus">正在获取实时净值...</span>',
    '<span id="navStatus">实时净值已就绪</span>'
)

filter_options = '<option value="">-- 请选择一只基金 --</option>'
for code in codes_info:
    filter_options += '<option value="{0}">{1} ({0})</option>'.format(code, codes_info[code])

html = html.replace(
    '<select id="fundDetailFilter" onchange="renderFundDetail()">\n      <option value="">-- 请选择一只基金 --</option>\n    </select>',
    '<select id="fundDetailFilter" onchange="renderFundDetail()">\n      {0}\n    </select>'.format(filter_options)
)

output_path = r'C:\Users\87159\WorkBuddy\2026-05-28-22-10-10\index.html'
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(html)

print("DONE: {0} ({1} bytes)".format(output_path, os.path.getsize(output_path)))
