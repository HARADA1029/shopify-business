# ============================================================
# 50件サンプル抽出・分析・マッピング試適用スクリプト
#
# 【役割】
#   1. Active Listings CSV から価格帯で層化した50件サンプルを抽出
#   2. ebay-data-analysis.md の6観点で分析
#   3. category-mapping.md のルールを試適用し自動判定率を計測
#   4. 手動確認が必要な商品を一覧化
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/analyze_sample.py
#
# 【前提】
#   ebay_fetch_listings.py で Active Listings CSV を取得済みであること
# ============================================================

import csv
import os
import random
import re
import sys
from collections import Counter
from datetime import datetime

# --- 設定 ---

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "product-migration", "data")

# 層化抽出の件数配分
STRATIFICATION = [
    # (下限, 上限, 抽出件数)
    (0, 30, 15),
    (30.01, 100, 20),
    (100.01, 300, 10),
    (300.01, float("inf"), 5),
]

# ============================================================
# マッピング辞書（category-mapping.md に基づく）
# ============================================================

# 商品ライン → Product Type の辞書
PRODUCT_LINE_MAP = {
    # Action Figures
    "s.h.figuarts": "Action Figures",
    "shfiguarts": "Action Figures",
    "sh figuarts": "Action Figures",
    "figma": "Action Figures",
    "mafex": "Action Figures",
    "revoltech": "Action Figures",
    "robot spirits": "Action Figures",
    "robot damashii": "Action Figures",
    "d-arts": "Action Figures",
    "ultra-act": "Action Figures",
    "s.h.monsterarts": "Action Figures",
    "shmonsterarts": "Action Figures",
    # Scale Figures
    "banpresto": "Scale Figures",
    "prize figure": "Scale Figures",
    "ichiban kuji": "Scale Figures",
    "pop up parade": "Scale Figures",
    "nendoroid": "Scale Figures",
    "q posket": "Scale Figures",
    "artfx": "Scale Figures",
    "p.o.p": "Scale Figures",
    "portrait of pirates": "Scale Figures",
    "g.e.m.": "Scale Figures",
    "megahouse": "Scale Figures",
    "alter": "Scale Figures",
}

# タイトルキーワード → Product Type（商品ラインで判定できなかった場合の補助）
TYPE_KEYWORDS = {
    "action figure": "Action Figures",
    "model kit": "Model Kits",
    "plastic model": "Model Kits",
    "plamo": "Model Kits",
    "gunpla": "Model Kits",
    "plush": "Plush & Soft Toys",
    "stuffed": "Plush & Soft Toys",
    "soft toy": "Plush & Soft Toys",
    "vintage": "Vintage & Retro Toys",
    "retro": "Vintage & Retro Toys",
    "statue": "Scale Figures",
    "figure": "Scale Figures",  # 最も弱い判定（他にマッチしない場合のみ使う）
}

# 完成品判定キーワード（Model Kit カテゴリだが完成品の場合）
BUILT_KEYWORDS = ["built", "assembled", "painted", "completed", "finished"]

# フランチャイズ辞書
FRANCHISE_MAP = {
    "Dragon Ball": ["dragon ball", "dragonball", "dbz", "db super"],
    "One Piece": ["one piece", "onepiece"],
    "Naruto": ["naruto", "boruto", "shippuden"],
    "Gundam": ["gundam"],
    "Demon Slayer": ["demon slayer", "kimetsu"],
    "My Hero Academia": ["my hero academia", "boku no hero", "mha"],
    "Neon Genesis Evangelion": ["evangelion", "eva unit", "nerv"],
    "Sailor Moon": ["sailor moon"],
    "Pokemon": ["pokemon", "pikachu", "pokémon"],
    "Studio Ghibli": ["ghibli", "totoro", "spirited away", "kiki", "mononoke", "howl"],
    "Jujutsu Kaisen": ["jujutsu kaisen", "jujutsu"],
    "Attack on Titan": ["attack on titan", "shingeki"],
    "Chainsaw Man": ["chainsaw man"],
    "Spy x Family": ["spy x family", "spy family"],
    "Bleach": ["bleach"],
    "Final Fantasy": ["final fantasy"],
    "Saint Seiya": ["saint seiya"],
    "Macross": ["macross", "robotech"],
    "Kamen Rider": ["kamen rider", "masked rider"],
    "Ultraman": ["ultraman"],
}

