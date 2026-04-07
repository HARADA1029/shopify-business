# ============================================================
# 日次アクション提案モジュール
#
# 売上改善のための具体的な提案を毎日生成する。
# - 記事テーマ / SNS投稿 / 内部リンク
# - Shopify追加候補 / 記事化候補 / 重点カテゴリ
# - eBay→Shopify展開 / 既存記事派生 / 競合参考
#
# 安全ルール: 読み取り専用。提案のみ。変更は行わない。
# ============================================================

import json
import os
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))


# ============================================================
# eBay 在庫データの読み込み
# ============================================================

def _load_ebay_enriched():
    """candidates_200_enriched.csv を読み込む（品質データ付き）"""
    path = os.path.join(PROJECT_ROOT, "product-migration", "data", "candidates_200_enriched.csv")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _load_ebay_target():
    """active_listings_target.csv を読み込む（全 eBay 在庫）"""
    path = os.path.join(PROJECT_ROOT, "product-migration", "data", "active_listings_target.csv")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _get_shopify_item_ids(products):
    """Shopify 商品から eBay item_id のセットを取得"""
    ids = set()
    for p in products:
        for v in p.get("variants", []):
            sku = v.get("sku", "")
            if sku.startswith("EB-"):
                ids.add(sku[3:])
    return ids


# カテゴリキーワードマッピング
CATEGORY_KEYWORDS = {
    "Scale Figures": ["figure", "nendoroid", "banpresto", "ichiban kuji", "scale", "pvc", "statue"],
    "Action Figures": ["figma", "figuarts", "action figure", "mafex", "revoltech", "sentai", "power rangers", "beyblade", "gundam"],
    "Trading Cards": ["card", "pokemon card", "tcg", "trading card", "yu-gi-oh", "promo", "holo"],
    "Video Games": ["game", "playstation", "nintendo", "console", "gameboy", "ps3", "psp", "famicom", "switch"],
    "Electronic Toys": ["tamagotchi", "digital pet", "digivice", "pedometer"],
    "Media & Books": ["manga", "art book", "blu-ray", "dvd", "comic", "complete set", "soundtrack", "album"],
    "Plush & Soft Toys": ["plush", "stuffed", "mascot", "doll", "cushion"],
    "Goods & Accessories": ["poster", "cosplay", "bag", "wallet", "keychain", "badge"],
}


# ============================================================
# 1. 記事テーマ提案
# ============================================================

