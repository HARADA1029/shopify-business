# ============================================================
# HD Toys Store Japan 日次点検スクリプト（改善提案型）
#
# 安全ルール:
#   - このスクリプトは読み取り専用
#   - Shopify API の書き込み操作（POST/PUT/DELETE）は一切行わない
#   - eBay API にはアクセスしない
#   - 提案をレポートに記載するのみ。本番変更は行わない
#
# レポート構成:
#   🔴 要対応 — 売上・運用に直接影響する問題
#   🚀 今日やると売上に効く改善 — すぐ実行できる改善提案
#   💡 中期改善候補 — 計画的に取り組む改善案
#   ✓ 異常なし — 正常確認済み項目
#
# 実行方法:
#   python ops/monitoring/daily_inspection.py
#
# 環境変数:
#   SHOPIFY_STORE, SHOPIFY_ACCESS_TOKEN, SHOPIFY_API_VERSION
#   CHATWORK_API_TOKEN, CHATWORK_ROOM_ID（任意）
# ============================================================

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import requests

# --- 設定 ---

STORE = os.environ.get("SHOPIFY_STORE", "")
TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-04")
CHATWORK_TOKEN = os.environ.get("CHATWORK_API_TOKEN", "")
CHATWORK_ROOM = os.environ.get("CHATWORK_ROOM_ID", "")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
DATE_STR = NOW.strftime("%Y-%m-%d")
TIME_STR = NOW.strftime("%Y-%m-%d %H:%M JST")

# GitHub Actions の実行 URL（環境変数から取得）
GITHUB_SERVER = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "")
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "")

if GITHUB_REPO and GITHUB_RUN_ID:
    ACTIONS_URL = f"{GITHUB_SERVER}/{GITHUB_REPO}/actions/runs/{GITHUB_RUN_ID}"
else:
    ACTIONS_URL = ""

# Collection タグ一覧（Smart Collection のルール条件と一致させる）
COLLECTION_TAGS = {
    "Action Figures": "Action Figures",
    "Figures & Statues": "Scale Figures",
    "Plush & Soft Toys": "Plush & Soft Toys",
    "Trading Cards": "Trading Cards",
    "Video Games": "Video Games",
    "Media & Books": "Media & Books",
    "Electronic Toys": "Electronic Toys",
    "Goods & Accessories": "Goods & Accessories",
}


# ============================================================
# Shopify API ヘルパー（読み取り専用）
# ============================================================

def shopify_get(endpoint):
    """Shopify Admin API に GET リクエスト"""
    url = f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/{endpoint}"
    headers = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        return resp
    except requests.exceptions.RequestException:
        return None


def shopify_graphql(query):
    """Shopify GraphQL API に読み取りクエリを送信"""
    url = f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json={"query": query}, timeout=30)
        return resp
    except requests.exceptions.RequestException:
        return None


def shopify_get_all_products(status="active"):
    """全商品を取得（ページネーション対応）"""
    products = []
    url = f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/products.json?status={status}&limit=50"
    headers = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
    while url:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
        except requests.exceptions.RequestException:
            break
        if resp.status_code != 200:
            break
        products.extend(resp.json().get("products", []))
        link = resp.headers.get("Link", "")
        if 'rel="next"' in link:
            match = re.search(r'<([^>]+)>; rel="next"', link)
            url = match.group(1) if match else None
        else:
            url = None
    return products


# ============================================================
# 各エージェントの点検ロジック
# ============================================================

# --- store-setup: ストア設定・UI・導線 ---

def inspect_store_setup(products, pages):
    """store-setup: 商品状態・画像・ページ・メニュー + UI改善提案"""
    findings = []

    # --- 監視項目 ---

    # 商品の公開状態
    active_count = len(products)
    draft_resp = shopify_get("products/count.json?status=draft")
    if draft_resp and draft_resp.status_code == 200:
        draft_count = draft_resp.json().get("count", 0)
    else:
        draft_count = "?"
        findings.append({"type": "critical", "agent": "store-setup",
                         "message": "Draft 商品数の取得に失敗"})

    findings.append({
        "type": "info", "agent": "store-setup",
        "message": f"Active: {active_count}件 / Draft: {draft_count}件",
    })

    # 画像0枚の公開商品
    no_image = [p for p in products if len(p.get("images", [])) == 0]
    if no_image:
        findings.append({
            "type": "critical", "agent": "store-setup",
            "message": f"画像なしの公開商品: {len(no_image)}件",
            "details": [p["title"][:50] for p in no_image[:5]],
        })

    # 必須ページの公開状態（Legal Notice を含む）
    required_pages = ["Shipping Policy", "Return Policy", "FAQ", "About Us"]
    page_titles_published = set()
    has_legal = False
    for p in pages:
        if p.get("published_at"):
            page_titles_published.add(p["title"])
            if "Legal" in p["title"] or "特定商取引法" in p["title"]:
                has_legal = True

    missing_pages = [t for t in required_pages if t not in page_titles_published]
    if not has_legal:
        missing_pages.append("Legal Notice (特定商取引法)")

    if missing_pages:
        findings.append({
            "type": "critical", "agent": "store-setup",
            "message": f"必須ページが非公開: {', '.join(missing_pages)}",
        })

    # メニューのリンク確認
    menu_query = """
    {
      menus(first: 5) {
        edges {
          node {
            handle
            title
            items {
              title
              url
              items { title url }
            }
          }
        }
      }
    }
    """
    menu_resp = shopify_graphql(menu_query)
    if menu_resp and menu_resp.status_code == 200:
        menus = menu_resp.json().get("data", {}).get("menus", {}).get("edges", [])
        main_menu = None
        footer_menu = None
        for edge in menus:
            m = edge["node"]
            if m["handle"] in ("main-menu", "main-menu-1"):
                main_menu = m
            if m["handle"] in ("footer", "footer-menu"):
                footer_menu = m

        if not main_menu or len(main_menu.get("items", [])) == 0:
            findings.append({
                "type": "critical", "agent": "store-setup",
                "message": "メインメニューが空または未設定",
            })

        if not footer_menu or len(footer_menu.get("items", [])) == 0:
            findings.append({
                "type": "critical", "agent": "store-setup",
                "message": "フッターメニューが空または未設定",
            })

        # メニュー内の空 URL をチェック
        empty_links = []
        for menu in [main_menu, footer_menu]:
            if not menu:
                continue
            for item in menu.get("items", []):
                if not item.get("url"):
                    empty_links.append(f"{menu['title']} > {item['title']}")
                for sub in item.get("items", []):
                    if not sub.get("url"):
                        empty_links.append(f"{menu['title']} > {item['title']} > {sub['title']}")

        if empty_links:
            findings.append({
                "type": "critical", "agent": "store-setup",
                "message": f"メニューに空リンク: {len(empty_links)}件",
                "details": empty_links[:5],
            })
    else:
        status = menu_resp.status_code if menu_resp else "N/A"
        detail = ""
        if menu_resp:
            try:
                gql_errors = menu_resp.json().get("errors", [])
                if gql_errors:
                    detail = f" ({gql_errors[0].get('message', '')[:80]})"
            except Exception:
                pass
        findings.append({
            "type": "critical", "agent": "store-setup",
            "message": f"メニュー情報の取得に失敗 (HTTP {status}){detail}",
        })

    return findings


# --- price-auditor: 価格監査 + 価格最適化提案 ---

def inspect_price_auditor(products):
    """price-auditor: 価格異常 + Compare at 活用提案 + 価格帯分析"""
    findings = []

    # --- 監視項目 ---

    price_errors = []
    no_compare = []
    zero_price = []

    # 価格帯カウント用
    band_low = 0     # $0-50
    band_mid = 0     # $50-100
    band_high = 0    # $100+

    for p in products:
        v = p.get("variants", [{}])[0]
        price = float(v.get("price", "0") or "0")
        compare = v.get("compare_at_price")
        compare_f = float(compare) if compare else 0

        if price == 0:
            zero_price.append(p["title"][:50])
        if compare_f > 0 and compare_f <= price:
            price_errors.append(
                f"{p['title'][:40]}: price=${price} compare=${compare_f}"
            )
        if not compare:
            no_compare.append(p["title"][:50])

        # 価格帯集計
        if price < 50:
            band_low += 1
        elif price < 100:
            band_mid += 1
        else:
            band_high += 1

    if zero_price:
        findings.append({
            "type": "critical", "agent": "price-auditor",
            "message": f"価格0の商品: {len(zero_price)}件",
            "details": zero_price[:5],
        })

    if price_errors:
        findings.append({
            "type": "critical", "agent": "price-auditor",
            "message": f"Price >= Compare at: {len(price_errors)}件",
            "details": price_errors[:5],
        })

    # --- 改善提案 ---

    # Compare at price 未設定 → 設定すれば割引表示で購買促進
    if no_compare:
        findings.append({
            "type": "suggestion", "agent": "price-auditor",
            "message": f"Compare at price 未設定: {len(no_compare)}/{len(products)}件 → 設定すると割引表示で購買促進",
        })

    # 価格帯分布（中期改善の参考情報）
    findings.append({
        "type": "medium_term", "agent": "price-auditor",
        "message": f"価格帯分布: $0-50: {band_low}件 / $50-100: {band_mid}件 / $100+: {band_high}件",
    })

    return findings


