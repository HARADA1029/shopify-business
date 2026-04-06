# 改善提案システム設計

## 概要

日次レポート（監視 + 改善提案）を軸に、エージェント間で情報を受け渡し、
外部データ × 自社データ × 実績評価 を組み合わせて、
提案の質を継続的に高める仕組み。

「自動学習」＝ memory・履歴・評価結果・提案ルールを蓄積し、
次回の提案精度を上げる運用上の学習ループ。


## 1. エージェント間の情報受け渡し設計

### 共有データストア: `ops/monitoring/shared_state.json`

```json
{
  "weekly_focus": {
    "category": "Trading Cards",
    "week": "2026-W14",
    "set_by": "growth-foundation",
    "actions": {
      "products_to_add": ["draft_id_1", "draft_id_2"],
      "articles_to_write": ["Top 5 Rare Pokemon Cards"],
      "sns_posts": ["pokemon-lugia", "pokemon-charizard"],
      "internal_links": [{"from": 4468, "to": 3932}],
      "cta_improvements": []
    },
    "results": {}
  },
  "active_experiments": [],
  "adopted_proposals": [],
  "proposal_history": []
}
```

### エージェント別の入出力

| エージェント | 書き込む情報 | 読み取る情報 |
|---|---|---|
| **growth-foundation** | 重点カテゴリ決定、記事案、SNS案、競合分析 | SC/GA4データ、実験結果 |
| **store-setup** | Shopify設定変更の結果、UI変更結果 | 重点カテゴリ、デザイン改善案 |
| **catalog-migration-planner** | 商品追加結果、Draft昇格結果 | 重点カテゴリ、Shopify追加候補 |
| **project-orchestrator** | 週次評価、採用/廃止判断 | 全エージェントの結果 |

### 受け渡しフロー

```
日次 03:00: daily_inspection.py が shared_state.json を読み込み
  → 前日の結果を評価
  → 当日の提案を生成（重点カテゴリに沿って）
  → 提案を shared_state.json に書き込み
  → レポート生成

日中: 原田 or Claude が提案を実行
  → 実行結果を shared_state.json に記録

翌日 03:00: 結果を自動評価
  → 良ければスコアを上げる
  → 悪ければ提案ロジックを調整
```


## 2. memory / 履歴保存ルール

### 保存先: `ops/monitoring/proposal_history.json`

```json
[
  {
    "id": "P-2026-04-06-001",
    "date": "2026-04-06",
    "type": "article",
    "category": "Trading Cards",
    "proposal": "Top 5 Rare Pokemon Cards 記事を作成",
    "source": "growth-foundation",
    "data_basis": "SC: pokemon card 11 impressions, Shopify: TC Active 1件",
    "expected_effect": "SC clicks +5/week, Shopify TC sessions +3/week",
    "status": "adopted",
    "implemented_date": "2026-04-07",
    "actual_result": null,
    "evaluated_date": null,
    "score_adjustment": 0,
    "tags": ["trading-cards", "pokemon", "article", "seo"]
  }
]
```

### 保存タイミング

| イベント | 保存内容 |
|---------|---------|
| 提案生成時 | proposal + expected_effect + data_basis |
| 原田が採用時 | status → "adopted" |
| 実装完了時 | implemented_date |
| 7日後に自動評価 | actual_result + score_adjustment |
| 30日後に最終評価 | 長期効果の判定 |

### 保存しないもの（メモリに保存）

- エージェントの運用方針 → Claude memory
- 原田の好み・フィードバック → Claude memory
- プロジェクト全体の状態 → Claude memory


## 3. 提案スコアリングルール

### スコア計算式

```
total_score = 
    売上近接度 × 3
  + 実装容易度 × 2
  + データ根拠 × 2
  + 競合比較優位 × 1
  + 重点カテゴリ一致 × 2
  + 過去成功率 × 1
```

### 各軸の定義

| 軸 | 1点 | 2点 | 3点 |
|---|---|---|---|
| **売上近接度** | 間接的（SEO改善等） | 送客導線（CTA等） | 直接購入（商品追加等） |
| **実装容易度** | 複数ツール連携必要 | API 1回で完了 | 設定変更のみ |
| **データ根拠** | 推測ベース | 部分データあり | GA4/SC 実データ裏付け |
| **競合比較優位** | 自社判断のみ | 競合事例あり | 競合で効果実証済み |
| **重点カテゴリ一致** | 別カテゴリ | 関連カテゴリ | 今週の重点カテゴリ |
| **過去成功率** | 初提案 | 類似提案で効果不明 | 類似提案で効果あり |


## 4. 週次競合比較設計

### 実行タイミング: 毎週月曜 03:00（日次レポートの拡張版）

### 比較対象

| カテゴリ | 競合 | 比較ポイント |
|---------|------|------------|
| **Shopify** | Solaris Japan, Japan Figure Store, Super Anime Store | 新商品、価格帯、プロモーション、UI変更 |
| **ブログ** | NekoFigs, Solaris Blog, MyFigureCollection | 記事テーマ、構成、SEO キーワード |
| **SNS** | 上記ストアのInstagram/Pinterest | 投稿テーマ、画像パターン、エンゲージメント |

### 週次レポートに含める項目