def suggest_article_themes(products, wp_posts, wp_categories):
    """Shopify 在庫 x WP 記事カバレッジのギャップから記事テーマを提案"""
    findings = []
    if not products or not wp_categories:
        return findings

    collection_to_wp = {
        "Action Figures": ["figure", "bandai", "freeing", "good-smile", "medicom"],
        "Scale Figures": ["figure", "nendoroid", "banpresto", "ichiban-kuji"],
        "Trading Cards": ["trading-card", "tcg-trading-card-game-collectable-card", "pokemon"],
        "Video Games": ["video-game", "playstation-3-ps3-sony", "xbox360-microsoft", "psp-playstation-portable-vita"],
        "Electronic Toys": ["tamagotchi"],
        "Media & Books": ["book-magazine", "comic", "art-book-illustration", "dvd-blu-ray-ld", "game-anime-sound-track-ost"],
        "Plush & Soft Toys": ["stuffed-toy-plush-doll-mascot", "sanrio"],
        "Goods & Accessories": ["collectibles", "poster"],
    }

    wp_cat_counts = {c.get("slug", ""): c.get("count", 0) for c in wp_categories}
    shopify_cat_counts = Counter(p.get("product_type", "") for p in products)

    gaps = []
    for collection, wp_slugs in collection_to_wp.items():
        shopify_count = shopify_cat_counts.get(collection, 0)
        if shopify_count == 0:
            continue
        wp_count = sum(wp_cat_counts.get(slug, 0) for slug in wp_slugs)
        if shopify_count > wp_count:
            gaps.append({
                "collection": collection,
                "shopify_products": shopify_count,
                "wp_articles": wp_count,
                "gap": shopify_count - wp_count,
            })

    gaps.sort(key=lambda x: -x["gap"])

    if gaps:
        details = []
        theme_ideas = {
            "Action Figures": "Top %d Action Figures from Japan Every Collector Needs",
            "Scale Figures": "Japanese Scale Figures: Nendoroid, Banpresto & More",
            "Trading Cards": "Rare Japanese Trading Cards: Pokemon, Yu-Gi-Oh! & Hidden Gems",
            "Video Games": "Retro Japanese Games Worth Collecting in 2026",
            "Electronic Toys": "Rare Tamagotchi Models Every Collector Should Know",
            "Media & Books": "Japanese Art Books & Manga Sets: A Collector's Guide",
            "Plush & Soft Toys": "Cutest Japanese Plush Toys: Pokemon, Sanrio & Anime",
            "Goods & Accessories": "Unique Japanese Anime Goods & Cosplay Items",
        }
        for g in gaps[:2]:
            sample = [p["title"][:45] for p in products if p.get("product_type") == g["collection"]][:3]
            theme = theme_ideas.get(g["collection"], "Guide to %s from Japan" % g["collection"])
            if "%d" in theme:
                theme = theme % min(5, g["shopify_products"])
            details.append('Theme: "%s"' % theme)
            details.append("  Reason: Shopify has %d products but only %d articles" % (g["shopify_products"], g["wp_articles"]))
            details.append("  Products: %s" % ", ".join(sample))

        findings.append({
            "type": "action", "agent": "content-strategist",
            "message": "Article ideas: %d categories with more products than articles" % len(gaps),
            "details": details,
        })

    return findings


# ============================================================
# 2. SNS 投稿案
# ============================================================

def suggest_sns_posts(products, wp_posts):
    """曜日ローテーション x 未投稿商品で SNS 投稿案を提案"""
    findings = []
    if not products:
        return findings

    day_of_week = NOW.weekday()
    rotation = [
        "Action Figures", "Trading Cards", "Scale Figures",
        "Electronic Toys", "Video Games", "Media & Books", "Plush & Soft Toys",
    ]
    today_category = rotation[day_of_week % len(rotation)]

    posted_file = os.path.join(SCRIPT_DIR, "sns_posted.json")
    posted_handles = set()
    if os.path.exists(posted_file):
        try:
            with open(posted_file, "r", encoding="utf-8") as f:
                posted_handles = set(json.load(f).get("posted", []))
        except (json.JSONDecodeError, IOError):
            pass

    candidates = [
        p for p in products
        if p.get("product_type") == today_category
        and p.get("handle", "") not in posted_handles
    ]
    if not candidates:
        for cat in rotation:
            if cat == today_category:
                continue
            candidates = [
                p for p in products
                if p.get("product_type") == cat and p.get("handle", "") not in posted_handles
            ]
            if candidates:
                today_category = cat
                break

    if candidates:
        product = candidates[0]
        handle = product.get("handle", "")
        title = product["title"][:60]
        images = product.get("images", [])
        image_url = images[0].get("src", "") if images else ""
        shopify_link = "https://hd-toys-store-japan.myshopify.com/products/%s" % handle

        board_map = {
            "Action Figures": "Action Figures", "Scale Figures": "Figures & Statues",
            "Trading Cards": "Trading Cards", "Video Games": "Video Games",
            "Electronic Toys": "Electronic Toys", "Media & Books": "Media & Books",
            "Plush & Soft Toys": "Plush & Soft Toys", "Goods & Accessories": "Goods & Accessories",
        }

        details = [
            "Category: %s (today's rotation)" % today_category,
            "Product: %s" % title,
            "Pinterest: Pin to '%s' board" % board_map.get(today_category, today_category),
            "Instagram: Product showcase image",
            "Link: %s?utm_source=pinterest&utm_medium=social&utm_campaign=daily-pin&utm_content=%s" % (shopify_link, handle),
        ]
        if image_url:
            details.append("Image: %s" % image_url[:80])

        findings.append({
            "type": "action", "agent": "sns-manager",
            "message": "SNS post idea: %s" % title,
            "details": details,
        })

    return findings