# Vendor 正規化テーブル
VENDOR_NORMALIZE = {
    "Bandai": ["bandai", "bandai namco"],
    "Banpresto": ["banpresto"],
    "Good Smile Company": ["good smile", "good smile company", "gsc", "goodsmile"],
    "Kotobukiya": ["kotobukiya", "koto"],
    "MegaHouse": ["megahouse", "mega house"],
    "Tamashii Nations": ["tamashii nations", "tamashii"],
    "Kaiyodo": ["kaiyodo"],
    "Medicom Toy": ["medicom", "medicom toy"],
    "Takara Tomy": ["takara tomy", "takara", "tomy"],
    "Funko": ["funko"],
    "Max Factory": ["max factory"],
    "Square Enix": ["square enix", "play arts"],
    "Plex": ["plex"],
    "Hasbro": ["hasbro"],
    "Mattel": ["mattel"],
}

# Condition マッピング
CONDITION_MAP = {
    "new": "Mint",
    "brand new": "Mint",
    "new with tags": "Mint",
    "new with box": "Mint",
    "new other": "Near Mint",
    "new without tags": "Near Mint",
    "open box": "Near Mint",
    "like new": "Near Mint",
    "used - like new": "Near Mint",
    "very good": "Good",
    "used - very good": "Good",
    "good": "Good",
    "used - good": "Good",
    "used": "Good",
    "pre-owned": "Good",
    "acceptable": "Fair",
    "used - acceptable": "Fair",
    "for parts or not working": "_EXCLUDE_",
    "for parts": "_EXCLUDE_",
}


# ============================================================
# CSV 読み込み
# ============================================================

def find_latest_csv():
    """data/ ディレクトリから最新の active_listings CSV を探す"""
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


# ============================================================
# サンプル抽出
# ============================================================

def extract_price(row):
    """価格を float に変換する。変換できない場合は 0"""
    try:
        return float(row.get("price", "0") or "0")
    except ValueError:
        return 0.0


def stratified_sample(rows):
    """価格帯で層化したサンプルを抽出する"""
    sample = []
    for low, high, count in STRATIFICATION:
        stratum = [r for r in rows if low <= extract_price(r) <= high]
        if len(stratum) <= count:
            sample.extend(stratum)
        else:
            sample.extend(random.sample(stratum, count))
    return sample


# ============================================================
# マッピング判定
# ============================================================

def detect_product_type(row):
    """Product Type を自動判定する。判定できなければ空文字を返す"""
    title = (row.get("title") or "").lower()
    category = (row.get("category_name") or "").lower()

    # 1. 商品ラインで判定
    for keyword, ptype in PRODUCT_LINE_MAP.items():
        if keyword in title:
            # 完成品キーワードがある場合は Scale Figures に修正
            if ptype == "Action Figures" or ptype == "Scale Figures":
                pass  # そのまま
            if keyword in ("model kit", "gunpla", "plamo"):
                if any(bw in title for bw in BUILT_KEYWORDS):
                    return "Scale Figures"
            return ptype

    # 2. eBay カテゴリで判定
    if "model" in category and "kit" in category:
        if any(bw in title for bw in BUILT_KEYWORDS):
            return "Scale Figures"
        return "Model Kits"
    if "plush" in category or "stuffed" in category:
        return "Plush & Soft Toys"
    if "vintage" in category or "pre-1990" in category:
        return "Vintage & Retro Toys"

    # 3. タイトルキーワードで判定（弱い判定。"figure" は最後の手段）
    # "figure" 以外のキーワードを先にチェック
    for keyword, ptype in TYPE_KEYWORDS.items():
        if keyword == "figure":
            continue  # 後回し
        if keyword in title:
            return ptype

    # 4. 上記いずれでもない → 手動確認リスト
    return ""