# --- catalog-migration-planner: 商品データ品質 + タグ最適化 ---

def inspect_catalog(products):
    """catalog-migration: 商品データ品質 + Collection タグ提案"""
    findings = []

    # --- 監視項目 ---

    no_type = [
        p for p in products
        if not p.get("product_type") or p["product_type"] == "Other"
    ]
    no_vendor = [p for p in products if not p.get("vendor")]
    no_tags = [p for p in products if not p.get("tags")]
    short_desc = [
        p for p in products if len(p.get("body_html", "") or "") < 100
    ]

    if no_type:
        findings.append({
            "type": "suggestion", "agent": "catalog-migration-planner",
            "message": f"Product Type 未設定/Other: {len(no_type)}件 → 適切な Type を設定して Collection に反映",
            "details": [p["title"][:50] for p in no_type[:5]],
        })

    if no_vendor:
        findings.append({
            "type": "medium_term", "agent": "catalog-migration-planner",
            "message": f"Vendor 未設定: {len(no_vendor)}件",
        })

    if no_tags:
        findings.append({
            "type": "suggestion", "agent": "catalog-migration-planner",
            "message": f"Tags 未設定: {len(no_tags)}件 → タグ追加で Collection・検索性を改善",
            "details": [p["title"][:50] for p in no_tags[:5]],
        })

    if short_desc:
        findings.append({
            "type": "medium_term", "agent": "catalog-migration-planner",
            "message": f"Description 100文字未満: {len(short_desc)}件 → SEO と購買判断に影響",
        })

    # --- 改善提案: Goods & Accessories Collection 状況 ---
    ga_products = [
        p for p in products if p.get("product_type") == "Goods & Accessories"
    ]
    if ga_products and len(ga_products) >= 7:
        findings.append({
            "type": "suggestion", "agent": "catalog-migration-planner",
            "message": f"Goods & Accessories: {len(ga_products)}件 → メインメニューへの追加を推奨",
        })
    elif ga_products:
        findings.append({
            "type": "info", "agent": "catalog-migration-planner",
            "message": f"Goods & Accessories: {len(ga_products)}件（Collection 作成済み。7件以上でメニュー追加を検討）",
        })

    return findings


# --- fulfillment-ops: 注文・在庫 ---

def inspect_fulfillment(products):
    """fulfillment-ops: 注文・在庫 + 在庫0チェック"""
    findings = []

    # --- 監視項目 ---

    resp = shopify_get("orders.json?status=open&fulfillment_status=unfulfilled&limit=50")
    if resp and resp.status_code == 200:
        orders = resp.json().get("orders", [])
        if orders:
            findings.append({
                "type": "critical", "agent": "fulfillment-ops",
                "message": f"未処理注文: {len(orders)}件",
                "details": [
                    f"#{o['order_number']} ${o['total_price']}" for o in orders[:5]
                ],
            })
        else:
            findings.append({
                "type": "ok", "agent": "fulfillment-ops",
                "message": "未処理注文: なし",
            })
    else:
        findings.append({
            "type": "critical", "agent": "fulfillment-ops",
            "message": "注文情報の取得に失敗",
        })

    # --- 改善提案: 在庫0の Active 商品 ---
    inventory_zero = []
    for p in products:
        for v in p.get("variants", []):
            qty = v.get("inventory_quantity", None)
            if qty is not None and qty <= 0:
                inventory_zero.append(p["title"][:50])
                break

    if inventory_zero:
        findings.append({
            "type": "suggestion", "agent": "fulfillment-ops",
            "message": f"在庫0の Active 商品: {len(inventory_zero)}件 → sold out 放置は顧客体験低下",
            "details": inventory_zero[:5],
        })

    return findings


# --- growth-foundation: SEO + 外部導線 ---

def inspect_seo(products):
    """growth-foundation: 画像 alt text + SEO Title/Meta + Collection SEO"""
    findings = []

    # --- 監視項目: alt text ---

    no_alt_count = 0
    total_images = 0
    for p in products:
        for img in p.get("images", []):
            total_images += 1
            if not img.get("alt"):
                no_alt_count += 1

    if no_alt_count > 0:
        findings.append({
            "type": "suggestion", "agent": "growth-foundation",
            "message": f"画像 alt text 未設定: {no_alt_count}/{total_images}枚 → 設定で画像検索流入を改善",
        })
    else:
        findings.append({
            "type": "ok", "agent": "growth-foundation",
            "message": f"画像 alt text: 全{total_images}枚設定済み",
        })

    # --- 改善提案: SEO Title 未設定の商品 ---
    # Shopify の商品 SEO Title は GraphQL でのみ取得可能
    seo_query = """
    {
      products(first: 100, query: "status:active") {
        edges {
          node {
            id
            title
            seo {
              title
              description
            }
          }
        }
      }
    }
    """
    seo_resp = shopify_graphql(seo_query)
    if seo_resp and seo_resp.status_code == 200:
        seo_data = seo_resp.json().get("data", {}).get("products", {}).get("edges", [])

        no_seo_title = []
        no_seo_desc = []
        short_seo_desc = []

        for edge in seo_data:
            node = edge["node"]
            seo = node.get("seo", {}) or {}
            title = node.get("title", "")[:50]

            if not seo.get("title"):
                no_seo_title.append(title)
            if not seo.get("description"):
                no_seo_desc.append(title)
            elif len(seo.get("description", "")) < 80:
                short_seo_desc.append(title)

        if no_seo_title:
            findings.append({
                "type": "suggestion", "agent": "growth-foundation",
                "message": f"SEO Title 未設定: {len(no_seo_title)}/{len(seo_data)}件 → 設定で検索結果の表示を改善",
                "details": no_seo_title[:5],
            })

        if no_seo_desc:
            findings.append({
                "type": "suggestion", "agent": "growth-foundation",
                "message": f"Meta Description 未設定: {len(no_seo_desc)}/{len(seo_data)}件 → 設定でCTR向上",
                "details": no_seo_desc[:5],
            })
        elif short_seo_desc:
            findings.append({
                "type": "medium_term", "agent": "growth-foundation",
                "message": f"Meta Description 80文字未満: {len(short_seo_desc)}件 → 充実させるとCTR改善",
            })

        if not no_seo_title and not no_seo_desc:
            findings.append({
                "type": "ok", "agent": "growth-foundation",
                "message": f"SEO Title / Meta Description: 全{len(seo_data)}件設定済み",
            })
    else:
        findings.append({
            "type": "info", "agent": "growth-foundation",
            "message": "商品 SEO 情報の取得に失敗（GraphQL）",
        })

    # --- 改善提案: Collection SEO の状態 ---
    col_seo_query = """
    {
      collections(first: 20) {
        edges {
          node {
            title
            seo {
              title
              description
            }
          }
        }
      }
    }
    """
    col_resp = shopify_graphql(col_seo_query)
    if col_resp and col_resp.status_code == 200:
        col_data = col_resp.json().get("data", {}).get("collections", {}).get("edges", [])
        no_col_seo = []
        for edge in col_data:
            node = edge["node"]
            seo = node.get("seo", {}) or {}
            if not seo.get("title") or not seo.get("description"):
                no_col_seo.append(node["title"])

        if no_col_seo:
            findings.append({
                "type": "medium_term", "agent": "growth-foundation",
                "message": f"Collection SEO 未設定: {len(no_col_seo)}件 → 設定でカテゴリページの検索流入を改善",
                "details": no_col_seo[:5],
            })

    return findings


# --- Collection カバレッジ: Active 商品の Collection 所属状況 ---

def inspect_collection_coverage(products):
    """store-setup + catalog: Active 商品の Collection 所属状況"""
    findings = []

    # Collection タグを1つも持たない Active 商品を抽出
    collection_tag_values = set(COLLECTION_TAGS.values())

    no_collection = []
    for p in products:
        tags = [t.strip() for t in (p.get("tags", "") or "").split(",") if t.strip()]
        if not any(tag in collection_tag_values for tag in tags):
            no_collection.append(p["title"][:50])

    if no_collection:
        findings.append({
            "type": "suggestion", "agent": "store-setup",
            "message": f"Collection 未所属の Active 商品: {len(no_collection)}件 → タグ追加で導線改善",
            "details": no_collection[:5],
        })

    # Active 商品0件の Collection を検出
    resp = shopify_get("smart_collections.json?limit=50")
    if resp and resp.status_code == 200:
        collections = resp.json().get("smart_collections", [])
        empty_collections = []
        for col in collections:
            # Collection 内の Active 商品数を確認
            col_id = col["id"]
            count_resp = shopify_get(
                f"products/count.json?collection_id={col_id}&status=active"
            )
            if count_resp and count_resp.status_code == 200:
                cnt = count_resp.json().get("count", 0)
                if cnt == 0:
                    empty_collections.append(col["title"])

        if empty_collections:
            findings.append({
                "type": "suggestion", "agent": "store-setup",
                "message": f"Active 商品0件の Collection: {len(empty_collections)}件 → 商品追加 or メニューから非表示",
                "details": empty_collections,
            })

    return findings


