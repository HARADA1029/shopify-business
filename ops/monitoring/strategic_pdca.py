# ============================================================
# 戦略PDCA モジュール
#
# 外部リサーチ → 自社比較 → 不足抽出 → 自動改善提案 →
# 自動更新 → 結果分析 → 再リサーチ の上位PDCAを回す。
#
# 安全ルール:
# - 品質基準は緩和しない
# - ブランド方針に反する改善は採用しない
# - 低リスク改善のみ自動更新、高リスクは提案止まり
# ============================================================

import json
import os
import re
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import requests

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

STRATEGIC_STATE = os.path.join(SCRIPT_DIR, "strategic_pdca_state.json")

# 自動更新可能な低リスク改善
AUTO_UPDATE_SAFE = {
    "trust_text", "cta_text", "internal_link", "description_expand",
    "category_tag", "mini_cta", "blog_structure", "template_tweak",
}

# 提案止まり（自動更新禁止）
PROPOSAL_ONLY = {
    "design_overhaul", "brand_tone_change", "price_strategy",
    "nav_restructure", "competitor_copy",
}


def _load_state():
    if os.path.exists(STRATEGIC_STATE):
        try:
            with open(STRATEGIC_STATE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"research_history": [], "improvements": [], "results": [], "last_updated": ""}


