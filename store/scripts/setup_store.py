# ============================================================
# Shopify ストア初期設定スクリプト
#
# 【役割】
#   API 経由で以下を設定する:
#   1. 必須ページ作成（Shipping Policy, Return Policy, FAQ, About Us, 特定商取引法）
#   2. Automated Collection 作成（7カテゴリ + New Arrivals + Sale）
#   3. ナビゲーションメニュー設定
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python store/scripts/setup_store.py
#
# 【注意】
#   - 商品の公開状態は変更しない（draft のまま）
#   - eBay 側には一切変更を加えない
# ============================================================

import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

STORE = os.getenv("SHOPIFY_STORE", "")
TOKEN_FILE = os.path.join(PROJECT_ROOT, ".shopify_token.json")
API_VERSION = "2026-04"

# API レート制限対策
REQUEST_INTERVAL = 0.5


def load_token():
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("access_token", "")


def api_url(endpoint):
    return f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/{endpoint}"


def graphql_url():
    return f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/graphql.json"


def headers(token):
    return {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }


def api_get(token, endpoint):
    resp = requests.get(api_url(endpoint), headers=headers(token))
    time.sleep(REQUEST_INTERVAL)
    return resp


def api_post(token, endpoint, data):
    resp = requests.post(api_url(endpoint), headers=headers(token), json=data)
    time.sleep(REQUEST_INTERVAL)
    return resp


def api_put(token, endpoint, data):
    resp = requests.put(api_url(endpoint), headers=headers(token), json=data)
    time.sleep(REQUEST_INTERVAL)
    return resp


def graphql(token, query, variables=None):
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = requests.post(graphql_url(), headers=headers(token), json=payload)
    time.sleep(REQUEST_INTERVAL)
    return resp


# ============================================================
# 1. 必須ページ作成
# ============================================================