# ============================================================
# 3. 内部リンク追加案
# ============================================================

def suggest_internal_links(wp_posts, wp_categories):
    """同カテゴリで相互リンクがない記事ペアを抽出"""
    findings = []
    if not wp_posts or len(wp_posts) < 2:
        return findings

    cat_posts = defaultdict(list)
    for p in wp_posts:
        for cat_id in p.get("categories", []):
            cat_posts[cat_id].append(p)

    suggestions = []
    checked = set()
    for cat_id, posts in cat_posts.items():
        if len(posts) < 2:
            continue
        for i, p1 in enumerate(posts):
            for p2 in posts[i+1:]:
                pair_key = tuple(sorted([p1["id"], p2["id"]]))
                if pair_key in checked:
                    continue
                checked.add(pair_key)

                p1_content = (p1.get("content", {}).get("rendered", "") or "").lower()
                p2_content = (p2.get("content", {}).get("rendered", "") or "").lower()
                p1_link = p1.get("link", "")
                p2_link = p2.get("link", "")

                p1_has_p2 = p2_link.lower().rstrip("/") in p1_content if p2_link else True
                p2_has_p1 = p1_link.lower().rstrip("/") in p2_content if p1_link else True

                if not p1_has_p2 or not p2_has_p1:
                    cat_name = ""
                    for c in wp_categories:
                        if c.get("id") == cat_id:
                            cat_name = c.get("name", "")
                            break
                    t1 = p1["title"]["rendered"][:40] if isinstance(p1["title"], dict) else str(p1["title"])[:40]
                    t2 = p2["title"]["rendered"][:40] if isinstance(p2["title"], dict) else str(p2["title"])[:40]
                    suggestions.append('"%s" <-> "%s" [%s]' % (t1, t2, cat_name))

    if suggestions:
        findings.append({
            "type": "action", "agent": "content-strategist",
            "message": "Internal link opportunities: %d article pairs without cross-links" % len(suggestions),
            "details": suggestions[:3],
        })

    return findings


# ============================================================
# 4. Shopify 追加候補（eBay → Shopify 展開）
# ============================================================

def suggest_shopify_candidates(products):
    """eBay 在庫から Shopify 展開すべき商品をスコアリングして提案"""
    findings = []

    ebay_rows = _load_ebay_enriched()
    if not ebay_rows or not products:
        return findings

    shopify_item_ids = _get_shopify_item_ids(products)

    shopify_prices = []
    for p in products:
        for v in p.get("variants", []):
            try:
                shopify_prices.append(float(v.get("price", "0") or "0"))
            except ValueError:
                pass
    avg_price = sum(shopify_prices) / max(len(shopify_prices), 1)

    top_cats = [cat for cat, _ in Counter(p.get("product_type", "") for p in products).most_common(5) if cat]

    scored = []
    for row in ebay_rows:
        item_id = row.get("item_id", "")
        if item_id in shopify_item_ids:
            continue
        title_lower = row.get("title", "").lower()
        try:
            price = float(row.get("price", "0") or "0")
            watchers = int(row.get("watchers", "0") or "0")
            image_count = int(row.get("image_count", "0") or "0")
        except ValueError:
            continue

        matched_cat = ""
        for cat, keywords in CATEGORY_KEYWORDS.items():
            if cat not in top_cats:
                continue
            if any(kw in title_lower for kw in keywords):
                matched_cat = cat
                break
        if not matched_cat:
            continue

        score = watchers * 3 + image_count * 5
        if 50 <= price <= avg_price * 1.5:
            score += 20
        if row.get("brand"):
            score += 10

        scored.append({
            "title": row.get("title", "")[:55],
            "category": matched_cat,
            "price": price,
            "watchers": watchers,
            "images": image_count,
            "brand": row.get("brand", "")[:20],
            "score": score,
        })

    scored.sort(key=lambda x: -x["score"])

    if scored:
        details = []
        for item in scored[:3]:
            line = "[%s] %s ($%.0f, %d watchers" % (item["category"], item["title"], item["price"], item["watchers"])
            if item["brand"]:
                line += ", %s" % item["brand"]
            line += ", %d images)" % item["images"]
            details.append(line)

        findings.append({
            "type": "action", "agent": "catalog-migration-planner",
            "message": "Shopify expansion: Top %d from %d matching eBay items (by watchers & quality)" % (min(3, len(scored)), len(scored)),
            "details": details,
        })

    return findings