def detect_franchise(row):
    """Franchise を自動判定する"""
    title = (row.get("title") or "").lower()
    # Item Specifics の franchise フィールドがあればそれを優先
    ebay_franchise = (row.get("franchise") or "").strip()
    if ebay_franchise:
        return ebay_franchise

    for franchise, keywords in FRANCHISE_MAP.items():
        for kw in keywords:
            if kw in title:
                return franchise
    return ""


def normalize_vendor(row):
    """Vendor を正規化する"""
    # Item Specifics の brand フィールドを優先
    brand = (row.get("brand") or "").strip()

    # brand が空ならタイトルから抽出を試みる
    sources = [brand, row.get("title") or ""]

    for source in sources:
        source_lower = source.lower()
        for vendor, patterns in VENDOR_NORMALIZE.items():
            for pattern in patterns:
                if pattern in source_lower:
                    return vendor
    return ""


def map_condition(row):
    """Condition を Shopify タグにマッピングする"""
    condition = (row.get("condition_name") or "").strip().lower()
    if not condition:
        return ""

    # 完全一致を先にチェック
    if condition in CONDITION_MAP:
        return CONDITION_MAP[condition]

    # 部分一致で探す
    for key, value in CONDITION_MAP.items():
        if key in condition:
            return value

    return ""


# ============================================================
# 分析・レポート生成
# ============================================================

