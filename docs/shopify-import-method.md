# Shopify 商品投入方法の比較と方針

## 1. 3方式の比較

| 項目 | CSV インポート | Admin API | 手動投入 |
|------|:---:|:---:|:---:|
| **セットアップ** | なし（Shopify 標準機能） | API キー取得 + スクリプト開発 | なし |
| **画像の扱い** | 画像 URL を CSV に記載 → Shopify が自動取得 | API で画像をアップロード | 1枚ずつ手動アップ |
| **下書き投入** | `Status` 列で `draft` を指定可能 | `status: "draft"` で投入可能 | 保存時に「下書き」を選択 |
| **100件の所要時間** | CSV 変換5分 + インポート待ち数分 | スクリプト開発1〜2時間 + 実行数分 | 1件5分 × 100 = 約8時間 |
| **エラー時の対応** | インポートエラーレポートで確認 | スクリプトでハンドリング可能 | その場で修正 |
| **再現性** | CSV ファイルが残る | スクリプトが残る | なし |
| **Collection 自動振り分け** | CSV の `Collection` 列は無視される※ | API で Collection に追加可能 | 手動で追加 |
| **将来の拡張（残り400件）** | 同じ CSV 形式で追加可能 | 同じスクリプトで追加可能 | 現実的でない |

※ Shopify CSV インポートでは Collection 列は直接指定できない。
  代わりに Automated Collection（タグ条件ベース）で自動振り分けするか、
  インポート後に手動 or API で Collection に追加する。

### 画像の扱いの詳細

| 方式 | 画像の流れ |
|------|-----------|
| **CSV** | CSV に eBay 画像 URL を記載 → Shopify がインポート時に URL から自動ダウンロード → Shopify CDN にホスト |
| **API** | ローカル画像をスクリプトから API でアップロード → Shopify CDN にホスト |
| **手動** | ローカル画像を1枚ずつ管理画面からアップロード |

**CSV 方式の場合、ローカルにダウンロードした画像ファイルは直接使わない。**
eBay CDN の URL を CSV に記載すれば、Shopify が直接取得する。
ただし eBay CDN の URL が将来無効になるリスクがあるため、
ローカルバックアップは保持しておく。


## 2. 推奨方式

### 第一候補: CSV インポート

**理由:**

1. **追加のセットアップが不要** — Shopify 管理画面の標準機能
2. **画像を eBay URL から直接取得** — ローカル画像のアップロード作業が不要
3. **CSV 変換スクリプトは既存データから5分で生成可能**
4. **下書き投入が可能** — `Status: draft` で全件下書き状態で入る
5. **100件なら CSV の行数制限（約15,000行）に余裕** — 今回は415行
6. **残り400件追加時も同じ形式で対応可能**

### CSV の制約と対策

| 制約 | 対策 |
|------|------|
| Collection を直接指定できない | Automated Collection をタグベースで作成（Product Type タグで自動振り分け） |
| Metafield は CSV で設定できない | 初期は不要。必要になったら API で追加 |
| インポート中は商品の編集ができない | 100件なら数分で完了。影響は軽微 |


## 3. Shopify 商品CSV 形式への変換方針

### Shopify CSV の必須カラム

```
Handle                  URL 用のスラッグ（自動生成可能）
Title                   商品タイトル
Body (HTML)             商品説明（HTML）
Vendor                  メーカー/ブランド
Product Category        Shopify の標準カテゴリ（空欄可）
Type                    Product Type
Tags                    カンマ区切りのタグ
Published               公開状態（TRUE/FALSE）
Variant SKU             SKU
Variant Grams           重量（グラム）
Variant Price           販売価格
Variant Compare At Price 取消線価格
Image Src               画像 URL
Image Position          画像の表示順
Status                  draft / active
```

### 変換ルール

| shopify_ready_100.csv | Shopify CSV | 変換 |
|---|---|---|
| title | Handle | タイトルをスラッグ化（小文字・スペースをハイフン・特殊文字除去） |
| title | Title | そのまま |
| description_html | Body (HTML) | そのまま |
| vendor | Vendor | そのまま（空欄なら空欄） |
| product_type | Type | そのまま |
| tags | Tags | そのまま |
| - | Published | `FALSE`（下書きのため） |
| sku | Variant SKU | そのまま |
| weight | Variant Grams | そのまま |
| price | Variant Price | そのまま |
| compare_at_price | Variant Compare At Price | そのまま |
| image_urls | Image Src | パイプ区切りを1行1画像に展開 |
| - | Image Position | 1, 2, 3, ... |
| - | Status | `draft` |

