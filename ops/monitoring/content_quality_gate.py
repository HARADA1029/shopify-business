# ============================================================
# コンテンツ品質ゲートモジュール
#
# ブログ記事・SNS静止画・SNS動画の投稿前品質監査と
# 競合品質比較・再発防止を統合管理する。
#
# 1. ブログ品質スコア（8項目）
# 2. 静止画品質スコア（6項目）
# 3. 動画品質スコア（7項目）
# 4. 競合品質比較
# 5. 品質低下の再発追跡
# 6. レポートセクション生成
# ============================================================

import json
import os
import re
from datetime import datetime, timezone, timedelta
from collections import Counter

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

QUALITY_LOG = os.path.join(SCRIPT_DIR, "content_quality_log.json")

# 品質基準（各1点、基準未満は投稿拒否）
BLOG_MIN_SCORE = 6    # /8
IMAGE_MIN_SCORE = 4   # /6
VIDEO_MIN_SCORE = 4   # /7


def _load_quality_log():
    if not os.path.exists(QUALITY_LOG):
        return {"blog": [], "image": [], "video": [], "rejections": [], "last_updated": ""}
    try:
        with open(QUALITY_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"blog": [], "image": [], "video": [], "rejections": [], "last_updated": ""}


def _save_quality_log(log):
    log["last_updated"] = NOW.strftime("%Y-%m-%d")
    for key in ["blog", "image", "video", "rejections"]:
        log[key] = log.get(key, [])[-50:]  # 50件保持
    with open(QUALITY_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


# ============================================================
# 1. ブログ品質スコア（8項目、各1点）
# ============================================================

def score_blog_quality(article_html, product=None):
    """ブログ記事の品質を8項目でスコアリング"""
    text = re.sub(r"<[^>]+>", "", article_html)
    word_count = len(text.split())
    img_count = len(re.findall(r"<img", article_html))
    h2_count = len(re.findall(r"<h2", article_html))
    al = article_html.lower()

    scores = {}
    # 1. 情報密度（800語以上）
    scores["content_depth"] = word_count >= 800
    # 2. 画像品質（3枚以上）
    scores["image_quality"] = img_count >= 3
    # 3. 構成（H2 3個以上）
    scores["structure"] = h2_count >= 3
    # 4. CTA自然さ（CTAありかつbuy now等なし）
    has_cta = "hd-toys-store-japan" in al
    no_pushy = not any(kw in al for kw in ["buy now", "hurry", "limited time", "act now"])
    scores["cta_natural"] = has_cta and no_pushy
    # 5. trust感（3要素中2以上）
    trust_count = sum(1 for kw in ["shipped from japan", "inspected", "condition", "pre-owned", "authentic"] if kw in al)
    scores["trust_feel"] = trust_count >= 2
    # 6. 読みやすさ（段落5個以上）
    scores["readability"] = len(re.findall(r"<p", article_html)) >= 5
    # 7. 内部リンク
    scores["internal_links"] = "hd-bodyscience.com" in al
    # 8. カテゴリ/コンテキスト（シリーズ/フランチャイズ言及）
    scores["context"] = any(kw in al for kw in ["series", "franchise", "collector", "released", "history", "culture"])

    total = sum(scores.values())
    passed = total >= BLOG_MIN_SCORE
    failed_items = [k for k, v in scores.items() if not v]

    return {
        "score": total, "max": 8, "passed": passed,
        "items": scores, "failed": failed_items,
        "word_count": word_count, "img_count": img_count,
    }


# ============================================================
# 2. 静止画品質スコア（6項目）
# ============================================================

def score_image_quality(image_url, caption="", product=None):
    """SNS静止画の品質を6項目でスコアリング"""
    scores = {}
    caption_lower = caption.lower()

    # 1. 商品情報あり
    scores["product_info"] = bool(product and product.get("title"))
    # 2. trust文言
    scores["trust_text"] = any(kw in caption_lower for kw in ["shipped from japan", "inspected", "pre-owned", "condition"])
    # 3. CTA（リンクまたはbio誘導）
    scores["cta_present"] = any(kw in caption_lower for kw in ["link in bio", "shop", "store", "hd-toys"])
    # 4. ハッシュタグ（3個以上）
    scores["hashtags"] = caption.count("#") >= 3
    # 5. 売り込み過多でない
    scores["not_pushy"] = not any(kw in caption_lower for kw in ["buy now", "hurry", "limited time"])
    # 6. 画像あり
    scores["has_image"] = bool(image_url)

    total = sum(scores.values())
    passed = total >= IMAGE_MIN_SCORE

    return {"score": total, "max": 6, "passed": passed, "items": scores, "failed": [k for k, v in scores.items() if not v]}


# ============================================================
# 3. 動画品質スコア（7項目）
# ============================================================

def score_video_quality(video_bytes=None, caption="", duration=5):
    """SNS動画の品質を7項目でスコアリング"""
    scores = {}
    caption_lower = caption.lower()

    # 1. 尺（3-15秒）
    scores["duration_ok"] = 3 <= duration <= 15
    # 2. キャプションあり
    scores["caption_present"] = len(caption) > 20
    # 3. trust文言
    scores["trust_text"] = any(kw in caption_lower for kw in ["shipped from japan", "inspected", "pre-owned"])
    # 4. 商品訴求（売り込みすぎない）
    scores["natural_appeal"] = not any(kw in caption_lower for kw in ["buy now", "hurry", "limited time"])
    # 5. ハッシュタグ
    scores["hashtags"] = caption.count("#") >= 3
    # 6. 動画データあり
    scores["has_video"] = video_bytes is not None and len(video_bytes) > 10000
    # 7. ファイルサイズ適切（100KB-10MB）
    if video_bytes:
        size_kb = len(video_bytes) / 1024
        scores["size_ok"] = 100 <= size_kb <= 10240
    else:
        scores["size_ok"] = False

    total = sum(scores.values())
    passed = total >= VIDEO_MIN_SCORE

    return {"score": total, "max": 7, "passed": passed, "items": scores, "failed": [k for k, v in scores.items() if not v]}


# ============================================================
# 4. 品質監査レポート（日次用）
# ============================================================

def audit_content_quality(wp_posts):
    """全コンテンツの品質を監査してレポート生成"""
    findings = []
    log = _load_quality_log()

    # === ブログ品質監査 ===
    blog_scores = []
    low_quality = []

    for p in wp_posts:
        content = p.get("content", {})
        if isinstance(content, dict):
            content = content.get("rendered", "")
        if not content:
            continue

        qc = score_blog_quality(content)
        blog_scores.append(qc["score"])
        if not qc["passed"]:
            title = p.get("title", {})
            if isinstance(title, dict):
                title = title.get("rendered", "")
            low_quality.append({
                "id": p.get("id", 0),
                "title": str(title)[:40],
                "score": qc["score"],
                "failed": qc["failed"],
            })

    avg_score = sum(blog_scores) / max(len(blog_scores), 1)
    perfect = sum(1 for s in blog_scores if s >= BLOG_MIN_SCORE)

    details = [
        "=== Content Quality Gate ===",
        "",
        "--- Blog Quality ---",
        "Articles checked: %d" % len(blog_scores),
        "Average score: %.1f / 8" % avg_score,
        "Passing (≥%d): %d / %d" % (BLOG_MIN_SCORE, perfect, len(blog_scores)),
        "Low quality: %d" % len(low_quality),
    ]

    if low_quality:
        details.append("Low quality articles:")
        for lq in low_quality[:5]:
            details.append("  [%d/8] ID:%d %s — fix: %s" % (lq["score"], lq["id"], lq["title"], ", ".join(lq["failed"][:3])))

    # 比較拒否サマリ
    if blog_state:
        rejections = blog_state.get("rejections", [])
        comparison_rejects = [r for r in rejections if any("comparison_weak" in i for i in r.get("issues", []))]
        if comparison_rejects:
            details.append("")
            details.append("--- Comparison-Based Rejections ---")
            details.append("Rejected by benchmark comparison: %d (all-time)" % len(comparison_rejects))
            for cr in comparison_rejects[-3:]:
                details.append("  [%s] %s" % (cr.get("date", "?"), cr.get("title", "?")[:40]))

    # === SNS品質サマリ ===
    sns_posted = None
    sns_path = os.path.join(SCRIPT_DIR, "sns_posted.json")
    if os.path.exists(sns_path):
        try:
            with open(sns_path, "r", encoding="utf-8") as f:
                sns_posted = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    if sns_posted:
        history = sns_posted.get("history", [])
        week_ago = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
        recent = [h for h in history if h.get("date", "") >= week_ago]

        image_posts = [h for h in recent if h.get("media_type") == "image"]
        video_posts = [h for h in recent if h.get("media_type") == "video"]

        details.append("")
        details.append("--- SNS Image Quality (7d) ---")
        details.append("Image posts: %d" % len(image_posts))
        with_trust = sum(1 for h in image_posts if any(kw in str(h).lower() for kw in ["inspect", "shipped", "condition"]))
        details.append("With trust text: %d/%d (%.0f%%)" % (with_trust, len(image_posts), with_trust / max(len(image_posts), 1) * 100))

        details.append("")
        details.append("--- SNS Video Quality (7d) ---")
        details.append("Video posts: %d" % len(video_posts))

    # === 投稿拒否・再生成サマリ ===
    blog_state = None
    bs_path = os.path.join(SCRIPT_DIR, "blog_state.json")
    if os.path.exists(bs_path):
        try:
            with open(bs_path, "r", encoding="utf-8") as f:
                blog_state = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    if blog_state:
        rejections = blog_state.get("rejections", [])
        generated = blog_state.get("articles_generated", [])
        week_rejections = [r for r in rejections if r.get("date", "") >= (NOW - timedelta(days=7)).strftime("%Y-%m-%d")]
        retried = [r for r in week_rejections if r.get("retry_attempted")]

        details.append("")
        details.append("--- Rejection / Retry Summary (7d) ---")
        details.append("Rejected: %d | Retried: %d | Published: %d" % (
            len(week_rejections), len(retried), len([g for g in generated if g.get("date", "") >= (NOW - timedelta(days=7)).strftime("%Y-%m-%d")])))

        # 拒否理由の再発チェック
        if week_rejections:
            reason_counts = Counter()
            for r in week_rejections:
                for issue in r.get("issues", []):
                    tag = issue.split("]")[0].replace("[", "") if "]" in issue else "other"
                    reason_counts[tag] += 1

            # 過去30日の同じ理由を比較
            all_rejections = blog_state.get("rejections", [])
            month_ago = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
            prev_reasons = Counter()
            for r in all_rejections:
                if r.get("date", "") >= month_ago and r.get("date", "") < (NOW - timedelta(days=7)).strftime("%Y-%m-%d"):
                    for issue in r.get("issues", []):
                        tag = issue.split("]")[0].replace("[", "") if "]" in issue else "other"
                        prev_reasons[tag] += 1

            recurring = [reason for reason in reason_counts if reason in prev_reasons]
            if recurring:
                details.append("Recurring rejection reasons: %s" % ", ".join(recurring))

    # ログ保存
    log["blog"].append({
        "date": NOW.strftime("%Y-%m-%d"),
        "checked": len(blog_scores),
        "avg_score": round(avg_score, 1),
        "low_quality": len(low_quality),
    })
    _save_quality_log(log)

    severity = "action" if len(low_quality) > 3 else "suggestion" if low_quality else "info"
    findings.append({
        "type": severity,
        "agent": "blog-analyst",
        "message": "Content quality: blog avg %.1f/8, %d low-quality, %d rejected (7d)" % (
            avg_score, len(low_quality), len(week_rejections) if blog_state else 0),
        "details": details,
    })

    return findings


# ============================================================
# メインエントリポイント
# ============================================================

def run_content_quality_audit(wp_posts):
    """コンテンツ品質監査を実行"""
    return audit_content_quality(wp_posts)
