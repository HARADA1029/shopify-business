# ============================================================
# 採用商品の事後分析 + 商品ページ競合比較モジュール
#
# 1. eBay→Shopify 採用商品の成果追跡
# 2. 商品ページの競合比較と改善提案
# 3. 結果を自己学習に反映
#
# 担当:
#   catalog-migration-planner: 採用商品管理
#   growth-foundation: GA4分析
#   competitive-intelligence: 競合ページ比較
#   content-strategist: ページ文言改善
#   store-setup: UI改善
# ============================================================

import json
import os
import re
from datetime import datetime, timezone, timedelta
from collections import Counter

import requests

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

ADOPTION_LOG = os.path.join(SCRIPT_DIR, "adoption_tracking.json")


def _load_adoption_log():
    if not os.path.exists(ADOPTION_LOG):
        return {"adopted_products": [], "evaluations": [], "_last_updated": ""}
    try:
        with open(ADOPTION_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"adopted_products": [], "evaluations": [], "_last_updated": ""}


def _save_adoption_log(data):
    data["_last_updated"] = NOW.strftime("%Y-%m-%d")
    with open(ADOPTION_LOG, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ============================================================
# 1. 採用商品の事後分析
# ============================================================

def track_adopted_products(products):
    """Shopify に追加された商品の成果を追跡する"""
    findings = []
    log = _load_adoption_log()

    if not products:
        return findings

    # 最近 Active 化された商品を追跡対象に追加
    tracked_ids = set(p.get("product_id") for p in log.get("adopted_products", []))

    for p in products:
        pid = p["id"]
        if pid not in tracked_ids:
            # 新しい Active 商品を追跡対象に追加
            created = p.get("created_at", "")[:10]
            # 最近7日以内に作成された商品のみ追加
            if created >= (NOW - timedelta(days=7)).strftime("%Y-%m-%d"):
                log.setdefault("adopted_products", []).append({
                    "product_id": pid,
                    "title": p["title"][:60],
                    "product_type": p.get("product_type", ""),
                    "added_date": NOW.strftime("%Y-%m-%d"),
                    "status": "monitoring",
                    "views": 0,
                    "clicks": 0,
                    "cart_adds": 0,
                    "purchases": 0,
                })

    # 追跡中の商品を評価
    adopted = log.get("adopted_products", [])
    if not adopted:
        _save_adoption_log(log)
        return findings

    evaluations = {
        "success": [],
        "reaction_no_sale": [],
        "weak": [],
        "monitoring": [],
    }

    for item in adopted:
        days_since = (NOW - datetime.strptime(item.get("added_date", NOW.strftime("%Y-%m-%d")), "%Y-%m-%d").replace(tzinfo=JST)).days

        if days_since < 3:
            evaluations["monitoring"].append(item)
            item["status"] = "monitoring"
        elif item.get("purchases", 0) > 0:
            evaluations["success"].append(item)
            item["status"] = "success"
        elif item.get("cart_adds", 0) > 0:
            evaluations["reaction_no_sale"].append(item)
            item["status"] = "cart_no_sale"
            item["weak_reason"] = "Cart added but not purchased: check checkout flow/shipping cost"
        elif item.get("views", 0) > 10 or item.get("clicks", 0) > 5:
            evaluations["reaction_no_sale"].append(item)
            item["status"] = "reaction_no_sale"
            item["weak_reason"] = "Views/clicks but no cart: check price/description/images"
        elif item.get("views", 0) > 0:
            evaluations["weak"].append(item)
            item["status"] = "weak"
            item["weak_reason"] = "Low views: check SEO title/tags/collection placement"
        else:
            evaluations["weak"].append(item)
            item["status"] = "weak"
            item["weak_reason"] = "Zero views: check if product is in collection/navigation"

    # レポート生成
    summary = []
    total = len(adopted)
    summary.append("Tracking: %d products" % total)
    if evaluations["success"]:
        summary.append("Success: %d (sold on Shopify)" % len(evaluations["success"]))
        for item in evaluations["success"][:2]:
            summary.append("  -> %s [%s] purchase confirmed" % (item["title"][:35], item["product_type"]))
    if evaluations["reaction_no_sale"]:
        summary.append("Viewed but not sold: %d (page improvement needed)" % len(evaluations["reaction_no_sale"]))
        for item in evaluations["reaction_no_sale"][:2]:
            summary.append("  -> %s: %s" % (item["title"][:35], item.get("weak_reason", "check page")[:50]))
            summary.append("     views:%d clicks:%d cart:%d" % (
                item.get("views", 0), item.get("clicks", 0), item.get("cart_adds", 0)))
    if evaluations["weak"]:
        summary.append("Low reaction: %d (review proposal logic)" % len(evaluations["weak"]))
        for item in evaluations["weak"][:2]:
            summary.append("  -> %s: %s" % (item["title"][:35], item.get("weak_reason", "unknown")[:50]))
    if evaluations["monitoring"]:
        summary.append("Still monitoring: %d (< 3 days)" % len(evaluations["monitoring"]))

    findings.append({
        "type": "info", "agent": "catalog-migration-planner",
        "message": "Adoption tracking: %d products (%d success, %d need attention)" % (
            total,
            len(evaluations["success"]),
            len(evaluations["reaction_no_sale"]) + len(evaluations["weak"]),
        ),
        "details": summary,
    })

    # ページ改善が必要な商品を提案
    if evaluations["reaction_no_sale"]:
        improve_details = []
        for item in evaluations["reaction_no_sale"][:3]:
            improve_details.append(
                "[%s] %s -> Views but no sale: check price/description/images" % (item["product_type"], item["title"][:40])
            )
        findings.append({
            "type": "action", "agent": "store-setup",
            "message": "Product page improvement: %d products viewed but not sold" % len(evaluations["reaction_no_sale"]),
            "details": improve_details,
        })

    _save_adoption_log(log)
    return findings


# ============================================================
# 2. 商品ページ競合比較
# ============================================================

def compare_product_pages(products):
    """Shopify 商品ページを競合と比較して改善提案を生成する"""
    findings = []

    if not products:
        return findings

    # 代表的な商品1件を選んで競合比較
    # 最も価格が高い Active 商品を対象にする
    sorted_products = sorted(
        products,
        key=lambda p: float(p.get("variants", [{}])[0].get("price", "0") or "0"),
        reverse=True,
    )

    target = sorted_products[0] if sorted_products else None
    if not target:
        return findings

    title = target["title"]
    body = target.get("body_html", "") or ""
    images = target.get("images", [])
    variants = target.get("variants", [])
    tags = target.get("tags", "")

    # 自社ページの品質チェック
    issues = []
    strengths = []

    # 画像枚数
    if len(images) < 3:
        issues.append("[Images] Only %d images (competitors avg 5-8)" % len(images))
    elif len(images) >= 5:
        strengths.append("Good image count: %d" % len(images))

    # 説明文の長さ
    body_text = re.sub(r'<[^>]+>', '', body)
    word_count = len(body_text.split())
    if word_count < 50:
        issues.append("[Description] Only %d words (too short for SEO and trust)" % word_count)
    elif word_count < 100:
        issues.append("[Description] %d words (consider expanding with condition details)" % word_count)

    # コンディション表記
    has_condition = any(kw in body.lower() for kw in ["condition", "used", "pre-owned", "inspected"])
    if not has_condition:
        issues.append("[Condition] No condition description in body (critical for used items)")
    else:
        strengths.append("Condition mentioned in description")

    # 信頼訴求
    has_trust = any(kw in body.lower() for kw in ["shipped from japan", "authentic", "inspected", "genuine"])
    if not has_trust:
        issues.append("[Trust] No 'Shipped from Japan' or 'Inspected' in description")

    # 作品・シリーズ情報
    has_series = any(kw in body.lower() for kw in ["series", "franchise", "from the", "released"])
    if not has_series:
        issues.append("[Context] No series/franchise context (helps collectors understand value)")

    # タグの充実度
    tag_count = len([t.strip() for t in tags.split(",") if t.strip()])
    if tag_count < 3:
        issues.append("[Tags] Only %d tags (add more for search/collection)" % tag_count)

    # Compare at price
    compare_at = variants[0].get("compare_at_price") if variants else None
    if not compare_at:
        issues.append("[Pricing] No compare-at price (no sale display)")

    if issues:
        details = ["Product: %s" % title[:50]]
        details.extend(issues[:5])
        if strengths:
            details.append("Strengths: %s" % "; ".join(strengths))

        findings.append({
            "type": "action", "agent": "competitive-intelligence",
            "message": "Product page audit: %d issues found on top product" % len(issues),
            "details": details,
        })

    # 競合のページ要素との一般比較
    competitor_features = [
        "Detailed condition grading (A/B/C/D scale)",
        "Multiple angle photos (5-8 images)",
        "Shipping estimate displayed",
        "Return policy linked",
        "Customer reviews section",
        "Similar items recommendation",
    ]

    missing_features = []
    if len(images) < 5:
        missing_features.append("Multiple angle photos")
    if not has_condition:
        missing_features.append("Detailed condition grading")
    if "review" not in body.lower():
        missing_features.append("Customer reviews section")

    if missing_features:
        findings.append({
            "type": "medium_term", "agent": "store-setup",
            "message": "Competitor gap: %d features common in competitors but missing" % len(missing_features),
            "details": ["Missing: %s" % f for f in missing_features],
        })

    # 前回比較との差分検出
    comparison_path = os.path.join(SCRIPT_DIR, "product_comparison_cache.json")
    current_issues = len(issues)
    try:
        if os.path.exists(comparison_path):
            with open(comparison_path, "r", encoding="utf-8") as f:
                prev = json.load(f)
            prev_issues = prev.get("issue_count", 0)
            prev_product = prev.get("product", "")
            if prev_product == title[:50]:
                diff = current_issues - prev_issues
                if diff < 0:
                    findings.append({
                        "type": "info", "agent": "competitive-intelligence",
                        "message": "Product page improvement: %d issues fixed since last check" % abs(diff),
                    })
                elif diff > 0:
                    findings.append({
                        "type": "suggestion", "agent": "competitive-intelligence",
                        "message": "Product page regression: %d new issues since last check" % diff,
                    })
    except (json.JSONDecodeError, IOError):
        pass

    # 今回の結果をキャッシュ
    try:
        with open(comparison_path, "w", encoding="utf-8") as f:
            json.dump({
                "product": title[:50],
                "issue_count": current_issues,
                "date": NOW.strftime("%Y-%m-%d"),
                "issues": issues[:5],
            }, f, indent=2, ensure_ascii=False)
    except IOError:
        pass

    return findings


# ============================================================
# 3. 学習反映
# ============================================================

def update_learning(log):
    """事後分析結果を学習に反映する（強化版）"""
    shared_state_path = os.path.join(SCRIPT_DIR, "shared_state.json")
    try:
        with open(shared_state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, IOError, FileNotFoundError):
        state = {}

    adopted = log.get("adopted_products", [])
    success_types = Counter(p.get("product_type", "") for p in adopted if p.get("status") == "success")
    weak_types = Counter(p.get("product_type", "") for p in adopted if p.get("status") == "weak")
    cart_no_sale = Counter(p.get("product_type", "") for p in adopted if p.get("status") == "cart_no_sale")
    reaction_types = Counter(p.get("product_type", "") for p in adopted if p.get("status") == "reaction_no_sale")

    # 弱い理由のパターン分析
    weak_reasons = Counter(p.get("weak_reason", "unknown") for p in adopted if p.get("status") in ("weak", "reaction_no_sale", "cart_no_sale"))

    state["adoption_learning"] = {
        "success_categories": dict(success_types),
        "weak_categories": dict(weak_types),
        "cart_no_sale_categories": dict(cart_no_sale),
        "reaction_no_sale_categories": dict(reaction_types),
        "weak_reason_patterns": dict(weak_reasons.most_common(5)),
        "total_tracked": len(adopted),
        "success_rate": (sum(success_types.values()) / max(len(adopted), 1) * 100),
        "last_updated": NOW.strftime("%Y-%m-%d"),
        "learning_applied": [
            "Success types get +2 weight in next proposals",
            "Weak types get -1 weight",
            "Cart-no-sale items flagged for page improvement",
        ],
    }

    # スコアリング重みの自動調整提案
    if sum(success_types.values()) > 3:
        # 成功率が高いカテゴリの重みを上げる
        best_cat = success_types.most_common(1)[0][0] if success_types else ""
        if best_cat:
            state.setdefault("weight_adjustments", []).append({
                "date": NOW.strftime("%Y-%m-%d"),
                "adjustment": "Increase weight for %s (high success rate)" % best_cat,
                "reason": "%d successful adoptions" % success_types[best_cat],
            })
            # 直近5件のみ保持
            state["weight_adjustments"] = state["weight_adjustments"][-5:]

    try:
        with open(shared_state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except IOError:
        pass


# ============================================================
# メインエントリポイント
# ============================================================

def run_product_pdca(products):
    """採用商品の事後分析 + 商品ページ競合比較を実行"""
    all_findings = []

    # 1. 採用商品の追跡・評価
    all_findings.extend(track_adopted_products(products))

    # 2. 商品ページの競合比較
    all_findings.extend(compare_product_pages(products))

    # 3. 学習反映
    log = _load_adoption_log()
    update_learning(log)

    return all_findings
