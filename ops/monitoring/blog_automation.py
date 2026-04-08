# ============================================================
# ブログ記事自動投稿 + PDCA改善モジュール
#
# 担当: content-strategist (主担当)
#       growth-foundation (分析)
#       competitive-intelligence (競合調査)
#
# 機能:
# 1. 記事テーマ候補の抽出
# 2. 標準テンプレート / テストテンプレートでの記事生成
# 3. WordPress への下書き投稿
# 4. 公開記事の分析と改善提案
# 5. 競合記事の定期リサーチ
# 6. 改善履歴の保存
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

BLOG_STATE_FILE = os.path.join(SCRIPT_DIR, "blog_state.json")

SHOPIFY_URL = "https://hd-toys-store-japan.myshopify.com"
EBAY_STORE = "https://www.ebay.com/str/hdtoysstore"

# 既存記事から抽出した標準テンプレート構造
STANDARD_TEMPLATE = {
    "name": "standard",
    "description": "既存記事に近い標準形式",
    "structure": [
        {"type": "intro", "desc": "導入文（商品の魅力を2-3段落で語る）"},
        {"type": "h2", "title": "Product Details"},
        {"type": "h3_list", "items": ["Product Name", "Category", "Key Features", "Rarity & Value"]},
        {"type": "h2", "title": "Background & Context"},
        {"type": "h3_list", "items": ["Series/Franchise Overview", "Why This Item Is Special"]},
        {"type": "h2", "title": "Related Items"},
        {"type": "h3_list", "items": ["Similar Products", "Collection Opportunities"]},
        {"type": "h2", "title": "Summary"},
        {"type": "cta", "buttons": ["shopify", "ebay"]},
    ],
    "guidelines": {
        "word_count": "1200-1800",
        "images": "3-5 (product photos + context images)",
        "tone": "Informative, collector-friendly, enthusiastic but not pushy",
        "cta_placement": "End of article, after Summary",
        "internal_links": "2-3 to related articles",
    },
}

# テストテンプレート A: Top 5 / ランキング形式
TEST_TEMPLATE_A = {
    "name": "top5_ranking",
    "description": "Top 5 ランキング形式（競合で人気の構成）",
    "structure": [
        {"type": "intro", "desc": "なぜこのカテゴリが人気なのかを簡潔に"},
        {"type": "h2", "title": "Top 5 [Category] from Japan"},
        {"type": "ranked_items", "count": 5, "each": [
            "Product image", "Product name", "Why it's special",
            "Price range", "Mini CTA (Shopify/eBay link)",
        ]},
        {"type": "h2", "title": "How to Choose"},
        {"type": "h3_list", "items": ["Condition Guide", "What to Look For", "Price Expectations"]},
        {"type": "h2", "title": "Where to Buy"},
        {"type": "cta", "buttons": ["shopify_collection", "ebay"]},
    ],
    "guidelines": {
        "word_count": "1500-2000",
        "images": "5-7 (one per ranked item + header)",
        "tone": "Guide-like, helpful, SEO-optimized headings",
        "cta_placement": "After each item (mini) + end (main)",
        "experiment_id": "EXP-BLOG-001",
    },
}

# テストテンプレート B: 比較 / vs 形式
TEST_TEMPLATE_B = {
    "name": "comparison",
    "description": "比較記事形式（2-3商品を比較）",
    "structure": [
        {"type": "intro", "desc": "比較の目的と対象を明示"},
        {"type": "h2", "title": "Quick Comparison Table"},
        {"type": "comparison_table", "columns": ["Feature", "Item A", "Item B"]},
        {"type": "h2", "title": "Detailed Review: [Item A]"},
        {"type": "h3_list", "items": ["Design", "Condition", "Value"]},
        {"type": "h2", "title": "Detailed Review: [Item B]"},
        {"type": "h3_list", "items": ["Design", "Condition", "Value"]},
        {"type": "h2", "title": "Which One Should You Get?"},
        {"type": "h2", "title": "Where to Buy"},
        {"type": "cta", "buttons": ["shopify", "ebay"]},
    ],
    "guidelines": {
        "word_count": "1200-1600",
        "images": "4-6 (both items + comparison shots)",
        "tone": "Objective, helpful comparison",
        "cta_placement": "End of article",
        "experiment_id": "EXP-BLOG-002",
    },
}


