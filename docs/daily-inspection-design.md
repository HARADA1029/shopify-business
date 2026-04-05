# 日次レポート設計（監視 + 売上改善提案型）

## 概要

毎日午前3時（JST）に各担当エージェントが自動で点検を実施し、
原田が朝確認できる日次レポートを生成する。

**目的:**
1. 異常検知（ストア運用に影響する問題の早期発見）
2. 売上改善提案（日々のブラッシュアップ候補を抽出）

**原則: 点検・提案のみ。本番反映は原田の承認後に実施。**


## 1. レポート構成

| 区分 | 意味 | 例 |
|------|------|-----|
| 🔴 要対応 | 売上・運用に直接影響する問題 | 価格0の商品、未処理注文、画像なし商品 |
| 🚀 今日やると売上に効く改善 | すぐ実行できる改善提案 | SEO Title 未設定、Collection 未所属、Compare at 未設定 |
| 💡 中期改善候補 | 計画的に取り組む改善案 | Draft 昇格候補、SNS 新規作成、Collection 新設 |
| ✓ 異常なし | 正常確認済み項目 | 画像OK、価格OK、注文OK |


## 2. エージェント別 点検項目

### Phase 1: Shopify 内で完結する項目（実装済み）

#### growth-foundation（集客・SEO）

| # | 区分 | 点検項目 | データソース | 判定基準 |
|---|------|---------|------------|---------|
| 1 | 監視 | 画像 alt text 未設定 | Shopify API | alt が空の画像がある |
| 2 | 🚀 | SEO Title 未設定の Active 商品 | GraphQL | seo.title が空 |
| 3 | 🚀 | Meta Description 未設定 | GraphQL | seo.description が空 |
| 4 | 💡 | Meta Description 80文字未満 | GraphQL | seo.description < 80文字 |
| 5 | 💡 | Collection SEO 未設定 | GraphQL | Collection の seo.title / description が空 |

#### store-setup（ストア設定・UI・導線）

| # | 区分 | 点検項目 | データソース | 判定基準 |
|---|------|---------|------------|---------|
| 1 | 監視 | 商品の公開状態 | Shopify API | Active / Draft の件数 |
| 2 | 監視 | 画像0枚の公開商品 | Shopify API | images が空 |
| 3 | 監視 | 必須ページの公開状態 | Shopify API | Shipping / Return / FAQ / About / Legal が非公開 |
| 4 | 監視 | メニューのリンク切れ | GraphQL | メニュー項目の URL が空 |
| 5 | 🚀 | Collection 未所属の Active 商品 | Shopify API | Collection タグを1つも持たない |
| 6 | 🚀 | Active 商品0件の Collection | Shopify API | Collection 内の Active 商品数 = 0 |
| 7 | 💡 | Draft → Active 昇格候補 | Shopify API | 画像・Type・タグ・説明・価格 全て OK の Draft |
| 8 | 💡 | Draft 昇格ブロッカー集計 | Shopify API | 昇格できない理由の内訳 |

#### fulfillment-ops（配送・在庫）

| # | 区分 | 点検項目 | データソース | 判定基準 |
|---|------|---------|------------|---------|
| 1 | 監視 | 未処理の注文 | Shopify API | unfulfilled 注文の有無 |
| 2 | 🚀 | 在庫0の Active 商品 | Shopify API | inventory_quantity <= 0 |

#### price-auditor（価格監査 + 価格最適化）

| # | 区分 | 点検項目 | データソース | 判定基準 |
|---|------|---------|------------|---------|
| 1 | 監視 | 価格0の商品 | Shopify API | price = 0 |
| 2 | 監視 | Price >= Compare at price | Shopify API | 逆転している |
| 3 | 🚀 | Compare at price 未設定 | Shopify API | compare_at_price が空 → 割引表示で購買促進 |
| 4 | 💡 | 価格帯分布 | Shopify API | $0-50 / $50-100 / $100+ の分布 |

