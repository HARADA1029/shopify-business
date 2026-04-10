"""Shopify プライバシーポリシーを設定するスクリプト"""

import json
import os
import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TOKEN_FILE = os.path.join(PROJECT_ROOT, ".shopify_token.json")

with open(TOKEN_FILE, "r") as f:
    token = json.load(f)["access_token"]

STORE = "hd-toys-store-japan.myshopify.com"
URL = "https://%s/admin/api/2024-10/graphql.json" % STORE

PRIVACY_BODY = """Privacy Policy for HD Toys Store Japan

Last updated: April 2026

1. INTRODUCTION
HD Toys Store Japan operates hd-toys-store-japan.myshopify.com and related services. This Privacy Policy explains how we collect, use, and safeguard your information.

2. INFORMATION WE COLLECT
We may collect: personal information (name, email, shipping address, phone number), payment information processed securely through Shopify Payments, browsing data via cookies and analytics, and device/browser information.

3. HOW WE USE YOUR INFORMATION
We use collected information to: process and fulfill orders, communicate about purchases, improve our website and services, send marketing (with consent), and comply with legal obligations.

4. COOKIES AND TRACKING
We use cookies and Google Analytics 4 (GA4) to analyze website traffic and improve user experience. You can control cookie settings through your browser.

5. THIRD-PARTY SERVICES
We use Shopify (e-commerce platform), Google Analytics (website analytics), and social media platforms (content distribution).

6. PINTEREST API DATA USAGE
HD Toys Store Japan uses the Pinterest API to share product images and content on our Pinterest account.

Data We Collect via Pinterest API:
- Pin performance data (impressions, clicks, saves, engagement metrics for our pins)
- Board information (our own board names and descriptions)
- Account analytics (audience insights and traffic data for our own account)

How We Use Pinterest Data:
- To publish product images and content to our Pinterest boards
- To analyze the performance of our pins and optimize content strategy
- To understand which products resonate with our Pinterest audience
- To generate internal reports for business improvement

Pinterest Data Storage and Retention:
- Pinterest API data is stored on our secure servers and GitHub Actions environment
- Analytics data is retained for up to 12 months for trend analysis
- We do not store Pinterest user data from other accounts
- Cached API responses are automatically deleted after 24 hours

Pinterest Data Sharing:
- We do NOT sell, rent, or share Pinterest API data with any third parties
- Pinterest API data is used solely for our own business operations
- No Pinterest user data is transferred to other platforms or services

We comply with Pinterest Developer Guidelines and Privacy Policy. We access only the minimum data necessary to operate our Pinterest presence.

HD Toys Store Japan is not endorsed by, affiliated with, or sponsored by Pinterest, Inc. "Pinterest" is a trademark of Pinterest, Inc.

7. TIKTOK API DATA USAGE
We use the TikTok API to publish video content. We collect only our own account performance metrics and do not collect or store TikTok user data from other accounts.

8. DATA SHARING
We do not sell your personal information. We may share information with service providers (shipping, payment), analytics services (anonymized), and legal authorities when required.

9. DATA SECURITY
We implement appropriate technical and organizational measures to protect your personal information.

10. YOUR RIGHTS
You may: access, correct, or delete your personal information; opt out of marketing; request data portability; lodge a complaint with a data protection authority.

11. DATA RETENTION
We retain personal information as long as necessary for order fulfillment and legal compliance.

12. CONTACT US
HD Toys Store Japan
Email: harada10291@gmail.com"""

QUERY = """
mutation shopPolicyUpdate($shopPolicy: ShopPolicyInput!) {
  shopPolicyUpdate(shopPolicy: $shopPolicy) {
    shopPolicy {
      body
      type
    }
    userErrors {
      field
      message
    }
  }
}
"""

resp = requests.post(
    URL,
    headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
    json={
        "query": QUERY,
        "variables": {
            "shopPolicy": {
                "type": "PRIVACY_POLICY",
                "body": PRIVACY_BODY,
            }
        }
    },
    timeout=30,
)

print("Status:", resp.status_code)
result = resp.json()

if result.get("errors"):
    print("GraphQL errors:", json.dumps(result["errors"], indent=2))
else:
    data = result.get("data", {}).get("shopPolicyUpdate", {})
    errors = data.get("userErrors", [])
    if errors:
        print("User errors:", errors)
    else:
        policy = data.get("shopPolicy", {})
        print("SUCCESS!")
        print("Type:", policy.get("type"))
        print("Body length:", len(policy.get("body", "")))