def _load_blog_state():
    if not os.path.exists(BLOG_STATE_FILE):
        return {"articles_generated": [], "experiments": [], "template_scores": {}, "_last_updated": ""}
    try:
        with open(BLOG_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"articles_generated": [], "experiments": [], "template_scores": {}, "_last_updated": ""}


def _save_blog_state(state):
    state["_last_updated"] = NOW.strftime("%Y-%m-%d")
    with open(BLOG_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ============================================================
# 1. 記事テーマ候補抽出
# ============================================================

def suggest_article_topics(products, wp_posts, wp_categories):
    """Shopify 商品 × WP 記事ギャップから記事テーマを提案"""
    findings = []

    if not products:
        return findings

    # WP 記事タイトル
    wp_titles = set()
    for p in wp_posts:
        title = p.get("title", {})
        if isinstance(title, dict):
            title = title.get("rendered", "")
        wp_titles.add(str(title).lower())

    # 未カバー商品
    uncovered = []
    for p in products:
        title_lower = p["title"].lower()
        # タイトルの主要単語が WP 記事に含まれるか
        words = [w for w in title_lower.split() if len(w) > 4]
        covered = any(w in " ".join(wp_titles) for w in words[:3])
        if not covered:
            uncovered.append({
                "title": p["title"],
                "handle": p["handle"],
                "type": p.get("product_type", ""),
                "images": len(p.get("images", [])),
            })

    if uncovered:
        # カテゴリ別にグループ化
        by_cat = {}
        for item in uncovered:
            cat = item["type"] or "Other"
            if cat not in by_cat:
                by_cat[cat] = []
            by_cat[cat].append(item)

        details = []
        for cat, items in sorted(by_cat.items(), key=lambda x: -len(x[1])):
            if len(items) >= 2:
                details.append(
                    "[%s] Top 5 article: %d uncovered products" % (cat, len(items))
                )
            for item in items[:1]:
                details.append(
                    "[%s] Single review: %s" % (cat, item["title"][:50])
                )

        findings.append({
            "type": "action", "agent": "blog-analyst",
            "message": "Blog topics: %d products need articles (%d categories)" % (len(uncovered), len(by_cat)),
            "details": details[:5],
        })

    return findings


# ============================================================
# 2. 記事 PDCA 改善判定
# ============================================================

def analyze_article_performance(wp_posts):
    """既存記事のパフォーマンスを分析して改善提案を生成"""
    findings = []

    if not wp_posts:
        return findings

    improvements = []

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
        has_ebay_link = "ebay.com" in content.lower()
        h2_count = len(re.findall(r'<h2', content))
        img_count = len(re.findall(r'<img', content))

        # 改善ルール
        if not has_shopify_cta:
            improvements.append("[CTA missing] %s -> Add Shopify CTA" % str(title)[:40])

        if word_count < 500:
            improvements.append("[Too short] %s (%d words) -> Expand content" % (str(title)[:40], word_count))

        if h2_count < 2:
            improvements.append("[Few headings] %s (%d H2) -> Add structure" % (str(title)[:40], h2_count))

        if img_count == 0:
            improvements.append("[No images] %s -> Add product images" % str(title)[:40])

    if improvements:
        findings.append({
            "type": "action", "agent": "blog-analyst",
            "message": "Blog PDCA: %d articles need improvement" % len(improvements),
            "details": improvements[:5],
        })

    return findings


# ============================================================
# 3. 競合記事リサーチ（軽量版）
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
                    "has_top_list": any(kw in html for kw in ["top 5", "top 10", "best", "ranking"]),
                    "has_comparison": any(kw in html for kw in ["vs", "comparison", "compare", "versus"]),
                    "has_guide": any(kw in html for kw in ["guide", "how to", "beginner", "tips"]),
                    "has_faq": "faq" in html or "frequently asked" in html,
                }

                active_formats = [k.replace("has_", "") for k, v in features.items() if v]
                if active_formats:
                    insights.append(
                        "%s: uses %s" % (comp["name"], ", ".join(active_formats))
                    )
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
# 4. テンプレート管理
# ============================================================

def get_recommended_template():
    """今日使うべきテンプレートを返す"""
    state = _load_blog_state()
    scores = state.get("template_scores", {})

    # デフォルトは標準テンプレート
    # 週の曜日で切り替え（月水金=標準、火木=テストA、土=テストB）
    day = NOW.weekday()
    if day in (1, 3):  # 火木
        return TEST_TEMPLATE_A
    elif day == 5:  # 土
        return TEST_TEMPLATE_B
    else:
        return STANDARD_TEMPLATE


