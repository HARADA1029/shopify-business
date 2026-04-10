# ============================================================
# 売上改善分析モジュール
#
# Shopify売上を改善するための6専門分野を統合分析する。
#
# 1. CRO（商品ページ/CTA/trust/モバイル導線）
# 2. Merchandising（カテゴリ厚み/価格帯/作品深掘り）
# 3. Content UX（ブログ品質/読みやすさ/テンプレート品質）
# 4. IA / Navigation（導線/内部リンク/回遊設計）
# 5. Marketplace-to-DTC（eBay→Shopify移植の見せ方改善）
# 6. Retention（再訪/ファン化/newsletter/類似提案）
#
# 追加機能:
# - 提案タイプ別勝敗評価
# - 売れない理由の切り分け
# - デザイン改善の学習化
# ============================================================

import json
import os
import re
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))


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
# 1. 提案タイプ別勝敗評価
# ============================================================

def evaluate_proposal_outcomes():
    """どの提案タイプが実際に売上に効いたかを評価"""
    findings = []
    pt = _load_json("proposal_tracking.json")
    if not pt or not pt.get("proposals"):
        return findings

    accuracy = pt.get("summary", {}).get("accuracy_by_type", {})
    details = ["=== Proposal Win/Loss by Type ==="]

    types_ranked = []
    for ptype, data in sorted(accuracy.items()):
        proposed = data.get("proposed", 0)
        adopted = data.get("adopted", 0)
        success = data.get("success", 0)
        if proposed == 0:
            continue

        adopt_rate = adopted / proposed * 100
        success_rate = success / max(adopted, 1) * 100
        types_ranked.append((ptype, proposed, adopted, success, adopt_rate, success_rate))

    types_ranked.sort(key=lambda x: -x[5])  # 成功率順

    for ptype, proposed, adopted, success, ar, sr in types_ranked:
        marker = "WIN" if sr >= 70 else "OK" if sr >= 40 else "WEAK"
        details.append("[%s] %s: proposed:%d adopted:%d success:%d (adopt:%.0f%% success:%.0f%%)" % (
            marker, ptype, proposed, adopted, success, ar, sr))

    # 次回採用条件の提案
    if types_ranked:
        best = types_ranked[0]
        worst = types_ranked[-1] if len(types_ranked) > 1 else None
        details.append("")
        details.append("--- Recommendations ---")
        details.append("Increase: %s proposals (%.0f%% success)" % (best[0], best[5]))
        if worst and worst[5] < 50:
            details.append("Review: %s proposals (%.0f%% success) — tighten criteria" % (worst[0], worst[5]))

    findings.append({
        "type": "info", "agent": "self-learning",
        "message": "Proposal outcomes: %d types tracked, best=%.0f%% success" % (
            len(types_ranked), types_ranked[0][5] if types_ranked else 0),
        "details": details,
    })
    return findings


# ============================================================
# 2. 売れない理由の切り分け
# ============================================================