def _save_state(state):
    state["last_updated"] = NOW.strftime("%Y-%m-%d")
    state["research_history"] = state.get("research_history", [])[-14:]
    state["improvements"] = state.get("improvements", [])[-30:]
    with open(STRATEGIC_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _load_json(filename):
    path = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


# ============================================================
# 1. 外部リサーチ
# ============================================================

def research_external():
    """競合・成功ストアの要素をリサーチ"""
    details = ["=== External Research ==="]

    competitors = [
        {"name": "Solaris Japan", "url": "https://solarisjapan.com"},
        {"name": "Japan Figure", "url": "https://www.japan-figure.com"},
    ]

    winning_elements = {
        "reviews": False,
        "newsletter_popup": False,
        "trust_badges": False,
        "related_products": False,
        "recently_viewed": False,
        "size_guide": False,
        "faq_on_product": False,
        "social_proof": False,
        "free_shipping_bar": False,
        "countdown_timer": False,
    }

    for comp in competitors:
        try:
            resp = requests.get(comp["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if resp.status_code == 200:
                html = resp.text.lower()
                if "review" in html: winning_elements["reviews"] = True
                if "newsletter" in html or "subscribe" in html: winning_elements["newsletter_popup"] = True
                if "trust" in html or "secure" in html: winning_elements["trust_badges"] = True
                if "related" in html or "you may also like" in html: winning_elements["related_products"] = True
                if "recently viewed" in html: winning_elements["recently_viewed"] = True
                if "faq" in html: winning_elements["faq_on_product"] = True
                if "sold" in html or "popular" in html: winning_elements["social_proof"] = True

                found = [k for k, v in winning_elements.items() if v]
                details.append("[%s] Found: %s" % (comp["name"], ", ".join(found[:5]) if found else "basic"))
        except Exception:
            pass

    we_have = {"trust_badges", "faq_on_product"}  # 自社にある要素
    gaps = [k for k, v in winning_elements.items() if v and k not in we_have]
    details.append("")
    details.append("Competitor elements we lack: %s" % ", ".join(gaps) if gaps else "No major gaps")

    return details, winning_elements, gaps


# ============================================================
# 2. 自社比較
# ============================================================

def compare_with_self(products, wp_posts, gaps):
    """外部リサーチ結果と自社を比較"""
    details = ["=== Self Comparison ==="]

    # 商品ページ品質
    total = len(products)
    with_trust = sum(1 for p in products if any(kw in (p.get("body_html", "") or "").lower() for kw in ["shipped from japan", "inspected"]))
    with_condition = sum(1 for p in products if "condition" in (p.get("body_html", "") or "").lower())

    details.append("Product pages: %d total" % total)
    details.append("  Trust language: %d/%d (%.0f%%)" % (with_trust, total, with_trust / max(total, 1) * 100))
    details.append("  Condition desc: %d/%d (%.0f%%)" % (with_condition, total, with_condition / max(total, 1) * 100))

    # ブログ
    articles_with_cta = sum(1 for p in wp_posts if "hd-toys-store-japan" in str(p.get("content", {}).get("rendered", "") if isinstance(p.get("content"), dict) else p.get("content", "")).lower())
    details.append("Blog CTA rate: %d/%d articles" % (articles_with_cta, len(wp_posts)))

    # ギャップの影響評価
    high_impact = []
    medium_impact = []
    for gap in gaps:
        if gap in ("related_products", "newsletter_popup", "social_proof"):
            high_impact.append(gap)
        else:
            medium_impact.append(gap)

    if high_impact:
        details.append("")
        details.append("High-impact gaps: %s" % ", ".join(high_impact))
    if medium_impact:
        details.append("Medium-impact gaps: %s" % ", ".join(medium_impact))

    return details, high_impact


# ============================================================
# 3. 不足抽出 + 4. 改善提案
# ============================================================

def extract_improvements(gaps, high_impact):
    """不足要素から改善提案を生成"""
    details = ["=== Improvement Candidates ==="]

    auto_candidates = []
    proposal_candidates = []

    improvement_map = {
        "related_products": {"type": "proposal_only", "effort": "medium", "desc": "Add related products section to product pages"},
        "newsletter_popup": {"type": "proposal_only", "effort": "medium", "desc": "Add newsletter signup with delayed popup"},
        "social_proof": {"type": "auto_safe", "effort": "low", "desc": "Add 'Popular item' or 'X customers viewed' text"},
        "reviews": {"type": "proposal_only", "effort": "high", "desc": "Review system (Harada declined — skip)"},
        "recently_viewed": {"type": "proposal_only", "effort": "medium", "desc": "Add recently viewed section"},
        "free_shipping_bar": {"type": "proposal_only", "effort": "low", "desc": "Conditional free shipping banner (needs margin analysis)"},
        "countdown_timer": {"type": "skip", "effort": "low", "desc": "Skip — conflicts with value-first policy"},
        "size_guide": {"type": "skip", "effort": "low", "desc": "Not applicable for pre-owned collectibles"},
    }

    for gap in gaps:
        imp = improvement_map.get(gap, {"type": "proposal_only", "effort": "medium", "desc": gap})

        if imp["type"] == "skip":
            details.append("[SKIP] %s — %s" % (gap, imp["desc"]))
        elif imp["type"] == "auto_safe":
            auto_candidates.append({"name": gap, "desc": imp["desc"], "effort": imp["effort"]})
            details.append("[AUTO] %s — %s (effort: %s)" % (gap, imp["desc"], imp["effort"]))
        else:
            proposal_candidates.append({"name": gap, "desc": imp["desc"], "effort": imp["effort"]})
            details.append("[PROPOSE] %s — %s (effort: %s)" % (gap, imp["desc"], imp["effort"]))

    return details, auto_candidates, proposal_candidates


# ============================================================
# 5. 結果分析
# ============================================================

def analyze_improvement_results(state):
    """過去の改善結果を分析"""
    details = ["=== Improvement Results ==="]

    improvements = state.get("improvements", [])
    if not improvements:
        details.append("No improvements tracked yet")
        return details

    recent = [i for i in improvements if i.get("date", "") >= (NOW - timedelta(days=14)).strftime("%Y-%m-%d")]
    success = sum(1 for i in recent if i.get("result") == "success")
    weak = sum(1 for i in recent if i.get("result") == "weak")

    details.append("Recent improvements (14d): %d total, %d success, %d weak" % (len(recent), success, weak))

    # 横展開候補
    successful = [i for i in recent if i.get("result") == "success"]
    if successful:
        details.append("")
        details.append("Horizontal expansion candidates:")
        for s in successful[:3]:
            details.append("  [SUCCESS] %s → expand to other categories/channels" % s.get("name", "?")[:40])

    return details


# ============================================================
# 6. New Element Test Log
# ============================================================

def track_new_elements(state, auto_candidates, proposal_candidates):
    """新規要素の導入テストを追跡"""
    details = ["=== New Element Test Log ==="]

    elements = state.get("element_tests", [])

    # 新しい候補を登録（未登録のもの）
    existing = set(e.get("name", "") for e in elements)
    for c in auto_candidates + proposal_candidates:
        if c["name"] not in existing:
            elements.append({
                "name": c["name"],
                "desc": c["desc"],
                "source": "competitor_research",
                "target": "pending",
                "implemented": None,
                "implemented_date": None,
                "result": None,
                "result_date": None,
                "expansion": None,
                "status": "identified",
            })

    # ステータス集計
    identified = sum(1 for e in elements if e.get("status") == "identified")
    testing = sum(1 for e in elements if e.get("status") == "testing")
    success = sum(1 for e in elements if e.get("result") == "success")
    failed = sum(1 for e in elements if e.get("result") == "failed")

    details.append("Identified: %d | Testing: %d | Success: %d | Failed: %d" % (identified, testing, success, failed))

    # 直近のテスト結果
    recent = [e for e in elements if e.get("result_date")]
    recent.sort(key=lambda x: x.get("result_date", ""), reverse=True)
    if recent:
        details.append("")
        details.append("Recent results:")
        for e in recent[:5]:
            details.append("  [%s] %s — %s (%s)" % (
                e.get("result", "?").upper(), e["name"], e.get("desc", "")[:40], e.get("result_date", "?")))

    # 横展開候補
    expand = [e for e in elements if e.get("result") == "success" and not e.get("expansion")]
    if expand:
        details.append("")
        details.append("Expansion candidates:")
        for e in expand:
            details.append("  [EXPAND] %s → apply to other categories/channels" % e["name"])

    state["element_tests"] = elements
    return details


# ============================================================
# 7. Gap → Fix → Result Tracker
# ============================================================

def track_gap_fix_result(state):
    """不足→修正→結果を1本で追跡"""
    details = ["=== Gap → Fix → Result ==="]

    elements = state.get("element_tests", [])
    if not elements:
        details.append("No elements tracked yet")
        return details

    for e in elements:
        status = e.get("status", "identified")
        name = e.get("name", "?")

        if status == "identified":
            details.append("[GAP] %s — found but not yet implemented" % name)
        elif status == "testing":
            details.append("[FIX] %s — implemented %s, awaiting results" % (name, e.get("implemented_date", "?")))
        elif e.get("result") == "success":
            details.append("[SUCCESS] %s — improved, expansion: %s" % (name, e.get("expansion", "pending")))
        elif e.get("result") == "weak":
            details.append("[WEAK] %s — partial improvement, re-adjust needed" % name)
        elif e.get("result") == "failed":
            details.append("[FAILED] %s — no improvement, consider stopping" % name)

    return details


# ============================================================
# 8. Expansion Decision
# ============================================================

def evaluate_expansion(state):
    """成功要素の横展開判断"""
    details = ["=== Expansion Decision ==="]

    elements = state.get("element_tests", [])
    decisions = {
        "expand_category": [],
        "expand_channel": [],
        "continue_local": [],
        "stop": [],
        "re_test": [],
    }

    for e in elements:
        result = e.get("result")
        if result == "success":
            if not e.get("expansion"):
                decisions["expand_category"].append(e["name"])
        elif result == "weak":
            decisions["re_test"].append(e["name"])
        elif result == "failed":
            decisions["stop"].append(e["name"])

    if decisions["expand_category"]:
        details.append("Expand to other categories: %s" % ", ".join(decisions["expand_category"]))
    if decisions["re_test"]:
        details.append("Re-test with adjustments: %s" % ", ".join(decisions["re_test"]))
    if decisions["stop"]:
        details.append("Stop (no impact): %s" % ", ".join(decisions["stop"]))
    if not any(decisions.values()):
        details.append("No decisions pending — elements still in testing")

    return details


# ============================================================
# メインエントリポイント
# ============================================================

def run_strategic_pdca(products, wp_posts):
    """戦略PDCAを実行"""
    result = []
    state = _load_state()
    all_details = []

    # 1. 外部リサーチ
    research_details, elements, gaps = research_external()
    all_details.extend(research_details)

    # 2. 自社比較
    compare_details, high_impact = compare_with_self(products, wp_posts, gaps)
    all_details.extend(compare_details)

    # 3-4. 不足抽出 + 改善提案
    improve_details, auto_candidates, proposal_candidates = extract_improvements(gaps, high_impact)
    all_details.extend(improve_details)

    # 5. 結果分析
    all_details.extend(analyze_improvement_results(state))

    # 6. New Element Test Log
    all_details.extend(track_new_elements(state, auto_candidates, proposal_candidates))

    # 7. Gap → Fix → Result
    all_details.extend(track_gap_fix_result(state))

    # 8. Expansion Decision
    all_details.extend(evaluate_expansion(state))

    # リサーチ履歴を保存
    state["research_history"].append({
        "date": NOW.strftime("%Y-%m-%d"),
        "gaps_found": len(gaps),
        "auto_candidates": len(auto_candidates),
        "proposal_candidates": len(proposal_candidates),
    })
    _save_state(state)

    severity = "action" if high_impact else "info"
    result.append({
        "type": severity,
        "agent": "competitive-intelligence",
        "message": "Strategic PDCA: %d gaps, %d auto-safe, %d proposal-only" % (
            len(gaps), len(auto_candidates), len(proposal_candidates)),
        "details": all_details,
    })

    return result