# --- Draft 昇格候補: データ品質が揃っている Draft 商品 ---

def inspect_draft_readiness():
    """store-setup: Draft → Active 昇格候補の抽出"""
    findings = []

    drafts = shopify_get_all_products("draft")
    if not drafts:
        return findings

    ready = []
    not_ready_reasons = {"no_image": 0, "no_type": 0, "no_tags": 0, "short_desc": 0}

    collection_tag_values = set(COLLECTION_TAGS.values())

    for p in drafts:
        has_image = len(p.get("images", [])) > 0
        has_type = bool(p.get("product_type")) and p["product_type"] != "Other"
        tags = [t.strip() for t in (p.get("tags", "") or "").split(",") if t.strip()]
        has_collection_tag = any(tag in collection_tag_values for tag in tags)
        desc_len = len(p.get("body_html", "") or "")
        has_desc = desc_len >= 100
        price = float(p.get("variants", [{}])[0].get("price", "0") or "0")
        has_price = price > 0

        if has_image and has_type and has_collection_tag and has_desc and has_price:
            ready.append(p["title"][:50])
        else:
            if not has_image:
                not_ready_reasons["no_image"] += 1
            if not has_type:
                not_ready_reasons["no_type"] += 1
            if not has_collection_tag:
                not_ready_reasons["no_tags"] += 1
            if not has_desc:
                not_ready_reasons["short_desc"] += 1

    if ready:
        findings.append({
            "type": "medium_term", "agent": "store-setup",
            "message": f"Draft → Active 昇格候補: {len(ready)}/{len(drafts)}件（画像・Type・タグ・説明・価格 全て OK）",
            "details": ready[:5],
        })

    # 昇格できない理由の集計
    blockers = []
    if not_ready_reasons["no_image"]:
        blockers.append(f"画像なし: {not_ready_reasons['no_image']}件")
    if not_ready_reasons["no_type"]:
        blockers.append(f"Type 未設定/Other: {not_ready_reasons['no_type']}件")
    if not_ready_reasons["no_tags"]:
        blockers.append(f"Collection タグなし: {not_ready_reasons['no_tags']}件")
    if not_ready_reasons["short_desc"]:
        blockers.append(f"説明不足: {not_ready_reasons['short_desc']}件")

    if blockers:
        findings.append({
            "type": "medium_term", "agent": "store-setup",
            "message": f"Draft 昇格ブロッカー: {', '.join(blockers)}",
        })

    return findings


# ============================================================
# Phase 2: 外部導線チェック
# ============================================================

# 設定ファイルのパス
EXTERNAL_CONFIG_PATH = os.path.join(SCRIPT_DIR, "external_links_config.json")


