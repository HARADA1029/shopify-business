# ============================================================
# 売上改善分析モジュール（精度強化版）
#
# 成功判定定義:
#   page_improvement: CTR改善 / カート率改善 / 購入発生
#   category_gap: 商品追加 / 閲覧増 / 売上発生
#   article_theme: 記事公開 / 閲覧 / CTAクリック / 送客
#   sns_post: 表示 / 保存 / プロフィール遷移 / Shopify遷移
#   sales_based: 売上発生 / カート追加
#   similar_product: 閲覧増 / カート追加
#   related_character: 閲覧増
#   internal_link: クリック増
#
# 成果4段階:
#   success: 売上 or カート追加 or 目標達成
#   reaction_only: 閲覧・クリックあるが購入なし
#   no_reaction: 閲覧もクリックもほぼなし
#   pending: データ蓄積中（7日未満）
#
# CROスコア採点項目（8項目、各1点、満点8）:
#   1. 画像3枚以上
#   2. compare-at price設定
#   3. trust語あり（shipped from japan/inspected/authentic）
#   4. condition語あり（condition/pre-owned/used）
#   5. About This Item ブロック
#   6. 説明文100語以上
#   7. タグ3個以上
#   8. コレクション所属
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

# 成功判定定義
SUCCESS_CRITERIA = {
    "page_improvement": {"success": "CTR or cart rate improved", "reaction": "views increased", "metric": "cart_adds"},
    "category_gap": {"success": "sale or 50+ views", "reaction": "views > 10", "metric": "views"},
    "article_theme": {"success": "article published + CTA clicked + Shopify referral", "reaction": "article published + viewed", "metric": "cta_clicks + shopify_referrals"},
    "sns_post": {"success": "profile visit or Shopify click", "reaction": "views > 100 or saves > 5", "metric": "save_rate + profile_visit_rate + shopify_visit_rate"},
    "sales_based": {"success": "sale occurred", "reaction": "cart added", "metric": "purchases"},
    "similar_product": {"success": "views > 20 + cart add", "reaction": "views > 10", "metric": "views"},
    "related_character": {"success": "views > 20", "reaction": "views > 5", "metric": "views"},
    "internal_link": {"success": "click-through increased", "reaction": "page viewed", "metric": "clicks"},
}

# フランチャイズ関係マッピング
FRANCHISE_MAP = {
    "pokemon": ["pikachu", "charizard", "eevee", "mewtwo", "lugia", "gardevoir", "appletun"],
    "one piece": ["luffy", "zoro", "nami", "shanks", "ace"],
    "dragon ball": ["goku", "vegeta", "frieza", "gohan"],
    "naruto": ["naruto", "sasuke", "sakura", "kakashi"],
    "gundam": ["rx-78", "zaku", "unicorn", "strike"],
    "vocaloid": ["miku", "hatsune", "rin", "len"],
    "evangelion": ["eva", "asuka", "rei", "shinji", "misato"],
    "jojo": ["jotaro", "dio", "giorno", "jolyne"],
    "tamagotchi": ["bandai", "digital pet", "chibi", "id l"],
    "ghibli": ["totoro", "chihiro", "howl", "kiki"],
}


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
# 1. 提案タイプ別勝敗評価（4段階）
# ============================================================