# ============================================================
# 5. eBay → Shopify カテゴリ別展開候補
# ============================================================

def suggest_ebay_to_shopify(products, wp_posts):
    """よく見られている記事テーマに一致する eBay 在庫で Shopify 未連携のものを提案"""
    findings = []

    ebay_rows = _load_ebay_target()
    if not ebay_rows or not products:
        return findings

    shopify_item_ids = _get_shopify_item_ids(products)

    # WP 記事タイトルからキーワードを抽出
    article_keywords = set()
    if wp_posts:
        for p in wp_posts:
            title = p.get("title", {})
            if isinstance(title, dict):
                title = title.get("rendered", "")
            for word in str(title).lower().split():
                if len(word) > 4:
                    article_keywords.add(word)

    # Shopify のカテゴリ別商品数
    cat_counts = Counter(p.get("product_type", "") for p in products)

    # Shopify で商品が少ないカテゴリを特定
    weak_categories = [cat for cat, cnt in cat_counts.items() if cnt <= 3 and cat]

    if not weak_categories:
        return findings

    # 弱いカテゴリに対応する eBay 商品を探す
    candidates_by_cat = {}
    for row in ebay_rows:
        item_id = row.get("item_id", "")
        if item_id in shopify_item_ids:
            continue
        title = row.get("title", "")
        title_lower = title.lower()

        try:
            watchers = int(row.get("watchers", "0") or "0")
        except ValueError:
            watchers = 0

        for cat in weak_categories:
            keywords = CATEGORY_KEYWORDS.get(cat, [])
            if any(kw in title_lower for kw in keywords):
                # 記事キーワードとの一致度もチェック
                title_words = set(title_lower.split())
                article_match = len(title_words & article_keywords)

                if cat not in candidates_by_cat:
                    candidates_by_cat[cat] = []
                candidates_by_cat[cat].append({
                    "title": title[:55],
                    "watchers": watchers,
                    "article_relevance": article_match,
                    "score": watchers * 2 + article_match * 10,
                })
                break

    if candidates_by_cat:
        details = []
        for cat in weak_categories:
            if cat not in candidates_by_cat:
                continue
            items = sorted(candidates_by_cat[cat], key=lambda x: -x["score"])[:1]
            for item in items:
                details.append(
                    "[%s] %s (%d watchers, article match: %d)" % (cat, item["title"], item["watchers"], item["article_relevance"])
                )
            if len(details) >= 3:
                break

        if details:
            total = sum(len(v) for v in candidates_by_cat.values())
            findings.append({
                "type": "action", "agent": "catalog-migration-planner",
                "message": "eBay->Shopify: %d items in weak categories (%s) could strengthen Shopify lineup" % (
                    total, ", ".join(weak_categories[:3]),
                ),
                "details": details,
            })

    return findings


# ============================================================
# 6. 記事化候補
# ============================================================