def analyze_unsold_reasons(products):
    """売れていない商品の原因を分類"""
    findings = []
    if not products:
        return findings

    adoption = _load_json("adoption_tracking.json")
    adopted = adoption.get("adopted_products", []) if adoption else []

    reasons = defaultdict(list)

    for p in products:
        body = p.get("body_html", "") or ""
        body_lower = body.lower()
        body_text = re.sub(r"<[^>]+>", "", body)
        word_count = len(body_text.split())
        images = len(p.get("images", []))
        variants = p.get("variants", [])
        price = float(variants[0].get("price", "0") or "0") if variants else 0
        has_trust = any(kw in body_lower for kw in ["shipped from japan", "inspected", "authentic"])
        title = p["title"][:40]

        # 追跡中商品と照合
        tracked = None
        for a in adopted:
            if a.get("product_id") == p["id"]:
                tracked = a
                break

        issues = []

        # 価格要因
        if price > 500:
            issues.append("high_price")
        elif price < 15:
            issues.append("low_price_low_margin")

        # ページ品質
        if word_count < 100:
            issues.append("thin_description")
        if images < 3:
            issues.append("few_images")
        if not has_trust:
            issues.append("no_trust_language")

        # 需要推定
        product_type = p.get("product_type", "")
        niche_categories = ["Goods & Accessories", "Media & Books"]
        if product_type in niche_categories:
            issues.append("niche_category")

        if issues:
            primary = issues[0]
            reasons[primary].append(title)

    if reasons:
        details = ["=== Unsold Reasons Classification ==="]
        reason_labels = {
            "thin_description": "Page quality: thin description (<100w)",
            "few_images": "Page quality: too few images (<3)",
            "no_trust_language": "Trust: missing shipped-from-japan/inspected",
            "high_price": "Price: over $500 (high barrier)",
            "low_price_low_margin": "Price: under $15 (low margin)",
            "niche_category": "Demand: niche category (lower search volume)",
        }
        for reason, titles in sorted(reasons.items(), key=lambda x: -len(x[1])):
            label = reason_labels.get(reason, reason)
            details.append("[%d products] %s" % (len(titles), label))
            for t in titles[:3]:
                details.append("  - %s" % t)

        findings.append({
            "type": "suggestion", "agent": "growth-foundation",
            "message": "Unsold analysis: %d products with issues across %d reasons" % (
                sum(len(v) for v in reasons.values()), len(reasons)),
            "details": details,
        })

    return findings


# ============================================================
# 3. CRO（Conversion Rate Optimization）
# ============================================================

def audit_cro(products):
    """商品ページのコンバージョン要素を監査"""
    findings = []
    if not products:
        return findings

    total = len(products)
    issues = defaultdict(int)

    for p in products:
        body = p.get("body_html", "") or ""
        body_lower = body.lower()
        images = len(p.get("images", []))
        variants = p.get("variants", [])
        compare_at = variants[0].get("compare_at_price") if variants else None

        # ファーストビュー要素
        if images < 3:
            issues["few_images"] += 1
        if not compare_at:
            issues["no_compare_price"] += 1

        # Trust要素
        if not any(kw in body_lower for kw in ["shipped from japan", "inspected", "authentic"]):
            issues["no_trust"] += 1
        if "condition" not in body_lower and "pre-owned" not in body_lower:
            issues["no_condition"] += 1

        # CTA品質
        if "about this item" not in body_lower:
            issues["no_about_block"] += 1

    details = ["=== CRO Audit (%d products) ===" % total]
    cro_scores = {
        "few_images": ("Images <3", "high", "Add more product photos"),
        "no_compare_price": ("No compare-at price", "medium", "Set eBay price as compare-at for sale display"),
        "no_trust": ("No trust language", "high", "Add shipped-from-japan/inspected"),
        "no_condition": ("No condition description", "high", "Add pre-owned condition details"),
        "no_about_block": ("No About This Item block", "medium", "Add structured product info block"),
    }

    for key, (label, priority, fix) in cro_scores.items():
        count = issues.get(key, 0)
        if count > 0:
            details.append("[%s] %s: %d/%d products → %s" % (priority.upper(), label, count, total, fix))

    overall = total - max(issues.values()) if issues else total
    cro_score = round(overall / max(total, 1) * 100)
    details.append("")
    details.append("CRO score: %d%% (products meeting all criteria)" % cro_score)

    findings.append({
        "type": "suggestion" if cro_score < 80 else "ok",
        "agent": "growth-foundation",
        "message": "CRO audit: %d%% score, %d improvement areas" % (cro_score, sum(1 for v in issues.values() if v > 0)),
        "details": details,
    })
    return findings


# ============================================================
# 4. Merchandising / Assortment Planning
# ============================================================

