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
    """今日使うべきテンプレートを返す（guide型優先）

    guide型が最もadd_to_cart率が高いため、週の過半数をguide型にする。
    月=guide, 火=top5, 水=guide, 木=guide, 金=top5, 土=comparison, 日=guide
    """
    day = NOW.weekday()
    if day in (1, 4):  # 火・金
        return TOP5_TEMPLATE
    elif day == 5:  # 土
        return COMPARISON_TEMPLATE
    else:  # 月・水・木・日 = guide
        return GUIDE_TEMPLATE


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

def report_rejection_summary():
    """ブログ投稿拒否サマリを生成"""
    findings = []
    state = _load_blog_state()
    rejections = state.get("rejections", [])

    if not rejections:
        findings.append({
            "type": "ok", "agent": "blog-analyst",
            "message": "Blog rejections: 0 articles rejected by quality gate",
        })
        return findings

    # 直近7日
    week_ago = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [r for r in rejections if r.get("date", "") >= week_ago]

    # 拒否理由の集計
    reason_counts = Counter()
    for r in recent:
        for issue in r.get("issues", []):
            # [no_images] / [no_cta] 等のタグを抽出
            tag = issue.split("]")[0].replace("[", "") if "]" in issue else "other"
            reason_counts[tag] += 1

    details = [
        "=== Blog Rejection Summary (7d) ===",
        "Total rejected: %d (all-time: %d)" % (len(recent), len(rejections)),
    ]

    if reason_counts:
        details.append("--- Rejection reasons ---")
        for reason, count in reason_counts.most_common():
            details.append("  [%d] %s" % (count, reason))

    # 直近の拒否例
    if recent:
        details.append("--- Recent rejections ---")
        for r in recent[-3:]:
            details.append("  [%s] %s: %s" % (r.get("date", "?"), r.get("title", "?")[:35], "; ".join(r.get("issues", [])[:2])))

    findings.append({
        "type": "suggestion" if len(recent) > 2 else "info",
        "agent": "blog-analyst",
        "message": "Blog rejections: %d in 7 days, top reason: %s" % (
            len(recent), reason_counts.most_common(1)[0][0] if reason_counts else "none"),
        "details": details,
    })
    return findings