def suggest_article_candidates(products, wp_posts):
    """Shopify 商品のうち記事カバレッジが低いものを提案"""
    findings = []
    if not products or not wp_posts:
        return findings

    wp_all_titles = " ".join(
        (p.get("title", {}).get("rendered", "") if isinstance(p.get("title"), dict) else str(p.get("title", "")))
        for p in wp_posts
    ).lower()

    cat_article_count = Counter()
    for p in wp_posts:
        title = (p.get("title", {}).get("rendered", "") if isinstance(p.get("title"), dict) else str(p.get("title", ""))).lower()
        if any(kw in title for kw in ["figure", "doll", "statue"]):
            cat_article_count["Figures"] += 1
        elif any(kw in title for kw in ["card", "tcg"]):
            cat_article_count["Trading Cards"] += 1
        elif any(kw in title for kw in ["game", "console", "playstation", "xbox"]):
            cat_article_count["Video Games"] += 1
        elif any(kw in title for kw in ["tamagotchi"]):
            cat_article_count["Electronic Toys"] += 1
        elif any(kw in title for kw in ["manga", "art book", "blu-ray", "album", "cd"]):
            cat_article_count["Media & Books"] += 1

    candidates = []
    for p in products:
        title = p["title"]
        title_lower = title.lower()
        product_type = p.get("product_type", "")
        key_words = [w for w in title_lower.split() if len(w) > 4]
        match_count = sum(1 for w in key_words if w in wp_all_titles)
        coverage = match_count / max(len(key_words), 1)

        if coverage >= 0.5:
            continue

        score = (1 - coverage) * 10
        cat_key = "Figures" if "Figure" in product_type else product_type
        if cat_article_count.get(cat_key, 0) < 3:
            score += 5

        candidates.append({
            "title": title[:55],
            "type": product_type,
            "coverage": coverage,
            "score": score,
        })

    candidates.sort(key=lambda x: -x["score"])

    if candidates:
        details = []
        seen_cats = set()
        for item in candidates:
            cat = item["type"]
            if cat in seen_cats:
                continue
            seen_cats.add(cat)
            details.append("[%s] %s (coverage: %.0f%%)" % (cat, item["title"], item["coverage"] * 100))
            if len(details) >= 2:
                break

        findings.append({
            "type": "action", "agent": "content-strategist",
            "message": "Article candidates: %d products with low blog coverage" % len(candidates),
            "details": details,
        })

    return findings


# ============================================================
# 7. 既存記事からの派生記事案
# ============================================================

def suggest_derived_articles(products, wp_posts, wp_categories):
    """既存記事のカテゴリから派生記事（Top5, 比較, まとめ）を提案"""
    findings = []
    if not wp_posts or not wp_categories or not products:
        return findings

    # 記事数が多いカテゴリを特定
    cat_map = {c["id"]: c for c in wp_categories}
    cat_article_counts = Counter()
    for p in wp_posts:
        for cat_id in p.get("categories", []):
            if cat_id in cat_map:
                cat_article_counts[cat_id] += 1

    # 記事が3件以上あるカテゴリ → まとめ記事の候補
    article_ideas = []
    for cat_id, count in cat_article_counts.most_common(5):
        if count < 2:
            continue
        cat_name = cat_map[cat_id].get("name", "")

        # このカテゴリに対応する Shopify 商品があるか
        cat_slug = cat_map[cat_id].get("slug", "").lower()
        has_shopify = False
        for ptype, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in cat_slug for kw in keywords):
                shopify_count = sum(1 for p in products if p.get("product_type") == ptype)
                if shopify_count > 0:
                    has_shopify = True
                    break

        # 記事形式を提案
        if count >= 5:
            format_type = "Top 5 roundup"
        elif count >= 3:
            format_type = "Collector's guide"
        else:
            format_type = "Comparison article"

        article_ideas.append({
            "category": cat_name,
            "articles": count,
            "format": format_type,
            "shopify_linked": has_shopify,
        })

    if article_ideas:
        details = []
        for idea in article_ideas[:2]:
            shopify_note = " (Shopify products available)" if idea["shopify_linked"] else ""
            details.append(
                '"%s" -> %s (%d existing articles%s)' % (
                    idea["category"], idea["format"], idea["articles"], shopify_note,
                )
            )

        findings.append({
            "type": "action", "agent": "content-strategist",
            "message": "Derived article ideas: roundups and guides from existing content",
            "details": details,
        })

    return findings