def analyze_merchandising(products):
    """カテゴリ厚み・価格帯・作品深掘りを分析"""
    findings = []
    if not products:
        return findings

    # カテゴリ別
    cats = Counter(p.get("product_type", "Other") for p in products)

    # 価格帯分布
    price_bands = {"under_30": 0, "30_100": 0, "100_300": 0, "300_500": 0, "over_500": 0}
    for p in products:
        price = float(p.get("variants", [{}])[0].get("price", "0") or "0")
        if price < 30:
            price_bands["under_30"] += 1
        elif price < 100:
            price_bands["30_100"] += 1
        elif price < 300:
            price_bands["100_300"] += 1
        elif price < 500:
            price_bands["300_500"] += 1
        else:
            price_bands["over_500"] += 1

    details = ["=== Merchandising Analysis ==="]

    # カテゴリ厚み
    details.append("--- Category Depth ---")
    thin_cats = []
    for cat, count in cats.most_common():
        marker = "THIN" if count < 5 else "OK"
        details.append("[%s] %s: %d products" % (marker, cat, count))
        if count < 5:
            thin_cats.append(cat)

    # 価格帯
    details.append("")
    details.append("--- Price Band Distribution ---")
    band_labels = {"under_30": "<$30", "30_100": "$30-100", "100_300": "$100-300", "300_500": "$300-500", "over_500": "$500+"}
    for band, label in band_labels.items():
        details.append("%s: %d products" % (label, price_bands[band]))

    # eBay売れ筋との比較
    ebay_cache = _load_json("ebay_sales_cache.json")
    if ebay_cache:
        ebay_cats = ebay_cache.get("categories", {})
        details.append("")
        details.append("--- eBay vs Shopify Category Gap ---")
        for cat, sold in sorted(ebay_cats.items(), key=lambda x: -x[1]):
            shopify_count = cats.get(cat, 0)
            if sold >= 3 and shopify_count < 5:
                details.append("[GAP] %s: eBay %d sold, Shopify %d listed → increase" % (cat, sold, shopify_count))

    # 提案
    if thin_cats:
        details.append("")
        details.append("--- Recommendations ---")
        for cat in thin_cats[:3]:
            details.append("Increase: %s (only %d products)" % (cat, cats[cat]))

    findings.append({
        "type": "suggestion" if thin_cats else "info",
        "agent": "catalog-migration-planner",
        "message": "Merchandising: %d categories, %d thin (<5 products), %d price bands" % (
            len(cats), len(thin_cats), sum(1 for v in price_bands.values() if v > 0)),
        "details": details,
    })
    return findings


# ============================================================
# 5. IA / Navigation Optimization
# ============================================================

def audit_navigation(products, wp_posts):
    """導線・内部リンク・回遊設計を監査"""
    findings = []

    details = ["=== Navigation & IA Audit ==="]

    # Collection → 商品の導線
    cats = Counter(p.get("product_type", "Other") for p in products)
    details.append("Collections: %d categories covering %d products" % (len(cats), len(products)))

    # ブログ → Shopify 導線
    articles_with_cta = 0
    articles_with_internal = 0
    total_articles = 0
    for p in wp_posts:
        content = p.get("content", {})
        if isinstance(content, dict):
            content = content.get("rendered", "")
        if not content:
            continue
        total_articles += 1
        if "hd-toys-store-japan" in content.lower():
            articles_with_cta += 1
        if "hd-bodyscience.com" in content.lower():
            articles_with_internal += 1

    cta_rate = articles_with_cta / max(total_articles, 1) * 100
    link_rate = articles_with_internal / max(total_articles, 1) * 100
    details.append("Blog→Shopify CTA: %d/%d articles (%.0f%%)" % (articles_with_cta, total_articles, cta_rate))
    details.append("Internal links: %d/%d articles (%.0f%%)" % (articles_with_internal, total_articles, link_rate))

    issues = []
    if cta_rate < 80:
        issues.append("Blog CTA coverage low (%.0f%%) → add CTAs to %d articles" % (cta_rate, total_articles - articles_with_cta))
    if link_rate < 50:
        issues.append("Internal link rate low (%.0f%%) → add cross-article links" % link_rate)

    if issues:
        details.append("")
        details.append("--- Issues ---")
        details.extend(issues)

    findings.append({
        "type": "suggestion" if issues else "ok",
        "agent": "store-setup",
        "message": "Navigation audit: CTA %.0f%%, internal links %.0f%%" % (cta_rate, link_rate),
        "details": details,
    })
    return findings