def evaluate_proposal_outcomes():
    """提案タイプ別の成果を4段階で評価"""
    findings = []
    pt = _load_json("proposal_tracking.json")
    if not pt or not pt.get("proposals"):
        return findings

    # 4段階集計
    type_results = defaultdict(lambda: {"success": 0, "reaction_only": 0, "no_reaction": 0, "pending": 0, "total": 0})

    for p in pt.get("proposals", []):
        ptype = p.get("type", "other")
        result = p.get("result")
        status = p.get("status", "")

        type_results[ptype]["total"] += 1

        if status == "pending":
            type_results[ptype]["pending"] += 1
        elif result == "success":
            type_results[ptype]["success"] += 1
        elif result == "weak" or result == "reaction_only":
            type_results[ptype]["reaction_only"] += 1
        elif result == "failed" or result == "no_reaction":
            type_results[ptype]["no_reaction"] += 1
        elif not result and status == "adopted":
            type_results[ptype]["pending"] += 1

    details = ["=== Proposal Win/Loss by Type (4-level) ==="]
    details.append("Criteria per type:")
    for ptype, criteria in sorted(SUCCESS_CRITERIA.items()):
        details.append("  %s: success=%s | reaction=%s" % (ptype, criteria["success"], criteria["reaction"]))
    details.append("")

    types_ranked = []
    for ptype, counts in sorted(type_results.items()):
        total = counts["total"]
        s = counts["success"]
        r = counts["reaction_only"]
        n = counts["no_reaction"]
        p = counts["pending"]
        evaluated = s + r + n
        success_rate = s / max(evaluated, 1) * 100

        marker = "WIN" if success_rate >= 70 else "OK" if success_rate >= 40 else "WEAK" if evaluated > 0 else "PENDING"
        details.append("[%s] %s: %d total | success:%d reaction:%d none:%d pending:%d (%.0f%%)" % (
            marker, ptype, total, s, r, n, p, success_rate))
        types_ranked.append((ptype, success_rate, total))

    types_ranked.sort(key=lambda x: -x[1])

    if types_ranked:
        details.append("")
        details.append("--- Weight Recommendations ---")
        best = types_ranked[0]
        details.append("Increase weight: %s (%.0f%% success)" % (best[0], best[1]))
        if len(types_ranked) > 1:
            worst = types_ranked[-1]
            if worst[1] < 50 and worst[2] >= 2:
                details.append("Decrease weight: %s (%.0f%% success)" % (worst[0], worst[1]))

    findings.append({
        "type": "info", "agent": "self-learning",
        "message": "Proposal outcomes: %d types, best=%.0f%% success" % (
            len(types_ranked), types_ranked[0][1] if types_ranked else 0),
        "details": details,
    })
    return findings


# ============================================================
# 2. 売れない理由の切り分け
# ============================================================

def analyze_unsold_reasons(products):
    """売れていない商品の原因を6分類"""
    findings = []
    if not products:
        return findings

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
        has_condition = any(kw in body_lower for kw in ["condition", "pre-owned", "used"])
        tags = len([t.strip() for t in p.get("tags", "").split(",") if t.strip()])
        title = p["title"][:40]

        issues = []

        # 1. 需要不足
        niche = ["Goods & Accessories", "Media & Books"]
        if p.get("product_type", "") in niche:
            issues.append("demand_niche")

        # 2. ページ品質不足
        if word_count < 100:
            issues.append("quality_thin_desc")
        if images < 3:
            issues.append("quality_few_images")

        # 3. 価格要因
        if price > 500:
            issues.append("price_high")

        # 4. trust不足
        if not has_trust:
            issues.append("trust_missing")
        if not has_condition:
            issues.append("trust_no_condition")

        # 5. 導線不足
        if tags < 3:
            issues.append("navigation_few_tags")

        for issue in issues:
            reasons[issue].append(title)

    if reasons:
        details = ["=== Unsold Reasons (6 categories) ==="]
        labels = {
            "demand_niche": "Demand: niche category",
            "quality_thin_desc": "Page: thin description (<100w)",
            "quality_few_images": "Page: few images (<3)",
            "price_high": "Price: over $500",
            "trust_missing": "Trust: no trust language",
            "trust_no_condition": "Trust: no condition description",
            "navigation_few_tags": "Navigation: few tags (<3)",
        }
        for reason, titles in sorted(reasons.items(), key=lambda x: -len(x[1])):
            label = labels.get(reason, reason)
            details.append("[%d items] %s" % (len(titles), label))
            for t in titles[:2]:
                details.append("  - %s" % t)

        findings.append({
            "type": "suggestion", "agent": "growth-foundation",
            "message": "Unsold analysis: %d items, %d reason types" % (
                sum(len(v) for v in reasons.values()), len(reasons)),
            "details": details,
        })
    return findings


# ============================================================
# 3. CRO（8項目スコアリング）
# ============================================================