def analyze_and_report(sample, all_rows, output_path):
    """6観点分析 + マッピング試適用の結果をレポートファイルに出力する"""
    lines = []

    def w(text=""):
        lines.append(text)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    w("=" * 70)
    w(f"  50件サンプル分析レポート（{timestamp}）")
    w("=" * 70)
    w()
    w(f"  全件数: {len(all_rows)} 件")
    w(f"  サンプル件数: {len(sample)} 件")
    w()

    # === 観点1: 商品タイプの分布 ===
    w("=" * 70)
    w("  観点1: 商品タイプの分布")
    w("=" * 70)
    w()

    type_results = {}
    type_unresolved = []
    for row in sample:
        ptype = detect_product_type(row)
        type_results[row["item_id"]] = ptype
        if not ptype:
            type_unresolved.append(row)

    type_counts = Counter(v for v in type_results.values() if v)
    for ptype, count in type_counts.most_common():
        w(f"  {ptype:25s}: {count} 件")
    w(f"  {'(判定不能)':25s}: {len(type_unresolved)} 件")
    w()

    auto_type_rate = (len(sample) - len(type_unresolved)) / len(sample) * 100
    w(f"  Product Type 自動判定率: {auto_type_rate:.1f}%")
    w()

    # === 観点2: フランチャイズの分布 ===
    w("=" * 70)
    w("  観点2: フランチャイズの分布")
    w("=" * 70)
    w()

    franchise_results = {}
    franchise_unresolved = []
    for row in sample:
        franchise = detect_franchise(row)
        franchise_results[row["item_id"]] = franchise
        if not franchise:
            franchise_unresolved.append(row)

    franchise_counts = Counter(v for v in franchise_results.values() if v)
    for franchise, count in franchise_counts.most_common():
        w(f"  {franchise:30s}: {count} 件")
    w(f"  {'(判定不能)':30s}: {len(franchise_unresolved)} 件")
    w()

    auto_franchise_rate = (len(sample) - len(franchise_unresolved)) / len(sample) * 100
    w(f"  Franchise 自動判定率: {auto_franchise_rate:.1f}%")
    w()

    # === 観点3: メーカーの分布 ===
    w("=" * 70)
    w("  観点3: メーカー（Vendor）の分布")
    w("=" * 70)
    w()

    brand_filled = sum(1 for r in sample if (r.get("brand") or "").strip())
    w(f"  Brand フィールド入力率: {brand_filled}/{len(sample)} ({brand_filled/len(sample)*100:.1f}%)")
    w()

    vendor_results = {}
    vendor_unresolved = []
    for row in sample:
        vendor = normalize_vendor(row)
        vendor_results[row["item_id"]] = vendor
        if not vendor:
            vendor_unresolved.append(row)

    vendor_counts = Counter(v for v in vendor_results.values() if v)
    for vendor, count in vendor_counts.most_common():
        w(f"  {vendor:25s}: {count} 件")
    w(f"  {'(判定不能)':25s}: {len(vendor_unresolved)} 件")
    w()

    auto_vendor_rate = (len(sample) - len(vendor_unresolved)) / len(sample) * 100
    w(f"  Vendor 自動判定率: {auto_vendor_rate:.1f}%")
    w()

    # === 観点4: 価格帯の分布 ===
    w("=" * 70)
    w("  観点4: 価格帯の分布")
    w("=" * 70)
    w()

    # 全件の価格帯分布
    w("  [全件の価格帯分布]")
    for low, high, _ in STRATIFICATION:
        high_label = f"${high:.0f}" if high != float("inf") else "$∞"
        count = sum(1 for r in all_rows if low <= extract_price(r) <= high)
        rate = count / len(all_rows) * 100 if all_rows else 0
        w(f"  ${low:>7.0f} 〜 {high_label:>6s}: {count:>6} 件 ({rate:5.1f}%)")
    w()

    # サンプルの価格帯分布
    w("  [サンプルの価格帯分布]")
    for low, high, _ in STRATIFICATION:
        high_label = f"${high:.0f}" if high != float("inf") else "$∞"
        count = sum(1 for r in sample if low <= extract_price(r) <= high)
        w(f"  ${low:>7.0f} 〜 {high_label:>6s}: {count:>4} 件")
    w()

    # === 観点5: Condition 表記の実態 ===
    w("=" * 70)
    w("  観点5: Condition 表記の実態")
    w("=" * 70)
    w()

    # 全件の Condition 分布
    w("  [全件の Condition 分布]")
    condition_raw = Counter((r.get("condition_name") or "(空欄)").strip() for r in all_rows)
    for cond, count in condition_raw.most_common():
        w(f"  {cond:30s}: {count:>6} 件")
    w()

    # マッピング結果
    condition_results = {}
    condition_unresolved = []
    for row in sample:
        mapped = map_condition(row)
        condition_results[row["item_id"]] = mapped
        if not mapped:
            condition_unresolved.append(row)

    w("  [サンプルの Condition マッピング結果]")
    cond_counts = Counter(v for v in condition_results.values() if v)
    for cond, count in cond_counts.most_common():
        w(f"  {cond:15s}: {count} 件")
    w(f"  {'(判定不能)':15s}: {len(condition_unresolved)} 件")
    w()

    auto_condition_rate = (len(sample) - len(condition_unresolved)) / len(sample) * 100
    w(f"  Condition 自動判定率: {auto_condition_rate:.1f}%")
    w()

    # === 観点6: 画像の状況 ===
    w("=" * 70)
    w("  観点6: 画像の状況")
    w("=" * 70)
    w()

    image_counts = []
    for r in sample:
        try:
            ic = int(r.get("image_count") or "0")
        except ValueError:
            ic = 0
        image_counts.append(ic)

    avg_images = sum(image_counts) / len(image_counts) if image_counts else 0
    under_3 = sum(1 for c in image_counts if c < 3)
    w(f"  平均画像枚数: {avg_images:.1f} 枚")
    w(f"  画像3枚未満の商品: {under_3}/{len(sample)} ({under_3/len(sample)*100:.1f}%)")
    w()

    # 全件の画像枚数分布
    w("  [全件の画像枚数分布]")
    all_img = []
    for r in all_rows:
        try:
            all_img.append(int(r.get("image_count") or "0"))
        except ValueError:
            all_img.append(0)
    img_dist = Counter(all_img)
    for count in sorted(img_dist.keys()):
        w(f"  {count:>2} 枚: {img_dist[count]:>6} 件")
    w()

    # === マッピング自動判定率サマリー ===
    w("=" * 70)
    w("  マッピング自動判定率サマリー")
    w("=" * 70)
    w()

    # 4項目すべて判定できた割合
    all_resolved = 0
    for row in sample:
        iid = row["item_id"]
        if (type_results.get(iid) and franchise_results.get(iid)
                and vendor_results.get(iid) and condition_results.get(iid)):
            all_resolved += 1
    all_rate = all_resolved / len(sample) * 100

    w(f"  Product Type : {auto_type_rate:5.1f}%")
    w(f"  Franchise    : {auto_franchise_rate:5.1f}%")
    w(f"  Vendor       : {auto_vendor_rate:5.1f}%")
    w(f"  Condition    : {auto_condition_rate:5.1f}%")
    w(f"  ---")
    w(f"  全4項目判定  : {all_rate:5.1f}% ({all_resolved}/{len(sample)})")
    w()

    target = 80
    if all_rate >= target:
        w(f"  → 目標 {target}% を達成。マッピングルールは現状で十分です。")
    else:
        w(f"  → 目標 {target}% 未達。辞書・ルールの拡充が必要です。")
    w()

    # === 手動確認リスト ===
    w("=" * 70)
    w("  手動確認リスト（4項目のいずれかが判定不能）")
    w("=" * 70)
    w()

    manual_check = []
    for row in sample:
        iid = row["item_id"]
        missing = []
        if not type_results.get(iid):
            missing.append("ProductType")
        if not franchise_results.get(iid):
            missing.append("Franchise")
        if not vendor_results.get(iid):
            missing.append("Vendor")
        if not condition_results.get(iid):
            missing.append("Condition")
        if missing:
            manual_check.append({
                "item_id": iid,
                "title": row.get("title", ""),
                "price": row.get("price", ""),
                "missing": ", ".join(missing),
            })

    if manual_check:
        for item in manual_check:
            w(f"  [{item['item_id']}] ${item['price']}")
            w(f"    Title  : {item['title'][:80]}")
            w(f"    不足項目: {item['missing']}")
            w()
    else:
        w("  なし（全件自動判定済み）")
        w()

    # レポート保存
    report_text = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    return report_text


