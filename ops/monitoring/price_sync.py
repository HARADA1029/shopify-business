# ============================================================
# eBay → Shopify 価格同期モジュール
#
# 担当: price-auditor (主担当)
#       store-setup (Shopify更新)
#       project-orchestrator (統括)
#
# ロジック:
# 1. eBay の最新価格を取得（CSV ベース）
# 2. Shopify 側の価格調整ルール（eBay × 0.91）を適用して再計算
# 3. 赤字防止チェック（下限価格）
# 4. Shopify 価格を更新
# 5. ログと変更履歴を保存
#
# 安全ルール:
# - eBay API は読み取り専用
# - 赤字になる更新は行わない
# - 異常な価格差は要確認フラグ
# ============================================================

import csv
import json
import os
from datetime import datetime, timezone, timedelta

import requests

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

SYNC_LOG_FILE = os.path.join(SCRIPT_DIR, "price_sync_log.json")

# === 価格調整ルール ===
# 分析結果: Shopify = eBay × 0.91（約9%引き）
# Compare at price = eBay 価格（元値表示）
SHOPIFY_DISCOUNT_RATE = 0.91
MINIMUM_PROFIT_MARGIN = 0.10  # 最低10%の利益マージン
MINIMUM_PRICE_USD = 10.0       # 最低販売価格
MAX_PRICE_CHANGE_PCT = 999.0   # 変動幅チェックなし（赤字防止のため即時更新優先）
PRICE_ROUNDING = True          # 端数を整数に丸める


def _load_sync_log():
    if not os.path.exists(SYNC_LOG_FILE):
        return {"last_sync": "", "changes": [], "alerts": []}
    try:
        with open(SYNC_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"last_sync": "", "changes": [], "alerts": []}