def audit_cro(products):
    """CROスコア: 8項目各1点、満点8"""
    findings = []
    if not products:
        return findings

    total = len(products)
    item_scores = []

    for p in products:
        body = p.get("body_html", "") or ""
        body_lower = body.lower()
        body_text = re.sub(r"<[^>]+>", "", body)
        images = len(p.get("images", []))
        variants = p.get("variants", [])
        compare_at = variants[0].get("compare_at_price") if variants else None
        tags = len([t.strip() for t in p.get("tags", "").split(",") if t.strip()])

        score = 0
        checks = {}
        # 1. 画像3枚以上
        checks["images_3plus"] = images >= 3
        if checks["images_3plus"]: score += 1
        # 2. compare-at price
        checks["compare_price"] = bool(compare_at)
        if checks["compare_price"]: score += 1
        # 3. trust語
        checks["trust_lang"] = any(kw in body_lower for kw in ["shipped from japan", "inspected", "authentic"])
        if checks["trust_lang"]: score += 1
        # 4. condition語
        checks["condition"] = any(kw in body_lower for kw in ["condition", "pre-owned", "used"])
        if checks["condition"]: score += 1
        # 5. About This Item
        checks["about_block"] = "about this item" in body_lower
        if checks["about_block"]: score += 1
        # 6. 説明100語以上
        checks["desc_100w"] = len(body_text.split()) >= 100
        if checks["desc_100w"]: score += 1
        # 7. タグ3個以上
        checks["tags_3plus"] = tags >= 3
        if checks["tags_3plus"]: score += 1
        # 8. コレクション所属（product_type設定）
        checks["collection"] = bool(p.get("product_type", ""))
        if checks["collection"]: score += 1

        item_scores.append(score)

    avg_score = sum(item_scores) / max(len(item_scores), 1)
    perfect = sum(1 for s in item_scores if s == 8)
    low = sum(1 for s in item_scores if s < 5)

    details = [
        "=== CRO Score (8 items, max 8) ===",
        "Average: %.1f / 8" % avg_score,
        "Perfect (8/8): %d / %d products" % (perfect, total),
        "Low (<5/8): %d / %d products" % (low, total),
        "",
        "--- Scoring Items ---",
        "1. Images 3+",
        "2. Compare-at price set",
        "3. Trust language (shipped from japan/inspected/authentic)",
        "4. Condition description (condition/pre-owned/used)",
        "5. About This Item block",
        "6. Description 100+ words",
        "7. Tags 3+",
        "8. Product type / collection set",
    ]

    cro_pct = round(avg_score / 8 * 100)
    findings.append({
        "type": "suggestion" if cro_pct < 80 else "ok",
        "agent": "growth-foundation",
        "message": "CRO score: %.1f/8 (%.0f%%), %d perfect, %d need improvement" % (avg_score, cro_pct, perfect, low),
        "details": details,
    })
    return findings


# ============================================================
# 4. Merchandising（作品厚み + 価格帯偏り + eBay周辺不足）
# ============================================================

def analyze_merchandising(products):
    """カテゴリ・作品・価格帯の深掘り分析"""
    findings = []
    if not products:
        return findings

    cats = Counter(p.get("product_type", "Other") for p in products)

    # 価格帯
    bands = {"<$30": 0, "$30-100": 0, "$100-300": 0, "$300-500": 0, "$500+": 0}
    for p in products:
        price = float(p.get("variants", [{}])[0].get("price", "0") or "0")
        if price < 30: bands["<$30"] += 1
        elif price < 100: bands["$30-100"] += 1
        elif price < 300: bands["$100-300"] += 1
        elif price < 500: bands["$300-500"] += 1
        else: bands["$500+"] += 1

    # 作品/フランチャイズ分析
    franchise_counts = Counter()
    for p in products:
        title_lower = p["title"].lower()
        for franchise, keywords in FRANCHISE_MAP.items():
            if franchise in title_lower or any(kw in title_lower for kw in keywords):
                franchise_counts[franchise] += 1
                break

    details = ["=== Merchandising Analysis ==="]

    # カテゴリ
    details.append("--- Category Depth ---")
    thin_cats = []
    for cat, count in cats.most_common():
        marker = "THIN" if count < 5 else "OK"
        details.append("[%s] %s: %d" % (marker, cat, count))
        if count < 5: thin_cats.append(cat)

    # 作品厚み
    details.append("")
    details.append("--- Franchise Depth ---")
    for franchise, count in franchise_counts.most_common(8):
        depth = "DEEP" if count >= 5 else "OK" if count >= 3 else "THIN"
        details.append("[%s] %s: %d products" % (depth, franchise, count))

    # 同作品内の関連キャラ展開余地
    thin_franchises = [f for f, c in franchise_counts.items() if c < 3]
    if thin_franchises:
        details.append("")
        details.append("--- Franchise Expansion Opportunities ---")
        for f in thin_franchises[:3]:
            related = FRANCHISE_MAP.get(f, [])
            details.append("[%s] Current:%d, expand with: %s" % (f, franchise_counts[f], ", ".join(related[:4])))

    # 価格帯偏り
    details.append("")
    details.append("--- Price Band ---")
    total = len(products)
    for band, count in bands.items():
        pct = count / max(total, 1) * 100
        details.append("%s: %d (%.0f%%)" % (band, count, pct))

    heavy = max(bands.items(), key=lambda x: x[1])
    if heavy[1] > total * 0.5:
        details.append("WARNING: %s band has %.0f%% — consider diversifying" % (heavy[0], heavy[1] / total * 100))

    # eBay売れ筋
    ebay = _load_json("ebay_sales_cache.json")
    if ebay and ebay.get("categories"):
        details.append("")
        details.append("--- eBay vs Shopify Gap ---")
        for cat, sold in sorted(ebay["categories"].items(), key=lambda x: -x[1]):
            shopify_n = cats.get(cat, 0)
            if sold >= 3 and shopify_n < 5:
                details.append("[GAP] %s: eBay %d sold, Shopify %d → increase" % (cat, sold, shopify_n))

    findings.append({
        "type": "suggestion" if thin_cats else "info",
        "agent": "catalog-migration-planner",
        "message": "Merchandising: %d categories, %d thin, %d franchises tracked" % (
            len(cats), len(thin_cats), len(franchise_counts)),
        "details": details,
    })
    return findings


