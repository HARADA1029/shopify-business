# ============================================================
# 週次改善レポート生成スクリプト
#
# 毎週月曜に実行し、以下を出力:
# - 先週の重点カテゴリ結果
# - 実験結果（本採用/廃止判断）
# - 競合比較まとめ
# - 提案の実行率・成功率
# - 次週の優先施策
#
# 実行: python ops/monitoring/weekly_report.py
# ============================================================

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from collections import Counter

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
WEEK_AGO = NOW - timedelta(days=7)

sys.path.insert(0, SCRIPT_DIR)


def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def generate_weekly_report():
    """週次レポートを生成"""
    lines = []
    lines.append("# HD Toys Store Japan 週次改善レポート")
    lines.append("")
    lines.append("**期間:** %s ～ %s" % (WEEK_AGO.strftime("%Y-%m-%d"), NOW.strftime("%Y-%m-%d")))
    lines.append("")

    # === 1. 先週の重点カテゴリ結果 ===
    shared_state = load_json(os.path.join(SCRIPT_DIR, "shared_state.json"))
    focus = shared_state.get("weekly_focus", {})

    lines.append("## 先週の重点カテゴリ")
    lines.append("")
    if focus:
        lines.append("- カテゴリ: **%s**" % focus.get("category", "?"))
        lines.append("- 理由: %s" % focus.get("reason", "?")[:80])
        actions = focus.get("actions", {})
        results = focus.get("results", {})
        lines.append("- 計画:")
        for k, v in actions.items():
            if v:
                lines.append("  - %s: %s" % (k, str(v)[:60]))
        if results:
            lines.append("- 結果:")
            for k, v in results.items():
                lines.append("  - %s: %s" % (k, v))
        else:
            lines.append("- 結果: 未記録")
    else:
        lines.append("- 設定なし")
    lines.append("")

    # === 2. SNS 投稿実績 ===
    posted = load_json(os.path.join(SCRIPT_DIR, "sns_posted.json"))
    history = posted.get("history", [])

    week_posts = [h for h in history if h.get("date", "") >= WEEK_AGO.strftime("%Y-%m-%d")]

    lines.append("## SNS 投稿実績")
    lines.append("")
    if week_posts:
        platform_counts = Counter(h.get("platform", "unknown") for h in week_posts)
        for platform, count in platform_counts.most_common():
            lines.append("- %s: %d 投稿" % (platform, count))
        lines.append("- 合計: %d 投稿" % len(week_posts))
    else:
        lines.append("- 投稿なし")
    lines.append("")

    # === 3. 提案履歴 ===
    proposal_history = load_json(os.path.join(SCRIPT_DIR, "proposal_history.json"))
    proposals = proposal_history.get("proposals", [])

    lines.append("## 提案の実行状況")
    lines.append("")
    if proposals:
        adopted = [p for p in proposals if p.get("status") == "adopted"]
        implemented = [p for p in proposals if p.get("implemented_date")]
        lines.append("- 提案総数: %d" % len(proposals))
        lines.append("- 採用: %d" % len(adopted))
        lines.append("- 実装済み: %d" % len(implemented))
    else:
        lines.append("- 提案履歴なし（自動記録は今後追加）")
    lines.append("")

    # === 4. 実験結果 ===
    experiments = load_json(os.path.join(SCRIPT_DIR, "experiments.json"))
    exp_list = experiments.get("experiments", [])

    lines.append("## 実験結果")
    lines.append("")
    if exp_list:
        for exp in exp_list:
            status = exp.get("status", "unknown")
            lines.append("- [%s] %s" % (status, exp.get("name", "?")))
            if exp.get("result"):
                lines.append("  - 結果: %s" % exp["result"])
            if exp.get("decision"):
                lines.append("  - 判断: %s" % exp["decision"])
    else:
        lines.append("- 実験なし（今後追加）")
    lines.append("")

    # === 5. 競合変化 ===
    competitor_cache = load_json(os.path.join(SCRIPT_DIR, "competitor_cache.json"))

    lines.append("## 競合の変化")
    lines.append("")
    changes_found = False
    for key, data in competitor_cache.items():
        if key.startswith("_"):
            continue
        if data.get("changed_since_last"):
            lines.append("- **%s**: サイト更新検出" % key)
            promos = data.get("promotions", [])
            if promos:
                lines.append("  - プロモーション: %s" % ", ".join(promos[:3]))
            changes_found = True

    if not changes_found:
        lines.append("- 大きな変化なし")
    lines.append("")

    # === 6. 日次レポートの集計 ===
    lines.append("## 日次レポート集計（先週）")
    lines.append("")

    # 過去7日分のレポートを読み込み
    daily_summaries = []
    for i in range(7):
        day = (NOW - timedelta(days=i)).strftime("%Y-%m-%d")
        report_path = os.path.join(REPORTS_DIR, "report_%s.json" % day)
        if os.path.exists(report_path):
            daily_summaries.append(load_json(report_path))

    if daily_summaries:
        lines.append("- レポート数: %d日分" % len(daily_summaries))
        # 提案タイプの集計
        all_findings = []
        for report in daily_summaries:
            all_findings.extend(report.get("findings", []))
        type_counts = Counter(f.get("type", "?") for f in all_findings)
        for t, c in type_counts.most_common():
            lines.append("- %s: %d件" % (t, c))
    else:
        lines.append("- レポートデータなし")
    lines.append("")

    # === 7. 次週の優先施策 ===
    lines.append("## 次週の優先施策")
    lines.append("")
    lines.append("1. 重点カテゴリの PDCA を回す")
    lines.append("2. SNS 投稿の効果を GA4 で確認")
    lines.append("3. 競合の変化があれば対応")
    lines.append("4. Analytics 設定不足を解消")
    lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("  HD Toys Store Japan 週次改善レポート")
    print("  %s" % NOW.strftime("%Y-%m-%d %H:%M JST"))
    print("=" * 60)
    print()

    report = generate_weekly_report()

    # 保存
    os.makedirs(REPORTS_DIR, exist_ok=True)
    week_str = NOW.strftime("%Y-W%W")
    md_path = os.path.join(REPORTS_DIR, "weekly_%s.md" % week_str)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report)
    print("[OK] Weekly report saved: %s" % md_path)

    # コンソール出力
    print()
    print(report)


if __name__ == "__main__":
    main()
