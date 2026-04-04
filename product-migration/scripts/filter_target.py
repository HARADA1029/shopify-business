# ============================================================
# Shopify 対象商材の再フィルタスクリプト
#
# 【役割】
#   active_listings_usd.csv を「日本のおもちゃ・ホビー・コレクター商品全般」
#   の基準でフィルタし、以下の3ファイルに分類する:
#     - active_listings_target.csv  : 採用（Shopify 移行候補）
#     - manual_review.csv           : 保留（手動確認が必要）
#     - excluded.csv                : 除外（対象外）
#
# 【対象商材の定義】
#   採用: フィギュア、ぬいぐるみ、グッズ、トレカ、設定資料、アニメBlu-ray、
#         マンガ、レトロゲーム、特撮玩具、プラモデル・模型全般、ホビー商品全般
#   除外: K-pop、一般音楽CD/レコード、汎用ガジェット、ファッション書籍、
#         ホビー性の低い一般雑貨
#
# 【実行方法】
#   cd C:\Users\mitsu\shopify-business
#   python product-migration/scripts/filter_target.py
# ============================================================

import csv
import os
import re
import sys
from collections import Counter

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "product-migration", "data")

# ============================================================
# 除外ルール（タイトルにマッチしたら除外）
# ============================================================

# K-pop アーティスト名（大文字小文字区別なし）
KPOP_ARTISTS = [
    "bts", "twice", "shinee", "ateez", "stray kids", "blackpink",
    "enhypen", "seventeen", "aespa",
    "itzy", "(g)i-dle", "g idle", "gidle", "newjeans",
    "le sserafim", "monsta x", "got7", "red velvet",
    "mamamoo", "dreamcatcher", "loona", "fromis", "everglow",
    "onew", "taemin", "shinee key", "minho shinee",
    # 短すぎる名前は正確なパターンで指定
    "nct 127", "nct dream", "nct wish", "nct dojaejung",
    "tomorrow x together",
    "exo-l", "exo official", "exo planet", "exo cbx",
    # K-pop であることを示す一般キーワード
    "k-pop", "kpop", "k pop",
    # K-pop レーベル・事務所
    "hybe", "sm entertainment", "jyp entertainment", "yg entertainment",
]

# 汎用ガジェット・周辺機器
GADGET_KEYWORDS = [
    "xim apex", "xim4",
    "converter mouse keyboard",
    "usb hub", "hdmi splitter", "hdmi switch",
    "robot vacuum", "vacuum cleaner", "roborock",
    "golf iron", "golf club", "golf set",
]

# ファッション・非ホビー書籍（ホビー系アートブックは除外しない）
FASHION_KEYWORDS = [
    "maison margiela", "supreme streetwear", "fashion magazine",
    "vogue", "elle magazine",
]

# 一般音楽を示すパターン（K-pop と合わせて使う）
# ※ アニメ・ゲームのサントラは除外しないよう注意
GENERAL_MUSIC_KEYWORDS = [
    # 注意: アニメ・ゲーム・シティポップのレコードは採用対象
    # vinyl record / vinyl lp は誤除外が多いため除外リストから削除済み
]


def is_excluded(title_lower):
    """除外対象かどうかを判定する。除外理由を返す。対象外なら空文字"""
    # K-pop チェック
    for artist in KPOP_ARTISTS:
        if artist in title_lower:
            return f"K-pop ({artist})"

    # 汎用ガジェット
    for kw in GADGET_KEYWORDS:
        if kw in title_lower:
            return f"汎用機器 ({kw})"

    # ファッション系
    for kw in FASHION_KEYWORDS:
        if kw in title_lower:
            return f"非ホビー ({kw})"

    # 一般音楽レコード（アニメ・ゲーム関連でないもの）
    for kw in GENERAL_MUSIC_KEYWORDS:
        if kw in title_lower:
            return f"一般音楽 ({kw})"

    return ""


# ============================================================
# 採用ルール（タイトルにマッチしたら採用確定）
# ============================================================