# ============================================================
# 8. 今週の重点カテゴリ
# ============================================================

def suggest_weekly_focus(products, wp_posts, wp_categories):
    """具体的なアクションプラン付きの重点カテゴリ提案"""
    findings = []
    if not products:
        return findings

    cat_counts = Counter(p.get("product_type", "") for p in products if p.get("product_type"))

    wp_cat_counts = {}
    if wp_categories:
        collection_to_wp = {
            "Scale Figures": ["figure"],
            "Action Figures": ["figure"],
            "Trading Cards": ["trading-card", "tcg-trading-card-game-collectable-card", "pokemon"],
            "Video Games": ["video-game", "playstation-3-ps3-sony", "xbox360-microsoft"],
            "Electronic Toys": ["tamagotchi"],
            "Media & Books": ["book-magazine", "comic", "art-book-illustration", "dvd-blu-ray-ld"],
            "Plush & Soft Toys": ["stuffed-toy-plush-doll-mascot"],
        }
        slug_counts = {c.get("slug", ""): c.get("count", 0) for c in wp_categories}
        for collection, slugs in collection_to_wp.items():
            wp_cat_counts[collection] = sum(slug_counts.get(s, 0) for s in slugs)

    scores = []
    for cat, product_count in cat_counts.most_common():
        wp_count = wp_cat_counts.get(cat, 0)
        gap = max(0, product_count - wp_count)
        score = gap * 3 + product_count
        scores.append({"category": cat, "shopify": product_count, "articles": wp_count, "score": score})

    scores.sort(key=lambda x: -x["score"])

    week_num = NOW.isocalendar()[1]
    valid = [s for s in scores if s["score"] > 0]
    if valid:
        idx = week_num % len(valid)
        focus = valid[idx]

        cat_products = [p["title"][:40] for p in products if p.get("product_type") == focus["category"]][:3]

        actions = [
            "Shopify: %d products | Blog: %d articles" % (focus["shopify"], focus["articles"]),
        ]
        if focus["articles"] < focus["shopify"]:
            actions.append("Write: Create 1-2 articles featuring %s products" % focus["category"])
        actions.append("SNS: Post 2-3 %s items on Pinterest/Instagram this week" % focus["category"])
        actions.append("CTA: Ensure all %s articles link to Shopify Collection" % focus["category"])
        if cat_products:
            actions.append("Products: %s" % ", ".join(cat_products))

        findings.append({
            "type": "action", "agent": "growth-foundation",
            "message": "Weekly focus: %s" % focus["category"],
            "details": actions,
        })

    return findings


# ============================================================
# 共有状態の読み書き
# ============================================================

