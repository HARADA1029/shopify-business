# 最初の14日間 実行計画

## 概要

Shopify ストア立ち上げの最初の14日間は「設計・方針決定・検証」に集中する。
実装は設計が固まった部分から段階的に進める。

**ゴール:** Day 14 終了時点で、小規模テスト移行が安定し、
本番移行（300〜500 SKU）に進める判断材料が揃った状態にする。

---

## Day 1〜3: 基盤設計フェーズ

**稼働エージェント:** project-orchestrator, store-setup, channel-sync-strategy

### Day 1: プロジェクト基盤と Shopify プラン選定
- [orchestrator] プロジェクト計画の最終確認、リスク一覧の整備
- [store-setup] Shopify プラン比較表の作成（Basic / Shopify / Advanced）
- [store-setup] 取引手数料・機能差の整理
- [channel-sync] 在庫同期の既存 SaaS 調査開始（LitCommerce, Codisto, Sellbrite 等）
- **意思決定:** Shopify プランの仮決定

### Day 2: ストア構造とテーマ設計
- [store-setup] テーマ候補3〜5件の比較（無料テーマ中心で開始）
- [store-setup] コレクション（カテゴリ）階層の設計案
- [store-setup] ナビゲーション構造の設計案
- [channel-sync] 在庫同期方式の比較表作成（SaaS / 自前 API / バッチ）
- **意思決定:** テーマの仮選定

### Day 3: 同期方針と移行準備
- [channel-sync] 二重販売防止のアーキテクチャ案を2〜3パターン作成
- [channel-sync] 各パターンのリスク・コスト・実装難易度を比較
- [store-setup] 必須ページの構成案（項目リスト）
- [orchestrator] Day 1〜3 の成果レビュー、未決事項の整理
- **意思決定:** 在庫同期方式の方針決定（SaaS or 自前 or ハイブリッド）

---

## Day 4〜7: 詳細設計フェーズ

**稼働エージェント:** +catalog-migration-planner, +fulfillment-ops

### Day 4: 商品移行の設計開始
- [catalog-migration] eBay 商品データの構造分析（出品データのサンプル取得）
- [catalog-migration] 移行対象 SKU の選定基準を策定
- [channel-sync] 選定した同期方式の詳細設計
- [fulfillment-ops] eBay 既存の配送フロー棚卸し

### Day 5: マッピングと変換ルール
- [catalog-migration] eBay カテゴリ → Shopify コレクションのマッピング案
- [catalog-migration] 商品タイトル・説明文の変換ルール策定
- [fulfillment-ops] 配送料金テーブルの設計（国別・重量別）
- [fulfillment-ops] 配送業者の比較表作成

### Day 6: 画像・バリデーション・返品
- [catalog-migration] 画像移行方針の決定（CDN 直接参照 or 再アップロード）
- [catalog-migration] バリデーションルールの設計
- [fulfillment-ops] 返品ポリシー案の策定
- [fulfillment-ops] 関税・禁制品の国別注意事項リスト
- **意思決定:** 画像移行方式の決定

### Day 7: 中間レビュー
- [orchestrator] Day 4〜7 の成果レビュー
- [orchestrator] 全エージェントの設計成果物を横断チェック
- [orchestrator] テスト移行の開始判定基準を策定
- 全エージェントの設計ドキュメントを docs/ に集約
- **意思決定:** テスト移行の Go / No-Go 判定

---

## Day 8〜11: 初回テスト移行フェーズ

**稼働エージェント:** +growth-foundation

### Day 8: Shopify ストア実構築開始
- [store-setup] Shopify アカウント作成（まだパスワード保護状態）
- [store-setup] テーマのインストールと基本カスタマイズ
- [store-setup] 基本設定の投入（通貨、言語、配送ゾーン）
- [growth-foundation] 競合ストアの調査・ベンチマーク

### Day 9: 移行スクリプトと同期設定
- [catalog-migration] 移行スクリプトの初期開発 or SaaS ツール設定
- [channel-sync] 在庫同期の初期設定（テスト環境）
- [growth-foundation] SEO 方針の策定（URL 設計、メタタグテンプレート）
- [store-setup] 必須ページの作成開始

### Day 10: 初回テスト移行の実行（10〜20 SKU）
- [catalog-migration] テスト移行の実行（少数 SKU で検証）
- [catalog-migration] 移行データのバリデーション実行
- [channel-sync] テスト商品の在庫同期動作確認
- [store-setup] テスト商品のストア上での表示確認
- **検証:** 商品データの品質、画像表示、在庫同期の動作

### Day 11: 初回テスト移行の結果検証
- [catalog-migration] 問題点の洗い出しと変換ルールの修正
- [channel-sync] 同期エラーの調査と対策
- [fulfillment-ops] テスト注文による配送フローの確認
- [growth-foundation] メール取得導線の設計

---

## Day 12〜14: 修正反映・拡張テスト・判定フェーズ

### Day 12: テスト結果の修正反映
- [catalog-migration] Day 11 で発見した問題の修正を反映
- [catalog-migration] 変換ルール・バリデーションルールの改訂
- [channel-sync] 同期設定の調整・再テスト
- [store-setup] テスト商品の表示崩れ等の修正
- **検証:** 修正後の 10〜20 SKU で再度バリデーション通過を確認

### Day 13: 拡張テスト移行（30〜50 SKU）
- [catalog-migration] 拡張テスト移行の実行（カテゴリを広げて 30〜50 SKU）
- [catalog-migration] 全件バリデーション実行
- [channel-sync] 拡張分の在庫同期動作確認（同時更新の挙動含む）
- [fulfillment-ops] 配送料金の Shopify 設定投入と検証
- **検証:** カテゴリ横断で移行品質が安定しているか確認

### Day 14: 本番移行可否の判定と次期計画
- [orchestrator] 全エージェントの成果物最終レビュー
- [orchestrator] 本番移行 Go/No-Go 判定チェックリストの実施
- [orchestrator] 発見済み課題の残件リスト作成
- [orchestrator] 次の14日間（本番移行〜ソフトローンチ）の計画策定
- **意思決定:** 300〜500 SKU 本番移行に進めるか Go / No-Go 判定

---

## マイルストーン一覧

| Day | マイルストーン | 判定基準 |
|:---:|---|---|
| 3 | 基盤設計完了 | プラン・テーマ・同期方式が仮決定 |
| 7 | 詳細設計完了 | テスト移行を開始できる設計が揃っている |
| 11 | 初回テスト移行完了 | 10〜20 SKU で商品表示・在庫同期・注文が動作する |
| 14 | 拡張テスト完了・判定材料完備 | 30〜50 SKU で移行品質が安定し、本番移行の Go/No-Go を判定できる |

---

## リスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| 在庫同期の二重販売 | 致命的 | Day 3 で同期方式を決定、Day 10 で初回実機テスト、Day 13 で拡張テスト |
| 商品データの品質不良 | 高 | Day 6 でバリデーション設計、Day 10 で実データ検証、Day 12 で修正反映後に再検証 |
| Shopify テーマが商材に合わない | 中 | Day 2 で3〜5候補を比較、Day 10 で実商品を表示して確認 |
| 配送料金の設定ミス | 中 | Day 11 でテスト注文、Day 13 で拡張テスト時に再確認 |
| スケジュール遅延 | 中 | Day 7 と Day 14 にレビューゲートを設置 |
| テスト移行の問題が多く本番移行に進めない | 中 | Day 12 を修正反映日として確保。Day 14 の判定で No-Go なら次期で再テスト |
