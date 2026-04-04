# Shopify 下書き投入 データ準備方針

## 1. 作るべきスクリプト一覧（優先順）

| 順位 | スクリプト | 役割 | 入力 | 出力 |
|:---:|-----------|------|------|------|
| 1 | **`prepare_shopify_data.py`** | GetItem で Description / Weight を取得し、Shopify 用にデータを整形して1ファイルに統合 | final_100.csv | shopify_ready_100.csv |
| 2 | **`download_images.py`** | eBay CDN から画像をローカルにダウンロード | shopify_ready_100.csv | product-migration/data/images/{item_id}/ |

### なぜ2本に分けるか

- `prepare_shopify_data.py` は GetItem API コール（100件 × 0.5秒 ≒ 50秒）
- `download_images.py` は画像ダウンロード（100件 × 平均6枚 = 600枚 × 0.3秒 ≒ 3分）
- API コールと画像 DL は障害モードが異なる。分けておけば片方だけ再実行できる


## 2. Description の取得・整形方針

### 現状の eBay Description 構造

全商品が共通 HTML テンプレートを使用:

```
[CSS スタイル定義]
[商品タイトル（H1）]
"Description"
  → 商品説明本文（1〜3行）
"Shipping"
  → 配送方法の説明（eBay 固有）
"International Buyers - Please Note:"
  → 関税注意書き（eBay 固有）
```

### Shopify 向け整形ルール

```
1. HTML から <style> タグと CSS を除去
2. HTML タグを除去してプレーンテキスト化
3. テキストを3セクションに分割:
   - Description セクション → 商品説明として採用
   - Shipping セクション → 除去（Shopify の Shipping Policy で別途記載）
   - International Buyers セクション → 除去（同上）
4. 商品説明を Shopify 用 HTML に再構成
```

### Description がない・抽出できない場合のフォールバック

```html
<p>Authentic {product_type} imported directly from Japan.</p>
<p>This item is pre-owned. Please refer to the photos for detailed condition.</p>
```

### Shopify Description の最終フォーマット

```html
<p>{商品説明テキスト（eBay から抽出）}</p>

<h3>Details</h3>
<ul>
  <li>Condition: {condition_name}</li>
  <li>Brand: {vendor}</li>
  <li>Franchise: {franchise}（あれば）</li>
  <li>Ships from Japan</li>
</ul>
```


## 3. 画像ダウンロード方針

### eBay 画像 URL の構造

```
https://i.ebayimg.com/00/s/MTA4MFgxMDgw/z/K24AAeSwz8lpwLy~/$_57.JPG?set_id=880000500F
```

- `$_57.JPG` → 1600px 版（最大サイズ）
- 直接 HTTP GET でダウンロード可能（認証不要）

### ダウンロード仕様

```
保存先: product-migration/data/images/{item_id}/
ファイル名: {item_id}_01.jpg, {item_id}_02.jpg, ...
サイズ: 元のサイズのまま（リサイズ不要。Shopify 側で自動リサイズ）
形式: JPEG（元のまま）
同時接続: 1（eBay CDN への負荷軽減）
リトライ: 3回まで（404 / タイムアウト時）
```

### ダウンロード後の検証

```
1. ファイルサイズが 1KB 未満 → 破損の可能性 → 警告
2. 画像が0枚の商品 → リストアップ（手動対応が必要）
3. ダウンロード失敗 → エラーログに記録、スキップして続行
```

### Shopify へのアップロード方法（後工程）

画像の Shopify アップロードは、ストア開設後に以下のいずれかで行う:
- **(a) Shopify Admin API** で自動アップロード（要 API キー）
- **(b) Shopify CSV インポート** で画像 URL を指定（外部ホスト or Shopify CDN）
- **(c) 手動アップロード**（100件なら現実的）

→ 初期はダウンロードまで。アップロード方法はストア開設時に決定。


## 4. その他の補完方針

### Product Type

| 方針 | 詳細 |
|------|------|
| 自動判定 | `detect_product_type()` で88件判定済み |
| 残り12件 | shopify_ready_100.csv に `product_type` 列を追加。判定不能は `"Other"` |
| 最終確認 | 原田がざっと目視確認。明らかに間違っているものがあれば修正 |

