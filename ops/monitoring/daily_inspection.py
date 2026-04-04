# ============================================================
# HD Toys Store Japan 日次点検スクリプト
#
# 安全ルール:
#   - このスクリプトは読み取り専用
#   - Shopify API の書き込み操作（POST/PUT/DELETE）は一切行わない
#   - eBay API にはアクセスしない
#   - 提案をレポートに記載するのみ。本番変更は行わない
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

def inspect_store_setup(products, pages):
    """store-setup: 商品状態・画像・ページ・メニュー"""
    findings = []

    # 商品の公開状態
    active_count = len(products)
    draft_resp = shopify_get("products/count.json?status=draft")
    if draft_resp and draft_resp.status_code == 200:
        draft_count = draft_resp.json().get("count", 0)
    else:
        draft_count = "?"
        findings.append({"type": "warning", "message": "Draft 商品数の取得に失敗"})

    findings.append({
        "type": "info",
        "message": f"Active: {active_count}件 / Draft: {draft_count}件",
    })

    # 画像0枚の公開商品
    no_image = [p for p in products if len(p.get("images", [])) == 0]
    if no_image:
        findings.append({
            "type": "critical",
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
            "type": "critical",
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
                "type": "warning",
                "message": "メインメニューが空または未設定",
            })

        if not footer_menu or len(footer_menu.get("items", [])) == 0:
            findings.append({
                "type": "warning",
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
                "type": "warning",
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
            "type": "warning",
            "message": f"メニュー情報の取得に失敗 (HTTP {status}){detail}",
        })

    return findings


def inspect_price_auditor(products):
    """price-auditor: 価格異常"""
    findings = []

    price_errors = []
    no_compare = []
    zero_price = []

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

    if zero_price:
        findings.append({
            "type": "critical",
            "message": f"価格0の商品: {len(zero_price)}件",
            "details": zero_price[:5],
        })

    if price_errors:
        findings.append({
            "type": "warning",
            "message": f"Price >= Compare at: {len(price_errors)}件",
            "details": price_errors[:5],
        })

    if no_compare:
        findings.append({
            "type": "info",
            "message": f"Compare at price 未設定: {len(no_compare)}件",
        })

    return findings


def inspect_catalog(products):
    """catalog-migration: 商品データ品質"""
    findings = []

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
            "type": "info",
            "message": f"Product Type 未設定/Other: {len(no_type)}件",
        })

    if no_vendor:
        findings.append({
            "type": "info",
            "message": f"Vendor 未設定: {len(no_vendor)}件",
        })

    if short_desc:
        findings.append({
            "type": "info",
            "message": f"Description 100文字未満: {len(short_desc)}件",
        })

    return findings


def inspect_fulfillment():
    """fulfillment-ops: 注文・在庫"""
    findings = []

    resp = shopify_get("orders.json?status=open&fulfillment_status=unfulfilled&limit=50")
    if resp and resp.status_code == 200:
        orders = resp.json().get("orders", [])
        if orders:
            findings.append({
                "type": "critical",
                "message": f"未処理注文: {len(orders)}件",
                "details": [
                    f"#{o['order_number']} ${o['total_price']}" for o in orders[:5]
                ],
            })
        else:
            findings.append({"type": "ok", "message": "未処理注文: なし"})
    else:
        findings.append({"type": "warning", "message": "注文情報の取得に失敗"})

    return findings


def inspect_seo(products):
    """growth-foundation: 画像 alt text の設定状況チェック
    ※ GA4 / Search Console 連携は後日追加
    """
    findings = []

    no_alt_count = 0
    total_images = 0
    for p in products:
        for img in p.get("images", []):
            total_images += 1
            if not img.get("alt"):
                no_alt_count += 1

    if no_alt_count > 0:
        findings.append({
            "type": "info",
            "message": f"画像 alt text 未設定: {no_alt_count}/{total_images}枚",
        })
    else:
        findings.append({
            "type": "ok",
            "message": f"画像 alt text: 全{total_images}枚設定済み",
        })

    return findings


# ============================================================
# レポート生成
# ============================================================

def classify_findings(all_findings):
    """findings を優先度で分類"""
    critical = [f for f in all_findings if f["type"] == "critical"]
    warning = [f for f in all_findings if f["type"] == "warning"]
    info = [f for f in all_findings if f["type"] == "info"]
    ok = [f for f in all_findings if f["type"] == "ok"]
    return critical, warning, info, ok


