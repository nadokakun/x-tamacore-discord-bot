import os
import re
import json
import time
import requests
import feedparser
from deep_translator import GoogleTranslator
from datetime import datetime, timezone

# 本地開發用 .env，GitHub Actions 直接注入環境變數
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── 設定 ──────────────────────────────────────────────────
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")
TARGET_USERNAME = "tamacolle_staff"
RSS_URL         = f"https://rsshub.app/twitter/user/{TARGET_USERNAME}"
STATE_FILE      = "last_tweet_id.json"
# ──────────────────────────────────────────────────────────

translator = GoogleTranslator(source="auto", target="zh-TW")


def load_last_id() -> str | None:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f).get("last_tweet_id")
    return None


def save_last_id(entry_id: str):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_tweet_id": entry_id}, f)


def fetch_entries():
    feed = feedparser.parse(RSS_URL)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"RSS 解析失敗: {feed.bozo_exception}")
    return feed.entries


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def translate(text: str) -> str:
    try:
        return translator.translate(text)
    except Exception as e:
        print(f"[翻譯失敗] {e}")
        return text


def send_to_discord(original: str, translated: str, link: str):
    payload = {
        "embeds": [{
            "author": {
                "name": f"@{TARGET_USERNAME}",
                "url": f"https://x.com/{TARGET_USERNAME}",
            },
            "color": 0x1D9BF0,
            "fields": [
                {"name": "原文",     "value": original[:1024],   "inline": False},
                {"name": "繁體中文", "value": translated[:1024],  "inline": False},
            ],
            "footer":    {"text": "X → Discord Bot"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url":       link,
        }]
    }
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    if r.status_code == 204:
        print(f"  ✓ 已發送: {link}")
    else:
        print(f"  ✗ Discord 錯誤 {r.status_code}: {r.text}")


def main():
    print(f"執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    entries = fetch_entries()
    if not entries:
        print("沒有取得任何推文")
        return

    last_id = load_last_id()

    # 首次執行：只記錄最新 ID，不發送
    if last_id is None:
        save_last_id(entries[0].id)
        print(f"首次執行，記錄最新推文（不發送）")
        return

    # 找出比上次更新的新推文
    new_entries = []
    for entry in entries:
        if entry.id == last_id:
            break
        new_entries.append(entry)

    if not new_entries:
        print("沒有新推文")
        return

    # 由舊到新處理
    for entry in reversed(new_entries):
        text       = strip_html(entry.summary)
        translated = translate(text)
        send_to_discord(text, translated, entry.link)
        time.sleep(1)

    save_last_id(entries[0].id)
    print(f"共處理 {len(new_entries)} 則推文")


if __name__ == "__main__":
    main()