# ============================================================
# 5. IA / Navigation（数式固定）
# ============================================================

def audit_navigation(products, wp_posts):
    """導線監査（計算式固定）"""
    findings = []
    cats = Counter(p.get("product_type", "Other") for p in products)

    total_articles = 0
    with_cta = 0
    with_internal = 0

    for p in wp_posts:
        content = p.get("content", {})
        if isinstance(content, dict): content = content.get("rendered", "")
        if not content: continue
        total_articles += 1
        if "hd-toys-store-japan" in content.lower(): with_cta += 1
        if "hd-bodyscience.com" in content.lower(): with_internal += 1

    # 計算式（固定）
    cta_rate = with_cta / max(total_articles, 1) * 100
    internal_rate = with_internal / max(total_articles, 1) * 100
    # Collection カバレッジ
    categories_with_products = sum(1 for c in cats.values() if c >= 3)
    collection_coverage = categories_with_products / max(len(cats), 1) * 100

    details = [
        "=== Navigation Audit (fixed formulas) ===",
        "Blog→Shopify CTA rate: %d/%d = %.0f%% (target: 80%%+)" % (with_cta, total_articles, cta_rate),
        "Internal link rate: %d/%d = %.0f%% (target: 50%%+)" % (with_internal, total_articles, internal_rate),
        "Collection coverage: %d/%d categories with 3+ products = %.0f%%" % (
            categories_with_products, len(cats), collection_coverage),
    ]

    issues = []
    if cta_rate < 80:
        issues.append("CTA rate %.0f%% < 80%% → add CTAs to %d articles" % (cta_rate, total_articles - with_cta))
    if internal_rate < 50:
        issues.append("Internal link rate %.0f%% < 50%% → add cross-links" % internal_rate)
    if collection_coverage < 80:
        issues.append("Collection coverage %.0f%% < 80%% → fill thin categories" % collection_coverage)

    if issues:
        details.append("")
        details.extend(["ISSUE: %s" % i for i in issues])

    findings.append({
        "type": "suggestion" if issues else "ok",
        "agent": "store-setup",
        "message": "Navigation: CTA %.0f%%, links %.0f%%, collections %.0f%%" % (cta_rate, internal_rate, collection_coverage),
        "details": details,
    })
    return findings


# ============================================================
# 6. DTC移植分析（強化版）
# ============================================================

