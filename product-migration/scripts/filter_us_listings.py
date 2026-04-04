# ============================================================
# 米国 USD 出品フィルタスクリプト
#
# 【役割】
#   Active Listings CSV から currency=USD の出品だけを抽出し、
#   フィルタ済み CSV を保存する。
#   SKU のプレフィックスパターンを集計して ebaymag 由来の候補を検出する。
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/filter_us_listings.py
# ============================================================

import csv
import os
import sys
from collections import Counter

# --- 設定 ---

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "product-migration", "data")


def find_latest_csv():
    """data/ から最新の active_listings CSV を探す"""
    if not os.path.isdir(DATA_DIR):
        return None
    csvs = [f for f in os.listdir(DATA_DIR) if f.startswith("active_listings") and f.endswith(".csv")]
    if not csvs:
        return None
    csvs.sort(reverse=True)
    return os.path.join(DATA_DIR, csvs[0])


def load_csv(filepath):
    """CSV を読み込んで辞書リストとして返す"""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def save_csv(rows, filepath):
    """辞書リストを CSV に保存する"""
    if not rows:
        return
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def extract_sku_prefix(sku, length=3):
    """SKU の先頭 N 文字をプレフィックスとして返す"""
    sku = (sku or "").strip()
    if not sku:
        return "(空欄)"
    return sku[:length]


def analyze_sku_patterns(rows):
    """SKU のパターンを複数の観点で集計する"""
    results = {}

    # --- 1. 先頭3文字のプレフィックス集計 ---
    prefix3 = Counter(extract_sku_prefix(r.get("sku"), 3) for r in rows)
    results["prefix_3char"] = prefix3

    # --- 2. 区切り文字で分割した先頭セグメント ---
    first_segment = Counter()
    for r in rows:
        sku = (r.get("sku") or "").strip()
        if not sku:
            first_segment["(空欄)"] += 1
            continue
        # ハイフン、アンダースコア、ドットで分割
        for sep in ["-", "_", "."]:
            if sep in sku:
                first_segment[sku.split(sep)[0]] += 1
                break
        else:
            # 区切り文字なし → SKU 全体が1セグメント
            first_segment[sku] += 1
    results["first_segment"] = first_segment

    # --- 3. SKU の長さ分布 ---
    length_dist = Counter(len((r.get("sku") or "").strip()) for r in rows)
    results["length_dist"] = length_dist

    return results


def detect_ebaymag_candidates(usd_rows, non_usd_rows):
    """
    ebaymag 由来の可能性がある SKU パターンを検出する。
    非 USD 出品にのみ存在する SKU プレフィックスを特定する。
    """
    # 非 USD の先頭セグメント集合
    non_usd_segments = set()
    for r in non_usd_rows:
        sku = (r.get("sku") or "").strip()
        if not sku:
            continue
        for sep in ["-", "_", "."]:
            if sep in sku:
                non_usd_segments.add(sku.split(sep)[0])
                break

    # USD 出品の先頭セグメント
    usd_segment_count = Counter()
    for r in usd_rows:
        sku = (r.get("sku") or "").strip()
        if not sku:
            continue
        for sep in ["-", "_", "."]:
            if sep in sku:
                usd_segment_count[sku.split(sep)[0]] += 1
                break

    # 両方に存在する SKU セグメントは ebaymag の可能性が低い（オリジナルの自分の SKU）
    # 非 USD にしか存在しないセグメントは ebaymag が生成した可能性がある
    candidates = []
    for seg in non_usd_segments:
        if seg not in usd_segment_count:
            count = sum(1 for r in non_usd_rows
                        if (r.get("sku") or "").strip().startswith(seg))
            if count >= 5:  # ノイズ除去: 5件以上あるパターンのみ
                candidates.append((seg, count))

    candidates.sort(key=lambda x: -x[1])
    return candidates