def _load_external_config():
    """外部導線の設定ファイルを読み込む"""
    if not os.path.exists(EXTERNAL_CONFIG_PATH):
        return None
    try:
        with open(EXTERNAL_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def inspect_hd_bodyscience():
    """growth-foundation: hd-bodyscience.com の Shopify 導線チェック

    1. HTTP でトップページの Shopify リンク有無を確認
    2. WordPress REST API で記事データを取得し、以下を分析:
       - 最終更新日・更新頻度
       - Shopify 関連カテゴリの記事数
       - 記事本文に Shopify リンクが含まれているか
       - Shopify 送客候補記事の特定
    3. 設定ファイルの checks に基づく導線改善提案
    """
    findings = []
    config = _load_external_config()
    if not config or "hd_bodyscience" not in config:
        findings.append({
            "type": "info", "agent": "blog-analyst",
            "message": "hd-bodyscience.com: 設定ファイル未読込 (external_links_config.json)",
        })
        return findings

    hd_config = config["hd_bodyscience"]
    site_url = hd_config.get("url", "https://hd-bodyscience.com/")
    checks = hd_config.get("checks", {})

    # --- 1. HTTP でトップページの Shopify リンク有無を確認 ---
    shopify_link_found = False
    try:
        resp = requests.get(site_url, timeout=15, headers={
            "User-Agent": "HD-Toys-Store-DailyInspection/1.0"
        })
        if resp.status_code == 200:
            page_text = resp.text.lower()
            for kw in ["hd-toys-store-japan.myshopify.com", "hd-toys-store-japan"]:
                if kw.lower() in page_text:
                    shopify_link_found = True
                    break
        else:
            findings.append({
                "type": "info", "agent": "blog-analyst",
                "message": "hd-bodyscience.com: HTTP %d (access failed)" % resp.status_code,
            })
            return findings
    except requests.exceptions.RequestException as e:
        findings.append({
            "type": "info", "agent": "blog-analyst",
            "message": "hd-bodyscience.com: connection failed (%s)" % str(e)[:60],
        })
        return findings

    if not shopify_link_found:
        findings.append({
            "type": "suggestion", "agent": "blog-analyst",
            "message": "hd-bodyscience.com に Shopify へのリンクが未設置 -> 以下を追加推奨",
            "details": [
                "サイドバーに Shopify ストアバナーを追加 (eBay バナーと並列)",
                "ヘッダーナビに Shopify ストアのメニュー項目を追加",
                "フッターに Shopify ストアリンクを追加",
            ],
        })
    else:
        findings.append({
            "type": "ok", "agent": "blog-analyst",
            "message": "hd-bodyscience.com: Shopify ストアへのリンク設置済み",
        })

    # --- 2. WordPress REST API で記事データを分析 ---
    wp_api = site_url.rstrip("/") + "/wp-json/wp/v2"
    wp_headers = {"User-Agent": "HD-Toys-Store-DailyInspection/1.0"}

    try:
        # 最新10記事を取得（タイトル・日付・カテゴリ・本文）
        wp_resp = requests.get(
            wp_api + "/posts?per_page=10&_fields=id,title,date,link,categories,content",
            headers=wp_headers, timeout=15,
        )
        if wp_resp.status_code != 200:
            findings.append({
                "type": "info", "agent": "blog-analyst",
                "message": "hd-bodyscience.com WP API: HTTP %d" % wp_resp.status_code,
            })
            return findings

        recent_posts = wp_resp.json()
        total_posts = wp_resp.headers.get("X-WP-Total", "?")

        # カテゴリ情報を取得
        cat_resp = requests.get(
            wp_api + "/categories?per_page=100&_fields=id,slug,name,count",
            headers=wp_headers, timeout=15,
        )
        cat_map = {}
        if cat_resp.status_code == 200:
            cat_map = {c["id"]: c for c in cat_resp.json()}

    except requests.exceptions.RequestException as e:
        findings.append({
            "type": "info", "agent": "blog-analyst",
            "message": "hd-bodyscience.com WP API: connection failed (%s)" % str(e)[:60],
        })
        return findings

    # --- 2a. 最終更新日・更新頻度 ---
    if recent_posts:
        from datetime import datetime as _dt
        latest_date_str = recent_posts[0]["date"][:10]
        try:
            latest_date = _dt.strptime(latest_date_str, "%Y-%m-%d").date()
            today = _dt.now().date()
            days_since = (today - latest_date).days
        except ValueError:
            days_since = -1

        latest_title = recent_posts[0]["title"]["rendered"][:60]

        if days_since > 14:
            findings.append({
                "type": "suggestion", "agent": "blog-analyst",
                "message": "hd-bodyscience.com: %d日間記事更新なし -> 定期更新で SEO 評価を維持" % days_since,
                "details": [
                    "最新記事: [%s] %s" % (latest_date_str, latest_title),
                    "総記事数: %s件" % total_posts,
                ],
            })
        elif days_since > 7:
            findings.append({
                "type": "medium_term", "agent": "blog-analyst",
                "message": "hd-bodyscience.com: 最終更新 %d日前 (%s)" % (days_since, latest_date_str),
                "details": ["最新記事: %s" % latest_title],
            })
        else:
            findings.append({
                "type": "ok", "agent": "blog-analyst",
                "message": "hd-bodyscience.com: 最終更新 %s (%d日前, 総%s件)" % (latest_date_str, days_since, total_posts),
            })

    # --- 2b. Shopify 関連カテゴリの記事 ---
    # Shopify 商材と重なるカテゴリ slug
    SHOPIFY_SLUGS = {
        "figure", "collectibles", "video-game", "toys-hobby",
        "stuffed-toy-plush-doll-mascot", "trading-card",
        "tcg-trading-card-game-collectable-card", "tamagotchi",
        "bandai-namco-spirits", "power-rangers-series", "epoch",
        "sylvanian-families", "hatsune-miku-vocaloid-series",
        "ichiban-kuji", "good-smile-company-max-factory",
        "freeing-b-style", "sega", "takara-tomy", "pokemon",
        "pokemon-pokemon-pocket-monster",
        "pokemon-pokemon-pocket-monster-collectibles",
        "metal-fight-beyblade-fusion-saga", "transformers-diaclone",
        "comic", "book-magazine", "art-book-illustration",
        "dvd-blu-ray-ld", "game-anime-sound-track-ost",
        "vocaloid-series-hatsune-miku-diva",
        "hatsune-miku-vocaloid-series-collectibles",
        "playstation-3-ps3-sony", "ryu-ga-gotoku-series",
        "psp-playstation-portable-vita", "xbox360-microsoft",
        "resident-evil-biohazard", "metal-gear-solid-series",
    }
    shopify_cat_ids = set()
    for cid, c in cat_map.items():
        if c["slug"] in SHOPIFY_SLUGS:
            shopify_cat_ids.add(cid)

    shopify_related_count = 0
    for c in cat_map.values():
        if c["slug"] in SHOPIFY_SLUGS:
            shopify_related_count += c.get("count", 0)

    # --- 2c. 記事本文に Shopify リンクが含まれているか ---
    posts_with_shopify = []
    posts_without_shopify = []
    for p in recent_posts:
        content_html = (p.get("content", {}).get("rendered", "") or "").lower()
        title = p["title"]["rendered"][:50]
        cat_ids = set(p.get("categories", []))
        is_shopify_related = bool(cat_ids & shopify_cat_ids)

        has_link = (
            "hd-toys-store-japan" in content_html
            or "myshopify.com" in content_html
        )
        if has_link:
            posts_with_shopify.append(title)
        elif is_shopify_related:
            posts_without_shopify.append(title)

    if posts_without_shopify:
        findings.append({
            "type": "suggestion", "agent": "blog-analyst",
            "message": "hd-bodyscience.com: Shopify リンク未設置の送客候補記事 %d件 -> 記事内に購入リンクを追加" % len(posts_without_shopify),
            "details": posts_without_shopify[:5],
        })
    if posts_with_shopify:
        findings.append({
            "type": "ok", "agent": "blog-analyst",
            "message": "hd-bodyscience.com: Shopify リンク設置済み記事 %d件" % len(posts_with_shopify),
        })

    # --- 3. 設定ファイルの checks に基づく導線改善提案 ---
    pending_items = []
    if not checks.get("sidebar_banner"):
        pending_items.append(
            "サイドバーバナー: eBay 3店舗バナーと並べて Shopify バナーを追加"
        )
    if not checks.get("header_nav_link"):
        pending_items.append(
            "ヘッダーナビ: Shopify Store メニュー項目を追加"
        )
    if not checks.get("footer_link"):
        pending_items.append(
            "フッター: Shopify ストアリンクを追加"
        )
    if not checks.get("article_cta"):
        pending_items.append(
            "記事内 CTA: Shopify 関連カテゴリの記事に購入リンクを追加 (対象: 約%d件)" % shopify_related_count
        )
    if not checks.get("shopify_buy_button"):
        pending_items.append(
            "Shopify Buy Button: 商品紹介記事に購入ボタンを埋め込み"
        )

    if pending_items:
        findings.append({
            "type": "medium_term", "agent": "blog-analyst",
            "message": "hd-bodyscience.com 導線改善候補: %d件" % len(pending_items),
            "details": pending_items,
        })

    return findings

def inspect_sns_status():
    """growth-foundation: SNS アカウント状況チェック (設定ファイルベース)

    - eBay 用 SNS: プロフィールリンクに Shopify URL が設置されているか
    - Shopify 専用 SNS: アカウント作成状況
    """
    findings = []
    config = _load_external_config()
    if not config:
        findings.append({
            "type": "info", "agent": "sns-manager",
            "message": "SNS チェック: 設定ファイル未読込 (external_links_config.json)",
        })
        return findings

    # --- eBay 用 SNS: プロフィールリンクの Shopify URL 設置状況 ---
    ebay_sns = config.get("ebay_sns", {}).get("accounts", {})
    not_set = []
    already_set = []
    for platform, info in ebay_sns.items():
        if info.get("shopify_url_in_profile"):
            already_set.append(platform)
        else:
            not_set.append(platform)

    if not_set:
        findings.append({
            "type": "suggestion", "agent": "sns-manager",
            "message": "eBay SNS プロフィールに Shopify URL 未設置: %s -> リンク欄に追加推奨" % ", ".join(not_set),
        })
    if already_set:
        findings.append({
            "type": "ok", "agent": "sns-manager",
            "message": "eBay SNS プロフィール Shopify URL 設置済み: %s" % ", ".join(already_set),
        })

    # --- Shopify 専用 SNS: 作成状況 ---
    shopify_sns = config.get("shopify_sns", {}).get("accounts", {})
    not_created = []
    created = []
    display_names = {
        "instagram": "Instagram",
        "x_twitter": "X (Twitter)",
        "tiktok": "TikTok",
        "youtube": "YouTube",
        "pinterest": "Pinterest",
    }
    for platform, info in shopify_sns.items():
        display_name = display_names.get(platform, platform)
        if info.get("created"):
            username = info.get("username", "?")
            created.append("%s: @%s" % (display_name, username))
        else:
            not_created.append(display_name)

    if not_created:
        findings.append({
            "type": "medium_term", "agent": "sns-manager",
            "message": "Shopify 専用 SNS 未作成: %s -> 作成して集客チャネルを拡張" % ", ".join(not_created),
            "details": [
                "優先: Instagram (フィギュア・おもちゃの視覚訴求に最適)",
                "次点: X/Twitter (新着情報・セール告知に有効)",
                "検討: TikTok (開封動画・レビュー動画で認知拡大)",
            ],
        })
    if created:
        findings.append({
            "type": "ok", "agent": "sns-manager",
            "message": "Shopify 専用 SNS 作成済み: %s" % ", ".join(created),
        })

    # --- SNS 投稿実行結果チェック ---
    posted_file = os.path.join(SCRIPT_DIR, "sns_posted.json")
    if os.path.exists(posted_file):
        try:
            with open(posted_file, "r", encoding="utf-8") as f:
                posted = json.load(f)
            history = posted.get("history", [])

            # 昨日の投稿を確認
            from datetime import timedelta as _td
            yesterday = (NOW - _td(days=1)).strftime("%Y-%m-%d")
            yesterday_posts = [h for h in history if h.get("date") == yesterday]

            expected_platforms = {"instagram", "facebook", "facebook_video", "instagram_reels", "youtube_shorts"}
            actual_platforms = set(h.get("platform", "") for h in yesterday_posts)
            missing_platforms = expected_platforms - actual_platforms

            if yesterday_posts:
                post_details = []
                for h in yesterday_posts:
                    post_details.append("[%s] %s" % (h.get("platform", "?"), h.get("title", "?")[:40]))

                findings.append({
                    "type": "ok", "agent": "sns-manager",
                    "message": "SNS posts yesterday: %d posts on %d platforms" % (len(yesterday_posts), len(actual_platforms)),
                    "details": post_details,
                })
            else:
                findings.append({
                    "type": "suggestion", "agent": "sns-manager",
                    "message": "SNS posts yesterday: 0 posts (no posts recorded for %s)" % yesterday,
                    "details": ["Check GitHub Actions workflow execution and sns_posted.json"],
                })

            # プラットフォーム別の欠落チェック
            if missing_platforms:
                missing_details = []
                for p in sorted(missing_platforms):
                    if p == "instagram_reels":
                        missing_details.append("[%s] Not posted — check video hosting (WordPress upload)" % p)
                    elif p == "youtube_shorts":
                        missing_details.append("[%s] Not posted — check YouTube token and Veo generation" % p)
                    else:
                        missing_details.append("[%s] Not posted — check workflow logs" % p)

                findings.append({
                    "type": "suggestion", "agent": "sns-manager",
                    "message": "SNS missing platforms yesterday: %s" % ", ".join(sorted(missing_platforms)),
                    "details": missing_details,
                })

        except (json.JSONDecodeError, IOError):
            pass

    return findings


# ============================================================
# Phase 3: GA4 / Search Console API 連携
# ============================================================

# GCP 認証情報
GCP_KEY_FILE = os.environ.get("GCP_KEY_FILE", os.path.join(
    os.path.dirname(SCRIPT_DIR), os.pardir, ".gcp_service_account.json"
))
GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "")

# GCP キーファイルのパスを解決（スクリプト実行ディレクトリ基準）
_project_root = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if not os.path.isabs(GCP_KEY_FILE):
    GCP_KEY_FILE = os.path.join(_project_root, GCP_KEY_FILE)