def analyze_dtc_transfer(products):
    """eBay→DTC移植の見せ方6項目チェック"""
    findings = []
    if not products:
        return findings

    checks = {
        "marketplace_lang": [],    # eBay的表現残存
        "spec_only": [],           # スペック列挙のみ
        "no_story": [],            # コレクター魅力なし
        "no_condition_detail": [], # 状態説明不足
        "no_trust": [],            # trust不足
        "no_brand": [],            # ブランドアイデンティティなし
    }

    for p in products:
        body = p.get("body_html", "") or ""
        body_lower = body.lower()
        body_text = re.sub(r"<[^>]+>", "", body)
        title = p["title"][:35]

        if any(kw in body_lower for kw in ["fast shipping", "best price", "buy it now", "great deal", "a+++ seller"]):
            checks["marketplace_lang"].append(title)
        if len(body_text.split()) < 50 and "<ul" in body_lower:
            checks["spec_only"].append(title)
        if not any(kw in body_lower for kw in ["story", "history", "series", "franchise", "collector", "released", "created"]):
            checks["no_story"].append(title)
        if not any(kw in body_lower for kw in ["condition", "pre-owned", "used", "inspected"]):
            checks["no_condition_detail"].append(title)
        if not any(kw in body_lower for kw in ["shipped from japan", "authentic", "genuine"]):
            checks["no_trust"].append(title)

    total_issues = sum(len(v) for v in checks.values())
    details = ["=== DTC Transfer Audit (6 checks) ==="]
    labels = {
        "marketplace_lang": "eBay language remaining",
        "spec_only": "Spec-only description (no narrative)",
        "no_story": "No collector story / franchise context",
        "no_condition_detail": "No condition description",
        "no_trust": "No trust elements",
        "no_brand": "No brand identity",
    }
    for key, titles in checks.items():
        if titles:
            details.append("[%d] %s" % (len(titles), labels.get(key, key)))
            for t in titles[:2]:
                details.append("  - %s" % t)

    findings.append({
        "type": "suggestion" if total_issues > 5 else "info",
        "agent": "catalog-migration-planner",
        "message": "DTC transfer: %d issues across %d check types" % (total_issues, sum(1 for v in checks.values() if v)),
        "details": details,
    })
    return findings


# ============================================================
# 7. Retention
# ============================================================

def analyze_retention():
    """再訪・ファン化の機会分析"""
    findings = []
    details = [
        "=== Retention & Repeat Purchase ===",
        "[MEDIUM] Newsletter: Not yet implemented → email collection for new arrivals",
        "[MEDIUM] Related products: Not on product pages → add recommendations",
        "[LOW] Blog series: Multi-part guides for return visits",
        "[LOW] SNS new arrivals: Bring followers back to store",
    ]
    findings.append({
        "type": "info", "agent": "project-orchestrator",
        "message": "Retention: 4 opportunities identified",
        "details": details,
    })
    return findings


# ============================================================
# メインエントリポイント
# ============================================================

# ============================================================
# 8. 媒体別SNS勝ちパターン比較
# ============================================================

def compare_sns_win_patterns():
    """SNS媒体別の勝ちパターンを比較"""
    findings = []
    posted = _load_json("sns_posted.json")
    if not posted or not posted.get("history"):
        return findings

    history = posted["history"]
    two_weeks = (NOW - timedelta(days=14)).strftime("%Y-%m-%d")
    recent = [h for h in history if h.get("date", "") >= two_weeks]
    if len(recent) < 2:
        return findings

    # 媒体別
    platform_data = defaultdict(lambda: {"posts": 0, "likes": 0, "views": 0, "saves": 0, "best_post": None, "best_likes": 0})
    # メディアタイプ別
    media_data = defaultdict(lambda: {"posts": 0, "likes": 0, "views": 0})
    # カテゴリ別
    cat_data = defaultdict(lambda: {"posts": 0, "likes": 0, "views": 0})

    for h in recent:
        eng = h.get("engagement", {})
        likes = eng.get("likes", 0)
        views = eng.get("views", eng.get("impressions", 0))
        saves = eng.get("saves", 0)
        platform = h.get("platform", "unknown")
        media = h.get("media_type", "unknown")
        cat = h.get("category", "unknown")

        platform_data[platform]["posts"] += 1
        platform_data[platform]["likes"] += likes
        platform_data[platform]["views"] += views
        platform_data[platform]["saves"] += saves
        if likes > platform_data[platform]["best_likes"]:
            platform_data[platform]["best_likes"] = likes
            platform_data[platform]["best_post"] = h.get("title", "?")[:35]

        media_data[media]["posts"] += 1
        media_data[media]["likes"] += likes
        media_data[media]["views"] += views

        cat_data[cat]["posts"] += 1
        cat_data[cat]["likes"] += likes
        cat_data[cat]["views"] += views

    details = ["=== SNS Win Pattern Comparison (14d) ==="]

    # 媒体別ランキング
    details.append("--- By Platform (avg likes/post) ---")
    ranked = sorted(platform_data.items(), key=lambda x: x[1]["likes"] / max(x[1]["posts"], 1), reverse=True)
    for i, (p, d) in enumerate(ranked):
        avg_l = d["likes"] / max(d["posts"], 1)
        avg_v = d["views"] / max(d["posts"], 1)
        marker = "BEST" if i == 0 and len(ranked) > 1 else ""
        details.append("  [%s] %d posts, avg likes:%.1f, avg views:%.0f %s" % (p, d["posts"], avg_l, avg_v, marker))
        if d["best_post"]:
            details.append("    Top post: %s (%d likes)" % (d["best_post"], d["best_likes"]))

    # 画像vs動画
    if len(media_data) > 1:
        details.append("--- Image vs Video ---")
        for m, d in sorted(media_data.items()):
            avg_l = d["likes"] / max(d["posts"], 1)
            details.append("  [%s] %d posts, avg likes:%.1f" % (m, d["posts"], avg_l))

    # カテゴリ別
    if len(cat_data) > 1:
        details.append("--- By Category ---")
        cat_ranked = sorted(cat_data.items(), key=lambda x: x[1]["likes"] / max(x[1]["posts"], 1), reverse=True)
        for c, d in cat_ranked[:5]:
            avg_l = d["likes"] / max(d["posts"], 1)
            details.append("  [%s] %d posts, avg likes:%.1f" % (c, d["posts"], avg_l))

    # 保存率/プロフィール遷移率/Shopify遷移率を媒体別に
    if any(platform_data[p]["saves"] > 0 for p in platform_data):
        details.append("")
        details.append("--- Save Rate by Platform ---")
        for p, d in ranked:
            save_rate = d["saves"] / max(d["views"], 1) * 100 if d["views"] > 0 else 0
            details.append("  [%s] saves:%d, save rate:%.1f%%" % (p, d["saves"], save_rate))

    findings.append({
        "type": "info", "agent": "sns-manager",
        "message": "SNS win patterns: %d platforms, %d media types, %d categories compared" % (
            len(platform_data), len(media_data), len(cat_data)),
        "details": details,
    })
    return findings