# ホビー・コレクター商品を示すキーワード
HOBBY_KEYWORDS = [
    # フィギュア全般
    "figure", "figurine", "figma", "figuarts", "nendoroid",
    "statue", "bust",
    "artfx", "p.o.p", "ichiban kuji", "pop up parade", "q posket",
    "prize", "banpresto",
    # ぬいぐるみ・マスコット
    "plush", "stuffed", "doll", "mascot",
    # グッズ
    "acrylic stand", "acrylic keychain", "can badge", "pin badge",
    "rubber strap", "clear file", "tapestry", "poster",
    "shikishi", "autograph", "mini towel",
    # トレーディングカード
    "trading card", "tcg", "ccg", "pokemon card", "yugioh",
    "union arena", "weiss schwarz", "carddass",
    "holo", "holographic", "foil card",
    # 模型・プラモデル全般（アニメ・非アニメ問わず）
    "model kit", "plastic model", "plamo", "gunpla",
    "tamiya", "hasegawa", "aoshima", "fujimi", "bandai spirits",
    "1/35", "1/48", "1/72", "1/144", "1/100",
    # ホビーブランド
    "bandai", "takara", "tomy", "kotobukiya", "megahouse",
    "good smile", "max factory", "kaiyodo", "medicom",
    "revoltech", "mafex", "hot toys", "freeing",
    "furyu", "sega prize", "taito prize",
    "plex", "x-plus", "art storm",
    # 特撮・戦隊
    "power rangers", "sentai", "kamen rider", "masked rider",
    "ultraman", "godzilla", "kaiju", "tokusatsu",
    "megazord", "morpher", "henshin",
    # アニメ・ゲーム関連メディア
    "anime", "manga", "artbook", "art book", "art works",
    "visual book", "setting material", "illustration book",
    "blu-ray", "bluray",
    "soundtrack", "ost", "original sound",
    # レトロゲーム・ゲーム関連
    "super famicom", "famicom", "game boy", "gameboy",
    "sega saturn", "sega genesis", "mega drive",
    "dreamcast", "neo geo", "pc engine",
    "nintendo", "game & watch", "game and watch",
    "retro game",
    # 一般コレクター系
    "vintage", "retro", "collectible", "collection",
    "limited edition", "rare", "japan exclusive",
    "import japan", "japanese", "japan import",
    # ゲーム関連コレクターズアイテム
    "amiibo",
    # レゴ
    "lego",
    # ボーカロイド
    "hatsune miku", "vocaloid", "miku",
    # MTG / TCG 追加
    "magic the gathering", "mtg ",
    # 追加ゲームプラットフォーム
    "neogeo", "neo geo", "neo-geo",
    "playstation", "play station",
    "ps1", "ps2", "ps3", "ps4", "ps5",
    "xbox", "wii", "switch",
    # 追加フランチャイズ・キャラクター
    "pikmin",
    "yoshitomo nara", "nara yoshitomo",
    # コミック・ノベル
    "comics complete", "complete set",
    "light novel", "visual novel",
    # ゲーム関連追加
    "fighting game", "arcade",
    # スポーツカード
    "rookie card", "baseball card", "bbm ",
    # アパレル（ゲーム・アニメコラボ）
    "gelato pique",
    # たまごっち
    "tamagotchi",
    # 鉄道模型
    "n gauge", "kato n", "tomix", "railway model", "model train",
    # 書籍（アニメ・ゲーム・ラノベ系）
    "book set", "vol.", "vol ",
    # スクエニ関連
    "square enix", "nier", "enix",
    # マクドナルド コラボ玩具
    "mcdonald",
    # レコード（コレクター系）
    "vinyl", "city pop",
]

# フランチャイズ辞書（これがタイトルに含まれていれば採用確定）
FRANCHISE_KEYWORDS = [
    "dragon ball", "dragonball", "dbz",
    "one piece", "onepiece",
    "naruto", "boruto",
    "gundam",
    "demon slayer", "kimetsu",
    "my hero academia",
    "evangelion",
    "sailor moon",
    "pokemon", "pikachu",
    "jujutsu kaisen",
    "attack on titan", "shingeki",
    "chainsaw man",
    "spy x family",
    "bleach",
    "final fantasy",
    "saint seiya",
    "macross", "robotech",
    "studio ghibli", "totoro", "spirited away",
    "transformers",
    "digimon",
    "yu-gi-oh", "yugioh",
    "doraemon",
    "hello kitty", "sanrio",
    "disney",
    "marvel",
    "star wars",
    "avengers",
    "batman", "dc comics",
    "mario", "zelda", "kirby", "splatoon",
    "monster hunter",
    "persona",
    "fate/", "fate stay", "fate grand",
    "sword art online",
    "re:zero", "re zero",
    "konosuba",
    "love live",
    "hololive", "vtuber",
    "touhou",
    "initial d",
    "dr. slump", "dr slump",
    "card captor sakura", "cardcaptor",
    "obey me",
    "ensemble stars",
    "project sekai",
    "high school dxd",
    "violet evergarden",
    "flowers art works",
    "king kong",
    "donkey kong",
]


def is_adopted(title_lower):
    """採用確定かどうかを判定する"""
    for kw in HOBBY_KEYWORDS:
        if kw in title_lower:
            return True
    for kw in FRANCHISE_KEYWORDS:
        if kw in title_lower:
            return True
    return False


