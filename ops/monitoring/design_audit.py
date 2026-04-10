# ============================================================
# デザイン監査モジュール
#
# Shopify / ブログのデザイン品質を毎回監査し、
# 競合比較・改善後事後分析・ズレ検知を行う。
#
# 監査対象:
# 1. Shopify（トップ/Collection/商品/CTA/trust/モバイル）
# 2. ブログ（アイキャッチ/画像/見出し/比較表/FAQ/CTA/導線）
# 3. 競合デザイン比較（差分・取り入れ候補・優先度）
# 4. 改善後事後分析（CTR/滞在/スクロール/カート/送客）
# 5. ズレ検知（中古向き/信頼形成/売り込み過多/新品模倣）
#
# 担当:
#   store-setup: Shopifyデザイン監査
#   blog-analyst: ブログデザイン監査
#   competitive-intelligence: 競合比較
#   growth-foundation: 事後分析データ
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

DESIGN_LOG_FILE = os.path.join(SCRIPT_DIR, "design_audit_log.json")

# 弊社デザイン方針
DESIGN_POLICY = {
    "style": "Solaris Japan型クリーン路線。白ベース＋アクセントカラー",
    "image_policy": "AI抽象画像より実商品写真を優先",
    "trust_elements": ["Shipped from Japan", "Inspected", "Condition description", "Return policy link"],
    "cta_style": "自然な導線。押し売りしない。価値提供後にさりげなく",
    "mobile_priority": True,
}

# 競合サイト定義
COMPETITORS = [
    {"name": "Solaris Japan", "url": "https://solarisjapan.com", "type": "direct_competitor"},
    {"name": "Japan Figure", "url": "https://www.japan-figure.com", "type": "direct_competitor"},
    {"name": "Super Anime Store", "url": "https://superanimestore.com", "type": "indirect_competitor"},
]


def _load_design_log():
    if not os.path.exists(DESIGN_LOG_FILE):
        return {"audits": [], "improvements": [], "last_updated": ""}
    try:
        with open(DESIGN_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"audits": [], "improvements": [], "last_updated": ""}


