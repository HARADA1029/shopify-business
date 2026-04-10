# ============================================================
# eBay → Shopify 画像追加モジュール
#
# 担当: catalog-migration-planner
#
# ロジック:
# 1. Shopify 商品のSKU（EB-xxxxx）から eBay IDを特定
# 2. eBay Browse API で画像一覧を取得
# 3. Shopify に無い画像があれば追加
# 4. 既存画像は一切削除しない（追加のみ）
# 5. ログを保存
#
# 安全ルール:
# - eBay API は読み取り専用
# - 既存画像は絶対に削除しない
# - 画像の重複追加を防止
# ============================================================

import base64
import json
import os
import time
from datetime import datetime, timezone, timedelta

import requests

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

IMAGE_SYNC_LOG = os.path.join(SCRIPT_DIR, "image_sync_log.json")


def _load_sync_log():
    if not os.path.exists(IMAGE_SYNC_LOG):
        return {"changes": [], "last_run": "", "stats": {"total_added": 0, "total_checked": 0}}
    try:
        with open(IMAGE_SYNC_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"changes": [], "last_run": "", "stats": {"total_added": 0, "total_checked": 0}}


def _save_sync_log(log):
    log["last_run"] = NOW.strftime("%Y-%m-%d %H:%M")
    cutoff = (NOW - timedelta(days=90)).strftime("%Y-%m-%d")
    log["changes"] = [c for c in log["changes"] if c.get("date", "") >= cutoff]
    with open(IMAGE_SYNC_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def _get_ebay_token():
    """eBay Browse API 用トークンを取得"""
    app_id = os.environ.get("EBAY_APP_ID", "")
    cert_id = os.environ.get("EBAY_CERT_ID", "")
    if not app_id or not cert_id:
        return None
    encoded = base64.b64encode(("%s:%s" % (app_id, cert_id)).encode()).decode()
    try:
        resp = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": "Basic %s" % encoded},
            data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token", "")
    except Exception:
        pass
    return None


def _get_ebay_images(ebay_token, ebay_id):
    """eBay Browse API から画像URLリストを取得"""
    try:
        resp = requests.get(
            "https://api.ebay.com/buy/browse/v1/item/v1|%s|0" % ebay_id,
            headers={"Authorization": "Bearer %s" % ebay_token, "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            timeout=15,
        )
        if resp.status_code == 200:
            item = resp.json()
            images = []
            main = item.get("image", {}).get("imageUrl", "")
            if main:
                images.append(main)
            for img in item.get("additionalImages", []):
                url = img.get("imageUrl", "")
                if url:
                    images.append(url)
            return images
    except Exception:
        pass
    return []


def _extract_image_id(url):
    """eBay画像URLからユニークIDを抽出
    例: https://i.ebayimg.com/images/g/H60AAOSwZAdiddEb/s-l1600.jpg → H60AAOSwZAdiddEb
    """
    try:
        if "/images/g/" in url:
            return url.split("/images/g/")[1].split("/")[0]
    except (IndexError, ValueError):
        pass
    return url.split("?")[0].rsplit("/", 1)[-1].split(".")[0]


def sync_images():
    """eBay に新しい画像があれば Shopify に追加する（既存画像は削除しない）"""
    findings = []
    sync_log = _load_sync_log()

    # Shopify トークン
    shopify_token_file = os.path.join(PROJECT_ROOT, ".shopify_token.json")
    if not os.path.exists(shopify_token_file):
        findings.append({"type": "info", "agent": "catalog-migration-planner", "message": "Image sync: Shopify token not available"})
        return findings
    with open(shopify_token_file, "r") as f:
        shopify_token = json.load(f).get("access_token", "")

    store = os.environ.get("SHOPIFY_STORE", "")
    if not store or not shopify_token:
        findings.append({"type": "info", "agent": "catalog-migration-planner", "message": "Image sync: Shopify credentials not available"})
        return findings

    api = "https://%s.myshopify.com/admin/api/2026-04" % store
    shopify_headers = {"X-Shopify-Access-Token": shopify_token, "Content-Type": "application/json"}

    # eBay トークン
    ebay_token = _get_ebay_token()
    if not ebay_token:
        findings.append({"type": "info", "agent": "catalog-migration-planner", "message": "Image sync failed [auth]: eBay token not available"})
        return findings

    # Shopify Active商品を取得
    products = []
    url = api + "/products.json?status=active&limit=250&fields=id,title,variants,images"
    while url:
        try:
            resp = requests.get(url, headers=shopify_headers, timeout=30)
            if resp.status_code != 200:
                break
            products.extend(resp.json().get("products", []))
            link = resp.headers.get("Link", "")
            url = link.split("<")[1].split(">")[0] if 'rel="next"' in link and "<" in link else None
        except Exception:
            break

    if not products:
        findings.append({"type": "info", "agent": "catalog-migration-planner", "message": "Image sync: No Shopify products"})
        return findings

    # 画像3枚未満の商品のみチェック対象（負荷軽減）
    MIN_IMAGES = 3
    low_image_products = [p for p in products if len(p.get("images", [])) < MIN_IMAGES]

    if not low_image_products:
        findings.append({
            "type": "ok", "agent": "catalog-migration-planner",
            "message": "Image sync: All %d products have %d+ images, skip check" % (len(products), MIN_IMAGES),
        })
        _save_sync_log(sync_log)
        return findings

    total_checked = 0
    total_added = 0
    changes = []

    for product in low_image_products:
        ebay_id = None
        for v in product.get("variants", []):
            sku = v.get("sku", "")
            if sku.startswith("EB-"):
                ebay_id = sku[3:]
                break
        if not ebay_id:
            continue

        total_checked += 1

        # Shopify 側の画像ID集合
        shopify_image_ids = set(_extract_image_id(img.get("src", "")) for img in product.get("images", []))

        # eBay 側の画像を取得
        ebay_images = _get_ebay_images(ebay_token, ebay_id)
        if not ebay_images:
            continue

        # Shopify にない画像を特定
        new_images = [url for url in ebay_images if _extract_image_id(url) not in shopify_image_ids]
        if not new_images:
            continue

        # 追加（既存は一切触らない）
        added = 0
        for img_url in new_images:
            try:
                r = requests.post(
                    "%s/products/%d/images.json" % (api, product["id"]),
                    headers=shopify_headers,
                    json={"image": {"src": img_url}},
                    timeout=30,
                )
                if r.status_code == 200:
                    added += 1
                time.sleep(0.5)
            except Exception:
                continue

        if added > 0:
            total_added += added
            changes.append({
                "date": NOW.strftime("%Y-%m-%d"),
                "product_id": product["id"],
                "title": product["title"][:50],
                "ebay_id": ebay_id,
                "before": len(product.get("images", [])),
                "added": added,
                "after": len(product.get("images", [])) + added,
            })

        time.sleep(0.3)

    # ログ保存
    sync_log["changes"].extend(changes)
    sync_log["stats"]["total_added"] = sync_log["stats"].get("total_added", 0) + total_added
    sync_log["stats"]["total_checked"] = total_checked
    _save_sync_log(sync_log)

    # レポート
    if total_added > 0:
        details = ["%s: +%d images (%d -> %d)" % (c["title"], c["added"], c["before"], c["after"]) for c in changes]
        findings.append({
            "type": "ok", "agent": "catalog-migration-planner",
            "message": "Image sync: %d images added to %d products (checked %d)" % (total_added, len(changes), total_checked),
            "details": details,
        })
    else:
        findings.append({
            "type": "ok", "agent": "catalog-migration-planner",
            "message": "Image sync: All %d products up to date" % total_checked,
        })

    return findings