PAGES = [
    {
        "title": "Shipping Policy",
        "body_html": """<h2>Shipping Policy</h2>

<p>All items ship directly from Japan.</p>

<h3>Shipping Methods</h3>
<p>We use tracked international shipping services (Japan Post, FedEx, or DHL depending on the item size and destination).</p>

<h3>Estimated Delivery Times</h3>
<ul>
  <li>United States: 7–14 business days</li>
  <li>United Kingdom / Canada / Australia: 7–14 business days</li>
  <li>Rest of World: 10–21 business days</li>
</ul>

<h3>Shipping Costs</h3>
<p>Shipping costs are calculated at checkout based on the weight of your order and your delivery address.</p>

<h3>Tracking</h3>
<p>A tracking number will be provided for every order via email once your item has been shipped.</p>

<h3>Important Notice</h3>
<p>Import duties, taxes, and customs fees are not included in the item price or shipping cost. These charges are the buyer's responsibility and vary by country. Please check with your local customs office for more information.</p>""",
    },
    {
        "title": "Return Policy",
        "body_html": """<h2>Return Policy</h2>

<p>We want you to be happy with your purchase. If there is an issue with your order, please contact us within 14 days of receiving your item.</p>

<h3>Eligible Returns</h3>
<ul>
  <li>Item significantly different from the listing description</li>
  <li>Item damaged during shipping</li>
  <li>Wrong item received</li>
</ul>

<h3>Not Eligible for Return</h3>
<ul>
  <li>Buyer's remorse or change of mind</li>
  <li>Minor wear consistent with pre-owned condition as described</li>
</ul>

<h3>Return Process</h3>
<ol>
  <li>Contact us at adstart.corporate@gmail.com with your order number and photos of the issue.</li>
  <li>We will review your request within 2 business days.</li>
  <li>If approved, we will provide return shipping instructions.</li>
  <li>Refund will be processed within 5 business days after we receive the returned item.</li>
</ol>

<h3>Return Shipping</h3>
<ul>
  <li>If the return is due to our error: we will cover return shipping costs.</li>
  <li>If the return is due to buyer's preference: buyer is responsible for return shipping costs.</li>
</ul>""",
    },
    {
        "title": "FAQ",
        "body_html": """<h2>Frequently Asked Questions</h2>

<h3>Are your items authentic?</h3>
<p>Yes. All items are sourced directly from Japan and are 100% authentic.</p>

<h3>What does the condition rating mean?</h3>
<p>We use the following condition scale:</p>
<ul>
  <li><strong>Mint:</strong> Brand new or like new, with original packaging</li>
  <li><strong>Near Mint:</strong> Excellent condition with minimal signs of use</li>
  <li><strong>Good:</strong> Normal signs of use, fully functional</li>
  <li><strong>Fair:</strong> Noticeable wear, but still displayable/functional</li>
</ul>

<h3>Do I have to pay customs/import duties?</h3>
<p>Import duties, taxes, and customs fees are not included in the price and are the buyer's responsibility. These charges vary by country.</p>

<h3>How long does shipping take?</h3>
<p>Estimated delivery is 7–14 business days for most countries. Please see our Shipping Policy for details.</p>

<h3>Can I cancel or change my order?</h3>
<p>Please contact us as soon as possible. If the item has not yet been shipped, we can accommodate changes or cancellations.</p>

<h3>Do you ship worldwide?</h3>
<p>Yes, we ship to most countries. Shipping costs are calculated at checkout.</p>

<h3>How can I contact you?</h3>
<p>Please use our Contact page or email us at adstart.corporate@gmail.com.</p>""",
    },
    {
        "title": "About Us",
        "body_html": """<h2>About HD Toys Store Japan</h2>

<p>We are a Japan-based shop specializing in authentic Japanese figures, toys, and collectibles.</p>

<p>Our collection includes action figures, scale figures, trading cards, vintage toys, video games, and more — all sourced directly from Japan.</p>

<p>Every item is carefully inspected and honestly described so you know exactly what you're getting.</p>

<p>We ship worldwide with tracking from Japan.</p>""",
    },
    {
        "title": "Legal Notice (特定商取引法に基づく表記)",
        "body_html": """<h2>Legal Notice / 特定商取引法に基づく表記</h2>

<table>
  <tr><td><strong>事業者名 / Business Name</strong></td><td>原田充</td></tr>
  <tr><td><strong>代表者名 / Representative</strong></td><td>原田充</td></tr>
  <tr><td><strong>所在地 / Address</strong></td><td>〒182-0034 東京都調布市下石原2-32-4</td></tr>
  <tr><td><strong>電話番号 / Phone</strong></td><td>080-6646-1029</td></tr>
  <tr><td><strong>メール / Email</strong></td><td>adstart.corporate@gmail.com</td></tr>
  <tr><td><strong>販売価格 / Prices</strong></td><td>As displayed on each product page (USD)</td></tr>
  <tr><td><strong>送料 / Shipping</strong></td><td>Calculated at checkout based on weight and destination</td></tr>
  <tr><td><strong>支払方法 / Payment</strong></td><td>Credit Card, PayPal</td></tr>
  <tr><td><strong>支払時期 / Payment Timing</strong></td><td>Charged at the time of order</td></tr>
  <tr><td><strong>商品の引渡時期 / Delivery</strong></td><td>Shipped within 7 business days after payment confirmation</td></tr>
  <tr><td><strong>返品 / Returns</strong></td><td>See our Return Policy page</td></tr>
</table>""",
    },
]