#### catalog-migration-planner（商品データ品質）

| # | 区分 | 点検項目 | データソース | 判定基準 |
|---|------|---------|------------|---------|
| 1 | 🚀 | Product Type 未設定/Other | Shopify API | product_type が空 or "Other" |
| 2 | 🚀 | Tags 未設定 | Shopify API | tags が空 |
| 3 | 💡 | Vendor 未設定 | Shopify API | vendor が空 |
| 4 | 💡 | Description 100文字未満 | Shopify API | body_html < 100文字 |
| 5 | 💡→🚀 | Goods & Accessories Collection 新設 | Shopify API | G&A 商品が7件以上なら 🚀 |


### Phase 2: 外部導線チェック（将来実装）

#### growth-foundation（外部導線）

| # | 区分 | 点検項目 | データソース | 判定基準 |
|---|------|---------|------------|---------|
| 1 | 🚀 | hd-bodyscience.com → Shopify 導線 | HTTP アクセス | Shopify URL のリンク・バナーの有無 |
| 2 | 🚀 | eBay SNS プロフィールリンク | 各 SNS ページ確認 | Shopify URL が設置されているか |
| 3 | 💡 | Shopify 専用 SNS アカウント | 各プラットフォーム確認 | 未作成プラットフォームの特定 |
| 4 | 💡 | SNS 投稿頻度・最終更新日 | SNS API / 手動 | 作成済みなら投稿状況を確認 |

**Phase 2 の実装方針:**
- hd-bodyscience.com: HTTP GET でページ取得 → Shopify URL の有無を検索
- eBay SNS: 各プロフィールページを HTTP GET → Shopify URL リンクの有無を検索
- Shopify 専用 SNS: 設定ファイルにアカウント情報を記載し、存在チェック

**外部導線の制約:**
- 既存 eBay 用 SNS（Instagram: hdstore777 / Facebook: hdstore111 / Pinterest: hdstore777）は投稿に使わない
- プロフィールリンクに Shopify URL を設置するのは可
- Shopify 集客用の投稿は Shopify 専用の新規 SNS アカウントで行う

**提案時の分類:**
1. 既存資産の安全な活用（hd-bodyscience.com、既存 SNS プロフィール）
2. 新規 SNS アカウント作成（Shopify 専用）
3. SEO 導線（Google 検索からの自然流入）


## 3. 日次レポートテンプレート

```
# HD Toys Store Japan 日次レポート
**日時:** 2026-04-05 03:00 JST

## ストア状態
- Active: 40件 / Draft: 60件

## 🔴 要対応（0件）
- なし

## 🚀 今日やると売上に効く改善（n件）

### growth-foundation
- SEO Title 未設定: n/40件 → 設定で検索結果の表示を改善
- Meta Description 未設定: n/40件 → 設定でCTR向上

### store-setup
- Collection 未所属の Active 商品: n件 → タグ追加で導線改善
- Active 商品0件の Collection: n件 → 商品追加 or メニューから非表示

### price-auditor
- Compare at price 未設定: n/40件 → 設定すると割引表示で購買促進

### catalog-migration-planner
- Product Type 未設定/Other: n件 → 適切な Type を設定して Collection に反映
- Tags 未設定: n件 → タグ追加で Collection・検索性を改善

### fulfillment-ops
- 在庫0の Active 商品: n件 → sold out 放置は顧客体験低下

## 💡 中期改善候補（n件）

### growth-foundation
- Collection SEO 未設定: n件 → 設定でカテゴリページの検索流入を改善

### store-setup
- Draft → Active 昇格候補: n/60件（画像・Type・タグ・説明・価格 全て OK）
- Draft 昇格ブロッカー: 画像なし: n件, Type 未設定: n件, ...

### price-auditor
- 価格帯分布: $0-50: n件 / $50-100: n件 / $100+: n件

### catalog-migration-planner
- Goods & Accessories: n件（7件以上で Collection 新設を検討）

## ✓ 異常なし
- 画像 alt text: 全n枚設定済み
- SEO Title / Meta Description: 全n件設定済み
- 未処理注文: なし

## 外部導線
- 外部導線チェック: Phase 2 で実装予定（hd-bodyscience.com / SNS）
```