def inspect_ga4():
    """growth-foundation: GA4 アクセスデータの取得と分析

    取得指標:
    - 昨日のセッション数 / PV / ユーザー数
    - UTM ソース別の流入（hd-bodyscience.com からの送客数）
    - UTM content 別（どの記事 CTA が効果的か）
    - ランディングページ Top 5
    """
    findings = []

    if not GA4_PROPERTY_ID:
        findings.append({
            "type": "info", "agent": "growth-foundation",
            "message": "GA4: GA4_PROPERTY_ID が未設定",
        })
        return findings

    if not os.path.exists(GCP_KEY_FILE):
        findings.append({
            "type": "info", "agent": "growth-foundation",
            "message": "GA4: GCP キーファイルが見つかりません",
        })
        return findings

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            RunReportRequest, DateRange, Metric, Dimension,
        )
        from google.oauth2 import service_account
    except ImportError:
        findings.append({
            "type": "info", "agent": "growth-foundation",
            "message": "GA4: google-analytics-data パッケージ未インストール",
        })
        return findings

    try:
        credentials = service_account.Credentials.from_service_account_file(
            GCP_KEY_FILE,
            scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        )
        client = BetaAnalyticsDataClient(credentials=credentials)
        prop = "properties/%s" % GA4_PROPERTY_ID

        # --- 昨日の基本指標 ---
        resp = client.run_report(RunReportRequest(
            property=prop,
            date_ranges=[DateRange(start_date="yesterday", end_date="yesterday")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="screenPageViews"),
                Metric(name="activeUsers"),
            ],
        ))

        if resp.rows:
            sessions = resp.rows[0].metric_values[0].value
            pvs = resp.rows[0].metric_values[1].value
            users = resp.rows[0].metric_values[2].value
            findings.append({
                "type": "info", "agent": "growth-foundation",
                "message": "GA4 昨日: %s sessions / %s PV / %s users" % (sessions, pvs, users),
            })
        else:
            findings.append({
                "type": "info", "agent": "growth-foundation",
                "message": "GA4 昨日: データなし (設置直後の可能性)",
            })
            return findings

        # --- UTM ソース別（hd-bodyscience からの送客） ---
        resp2 = client.run_report(RunReportRequest(
            property=prop,
            date_ranges=[DateRange(start_date="yesterday", end_date="yesterday")],
            dimensions=[
                Dimension(name="sessionSource"),
                Dimension(name="sessionMedium"),
            ],
            metrics=[Metric(name="sessions")],
        ))

        hd_sessions = 0
        for row in resp2.rows:
            source = row.dimension_values[0].value
            if "hd-bodyscience" in source:
                hd_sessions += int(row.metric_values[0].value)

        if hd_sessions > 0:
            findings.append({
                "type": "ok", "agent": "growth-foundation",
                "message": "hd-bodyscience.com -> Shopify 送客: %d sessions" % hd_sessions,
            })
        else:
            findings.append({
                "type": "medium_term", "agent": "growth-foundation",
                "message": "hd-bodyscience.com -> Shopify 送客: 0件 (CTA 導線の効果測定中)",
            })

        # --- UTM content 別（どの記事 CTA が効果的か）---
        resp3 = client.run_report(RunReportRequest(
            property=prop,
            date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
            dimensions=[Dimension(name="sessionManualAdContent")],
            metrics=[Metric(name="sessions")],
        ))

        cta_results = []
        for row in resp3.rows:
            utm_content = row.dimension_values[0].value
            if utm_content and utm_content != "(not set)":
                cta_results.append(
                    "%s: %s sessions" % (utm_content, row.metric_values[0].value)
                )

        if cta_results:
            findings.append({
                "type": "ok", "agent": "growth-foundation",
                "message": "CTA 効果 (7日間): %d記事から送客あり" % len(cta_results),
                "details": cta_results[:5],
            })

        # --- ランディングページ Top 5 ---
        resp4 = client.run_report(RunReportRequest(
            property=prop,
            date_ranges=[DateRange(start_date="yesterday", end_date="yesterday")],
            dimensions=[Dimension(name="landingPage")],
            metrics=[Metric(name="sessions")],
            limit=5,
        ))

        if resp4.rows:
            landing_pages = []
            for row in resp4.rows:
                page = row.dimension_values[0].value
                sess = row.metric_values[0].value
                landing_pages.append("%s (%s sessions)" % (page[:60], sess))

            findings.append({
                "type": "info", "agent": "growth-foundation",
                "message": "Landing Page Top %d:" % len(landing_pages),
                "details": landing_pages,
            })

    except Exception as e:
        findings.append({
            "type": "info", "agent": "growth-foundation",
            "message": "GA4 API error: %s" % str(e)[:80],
        })

    return findings


def inspect_search_console():
    """growth-foundation: Search Console データの取得と分析

    取得指標:
    - 検索クエリ Top 10（クリック数順）
    - サイト別のクリック数・表示回数
    - CTR が低いが表示回数が多いクエリ（改善候補）
    """
    findings = []

    if not os.path.exists(GCP_KEY_FILE):
        findings.append({
            "type": "info", "agent": "growth-foundation",
            "message": "Search Console: GCP キーファイルが見つかりません",
        })
        return findings

    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
    except ImportError:
        findings.append({
            "type": "info", "agent": "growth-foundation",
            "message": "Search Console: google-api-python-client パッケージ未インストール",
        })
        return findings

    try:
        credentials = service_account.Credentials.from_service_account_file(
            GCP_KEY_FILE,
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
        )
        service = build("searchconsole", "v1", credentials=credentials)

        # 両サイトのデータを取得（過去7日間、SC は 2-3日遅延あり）
        sites = [
            ("hd-bodyscience.com", "https://hd-bodyscience.com/"),
            ("Shopify", "https://hd-toys-store-japan.myshopify.com/"),
        ]

        for site_name, site_url in sites:
            try:
                resp = service.searchanalytics().query(
                    siteUrl=site_url,
                    body={
                        "startDate": (NOW - timedelta(days=7)).strftime("%Y-%m-%d"),
                        "endDate": (NOW - timedelta(days=2)).strftime("%Y-%m-%d"),
                        "dimensions": ["query"],
                        "rowLimit": 10,
                    },
                ).execute()

                rows = resp.get("rows", [])
                if rows:
                    total_clicks = sum(r["clicks"] for r in rows)
                    total_impressions = sum(r["impressions"] for r in rows)

                    findings.append({
                        "type": "info", "agent": "growth-foundation",
                        "message": "Search Console %s (7日間): %d clicks / %d impressions" % (
                            site_name, total_clicks, total_impressions,
                        ),
                    })

                    # Top 5 クエリ
                    top_queries = []
                    for r in rows[:5]:
                        q = r["keys"][0]
                        clicks = r["clicks"]
                        impr = r["impressions"]
                        ctr = r.get("ctr", 0) * 100
                        pos = r.get("position", 0)
                        top_queries.append(
                            "%s: %d clicks / %d impr (CTR %.1f%%, pos %.1f)"
                            % (q[:40], clicks, impr, ctr, pos)
                        )

                    if top_queries:
                        findings.append({
                            "type": "info", "agent": "growth-foundation",
                            "message": "Search Console %s Top queries:" % site_name,
                            "details": top_queries,
                        })

                    # CTR 改善候補（表示が多いがクリックが少ない）
                    low_ctr = [
                        r for r in rows
                        if r["impressions"] >= 10 and r.get("ctr", 1) < 0.03
                    ]
                    if low_ctr:
                        ctr_candidates = []
                        for r in low_ctr[:3]:
                            q = r["keys"][0]
                            ctr_candidates.append(
                                "%s: %d impr but %d clicks (CTR %.1f%%)"
                                % (q[:40], r["impressions"], r["clicks"], r.get("ctr", 0) * 100)
                            )
                        findings.append({
                            "type": "suggestion", "agent": "growth-foundation",
                            "message": "Search Console %s: CTR 改善候補 %d件 -> Title/Meta 改善で流入増" % (
                                site_name, len(low_ctr),
                            ),
                            "details": ctr_candidates,
                        })
                else:
                    findings.append({
                        "type": "info", "agent": "growth-foundation",
                        "message": "Search Console %s: データなし (登録直後の可能性)" % site_name,
                    })

            except Exception as e:
                error_msg = str(e)[:80]
                if "403" in error_msg or "permission" in error_msg.lower():
                    findings.append({
                        "type": "info", "agent": "growth-foundation",
                        "message": "Search Console %s: 権限エラー (%s)" % (site_name, error_msg),
                    })
                else:
                    findings.append({
                        "type": "info", "agent": "growth-foundation",
                        "message": "Search Console %s: %s" % (site_name, error_msg),
                    })

    except Exception as e:
        findings.append({
            "type": "info", "agent": "growth-foundation",
            "message": "Search Console API error: %s" % str(e)[:80],
        })

    return findings


