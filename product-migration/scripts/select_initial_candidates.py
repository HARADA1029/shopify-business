# ============================================================
# 初期移行候補 選定 → GetItem 補完 → price-auditor 監査
#
# 【役割】
#   1. active_listings_target.csv から候補プール200件を層化抽出
#   2. GetItem API で詳細データを補完
#   3. price-auditor の監査条件で分類 A / B / C に仕分け
#   4. 確認リスト・レポートを出力
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/select_initial_candidates.py
#
# 【参照】
#   docs/initial-migration-selection.md
#   docs/shopify-price-strategy.md
# ============================================================

import csv
import json
import math
import os
import random
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime

import requests
from dotenv import load_dotenv

# --- 設定 ---

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

DATA_DIR = os.path.join(PROJECT_ROOT, "product-migration", "data")
TOKEN_FILE = os.path.join(PROJECT_ROOT, ".ebay_token.json")

TRADING_API_URL = "https://api.ebay.com/ws/api.dll"
NS = {"e": "urn:ebay:apis:eBLBaseComponents"}

REQUEST_INTERVAL = 0.5

# --- 選定パラメータ ---

PRICE_MIN = 100
PRICE_MAX = 999
WATCHERS_MIN = 3          # 基本条件
WATCHERS_FALLBACK = 1     # 緩和時の下限
QUANTITY_TARGET = 1

# 層化抽出の配分
STRATA = [
    # (下限, 上限, 抽出件数)
    (100, 200, 60),
    (200, 300, 50),
    (300, 500, 50),
    (500, 999, 40),
]

# price-auditor 監査パラメータ
ZSCORE_THRESHOLD = 2.0
MIN_CATEGORY_SIZE = 5
DUTY_KEYWORDS = ["import tax", "customs", "tax included", "ddp", "duty paid"]

# Shopify 暫定変換率
SHOPIFY_RATE = 0.91

# Condition 除外リスト
CONDITION_EXCLUDE = ["for parts or not working", "for parts"]


# ============================================================
# ユーティリティ
# ============================================================

def load_token():
    if not os.path.exists(TOKEN_FILE):
        print(f"[エラー] トークンファイルが見つかりません: {TOKEN_FILE}")
        sys.exit(1)
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    token = data.get("access_token", "")
    if not token:
        print("[エラー] access_token が空です。")
        sys.exit(1)
    return token