def create_pages(token):
    """必須ページを作成する"""
    print("=" * 60)
    print("  1. 必須ページ作成")
    print("=" * 60)
    print()

    # 既存ページを確認
    resp = api_get(token, "pages.json?limit=50")
    existing = {p["title"]: p["id"] for p in resp.json().get("pages", [])}

    created = 0
    skipped = 0

    for page_data in PAGES:
        title = page_data["title"]
        if title in existing:
            print(f"  [スキップ] {title}（既に存在）")
            skipped += 1
            continue

        resp = api_post(token, "pages.json", {"page": page_data})
        if resp.status_code in (200, 201):
            print(f"  [OK] {title}")
            created += 1
        else:
            print(f"  [エラー] {title}: HTTP {resp.status_code} - {resp.text[:100]}")

    print()
    print(f"  作成: {created} / スキップ: {skipped}")
    return created


# ============================================================
# 2. Automated Collection 作成
# ============================================================

COLLECTIONS = [
    # (タイトル, ルールの列, ルールの条件, ルールの値)
    ("Action Figures", "tag", "equals", "Action Figures"),
    ("Figures & Statues", "tag", "equals", "Scale Figures"),
    ("Plush & Soft Toys", "tag", "equals", "Plush & Soft Toys"),
    ("Trading Cards", "tag", "equals", "Trading Cards"),
    ("Video Games", "tag", "equals", "Video Games"),
    ("Media & Books", "tag", "equals", "Media & Books"),
    ("Electronic Toys", "tag", "equals", "Electronic Toys"),
]

# 特殊コレクション（New Arrivals はタグではなく作成日ベース）
# Shopify REST API では作成日条件の Smart Collection は作れないため、
# New Arrivals はタグベースで代用する


def create_collections(token):
    """Automated Collection を作成する"""
    print("=" * 60)
    print("  2. Automated Collection 作成")
    print("=" * 60)
    print()

    # 既存コレクションを確認
    resp = api_get(token, "smart_collections.json?limit=50")
    existing_smart = {c["title"]: c["id"] for c in resp.json().get("smart_collections", [])}

    resp = api_get(token, "custom_collections.json?limit=50")
    existing_custom = {c["title"]: c["id"] for c in resp.json().get("custom_collections", [])}

    existing = {**existing_smart, **existing_custom}
    created = 0
    skipped = 0

    # タグベースの Smart Collection
    for title, column, relation, condition in COLLECTIONS:
        if title in existing:
            print(f"  [スキップ] {title}（既に存在）")
            skipped += 1
            continue

        data = {
            "smart_collection": {
                "title": title,
                "rules": [
                    {
                        "column": column,
                        "relation": relation,
                        "condition": condition,
                    }
                ],
                "published": True,
            }
        }
        resp = api_post(token, "smart_collections.json", data)
        if resp.status_code in (200, 201):
            print(f"  [OK] {title} (tag = {condition})")
            created += 1
        else:
            print(f"  [エラー] {title}: HTTP {resp.status_code} - {resp.text[:100]}")

    # Sale コレクション（手動）
    if "Sale" not in existing:
        data = {
            "custom_collection": {
                "title": "Sale",
                "published": True,
            }
        }
        resp = api_post(token, "custom_collections.json", data)
        if resp.status_code in (200, 201):
            print(f"  [OK] Sale (manual collection)")
            created += 1
        else:
            print(f"  [エラー] Sale: HTTP {resp.status_code}")
    else:
        print(f"  [スキップ] Sale（既に存在）")
        skipped += 1

    print()
    print(f"  作成: {created} / スキップ: {skipped}")
    return created


# ============================================================
# 3. ナビゲーションメニュー設定（GraphQL）
# ============================================================

def setup_navigation(token):
    """メインメニューとフッターメニューを設定する"""
    print("=" * 60)
    print("  3. ナビゲーションメニュー確認")
    print("=" * 60)
    print()

    # メニュー一覧を取得
    query = """
    {
      menus(first: 10) {
        edges {
          node {
            id
            title
            handle
            itemsCount
          }
        }
      }
    }
    """
    resp = graphql(token, query)
    if resp.status_code != 200:
        print(f"  [エラー] メニュー取得失敗: HTTP {resp.status_code}")
        return

    data = resp.json()
    menus = data.get("data", {}).get("menus", {}).get("edges", [])

    print("  既存メニュー:")
    for edge in menus:
        node = edge["node"]
        print(f"    {node['title']} (handle: {node['handle']}, items: {node['itemsCount']})")

    print()
    print("  ※ メニュー項目の追加は GraphQL menuUpdate で行います。")
    print("    Collection 作成後にメニューを更新します。")