# ============================================================
# アクション提案（action_suggestions.py に分離）
# ============================================================

import sys as _sys
_sys.path.insert(0, SCRIPT_DIR)
from action_suggestions import generate_all_suggestions
from settings_audit import run_all_audits
from competitive_analysis import run_competitive_analysis
from sns_optimizer import run_sns_optimization
from task_tracker import generate_task_report
from cross_feedback import generate_cross_feedback
from agent_learning_summary import generate_learning_summary
from agent_load_monitor import check_agent_load
from execution_evidence import generate_execution_evidence
from blog_automation import run_blog_automation
from ebay_sales_analysis import run_ebay_sales_analysis
from product_pdca import run_product_pdca
from price_sync import sync_prices
from image_sync import sync_images
from experiment_manager import check_experiments, auto_register_experiments
from research_audit import generate_research_report
from data_sufficiency_audit import generate_data_sufficiency_report
from self_learning_audit import generate_self_learning_audit
from bug_audit import generate_bug_audit
from design_audit import run_design_audit
from sales_optimization import run_sales_optimization
from state_consistency_audit import generate_consistency_audit, filter_findings_by_ledger


# ============================================================
# レポート生成
# ============================================================

def classify_findings(all_findings):
    """findings を新4段階で分類"""
    critical = [f for f in all_findings if f["type"] == "critical"]
    suggestion = [f for f in all_findings if f["type"] == "suggestion"]
    medium_term = [f for f in all_findings if f["type"] == "medium_term"]
    info = [f for f in all_findings if f["type"] == "info"]
    ok = [f for f in all_findings if f["type"] == "ok"]
    action = [f for f in all_findings if f["type"] == "action"]
    return critical, suggestion, medium_term, info, ok, action


def _format_finding_line(f, prefix=""):
    """finding を1行（+ details）にフォーマット"""
    lines = []
    agent = f.get("agent", "")
    lines.append(f"{prefix}- [{agent}] {f['message']}")
    for d in f.get("details", []):
        lines.append(f"{prefix}  - {d}")
    return lines


def _classify_task_status(all_findings):
    """タスクを6区分に分類する"""
    # 実施済み基盤（完了済みで安定稼働中）
    completed_infra = [
        "GA4 e-commerce events", "Shopify store setup", "eBay price sync",
        "Collection setup", "Trust badges", "Shipping policy", "Refund policy",
        "Instagram auto post", "Facebook auto post", "YouTube auto post",
        "Blog auto post", "WordPress CTA", "UTM tracking",
        "Daily inspection workflow", "SNS video post workflow",
    ]
    # 実施済み（活用改善フェーズ）
    improvement_phase = [
        "GA4 data → product PDCA", "Blog PDCA → article quality",
        "SNS analytics → posting optimization", "Price sync → margin optimization",
        "Competitive analysis → UI improvement", "Internal links → SEO boost",
    ]
    return completed_infra, improvement_phase