# ============================================================
# 6. Marketplace-to-DTC Transfer
# ============================================================

def analyze_dtc_transfer(products):
    """eBay→Shopify移植時の見せ方改善を分析"""
    findings = []
    if not products:
        return findings

    details = ["=== eBay-to-DTC Transfer Analysis ==="]
    transfer_issues = []

    for p in products[:10]:  # 上位10商品
        body = p.get("body_html", "") or ""
        body_lower = body.lower()
        title = p["title"][:40]

        issues = []
        # eBay的な表現が残っていないか
        if any(kw in body_lower for kw in ["fast shipping", "best price", "buy it now", "great deal"]):
            issues.append("marketplace-language")
        # DTC向けのストーリーがあるか
        if not any(kw in body_lower for kw in ["story", "history", "series", "franchise", "collector"]):
            issues.append("no-collector-story")
        # ブランド体験要素
        if "hd toys" not in body_lower and "hd store" not in body_lower:
            issues.append("no-brand-identity")

        if issues:
            transfer_issues.append("[%s] %s" % (", ".join(issues), title))

    if transfer_issues:
        details.append("Products needing DTC optimization:")
        details.extend(transfer_issues[:5])
        details.append("")
        details.append("--- DTC Best Practices ---")
        details.append("Add: collector story/franchise context (why this item matters)")
        details.append("Add: brand identity (HD Toys Store Japan experience)")
        details.append("Remove: marketplace language (buy it now, best price)")
    else:
        details.append("Top 10 products: DTC-ready (no marketplace language detected)")

    findings.append({
        "type": "suggestion" if transfer_issues else "ok",
        "agent": "catalog-migration-planner",
        "message": "DTC transfer: %d/%d top products need optimization" % (len(transfer_issues), min(10, len(products))),
        "details": details,
    })
    return findings


# ============================================================
# 7. Retention / Repeat Purchase
# ============================================================

def analyze_retention():
    """再訪・ファン化・回遊改善を分析"""
    findings = []

    details = ["=== Retention & Repeat Purchase ==="]
    opportunities = []

    # Newsletter
    opportunities.append("[MEDIUM] Newsletter signup: Not implemented → collect emails for new arrivals")

    # 類似商品提案
    opportunities.append("[MEDIUM] Related products: Add related items section to product pages")

    # ブログ回遊
    opportunities.append("[LOW] Blog series: Create multi-part collector guides for return visits")

    # SNS フォロワー → リピーター
    opportunities.append("[LOW] SNS→repeat: Post new arrivals to bring followers back to store")

    details.extend(opportunities)

    findings.append({
        "type": "info",
        "agent": "project-orchestrator",
        "message": "Retention opportunities: %d identified" % len(opportunities),
        "details": details,
    })
    return findings


# ============================================================
# メインエントリポイント
# ============================================================

def run_sales_optimization(products, wp_posts, all_findings):
    """売上改善分析フルスイートを実行"""
    result = []

    # 1. 提案タイプ別勝敗
    result.extend(evaluate_proposal_outcomes())

    # 2. 売れない理由の切り分け
    result.extend(analyze_unsold_reasons(products))

    # 3. CRO監査
    result.extend(audit_cro(products))

    # 4. Merchandising分析
    result.extend(analyze_merchandising(products))

    # 5. 導線監査
    result.extend(audit_navigation(products, wp_posts))

    # 6. DTC移植分析
    result.extend(analyze_dtc_transfer(products))

    # 7. Retention分析
    result.extend(analyze_retention())

    return result