# ============================================================
# 4. メニュー更新
# ============================================================

def update_menus(token):
    """メインメニューとフッターメニューにリンクを追加する"""
    print("=" * 60)
    print("  4. ナビゲーションメニュー更新")
    print("=" * 60)
    print()

    # コレクション一覧を取得してIDを把握
    resp = api_get(token, "smart_collections.json?limit=50")
    smart_cols = {c["title"]: c for c in resp.json().get("smart_collections", [])}

    resp = api_get(token, "custom_collections.json?limit=50")
    custom_cols = {c["title"]: c for c in resp.json().get("custom_collections", [])}

    all_cols = {**smart_cols, **custom_cols}

    # ページ一覧を取得
    resp = api_get(token, "pages.json?limit=50")
    pages = {p["title"]: p for p in resp.json().get("pages", [])}

    # メニュー一覧を取得
    query = """
    {
      menus(first: 10) {
        edges {
          node {
            id
            title
            handle
          }
        }
      }
    }
    """
    resp = graphql(token, query)
    menus_data = resp.json().get("data", {}).get("menus", {}).get("edges", [])
    menus = {edge["node"]["handle"]: edge["node"] for edge in menus_data}

    # --- メインメニュー ---
    main_menu = menus.get("main-menu")
    if main_menu:
        main_menu_id = main_menu["id"]
        print(f"  メインメニュー: {main_menu_id}")

        # コレクションへのリンクを構築
        items = []
        menu_collections = [
            "Action Figures", "Figures & Statues", "Plush & Soft Toys",
            "Trading Cards", "Video Games", "Media & Books", "Electronic Toys",
        ]
        for col_name in menu_collections:
            if col_name in all_cols:
                col = all_cols[col_name]
                items.append({
                    "title": col_name,
                    "type": "HTTP",
                    "url": f"https://{STORE}.myshopify.com/collections/{col['handle']}",
                })

        if items:
            mutation = """
            mutation menuUpdate($id: ID!, $items: [MenuItemCreateInput!]!) {
              menuUpdate(id: $id, items: $items) {
                menu {
                  id
                  title
                }
                userErrors {
                  field
                  message
                }
              }
            }
            """
            variables = {"id": main_menu_id, "items": items}
            resp = graphql(token, mutation, variables)
            result = resp.json()
            errors = result.get("data", {}).get("menuUpdate", {}).get("userErrors", [])
            if errors:
                print(f"  [警告] メインメニュー更新エラー: {errors}")
            else:
                print(f"  [OK] メインメニュー更新: {len(items)} 件のコレクションリンク")
    else:
        print("  [スキップ] メインメニューが見つかりません")

    # --- フッターメニュー ---
    footer_menu = menus.get("footer")
    if footer_menu:
        footer_menu_id = footer_menu["id"]
        print(f"  フッターメニュー: {footer_menu_id}")

        items = []
        footer_pages = [
            "Shipping Policy", "Return Policy", "FAQ", "About Us",
            "Legal Notice (特定商取引法に基づく表記)",
        ]
        for page_title in footer_pages:
            if page_title in pages:
                p = pages[page_title]
                display_title = page_title
                if "特定商取引法" in page_title:
                    display_title = "Legal Notice"
                items.append({
                    "title": display_title,
                    "type": "HTTP",
                    "url": f"https://{STORE}.myshopify.com/pages/{p['handle']}",
                })

        if items:
            mutation = """
            mutation menuUpdate($id: ID!, $items: [MenuItemCreateInput!]!) {
              menuUpdate(id: $id, items: $items) {
                menu {
                  id
                  title
                }
                userErrors {
                  field
                  message
                }
              }
            }
            """
            variables = {"id": footer_menu_id, "items": items}
            resp = graphql(token, mutation, variables)
            result = resp.json()
            errors = result.get("data", {}).get("menuUpdate", {}).get("userErrors", [])
            if errors:
                print(f"  [警告] フッターメニュー更新エラー: {errors}")
            else:
                print(f"  [OK] フッターメニュー更新: {len(items)} 件のページリンク")
    else:
        print("  [スキップ] フッターメニューが見つかりません")

    print()


