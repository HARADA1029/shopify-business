# 日次定期点検フロー設計

## 概要

毎日午前3時（JST）に各担当エージェントが自動で点検を実施し、
原田が朝確認できる日次レポートを生成する。

**原則: 点検・提案のみ。本番反映は原田の承認後に実施。**


## 1. エージェント別 日次点検項目

### growth-foundation（集客・SEO・外部導線）

#### Shopify 内部 SEO

| # | 点検項目 | データソース | 判定基準 |
|---|---------|------------|---------|
| 1 | Google Analytics のセッション数・PV | GA4 API | 前日比で異常な増減がないか |
| 2 | 検索流入キーワード上位10 | Search Console API | 新しいキーワードの出現、順位変動 |
| 3 | 商品ページの SEO スコア | Shopify API | SEO Title / Meta Description / alt text 未設定の商品 |
| 4 | 404 エラーの発生 | Search Console API | クロールエラーがあれば報告 |
| 5 | Collection ページのインデックス状況 | Search Console API | 未インデックスのページ |

#### 外部導線（既存資産活用）

| # | 点検項目 | データソース | 判定基準 |
|---|---------|------------|---------|
| 6 | hd-bodyscience.com → Shopify 導線 | サイト確認 | 内部リンク・バナー設置の改善余地 |
| 7 | 既存 eBay SNS のプロフィールリンク | 各SNSプロフィール | Shopify URL が設置されているか（投稿は行わない） |

#### 外部導線（新規作成）

| # | 点検項目 | データソース | 判定基準 |
|---|---------|------------|---------|
| 8 | Shopify 専用 SNS アカウント | 各プラットフォーム | 未作成なら作成候補を提案 |
| 9 | SNS 投稿頻度・エンゲージメント | SNS API / 手動 | 作成済みなら投稿状況を確認 |

**外部導線の制約:**
- 既存 eBay 用 SNS（Instagram: hdstore777 / Facebook: hdstore111 / Pinterest: hdstore777）は投稿に使わない
- プロフィールリンクに Shopify URL を設置するのは可
- Shopify 集客用の投稿は Shopify 専用の新規 SNS アカウントで行う

**提案時の整理方法:**
外部導線の提案は以下の3方向で分類する:
1. 既存資産の安全な活用（hd-bodyscience.com、既存SNSプロフィール）
2. 新規 SNS アカウント作成（Shopify 専用）
3. SEO 導線（Google 検索からの自然流入）

### store-setup（ストア設定・UI）

| # | 点検項目 | データソース | 判定基準 |
|---|---------|------------|---------|
| 1 | 商品の公開状態 | Shopify API | Active / Draft の件数変動 |
| 2 | 画像の読み込み状態 | Shopify API | 画像0枚の公開商品がないか |
| 3 | テーマのエラー | Shopify API | テーマのステータス |
| 4 | 必須ページの公開状態 | Shopify API | Shipping / Return / FAQ が非公開になっていないか |
| 5 | メニューのリンク切れ | Shopify API | メニュー項目の URL が有効か |

### fulfillment-ops（配送・運用）

| # | 点検項目 | データソース | 判定基準 |
|---|---------|------------|---------|
| 1 | 未処理の注文 | Shopify API | unfulfilled 注文が24時間以上放置されていないか |
| 2 | Shipping ゾーン設定 | Shopify API | 送料テーブルに変更がないか |
| 3 | 在庫数の異常 | Shopify API | 在庫0の公開商品（sold out のまま放置）|
| 4 | eBay との在庫乖離 | eBay API（読み取りのみ）| Shopify で active だが eBay で売れた商品がないか |

### price-auditor（価格監査）

| # | 点検項目 | データソース | 判定基準 |
|---|---------|------------|---------|
| 1 | 価格異常 | Shopify API | Price > Compare at price の商品がないか |
| 2 | 価格0の商品 | Shopify API | 無料で購入できてしまう商品がないか |
| 3 | Compare at price 未設定 | Shopify API | 設定漏れの商品 |
| 4 | 為替レート変動 | 外部 API | USD/JPY が大きく動いた場合に警告 |

### catalog-migration-planner（商品データ）

| # | 点検項目 | データソース | 判定基準 |
|---|---------|------------|---------|
| 1 | Product Type 未設定の商品 | Shopify API | "Other" のままの商品数 |
| 2 | Vendor 未設定の商品 | Shopify API | Vendor が空の商品数 |
| 3 | Tags 未設定の商品 | Shopify API | Tags が空の商品 |
| 4 | Description が短すぎる商品 | Shopify API | body_html が100文字未満 |


