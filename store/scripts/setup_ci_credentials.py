"""GitHub Actions 用の認証ファイルセットアップスクリプト"""
import json
import os

# Shopify トークン
shopify_token = os.environ.get("SHOPIFY_TOKEN", "")
if shopify_token:
    with open(".shopify_token.json", "w") as f:
        json.dump({"access_token": shopify_token}, f)
    print("[OK] .shopify_token.json created")

# Instagram トークン
ig_access = os.environ.get("IG_ACCESS_TOKEN", "")
ig_page = os.environ.get("IG_PAGE_TOKEN", "")
ig_user = os.environ.get("IG_USER_ID", "")

if ig_access and ig_user:
    ig_data = {
        "access_token": ig_access,
        "page_access_token": ig_page,
        "ig_user_id": ig_user,
        "page_id": "979402688599458",
        "page_name": "HD Toys Store Japan",
        "token_type": "long_lived",
    }
    with open(".instagram_token.json", "w") as f:
        json.dump(ig_data, f)
    print("[OK] .instagram_token.json created (IG user: %s)" % ig_user)