# ============================================================
# メイン処理
# ============================================================

def main():
    print()
    print("=" * 60)
    print("  Shopify ストア初期設定")
    print("  ※ 商品の公開状態は変更しません")
    print("  ※ eBay には一切変更を加えません")
    print("=" * 60)
    print()

    token = load_token()
    if not token:
        print("[エラー] トークンがありません。shopify_auth.py を実行してください。")
        sys.exit(1)

    # 接続テスト
    ok, resp = test_token(token)
    if not ok:
        print(f"[エラー] API 接続失敗: HTTP {resp.status_code}")
        sys.exit(1)
    shop = resp.json().get("shop", {})
    print(f"[OK] 接続確認: {shop.get('name', '?')} ({shop.get('myshopify_domain', '?')})")
    print()

    # 1. ページ作成
    create_pages(token)
    print()

    # 2. Collection 作成
    create_collections(token)
    print()

    # 3. ナビゲーション確認
    setup_navigation(token)

    # 4. メニュー更新
    update_menus(token)

    # --- サマリ ---
    print("=" * 60)
    print("  設定完了サマリ")
    print("=" * 60)
    print()

    # ページ一覧
    resp = api_get(token, "pages.json?limit=50")
    pages = resp.json().get("pages", [])
    print(f"  --- 作成済みページ ({len(pages)}件) ---")
    for p in pages:
        print(f"    {p['title']}")

    # コレクション一覧
    resp = api_get(token, "smart_collections.json?limit=50")
    smart = resp.json().get("smart_collections", [])
    resp = api_get(token, "custom_collections.json?limit=50")
    custom = resp.json().get("custom_collections", [])
    print()
    print(f"  --- 作成済みコレクション ({len(smart) + len(custom)}件) ---")
    for c in smart:
        rules = c.get("rules", [])
        rule_str = f" (tag = {rules[0]['condition']})" if rules else ""
        print(f"    [Auto] {c['title']}{rule_str}")
    for c in custom:
        print(f"    [Manual] {c['title']}")

    # 商品状態の確認
    resp = api_get(token, "products/count.json?status=draft")
    draft_count = resp.json().get("count", 0)
    resp = api_get(token, "products/count.json?status=active")
    active_count = resp.json().get("count", 0)
    print()
    print(f"  --- 商品状態 ---")
    print(f"    Draft: {draft_count} 件")
    print(f"    Active (公開済み): {active_count} 件")
    print()

    if active_count == 0:
        print("  ✓ 商品は公開されていません（draft のまま）")
    else:
        print("  ⚠ 公開済み商品があります。確認してください。")

    print()
    print("  --- 次に原田が確認すべきこと ---")
    print("  1. Shopify Payments / PayPal の設定が完了したか")
    print("  2. 各ページの内容を管理画面でプレビュー確認")
    print("     https://admin.shopify.com/store/hd-toys-store-japan/pages")
    print("  3. コレクションが正しく作成されたか")
    print("     https://admin.shopify.com/store/hd-toys-store-japan/collections")
    print("  4. 設定に問題なければ CSV インポートに進む")


def test_token(access_token):
    url = f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/shop.json"
    hdrs = {"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"}
    resp = requests.get(url, headers=hdrs)
    return resp.status_code == 200, resp


if __name__ == "__main__":
    main()