# ============================================================
# メイン処理
# ============================================================

def load_csv(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_csv(rows, filepath):
    if not rows:
        # 空でもヘッダーだけ書く
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            f.write("")
        return
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) + ["_filter_reason"])
        writer.writeheader()
        writer.writerows(rows)


def main():
    print()
    print("=" * 60)
    print("  Shopify 対象商材 再フィルタ")
    print("=" * 60)
    print()

    usd_csv = os.path.join(DATA_DIR, "active_listings_usd.csv")
    if not os.path.exists(usd_csv):
        print(f"[エラー] {usd_csv} が見つかりません。")
        sys.exit(1)

    rows = load_csv(usd_csv)
    print(f"[OK] USD 出品を読み込みました: {len(rows)} 件")
    print()

    adopted = []     # 採用
    excluded = []    # 除外
    manual = []      # 保留（手動確認）

    exclude_reasons = Counter()
    adopt_count_hobby = 0
    adopt_count_franchise = 0

    for row in rows:
        title_lower = (row.get("title") or "").lower()
        row_with_reason = dict(row)

        # 1. まず除外チェック（除外が最優先）
        exclude_reason = is_excluded(title_lower)
        if exclude_reason:
            row_with_reason["_filter_reason"] = exclude_reason
            excluded.append(row_with_reason)
            exclude_reasons[exclude_reason.split(" (")[0]] += 1
            continue

        # 2. 採用チェック
        if is_adopted(title_lower):
            row_with_reason["_filter_reason"] = "auto_adopted"
            adopted.append(row_with_reason)
            continue

        # 3. どちらにもマッチしない → 保留
        row_with_reason["_filter_reason"] = "manual_review"
        manual.append(row_with_reason)

    # --- 結果表示 ---
    print("  --- フィルタ結果 ---")
    print(f"  採用（target）: {len(adopted):>5} 件")
    print(f"  保留（review）: {len(manual):>5} 件")
    print(f"  除外（excluded）: {len(excluded):>5} 件")
    print(f"  合計           : {len(rows):>5} 件")
    print()

    # 除外理由の内訳
    print("  --- 除外理由の内訳 ---")
    for reason, count in exclude_reasons.most_common():
        print(f"  {reason:20s}: {count:>5} 件")
    print()

    # 保留の件数が多い場合、タイトルサンプルを表示
    print(f"  --- 保留商品のサンプル（先頭20件）---")
    for row in manual[:20]:
        title = (row.get("title") or "")[:75]
        price = row.get("price", "")
        print(f"  ${price:>7s} | {title}")
    if len(manual) > 20:
        print(f"  ... 他 {len(manual) - 20} 件")
    print()

    # 採用商品の価格帯分布
    print("  --- 採用商品の価格帯分布 ---")
    ranges = [(0, 30), (30.01, 100), (100.01, 300), (300.01, float("inf"))]
    for low, high in ranges:
        count = 0
        for r in adopted:
            try:
                p = float(r.get("price") or "0")
            except ValueError:
                p = 0
            if low <= p <= high:
                count += 1
        high_label = f"${high:.0f}" if high != float("inf") else "$∞"
        print(f"  ${low:>7.0f} 〜 {high_label:>6s}: {count:>5} 件")
    print()

    # --- CSV 保存 ---
    target_path = os.path.join(DATA_DIR, "active_listings_target.csv")
    review_path = os.path.join(DATA_DIR, "manual_review.csv")
    excluded_path = os.path.join(DATA_DIR, "excluded.csv")

    save_csv(adopted, target_path)
    save_csv(manual, review_path)
    save_csv(excluded, excluded_path)

    print(f"[OK] 採用   : {target_path}")
    print(f"[OK] 保留   : {review_path}")
    print(f"[OK] 除外   : {excluded_path}")
    print()

    # --- 次のステップ ---
    print("=" * 60)
    print("  次に確認すべきこと")
    print("=" * 60)
    print()
    print(f"  1. 採用 {len(adopted)} 件は母集団として妥当ですか？")
    print(f"     （初期移行 300〜500 SKU を選べる規模があるか）")
    print()
    print(f"  2. 保留 {len(manual)} 件のサンプルを見て、")
    print(f"     採用に回すべき商品群・除外に回すべき商品群があれば教えてください。")
    print()
    print(f"  3. 除外 {len(excluded)} 件の内訳は妥当ですか？")
    print(f"     誤除外されている商品群があれば教えてください。")
    print()
    print("  確認後、target.csv から50件を再抽出 → GetItem 補完 → 再分析に進みます。")


if __name__ == "__main__":
    main()