def main():
    print()
    print("=" * 60)
    print("  米国 USD 出品フィルタ")
    print("=" * 60)
    print()

    # --- CSV を読み込む ---
    csv_path = find_latest_csv()
    if not csv_path:
        print(f"[エラー] {DATA_DIR} に active_listings_*.csv が見つかりません。")
        sys.exit(1)

    print(f"[OK] CSV を読み込みます: {csv_path}")
    all_rows = load_csv(csv_path)
    print(f"[OK] 全件数: {len(all_rows)} 件")
    print()

    # --- 通貨別に分割する ---
    currency_counts = Counter((r.get("currency") or "(空欄)").strip().upper() for r in all_rows)

    print("  --- 通貨別件数 ---")
    for currency, count in currency_counts.most_common():
        rate = count / len(all_rows) * 100
        print(f"  {currency:10s}: {count:>6} 件 ({rate:5.1f}%)")
    print()

    # USD でフィルタ
    usd_rows = [r for r in all_rows if (r.get("currency") or "").strip().upper() == "USD"]
    non_usd_rows = [r for r in all_rows if (r.get("currency") or "").strip().upper() != "USD"]

    print(f"  抽出前: {len(all_rows):>6} 件")
    print(f"  USD    : {len(usd_rows):>6} 件")
    print(f"  除外   : {len(non_usd_rows):>6} 件")
    print()

    # --- USD 出品の価格帯分布 ---
    print("  --- USD 出品の価格帯分布 ---")
    price_ranges = [(0, 30), (30.01, 100), (100.01, 300), (300.01, float("inf"))]
    for low, high in price_ranges:
        count = 0
        for r in usd_rows:
            try:
                p = float(r.get("price") or "0")
            except ValueError:
                p = 0
            if low <= p <= high:
                count += 1
        high_label = f"${high:.0f}" if high != float("inf") else "$∞"
        print(f"  ${low:>7.0f} 〜 {high_label:>6s}: {count:>6} 件")
    print()

    # --- SKU パターン分析（USD 出品）---
    print("  --- USD 出品の SKU パターン分析 ---")
    print()
    sku_analysis = analyze_sku_patterns(usd_rows)

    # 先頭セグメント（上位20件）
    print("  [SKU 先頭セグメント（区切り文字で分割）上位20件]")
    for seg, count in sku_analysis["first_segment"].most_common(20):
        print(f"  {seg:30s}: {count:>5} 件")
    print()

    # SKU 長さ分布
    print("  [SKU 長さ分布]")
    for length in sorted(sku_analysis["length_dist"].keys()):
        count = sku_analysis["length_dist"][length]
        if length == 0:
            print(f"  (空欄)  : {count:>5} 件")
        else:
            print(f"  {length:>2} 文字 : {count:>5} 件")
    print()

    # --- ebaymag 由来の可能性がある SKU パターン検出 ---
    print("  --- ebaymag 由来の可能性がある SKU パターン ---")
    print("  （非 USD 出品にのみ存在し、USD 出品には存在しないセグメント）")
    print()
    ebaymag_candidates = detect_ebaymag_candidates(usd_rows, non_usd_rows)
    if ebaymag_candidates:
        for seg, count in ebaymag_candidates[:10]:
            print(f"  {seg:30s}: {count:>5} 件（非USD出品のみ）")
    else:
        print("  特定のパターンは検出されませんでした。")
        print("  currency=USD のフィルタだけで十分と思われます。")
    print()

    # --- USD 出品の title が重複していないか確認 ---
    usd_titles = [r.get("title", "") for r in usd_rows]
    unique_titles = len(set(usd_titles))
    dup_titles = len(usd_titles) - unique_titles
    print(f"  --- タイトル重複チェック ---")
    print(f"  USD 出品数     : {len(usd_rows)} 件")
    print(f"  ユニークタイトル: {unique_titles} 件")
    print(f"  重複タイトル    : {dup_titles} 件")
    print()

    # --- フィルタ済み CSV を保存する ---
    output_path = os.path.join(DATA_DIR, "active_listings_usd.csv")
    save_csv(usd_rows, output_path)
    print(f"[OK] フィルタ済み CSV を保存しました: {output_path}")
    print(f"     件数: {len(usd_rows)} 件")
    print()

    # --- 次のステップ ---
    print("=" * 60)
    print("  次に確認すべきこと")
    print("=" * 60)
    print()
    print(f"  1. USD 出品 {len(usd_rows)} 件は想定と合っていますか？")
    print(f"     （自分で出品した米国向け商品の感覚値と比較してください）")
    print()
    print("  2. 上記の SKU パターンに ebaymag 由来のものはありますか？")
    print("     （心当たりがあれば教えてください。追加除外します）")
    print()
    print("  3. タイトル重複が多い場合、ebaymag が USD でも")
    print("     コピー出品を作っている可能性があります。")
    print()
    print("  上記を確認後、Step 2（50件サンプル抽出 → GetItem 補完）に進みます。")


if __name__ == "__main__":
    main()