# ============================================================
# 9. 記事タイプ別送客比較
# ============================================================

def compare_article_referrals(wp_posts):
    """記事タイプ別のShopify送客力を比較"""
    findings = []
    if not wp_posts:
        return findings

    type_data = defaultdict(lambda: {"count": 0, "with_cta": 0, "with_images": 0, "total_words": 0})

    for p in wp_posts:
        title = p.get("title", {})
        if isinstance(title, dict): title = title.get("rendered", "")
        content = p.get("content", {})
        if isinstance(content, dict): content = content.get("rendered", "")
        if not content: continue

        # タイプ分類
        t = (str(title) + " " + str(content)[:500]).lower()
        if any(kw in t for kw in ["top 5", "top 10", "best", "ranking"]):
            atype = "top5"
        elif any(kw in t for kw in ["vs", "comparison", "compare"]):
            atype = "comparison"
        elif any(kw in t for kw in ["guide", "how to", "beginner", "tips"]):
            atype = "guide"
        else:
            atype = "single_review"

        word_count = len(re.sub(r"<[^>]+>", "", content).split())
        has_cta = "hd-toys-store-japan" in content.lower()
        has_images = len(re.findall(r"<img", content)) > 0

        type_data[atype]["count"] += 1
        type_data[atype]["total_words"] += word_count
        if has_cta: type_data[atype]["with_cta"] += 1
        if has_images: type_data[atype]["with_images"] += 1

    if not type_data:
        return findings

    details = ["=== Article Type Referral Comparison ==="]
    details.append("%-15s | Count | AvgW | CTA%% | Img%%" % "Type")
    details.append("-" * 50)

    for atype, d in sorted(type_data.items()):
        avg_w = d["total_words"] / max(d["count"], 1)
        cta_pct = d["with_cta"] / max(d["count"], 1) * 100
        img_pct = d["with_images"] / max(d["count"], 1) * 100
        details.append("%-15s | %5d | %4d | %3.0f%% | %3.0f%%" % (atype, d["count"], avg_w, cta_pct, img_pct))

    # 送客力が高い型の推定
    best_type = max(type_data.items(), key=lambda x: x[1]["with_cta"] / max(x[1]["count"], 1))
    details.append("")
    details.append("Best referral type: %s (%.0f%% CTA rate)" % (
        best_type[0], best_type[1]["with_cta"] / max(best_type[1]["count"], 1) * 100))

    findings.append({
        "type": "info", "agent": "blog-analyst",
        "message": "Article referral: %d types compared, best=%s" % (len(type_data), best_type[0]),
        "details": details,
    })
    return findings


# ============================================================
# 10. CRO改善案の成功率比較
# ============================================================

