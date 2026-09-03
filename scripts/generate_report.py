#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机械装置 + 控制方法组合型专利价值评估 —— 多页 A4 报告生成器

读取评估 JSON（结构见 SKILL.md / scoring_rubric.md），输出自包含、可打印的
多页 A4 HTML 报告（2–3 页，内容自适应分页，无文字重叠），内嵌 SVG 图表，
无需任何外部依赖。

用法:
    python generate_report.py <input.json> [output.html]

若不指定 output.html，则在输入文件同目录生成 <输入名>.report.html
"""

import sys
import json
import math
from pathlib import Path
from datetime import datetime, date

# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------

def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def fmt(v, nd=1):
    try:
        return f"{float(v):.{nd}f}"
    except Exception:
        return str(v)


_MISSING = object()


def get(d, *keys, **kwargs):
    """安全多级取值。

    支持两种写法：
      - 关键字默认：get(d, "k1", "k2", default="x")
      - 遗留位置默认：get(d, "k", "默认值")   # 最后一个位置参数是默认值
    当使用关键字 default 时，不触发遗留分支，避免把多键路径末段误判为默认值。
    """
    default = kwargs.get("default", _MISSING)
    if default is _MISSING:
        if len(keys) >= 2:
            keys, default = keys[:-1], keys[-1]   # 遗留：末位位置参数是默认值
        else:
            default = None
    cur = d
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


# ----------------------------------------------------------------------------
# 图表生成（纯 SVG，无依赖）
# ----------------------------------------------------------------------------

def radar_svg(values, labels, size=280):
    """5 轴雷达图。values: list[float] 0-100; labels: list[str]"""
    cx = size / 2
    cy = size / 2
    R = size / 2 - 42
    n = len(values)
    angles = [-90 + i * 360 / n for i in range(n)]

    def pt(angle_deg, radius):
        a = math.radians(angle_deg)
        return cx + radius * math.cos(a), cy + radius * math.sin(a)

    # 网格环
    rings = ""
    for f in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{fmt(x,1)},{fmt(y,1)}" for x, y in (pt(ang, R * f) for ang in angles))
        rings += f'<polygon points="{pts}" fill="none" stroke="#d0d7e2" stroke-width="1"/>'

    # 轴线
    axes = ""
    for ang in angles:
        x, y = pt(ang, R)
        axes += f'<line x1="{cx}" y1="{cy}" x2="{fmt(x,1)}" y2="{fmt(y,1)}" stroke="#d0d7e2" stroke-width="1"/>'

    # 数据多边形
    data_pts = []
    for v, ang in zip(values, angles):
        x, y = pt(ang, R * clamp(v) / 100)
        data_pts.append((x, y))
    data_poly = " ".join(f"{fmt(x,1)},{fmt(y,1)}" for x, y in data_pts)
    data_svg = (f'<polygon points="{data_poly}" fill="rgba(37,99,235,0.22)" '
                f'stroke="#2563eb" stroke-width="2"/>')
    dots = "".join(f'<circle cx="{fmt(x,1)}" cy="{fmt(y,1)}" r="3" fill="#2563eb"/>' for x, y in data_pts)

    # 轴标签
    labels_svg = ""
    for lab, ang in zip(labels, angles):
        lx, ly = pt(ang, R + 22)
        a = math.radians(ang)
        anchor = "middle"
        if math.cos(a) > 0.2:
            anchor = "start"
        elif math.cos(a) < -0.2:
            anchor = "end"
        dy = 0
        if math.sin(a) > 0.5:
            dy = 10
        elif math.sin(a) < -0.5:
            dy = -4
        labels_svg += f'<text x="{fmt(lx,1)}" y="{fmt(ly+dy,1)}" font-size="11" fill="#334155" text-anchor="{anchor}">{lab}</text>'

    return (f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
            f'{rings}{axes}{data_svg}{dots}{labels_svg}</svg>')


def donut_svg(w_mech, w_ctrl, size=150):
    """贡献拆分甜甜圈。w_mech+w_ctrl≈1"""
    cx = size / 2
    cy = size / 2
    r = size / 2 - 14
    stroke = 20
    C = 2 * math.pi * r
    mech_len = clamp(w_mech, 0, 1) * C
    # 机械段（起点 -90°）
    mech = (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#2563eb" stroke-width="{stroke}" '
            f'stroke-dasharray="{fmt(mech_len,1)} {fmt(C-mech_len,1)}" '
            f'transform="rotate(-90 {cx} {cy})" stroke-linecap="butt"/>')
    # 控制段
    ctrl = (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#f59e0b" stroke-width="{stroke}" '
            f'stroke-dasharray="{fmt(C-mech_len,1)} {fmt(mech_len,1)}" '
            f'stroke-dashoffset="{fmt(-mech_len,1)}" transform="rotate(-90 {cx} {cy})" stroke-linecap="butt"/>')
    pct = (f'<text x="{cx}" y="{cy-4}" font-size="13" font-weight="bold" fill="#1e293b" text-anchor="middle">机械 {fmt(w_mech*100,0)}%</text>'
           f'<text x="{cx}" y="{cy+13}" font-size="12" fill="#64748b" text-anchor="middle">控制 {fmt(w_ctrl*100,0)}%</text>')
    return (f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
            f'{mech}{ctrl}{pct}</svg>')


def trl_bars_svg(m_trl, c_trl, w=300, h=80):
    """TRL 双水平条 0-9"""
    maxv = 9
    bar_w = w - 90
    x0 = 84
    rows = [("机械 TRL", m_trl, "#2563eb"), ("控制 TRL", c_trl, "#f59e0b")]
    out = f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">'
    y = 14
    for name, val, color in rows:
        v = clamp(val, 0, maxv)
        bw = bar_w * v / maxv
        out += f'<text x="0" y="{y+11}" font-size="11" fill="#334155">{name}</text>'
        out += f'<rect x="{x0}" y="{y}" width="{bar_w}" height="14" rx="3" fill="#eef2f7"/>'
        out += f'<rect x="{x0}" y="{y}" width="{fmt(bw,1)}" height="14" rx="3" fill="{color}"/>'
        out += f'<text x="{x0+bar_w+6}" y="{y+11}" font-size="11" font-weight="bold" fill="#1e293b">{fmt(val,0)}</text>'
        y += 34
    out += '</svg>'
    return out


def value_bars_svg(now, future, trend, w=320, h=90):
    """现状值 vs 未来期望值 水平条 + 箭头"""
    bar_w = w - 150
    x0 = 70
    arrow = {"上升": "↑", "平稳": "→", "下降": "↓"}.get(trend, "→")
    acolor = {"上升": "#16a34a", "平稳": "#64748b", "下降": "#dc2626"}.get(trend, "#64748b")
    rows = [("现状估值", now, "#475569"), ("未来期望", future, "#2563eb")]
    out = f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">'
    y = 14
    for name, val, color in rows:
        v = clamp(val)
        bw = bar_w * v / 100
        out += f'<text x="0" y="{y+11}" font-size="11" fill="#334155">{name}</text>'
        out += f'<rect x="{x0}" y="{y}" width="{bar_w}" height="14" rx="3" fill="#eef2f7"/>'
        out += f'<rect x="{x0}" y="{y}" width="{fmt(bw,1)}" height="14" rx="3" fill="{color}"/>'
        out += f'<text x="{x0+bar_w+6}" y="{y+11}" font-size="11" font-weight="bold" fill="#1e293b">{fmt(val,0)}</text>'
        y += 32
    out += (f'<text x="{x0}" y="{y+2}" font-size="12" font-weight="bold" fill="{acolor}">'
            f'趋势 {arrow} {trend}</text>')
    out += '</svg>'
    return out


# ----------------------------------------------------------------------------
# 综合评分计算（与 scoring_rubric.md 一致）
# ----------------------------------------------------------------------------

def compute_remaining_term(filing_date_str):
    """由申请日 + 20 年推算剩余期限（发明/utility 通用）；失败返回 None。"""
    try:
        fd = datetime.strptime(str(filing_date_str).strip(), "%Y-%m-%d").date()
        expiry = date(fd.year + 20, fd.month, fd.day)
        today = date.today()
        if expiry <= today:
            return "已届满（%s）" % expiry.isoformat()
        yrs = (expiry - today).days / 365.25
        return "约 %.1f 年（%s 届满）" % (yrs, expiry.isoformat())
    except Exception:
        return None


def compute(data):
    dims = get(data, "dimensions", default={})
    ts = get(data, "technical_split", default={})
    cf = get(data, "correction_factors", default={})
    legal = float(get(dims, "legal", default=0) or 0)
    market = float(get(dims, "market", default=0) or 0)
    claim = float(get(dims, "claim_quality", default=0) or 0)
    feas = float(get(dims, "feasibility", default=0) or 0)

    # 技术维度：优先用"机械/控制/耦合"三维子分加权合成（scoring_rubric §1.2）
    sm = get(ts, "mechanical_score")
    sc = get(ts, "control_score")
    sk = get(ts, "coupling_score")
    if sm is not None or sc is not None or sk is not None:
        sm = float(sm or 0)
        sc = float(sc or 0)
        sk = float(sk or 0)
        wm = float(get(ts, "mechanical_contribution", default=None)
                   or get(cf, "cf3_mechanical", default=None) or 0.0)
        wc = float(get(ts, "control_contribution", default=None)
                   or get(cf, "cf3_control", default=None) or 0.0)
        wk = float(get(ts, "coupling_contribution", default=None)
                   or get(cf, "cf3_coupling", default=None) or 0.0)
        wsum = wm + wc + wk
        if wsum <= 0:                      # 未给权重 → 三维等权
            wm, wc, wk, wsum = 1 / 3, 1 / 3, 1 / 3, 1.0
        tech_raw = (wm * sm + wc * sc + wk * sk) / wsum
        tech_from_split = True
    else:
        tech_raw = float(get(dims, "technical", default=0) or 0)
        tech_from_split = False

    cf1 = float(get(cf, "cf1", default=1.0) or 1.0)
    cf2 = float(get(cf, "cf2", default=0) or 0)
    cf4 = float(get(cf, "cf4", default=0) or 0)

    legal_100 = legal / 5 * 100 * cf1
    tech_100 = tech_raw / 5 * 100
    mkt_100 = market / 5 * 100
    claim_100 = claim / 5 * 100
    feas_100 = feas / 5 * 100

    composite = (0.25 * legal_100 + 0.30 * tech_100 + 0.20 * mkt_100
                 + 0.15 * claim_100 + 0.10 * feas_100)
    composite_final = clamp(composite + cf2 + cf4)

    return {
        "radar": [legal_100, tech_100, mkt_100, claim_100, feas_100],
        "composite_final": composite_final,
        "tech_from_split": tech_from_split,
    }


# ----------------------------------------------------------------------------
# HTML 报告组装
# ----------------------------------------------------------------------------

def build_html(data):
    p = get(data, "patent", default={})
    dims = get(data, "dimensions", default={})
    ts = get(data, "technical_split", default={})
    cf = get(data, "correction_factors", default={})
    comp = get(data, "comprehensive", default={})
    risks = get(data, "risks", default=[])
    frameworks = get(data, "frameworks", default=[])
    dim_notes = get(data, "dimension_notes", default={})

    calc = compute(data)
    radar_vals = calc["radar"]
    composite_final = calc["composite_final"]

    # 现状/未来值
    value_now = float(get(comp, "value_now", default=None) or composite_final)
    value_future = float(get(comp, "value_future", default=None) or value_now)
    trend = get(comp, "trend", default=None)
    if not trend:
        diff = value_future - value_now
        trend = "上升" if diff > 3 else ("下降" if diff < -3 else "平稳")
    grade = get(comp, "grade", default=None)
    if not grade:
        s = composite_final
        grade = ("高" if s >= 80 else "中高" if s >= 65 else "中" if s >= 50 else "中低" if s >= 35 else "低")

    # 图表
    radar = radar_svg(radar_vals, ["法律价值", "技术价值", "市场商业", "权利要求", "实施落地"])
    w_mech = float(get(ts, "mechanical_contribution", default=0.5) or 0.5)
    w_ctrl = float(get(ts, "control_contribution", default=(1 - w_mech)) or (1 - w_mech))
    donut = donut_svg(w_mech, w_ctrl)
    m_trl = float(get(ts, "mechanical_trl", default=0) or 0)
    c_trl = float(get(ts, "control_trl", default=0) or 0)
    trl = trl_bars_svg(m_trl, c_trl)
    vbars = value_bars_svg(value_now, value_future, trend)

    # 维度定性文本卡片
    def dim_card(title, score, note):
        sc = float(score or 0)
        return (f'<div class="card"><div class="card-h"><span>{title}</span>'
                f'<b>{fmt(sc,1)}/5</b></div><div class="card-b">{note or "—"}</div></div>')

    dim_cards = (
        dim_card("法律价值", get(dims, "legal"), get(dim_notes, "legal"))
        + dim_card("技术价值", get(dims, "technical"), get(dim_notes, "technical"))
        + dim_card("市场商业价值", get(dims, "market"), get(dim_notes, "market"))
        + dim_card("权利要求质量", get(dims, "claim_quality"), get(dim_notes, "claim_quality"))
        + dim_card("实施落地可行性", get(dims, "feasibility"), get(dim_notes, "feasibility"))
    )

    # 技术三拆分（子分加权展示）
    def split_block(title, eval_text, score):
        ss = "" if score is None else f'<span class="ss">{fmt(float(score or 0),1)}/5</span>'
        return (f'<div class="split"><div class="split-h">{title}{ss}</div>'
                f'<div class="split-b">{eval_text or "—"}</div></div>')

    tech3 = (
        split_block("① 机械装置创新评价", get(ts, "mechanical_eval"), get(ts, "mechanical_score"))
        + split_block("② 控制方法创新评价", get(ts, "control_eval"), get(ts, "control_score"))
        + split_block("③ 软硬件耦合协同创新评价", get(ts, "coupling_eval"), get(ts, "coupling_score"))
    )

    # 风险清单
    level_color = {"高": "#dc2626", "中": "#f59e0b", "低": "#16a34a"}
    risk_html = ""
    if risks:
        for r in risks:
            lvl = get(r, "level", default="中")
            item = get(r, "item", default="")
            c = level_color.get(lvl, "#64748b")
            risk_html += f'<div class="risk"><span class="badge" style="background:{c}">{lvl}</span>{item}</div>'
    else:
        risk_html = '<div class="risk">未识别到显式风险</div>'

    # 修正因子
    cf1 = float(get(cf, "cf1", default=1.0) or 1.0)
    cf2 = float(get(cf, "cf2", default=0) or 0)
    cf3m = float(get(cf, "cf3_mechanical", default=w_mech) or w_mech)
    cf3c = float(get(cf, "cf3_control", default=w_ctrl) or w_ctrl)
    cf3k = float(get(cf, "cf3_coupling", default=get(ts, "coupling_contribution", 0)) or get(ts, "coupling_contribution", 0) or 0)
    cf4 = float(get(cf, "cf4", default=0) or 0)
    cf_html = (
        f'<div class="cf">Cf1 取证难度系数 ×{fmt(cf1,2)} — {get(cf,"cf1_note","")}</div>'
        f'<div class="cf">Cf2 软硬件成熟度不一致 {fmt(cf2,0)} 分 — {get(cf,"cf2_note","")}</div>'
        f'<div class="cf">Cf3 创新贡献拆分 机械 {fmt(cf3m*100,0)}% / 控制 {fmt(cf3c*100,0)}% / 耦合 {fmt(cf3k*100,0)}%</div>'
        f'<div class="cf">Cf4 装置-方法对应缺陷 {fmt(cf4,0)} 分 — {get(cf,"cf4_note","")}</div>'
    )

    fw_html = "、".join(frameworks) if frameworks else "WIPO / IPscore / Ocean Tomo / Relecura / 国知局 / LRF（融合）"

    juris = get(p, "jurisdictions", default=[])
    juris_s = "、".join(juris) if juris else "—"
    scenario = get(p, "combination_scenario", default="—")
    grade_color = {"高": "#16a34a", "中高": "#2563eb", "中": "#0891b2", "中低": "#f59e0b", "低": "#dc2626"}.get(grade, "#2563eb")

    # 剩余期限：若 JSON 未给，依申请日 +20 年自动推算
    remaining_term = get(p, "remaining_term")
    if not remaining_term:
        rt = compute_remaining_term(get(p, "filing_date", ""))
        if rt:
            remaining_term = rt

    html = f"""