```
## 週次改善レポート（毎週月曜）

### 先週の結果
  - 重点カテゴリ: Trading Cards
  - 追加商品: 3件 Active化
  - 記事: 2件公開
  - SNS: 5投稿
  - GA4 送客: +XX sessions
  - SC クリック: +XX clicks
  - 評価: 成功 / 要改善

### 実験結果
  - [実験] 新CTA配色 → CTR X% (従来 Y%) → 本採用 / 廃止
  - [実験] Top 5 記事フォーマット → PV XX → 本採用

### 競合を参考にした今週の提案
  - [Shopify] Solaris Japan がコンディションバッジを導入 → 自社にも導入推奨
  - [ブログ] NekoFigs が Figure Care 記事シリーズを開始 → 類似シリーズ提案
  - [SNS] 競合の比較画像投稿が高エンゲージメント → 今週試す

### 今週の重点カテゴリ
  カテゴリ: [自動選定]
  商品追加: [具体的な商品名]
  記事: [具体的なテーマ]
  SNS: [具体的な投稿案]
  CTA: [改善案]

### 次週の優先施策
  1. [スコア順の提案]
  2. ...
```


## 5. カテゴリ単位 PDCA 設計

### 1カテゴリ1週間のサイクル

```
月曜（Plan）:
  重点カテゴリを決定
  → 商品追加候補を選定
  → 記事テーマを決定
  → SNS投稿スケジュールを作成
  → CTA改善案を作成

火-木（Do）:
  → Draft 商品を Active化
  → hd-bodyscience.com に記事作成（WP API）
  → Pinterest / Instagram に投稿
  → 内部リンクを追加（WP API）
  → CTA を更新

金（Check）:
  → GA4: セッション・送客・LP
  → SC: クリック・表示・CTR
  → SNS: クリック・保存
  → CTA: utm_content 別効果

土-日（Act）:
  → 結果を proposal_history.json に記録
  → スコア調整
  → 翌週の Plan に反映
```

### カテゴリ PDCA テンプレート

```json
{
  "category": "Trading Cards",
  "week": "2026-W14",
  "plan": {
    "products_to_add": 3,
    "articles_to_write": 2,
    "sns_posts": 5,
    "internal_links": 3,
    "cta_improvements": 1
  },
  "do": {
    "products_added": 0,
    "articles_written": 0,
    "sns_posted": 0,
    "links_added": 0,
    "cta_updated": 0
  },
  "check": {
    "ga4_sessions_before": null,
    "ga4_sessions_after": null,
    "sc_clicks_before": null,
    "sc_clicks_after": null,
    "cta_clicks_before": null,
    "cta_clicks_after": null
  },
  "act": {
    "evaluation": null,
    "carry_forward": [],
    "drop": [],
    "next_week_adjustments": []
  }
}
```


## 6. 実験運用設計

### 実験と本採用の分離

```
実験 → 観測期間（7日間）→ 評価 → 本採用 or 廃止
```

### 実験管理: `ops/monitoring/experiments.json`

```json
[
  {
    "id": "EXP-001",
    "name": "新CTA配色テスト",
    "type": "cta_design",
    "start_date": "2026-04-07",
    "end_date": "2026-04-14",
    "hypothesis": "緑→オレンジに変えるとCTR +20%",
    "metric": "cta_click_rate",
    "baseline": null,
    "result": null,
    "status": "running",
    "decision": null
  }
]
```

### 実験対象

| カテゴリ | 実験例 |
|---------|--------|
| CTA | ボタン配色、文言、配置 |
| 記事構成 | Top 5 vs 単品紹介 vs 比較記事 |
| 画像トーン | 明るい vs 暗い、テキスト有 vs 無 |
| SNS | 投稿時間帯、ハッシュタグ、画像パターン |
| Shopify | 配色、バナー、Collection順 |


## 7. 日次と週次の役割分担

### 日次レポート（毎日 03:00）

```
監視:
  🔴 要対応 — 異常検知
  🚀 即効改善 — 設定漏れ・未設置
  💡 中期改善 — 計画的改善

提案:
  📝 今日のアクション提案
    - 記事テーマ案（重点カテゴリ優先）
    - SNS投稿案（ローテーション）
    - 内部リンク案
    - Shopify追加候補
    - eBay→Shopify展開候補
    - 記事化候補
    - 派生記事案
    - 重点カテゴリアクション

状態:
  ✓ 異常なし
  外部導線サマリ
  GA4 / SC データ
```

### 週次レポート（毎週月曜）

```
評価:
  先週の重点カテゴリ結果
  実験結果（本採用 / 廃止判断）
  提案の実行率 / 成功率

競合比較:
  Shopify 競合の変化
  ブログ競合の新記事
  SNS 競合の投稿パターン

提案:
  競合参考の改善案
  今週の重点カテゴリ + アクションプラン
  新規実験の提案
  次週の優先施策（スコア順）

振り返り:
  過去の提案で効果が出たもの（再現推奨）
  効果が出なかったもの（方向転換）
```


## 実装計画

| Phase | 内容 | タイミング |
|-------|------|-----------|
| **A** | shared_state.json / proposal_history.json / experiments.json の雛形作成 | 今すぐ |
| **B** | daily_inspection.py に shared_state 読み書きを追加 | 今すぐ |
| **C** | action_suggestions.py にスコアリングを追加 | 今すぐ |
| **D** | 週次レポート生成スクリプトの作成 | 今週中 |
| **E** | 競合自動チェック機能の追加 | 来週 |
| **F** | 実験管理の自動評価 | データ蓄積後 |