def generate_markdown_report(all_findings, store_info):
    """詳細 Markdown レポートを生成（6区分フォーマット）"""
    critical, suggestion, medium_term, info, ok, action = classify_findings(all_findings)

    lines = []
    lines.append("# HD Toys Store Japan 日次レポート")
    lines.append("")
    lines.append(f"**日時:** {TIME_STR}")
    lines.append("")

    # ストア状態
    lines.append("## ストア状態")
    lines.append("")
    for f in info:
        if "Active:" in f["message"]:
            lines.append(f"- {f['message']}")
    lines.append("")

    # === 6区分タスクステータス ===
    completed_infra, improvement_phase = _classify_task_status(all_findings)

    lines.append("## 📊 タスクステータス（6区分）")
    lines.append("")

    # 1. 実施済み
    lines.append("### 1. 実施済み（基盤構築完了）")
    lines.append("")
    for item in completed_infra:
        lines.append(f"- ✅ {item}")
    lines.append("")

    # 2. 実施済み（活用改善フェーズ）
    lines.append("### 2. 実施済み（活用改善フェーズ）")
    lines.append("")
    for item in improvement_phase:
        lines.append(f"- 🔄 {item}")
    lines.append("")

    # 3. 進行中
    in_progress = [f for f in all_findings if "progress" in f.get("message", "").lower() or "running" in f.get("message", "").lower()]
    lines.append(f"### 3. 進行中（{len(in_progress)}件）")
    lines.append("")
    if in_progress:
        for f in in_progress[:5]:
            lines.append(f"- 🔨 [{f.get('agent', '')}] {f['message'][:80]}")
    else:
        lines.append("- なし")
    lines.append("")

    # 4. 未着手
    lines.append(f"### 4. 未着手")
    lines.append("")
    # pending_tasks.json から未着手を抽出
    task_findings = [f for f in all_findings if "pending tasks" in f.get("message", "").lower()]
    if task_findings:
        for f in task_findings:
            for d in f.get("details", [])[:5]:
                lines.append(f"- ⬜ {d}")
    else:
        lines.append("- なし")
    lines.append("")

    # 5. 保留
    hold_findings = [f for f in all_findings if "on_hold" in f.get("message", "").lower() or "waiting" in f.get("message", "").lower()]
    lines.append(f"### 5. 保留（{len(hold_findings)}件）")
    lines.append("")
    if hold_findings:
        for f in hold_findings[:3]:
            lines.append(f"- ⏸️ [{f.get('agent', '')}] {f['message'][:80]}")
    else:
        lines.append("- なし")
    lines.append("")

    # 6. 改善提案のみ
    lines.append(f"### 6. 改善提案のみ（{len(action)}件）")
    lines.append("")
    if action:
        for f in action[:5]:
            lines.extend(_format_finding_line(f))
        if len(action) > 5:
            lines.append(f"  ...他 {len(action) - 5}件")
    else:
        lines.append("- なし")
    lines.append("")

    # === 従来セクション ===

    # 🔴 要対応
    lines.append(f"## 🔴 要対応（{len(critical)}件）")
    lines.append("")
    if critical:
        for f in critical:
            lines.extend(_format_finding_line(f))
    else:
        lines.append("- なし")
    lines.append("")

    # 🚀 今日やると売上に効く改善
    lines.append(f"## 🚀 今日やると売上に効く改善（{len(suggestion)}件）")
    lines.append("")
    if suggestion:
        agents_order = [
            "growth-foundation", "store-setup", "price-auditor",
            "catalog-migration-planner", "fulfillment-ops",
            "content-strategist", "competitive-intelligence",
            "sns-manager", "blog-analyst", "self-learning",
        ]
        for agent in agents_order:
            agent_findings = [f for f in suggestion if f.get("agent") == agent]
            if agent_findings:
                lines.append(f"### {agent}")
                lines.append("")
                for f in agent_findings:
                    lines.extend(_format_finding_line(f))
                lines.append("")
    else:
        lines.append("- なし")
        lines.append("")

    # 💡 中期改善候補
    lines.append(f"## 💡 中期改善候補（{len(medium_term)}件）")
    lines.append("")
    if medium_term:
        agents_order = [
            "growth-foundation", "store-setup", "price-auditor",
            "catalog-migration-planner", "fulfillment-ops",
            "content-strategist", "competitive-intelligence",
            "sns-manager", "blog-analyst",
        ]
        for agent in agents_order:
            agent_findings = [f for f in medium_term if f.get("agent") == agent]
            if agent_findings:
                lines.append(f"### {agent}")
                lines.append("")
                for f in agent_findings:
                    lines.extend(_format_finding_line(f))
                lines.append("")
    else:
        lines.append("- なし")
        lines.append("")

    # ✓ 異常なし
    lines.append(f"## ✓ 異常なし（{len(ok)}件）")
    lines.append("")
    if ok:
        for f in ok:
            lines.append(f"- {f['message']}")
    else:
        lines.append("- （チェック項目なし）")
    lines.append("")

    # 💰 eBay→Shopify 価格同期サマリ
    price_findings = [f for f in all_findings if f.get("agent") == "price-auditor" and "sync" in f.get("message", "").lower()]
    if price_findings:
        lines.append("## 💰 eBay→Shopify 価格同期")
        lines.append("")
        for f in price_findings:
            lines.append(f"- {f['message']}")
            for d in f.get("details", []):
                lines.append(f"  - {d}")
        lines.append("")

    # 🎨 UI/UX 競合比較サマリ
    uiux_findings = [f for f in all_findings if "UI/UX" in f.get("message", "") or "ui/ux" in f.get("message", "").lower() or "Competitive insights" in f.get("message", "")]
    if uiux_findings:
        lines.append("## 🎨 UI/UX 競合比較")
        lines.append("")
        for f in uiux_findings:
            icon = {"action": "実装候補", "medium_term": "改善候補", "ok": "OK", "suggestion": "要対応"}.get(f["type"], "情報")
            lines.append(f"- [{icon}] {f['message']}")
            for d in f.get("details", [])[:3]:
                lines.append(f"  - {d}")
        lines.append("")

    # 💰 売上改善分析
    sales_findings = [f for f in all_findings if any(kw in f.get("message", "") for kw in [
        "Proposal outcomes", "Unsold analysis", "CRO audit", "Merchandising",
        "Navigation audit", "DTC transfer", "Retention",
    ])]
    if sales_findings:
        lines.append("## 💰 売上改善分析")
        lines.append("")
        for f in sales_findings:
            icon = {"action": "🔴", "suggestion": "⚠️", "info": "ℹ️", "ok": "✅"}.get(f["type"], "📋")
            lines.append(f"### {icon} {f['message']}")
            lines.append("")
            for d in f.get("details", []):
                lines.append(f"- {d}")
            lines.append("")

    # 🎨 デザイン監査
    design_findings = [f for f in all_findings if any(kw in f.get("message", "") for kw in ["design audit", "Design direction", "Design improvement", "Competitor design"])]
    if design_findings:
        lines.append("## 🎨 デザイン監査")
        lines.append("")
        for f in design_findings:
            icon = {"action": "🔴", "suggestion": "⚠️", "info": "ℹ️", "ok": "✅"}.get(f["type"], "📋")
            lines.append(f"### {icon} {f['message']}")
            lines.append("")
            for d in f.get("details", []):
                lines.append(f"- {d}")
            lines.append("")

    # 🔗 状態整合性監査
    consistency_findings = [f for f in all_findings if "State consistency" in f.get("message", "")]
    if consistency_findings:
        lines.append("## 🔗 状態整合性監査")
        lines.append("")
        for f in consistency_findings:
            lines.append(f"### {f['message']}")
            lines.append("")
            for d in f.get("details", []):
                lines.append(f"- {d}")
            lines.append("")

    # 🐛 バグ・異常監査
    bug_findings = [f for f in all_findings if "Bug audit" in f.get("message", "") or "Quality anomal" in f.get("message", "")]
    if bug_findings:
        lines.append("## 🐛 バグ・異常監査")
        lines.append("")
        for f in bug_findings:
            icon = {"critical": "🔴", "suggestion": "⚠️", "info": "ℹ️", "ok": "✅"}.get(f["type"], "📋")
            lines.append(f"### {icon} {f['message']}")
            lines.append("")
            for d in f.get("details", []):
                lines.append(f"- {d}")
            lines.append("")

    # 🧠 自己学習機能監査
    learning_audit = [f for f in all_findings if "Self-learning" in f.get("message", "") or "Learning accuracy" in f.get("message", "") or "Learning logs" in f.get("message", "") or "Learning event" in f.get("message", "") or "API audit" in f.get("message", "") or "Self-learning improvement" in f.get("message", "")]
    if learning_audit:
        lines.append("## 🧠 自己学習機能監査")
        lines.append("")
        for f in learning_audit:
            icon = {"action": "🔴", "suggestion": "⚠️", "info": "ℹ️"}.get(f["type"], "📋")
            lines.append(f"### {icon} {f['message']}")
            lines.append("")
            for d in f.get("details", []):
                lines.append(f"- {d}")
            lines.append("")

    # 📊 データ充足監査
    data_findings = [f for f in all_findings if "Data sufficiency" in f.get("message", "") or "Data gaps" in f.get("message", "") or "Priority data gaps" in f.get("message", "")]
    if data_findings:
        lines.append("## 📊 データ充足監査")
        lines.append("")
        for f in data_findings:
            icon = {"suggestion": "⚠️", "action": "🔴", "info": "ℹ️"}.get(f["type"], "📋")
            lines.append(f"### {icon} {f['message']}")
            lines.append("")
            for d in f.get("details", []):
                lines.append(f"- {d}")
            lines.append("")

    # 🔍 リサーチ監査
    research_findings = [f for f in all_findings if "Research" in f.get("message", "") or "research" in f.get("message", "").lower() or "Business fit" in f.get("message", "") or "Deviation" in f.get("message", "") or "self-review" in f.get("message", "").lower()]
    if research_findings:
        lines.append("## 🔍 リサーチ監査")
        lines.append("")
        for f in research_findings:
            icon = {"critical": "🚨", "suggestion": "⚠️", "info": "ℹ️"}.get(f["type"], "📋")
            lines.append(f"### {icon} {f['message']}")
            lines.append("")
            for d in f.get("details", []):
                lines.append(f"- {d}")
            lines.append("")

    # 🔁 実行証跡
    evidence_findings = [f for f in all_findings if f.get("message", "").startswith(("Learning summary", "PDCA progress", "Cross-agent activity", "State files", "Self-check"))]
    if evidence_findings:
        lines.append("## 🔁 実行証跡")
        lines.append("")
        for f in evidence_findings:
            lines.append(f"### {f['message']}")
            lines.append("")
            for d in f.get("details", []):
                lines.append(f"- {d}")
            lines.append("")

    # 📌 未実装タスク
    task_findings = [f for f in all_findings if "pending tasks" in f.get("message", "").lower()]
    if task_findings:
        lines.append("## 📌 未実装タスク")
        lines.append("")
        for f in task_findings:
            lines.append(f"- {f['message']}")
            for d in f.get("details", []):
                lines.append(f"  - {d}")
        lines.append("")

    # 外部導線サマリ
    hd_findings = [
        f for f in all_findings if "hd-bodyscience" in f.get("message", "").lower()
    ]
    ebay_sns_findings = [
        f for f in all_findings if "eBay SNS" in f.get("message", "")
    ]
    shopify_sns_findings = [
        f for f in all_findings
        if "Shopify 専用 SNS" in f.get("message", "")
    ]
    has_external = hd_findings or ebay_sns_findings or shopify_sns_findings
    if has_external:
        lines.append("## 外部導線サマリ")
        lines.append("")
        if hd_findings:
            lines.append("### hd-bodyscience.com")
            lines.append("")
            for f in hd_findings:
                icon = {"ok": "OK", "suggestion": "要対応", "medium_term": "改善候補", "info": "情報"}.get(f["type"], "")
                lines.append(f"- [{icon}] {f['message']}")
            lines.append("")
        if ebay_sns_findings:
            lines.append("### eBay SNS プロフィール")
            lines.append("")
            for f in ebay_sns_findings:
                icon = {"ok": "OK", "suggestion": "要対応"}.get(f["type"], "")
                lines.append(f"- [{icon}] {f['message']}")
            lines.append("")
        if shopify_sns_findings:
            lines.append("### Shopify 専用 SNS")
            lines.append("")
            for f in shopify_sns_findings:
                icon = {"ok": "OK", "medium_term": "改善候補"}.get(f["type"], "")
                lines.append(f"- [{icon}] {f['message']}")
            lines.append("")

    return "\n".join(lines)


def generate_chatwork_message(all_findings):
    """Chatwork 要約メッセージを生成（改善提案型）"""
    critical, suggestion, medium_term, info, ok, action = classify_findings(all_findings)

    lines = []
    lines.append(
        f"[info][title]HD Toys Store Japan 日次レポート（{DATE_STR}）[/title]"
    )

    # ストア状態
    for f in info:
        if "Active:" in f["message"]:
            lines.append(f["message"])

    # 🔴 要対応
    if critical:
        lines.append("")
        lines.append(f"🔴 要対応（{len(critical)}件）")
        for f in critical:
            lines.append(f"  {f['message']}")

    # 🚀 売上改善
    if suggestion:
        lines.append("")
        lines.append(f"🚀 今日やると売上に効く改善（{len(suggestion)}件）")
        for f in suggestion[:5]:
            agent = f.get("agent", "")
            lines.append(f"  [{agent}] {f['message']}")
        if len(suggestion) > 5:
            lines.append(f"  ...他 {len(suggestion) - 5}件（詳細はレポート参照）")

    # 💡 中期
    if medium_term:
        lines.append("")
        lines.append(f"💡 中期改善候補（{len(medium_term)}件）")
        for f in medium_term[:3]:
            agent = f.get("agent", "")
            lines.append(f"  [{agent}] {f['message']}")
        if len(medium_term) > 3:
            lines.append(f"  ...他 {len(medium_term) - 3}件")

    # 📝 アクション
    if action:
        lines.append("")
        lines.append("📝 今日のアクション提案（%d件）" % len(action))
        for f in action[:2]:
            lines.append("  %s" % f["message"][:70])

    # ✓ 異常なし
    if not critical and not suggestion:
        lines.append("")
        lines.append("✓ 異常なし・改善候補なし")
    elif ok:
        lines.append("")
        lines.append(f"✓ 正常: {len(ok)}件")

    # 詳細レポートへの導線
    lines.append("")
    if ACTIONS_URL:
        lines.append("■ 詳細レポート")
        lines.append(ACTIONS_URL)
        lines.append("↑ ページ下部「Artifacts」→ daily-report-* をダウンロード")
    else:
        lines.append("■ 詳細レポート: ops/monitoring/reports/ に保存済み")

    lines.append("[/info]")

    return "\n".join(lines)