<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>组合型专利价值评估报告</title>
<style>
@page {{ size: A4; margin: 12mm; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:#eef2f7; font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif; color:#1e293b; }}
.page {{ width: 794px; margin: 0 auto; padding: 14px 20px 20px; background:#fff; box-shadow:0 1px 6px rgba(0,0,0,.12); }}
.section {{ margin-top: 14px; }}
.section-title {{ font-size:13px; font-weight:bold; color:#1d4ed8; border-left:4px solid #2563eb; padding-left:8px; margin:6px 0 8px; }}
.header {{ display:flex; justify-content:space-between; align-items:flex-start; border-bottom:3px solid #2563eb; padding-bottom:8px; }}
.header h1 {{ font-size:17px; margin:0 0 2px; line-height:1.3; }}
.header .sub {{ font-size:11px; color:#64748b; line-height:1.4; }}
.grade {{ background:{grade_color}; color:#fff; padding:6px 14px; border-radius:8px; font-size:15px; font-weight:bold; text-align:center; white-space:nowrap; }}
.grade small {{ display:block; font-size:10px; font-weight:normal; }}
.meta {{ display:flex; flex-wrap:wrap; gap:6px 18px; font-size:11px; color:#475569; margin:8px 0 4px; }}
.meta b {{ color:#1e293b; }}
.grid {{ display:grid; grid-template-columns: 300px 1fr; gap:14px; }}
.panel {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px 12px; }}
.panel h2 {{ font-size:12px; margin:0 0 6px; color:#2563eb; border-left:3px solid #2563eb; padding-left:6px; }}
.radar-wrap {{ text-align:center; }}
.right-col {{ display:flex; flex-direction:column; gap:10px; }}
.donut-row {{ display:flex; align-items:center; gap:12px; }}
.donut-row .info {{ font-size:11px; color:#475569; }}
.donut-row .info b {{ color:#1e293b; }}
.cards {{ display:grid; grid-template-columns: 1fr 1fr; gap:8px; }}
.card {{ background:#fff; border:1px solid #e2e8f0; border-radius:6px; padding:7px 9px; }}
.card-h {{ display:flex; justify-content:space-between; font-size:11px; font-weight:bold; }}
.card-h b {{ color:#2563eb; }}
.card-b {{ font-size:10.5px; color:#64748b; margin-top:3px; line-height:1.45; }}
.splits {{ display:grid; grid-template-columns: 1fr 1fr 1fr; gap:8px; }}
.split {{ background:#fff; border:1px solid #e2e8f0; border-radius:6px; padding:7px 9px; }}
.split-h {{ font-size:11px; font-weight:bold; color:#0891b2; margin-bottom:3px; }}
.split-h .ss {{ float:right; color:#0e7490; font-weight:bold; }}
.split-b {{ font-size:10.5px; color:#64748b; line-height:1.45; }}
.bottom {{ display:grid; grid-template-columns: 1fr 1fr; gap:14px; }}
.risk {{ font-size:11px; margin:4px 0; line-height:1.45; }}
.badge {{ color:#fff; font-size:10px; padding:1px 6px; border-radius:4px; margin-right:6px; white-space:nowrap; }}
.cf {{ font-size:10.5px; color:#475569; margin:3px 0; line-height:1.4; }}
.qual {{ font-size:11px; color:#334155; margin-top:4px; line-height:1.55; }}
.footnote {{ font-size:10px; color:#94a3b8; line-height:1.5; margin-top:6px; }}
.footer {{ margin-top:14px; font-size:10px; color:#64748b; border-top:1px solid #e2e8f0; padding-top:8px; line-height:1.5; }}
@media print {{
  body {{ background:#fff; }}
  .page {{ width:auto; margin:0; padding:0; box-shadow:none; }}
  .panel, .card, .split, .risk {{ page-break-inside: avoid; }}
  .grid, .cards, .splits, .bottom {{ page-break-inside: avoid; }}
}}
</style></head>
<body>
<div class="page">
  <div class="header">
    <div>
      <h1>{get(p,'title','专利名称未知')}</h1>
      <div class="sub">专利号：{get(p,'number','—')} ｜ 申请人：{get(p,'applicant','—')} ｜ 组合场景：{scenario}</div>
    </div>
    <div class="grade">{grade}<small>综合价值分级</small></div>
  </div>

  <div class="meta">
    <span>法律状态：<b>{get(p,'legal_status','—')}</b></span>
    <span>申请日：<b>{get(p,'filing_date','—')}</b></span>
    <span>剩余期限：<b>{remaining_term or '—'}</b></span>
    <span>布局地域：<b>{juris_s}</b></span>
    <span>同族数量：<b>{get(p,'family_count','—')}</b></span>
  </div>

  <div class="section">
    <div class="section-title">一、价值概览 · 五维雷达 / 创新拆分 / 估值趋势</div>
    <div class="grid">
      <div class="panel">
        <h2>五维价值雷达</h2>
        <div class="radar-wrap">{radar}</div>
      </div>
      <div class="right-col">
        <div class="panel">
          <h2>创新贡献拆分 & TRL 成熟度</h2>
          <div class="donut-row">
            <div>{donut}</div>
            <div class="info">
              创新类型：<b>{get(ts,'innovation_type','—')}</b><br>
              机械主导 / 控制主导 / 耦合协同
            </div>
          </div>
          <div style="margin-top:6px">{trl}</div>
        </div>
        <div class="panel">
          <h2>现有估值 → 未来期望值</h2>
          {vbars}
        </div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">二、五维分项评分明细</div>
    <div class="cards">{dim_cards}</div>
  </div>

  <div class="section">
    <div class="section-title">三、技术创新三维拆分评价（机械 / 控制 / 耦合）</div>
    <div class="splits">{tech3}</div>
  </div>

  <div class="section">
    <div class="section-title">四、关键风险清单 & 专属修正因子（Cf1–Cf4）</div>
    <div class="bottom">
      <div class="panel">
        <h2>关键风险清单</h2>
        {risk_html}
      </div>
      <div class="panel">
        <h2>专属修正因子（Cf1–Cf4）</h2>
        {cf_html}
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">五、综合研判结论 & 评估方法说明</div>
    <div class="panel">
      <h2>综合研判结论</h2>
      <div class="qual"><b>综合价值分级：{grade}（综合得分 {fmt(composite_final,1)}）</b><br>{get(comp,'qualitative','—')}</div>
    </div>
    <div class="panel" style="margin-top:8px">
      <h2>评估方法说明</h2>
      <div class="cf">① 法律 / 市场 / 权项质量 / 实施落地 四维：采用世界流行方法融合评分（{fw_html}）。</div>
      <div class="cf">② 技术价值：采用"机械 / 控制 / 耦合"三维子分加权 —— 技术价值 = wm·SM + wc·SC + wk·SK（wm+wc+wk=1，来自 Cf3 创新贡献拆分）。</div>
      <div class="cf">③ 综合得分 = 0.25·法律 + 0.30·技术 + 0.20·市场 + 0.15·权项 + 0.10·落地，叠加 Cf2 / Cf4 修正。</div>
      <div class="footnote">数据来源：{get(p,'metadata_source','公开专利库检索补全')}。本报告为辅助决策参考，正式价值判断建议结合 CNIPA 官方登记簿与 FTO 检索。</div>
    </div>
  </div>

  <div class="footer">
    <div><b>对标全球评估体系：</b>{fw_html}</div>
    <div><b>数据来源：</b>{get(p,'metadata_source','—')} ｜ <b>生成日期：</b>{date.today().isoformat()}</div>
  </div>
</div>
</body></html>
"""
    return html


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_report.py <input.json> [output.html]")
        sys.exit(1)
    in_path = Path(sys.argv[1]).resolve()
    if not in_path.exists():
        print(f"输入文件不存在: {in_path}")
        sys.exit(1)
    out_path = sys.argv[2] if len(sys.argv) > 2 else str(in_path.with_suffix("")) + ".report.html"
    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    html = build_html(data)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ 报告已生成: {out_path}")


if __name__ == "__main__":
    main()
