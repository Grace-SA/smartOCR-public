#!/usr/bin/env python3
"""Build a read-only HTML view of frozen receipt evaluations; never run OCR.

Run again after evaluation JSON files have been written. Missing evaluations are
shown as pending and are never substituted with the partial47 development run.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {"merchant": "商家", "date": "交易日期", "total": "票面交易总额"}
ENGINES = {"paddle": "Paddle OCR", "unlimited": "Unlimited OCR", "oxr": "OXR"}
VISIBILITY = {
    "outside_frame": "原图未拍入", "redacted": "原图已遮盖",
    "subtotal_only": "只有小计，缺交易总额", "ambiguous_or_cropped": "商家模糊或截断",
    "not_required_for_exclusion": "该字段尚未视觉核对", "readable": "原图可读",
    "readable_pre_surcharge_total": "票面总额可读（附加费前）",
}
UNAVAILABLE = {"outside_frame", "redacted", "subtotal_only", "ambiguous_or_cropped"}


def esc(value):
    return html.escape(str(value), quote=True)


def read_json(path, fallback, notices):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        notices.append(f"无法读取 {path.relative_to(ROOT)}：{exc}")
        return fallback


def records(value):
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    if isinstance(value, dict):
        return records(value.get("records", value.get("results", [])))
    return []


def by_id(value):
    return {str(r["id"]): r for r in records(value) if r.get("id") is not None}


def local_url(value):
    """Only link files inside this project, relative to output/quality/index.html."""
    if not value:
        return None
    try:
        path = Path(str(value))
        absolute = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
        relative = absolute.relative_to(ROOT)
        if not relative.parts or relative.parts[0] not in {"data", "research", "output"}:
            return None
        return "../../" + quote(relative.as_posix(), safe="/-_.")
    except (OSError, ValueError):
        return None


def external_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else None
    except ValueError:
        return None


def link(url, label):
    if not url:
        return f'<span class="muted">{esc(label)}不可用</span>'
    return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(label)}</a>'


def compare(actual, expected, field):
    if expected is None:
        return None
    if actual is None:
        return False
    if field == "merchant":
        clean = lambda v: re.sub(r"[^a-z0-9]", "", str(v).lower().replace('&',' and '))
        return clean(actual) == clean(expected)
    if field == "total":
        try:
            return Decimal(str(actual)).quantize(Decimal(".01")) == Decimal(str(expected)).quantize(Decimal(".01"))
        except InvalidOperation:
            return False
    return actual == expected


def value_text(value, field):
    if value is None or value == "":
        return "—"
    if field == "total":
        try:
            return f"AUD {Decimal(str(value)):.2f}"
        except InvalidOperation:
            pass
    return str(value)


def engine_complete(engine):
    """A successful process alone is insufficient: require usable, uncapped text."""
    if not isinstance(engine, dict) or engine.get("status") != "complete":
        return False
    if engine.get("has_text") is False or engine.get("recognition_complete") is False:
        return False
    if engine.get("inference_completed") is False:
        return False
    variants = engine.get("variants", [])
    if not variants:
        return False
    if engine.get("recognition_complete") is True and engine.get("has_text") is True:
        return any(v.get('quality',{}).get('recognition_complete') for v in variants)
    return any(isinstance(v, dict) and not v.get('normalized',{}).get('capped') and str(v.get("normalized", {}).get("text", "")).strip() for v in variants)


def engine_status(engine):
    if engine_complete(engine):
        return "有效完成"
    if not engine:
        return "未完成 / 无输出"
    if engine.get("capped"):
        return "输出被截断"
    if engine.get("has_text") is False:
        return "无有效文字"
    if engine.get("recognition_complete") is False:
        return "识别未完整结束"
    return str(engine.get("error") or engine.get("status") or "完成证据不足")


def load_set(name, manifest_path, audit, baseline, notices):
    evaluation_path = ROOT / "research/evaluations" / name / "evaluation.json"
    predictions_path = evaluation_path.with_name("predictions.json")
    evaluation = read_json(evaluation_path, {}, notices)
    predictions = by_id(read_json(predictions_path, [], notices))
    manifest = records(read_json(ROOT / manifest_path, [], notices))
    results = by_id(evaluation)
    if not manifest:
        # Incomplete file production must remain visible; do not borrow another corpus.
        manifest = [{"id": key} for key in results]
    errors = []
    if not (ROOT / manifest_path).exists():
        errors.append("冻结样本清单尚未生成")
    if not evaluation_path.exists():
        errors.append("评测结果尚未完成")
    if not predictions_path.exists():
        errors.append("三模型提取结果尚未完成")
    if evaluation and (ROOT / manifest_path).exists():
        digest = hashlib.sha256((ROOT / manifest_path).read_bytes()).hexdigest()
        if evaluation.get("manifest_sha256") and evaluation["manifest_sha256"] != digest:
            errors.append("评测记录的样本清单哈希与当前文件不同；本页结果不能视为当前冻结集验收")
    rows = []
    for item in manifest:
        rid = str(item.get("id", ""))
        result, prediction, visual, old = results.get(rid, {}), predictions.get(rid, {}), audit.get(rid, {}), baseline.get(rid, {})
        expected = dict(result.get("expected", {}))
        for field in FIELDS:
            if field not in expected:
                expected[field] = visual.get(field, {}).get("value")
        actual = {f: prediction.get(f) if prediction else result.get("actual", {}).get(f) for f in FIELDS}
        has_result = rid in results
        extraction_pending = not prediction and all(actual[f] is None for f in FIELDS)
        checks = {f: compare(actual[f], expected.get(f), f) if has_result and not extraction_pending else None for f in FIELDS}
        engines = prediction.get("ocr_engines", {})
        complete = [name for name in ENGINES if engine_complete(engines.get(name, {}))]
        known = all(expected.get(f) is not None for f in FIELDS)
        correct = has_result and known and all(checks[f] is True for f in FIELDS)
        failed_fields = [f for f in FIELDS if has_result and expected.get(f) is not None and checks[f] is False]
        missing_fields = [f for f in FIELDS if visual.get(f, {}).get("visibility") in UNAVAILABLE]
        unknown_fields = [f for f in FIELDS if expected.get(f) is None and f not in missing_fields]
        reasons = []
        if not has_result or extraction_pending:
            reasons.append("该样本的 v2 提取尚未完成；不把未运行或缺缓存计为已识别后的字段错误")
        for field in missing_fields:
            reasons.append(f"{FIELDS[field]}：{VISIBILITY.get(visual[field].get('visibility'), '原图不可核对')}；不能要求模型补造")
        for field in unknown_fields:
            reasons.append(f"{FIELDS[field]}：尚无可核对参考值")
        for field in failed_fields:
            reasons.append(f"{FIELDS[field]}识别不符：参考 {value_text(expected[field], field)}；实际 {value_text(actual[field], field)}")
        if has_result and len(complete) != 3:
            reasons.append("三模型尚未全部有效完成：" + "、".join(ENGINES[n] for n in ENGINES if n not in complete))
        if result.get("error"):
            reasons.append(str(result["error"]))
        if not reasons:
            reasons.append("三个核心字段均与参考值一致，且三模型有效完成")
        if not has_result or extraction_pending:
            status, label = "pending", "待完成"
        elif failed_fields:
            status, label = "error", "识别错误"
        elif missing_fields:
            status, label = "source", "原图缺字段"
        elif unknown_fields:
            status, label = "unverified", "参考未完整"
        elif len(complete) != 3:
            status, label = "model", "模型未完整"
        else:
            status, label = "pass", "通过"
        rows.append(dict(id=rid, item=item, result=result, prediction=prediction, old=old, visual=visual,
                         expected=expected, actual=actual, checks=checks, engines=engines, complete=complete,
                         known=known, correct=correct, failed_fields=failed_fields, missing_fields=missing_fields,
                         has_result=has_result, extraction_pending=extraction_pending,
                         reasons=reasons, status=status, label=label))
    return {"name": name, "rows": rows, "evaluation": evaluation, "errors": errors,
            "manifest_path": manifest_path, "evaluation_path": evaluation_path,
            "predictions_path": predictions_path, "manifest_count": len(manifest)}


def stat(label, value, note=""):
    return f'<div class="stat"><span>{esc(label)}</span><strong>{esc(value)}</strong><small>{esc(note)}</small></div>'


def field_table(rows, old=False):
    output = ['<table class="scores"><thead><tr><th>可核对字段</th>']
    if old:
        output.append('<th>v1 正确 / 可核对</th>')
    output.append('<th>v2 正确 / 可核对</th><th>v2 尚未完成</th></tr></thead><tbody>')
    for field, label in FIELDS.items():
        known = [r for r in rows if r["expected"].get(field) is not None]
        score = sum(r["checks"][field] is True for r in known)
        output.append(f'<tr><th>{esc(label)}</th>')
        if old:
            oldscore = sum(compare(r["old"].get(field), r["expected"][field], field) is True for r in known)
            output.append(f'<td>{oldscore} / {len(known)}</td>')
        output.append(f'<td>{score} / {len(known)}</td><td>{sum(not r["has_result"] or r["extraction_pending"] for r in known)}</td></tr>')
    return "".join(output) + "</tbody></table>"


def receipt_card(row, old=False):
    item, prediction = row["item"], row["prediction"]
    path = item.get("local_path") or prediction.get("source", {}).get("local_path") or row["visual"].get("image")
    source = item.get("source_page_url") or item.get("source_url") or prediction.get("source", {}).get("page_url")
    image_href = local_url(path)
    merchant = row["expected"].get("merchant") or row["actual"].get("merchant") or row["old"].get("merchant") or "商家待核对"
    search = " ".join([row["id"], str(merchant), *(str(v or "") for v in row["expected"].values()), *(str(v or "") for v in row["actual"].values())])
    tags = [row["status"]]
    if row["missing_fields"]:
        tags.append("source")
    if row["failed_fields"]:
        tags.append("error")
    output = [f'<details class="receipt" data-status="{esc(" ".join(tags))}" data-search="{esc(search.lower())}">',
              f'<summary><span class="receipt-title"><b>{esc(merchant)}</b><code>{esc(row["id"])}</code></span>',
              f'<span class="badge {esc(row["status"])}">{esc(row["label"])}</span></summary>', '<div class="receipt-body"><div class="image-panel">']
    if image_href:
        output.append(f'<a href="{esc(image_href)}" target="_blank" rel="noopener"><img src="{esc(image_href)}" loading="lazy" alt="{esc(row["id"])} 原始票据" /></a>')
    output.append('<p class="links">' + link(image_href, "打开原图") + " · " + link(external_url(source), "来源网页") + "</p>")
    if item.get("sha256"):
        output.append(f'<p class="hash">SHA-256 {esc(item["sha256"])}</p>')
    output.append('</div><div class="comparison"><table><thead><tr><th>字段</th><th>视觉参考值</th>')
    if old:
        output.append('<th>旧 v1</th>')
    output.append('<th>新 v2</th><th>核对状态</th></tr></thead><tbody>')
    for field, label in FIELDS.items():
        expected = row["expected"].get(field)
        visibility = row["visual"].get(field, {}).get("visibility")
        if expected is None:
            match_text = VISIBILITY.get(visibility, "参考值待核对")
        elif not row["has_result"] or row["extraction_pending"]:
            match_text = "v2 待完成"
        else:
            match_text = "一致" if row["checks"][field] else "不一致 / 未提取"
        output.append(f'<tr><th>{esc(label)}</th><td>{esc(value_text(expected, field))}</td>')
        if old:
            old_value = row["old"].get(field)
            old_match = compare(old_value, expected, field)
            output.append(f'<td class="{"good" if old_match is True else "bad" if old_match is False else ""}">{esc(value_text(old_value, field))}</td>')
        output.append(f'<td>{esc(value_text(row["actual"][field], field))}</td><td class="{"bad" if row["checks"][field] is False else ""}">{esc(match_text)}</td></tr>')
    output.append('</tbody></table><ul class="reasons">' + "".join(f'<li>{esc(reason)}</li>' for reason in row["reasons"]) + "</ul>")
    output.append('<div class="engines">' + "".join(f'<span class="engine {"ok" if name in row["complete"] else "waiting"}"><b>{esc(label)}</b> {esc(engine_status(row["engines"].get(name, {})))}</span>' for name, label in ENGINES.items()) + '</div>')
    notes = row["visual"].get("notes")
    if notes:
        output.append(f'<p class="muted">原图复核备注：{esc(notes)}</p>')
    warnings = row["result"].get("warnings") or prediction.get("warnings") or []
    if warnings:
        output.append('<details class="evidence"><summary>提取提示</summary><ul>' + "".join(f'<li>{esc(w)}</li>' for w in warnings) + '</ul></details>')
    evidence = row["result"].get("field_evidence") or prediction.get("field_evidence") or {}
    evidence_rows = []
    for field in FIELDS:
        detail = evidence.get(field, {})
        if detail.get("text"):
            evidence_rows.append(f'<b>{esc(FIELDS[field])}</b><pre>{esc(detail["text"])}</pre>')
    if evidence_rows:
        output.append('<details class="evidence"><summary>查看核心字段 OCR 依据</summary>' + "".join(evidence_rows) + '</details>')
    output.append('</div></div></details>')
    return "".join(output)


def set_section(data, old=False):
    rows = data["rows"]
    known = [r for r in rows if r["known"]]
    correct = sum(r["correct"] for r in rows)
    three = sum(len(r["complete"]) == 3 for r in rows)
    passed = sum(r["correct"] and len(r["complete"]) == 3 for r in rows)
    done = sum(r["has_result"] for r in rows)
    title = "原 100 份：旧 v1 与新 v2" if old else "新 100 份：核心流程验收"
    output = [f'<section id="{esc(data["name"])}" class="corpus"><div class="section-heading"><h2>{esc(title)}</h2>',
              f'<span class="muted">样本清单 {data["manifest_count"]} 份 · 评测记录 {done} 份</span></div>']
    for error in data["errors"]:
        output.append(f'<p class="notice">{esc(error)}</p>')
    if data["manifest_count"] != 100:
        output.append(f'<p class="notice">当前清单为 {data["manifest_count"]} 份，目标为固定 100 份。本页不能据此宣称 100 份通过。</p>')
    output.append('<div class="stats">')
    if old:
        old_correct = sum(all(compare(r["old"].get(f), r["expected"][f], f) is True for f in FIELDS) for r in known)
        output.extend([stat("旧 v1 三字段一致", f"{old_correct} / {len(known)}", "仅完整可核对票据"),
                       stat("新 v2 三字段一致", f"{correct} / {len(known)}", "未完成不计为正确"),
                       stat("原图缺核心字段", str(sum(bool(r["missing_fields"]) for r in rows)), "与识别错误分别统计"),
                       stat("三模型有效完成", f"{three} / 100", "Paddle + Unlimited + OXR")])
    else:
        output.extend([stat("三字段全部正确", f"{correct} / 100", "商家、日期、票面交易总额"),
                       stat("三模型有效完成", f"{three} / 100", "有文字、未截断、识别完整结束"),
                       stat("满足全部验收条件", f"{passed} / 100", "三字段一致且三模型有效完成"),
                       stat("已有提取结果", f"{sum(bool(r['prediction']) for r in rows)} / 100", "未完成的样本仍待验收")])
    output.append('</div>')
    output.append('<p class="muted">各模型有效完成：' + " · ".join(f'{esc(label)} {sum(name in r["complete"] for r in rows)}/100' for name, label in ENGINES.items()) + '</p>')
    if old:
        output.append('<p>以下对照保留原始 100 份。可读字段提取错误计为识别错误；未拍入、遮盖或只有小计的字段不设虚构答案。原图缺字段与其他字段识别错误可能同时存在。v1 是历史输出，v2 是三模型输出。</p>')
    output.append(field_table(rows, old))
    if data["evaluation"].get("created_at"):
        output.append(f'<p class="muted">评测时间 {esc(data["evaluation"]["created_at"])}</p>')
    output.append('<p class="links">' + link(local_url(data["manifest_path"]), "冻结清单") + " · " + link(local_url(data["evaluation_path"]) if data["evaluation_path"].exists() else None, "评测 JSON") + " · " + link(local_url(data["predictions_path"]) if data["predictions_path"].exists() else None, "提取 JSON") + '</p>')
    output.append('<div class="filters"><label>搜索 <input type="search" placeholder="样本 ID、商家、日期或金额" aria-label="搜索票据" /></label><label>显示 <select aria-label="筛选结果"><option value="all">全部票据</option><option value="error">识别错误</option><option value="source">原图缺字段</option><option value="model">模型未完整</option><option value="pending">待完成</option><option value="unverified">参考未完整</option><option value="pass">通过</option></select></label><button type="button" class="expand">展开当前结果</button><span class="visible-count muted"></span></div>')
    output.append('<div class="receipts">' + "".join(receipt_card(r, old) for r in rows) + '</div></section>')
    return "".join(output)


CSS = """
:root{color-scheme:light;--ink:#17302d;--muted:#5e6f6b;--line:#d7e2dc;--paper:#fff;--accent:#0b6754}
*{box-sizing:border-box}body{margin:0;background:#f3f6f2;color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1380px;margin:auto;padding:36px 28px 80px}h1{font-size:32px;letter-spacing:-.8px;margin:8px 0 12px}h2{font-size:23px;margin:0}p{margin:12px 0}a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:3px}nav{display:flex;gap:20px;margin:22px 0}.eyebrow{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:var(--accent);font-weight:700}.intro{max-width:980px}.scope{padding:18px 22px;background:#e6eee8;border-radius:12px}.scope p{margin:5px 0}.muted,small{color:var(--muted)}.corpus{margin-top:38px;padding:26px;background:var(--paper);border:1px solid var(--line);border-radius:16px}.section-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:22px 0 10px}.stat{padding:18px;border:1px solid var(--line);border-radius:11px;background:#f8faf7}.stat span,.stat small{display:block}.stat strong{display:block;font-size:31px;line-height:1.3;margin:10px 0;letter-spacing:-1px}.stat small{font-size:12px}.notice{padding:12px 16px;background:#fff4d9;border-left:4px solid #c29029;border-radius:6px}.scores{max-width:760px;margin:18px 0}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:11px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}th{font-weight:600;background:#f5f8f4}.filters{display:flex;gap:16px;align-items:center;flex-wrap:wrap;padding:17px 0;border-top:1px solid var(--line);margin-top:22px}.filters label{display:flex;align-items:center;gap:8px}input,select,button{font:inherit;border:1px solid #bccbc2;border-radius:7px;padding:9px 11px;background:#fff;color:var(--ink)}input{min-width:260px}button{cursor:pointer}button:hover{background:#e9f2ec}.receipt{border:1px solid var(--line);border-radius:10px;margin:10px 0;overflow:hidden}.receipt>summary{cursor:pointer;padding:16px;display:flex;align-items:center;justify-content:space-between;gap:14px;background:#fbfcfa}.receipt>summary::before{content:'＋';color:var(--accent);font-size:20px}.receipt[open]>summary::before{content:'−'}.receipt-title{flex:1;min-width:0}.receipt-title b{display:block;font-size:16px}.receipt-title code{font-size:12px;color:var(--muted);overflow-wrap:anywhere}.badge{font-size:12px;font-weight:600;border-radius:999px;padding:4px 10px;background:#edf0ed;white-space:nowrap}.badge.pass,.engine.ok{background:#dcefe3;color:#176143}.badge.error{background:#fde3dd;color:#9f3425}.badge.source,.badge.model,.badge.unverified{background:#fff0cf;color:#795616}.receipt-body{display:grid;grid-template-columns:280px minmax(0,1fr);gap:24px;padding:20px;border-top:1px solid var(--line)}.image-panel{text-align:center}.image-panel img{width:100%;max-height:440px;object-fit:contain;background:#f1f3ef;border:1px solid var(--line);border-radius:6px}.hash{font-size:10px;color:var(--muted);overflow-wrap:anywhere}.links{font-size:13px}.comparison{min-width:0}.bad{color:#a23326}.good{color:#176143}.reasons{padding-left:20px;margin:16px 0}.reasons li{margin:7px 0}.engines{display:flex;gap:7px;flex-wrap:wrap}.engine{padding:6px 9px;background:#f4ebda;border-radius:6px;font-size:12px;overflow-wrap:anywhere}.evidence{margin-top:15px;border-top:1px solid var(--line);padding-top:12px}.evidence summary{cursor:pointer;color:var(--accent)}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.65 ui-monospace,monospace;background:#f6f8f5;padding:12px;border-radius:6px}.receipt[hidden]{display:none}footer{margin-top:28px;font-size:12px;color:var(--muted)}@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}.receipt-body{grid-template-columns:1fr}.image-panel img{max-height:360px}.image-panel{max-width:400px;margin:auto}main{padding:22px 14px}.corpus{padding:18px}.comparison{overflow:auto}}@media(max-width:500px){.stats{gap:8px}.stat{padding:12px}.stat strong{font-size:27px}h1{font-size:27px}th,td{padding:8px;font-size:12px}input{min-width:180px;width:100%}.filters label{width:100%}}@media print{.filters{display:none}.corpus{break-before:page}.receipt-body{grid-template-columns:200px 1fr}}
"""
JS = """
document.querySelectorAll('.corpus').forEach(section=>{
  const input=section.querySelector('input'), select=section.querySelector('select');
  const cards=[...section.querySelectorAll('.receipt')], counter=section.querySelector('.visible-count');
  const filter=()=>{const q=input.value.toLowerCase().trim(),status=select.value;let shown=0;
    cards.forEach(card=>{const ok=(!q||card.dataset.search.includes(q))&&(status==='all'||card.dataset.status.split(' ').includes(status));card.hidden=!ok;if(ok)shown++;});
    counter.textContent=shown+' / '+cards.length+' 份';};
  input.addEventListener('input',filter);select.addEventListener('change',filter);filter();
  section.querySelector('.expand').addEventListener('click',event=>{const visible=cards.filter(c=>!c.hidden);const expand=visible.some(c=>!c.open);visible.forEach(c=>c.open=expand);event.currentTarget.textContent=expand?'收起当前结果':'展开当前结果';});
});
"""


def build(output):
    notices = []
    audit = by_id(read_json(ROOT / "research/visibility_audit.json", {}, notices))
    baseline = by_id(read_json(ROOT / "data/baseline_v1/receipts.json", [], notices))
    validation = load_set("validation100", "research/validation100_manifest.json", {}, {}, notices)
    original = load_set("original100", "research/sample_100_manifest.json", audit, baseline, notices)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    content = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>票据提取质量验收</title>',
               '<style>' + CSS + '</style></head><body><main><header><div class="eyebrow">Receipt OCR · Quality Review</div><h1>票据提取质量验收</h1>',
               '<p class="intro">逐张检查原图与提取结果。此页面由已经落盘的评测结果生成，不启动识别，也不修改参考值。</p>',
               '<div class="scope"><p><b>本轮范围：</b>商家、含年份的交易日期、票面交易总额。金额按分核对，保留退款负号与零元；现金舍入、支付金额与商品明细不是本轮三个核心字段的替代值。</p>',
               '<p><b>通过条件：</b>三个字段与参考值一致，且 Paddle OCR、Unlimited OCR、OXR 各至少有一份有效文字、未截断的结果。商家比较忽略大小写、空格、标点，并将 &amp; 与 and 视为相同；日期和金额严格比较。</p>',
               '<p><b>评测限制：</b>固定样本集经过反复调试，不是独立盲测。参考值来自 AI 视觉核对，尚非独立人工金标准；固定集通过不能解释为所有票据的普遍 100% 准确率。缺失结果不会计为通过。</p></div>',
               '<p class="links">参考文字修订有独立留档：'+link(local_url('research/validation100_reference_changes.json'),'修订原因与前后值')+'。原图与冻结样本清单不变。</p>',
               '<nav><a href="#validation100">新 100 份验收</a><a href="#original100">原 100 份前后对照</a></nav></header>']
    content.extend(f'<p class="notice">{esc(n)}</p>' for n in notices)
    content.extend([set_section(validation), set_section(original, old=True),
                    f'<footer>页面生成时间（UTC）：{esc(generated)}。结果为生成时快照；评测更新后运行 python3 scripts/build_quality_report.py 重新生成。partial47 开发结果未混入本页 100 份验收。</footer>',
                    '</main><script>' + JS + '</script></body></html>'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(content), encoding="utf-8")
    return {"output": str(output), "validation_rows": len(validation["rows"]), "original_rows": len(original["rows"]),
            "validation_evaluation_present": bool(validation["evaluation"]), "original_evaluation_present": bool(original["evaluation"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/quality/index.html")
    args = parser.parse_args()
    target = args.output.resolve()
    if not target.is_relative_to(ROOT / "output/quality"):
        parser.error("Output must stay inside output/quality")
    print(json.dumps(build(target), ensure_ascii=False))