### Collection

`collection` 列は **初期投入時に商品を振り分けるメインコレクション** を表す。
将来的にタグベースの Automated Collection（フランチャイズ別など）を追加する際は
別の仕組みで対応するため、ここでは Product Type ベースの1コレクションのみを指定する。

Product Type → Collection のマッピング:

| Product Type | Collection（初期投入用） |
|---|---|
| Action Figures | Action Figures |
| Scale Figures | Figures & Statues |
| Plush & Soft Toys | Plush & Soft Toys |
| Trading Cards | Trading Cards |
| Video Games | Video Games |
| Media & Books | Media & Books |
| Electronic Toys | Electronic Toys |
| Model Kits | Model Kits |
| Tokusatsu Toys / Goods | Action Figures に統合 |
| (不明) / Other | Other |

### Tags

以下を自動でカンマ区切り文字列に統合:

```
tags = [
    condition,           # "Good", "Near Mint" 等
    franchise,           # "Pokemon", "Dragon Ball" 等
    product_type,        # "Action Figures" 等
    "Japan Import",      # 全商品共通
]
```

### Weight

| 状況 | 対応 |
|------|------|
| GetItem で取得できる | そのまま使用（lbs → g に変換） |
| 0 lbs 0 oz（全商品がこの可能性大） | Product Type 別デフォルト値を設定 |

Product Type 別デフォルト Weight:

| Product Type | デフォルト重量 |
|---|---|
| Action Figures | 500g |
| Scale Figures | 800g |
| Plush & Soft Toys | 400g |
| Trading Cards | 100g |
| Video Games | 300g |
| Media & Books | 500g |
| Electronic Toys | 300g |
| Other | 500g |

### SKU

```
Shopify SKU = "EB-" + eBay item_id
例: EB-125977075682
```


## 5. shopify_ready_100.csv の出力カラム

```
item_id              eBay 商品ID
sku                  Shopify SKU（EB-{item_id}）
title                Shopify 用タイトル（eBay タイトルをそのまま使用）
description_html     Shopify Description（HTML）
product_type         Product Type
collection           初期投入用メインコレクション名
vendor               Vendor
tags                 タグ（カンマ区切り）
price                Shopify 暫定価格
compare_at_price     eBay 価格（Compare at price に流用可能）
condition            Condition（Shopify タグ用）
weight               重量（g）
weight_unit          "g"
image_urls           eBay 画像 URL（パイプ区切り）
image_local_paths    ローカル画像パス（download_images.py 実行後に埋まる）
```


## 6. Shopify 下書き投入までの残作業

```
現在地 ←
  │
  ① prepare_shopify_data.py を実行
  │  → shopify_ready_100.csv を生成（GetItem 100件コール）
  │
  ② download_images.py を実行
  │  → 画像約600枚をローカルにダウンロード
  │
  ③ 原田が shopify_ready_100.csv を最終確認
  │  → Product Type, Description, 価格をざっとチェック
  │
  ④ Shopify ストア開設（store-setup 担当）
  │  → プラン選定、テーマ設定、コレクション作成
  │
  ⑤ Shopify への投入方法を決定
  │  → CSV インポート / Admin API / 手動
  │
  ⑥ 下書きとして投入 → 動作確認 → 公開
```


## 7. オーナーが確認すべきこと

### prepare_shopify_data.py 実行前

| # | 確認事項 | 推奨 |
|---|---------|------|
| 1 | SKU フォーマット `EB-{item_id}` でよいか | Yes |
| 2 | Description のフォーマットでよいか | Yes（後から修正可能） |
| 3 | Weight のデフォルト値でよいか | Yes（概算で十分） |
| 4 | Collection の分類でよいか | Yes（Automated Collection で後から調整可能） |

### prepare_shopify_data.py 実行後

| # | 確認事項 |
|---|---------|
| 1 | Description が正しく抽出されているか（先頭10件を目視） |
| 2 | Product Type の自動判定結果に明らかな誤りがないか |
| 3 | Tags が適切か |