def generate_markdown_report(all_findings, store_info):
    """詳細 Markdown レポートを生成"""
    critical, warning, info, ok = classify_findings(all_findings)

    lines = []
    lines.append("# HD Toys Store Japan 日次点検レポート")
    lines.append("")
    lines.append(f"**日時:** {TIME_STR}")
    lines.append("")

    # ストア状態
    lines.append("## ストア状態")
    lines.append("")
    for f in all_findings:
        if f["type"] == "info" and "Active:" in f["message"]:
            lines.append(f"- {f['message']}")
    lines.append("")

    # 要対応
    if critical:
        lines.append(f"## 🔴 要対応（{len(critical)}件）")
        lines.append("")
        for f in critical:
            lines.append(f"- **{f['message']}**")
            for d in f.get("details", []):
                lines.append(f"  - {d}")
        lines.append("")

    # 改善候補
    if warning:
        lines.append(f"## 🟡 改善候補（{len(warning)}件）")
        lines.append("")
        for f in warning:
            lines.append(f"- {f['message']}")
            for d in f.get("details", []):
                lines.append(f"  - {d}")
        lines.append("")

    # 情報
    if info:
        lines.append("## 💡 情報")
        lines.append("")
        for f in info:
            lines.append(f"- {f['message']}")
        lines.append("")

    # 正常
    if ok:
        lines.append("## ✓ 異常なし")
        lines.append("")
        for f in ok:
            lines.append(f"- {f['message']}")
        lines.append("")

    return "\n".join(lines)


def generate_chatwork_message(all_findings):
    """Chatwork 要約メッセージを生成"""
    critical, warning, info, ok = classify_findings(all_findings)

    lines = []
    lines.append(
        f"[info][title]HD Toys Store Japan 日次点検（{DATE_STR}）[/title]"
    )

    # ストア状態
    for f in all_findings:
        if f["type"] == "info" and "Active:" in f["message"]:
            lines.append(f["message"])

    # 要対応
    if critical:
        lines.append("")
        lines.append(f"■ 要対応（{len(critical)}件）")
        for f in critical:
            lines.append(f"🔴 {f['message']}")

    # 改善候補
    if warning:
        lines.append("")
        lines.append(f"■ 改善候補（{len(warning)}件）")
        for f in warning:
            lines.append(f"🟡 {f['message']}")

    # 正常
    if not critical and not warning:
        lines.append("")
        lines.append("✓ 異常なし")

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
    print("  HD Toys Store Japan 日次点検")
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
                "type": "critical",
                "message": f"Active 商品の取得に失敗（API は {expected_count}件を報告しているが取得0件）",
            })
        elif expected_count == 0:
            all_findings.append({
                "type": "warning",
                "message": "Active 商品が0件（全商品が Draft または削除されている可能性）",
            })
    else:
        all_findings.append({
            "type": "warning",
            "message": "Active 商品数の API 確認に失敗",
        })
    print(f"  Active products: {len(products)}")

    pages_resp = shopify_get("pages.json?limit=50")
    if pages_resp and pages_resp.status_code == 200:
        pages = pages_resp.json().get("pages", [])
    else:
        pages = []
        all_findings.append({"type": "warning", "message": "ページ情報の取得に失敗"})
    print(f"  Pages: {len(pages)}")
    print()

    # 各エージェントの点検実行
    print("[INFO] store-setup 点検...")
    all_findings.extend(inspect_store_setup(products, pages))

    print("[INFO] price-auditor 点検...")
    all_findings.extend(inspect_price_auditor(products))

    print("[INFO] catalog-migration 点検...")
    all_findings.extend(inspect_catalog(products))

    print("[INFO] fulfillment-ops 点検...")
    all_findings.extend(inspect_fulfillment())

    print("[INFO] growth-foundation 点検（alt text）...")
    all_findings.extend(inspect_seo(products))

    print()

    # レポート生成
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
    critical, warning, info, ok = classify_findings(all_findings)
    print(f"  🔴 要対応: {len(critical)}件")
    print(f"  🟡 改善候補: {len(warning)}件")
    print(f"  💡 情報: {len(info)}件")
    print(f"  ✓ 正常: {len(ok)}件")


if __name__ == "__main__":
    main()
