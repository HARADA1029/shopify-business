# ============================================================
# 画像ダウンロードスクリプト
#
# 【役割】
#   shopify_ready_100.csv の image_urls から画像をダウンロードし、
#   ローカルに保存する。完了後 image_local_paths 列を更新する。
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/download_images.py
#
# 【保存先】
#   product-migration/data/images/{item_id}/{item_id}_01.jpg, ...
# ============================================================

import csv
import os
import sys
import time
from datetime import datetime

import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "product-migration", "data")
IMAGES_DIR = os.path.join(DATA_DIR, "images")

REQUEST_INTERVAL = 0.3
MAX_RETRIES = 3
TIMEOUT = 15  # 秒
MIN_FILE_SIZE = 1024  # 1KB 未満は破損の疑い


def load_csv(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_csv(rows, filepath, fieldnames):
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def download_one(url, filepath):
    """1枚の画像をダウンロードする。成功なら True"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=TIMEOUT, stream=True)
            if resp.status_code == 200:
                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                # サイズチェック
                size = os.path.getsize(filepath)
                if size < MIN_FILE_SIZE:
                    return False, f"小さすぎ({size}B)"
                return True, None
            else:
                if attempt == MAX_RETRIES:
                    return False, f"HTTP {resp.status_code}"
        except requests.exceptions.Timeout:
            if attempt == MAX_RETRIES:
                return False, "タイムアウト"
        except Exception as e:
            if attempt == MAX_RETRIES:
                return False, str(e)[:50]
        time.sleep(1)

    return False, "リトライ超過"


def main():
    print()
    print("=" * 60)
    print("  画像ダウンロード")
    print("=" * 60)
    print()

    # --- CSV 読み込み ---
    csv_path = os.path.join(DATA_DIR, "shopify_ready_100.csv")
    rows = load_csv(csv_path)
    print(f"[OK] shopify_ready_100.csv 読み込み: {len(rows)} 件")

    # --- images ディレクトリ作成 ---
    os.makedirs(IMAGES_DIR, exist_ok=True)

    # --- ダウンロード ---
    total_images = 0
    downloaded = 0
    failed = 0
    skipped_empty = 0
    warnings = []  # (item_id, 理由)
    zero_image_items = []

    for i, row in enumerate(rows, 1):
        item_id = row.get("item_id", "")
        urls_raw = row.get("image_urls", "") or ""

        # パイプ区切りの URL をリスト化
        urls = [u.strip() for u in urls_raw.split("|") if u.strip()]

        if not urls:
            zero_image_items.append(item_id)
            row["image_local_paths"] = ""
            print(f"  [{i:>3}/100] {item_id} → 画像なし")
            continue

        # 商品ごとのフォルダ
        item_dir = os.path.join(IMAGES_DIR, item_id)
        os.makedirs(item_dir, exist_ok=True)

        local_paths = []
        item_ok = 0
        item_fail = 0

        for idx, url in enumerate(urls, 1):
            total_images += 1
            filename = f"{item_id}_{idx:02d}.jpg"
            filepath = os.path.join(item_dir, filename)

            # 既にダウンロード済みならスキップ
            if os.path.exists(filepath) and os.path.getsize(filepath) >= MIN_FILE_SIZE:
                local_paths.append(filepath)
                downloaded += 1
                item_ok += 1
                continue

            ok, err = download_one(url, filepath)
            if ok:
                local_paths.append(filepath)
                downloaded += 1
                item_ok += 1
            else:
                failed += 1
                item_fail += 1
                warnings.append((item_id, f"画像{idx}: {err}"))

            time.sleep(REQUEST_INTERVAL)

        row["image_local_paths"] = " | ".join(local_paths)

        status = f"{item_ok}枚OK"
        if item_fail:
            status += f" {item_fail}枚失敗"
        print(f"  [{i:>3}/100] {item_id} → {status} (全{len(urls)}枚)")

    print()

    # --- CSV 更新 ---
    fieldnames = list(rows[0].keys())
    save_csv(rows, csv_path, fieldnames=fieldnames)
    print(f"[OK] shopify_ready_100.csv 更新（image_local_paths 列）")
    print()

    # --- レポート ---
    print("=" * 60)
    print("  ダウンロードレポート")
    print("=" * 60)
    print()
    print(f"  商品数     : {len(rows)} 件")
    print(f"  画像総数   : {total_images} 枚")
    print(f"  成功       : {downloaded} 枚")
    print(f"  失敗       : {failed} 枚")
    print(f"  画像0枚商品: {len(zero_image_items)} 件")
    print()

    if zero_image_items:
        print("  --- 画像0枚の商品（要手動対応）---")
        for iid in zero_image_items:
            r = next((r for r in rows if r["item_id"] == iid), {})
            print(f"  {iid} | {r.get('title', '')[:60]}")
        print()

    if warnings:
        print(f"  --- ダウンロード警告（{len(warnings)} 件）---")
        for iid, reason in warnings[:20]:
            print(f"  {iid} | {reason}")
        if len(warnings) > 20:
            print(f"  ... 他 {len(warnings) - 20} 件")
        print()

    # 画像枚数分布
    img_counts = []
    for row in rows:
        paths = (row.get("image_local_paths", "") or "").strip()
        cnt = len(paths.split(" | ")) if paths else 0
        img_counts.append(cnt)

    print("  --- ダウンロード後の画像枚数分布 ---")
    from collections import Counter
    dist = Counter(img_counts)
    for cnt in sorted(dist.keys()):
        print(f"  {cnt:>2} 枚: {dist[cnt]} 件")
    print()

    avg = sum(img_counts) / len(img_counts) if img_counts else 0
    under3 = sum(1 for c in img_counts if c < 3)
    print(f"  平均: {avg:.1f} 枚")
    print(f"  3枚未満: {under3} 件")
    print()

    # ディスク使用量
    total_size = 0
    for root_dir, dirs, files in os.walk(IMAGES_DIR):
        for f in files:
            total_size += os.path.getsize(os.path.join(root_dir, f))
    print(f"  ディスク使用量: {total_size / 1024 / 1024:.1f} MB")
    print()

    print("  --- 次のステップ ---")
    if failed == 0 and len(zero_image_items) == 0:
        print("  ✓ 全画像のダウンロードに成功。Shopify 下書き投入に進めます。")
    else:
        if len(zero_image_items) > 0:
            print(f"  ⚠ 画像0枚の商品が {len(zero_image_items)} 件。手動で画像を準備するか除外を検討。")
        if failed > 0:
            print(f"  ⚠ {failed} 枚のダウンロードに失敗。再実行で回復する可能性あり。")


if __name__ == "__main__":
    main()