def _load_shared_state():
    """shared_state.json を読み込む"""
    path = os.path.join(SCRIPT_DIR, "shared_state.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_shared_state(state):
    """shared_state.json に書き込む"""
    path = os.path.join(SCRIPT_DIR, "shared_state.json")
    state["last_updated"] = NOW.strftime("%Y-%m-%d")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except IOError:
        pass


def _load_proposal_history():
    """proposal_history.json を読み込む"""
    path = os.path.join(SCRIPT_DIR, "proposal_history.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("proposals", [])
    except (json.JSONDecodeError, IOError):
        return []


# ============================================================
# 提案スコアリング
# ============================================================

def _score_proposal(proposal, shared_state):
    """提案にスコアを付与する"""
    weights = shared_state.get("scoring_weights", {
        "sales_proximity": 3,
        "ease_of_implementation": 2,
        "data_evidence": 2,
        "competitive_advantage": 1,
        "focus_category_match": 2,
        "past_success_rate": 1,
    })

    msg = proposal.get("message", "").lower()
    agent = proposal.get("agent", "")
    focus_cat = shared_state.get("weekly_focus", {}).get("category", "").lower()

    # 価値提供度（最上位方針: 売上直結より価値提供・信頼形成を優先）
    if "article" in msg or "internal link" in msg or "derived" in msg:
        sales = 3  # 読者価値の高いコンテンツ提供
    elif "shopify expansion" in msg or "products_to_add" in msg:
        sales = 2  # 商品充実（品揃え価値）
    elif "cta" in msg or "sns post" in msg:
        sales = 1  # 導線（自然な範囲）
    else:
        sales = 1

    # 実装容易度
    if agent == "catalog-migration-planner":
        ease = 2  # 商品追加はAPI1回
    elif "article" in msg:
        ease = 1  # 記事作成は手間がかかる
    else:
        ease = 2

    # データ根拠
    if "watchers" in msg or "coverage" in msg or "impressions" in msg:
        evidence = 3
    elif "articles" in msg and "products" in msg:
        evidence = 2
    else:
        evidence = 1

    # 競合比較優位
    competitive = 1  # デフォルト。競合分析結果が入ったら加点

    # 重点カテゴリ一致
    if focus_cat and focus_cat in msg:
        focus_match = 3
    elif focus_cat and any(word in msg for word in focus_cat.lower().split()):
        focus_match = 2
    else:
        focus_match = 1

    # 過去成功率（履歴に基づく）
    past = 1  # デフォルト
    history = _load_proposal_history()
    if history:
        # 類似提案の過去結果を確認
        for h in history:
            h_msg = h.get("proposal", "").lower()
            if any(word in h_msg for word in msg.split()[:3] if len(word) > 4):
                if h.get("actual_result") and "success" in str(h.get("actual_result", "")).lower():
                    past = 3  # 過去に成功
                elif h.get("actual_result") and "fail" in str(h.get("actual_result", "")).lower():
                    past = 0  # 過去に失敗

    total = (
        sales * weights.get("reader_value", weights.get("sales_proximity", 3))
        + ease * weights.get("ease_of_implementation", 2)
        + evidence * weights.get("data_evidence", 2)
        + competitive * weights.get("trust_building", weights.get("competitive_advantage", 1))
        + focus_match * weights.get("focus_category_match", 2)
        + past * weights.get("past_success_rate", 1)
    )

    proposal["_score"] = total
    return proposal


# ============================================================
# メインエントリポイント: 全提案を生成 + スコアリング
# ============================================================

def generate_all_suggestions(products, wp_posts, wp_categories):
    """全てのアクション提案を生成し、スコアリングして返す"""
    shared_state = _load_shared_state()

    all_findings = []
    all_findings.extend(suggest_article_themes(products, wp_posts, wp_categories))
    all_findings.extend(suggest_sns_posts(products, wp_posts))
    all_findings.extend(suggest_internal_links(wp_posts, wp_categories))
    all_findings.extend(suggest_shopify_candidates(products))
    all_findings.extend(suggest_ebay_to_shopify(products, wp_posts))
    all_findings.extend(suggest_article_candidates(products, wp_posts))
    all_findings.extend(suggest_derived_articles(products, wp_posts, wp_categories))
    all_findings.extend(suggest_weekly_focus(products, wp_posts, wp_categories))

    # スコアリング
    for f in all_findings:
        _score_proposal(f, shared_state)

    # スコア順にソート
    all_findings.sort(key=lambda x: -x.get("_score", 0))

    # 各提案にスコアを表示用に追加
    for f in all_findings:
        score = f.pop("_score", 0)
        f["message"] = "[Score:%d] %s" % (score, f["message"])

    return all_findings
