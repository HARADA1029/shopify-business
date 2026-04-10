# ============================================================
# ブログ記事自動投稿 + PDCA改善 + 画像監査 + カテゴリ監査モジュール
#
# 担当: blog-analyst (主担当), content-strategist, growth-foundation
#
# 機能:
# 1. 記事テーマ候補の抽出
# 2. テンプレート管理
# 3. 記事品質監査（画像/CTA/構造/内部リンク）
# 4. 画像監査（アイキャッチ/本文画像/枚数）
# 5. カテゴリ別監査（商品数/記事数/画像率/リンク率）
# 6. 投稿後PDCA（記事タイプ別比較）
# 7. blog_state 蓄積
# 8. proposal_history / experiments 連携
# 9. 競合記事リサーチ
# ============================================================

import json
import os
import re
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

import requests

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

BLOG_STATE_FILE = os.path.join(SCRIPT_DIR, "blog_state.json")

SHOPIFY_URL = "https://hd-toys-store-japan.myshopify.com"
EBAY_STORE = "https://www.ebay.com/str/hdtoysstore"

# カテゴリキーワード（商品タイプとブログ記事のマッチング用）
CATEGORY_KEYWORDS = {
    "Action Figures": ["action figure", "figuarts", "figma", "bandai", "sentai", "beyblade", "gundam"],
    "Scale Figures": ["scale figure", "nendoroid", "banpresto", "ichiban kuji", "statue"],
    "Trading Cards": ["card", "tcg", "pokemon card", "yu-gi-oh", "weiss schwarz"],
    "Video Games": ["game", "playstation", "nintendo", "console", "gameboy"],
    "Electronic Toys": ["tamagotchi", "digivice", "digital pet", "electronic"],
    "Media & Books": ["manga", "book", "dvd", "blu-ray", "art book", "cd"],
    "Plush & Soft Toys": ["plush", "stuffed", "doll", "mascot", "sylvanian"],
    "Goods & Accessories": ["goods", "accessory", "bag", "watch", "pen", "copic"],
}

# テンプレート定義
STANDARD_TEMPLATE = {
    "name": "standard", "description": "単品レビュー・紹介形式",
    "article_type": "single_review",
}
TOP5_TEMPLATE = {
    "name": "top5_ranking", "description": "Top 5 ランキング形式",
    "article_type": "top5",
}
COMPARISON_TEMPLATE = {
    "name": "comparison", "description": "比較記事形式",
    "article_type": "comparison",
}
GUIDE_TEMPLATE = {
    "name": "beginner_guide", "description": "初心者ガイド形式",
    "article_type": "guide",
}


def _load_blog_state():
    if not os.path.exists(BLOG_STATE_FILE):
        return {
            "articles_analyzed": [],
            "image_audit": [],
            "category_audit": [],
            "pdca_history": [],
            "template_scores": {},
            "_last_updated": "",
        }
    try:
        with open(BLOG_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"articles_analyzed": [], "image_audit": [], "category_audit": [], "pdca_history": [], "template_scores": {}, "_last_updated": ""}