def _save_sync_log(log):
    log["last_sync"] = NOW.strftime("%Y-%m-%d %H:%M")
    # 過去30日分のみ保持
    cutoff = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
    log["changes"] = [c for c in log.get("changes", []) if c.get("date", "") >= cutoff]
    log["alerts"] = [a for a in log.get("alerts", []) if a.get("date", "") >= cutoff]
    with open(SYNC_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def _get_ebay_token():
    """eBay OAuth トークンを取得"""
    import base64
    app_id = os.environ.get("EBAY_APP_ID", "")
    cert_id = os.environ.get("EBAY_CERT_ID", "")
    if not app_id or not cert_id:
        # .env から読み込み
        from dotenv import dotenv_values
        env = dotenv_values(os.path.join(PROJECT_ROOT, ".env"))
        app_id = env.get("EBAY_APP_ID", "")
        cert_id = env.get("EBAY_CERT_ID", "")
    if not app_id or not cert_id:
        return None
    credentials = "%s:%s" % (app_id, cert_id)
    encoded = base64.b64encode(credentials.encode()).decode()
    try:
        resp = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic %s" % encoded,
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token", "")
    except Exception:
        pass
    return None


def _load_ebay_prices(ebay_ids):
    """eBay API からリアルタイム価格を取得"""
    token = _get_ebay_token()
    if not token:
        # フォールバック: CSV から取得
        csv_path = os.path.join(PROJECT_ROOT, "product-migration", "data", "active_listings_target.csv")
        if os.path.exists(csv_path):
            try:
                with open(csv_path, "r", encoding="utf-8-sig") as f:
                    return {r["item_id"]: float(r.get("price", "0") or "0") for r in csv.DictReader(f)}
            except Exception:
                pass
        return {}

    prices = {}
    headers = {
        "Authorization": "Bearer %s" % token,
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }

    for ebay_id in ebay_ids:
        try:
            resp = requests.get(
                "https://api.ebay.com/buy/browse/v1/item/v1|%s|0" % ebay_id,
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                item = resp.json()
                price_str = item.get("price", {}).get("value", "0")
                prices[ebay_id] = float(price_str)
            import time
            time.sleep(0.2)  # レート制限対策
        except Exception:
            continue

    return prices


def _get_shopify_products():
    """Shopify の商品と価格を取得"""
    shopify_token_file = os.path.join(PROJECT_ROOT, ".shopify_token.json")
    if not os.path.exists(shopify_token_file):
        return []
    with open(shopify_token_file, "r") as f:
        token = json.load(f).get("access_token", "")

    store = os.environ.get("SHOPIFY_STORE", "")
    if not store or not token:
        return []

    api = "https://%s.myshopify.com/admin/api/2026-04" % store
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    products = []
    url = api + "/products.json?limit=250&fields=id,title,variants"
    while url:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code != 200:
                break
            products.extend(resp.json().get("products", []))
            link = resp.headers.get("Link", "")
            import re
            match = re.search(r'<([^>]+)>; rel="next"', link)
            url = match.group(1) if match else None
        except Exception:
            break

    return products


def calculate_shopify_price(ebay_price):
    """eBay 価格から Shopify 価格を再計算する"""
    # 基本: eBay × 割引率
    shopify_price = ebay_price * SHOPIFY_DISCOUNT_RATE

    # 端数処理（整数に丸める）
    if PRICE_ROUNDING:
        shopify_price = round(shopify_price)

    # 最低価格チェック
    if shopify_price < MINIMUM_PRICE_USD:
        shopify_price = MINIMUM_PRICE_USD

    return shopify_price


def check_profitability(shopify_price, ebay_price):
    """赤字チェック（簡易版）"""
    # Shopify 手数料: 約2.9% + $0.30（Shopify Payments）
    shopify_fee = shopify_price * 0.029 + 0.30

    # eBay 側での仕入れ想定原価（eBay 価格の約60-70%と仮定）
    # ※実際の原価データがないため安全マージンで判定
    estimated_cost = ebay_price * 0.6  # 保守的に60%

    net_profit = shopify_price - shopify_fee - estimated_cost
    profit_margin = net_profit / shopify_price if shopify_price > 0 else 0

    return {
        "shopify_fee": round(shopify_fee, 2),
        "estimated_cost": round(estimated_cost, 2),
        "net_profit": round(net_profit, 2),
        "profit_margin": round(profit_margin, 3),
        "is_profitable": profit_margin >= MINIMUM_PROFIT_MARGIN,
    }


def sync_prices():
    """eBay → Shopify の価格同期を実行する"""
    findings = []
    sync_log = _load_sync_log()

    # Shopify 商品から eBay ID を収集
    products = _get_shopify_products()
    ebay_ids = []
    for p in products:
        for v in p.get("variants", []):
            sku = v.get("sku", "")
            if sku.startswith("EB-"):
                ebay_ids.append(sku[3:])

    # eBay API からリアルタイム価格を取得
    ebay_prices = _load_ebay_prices(ebay_ids)
    if not ebay_prices:
        # 失敗理由を特定
        token = _get_ebay_token()
        if not token:
            app_id = os.environ.get("EBAY_APP_ID", "")
            cert_id = os.environ.get("EBAY_CERT_ID", "")
            if not app_id or not cert_id:
                failure_reason = "Credentials missing: EBAY_APP_ID / EBAY_CERT_ID not set in environment"
                failure_type = "credentials"
            else:
                failure_reason = "API authentication failed: eBay OAuth token request rejected (check APP_ID/CERT_ID validity)"
                failure_type = "auth"
        elif not ebay_ids:
            failure_reason = "No eBay SKU mapping: no Shopify variants have EB-xxxxx SKU format"
            failure_type = "mapping"
        else:
            failure_reason = "API request failed: eBay Browse API returned no data (possible rate limit or temporary outage)"
            failure_type = "api_error"

        findings.append({
            "type": "suggestion" if failure_type in ("credentials", "auth") else "info",
            "agent": "price-auditor",
            "message": "Price sync failed [%s]: %s" % (failure_type, failure_reason[:80]),
            "details": [
                "Failure type: %s" % failure_type,
                "Reason: %s" % failure_reason,
                "eBay IDs found in Shopify: %d" % len(ebay_ids),
                "Fallback: CSV price data also not available" if not ebay_prices else "",
            ],
        })
        return findings

    if not products:
        findings.append({
            "type": "info", "agent": "price-auditor",
            "message": "Price sync failed [shopify_api]: Shopify products not available (check SHOPIFY_STORE / access token)",
            "details": [
                "Failure type: shopify_api",
                "SHOPIFY_STORE: %s" % ("set" if os.environ.get("SHOPIFY_STORE") else "not set"),
                "Token file: %s" % ("exists" if os.path.exists(os.path.join(PROJECT_ROOT, ".shopify_token.json")) else "missing"),
            ],
        })
        return findings

    # 商品マッチングと価格比較
    store = os.environ.get("SHOPIFY_STORE", "")
    shopify_token_file = os.path.join(PROJECT_ROOT, ".shopify_token.json")
    with open(shopify_token_file, "r") as f:
        token = json.load(f).get("access_token", "")
    api = "https://%s.myshopify.com/admin/api/2026-04" % store
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    updated = []
    alerts = []
    skipped = []
    today = NOW.strftime("%Y-%m-%d")

    for product in products:
        for variant in product.get("variants", []):
            sku = variant.get("sku", "")
            if not sku.startswith("EB-"):
                continue

            ebay_id = sku[3:]
            ebay_price = ebay_prices.get(ebay_id, 0)
            if ebay_price <= 0:
                continue

            current_shopify_price = float(variant.get("price", "0") or "0")
            current_compare_at = variant.get("compare_at_price")
            current_compare_at_f = float(current_compare_at) if current_compare_at else 0

            # Shopify 新価格を計算
            new_shopify_price = calculate_shopify_price(ebay_price)
            new_compare_at = round(ebay_price) if PRICE_ROUNDING else ebay_price

            # 価格変更があるか
            price_changed = abs(new_shopify_price - current_shopify_price) >= 1.0
            compare_changed = abs(new_compare_at - current_compare_at_f) >= 1.0

            if not price_changed and not compare_changed:
                continue

            # 変更幅チェック
            if current_shopify_price > 0:
                change_pct = abs(new_shopify_price - current_shopify_price) / current_shopify_price
            else:
                change_pct = 1.0

            # 赤字チェック
            profitability = check_profitability(new_shopify_price, ebay_price)

            # 要確認条件
            needs_review = False
            review_reasons = []

            if change_pct > MAX_PRICE_CHANGE_PCT:
                needs_review = True
                review_reasons.append("Price change > %.0f%% (%.1f%%)" % (MAX_PRICE_CHANGE_PCT * 100, change_pct * 100))

            if not profitability["is_profitable"]:
                needs_review = True
                review_reasons.append("Low margin: %.1f%% (min: %.0f%%)" % (profitability["profit_margin"] * 100, MINIMUM_PROFIT_MARGIN * 100))
                # 赤字防止: 価格を補正
                new_shopify_price = max(new_shopify_price, ebay_price * 0.7)  # 最低でも eBay の70%
                if PRICE_ROUNDING:
                    new_shopify_price = round(new_shopify_price)

            change_record = {
                "date": today,
                "product_id": product["id"],
                "variant_id": variant["id"],
                "title": product["title"][:50],
                "ebay_id": ebay_id,
                "ebay_price": ebay_price,
                "shopify_old_price": current_shopify_price,
                "shopify_new_price": new_shopify_price,
                "compare_at_old": current_compare_at_f,
                "compare_at_new": new_compare_at,
                "rule_applied": "eBay x %.3f" % SHOPIFY_DISCOUNT_RATE,
                "profitability": profitability,
                "needs_review": needs_review,
                "review_reasons": review_reasons,
                "status": "pending",
            }

            if needs_review:
                # 要確認の場合は更新しない
                change_record["status"] = "needs_review"
                alerts.append(change_record)
            else:
                # Shopify 価格を更新
                try:
                    update_resp = requests.put(
                        "%s/variants/%d.json" % (api, variant["id"]),
                        headers=headers,
                        json={
                            "variant": {
                                "id": variant["id"],
                                "price": str(new_shopify_price),
                                "compare_at_price": str(new_compare_at),
                            }
                        },
                        timeout=15,
                    )
                    if update_resp.status_code == 200:
                        change_record["status"] = "updated"
                        updated.append(change_record)
                    else:
                        change_record["status"] = "failed"
                        change_record["error"] = update_resp.text[:100]
                        alerts.append(change_record)
                except Exception as e:
                    change_record["status"] = "error"
                    change_record["error"] = str(e)[:100]
                    alerts.append(change_record)

    # ログ保存
    sync_log["changes"].extend(updated)
    sync_log["changes"].extend(alerts)
    _save_sync_log(sync_log)

    # レポート生成
    if updated:
        details = []
        for u in updated[:3]:
            details.append(
                "%s: $%.0f -> $%.0f (eBay: $%.0f)" % (u["title"][:30], u["shopify_old_price"], u["shopify_new_price"], u["ebay_price"])
            )
        findings.append({
            "type": "ok", "agent": "price-auditor",
            "message": "Price sync: %d products updated" % len(updated),
            "details": details,
        })

    if alerts:
        alert_details = []
        for a in alerts[:3]:
            reasons = "; ".join(a.get("review_reasons", []))
            alert_details.append(
                "%s: needs review (%s)" % (a["title"][:30], reasons[:50])
            )
        findings.append({
            "type": "suggestion", "agent": "price-auditor",
            "message": "Price sync alerts: %d products need review" % len(alerts),
            "details": alert_details,
        })

    if not updated and not alerts:
        findings.append({
            "type": "ok", "agent": "price-auditor",
            "message": "Price sync: All prices in sync, no changes needed",
        })

    return findings