## 2. 日次レポートテンプレート

```
====================================================
  HD Toys Store Japan 日次点検レポート
  {date} 03:00 JST
====================================================

■ ストア状態
  Active: {n} 件 / Draft: {n} 件
  昨日の注文: {n} 件（売上 ${amount}）
  未処理注文: {n} 件

■ 要対応（今日やるべきこと）
  🔴 {緊急度高の項目}
  🟡 {中程度の項目}

■ 提案（改善候補）
  💡 {SEO 改善提案}
  💡 {UI 改善提案}
  💡 {価格改善提案}

■ 異常なし
  ✓ 画像: 全商品に画像あり
  ✓ 価格: 異常なし
  ✓ ページ: 全ページ公開中
  ✓ メニュー: リンク切れなし

■ 在庫同期（eBay ↔ Shopify）
  ⚠ 要確認: {n} 件（eBay で sold だが Shopify で active）
  ✓ 問題なし: {n} 件

■ 外部導線
  [既存資産活用]
    hd-bodyscience.com: {改善提案 or 「導線設置済み」}
    eBay SNS プロフィールリンク: {Shopify URL 設置済み / 未設置}

  [新規 SNS]
    Shopify 専用アカウント: {作成状況 / 作成候補}
    投稿状況: {直近の投稿有無}

■ 詳細
  [growth-foundation]
    セッション: {n}（前日比 {+/-n}%）
    検索流入 Top 3: {keyword1}, {keyword2}, {keyword3}

  [price-auditor]
    価格異常: {n} 件
    為替: USD/JPY {rate}（前日比 {+/-}%）

====================================================
  次のアクション候補（原田の承認待ち）
====================================================
  1. {具体的なアクション}
  2. {具体的なアクション}
```


## 3. 実装方法

### 方法A: GitHub Actions（推奨）

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
        run: pip install requests python-dotenv

      - name: Run inspection
        env:
          SHOPIFY_STORE: ${{ secrets.SHOPIFY_STORE }}
          SHOPIFY_ACCESS_TOKEN: ${{ secrets.SHOPIFY_ACCESS_TOKEN }}
          EBAY_APP_ID: ${{ secrets.EBAY_APP_ID }}
          EBAY_TOKEN: ${{ secrets.EBAY_TOKEN }}
        run: python ops/monitoring/daily_inspection.py

      - name: Save report
        uses: actions/upload-artifact@v4
        with:
          name: daily-report-${{ github.run_id }}
          path: ops/monitoring/reports/
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

**メリット:** シンプル。外部サービス不要
**デメリット:** PCが起動していないと実行されない

### 方法C: Claude Code の schedule 機能

Claude Code の `/schedule` コマンドでリモートエージェントとして定期実行。

**メリット:** Claude が直接点検と提案を行える
**デメリット:** 長期安定性は要検証

### 推奨: 初期は方法A（GitHub Actions）

理由:
- PCの起動状態に依存しない
- シークレットを安全に管理できる
- レポートが GitHub Artifacts として残る
- 将来的に Slack / Email 通知も追加しやすい


## 4. 安全設計

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

### トークンの権限

| 用途 | トークン | 権限 |
|------|---------|------|
| 日次点検用 | 専用の読み取り専用トークン（将来分離） | read_products, read_orders, read_content のみ |
| 変更適用用 | 現在のフルアクセストークン | write_* 含む（原田が手動実行時のみ使用） |

初期は現在のトークンを共用し、運用が安定したら読み取り専用トークンに分離する。


## 5. 将来の拡張案

### Phase 1: 現在（提案のみ）

```
点検 → レポート生成 → 原田が確認 → 手動で対応
```

### Phase 2: 通知追加

```
点検 → レポート生成 → Slack / Email に自動通知 → 原田が確認
```

実装: GitHub Actions の最後に Slack Webhook or SendGrid で通知

### Phase 3: 半自動化

```
点検 → 軽微な修正は自動実行 → 重要な変更は承認待ち
```

自動実行の対象（原田の事前承認が必要）:
- eBay で sold → Shopify を自動で非公開（在庫同期）
- SEO Title / alt text が空の新商品に自動設定
- 404 エラーのリダイレクト自動設定

### Phase 4: 完全自動化

```
点検 → AI が判断 → 安全な変更は自動実行 → 危険な変更は承認待ち
```

対象:
- 為替変動に応じた価格自動調整（閾値内）
- 新商品の自動投入パイプライン
- 在庫同期の完全自動化