def load_csv(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_csv(rows, filepath, fieldnames=None):
    if not rows:
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            f.write("")
        return
    if not fieldnames:
        fieldnames = list(rows[0].keys())
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def get_price(row):
    try:
        return float(row.get("price", "0") or "0")
    except ValueError:
        return 0.0


def get_watchers(row):
    try:
        return int(row.get("watchers", "0") or "0")
    except ValueError:
        return 0


def get_quantity(row):
    """数量を取得する。空欄・変換不能は None を返す"""
    raw = (row.get("quantity_available", "") or "").strip()
    if not raw:
        return None
    try:
        q = int(raw)
        if q < 0:
            return -1  # 不正値マーカー
        return q
    except ValueError:
        return None


def get_text(element, path):
    el = element.find(path, NS)
    return el.text.strip() if el is not None and el.text else ""


def get_item_specific(item_el, name):
    specifics = item_el.findall(".//e:ItemSpecifics/e:NameValueList", NS)
    for spec in specifics:
        spec_name = get_text(spec, "e:Name")
        if spec_name.lower() == name.lower():
            return get_text(spec, "e:Value")
    return ""


# ============================================================
# Phase 1: 候補プール抽出
# ============================================================

def select_candidate_pool(rows):
    """価格帯・watchers・数量でフィルタし、層化抽出する"""
    print("=" * 60)
    print("  Phase 1: 候補プール抽出")
    print("=" * 60)
    print()

    # 基本フィルタ
    pool = []
    qty_unknown = 0
    qty_multi = 0
    qty_invalid = 0

    for r in rows:
        price = get_price(r)
        watchers = get_watchers(r)
        qty = get_quantity(r)

        if not (PRICE_MIN <= price <= PRICE_MAX):
            continue
        if watchers < WATCHERS_MIN:
            continue

        # 数量チェック
        if qty is None:
            qty_unknown += 1
            continue  # 候補プールには入れない（Phase 3 で分類 B に入る余地なし）
        if qty < 0:
            qty_invalid += 1
            continue
        if qty != QUANTITY_TARGET:
            qty_multi += 1
            continue

        pool.append(r)

    print(f"  基本条件: ${PRICE_MIN}〜${PRICE_MAX}, watchers >= {WATCHERS_MIN}, quantity = {QUANTITY_TARGET}")
    print(f"  フィルタ通過: {len(pool)} 件")
    if qty_unknown > 0:
        print(f"  数量不明で除外: {qty_unknown} 件")
    if qty_multi > 0:
        print(f"  複数在庫で除外: {qty_multi} 件")
    if qty_invalid > 0:
        print(f"  数量不正で除外: {qty_invalid} 件")
    print()

    # 層化抽出（watchers 上位から）
    sample = []
    relaxed_strata = []

    for low, high, target_count in STRATA:
        stratum = [r for r in pool if low <= get_price(r) < high]
        # watchers でソート（降順）
        stratum.sort(key=lambda r: get_watchers(r), reverse=True)

        actual = min(target_count, len(stratum))
        selected = stratum[:actual]
        sample.extend(selected)

        relaxed = ""
        if actual < target_count:
            # 緩和が必要な場合
            shortfall = target_count - actual
            relaxed_pool = [r for r in rows
                           if low <= get_price(r) < high
                           and WATCHERS_FALLBACK <= get_watchers(r) < WATCHERS_MIN
                           and get_quantity(r) == QUANTITY_TARGET]
            relaxed_pool.sort(key=lambda r: get_watchers(r), reverse=True)
            extra = relaxed_pool[:shortfall]
            sample.extend(extra)
            if extra:
                relaxed = f" (+{len(extra)} 件を watchers >= {WATCHERS_FALLBACK} で緩和補充)"
                relaxed_strata.append(f"${low}-${high}")

        print(f"  ${low:>3}-${high:>3}: 母集団 {len(stratum):>4} → 抽出 {actual}{relaxed}")

    print()
    print(f"  候補プール合計: {len(sample)} 件")
    if relaxed_strata:
        print(f"  ※ {', '.join(relaxed_strata)} で watchers 条件を緩和")
    print()

    return sample


# ============================================================
# Phase 2: GetItem 補完
# ============================================================

def fetch_item_details(access_token, item_id):
    headers = {
        "X-EBAY-API-SITEID": "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "GetItem",
        "X-EBAY-API-IAF-TOKEN": access_token,
        "Content-Type": "text/xml",
    }
    xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
  <IncludeItemSpecifics>true</IncludeItemSpecifics>
</GetItemRequest>"""
    return requests.post(TRADING_API_URL, headers=headers, data=xml_request)


def parse_item_details(response_text):
    root = ET.fromstring(response_text)
    ack = get_text(root, "e:Ack")
    if ack not in ("Success", "Warning"):
        errors = root.findall(".//e:Errors/e:ShortMessage", NS)
        return None, [e.text for e in errors if e.text]

    item = root.find(".//e:Item", NS)
    if item is None:
        return None, ["Item 要素が見つかりません"]

    pic_urls = item.findall(".//e:PictureDetails/e:PictureURL", NS)
    image_urls = [u.text for u in pic_urls if u.text]

    details = {
        "category_id": get_text(item, ".//e:PrimaryCategory/e:CategoryID"),
        "category_name": get_text(item, ".//e:PrimaryCategory/e:CategoryName"),
        "condition_id": get_text(item, ".//e:ConditionID"),
        "condition_name": get_text(item, ".//e:ConditionDisplayName"),
        "brand": get_item_specific(item, "Brand"),
        "character": (get_item_specific(item, "Character")
                      or get_item_specific(item, "Character Family")),
        "franchise": (get_item_specific(item, "Franchise")
                      or get_item_specific(item, "TV Show")
                      or get_item_specific(item, "Theme")),
        "image_count": str(len(image_urls)),
        "image_urls": " | ".join(image_urls[:5]),  # 最大5枚分の URL
        "view_count": get_text(item, ".//e:HitCount") or "0",
    }
    return details, None


def enrich_candidates(access_token, candidates):
    """候補プールの各商品を GetItem で補完する"""
    print("=" * 60)
    print("  Phase 2: GetItem 補完")
    print("=" * 60)
    print()

    enriched = []
    ok_count = 0
    err_count = 0
    total = len(candidates)

    for i, row in enumerate(candidates, 1):
        item_id = row.get("item_id", "")
        print(f"  [{i:>3}/{total}] {item_id} ... ", end="", flush=True)

        try:
            response = fetch_item_details(access_token, item_id)
        except Exception as e:
            print(f"通信エラー → スキップ")
            err_count += 1
            enriched.append(row)
            time.sleep(REQUEST_INTERVAL)
            continue

        if response.status_code != 200:
            print(f"HTTP {response.status_code} → スキップ")
            err_count += 1
            enriched.append(row)
            time.sleep(REQUEST_INTERVAL)
            continue

        details, errors = parse_item_details(response.text)
        if errors:
            print(f"{errors[0]} → スキップ")
            err_count += 1
            enriched.append(row)
            time.sleep(REQUEST_INTERVAL)
            continue

        merged = dict(row)
        for key, value in details.items():
            if value:
                merged[key] = value
        enriched.append(merged)
        ok_count += 1
        print("OK")
        time.sleep(REQUEST_INTERVAL)

    print()
    print(f"  補完成功: {ok_count} / {total}")
    if err_count:
        print(f"  補完失敗: {err_count} / {total}")
    print()

    return enriched


# ============================================================
# Phase 3: price-auditor 監査
# ============================================================

def audit_candidates(enriched):
    """分類 A / B / C に仕分ける"""
    print("=" * 60)
    print("  Phase 3: price-auditor 監査")
    print("=" * 60)
    print()

    # --- カテゴリ別の価格統計を計算 ---
    cat_prices = defaultdict(list)
    for r in enriched:
        cat = (r.get("category_name") or "").strip()
        if cat:
            cat_prices[cat].append(get_price(r))

    cat_stats = {}
    for cat, prices in cat_prices.items():
        if len(prices) >= MIN_CATEGORY_SIZE:
            mean = sum(prices) / len(prices)
            variance = sum((p - mean) ** 2 for p in prices) / len(prices)
            std = math.sqrt(variance) if variance > 0 else 0
            cat_stats[cat] = (mean, std)

    # --- 各商品を分類 ---
    auto_convert = []    # 分類 A
    review_list = []     # 分類 B
    excluded = []        # 分類 C

    for r in enriched:
        price = get_price(r)
        title_lower = (r.get("title") or "").lower()
        condition = (r.get("condition_name") or "").strip().lower()
        image_count = 0
        try:
            image_count = int(r.get("image_count") or "0")
        except ValueError:
            pass
        qty = get_quantity(r)
        cat = (r.get("category_name") or "").strip()

        flags = []

        # --- 分類 C チェック（即除外） ---
        if price >= 1000:
            flags.append("高額品($1,000+)")
            r["_audit_class"] = "C"
            r["_audit_flags"] = "; ".join(flags)
            excluded.append(r)
            continue

        if condition in CONDITION_EXCLUDE:
            flags.append(f"Condition除外({condition})")
            r["_audit_class"] = "C"
            r["_audit_flags"] = "; ".join(flags)
            excluded.append(r)
            continue

        if qty is not None and qty < 0:
            flags.append("数量不正")
            r["_audit_class"] = "C"
            r["_audit_flags"] = "; ".join(flags)
            excluded.append(r)
            continue

        # --- 分類 B チェック（要確認フラグ） ---

        # 価格外れ値チェック
        if cat in cat_stats:
            mean, std = cat_stats[cat]
            if std > 0:
                z = abs(price - mean) / std
                if z > ZSCORE_THRESHOLD:
                    flags.append(f"価格外れ値(z={z:.1f}, カテゴリ平均${mean:.0f})")

        # 関税キーワードチェック
        for kw in DUTY_KEYWORDS:
            if kw in title_lower:
                flags.append(f"関税キーワード({kw})")
                break

        # 画像なしチェック
        if image_count == 0:
            flags.append("画像なし")

        # 数量不明チェック
        if qty is None:
            flags.append("数量不明")

        if flags:
            r["_audit_class"] = "B"
            r["_audit_flags"] = "; ".join(flags)
            review_list.append(r)
        else:
            r["_audit_class"] = "A"
            r["_audit_flags"] = ""
            auto_convert.append(r)

    print(f"  分類 A（自動変換）: {len(auto_convert)} 件")
    print(f"  分類 B（要確認）  : {len(review_list)} 件")
    print(f"  分類 C（除外）    : {len(excluded)} 件")
    print()

    # 分類 B のフラグ理由集計
    if review_list:
        print("  --- 分類 B のフラグ理由 ---")
        flag_counts = Counter()
        for r in review_list:
            for flag in r["_audit_flags"].split("; "):
                # 括弧内の詳細を除去して集計
                key = flag.split("(")[0].strip()
                flag_counts[key] += 1
        for reason, count in flag_counts.most_common():
            print(f"  {reason:20s}: {count} 件")
        print()

    return auto_convert, review_list, excluded


# ============================================================
# Phase 4: 出力ファイル生成
# ============================================================

# 出力 CSV のカラム定義
OUTPUT_FIELDS = [
    "item_id", "sku", "title", "category_id", "category_name",
    "price", "currency", "condition_id", "condition_name",
    "quantity_available", "brand", "character", "franchise",
    "watchers", "image_count", "image_urls",
    "listing_start_date", "view_count",
]

REVIEW_FIELDS = [
    "item_id", "sku", "title",
    "ebay_price", "shopify_price_draft", "category",
    "flag_reason",
    "decision", "custom_price",
]


def build_review_row(r):
    """分類 B の商品を確認リスト形式に変換する"""
    price = get_price(r)
    shopify_draft = round(price * SHOPIFY_RATE) - 0.01
    return {
        "item_id": r.get("item_id", ""),
        "sku": r.get("sku", ""),
        "title": r.get("title", ""),
        "ebay_price": f"{price:.2f}",
        "shopify_price_draft": f"{shopify_draft:.2f}",
        "category": r.get("category_name", ""),
        "flag_reason": r.get("_audit_flags", ""),
        "decision": "",
        "custom_price": "",
    }


def generate_report(candidates, enriched, auto_convert, review_list, excluded):
    """選定レポートを生成する"""
    lines = []

    def w(text=""):
        lines.append(text)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    w("=" * 70)
    w(f"  初期移行候補 選定レポート（{timestamp}）")
    w("=" * 70)

    # --- 候補プール ---
    w()
    w("  --- 候補プール ---")
    w(f"  抽出件数: {len(candidates)} 件")
    w()
    ranges = [(100, 200), (200, 300), (300, 500), (500, 999)]
    for low, high in ranges:
        cnt = sum(1 for r in candidates if low <= get_price(r) < high)
        w(f"  ${low:>3}-${high:>3}: {cnt:>4} 件")

    # --- GetItem 補完 ---
    w()
    w("  --- GetItem 補完結果 ---")
    cat_filled = sum(1 for r in enriched if (r.get("category_name") or "").strip())
    cond_filled = sum(1 for r in enriched if (r.get("condition_name") or "").strip())
    brand_filled = sum(1 for r in enriched if (r.get("brand") or "").strip())
    img_filled = sum(1 for r in enriched if int(r.get("image_count") or "0") > 0)
    n = len(enriched)
    w(f"  Category  : {cat_filled}/{n} ({cat_filled/n*100:.0f}%)")
    w(f"  Condition : {cond_filled}/{n} ({cond_filled/n*100:.0f}%)")
    w(f"  Brand     : {brand_filled}/{n} ({brand_filled/n*100:.0f}%)")
    w(f"  画像1枚以上: {img_filled}/{n} ({img_filled/n*100:.0f}%)")

    # --- price-auditor 監査結果 ---
    w()
    w("  --- price-auditor 監査結果 ---")
    w(f"  分類 A（自動変換）: {len(auto_convert)} 件")
    w(f"  分類 B（要確認）  : {len(review_list)} 件")
    w(f"  分類 C（除外）    : {len(excluded)} 件")

    # --- 分類 A の価格帯分布 ---
    w()
    w("  --- 分類 A: 自動変換候補の価格帯 ---")
    for low, high in ranges:
        cnt = sum(1 for r in auto_convert if low <= get_price(r) < high)
        w(f"  ${low:>3}-${high:>3}: {cnt:>4} 件")

    # --- 分類 A の Shopify 暫定価格帯 ---
    w()
    w("  --- 分類 A: Shopify 暫定価格（× 0.91） ---")
    if auto_convert:
        sp = [get_price(r) * SHOPIFY_RATE for r in auto_convert]
        sp.sort()
        w(f"  最小: ${min(sp):.0f}  中央値: ${sp[len(sp)//2]:.0f}  最大: ${max(sp):.0f}")

    # --- 分類 B のサンプル ---
    w()
    w("  --- 分類 B: 要確認リスト（先頭10件）---")
    for r in review_list[:10]:
        price = get_price(r)
        title = (r.get("title") or "")[:60]
        flags = r.get("_audit_flags", "")
        w(f"  ${price:>7.0f} | {title}")
        w(f"           フラグ: {flags}")

    # --- 分類 C のサンプル ---
    if excluded:
        w()
        w("  --- 分類 C: 除外（全件）---")
        for r in excluded:
            price = get_price(r)
            title = (r.get("title") or "")[:60]
            flags = r.get("_audit_flags", "")
            w(f"  ${price:>7.0f} | {title}")
            w(f"           理由: {flags}")

    # --- 次のアクション ---
    w()
    w("=" * 70)
    w("  次のアクション")
    w("=" * 70)
    w()
    w(f"  1. review_list.csv（{len(review_list)} 件）を原田が確認")
    w(f"     → decision 列に ok / exclude / custom を記入")
    w()
    w(f"  2. 確認完了後、分類 A（{len(auto_convert)} 件）+ 原田承認分 から")
    w(f"     watchers 上位100件をドラフト100件として確定")
    w()
    w(f"  3. ドラフト100件の最終レビュー")
    w(f"     → 問題なければ移行パイプラインへ投入")

    return "\n".join(lines)


# ============================================================
# メイン処理
# ============================================================

def main():
    print()
    print("=" * 60)
    print("  初期移行候補 選定 → GetItem 補完 → price-auditor 監査")
    print("=" * 60)
    print()

    # --- target CSV を読み込む ---
    target_csv = os.path.join(DATA_DIR, "active_listings_target.csv")
    if not os.path.exists(target_csv):
        print(f"[エラー] {target_csv} が見つかりません。")
        sys.exit(1)

    rows = load_csv(target_csv)
    print(f"[OK] 母集団を読み込みました: {len(rows)} 件")
    print()

    # --- Phase 1: 候補プール抽出 ---
    candidates = select_candidate_pool(rows)

    # 候補プール保存（不要カラムを除去）
    for r in candidates:
        r.pop("_filter_reason", None)
        for key in OUTPUT_FIELDS:
            if key not in r:
                r[key] = ""
    candidates_path = os.path.join(DATA_DIR, "candidates_200.csv")
    save_csv(candidates, candidates_path, fieldnames=OUTPUT_FIELDS)
    print(f"[OK] 候補プール保存: {candidates_path}")
    print()

    # --- Phase 2: GetItem 補完 ---
    access_token = load_token()
    enriched = enrich_candidates(access_token, candidates)

    # 補完済み候補保存
    enriched_path = os.path.join(DATA_DIR, "candidates_200_enriched.csv")
    # カラムを揃える
    for r in enriched:
        for key in OUTPUT_FIELDS:
            if key not in r:
                r[key] = ""
    save_csv(enriched, enriched_path, fieldnames=OUTPUT_FIELDS)
    print(f"[OK] 補完済み候補保存: {enriched_path}")
    print()

    # --- Phase 3: price-auditor 監査 ---
    auto_convert, review_list, excluded = audit_candidates(enriched)

    # 分類 A: watchers 降順でソート
    auto_convert.sort(key=lambda r: get_watchers(r), reverse=True)

    # Shopify 暫定価格を付与して保存
    for r in auto_convert:
        price = get_price(r)
        r["shopify_price_draft"] = f"{round(price * SHOPIFY_RATE) - 0.01:.2f}"

    auto_fields = OUTPUT_FIELDS + ["shopify_price_draft", "_audit_class", "_audit_flags"]
    auto_path = os.path.join(DATA_DIR, "auto_convert.csv")
    save_csv(auto_convert, auto_path, fieldnames=auto_fields)
    print(f"[OK] 分類 A 保存: {auto_path} ({len(auto_convert)} 件)")

    # 分類 B: 確認リスト
    review_rows = [build_review_row(r) for r in review_list]
    review_path = os.path.join(DATA_DIR, "review_list.csv")
    save_csv(review_rows, review_path, fieldnames=REVIEW_FIELDS)
    print(f"[OK] 分類 B 保存: {review_path} ({len(review_list)} 件)")

    # 分類 C: 除外
    excluded_fields = OUTPUT_FIELDS + ["_audit_class", "_audit_flags"]
    excluded_path = os.path.join(DATA_DIR, "initial_excluded.csv")
    save_csv(excluded, excluded_path, fieldnames=excluded_fields)
    print(f"[OK] 分類 C 保存: {excluded_path} ({len(excluded)} 件)")
    print()

    # --- Phase 4: レポート ---
    report = generate_report(candidates, enriched, auto_convert, review_list, excluded)
    report_path = os.path.join(DATA_DIR, "selection_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[OK] レポート保存: {report_path}")
    print()
    print(report)


if __name__ == "__main__":
    main()