# ============================================================
# メイン処理
# ============================================================

def main():
    print()
    print("=" * 60)
    print("  50件サンプル抽出・分析・マッピング試適用")
    print("=" * 60)
    print()

    # --- CSV を探す ---
    csv_path = find_latest_csv()
    if not csv_path:
        print(f"[エラー] {DATA_DIR} に active_listings_*.csv が見つかりません。")
        print("  先に ebay_fetch_listings.py を実行してください。")
        sys.exit(1)

    print(f"[OK] CSV を読み込みます: {csv_path}")
    all_rows = load_csv(csv_path)
    print(f"[OK] 全件数: {len(all_rows)} 件")

    # --- 50件サンプル抽出 ---
    random.seed(42)  # 再現性のためシード固定
    sample = stratified_sample(all_rows)
    print(f"[OK] サンプル抽出: {len(sample)} 件")

    # sample_50.csv を保存
    sample_path = os.path.join(DATA_DIR, "sample_50.csv")
    with open(sample_path, "w", newline="", encoding="utf-8-sig") as f:
        if sample:
            writer = csv.DictWriter(f, fieldnames=sample[0].keys())
            writer.writeheader()
            writer.writerows(sample)
    print(f"[OK] サンプル保存: {sample_path}")

    # --- 分析 + マッピング試適用 ---
    report_path = os.path.join(DATA_DIR, "analysis_report.txt")
    report = analyze_and_report(sample, all_rows, report_path)

    print(f"[OK] レポート保存: {report_path}")
    print()

    # レポートをコンソールにも表示
    print(report)


if __name__ == "__main__":
    main()