## 4. 実装方法

### 方法A: GitHub Actions（推奨・現在使用中）

```yaml
# .github/workflows/daily-inspection.yml
name: Daily Store Inspection

on:
  schedule:
    - cron: '0 18 * * *'  # UTC 18:00 = JST 03:00

jobs:
  inspect:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install requests

      - name: Run inspection
        env:
          SHOPIFY_STORE: ${{ secrets.SHOPIFY_STORE }}
          SHOPIFY_ACCESS_TOKEN: ${{ secrets.SHOPIFY_ACCESS_TOKEN }}
          CHATWORK_API_TOKEN: ${{ secrets.CHATWORK_API_TOKEN }}
          CHATWORK_ROOM_ID: ${{ secrets.CHATWORK_ROOM_ID }}
        run: python ops/monitoring/daily_inspection.py

      - name: Save report
        uses: actions/upload-artifact@v4
        with:
          name: daily-report-${{ github.run_id }}
          path: ops/monitoring/reports/
          retention-days: 90
```

**メリット:**
- サーバー管理不要
- シークレット管理が安全
- ログが GitHub 上に残る
- 無料枠で十分（月2000分）

### 方法B: ローカル Windows タスクスケジューラ

```
schtasks /create /tn "ShopifyDailyInspection" /tr "python C:\Users\mitsu\shopify-business\ops\monitoring\daily_inspection.py" /sc daily /st 03:00
```

### 方法C: Claude Code の schedule 機能

Claude Code の `/schedule` コマンドでリモートエージェントとして定期実行。


## 5. 安全設計

### 絶対ルール

| ルール | 詳細 |
|--------|------|
| **読み取り専用** | 点検スクリプトは Shopify API / eBay API の読み取りのみ |
| **書き込み禁止** | 商品の公開・非公開・価格変更・在庫変更は一切行わない |
| **eBay 不変** | eBay API は GetItem / GetMyeBaySelling のみ。書き込み API は使用しない |
| **提案のみ** | レポートに「推奨アクション」を記載するが、実行しない |
| **承認フロー** | 原田がレポートを確認し、承認した項目のみ手動 or 別スクリプトで実行 |

### スクリプトの権限分離

```
daily_inspection.py    → 読み取り専用。書き込み API を一切 import しない
apply_changes.py       → 原田の承認後に手動実行。変更内容をログに記録
```


## 6. 実装フェーズ

### Phase 1（実装済み）: Shopify 内で完結する項目

- 全エージェントの監視項目
- SEO Title / Meta Description チェック
- Collection カバレッジ（未所属・0件 Collection）
- Draft 昇格候補の抽出
- Compare at price 活用提案
- 価格帯分布
- 在庫0の Active 商品チェック
- Goods & Accessories Collection 新設判定

### Phase 2（将来実装）: 外部導線チェック

- hd-bodyscience.com → Shopify 導線（HTTP GET でリンク有無を確認）
- eBay SNS プロフィールの Shopify URL 設置状況
- Shopify 専用 SNS アカウントの作成状況・投稿頻度

### Phase 3: 通知追加

```
点検 → レポート生成 → Slack / Email に自動通知 → 原田が確認
```

### Phase 4: 半自動化

```
点検 → 軽微な修正は自動実行 → 重要な変更は承認待ち
```

自動実行の対象（原田の事前承認が必要）:
- eBay で sold → Shopify を自動で非公開（在庫同期）
- SEO Title / alt text が空の新商品に自動設定
- 404 エラーのリダイレクト自動設定

### Phase 5: 完全自動化

```
点検 → AI が判断 → 安全な変更は自動実行 → 危険な変更は承認待ち
```