### 複数画像の展開ルール

Shopify CSV では **1画像 = 1行** で表現する。
1つの商品に5枚の画像がある場合、5行になる。
2行目以降は Handle のみ指定し、他のカラムは空欄にする。

```csv
Handle,Title,Body (HTML),Image Src,Image Position,...
my-product,My Product,<p>Description</p>,https://img1.jpg,1,...
my-product,,,https://img2.jpg,2,...
my-product,,,https://img3.jpg,3,...
```

### 変換スクリプト: `convert_to_shopify_csv.py`

```
入力:  shopify_ready_100.csv
出力:  shopify_import.csv（Shopify インポート形式）
行数:  約415行（100商品 × 平均4.2画像）
```


## 4. 追加で必要な準備

### CSV インポート前に必要なこと

| # | 作業 | 担当 | 所要時間 |
|---|------|------|---------|
| 1 | **Shopify ストア開設** | store-setup | プラン選定〜初期設定 |
| 2 | **convert_to_shopify_csv.py の実行** | catalog-migration | 5分 |
| 3 | **Automated Collection の作成** | store-setup | 10分 |
| 4 | **Shipping 設定** | fulfillment-ops | 30分 |

### Automated Collection の設定（タグベース）

インポート後に商品を自動でコレクションに振り分けるため、
以下の Automated Collection を事前に作成する:

| Collection 名 | 条件 |
|---|---|
| Action Figures | Tag = "Action Figures" |
| Figures & Statues | Tag = "Scale Figures" |
| Plush & Soft Toys | Tag = "Plush & Soft Toys" |
| Trading Cards | Tag = "Trading Cards" |
| Video Games | Tag = "Video Games" |
| Media & Books | Tag = "Media & Books" |
| Electronic Toys | Tag = "Electronic Toys" |

→ CSV インポートで Tags が入った時点で自動的に Collection に振り分けられる。


## 5. 下書き投入前チェックリスト

### ストア側の準備

- [ ] Shopify プラン選定・契約完了
- [ ] テーマ選定・基本カスタマイズ完了
- [ ] Automated Collection 作成済み（7コレクション）
- [ ] Shipping ゾーン・料金テーブル設定済み
- [ ] Payment 設定済み（Shopify Payments）
- [ ] 必須ページ作成済み（Shipping Policy, Return Policy, FAQ）
- [ ] ドメイン設定済み（または後回し可）

### データ側の準備

- [x] shopify_ready_100.csv 完成（100件・全カラム埋まり済み）
- [x] 画像ダウンロード完了（415枚・0失敗）
- [ ] convert_to_shopify_csv.py で Shopify 形式に変換
- [ ] 変換後の CSV を原田が最終確認

### 原田の最終確認ポイント

| # | 確認内容 | 確認方法 |
|---|---------|---------|
| 1 | **商品タイトルに問題がないか** | CSV の Title 列を流し見（eBay 向けタイトルがそのまま入っている。必要なら調整） |
| 2 | **Shopify 価格が妥当か** | Variant Price 列をざっと確認（× 0.91 が適用済み） |
| 3 | **Description が正しく整形されているか** | CSV から5件ほど Body (HTML) をブラウザで表示確認 |
| 4 | **画像 URL が有効か** | Image Src の URL を5件ほどブラウザで開いて表示確認 |
| 5 | **出したくない商品が混ざっていないか** | Title + Price を100件流し見 |

### インポート後の確認ポイント

| # | 確認内容 |
|---|---------|
| 1 | 全100件が下書き状態で入っているか |
| 2 | 画像が正しく表示されているか（5件サンプルチェック） |
| 3 | Collection に正しく振り分けられているか |
| 4 | Price / Compare at price が正しいか |
| 5 | テスト注文で checkout が正常に動くか |


## 6. 投入から公開までの流れ

```
現在地 ←
  │
  ① convert_to_shopify_csv.py を実行
  │  → shopify_import.csv を生成
  │
  ② 原田が CSV を最終確認（5〜10分）
  │
  ③ Shopify ストア開設・基本設定
  │  → プラン契約、テーマ、Collection、Shipping、Payment
  │
  ④ Shopify 管理画面で CSV インポート
  │  → Settings > Import products > shopify_import.csv
  │  → 全件 draft 状態で投入
  │
  ⑤ インポート後の確認（10〜15分）
  │  → 画像・価格・Collection・Description を目視確認
  │
  ⑥ 問題なければ、段階的に公開
  │  → まず10件公開 → 動作確認 → 残り90件公開
```