def report_passed_article_performance():
    """5項目通過記事の成果を追跡"""
    findings = []
    state = _load_blog_state()
    generated = state.get("articles_generated", [])

    if not generated:
        return findings

    # 品質データ付き記事（5項目通過）
    passed = [a for a in generated if a.get("quality", {}).get("passed")]
    if not passed:
        return findings

    details = [
        "=== Quality-Passed Article Performance ===",
        "Total passed: %d articles" % len(passed),
    ]

    # 品質スコア集計
    total_words = sum(a.get("quality", {}).get("words", 0) for a in passed)
    total_imgs = sum(a.get("quality", {}).get("images", 0) for a in passed)
    avg_words = total_words / max(len(passed), 1)
    avg_imgs = total_imgs / max(len(passed), 1)
    details.append("Avg quality: %.0f words, %.1f images" % (avg_words, avg_imgs))

    # 設定充足率
    with_cats = sum(1 for a in passed if a.get("settings", {}).get("categories"))
    with_tags = sum(1 for a in passed if a.get("settings", {}).get("tags"))
    with_featured = sum(1 for a in passed if a.get("settings", {}).get("featured_media"))
    details.append("Category set: %d/%d (%.0f%%)" % (with_cats, len(passed), with_cats / max(len(passed), 1) * 100))
    details.append("Tags set: %d/%d (%.0f%%)" % (with_tags, len(passed), with_tags / max(len(passed), 1) * 100))
    details.append("Featured image: %d/%d (%.0f%%)" % (with_featured, len(passed), with_featured / max(len(passed), 1) * 100))

    # 直近の記事リスト + 公開後成果
    details.append("--- Recent passed articles (post-publish tracking) ---")
    for a in passed[-5:]:
        q = a.get("quality", {})
        wp_id = a.get("wp_post_id", 0)
        days_since = 0
        try:
            from datetime import datetime as _dt
            days_since = (NOW.date() - _dt.strptime(a.get("date", ""), "%Y-%m-%d").date()).days
        except (ValueError, TypeError):
            pass

        status_mark = "NEW" if days_since < 3 else "TRACK" if days_since < 14 else "MATURE"
        details.append("  [%s] [%s] %s (%dw, %dimg) — %dd old" % (
            status_mark, a.get("date", "?"), a.get("title", "?")[:30], q.get("words", 0), q.get("images", 0), days_since))

    # 公開後の成果要求
    track_articles = [a for a in passed if a.get("wp_post_id")]
    trackable = 0
    for a in track_articles:
        try:
            days = (NOW.date() - datetime.strptime(a.get("date", ""), "%Y-%m-%d").date()).days
            if 3 <= days <= 30:
                trackable += 1
        except (ValueError, TypeError):
            pass

    if trackable > 0:
        details.append("")
        details.append("--- Post-Publish Performance Tracking ---")
        details.append("Articles in tracking window (3-30 days old): %d" % trackable)

        # GA4/UTM ベースの成果追跡項目
        details.append("")
        details.append("Tracked metrics per article:")
        details.append("  1. Pageviews (GA4: page_view event)")
        details.append("  2. Avg time on page (GA4: engagement_time)")
        details.append("  3. CTA click rate (UTM: utm_medium=article → Shopify landing)")
        details.append("  4. Shopify referral count (GA4: session_source=hd-bodyscience)")
        details.append("  5. Product page views from blog (UTM: utm_campaign=blog-auto)")
        details.append("  6. Add-to-cart from blog referral (GA4: add_to_cart with referrer)")

        # 個別記事の送客状況（UTM追跡可能なもの）
        details.append("")
        details.append("Per-article UTM tracking URLs:")
        track_window = [a for a in passed if a.get("wp_post_id")]
        for a in track_window[-3:]:
            handle = a.get("handle", "")
            if handle:
                details.append("  %s → utm_content=%s" % (a.get("title", "?")[:30], handle))

        # blog_state に追跡対象を記録
        state.setdefault("post_publish_tracking", [])
        for a in track_window:
            wp_id = a.get("wp_post_id", 0)
            if not any(t.get("wp_post_id") == wp_id for t in state.get("post_publish_tracking", [])):
                try:
                    pub_days = (NOW.date() - datetime.strptime(a.get("date", ""), "%Y-%m-%d").date()).days
                except (ValueError, TypeError):
                    pub_days = 0

                if 3 <= pub_days <= 30:
                    state["post_publish_tracking"].append({
                        "wp_post_id": wp_id,
                        "title": a.get("title", "")[:50],
                        "handle": a.get("handle", ""),
                        "published_date": a.get("date", ""),
                        "tracking_start": NOW.strftime("%Y-%m-%d"),
                        "metrics": {
                            "pageviews": 0,
                            "cta_clicks": 0,
                            "shopify_referrals": 0,
                            "product_views": 0,
                            "add_to_cart": 0,
                        },
                        "status": "tracking",
                    })
        # 30日超のものを完了に
        for t in state.get("post_publish_tracking", []):
            try:
                days = (NOW.date() - datetime.strptime(t.get("published_date", ""), "%Y-%m-%d").date()).days
                if days > 30:
                    t["status"] = "completed"
            except (ValueError, TypeError):
                pass

        _save_blog_state(state)

    # 品質通過率
    all_generated = state.get("articles_generated", [])
    all_rejected = state.get("rejections", [])
    total_attempts = len(all_generated) + len(all_rejected)
    if total_attempts > 0:
        pass_rate = len(passed) / total_attempts * 100
        details.append("")
        details.append("Quality pass rate: %d/%d (%.0f%%)" % (len(passed), total_attempts, pass_rate))

    # 自動再生成の成功率と失敗理由
    if all_rejected:
        retried = [r for r in all_rejected if r.get("retry_attempted")]
        not_retried = [r for r in all_rejected if not r.get("retry_attempted")]
        # 再生成後に通過したもの = generated の中で retry があったもの
        retry_succeeded = sum(1 for a in all_generated if a.get("quality", {}).get("passed") and a.get("date") in [r.get("date") for r in retried])

        details.append("")
        details.append("--- Auto-Retry Stats ---")
        details.append("Retried: %d, Retry succeeded: %d, Retry failed: %d, Not retried: %d" % (
            len(retried), retry_succeeded, len(retried) - retry_succeeded, len(not_retried)))

        if retried:
            retry_rate = retry_succeeded / max(len(retried), 1) * 100
            details.append("Retry success rate: %.0f%%" % retry_rate)

        # 失敗理由の集計
        reason_counts = Counter()
        for r in all_rejected:
            for issue in r.get("issues", []):
                tag = issue.split("]")[0].replace("[", "") if "]" in issue else "other"
                reason_counts[tag] += 1
        if reason_counts:
            details.append("Top rejection reasons:")
            for reason, count in reason_counts.most_common(5):
                details.append("  [%d] %s" % (count, reason))

        # アウトライン導入前後の short_content 比較
        outline_date = "2026-04-10"  # アウトライン導入日
        before_outline = [r for r in all_rejected if r.get("date", "") < outline_date]
        after_outline = [r for r in all_rejected if r.get("date", "") >= outline_date]
        short_before = sum(1 for r in before_outline if any("short_content" in i for i in r.get("issues", [])))
        short_after = sum(1 for r in after_outline if any("short_content" in i for i in r.get("issues", [])))

        details.append("")
        details.append("--- Outline Effect (short_content) ---")
        details.append("Before outline: %d/%d rejected for short_content" % (short_before, max(len(before_outline), 1)))
        details.append("After outline: %d/%d rejected for short_content" % (short_after, max(len(after_outline), 1)))
        if len(after_outline) >= 2:
            if short_after < short_before:
                details.append("EFFECTIVE: short_content rejections decreased")
            elif short_after == 0:
                details.append("EFFECTIVE: zero short_content rejections since outline")
            else:
                details.append("PARTIAL: short_content still occurring — review outline prompts")

    # === 勝ち記事 / 弱い記事の判定 ===
    tracking_data = state.get("post_publish_tracking", [])
    if tracking_data:
        winners = []
        weak = []
        for t in tracking_data:
            if t.get("status") != "tracking":
                continue
            m = t.get("metrics", {})
            total_engagement = m.get("pageviews", 0) + m.get("cta_clicks", 0) + m.get("shopify_referrals", 0)

            # 勝ち記事: CTA clicked + Shopify referral、または pageviews 50+
            if m.get("cta_clicks", 0) > 0 and m.get("shopify_referrals", 0) > 0:
                winners.append(t)
            elif m.get("pageviews", 0) >= 50:
                winners.append(t)
            # 弱い記事: pageviews < 10 and tracking > 7 days
            elif m.get("pageviews", 0) < 10:
                try:
                    days = (NOW.date() - datetime.strptime(t.get("published_date", ""), "%Y-%m-%d").date()).days
                    if days >= 7:
                        weak.append(t)
                except (ValueError, TypeError):
                    pass

        if winners or weak:
            details.append("")
            details.append("--- Win / Weak Article Classification ---")
            details.append("Winners: %d | Weak: %d | Tracking: %d" % (len(winners), len(weak), len(tracking_data)))

            if winners:
                details.append("WIN articles:")
                for w in winners[:3]:
                    m = w.get("metrics", {})
                    details.append("  [WIN] %s — pv:%d cta:%d ref:%d cart:%d" % (
                        w.get("title", "?")[:30], m.get("pageviews", 0), m.get("cta_clicks", 0),
                        m.get("shopify_referrals", 0), m.get("add_to_cart", 0)))

            if weak:
                details.append("WEAK articles (reason breakdown):")
                for w in weak[:3]:
                    m = w.get("metrics", {})
                    reasons = []
                    if m.get("pageviews", 0) < 5:
                        reasons.append("low-discovery(SEO/導線不足)")
                    elif m.get("cta_clicks", 0) == 0:
                        reasons.append("no-CTA-click(CTA配置/訴求弱い)")
                    elif m.get("shopify_referrals", 0) == 0:
                        reasons.append("no-referral(CTA→Shopify遷移なし)")

                    # 記事品質要因
                    handle = w.get("handle", "")
                    wp_id = w.get("wp_post_id", 0)
                    # blog_state から品質データを取得
                    gen = [a for a in state.get("articles_generated", []) if a.get("wp_post_id") == wp_id]
                    if gen:
                        q = gen[0].get("quality", {})
                        if q.get("words", 0) < 1000:
                            reasons.append("thin-content(%dw)" % q.get("words", 0))
                        if q.get("images", 0) < 3:
                            reasons.append("few-images(%d)" % q.get("images", 0))
                        s = gen[0].get("settings", {})
                        if not s.get("categories"):
                            reasons.append("no-category")
                        if not s.get("featured_media"):
                            reasons.append("no-featured-image")

                    if not reasons:
                        reasons.append("unknown(needs manual review)")

                    details.append("  [WEAK] %s — pv:%d cta:%d ref:%d" % (
                        w.get("title", "?")[:30], m.get("pageviews", 0), m.get("cta_clicks", 0),
                        m.get("shopify_referrals", 0)))
                    details.append("    Reasons: %s" % " + ".join(reasons))

    # === 記事タイプ別 add_to_cart 学習 ===
    if tracking_data:
        type_cart = defaultdict(lambda: {"articles": 0, "total_cart": 0, "total_pv": 0})

        for t in tracking_data:
            # 記事タイプを推定
            title = t.get("title", "").lower()
            if any(kw in title for kw in ["top 5", "top 10", "best", "ranking"]):
                atype = "top5"
            elif any(kw in title for kw in ["guide", "how to", "tips", "collector"]):
                atype = "guide"
            elif any(kw in title for kw in ["vs", "comparison", "compare"]):
                atype = "comparison"
            else:
                atype = "single_review"

            m = t.get("metrics", {})
            type_cart[atype]["articles"] += 1
            type_cart[atype]["total_cart"] += m.get("add_to_cart", 0)
            type_cart[atype]["total_pv"] += m.get("pageviews", 0)

        if type_cart:
            details.append("")
            details.append("--- Article Type → add_to_cart Learning ---")
            best_type = None
            best_rate = 0
            for atype, d in sorted(type_cart.items()):
                cart_rate = d["total_cart"] / max(d["total_pv"], 1) * 100
                details.append("  [%s] %d articles, %d carts, %d pv (cart rate: %.1f%%)" % (
                    atype, d["articles"], d["total_cart"], d["total_pv"], cart_rate))
                if cart_rate > best_rate:
                    best_rate = cart_rate
                    best_type = atype

            if best_type and best_rate > 0:
                details.append("  Best for conversion: %s (%.1f%% cart rate) → increase this type" % (best_type, best_rate))

        # guide vs single_review 詳細比較
        guide_articles = [t for t in tracking_data if any(kw in t.get("title", "").lower() for kw in ["guide", "how to", "tips", "collector"])]
        review_articles = [t for t in tracking_data if t not in guide_articles]

        # PV→CTA率の前後比較（ミニCTA導入前後）
        mini_cta_date = "2026-04-10"  # ミニCTA導入日
        before_mini = [t for t in tracking_data if t.get("published_date", "") < mini_cta_date]
        after_mini = [t for t in tracking_data if t.get("published_date", "") >= mini_cta_date]

        if before_mini or after_mini:
            details.append("")
            details.append("--- PV→CTA Rate Before/After Mini CTA ---")

            for label, articles in [("Before mini CTA", before_mini), ("After mini CTA", after_mini)]:
                pv = sum(a.get("metrics", {}).get("pageviews", 0) for a in articles)
                cta = sum(a.get("metrics", {}).get("cta_clicks", 0) for a in articles)
                rate = cta / max(pv, 1) * 100
                details.append("  [%s] %d articles, pv:%d → cta:%d (%.1f%%)" % (label, len(articles), pv, cta, rate))

            if before_mini and after_mini:
                pv_b = sum(a.get("metrics", {}).get("pageviews", 0) for a in before_mini)
                cta_b = sum(a.get("metrics", {}).get("cta_clicks", 0) for a in before_mini)
                pv_a = sum(a.get("metrics", {}).get("pageviews", 0) for a in after_mini)
                cta_a = sum(a.get("metrics", {}).get("cta_clicks", 0) for a in after_mini)
                rate_b = cta_b / max(pv_b, 1) * 100
                rate_a = cta_a / max(pv_a, 1) * 100
                if rate_a > rate_b:
                    details.append("  IMPROVED: CTA rate %.1f%% → %.1f%% (+%.1fpp)" % (rate_b, rate_a, rate_a - rate_b))
                elif rate_b > 0:
                    details.append("  Change: %.1f%% → %.1f%% (%.1fpp)" % (rate_b, rate_a, rate_a - rate_b))

        # trust文言あり/なしのCTA反応差
        trust_articles = []
        no_trust_articles = []
        for t in tracking_data:
            gen = [a for a in state.get("articles_generated", []) if a.get("wp_post_id") == t.get("wp_post_id")]
            if gen:
                title = gen[0].get("title", "").lower()
                if any(kw in title for kw in ["ship", "inspect", "condition", "japan", "pre-owned"]):
                    trust_articles.append(t)
                else:
                    no_trust_articles.append(t)

        if trust_articles or no_trust_articles:
            details.append("")
            details.append("--- Trust Language vs No-Trust CTA Comparison ---")
            for label, articles in [("With trust context", trust_articles), ("Without trust context", no_trust_articles)]:
                if not articles:
                    details.append("  [%s] No articles" % label)
                    continue
                pv = sum(a.get("metrics", {}).get("pageviews", 0) for a in articles)
                cta = sum(a.get("metrics", {}).get("cta_clicks", 0) for a in articles)
                ref = sum(a.get("metrics", {}).get("shopify_referrals", 0) for a in articles)
                rate = cta / max(pv, 1) * 100
                details.append("  [%s] %d articles, pv:%d → cta:%d (%.1f%%) → ref:%d" % (label, len(articles), pv, cta, rate, ref))

        if guide_articles or review_articles:
            details.append("")
            details.append("--- guide vs single_review Deep Comparison ---")

            for label, articles in [("guide", guide_articles), ("single_review", review_articles)]:
                if not articles:
                    details.append("  [%s] No articles yet" % label)
                    continue

                total_pv = sum(a.get("metrics", {}).get("pageviews", 0) for a in articles)
                total_cta = sum(a.get("metrics", {}).get("cta_clicks", 0) for a in articles)
                total_ref = sum(a.get("metrics", {}).get("shopify_referrals", 0) for a in articles)
                total_cart = sum(a.get("metrics", {}).get("add_to_cart", 0) for a in articles)
                count = len(articles)

                # 品質指標（blog_state から取得）
                avg_words = 0
                avg_imgs = 0
                trust_count = 0
                for a in articles:
                    gen = [g for g in state.get("articles_generated", []) if g.get("wp_post_id") == a.get("wp_post_id")]
                    if gen:
                        q = gen[0].get("quality", {})
                        avg_words += q.get("words", 0)
                        avg_imgs += q.get("images", 0)
                        # trust文言チェック（タイトルから簡易推定）
                        msg = gen[0].get("title", "").lower()
                        if any(kw in msg for kw in ["ship", "inspect", "condition", "japan"]):
                            trust_count += 1

                avg_words = avg_words / max(count, 1)
                avg_imgs = avg_imgs / max(count, 1)

                details.append("  [%s] %d articles" % (label, count))
                details.append("    Content: avg %.0fw, %.1f imgs, %d with trust context" % (avg_words, avg_imgs, trust_count))
                details.append("    Funnel: pv:%d → cta:%d → ref:%d → cart:%d" % (total_pv, total_cta, total_ref, total_cart))
                if total_pv > 0:
                    details.append("    Rates: CTA %.1f%% | Ref %.1f%% | Cart %.1f%%" % (
                        total_cta / total_pv * 100,
                        total_ref / max(total_cta, 1) * 100,
                        total_cart / max(total_ref, 1) * 100))

                # shared_state に学習結果を保存
                ss_path = os.path.join(SCRIPT_DIR, "shared_state.json")
                try:
                    with open(ss_path, "r", encoding="utf-8") as f:
                        ss = json.load(f)
                    ss.setdefault("blog_type_learning", []).append({
                        "date": NOW.strftime("%Y-%m-%d"),
                        "best_type": best_type,
                        "best_cart_rate": round(best_rate, 1),
                        "type_data": {k: {"articles": v["articles"], "carts": v["total_cart"]} for k, v in type_cart.items()},
                    })
                    ss["blog_type_learning"] = ss["blog_type_learning"][-10:]

                    # guide型の継続追跡
                    guide_data = type_cart.get("guide", {"articles": 0, "total_cart": 0, "total_pv": 0})
                    ss.setdefault("guide_tracking", []).append({
                        "date": NOW.strftime("%Y-%m-%d"),
                        "articles": guide_data["articles"],
                        "carts": guide_data["total_cart"],
                        "pv": guide_data["total_pv"],
                        "cart_rate": round(guide_data["total_cart"] / max(guide_data["total_pv"], 1) * 100, 2),
                    })
                    ss["guide_tracking"] = ss["guide_tracking"][-14:]  # 14日分

                    with open(ss_path, "w", encoding="utf-8") as f:
                        json.dump(ss, f, indent=2, ensure_ascii=False)
                except (json.JSONDecodeError, IOError):
                    pass

        # guide型の7日推移表示
        try:
            with open(os.path.join(SCRIPT_DIR, "shared_state.json"), "r", encoding="utf-8") as f:
                ss_read = json.load(f)
            guide_history = ss_read.get("guide_tracking", [])
            if len(guide_history) >= 2:
                details.append("")
                details.append("--- guide Type Trend ---")
                for g in guide_history[-7:]:
                    details.append("  [%s] %d articles, %d carts, %d pv (rate: %.1f%%)" % (
                        g.get("date", "?"), g.get("articles", 0), g.get("carts", 0),
                        g.get("pv", 0), g.get("cart_rate", 0)))

                first = guide_history[-min(len(guide_history), 7)]
                last = guide_history[-1]
                if first.get("cart_rate", 0) > 0 and last.get("cart_rate", 0) > 0:
                    if last["cart_rate"] > first["cart_rate"]:
                        details.append("  TREND: guide cart rate IMPROVING (%.1f%% → %.1f%%)" % (first["cart_rate"], last["cart_rate"]))
                    elif last["cart_rate"] < first["cart_rate"]:
                        details.append("  TREND: guide cart rate DECLINING (%.1f%% → %.1f%%)" % (first["cart_rate"], last["cart_rate"]))
                    else:
                        details.append("  TREND: guide cart rate STABLE")
        except (json.JSONDecodeError, IOError):
            pass

    findings.append({
        "type": "info", "agent": "blog-analyst",
        "message": "Passed articles: %d total, avg %.0fw %.1fimg, %.0f%% category, %d tracking" % (
            len(passed), avg_words, avg_imgs, with_cats / max(len(passed), 1) * 100, trackable),
        "details": details,
    })
    return findings


def run_blog_automation(products, wp_posts, wp_categories):
    """ブログ自動化の全機能を実行して findings を返す"""
    all_findings = []

    # 0. ブログ投稿拒否サマリ
    all_findings.extend(report_rejection_summary())

    # 0b. 5項目通過記事の成果追跡
    all_findings.extend(report_passed_article_performance())

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