def send_chatwork(message):
    """Chatwork にメッセージを送信"""
    if not CHATWORK_TOKEN or not CHATWORK_ROOM:
        print("[SKIP] Chatwork: トークンまたはルーム ID が未設定")
        return False

    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM}/messages"
    headers = {
        "X-ChatWorkToken": CHATWORK_TOKEN,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"body": message}

    try:
        resp = requests.post(url, headers=headers, data=data, timeout=30)
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Chatwork 送信失敗: {e}")
        return False

    if resp.status_code == 200:
        print("[OK] Chatwork に通知を送信しました")
        return True
    else:
        print(f"[ERROR] Chatwork 送信失敗: HTTP {resp.status_code} {resp.text[:200]}")
        return False


# ============================================================
# メイン処理
# ============================================================

def main():
    print("=" * 60)
    print("  HD Toys Store Japan 日次レポート（改善提案型）")
    print(f"  {TIME_STR}")
    print("=" * 60)
    print()

    # 接続テスト
    if not STORE or not TOKEN:
        print("[ERROR] SHOPIFY_STORE / SHOPIFY_ACCESS_TOKEN が未設定")
        sys.exit(1)

    resp = shopify_get("shop.json")
    if not resp or resp.status_code != 200:
        print("[ERROR] Shopify API 接続失敗")
        sys.exit(1)

    shop = resp.json()["shop"]
    print(f"[OK] {shop['name']} ({shop['myshopify_domain']})")
    print()

    # データ取得
    all_findings = []

    print("[INFO] 商品データ取得中...")
    products = shopify_get_all_products("active")
    # Active 0件と API 取得失敗を区別
    active_count_resp = shopify_get("products/count.json?status=active")
    if active_count_resp and active_count_resp.status_code == 200:
        expected_count = active_count_resp.json().get("count", 0)
        if expected_count > 0 and len(products) == 0:
            all_findings.append({
                "type": "critical", "agent": "store-setup",
                "message": f"Active 商品の取得に失敗（API は {expected_count}件を報告しているが取得0件）",
            })
        elif expected_count == 0:
            all_findings.append({
                "type": "critical", "agent": "store-setup",
                "message": "Active 商品が0件（全商品が Draft または削除されている可能性）",
            })
    else:
        all_findings.append({
            "type": "critical", "agent": "store-setup",
            "message": "Active 商品数の API 確認に失敗",
        })
    print(f"  Active products: {len(products)}")

    pages_resp = shopify_get("pages.json?limit=50")
    if pages_resp and pages_resp.status_code == 200:
        pages = pages_resp.json().get("pages", [])
    else:
        pages = []
        all_findings.append({
            "type": "critical", "agent": "store-setup",
            "message": "ページ情報の取得に失敗",
        })
    print(f"  Pages: {len(pages)}")
    print()

    # --- 監視 + 改善提案の実行 ---

    print("[INFO] store-setup 点検...")
    all_findings.extend(inspect_store_setup(products, pages))

    print("[INFO] price-auditor 点検...")
    all_findings.extend(inspect_price_auditor(products))

    print("[INFO] eBay→Shopify 価格同期...")
    all_findings.extend(sync_prices())

    print("[INFO] eBay→Shopify 画像同期...")
    all_findings.extend(sync_images())

    print("[INFO] catalog-migration-planner 点検...")
    all_findings.extend(inspect_catalog(products))

    print("[INFO] fulfillment-ops 点検...")
    all_findings.extend(inspect_fulfillment(products))

    print("[INFO] growth-foundation SEO 点検...")
    all_findings.extend(inspect_seo(products))

    print("[INFO] Collection カバレッジ点検...")
    all_findings.extend(inspect_collection_coverage(products))

    print("[INFO] Draft 昇格候補チェック...")
    all_findings.extend(inspect_draft_readiness())

    print("[INFO] hd-bodyscience.com 導線チェック...")
    all_findings.extend(inspect_hd_bodyscience())

    print("[INFO] SNS アカウント状況チェック...")
    all_findings.extend(inspect_sns_status())

    print("[INFO] GA4 アクセスデータ取得...")
    all_findings.extend(inspect_ga4())

    print("[INFO] Search Console データ取得...")
    all_findings.extend(inspect_search_console())

    # --- アクション提案（action_suggestions.py）---
    print("[INFO] アクション提案を生成中...")
    wp_posts_data = []
    wp_categories_data = []
    try:
        _wp_api = "https://hd-bodyscience.com/wp-json/wp/v2"
        _wp_headers = {"User-Agent": "HD-Toys-Store-DailyInspection/1.0"}
        _wp_resp = requests.get(
            _wp_api + "/posts?per_page=20&_fields=id,title,date,link,categories,content",
            headers=_wp_headers, timeout=15,
        )
        if _wp_resp.status_code == 200:
            wp_posts_data = _wp_resp.json()
        _wp_cat_resp = requests.get(
            _wp_api + "/categories?per_page=100&_fields=id,name,slug,count",
            headers=_wp_headers, timeout=15,
        )
        if _wp_cat_resp.status_code == 200:
            wp_categories_data = _wp_cat_resp.json()
    except Exception:
        pass

    all_findings.extend(generate_all_suggestions(products, wp_posts_data, wp_categories_data))

    print("[INFO] 設定最適化 + 分析設定チェック...")
    all_findings.extend(run_all_audits(products))

    print("[INFO] 競合比較チェック...")
    all_findings.extend(run_competitive_analysis(products))

    print("[INFO] デザイン監査...")
    all_findings.extend(run_design_audit(products, wp_posts_data, all_findings))

    print("[INFO] 売上改善分析...")
    all_findings.extend(run_sales_optimization(products, wp_posts_data, all_findings))

    print("[INFO] SNS 最適化ループ...")
    all_findings.extend(run_sns_optimization())

    print("[INFO] 未実装タスク追跡...")
    all_findings.extend(generate_task_report())

    print()

    # レポート生成
    print("[INFO] 横断フィードバック生成...")
    all_findings.extend(generate_cross_feedback(all_findings))

    print("[INFO] エージェント学習サマリ...")
    all_findings.extend(generate_learning_summary(all_findings))

    print("[INFO] エージェント負荷チェック...")
    print("[INFO] ブログ記事 PDCA...")
    print("[INFO] eBay 売れ筋分析...")
    all_findings.extend(run_ebay_sales_analysis(products))

    print("[INFO] 採用商品PDCA + 商品ページ競合比較...")
    all_findings.extend(run_product_pdca(products))

    all_findings.extend(run_blog_automation(products, wp_posts_data, wp_categories_data))

    all_findings.extend(check_agent_load(all_findings))

    print("[INFO] 実験管理チェック...")
    all_findings.extend(check_experiments())
    auto_register_experiments(all_findings)

    print("[INFO] リサーチ監査...")
    all_findings.extend(generate_research_report(all_findings))

    print("[INFO] データ充足監査...")
    all_findings.extend(generate_data_sufficiency_report(all_findings))

    print("[INFO] 自己学習機能監査...")
    all_findings.extend(generate_self_learning_audit(all_findings))

    print("[INFO] バグ・異常監査...")
    all_findings.extend(generate_bug_audit(all_findings))

    print("[INFO] 実行証跡生成...")
    all_findings.extend(generate_execution_evidence(all_findings))

    # 状態整合性監査（台帳ベース）
    print("[INFO] 状態整合性監査...")
    all_findings.extend(generate_consistency_audit(all_findings))

    # 完了済みタスクの誤検知を除去
    print("[INFO] 誤検知フィルタリング...")
    all_findings, corrected = filter_findings_by_ledger(all_findings)
    if corrected:
        print("  Suppressed %d false positives" % len(corrected))

    print("[INFO] レポート生成...")

    md_report = generate_markdown_report(all_findings, shop)
    md_path = os.path.join(REPORTS_DIR, f"report_{DATE_STR}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    print(f"  Markdown: {md_path}")

    json_data = {
        "date": DATE_STR,
        "timestamp": TIME_STR,
        "store": shop["name"],
        "findings": all_findings,
    }
    json_path = os.path.join(REPORTS_DIR, f"report_{DATE_STR}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    print(f"  JSON: {json_path}")

    # Chatwork 通知
    print()
    cw_message = generate_chatwork_message(all_findings)
    send_chatwork(cw_message)

    # コンソールサマリ
    print()
    critical, suggestion, medium_term, info, ok, action = classify_findings(all_findings)
    print(f"  🔴 要対応: {len(critical)}件")
    print(f"  🚀 売上改善: {len(suggestion)}件")
    print(f"  💡 中期改善: {len(medium_term)}件")
    print(f"  📝 アクション: {len(action)}件")
    print(f"  ✓ 正常: {len(ok)}件")


if __name__ == "__main__":
    main()