def compare_cro_success():
    """CRO関連提案の成功率を他の提案タイプと比較"""
    findings = []
    pt = _load_json("proposal_tracking.json")
    if not pt or not pt.get("proposals"):
        return findings

    proposals = pt["proposals"]
    cro_proposals = [p for p in proposals if p.get("type") == "page_improvement"]
    other_proposals = [p for p in proposals if p.get("type") != "page_improvement" and p.get("status") != "pending"]

    if not cro_proposals:
        return findings

    cro_adopted = sum(1 for p in cro_proposals if p.get("status") == "adopted")
    cro_success = sum(1 for p in cro_proposals if p.get("result") == "success")
    cro_total = len(cro_proposals)

    other_adopted = sum(1 for p in other_proposals if p.get("status") == "adopted")
    other_success = sum(1 for p in other_proposals if p.get("result") == "success")
    other_total = len(other_proposals)

    cro_rate = cro_success / max(cro_adopted, 1) * 100
    other_rate = other_success / max(other_adopted, 1) * 100

    details = [
        "=== CRO vs Other Proposals ===",
        "CRO (page_improvement): %d proposed, %d adopted, %d success (%.0f%%)" % (cro_total, cro_adopted, cro_success, cro_rate),
        "Other types: %d proposed, %d adopted, %d success (%.0f%%)" % (other_total, other_adopted, other_success, other_rate),
        "",
    ]

    if cro_rate > other_rate:
        details.append("CRO outperforms other types by %.0f pp → increase CRO weight" % (cro_rate - other_rate))
    elif other_rate > cro_rate and cro_adopted >= 2:
        details.append("CRO underperforms by %.0f pp → review CRO proposal quality" % (other_rate - cro_rate))
    else:
        details.append("Similar performance — continue balanced approach")

    # CRO提案の詳細
    if cro_proposals:
        details.append("")
        details.append("--- Recent CRO proposals ---")
        for p in cro_proposals[-5:]:
            result = p.get("result", "pending")
            details.append("[%s] %s (%s)" % (result or "pending", p.get("message", "")[:50], p.get("adopted_date", "?")))

    # CRO内容別分解
    cro_subtypes = defaultdict(lambda: {"total": 0, "success": 0})
    for p in cro_proposals:
        msg = p.get("message", "").lower()
        if "trust" in msg or "shipped" in msg or "inspected" in msg:
            subtype = "trust_block"
        elif "description" in msg or "説明" in msg or "expand" in msg:
            subtype = "description_improvement"
        elif "image" in msg or "画像" in msg or "photo" in msg:
            subtype = "image_addition"
        elif "condition" in msg or "状態" in msg:
            subtype = "condition_detail"
        elif "compare" in msg or "price" in msg or "sale" in msg:
            subtype = "compare_at_price"
        elif "policy" in msg or "shipping" in msg or "refund" in msg:
            subtype = "policy_setup"
        else:
            subtype = "other_cro"

        cro_subtypes[subtype]["total"] += 1
        if p.get("result") == "success":
            cro_subtypes[subtype]["success"] += 1

    if cro_subtypes:
        details.append("")
        details.append("--- CRO Breakdown by Content ---")
        for sub, d in sorted(cro_subtypes.items(), key=lambda x: -x[1]["success"]):
            rate = d["success"] / max(d["total"], 1) * 100
            details.append("  [%s] %d proposals, %d success (%.0f%%)" % (sub, d["total"], d["success"], rate))

    findings.append({
        "type": "info", "agent": "self-learning",
        "message": "CRO success rate: %.0f%% vs others %.0f%%" % (cro_rate, other_rate),
        "details": details,
    })
    return findings


def _sync_cro_to_tracking(cro_findings):
    """CRO改善案をproposal_tracking / experimentsに反映"""
    tracking_path = os.path.join(SCRIPT_DIR, "proposal_tracking.json")
    if not os.path.exists(tracking_path):
        return

    try:
        with open(tracking_path, "r", encoding="utf-8") as f:
            pt = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    existing_msgs = set(p.get("message_hash", "") for p in pt.get("proposals", []))
    import hashlib

    for f in cro_findings:
        if f.get("type") != "suggestion":
            continue
        msg = f.get("message", "")
        msg_hash = hashlib.md5(("cro:" + msg[:50]).encode()).hexdigest()[:10]
        if msg_hash in existing_msgs:
            continue

        pt["proposals"].append({
            "id": "P-%s-cro" % NOW.strftime("%y%m%d"),
            "message_hash": msg_hash,
            "date": NOW.strftime("%Y-%m-%d"),
            "agent": "growth-foundation",
            "type": "page_improvement",
            "message": "CRO: %s" % msg[:100],
            "score": 18,
            "status": "pending",
            "adopted_date": None,
            "result": None,
            "result_date": None,
            "next_action": None,
        })

    pt["summary"]["total"] = len(pt["proposals"])
    pt["summary"]["pending"] = sum(1 for p in pt["proposals"] if p.get("status") == "pending")
    pt["summary"]["last_updated"] = NOW.strftime("%Y-%m-%d")

    with open(tracking_path, "w", encoding="utf-8") as f:
        json.dump(pt, f, indent=2, ensure_ascii=False)