def _save_blog_state(state):
    state["_last_updated"] = NOW.strftime("%Y-%m-%d")
    with open(BLOG_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _classify_article_type(title, content):
    """記事タイプを推定"""
    t = (str(title) + " " + str(content)[:500]).lower()
    if any(kw in t for kw in ["top 5", "top 10", "best", "ranking", "must-have"]):
        return "top5"
    if any(kw in t for kw in ["vs", "comparison", "compare", "versus", "which"]):
        return "comparison"
    if any(kw in t for kw in ["guide", "how to", "beginner", "tips", "getting started"]):
        return "guide"
    return "single_review"


def _detect_category(title, content):
    """記事のカテゴリを推定"""
    text = (str(title) + " " + str(content)[:1000]).lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return cat
    return "Other"


# ============================================================
# 1. 記事テーマ候補抽出
# ============================================================

def suggest_article_topics(products, wp_posts, wp_categories):
    """Shopify 商品 × WP 記事ギャップから記事テーマを提案"""
    findings = []
    if not products:
        return findings

    wp_titles = set()
    for p in wp_posts:
        title = p.get("title", {})
        if isinstance(title, dict):
            title = title.get("rendered", "")
        wp_titles.add(str(title).lower())

    uncovered = []
    for p in products:
        title_lower = p["title"].lower()
        words = [w for w in title_lower.split() if len(w) > 4]
        covered = any(w in " ".join(wp_titles) for w in words[:3])
        if not covered:
            uncovered.append({
                "title": p["title"], "handle": p["handle"],
                "type": p.get("product_type", ""), "images": len(p.get("images", [])),
            })

    if uncovered:
        by_cat = defaultdict(list)
        for item in uncovered:
            by_cat[item["type"] or "Other"].append(item)

        details = []
        for cat, items in sorted(by_cat.items(), key=lambda x: -len(x[1])):
            if len(items) >= 2:
                details.append("[%s] Top 5 article: %d uncovered products" % (cat, len(items)))
            for item in items[:1]:
                details.append("[%s] Single review: %s" % (cat, item["title"][:50]))

        findings.append({
            "type": "action", "agent": "blog-analyst",
            "message": "Blog topics: %d products need articles (%d categories)" % (len(uncovered), len(by_cat)),
            "details": details[:5],
        })

    return findings


# ============================================================
# 2. 画像監査
# ============================================================

def audit_article_images(wp_posts):
    """全記事の画像状況を監査"""
    findings = []
    if not wp_posts:
        return findings

    no_image = []
    few_images = []
    good_images = []
    total = 0

    for p in wp_posts:
        title = p.get("title", {})
        if isinstance(title, dict):
            title = title.get("rendered", "")

        content = p.get("content", {})
        if isinstance(content, dict):
            content = content.get("rendered", "")

        if not content:
            continue

        total += 1
        # アイキャッチ（featured_media）
        has_featured = p.get("featured_media", 0) > 0
        # 本文画像
        img_count = len(re.findall(r'<img', str(content)))
        # 引用表記
        has_citation = bool(re.search(r'(source|credit|photo by|image from|©)', str(content).lower()))

        if img_count == 0 and not has_featured:
            no_image.append({"title": str(title)[:45], "id": p.get("id", 0)})
        elif img_count < 2:
            few_images.append({"title": str(title)[:45], "id": p.get("id", 0), "count": img_count, "featured": has_featured})
        else:
            good_images.append({"title": str(title)[:45], "count": img_count})

    # サマリ
    details = [
        "=== Blog Image Audit (%d articles) ===" % total,
        "No images: %d articles" % len(no_image),
        "Few images (1-2): %d articles" % len(few_images),
        "Good images (3+): %d articles" % len(good_images),
    ]

    if no_image:
        details.append("--- No image articles ---")
        for a in no_image[:5]:
            details.append("  [ID:%d] %s" % (a["id"], a["title"]))

    if few_images:
        details.append("--- Few image articles ---")
        for a in few_images[:5]:
            details.append("  [ID:%d] %s (%d images, featured:%s)" % (
                a["id"], a["title"], a["count"], "yes" if a["featured"] else "no"))

    severity = "action" if len(no_image) > 3 else "suggestion" if no_image else "info"
    findings.append({
        "type": severity, "agent": "blog-analyst",
        "message": "Blog image audit: %d no-image, %d few-image, %d good (%d total)" % (
            len(no_image), len(few_images), len(good_images), total),
        "details": details,
    })

    # blog_state に記録
    state = _load_blog_state()
    state["image_audit"] = [{
        "date": NOW.strftime("%Y-%m-%d"),
        "total": total,
        "no_image": len(no_image),
        "few_images": len(few_images),
        "good_images": len(good_images),
    }]
    _save_blog_state(state)

    return findings


# ============================================================
# 3. カテゴリ別監査
# ============================================================

def audit_categories(products, wp_posts):
    """カテゴリごとの商品数/記事数/画像率/リンク率を監査"""
    findings = []
    if not products:
        return findings

    # 商品カテゴリ集計
    product_cats = Counter(p.get("product_type", "Other") for p in products)

    # 記事カテゴリ集計
    article_cats = defaultdict(lambda: {"count": 0, "with_images": 0, "with_cta": 0, "with_internal_links": 0})

    for p in wp_posts:
        title = p.get("title", {})
        if isinstance(title, dict):
            title = title.get("rendered", "")
        content = p.get("content", {})
        if isinstance(content, dict):
            content = content.get("rendered", "")

        cat = _detect_category(title, content)
        article_cats[cat]["count"] += 1

        if re.findall(r'<img', str(content)):
            article_cats[cat]["with_images"] += 1
        if "hd-toys-store-japan" in str(content).lower():
            article_cats[cat]["with_cta"] += 1
        if "hd-bodyscience.com" in str(content).lower():
            article_cats[cat]["with_internal_links"] += 1

    # レポート
    details = ["=== Category Audit ==="]
    details.append("%-20s | Prod | Art | Img%% | CTA%% | Link%%" % "Category")
    details.append("-" * 60)

    all_cats = set(list(product_cats.keys()) + list(article_cats.keys()))
    gaps = []

    for cat in sorted(all_cats):
        prod_count = product_cats.get(cat, 0)
        art = article_cats.get(cat, {"count": 0, "with_images": 0, "with_cta": 0, "with_internal_links": 0})
        art_count = art["count"]
        img_rate = (art["with_images"] / art_count * 100) if art_count > 0 else 0
        cta_rate = (art["with_cta"] / art_count * 100) if art_count > 0 else 0
        link_rate = (art["with_internal_links"] / art_count * 100) if art_count > 0 else 0

        details.append("%-20s | %4d | %3d | %3.0f%% | %3.0f%% | %3.0f%%" % (
            cat[:20], prod_count, art_count, img_rate, cta_rate, link_rate))

        # ギャップ検出
        if prod_count > 0 and art_count == 0:
            gaps.append("[%s] %d products, 0 articles" % (cat, prod_count))
        elif prod_count > 3 and art_count < 2:
            gaps.append("[%s] %d products, only %d articles" % (cat, prod_count, art_count))

    if gaps:
        details.append("")
        details.append("--- Category Gaps ---")
        details.extend(gaps)

    findings.append({
        "type": "action" if gaps else "info",
        "agent": "blog-analyst",
        "message": "Category audit: %d categories, %d gaps found" % (len(all_cats), len(gaps)),
        "details": details,
    })

    # blog_state に記録
    state = _load_blog_state()
    state["category_audit"] = [{
        "date": NOW.strftime("%Y-%m-%d"),
        "categories": {
            cat: {
                "products": product_cats.get(cat, 0),
                "articles": article_cats.get(cat, {}).get("count", 0),
                "image_rate": round((article_cats.get(cat, {}).get("with_images", 0) / max(article_cats.get(cat, {}).get("count", 1), 1)) * 100),
                "cta_rate": round((article_cats.get(cat, {}).get("with_cta", 0) / max(article_cats.get(cat, {}).get("count", 1), 1)) * 100),
            }
            for cat in all_cats
        },
        "gaps": len(gaps),
    }]
    _save_blog_state(state)

    return findings


# ============================================================
# 4. 記事品質監査 + 投稿後PDCA
# ============================================================

def analyze_article_performance(wp_posts):
    """全記事の品質監査と改善提案"""
    findings = []
    if not wp_posts:
        return findings

    state = _load_blog_state()
    improvements = []
    type_stats = defaultdict(lambda: {"count": 0, "avg_words": 0, "total_words": 0, "with_images": 0, "with_cta": 0})

    for p in wp_posts:
        title = p.get("title", {})
        if isinstance(title, dict):
            title = title.get("rendered", "")
        content = p.get("content", {})
        if isinstance(content, dict):
            content = content.get("rendered", "")
        if not content:
            continue

        post_id = p.get("id", 0)
        word_count = len(re.sub(r'<[^>]+>', '', content).split())
        has_shopify_cta = "hd-toys-store-japan" in content.lower()
        h2_count = len(re.findall(r'<h2', content))
        img_count = len(re.findall(r'<img', content))
        has_featured = p.get("featured_media", 0) > 0
        has_internal_links = "hd-bodyscience.com" in content.lower()
        article_type = _classify_article_type(title, content)

        # タイプ別集計
        type_stats[article_type]["count"] += 1
        type_stats[article_type]["total_words"] += word_count
        if img_count > 0:
            type_stats[article_type]["with_images"] += 1
        if has_shopify_cta:
            type_stats[article_type]["with_cta"] += 1

        # 改善ルール
        issues = []
        if not has_shopify_cta:
            issues.append("CTA missing")
        if word_count < 500:
            issues.append("Too short (%dw)" % word_count)
        if h2_count < 2:
            issues.append("Few H2 (%d)" % h2_count)
        if img_count == 0:
            issues.append("No images")
        elif img_count < 3:
            issues.append("Few images (%d)" % img_count)
        if not has_featured:
            issues.append("No featured image")
        if not has_internal_links:
            issues.append("No internal links")

        if issues:
            improvements.append("[%s] %s: %s" % (article_type, str(title)[:35], "; ".join(issues)))

    # 改善提案
    if improvements:
        findings.append({
            "type": "action", "agent": "blog-analyst",
            "message": "Blog PDCA: %d articles need improvement" % len(improvements),
            "details": improvements[:8],
        })

    # タイプ別比較
    if type_stats:
        type_details = ["=== Article Type Comparison ==="]
        for atype, stats in sorted(type_stats.items()):
            count = stats["count"]
            avg_words = stats["total_words"] / count if count > 0 else 0
            img_rate = stats["with_images"] / count * 100 if count > 0 else 0
            cta_rate = stats["with_cta"] / count * 100 if count > 0 else 0
            type_details.append(
                "[%s] %d articles, avg %dw, %.0f%% images, %.0f%% CTA"
                % (atype, count, avg_words, img_rate, cta_rate)
            )

        findings.append({
            "type": "info", "agent": "blog-analyst",
            "message": "Article type analysis: %d types, %d total articles" % (len(type_stats), sum(s["count"] for s in type_stats.values())),
            "details": type_details,
        })

    # blog_state に PDCA 履歴を蓄積
    today_metrics = {
        "no_images": sum(1 for p in wp_posts if not re.findall(r"<img", str(p.get("content", {}).get("rendered", "") if isinstance(p.get("content"), dict) else p.get("content", "")))),
        "no_category": sum(1 for p in wp_posts if len(p.get("categories", [])) <= 1),
        "no_cta": sum(1 for p in wp_posts if "hd-toys-store-japan" not in str(p.get("content", {}).get("rendered", "") if isinstance(p.get("content"), dict) else p.get("content", "")).lower()),
        "no_internal_links": sum(1 for p in wp_posts if "hd-bodyscience.com" not in str(p.get("content", {}).get("rendered", "") if isinstance(p.get("content"), dict) else p.get("content", "")).lower()),
        "short_content": sum(1 for p in wp_posts if len(re.sub(r"<[^>]+>", "", str(p.get("content", {}).get("rendered", "") if isinstance(p.get("content"), dict) else p.get("content", ""))).split()) < 500),
    }

    state["pdca_history"].append({
        "date": NOW.strftime("%Y-%m-%d"),
        "total_articles": len(wp_posts),
        "issues_found": len(improvements),
        "type_stats": {k: {"count": v["count"], "avg_words": round(v["total_words"] / max(v["count"], 1))} for k, v in type_stats.items()},
        "quality_metrics": today_metrics,
    })
    state["pdca_history"] = [h for h in state["pdca_history"] if h.get("date", "") >= (NOW - timedelta(days=30)).strftime("%Y-%m-%d")]

    # === 予防提案後の改善追跡 ===
    if len(state["pdca_history"]) >= 2:
        prev = state["pdca_history"][-2].get("quality_metrics", {})
        curr = today_metrics
        if prev:
            tracking_details = ["--- article_theme Quality Tracking ---"]
            improved = []
            worsened = []
            for metric in ["no_images", "no_category", "no_cta", "no_internal_links", "short_content"]:
                p_val = prev.get(metric, 0)
                c_val = curr.get(metric, 0)
                if c_val < p_val:
                    improved.append("%s: %d → %d (improved)" % (metric, p_val, c_val))
                elif c_val > p_val:
                    worsened.append("%s: %d → %d (worsened)" % (metric, p_val, c_val))

            if improved:
                tracking_details.append("Improved:")
                tracking_details.extend(["  %s" % i for i in improved])
            if worsened:
                tracking_details.append("Worsened:")
                tracking_details.extend(["  %s" % w for w in worsened])
            if not improved and not worsened:
                tracking_details.append("No change from previous run")

            findings.append({
                "type": "info" if not worsened else "suggestion",
                "agent": "blog-analyst",
                "message": "Blog quality tracking: %d improved, %d worsened" % (len(improved), len(worsened)),
                "details": tracking_details,
            })

    _save_blog_state(state)

    return findings


# ============================================================
# 5. 競合記事リサーチ
# ============================================================

def research_competitor_articles():
    """競合ブログの記事構成をリサーチする"""
    findings = []
    competitor_blogs = [
        {"name": "Solaris Japan Blog", "url": "https://solarisjapan.com/blogs/news"},
        {"name": "NekoFigs", "url": "https://nekofigs.com/"},
    ]

    insights = []
    for comp in competitor_blogs:
        try:
            resp = requests.get(comp["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if resp.status_code == 200:
                html = resp.text.lower()
                features = {
                    "top_list": any(kw in html for kw in ["top 5", "top 10", "best", "ranking"]),
                    "comparison": any(kw in html for kw in ["vs", "comparison", "compare"]),
                    "guide": any(kw in html for kw in ["guide", "how to", "beginner", "tips"]),
                }
                active = [k for k, v in features.items() if v]
                if active:
                    insights.append("%s: uses %s" % (comp["name"], ", ".join(active)))
        except Exception:
            pass

    if insights:
        findings.append({
            "type": "info", "agent": "competitive-intelligence",
            "message": "Competitor blog formats: %d blogs analyzed" % len(insights),
            "details": insights,
        })

    return findings


# ============================================================
# 6. テンプレート推奨
# ============================================================

def get_recommended_template():
    """今日使うべきテンプレートを返す"""
    day = NOW.weekday()
    if day in (1, 3):
        return TOP5_TEMPLATE
    elif day == 5:
        return COMPARISON_TEMPLATE
    elif day == 0:
        return GUIDE_TEMPLATE
    else:
        return STANDARD_TEMPLATE


# ============================================================
# 7. proposal_history / experiments 連携
# ============================================================

def _sync_to_proposal_tracking(wp_posts):
    """ブログ関連の結果を proposal_tracking に反映"""
    tracking_path = os.path.join(SCRIPT_DIR, "proposal_tracking.json")
    if not os.path.exists(tracking_path):
        return

    try:
        with open(tracking_path, "r", encoding="utf-8") as f:
            tracking = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    wp_titles = set()
    for p in wp_posts:
        title = p.get("title", {})
        if isinstance(title, dict):
            title = title.get("rendered", "")
        wp_titles.add(str(title).lower())

    updated = False
    for proposal in tracking.get("proposals", []):
        if proposal.get("type") != "article_theme" or proposal.get("status") != "pending":
            continue
        msg = proposal.get("message", "").lower()
        # 提案されたテーマが実際に記事化されたかチェック
        for wp_title in wp_titles:
            keywords = [w for w in msg.split() if len(w) > 4][:3]
            if any(kw in wp_title for kw in keywords):
                proposal["status"] = "adopted"
                proposal["adopted_date"] = NOW.strftime("%Y-%m-%d")
                proposal["result"] = "success"
                proposal["result_date"] = NOW.strftime("%Y-%m-%d")
                updated = True
                break

    if updated:
        tracking["summary"]["adopted"] = sum(1 for p in tracking["proposals"] if p.get("status") == "adopted")
        tracking["summary"]["success"] = sum(1 for p in tracking["proposals"] if p.get("result") == "success")
        tracking["summary"]["last_updated"] = NOW.strftime("%Y-%m-%d")
        with open(tracking_path, "w", encoding="utf-8") as f:
            json.dump(tracking, f, indent=2, ensure_ascii=False)


# ============================================================
# メインエントリポイント
# ============================================================

def run_blog_automation(products, wp_posts, wp_categories):
    """ブログ自動化の全機能を実行して findings を返す"""
    all_findings = []

    # 1. 記事テーマ候補
    all_findings.extend(suggest_article_topics(products, wp_posts, wp_categories))

    # 2. 画像監査
    all_findings.extend(audit_article_images(wp_posts))

    # 3. カテゴリ別監査
    all_findings.extend(audit_categories(products, wp_posts))

    # 4. 記事品質監査 + 投稿後PDCA + タイプ別比較
    all_findings.extend(analyze_article_performance(wp_posts))

    # 5. 競合記事リサーチ
    all_findings.extend(research_competitor_articles())

    # 6. テンプレート推奨
    template = get_recommended_template()
    all_findings.append({
        "type": "info", "agent": "content-strategist",
        "message": "Today's article template: %s (%s)" % (template["name"], template["description"]),
    })

    # 7. proposal_tracking 連携
    _sync_to_proposal_tracking(wp_posts)

    return all_findings