# ============================================================
# 5. 公開記事の分析と改善提案
# ============================================================

def analyze_published_articles_deep(wp_posts):
    """公開記事を詳細分析し、具体的な改善提案を生成する"""
    findings = []
    state = _load_blog_state()

    # 自動生成した記事の分析（blog_state に記録されているもの）
    generated = state.get("articles_generated", [])
    if not generated:
        return findings

    analyzed_ids = set(a.get("wp_post_id") for a in state.get("analysis_history", []))
    improvements = []
    improvement_actions = []

    for article in generated:
        wp_id = article.get("wp_post_id", 0)
        if not wp_id:
            continue

        # 公開後7日以上経過した記事を分析対象にする
        from datetime import datetime as _dt
        try:
            pub_date = _dt.strptime(article.get("date", ""), "%Y-%m-%d").date()
            days_since = (NOW.date() - pub_date).days
        except (ValueError, TypeError):
            days_since = 0

        if days_since < 1:
            continue

        # WP から最新の記事データを取得
        matching = [p for p in wp_posts if p.get("id") == wp_id]
        if not matching:
            continue

        post = matching[0]
        title = post.get("title", {})
        if isinstance(title, dict):
            title = title.get("rendered", "")
        content = post.get("content", {})
        if isinstance(content, dict):
            content = content.get("rendered", "")

        # 構造分析
        word_count = len(re.sub(r'<[^>]+>', '', content).split())
        has_shopify = "hd-toys-store-japan" in content.lower()
        has_ebay = "ebay.com" in content.lower()
        h2_count = len(re.findall(r'<h2', content))
        h3_count = len(re.findall(r'<h3', content))
        img_count = len(re.findall(r'<img', content))
        internal_links = len(re.findall(r'hd-bodyscience\.com', content))

        # 改善ルール
        article_improvements = []

        if not has_shopify:
            article_improvements.append("Add Shopify CTA")
        if h2_count < 3:
            article_improvements.append("Add more H2 headings (current: %d)" % h2_count)
        if img_count < 3:
            article_improvements.append("Add more images (current: %d)" % img_count)
        if internal_links < 2:
            article_improvements.append("Add internal links to related articles")
        if word_count < 800:
            article_improvements.append("Expand content (current: %d words)" % word_count)
        if word_count > 3000:
            article_improvements.append("Consider trimming (current: %d words, may lose readers)" % word_count)

        if article_improvements:
            improvements.append({
                "wp_id": wp_id,
                "title": str(title)[:50],
                "days_since_publish": days_since,
                "issues": article_improvements,
            })

    if improvements:
        details = []
        for imp in improvements[:3]:
            details.append(
                "[%dd old] %s: %s" % (
                    imp["days_since_publish"],
                    imp["title"],
                    "; ".join(imp["issues"][:2]),
                )
            )
        findings.append({
            "type": "action", "agent": "blog-analyst",
            "message": "Blog improvement: %d published articles need optimization" % len(improvements),
            "details": details,
        })

        # 改善履歴を保存
        state.setdefault("analysis_history", []).append({
            "date": NOW.strftime("%Y-%m-%d"),
            "articles_analyzed": len(improvements),
            "issues_found": sum(len(i["issues"]) for i in improvements),
        })
        _save_blog_state(state)

    return findings


# ============================================================
# メインエントリポイント
# ============================================================

def run_blog_automation(products, wp_posts, wp_categories):
    """ブログ自動化の全機能を実行して findings を返す"""
    all_findings = []

    # 1. 記事テーマ候補
    all_findings.extend(suggest_article_topics(products, wp_posts, wp_categories))

    # 2. 既存記事の PDCA 分析（全記事）
    all_findings.extend(analyze_article_performance(wp_posts))

    # 3. 公開記事の詳細分析（自動生成記事）
    all_findings.extend(analyze_published_articles_deep(wp_posts))

    # 4. 競合記事リサーチ
    all_findings.extend(research_competitor_articles())

    # 5. 今日のテンプレート推奨
    template = get_recommended_template()
    all_findings.append({
        "type": "info", "agent": "content-strategist",
        "message": "Today's article template: %s (%s)" % (template["name"], template["description"]),
    })

    return all_findings