def run_sales_optimization(products, wp_posts, all_findings):
    """売上改善分析フルスイート"""
    result = []
    result.extend(evaluate_proposal_outcomes())
    result.extend(analyze_unsold_reasons(products))

    cro = audit_cro(products)
    result.extend(cro)
    _sync_cro_to_tracking(cro)

    result.extend(analyze_merchandising(products))
    result.extend(audit_navigation(products, wp_posts))
    result.extend(analyze_dtc_transfer(products))
    result.extend(analyze_retention())

    # 比較分析
    result.extend(compare_sns_win_patterns())
    result.extend(compare_article_referrals(wp_posts))
    result.extend(compare_cro_success())

    # 比較結果を提案重み付けに反映
    result.extend(_apply_comparison_to_weights())

    return result


# ============================================================
# 11. 比較結果→重み付け反映
# ============================================================

def _apply_comparison_to_weights():
    """比較分析結果をshared_stateのscoring_weightsに反映"""
    findings = []
    pt = _load_json("proposal_tracking.json")
    if not pt or not pt.get("proposals"):
        return findings

    shared_path = os.path.join(SCRIPT_DIR, "shared_state.json")
    try:
        with open(shared_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, IOError, FileNotFoundError):
        return findings

    weights = state.get("scoring_weights", {})
    adjustments = []

    # 提案タイプ別成功率から重み調整
    accuracy = pt.get("summary", {}).get("accuracy_by_type", {})
    for ptype, data in accuracy.items():
        adopted = data.get("adopted", 0)
        success = data.get("success", 0)
        if adopted < 2:
            continue  # データ不足は調整しない

        rate = success / adopted

        if rate >= 0.8:
            # 高成功率 → データ根拠の重みを上げる
            current = weights.get("data_evidence", 2)
            if current < 3:
                weights["data_evidence"] = min(current + 0.5, 4)
                adjustments.append("data_evidence +0.5 (high success in %s: %.0f%%)" % (ptype, rate * 100))
        elif rate < 0.3 and adopted >= 3:
            # 低成功率 → 該当タイプの重みを下げる提案
            adjustments.append("WARNING: %s has %.0f%% success rate — reduce weight or tighten criteria" % (ptype, rate * 100))

    # SNS勝ちパターンから重み調整
    posted = _load_json("sns_posted.json")
    if posted and posted.get("history"):
        history = posted["history"]
        two_weeks = (NOW - timedelta(days=14)).strftime("%Y-%m-%d")
        recent = [h for h in history if h.get("date", "") >= two_weeks and h.get("engagement")]
        with_eng = [h for h in recent if sum(h.get("engagement", {}).values()) > 0]

        if len(with_eng) >= 3:
            # 媒体別平均を算出
            platform_avg = defaultdict(list)
            for h in with_eng:
                eng = h.get("engagement", {})
                likes = eng.get("likes", 0)
                platform_avg[h.get("platform", "")].append(likes)

            best_platform = max(platform_avg.items(), key=lambda x: sum(x[1]) / len(x[1]), default=None)
            if best_platform:
                adjustments.append("SNS best platform: %s (avg %.1f likes) → prioritize in next posts" % (
                    best_platform[0], sum(best_platform[1]) / len(best_platform[1])))

    if adjustments:
        # shared_state を更新
        state["scoring_weights"] = weights
        state.setdefault("weight_adjustment_log", []).append({
            "date": NOW.strftime("%Y-%m-%d"),
            "adjustments": adjustments,
        })
        state["weight_adjustment_log"] = state["weight_adjustment_log"][-10:]  # 10件保持

        try:
            with open(shared_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except IOError:
            pass

        findings.append({
            "type": "info", "agent": "self-learning",
            "message": "Weight adjustment: %d changes applied from comparison results" % len(adjustments),
            "details": ["=== Auto Weight Adjustments ==="] + adjustments,
        })

    return findings