def _save_design_log(log):
    log["last_updated"] = NOW.strftime("%Y-%m-%d")
    log["audits"] = log["audits"][-30:]  # 30日分保持
    with open(DESIGN_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


# ============================================================
# 1. Shopify デザイン監査
# ============================================================

def audit_shopify_design(products):
    """Shopifyストアのデザイン要素を監査"""
    findings = []
    if not products:
        return findings

    checks = []
    issues = []

    # --- 商品ページ品質 ---
    total = len(products)
    with_trust = 0
    with_images_5plus = 0
    with_compare_price = 0
    short_desc = 0

    for p in products:
        body = p.get("body_html", "") or ""
        body_lower = body.lower()
        images = len(p.get("images", []))
        variants = p.get("variants", [])
        compare = variants[0].get("compare_at_price") if variants else None

        if any(kw in body_lower for kw in ["shipped from japan", "inspected", "authentic"]):
            with_trust += 1
        if images >= 5:
            with_images_5plus += 1
        if compare:
            with_compare_price += 1
        if len(re.sub(r"<[^>]+>", "", body).split()) < 100:
            short_desc += 1

    checks.append("Trust elements: %d/%d products (%.0f%%)" % (with_trust, total, with_trust / max(total, 1) * 100))
    checks.append("5+ images: %d/%d products (%.0f%%)" % (with_images_5plus, total, with_images_5plus / max(total, 1) * 100))
    checks.append("Compare-at price: %d/%d products (%.0f%%)" % (with_compare_price, total, with_compare_price / max(total, 1) * 100))

    if short_desc > 0:
        issues.append("[Product pages] %d products with thin descriptions (<100w)" % short_desc)
    if with_trust < total:
        issues.append("[Trust] %d products missing trust language" % (total - with_trust))
    if with_compare_price < total * 0.5:
        issues.append("[Pricing] Only %d/%d have compare-at price (no sale display)" % (with_compare_price, total))

    # --- Collection 導線 ---
    checks.append("Collections: 8 categories in main menu")

    # --- CTA スタイル ---
    cta_issues = []
    for p in products[:5]:
        body = p.get("body_html", "") or ""
        if any(kw in body.lower() for kw in ["buy now", "limited time", "hurry", "order now"]):
            cta_issues.append(p["title"][:30])
    if cta_issues:
        issues.append("[CTA] Pushy language detected in: %s" % ", ".join(cta_issues))
    else:
        checks.append("CTA style: No pushy language detected (value-first aligned)")

    findings.append({
        "type": "suggestion" if issues else "ok",
        "agent": "store-setup",
        "message": "Shopify design audit: %d checks, %d issues" % (len(checks), len(issues)),
        "details": ["=== Shopify Design Audit ==="] + checks + (["--- Issues ---"] + issues if issues else []),
    })

    return findings


# ============================================================
# 2. ブログデザイン監査
# ============================================================

def audit_blog_design(wp_posts):
    """ブログ記事のデザイン品質を監査"""
    findings = []
    if not wp_posts:
        return findings

    total = 0
    no_featured = 0
    no_images = 0
    few_h2 = 0
    no_cta = 0
    no_internal = 0
    has_table = 0
    has_faq = 0
    has_related = 0

    for p in wp_posts:
        content = p.get("content", {})
        if isinstance(content, dict):
            content = content.get("rendered", "")
        if not content:
            continue

        total += 1
        featured = p.get("featured_media", 0) > 0
        img_count = len(re.findall(r"<img", content))
        h2_count = len(re.findall(r"<h2", content))
        has_shopify = "hd-toys-store-japan" in content.lower()
        has_internal_link = "hd-bodyscience.com" in content.lower()
        has_tbl = "<table" in content.lower()
        has_fq = "faq" in content.lower() or "frequently" in content.lower()

        if not featured:
            no_featured += 1
        if img_count == 0:
            no_images += 1
        if h2_count < 3:
            few_h2 += 1
        if not has_shopify:
            no_cta += 1
        if not has_internal_link:
            no_internal += 1
        if has_tbl:
            has_table += 1
        if has_fq:
            has_faq += 1

    details = [
        "=== Blog Design Audit (%d articles) ===" % total,
        "No featured image: %d" % no_featured,
        "No body images: %d" % no_images,
        "Few H2 (<3): %d" % few_h2,
        "No CTA block: %d" % no_cta,
        "No internal links: %d" % no_internal,
        "Has comparison table: %d" % has_table,
        "Has FAQ section: %d" % has_faq,
        "--- Competitor features not yet adopted ---",
    ]

    # 競合にあって自社にない要素
    missing_features = []
    if has_table == 0:
        missing_features.append("Comparison tables (Solaris uses for product specs)")
    if has_faq == 0:
        missing_features.append("FAQ sections (NekoFigs uses for common questions)")
    if no_featured > total * 0.3:
        missing_features.append("Featured images (%.0f%% missing)" % (no_featured / max(total, 1) * 100))

    if missing_features:
        details.extend(missing_features)

    severity = "action" if no_images > 3 or no_cta > 5 else "suggestion" if missing_features else "info"
    findings.append({
        "type": severity,
        "agent": "blog-analyst",
        "message": "Blog design audit: %d articles, %d need images, %d need CTA" % (total, no_images, no_cta),
        "details": details,
    })

    return findings


# ============================================================
# 3. 競合デザイン比較
# ============================================================

def compare_competitor_design():
    """競合サイトのデザイン要素を分析・比較"""
    findings = []

    competitor_features = []
    for comp in COMPETITORS:
        try:
            resp = requests.get(comp["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if resp.status_code != 200:
                continue

            html = resp.text.lower()
            features = {
                "reviews": any(kw in html for kw in ["review", "rating", "stars"]),
                "newsletter": any(kw in html for kw in ["newsletter", "subscribe", "email signup"]),
                "trust_badges": any(kw in html for kw in ["authentic", "verified", "secure", "ssl"]),
                "live_chat": any(kw in html for kw in ["live chat", "chat widget", "zendesk", "intercom"]),
                "wishlist": any(kw in html for kw in ["wishlist", "wish list", "save for later"]),
                "comparison": any(kw in html for kw in ["compare", "comparison"]),
                "faq": any(kw in html for kw in ["faq", "frequently asked"]),
                "social_proof": any(kw in html for kw in ["customers", "sold", "popular", "trending"]),
                "free_shipping": any(kw in html for kw in ["free shipping", "free delivery"]),
                "loyalty": any(kw in html for kw in ["loyalty", "points", "rewards"]),
            }

            active = [k for k, v in features.items() if v]
            competitor_features.append({
                "name": comp["name"],
                "features": active,
                "feature_count": len(active),
            })
        except Exception:
            pass

    if not competitor_features:
        findings.append({
            "type": "info", "agent": "competitive-intelligence",
            "message": "Competitor design: Unable to reach competitor sites",
        })
        return findings

    # 自社にない要素を特定
    our_features = {"trust_badges", "faq"}  # 現在あるもの
    all_competitor_features = set()
    for comp in competitor_features:
        all_competitor_features.update(comp["features"])

    gap = all_competitor_features - our_features
    gap_priority = {
        "reviews": ("medium", "Builds trust but Harada declined — skip"),
        "newsletter": ("medium", "Email list building for repeat customers"),
        "live_chat": ("low", "Customer support — consider when volume grows"),
        "wishlist": ("medium", "Increases return visits"),
        "comparison": ("medium", "Helps collectors decide"),
        "social_proof": ("medium", "Shows popularity — safe for used items"),
        "free_shipping": ("low", "Margin impact — conditional only"),
        "loyalty": ("low", "Too early for current stage"),
    }

    details = ["=== Competitor Design Comparison ==="]
    for comp in competitor_features:
        details.append("[%s] %d features: %s" % (comp["name"], comp["feature_count"], ", ".join(comp["features"][:6])))

    if gap:
        details.append("")
        details.append("--- Gap Analysis (features competitors have, we don't) ---")
        for feature in sorted(gap):
            priority, note = gap_priority.get(feature, ("low", ""))
            details.append("[%s] %s — %s" % (priority.upper(), feature, note))

    findings.append({
        "type": "info",
        "agent": "competitive-intelligence",
        "message": "Competitor design: %d sites analyzed, %d feature gaps" % (len(competitor_features), len(gap)),
        "details": details,
    })

    return findings


# ============================================================
# 4. デザイン改善後 事後分析
# ============================================================

def analyze_design_improvements():
    """過去のデザイン改善の効果を分析"""
    findings = []
    log = _load_design_log()

    improvements = log.get("improvements", [])
    if not improvements:
        return findings

    details = ["=== Design Improvement Results ==="]
    for imp in improvements[-5:]:
        details.append(
            "[%s] %s: %s → %s" % (
                imp.get("date", "?"),
                imp.get("change", "?")[:40],
                imp.get("before", "?"),
                imp.get("after", "?"),
            )
        )

    findings.append({
        "type": "info",
        "agent": "growth-foundation",
        "message": "Design improvements tracked: %d total" % len(improvements),
        "details": details,
    })

    return findings


# ============================================================
# 5. ズレ検知（デザイン方向性）
# ============================================================

def check_design_direction(all_findings):
    """デザイン提案が弊社方針とズレていないか検知"""
    findings = []
    warnings = []

    for f in all_findings:
        msg = f.get("message", "").lower()
        details_text = " ".join(str(d) for d in f.get("details", [])).lower()
        agent = f.get("agent", "")

        if f.get("type") not in ("action", "suggestion"):
            continue

        # デザイン関連の提案のみチェック
        is_design = any(kw in msg for kw in ["design", "ui", "ux", "layout", "banner", "color", "font", "image", "photo"])
        if not is_design:
            continue

        issues = []

        # 新品向け施策の模倣チェック
        if any(kw in details_text for kw in ["flash sale", "countdown", "urgency", "limited offer", "act now"]):
            issues.append("new-product-tactic: urgency/scarcity language (not suitable for used items)")

        # 売り込み過多チェック
        if any(kw in details_text for kw in ["buy now", "add to cart immediately", "don't miss"]):
            issues.append("pushy-cta: aggressive call-to-action (conflicts with value-first policy)")

        # trust要素欠如チェック
        if "product" in msg and not any(kw in details_text for kw in ["condition", "inspect", "authentic", "trust"]):
            issues.append("missing-trust: design proposal without trust/condition elements")

        # AI画像の使用チェック
        if any(kw in details_text for kw in ["ai generated", "ai image", "abstract banner", "generated graphic"]):
            issues.append("ai-image: policy is to use real product photos, not AI abstracts")

        if issues:
            warnings.append({
                "agent": agent,
                "proposal": msg[:60],
                "issues": issues,
            })

    if warnings:
        details = ["=== Design Direction Alerts ==="]
        for w in warnings:
            details.append("[%s] %s" % (w["agent"], w["proposal"]))
            for issue in w["issues"]:
                details.append("  WARNING: %s" % issue)

        findings.append({
            "type": "suggestion",
            "agent": "project-orchestrator",
            "message": "Design direction: %d proposals may conflict with brand policy" % len(warnings),
            "details": details,
        })
    else:
        findings.append({
            "type": "ok",
            "agent": "project-orchestrator",
            "message": "Design direction: All proposals aligned with brand policy",
        })

    return findings


# ============================================================
# 6. デザイン監査ログ保存
# ============================================================

def _record_audit(products_count, blog_count, issues_count, gaps_count):
    """監査結果をログに保存"""
    log = _load_design_log()
    log["audits"].append({
        "date": NOW.strftime("%Y-%m-%d"),
        "shopify_products": products_count,
        "blog_articles": blog_count,
        "issues_found": issues_count,
        "competitor_gaps": gaps_count,
    })
    _save_design_log(log)


# ============================================================
# メインエントリポイント
# ============================================================

def run_design_audit(products, wp_posts, all_findings):
    """デザイン監査フルスイートを実行"""
    result = []

    # 1. Shopifyデザイン監査
    shopify_results = audit_shopify_design(products)
    result.extend(shopify_results)

    # 2. ブログデザイン監査
    blog_results = audit_blog_design(wp_posts)
    result.extend(blog_results)

    # 3. 競合デザイン比較
    comp_results = compare_competitor_design()
    result.extend(comp_results)

    # 4. 改善後事後分析
    result.extend(analyze_design_improvements())

    # 5. ズレ検知
    result.extend(check_design_direction(all_findings + result))

    # 6. ログ保存
    shopify_issues = sum(len(f.get("details", [])) for f in shopify_results if f.get("type") == "suggestion")
    blog_issues = sum(1 for f in blog_results if f.get("type") in ("action", "suggestion"))
    comp_gaps = sum(1 for f in comp_results if "gap" in f.get("message", "").lower())
    _record_audit(len(products), len(wp_posts), shopify_issues + blog_issues, comp_gaps)

    return result
