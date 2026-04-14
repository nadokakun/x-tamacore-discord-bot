import os
import json
import time
import requests
import tweepy
from deep_translator import GoogleTranslator
from datetime import datetime, timezone

# 本地開發用 .env，GitHub Actions 直接注入環境變數
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── 設定 ──────────────────────────────────────────────────
BEARER_TOKEN    = os.getenv("X_BEARER_TOKEN")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")
TARGET_USERNAME = "tamacolle_staff"
STATE_FILE      = "last_tweet_id.json"
# ──────────────────────────────────────────────────────────

client     = tweepy.Client(bearer_token=BEARER_TOKEN)
translator = GoogleTranslator(source="auto", target="zh-TW")


def load_last_id() -> str | None:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f).get("last_tweet_id")
    return None


def save_last_id(tweet_id: str):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_tweet_id": str(tweet_id)}, f)


def get_user_id(username: str) -> str:
    return client.get_user(username=username).data.id


def fetch_new_tweets(user_id: str, since_id: str | None = None):
    kwargs = dict(
        max_results=10,
        tweet_fields=["created_at", "text"],
        exclude=["retweets", "replies"],
    )
    if since_id:
        kwargs["since_id"] = since_id
    resp = client.get_users_tweets(user_id, **kwargs)
    return resp.data or []


def translate(text: str) -> str:
    try:
        return translator.translate(text)
    except Exception as e:
        print(f"[翻譯失敗] {e}")
        return text


def send_to_discord(original: str, translated: str, tweet_id: str):
    url = f"https://x.com/{TARGET_USERNAME}/status/{tweet_id}"
    payload = {
        "embeds": [{
            "author": {
                "name": f"@{TARGET_USERNAME}",
                "url": f"https://x.com/{TARGET_USERNAME}",
            },
            "color": 0x1D9BF0,
            "fields": [
                {"name": "原文",     "value": original,   "inline": False},
                {"name": "繁體中文", "value": translated,  "inline": False},
            ],
            "footer":    {"text": "X → Discord Bot"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url":       url,
        }]
    }
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    if r.status_code == 204:
        print(f"  ✓ 已發送 tweet {tweet_id}")
    else:
        print(f"  ✗ Discord 錯誤 {r.status_code}: {r.text}")


def main():
    print(f"執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    user_id = get_user_id(TARGET_USERNAME)
    last_id = load_last_id()

    # 首次執行：只記錄最新 ID，不發送
    if last_id is None:
        tweets = fetch_new_tweets(user_id)
        if tweets:
            save_last_id(tweets[0].id)
            print(f"首次執行，記錄最新推文 ID: {tweets[0].id}（不發送）")
        else:
            print("目前沒有推文")
        return

    tweets = fetch_new_tweets(user_id, since_id=last_id)

    if not tweets:
        print("沒有新推文")
        return

    # 由舊到新處理
    for tweet in reversed(tweets):
        send_to_discord(tweet.text, translate(tweet.text), str(tweet.id))
        time.sleep(1)

    save_last_id(tweets[0].id)
    print(f"共處理 {len(tweets)} 則推文")


if __name__ == "__main__":
    main()
