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
STATE_FILE      = "last_tweet_id.json"

# RSS 來源（依序嘗試，成功即停止）
RSS_SOURCES = [
    # Nitter 公開實例
    f"https://nitter.privacydev.net/{TARGET_USERNAME}/rss",
    f"https://nitter.poast.org/{TARGET_USERNAME}/rss",
    f"https://nitter.net/{TARGET_USERNAME}/rss",
    f"https://nitter.1d4.us/{TARGET_USERNAME}/rss",
    f"https://nitter.kavin.rocks/{TARGET_USERNAME}/rss",
    f"https://nitter.unixfox.eu/{TARGET_USERNAME}/rss",
    f"https://nitter.moomoo.me/{TARGET_USERNAME}/rss",
    f"https://nitter.it/{TARGET_USERNAME}/rss",
    f"https://nitter.tiekoetter.com/{TARGET_USERNAME}/rss",
    f"https://nitter.esmailelbob.xyz/{TARGET_USERNAME}/rss",
    f"https://nitter.pussthecat.org/{TARGET_USERNAME}/rss",
    f"https://nitter.fdn.fr/{TARGET_USERNAME}/rss",
    f"https://twiiit.com/{TARGET_USERNAME}/rss",
    # RSSHub 公開實例
    f"https://rsshub.app/twitter/user/{TARGET_USERNAME}",
    f"https://rsshub.rssforever.com/twitter/user/{TARGET_USERNAME}",
    f"https://rsshub.feeded.app/twitter/user/{TARGET_USERNAME}",
    f"https://hub.slarker.me/twitter/user/{TARGET_USERNAME}",
]
# ──────────────────────────────────────────────────────────

translator = GoogleTranslator(source="auto", target="zh-TW")

# 載入自訂字典
DICT_FILE = "dictionary.json"
def load_dictionary() -> dict:
    if os.path.exists(DICT_FILE):
        with open(DICT_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}

DICTIONARY = load_dictionary()


def apply_dictionary(text: str) -> str:
    """翻譯後套用自訂字典修正術語"""
    for wrong, correct in DICTIONARY.items():
        text = text.replace(wrong, correct)
    return text


def protect_terms(text: str) -> tuple[str, dict]:
    """翻譯前將已知術語替換成佔位符，避免被亂翻"""
    placeholders = {}
    for i, (jp_term, zh_term) in enumerate(DICTIONARY.items()):
        placeholder = f"__TERM{i}__"
        if jp_term in text:
            text = text.replace(jp_term, placeholder)
            placeholders[placeholder] = zh_term
    return text, placeholders


def restore_terms(text: str, placeholders: dict) -> str:
    """翻譯後還原佔位符為正確繁中術語"""
    for placeholder, zh_term in placeholders.items():
        text = text.replace(placeholder, zh_term)
    return text


def load_last_id() -> str | None:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f).get("last_tweet_id")
    return None


def save_last_id(entry_id: str):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_tweet_id": entry_id}, f)


def fetch_entries():
    for url in RSS_SOURCES:
        print(f"  嘗試: {url}")
        feed = feedparser.parse(url)
        if feed.entries:
            print(f"  成功取得 {len(feed.entries)} 則推文")
            return feed.entries
        print(f"  失敗: {getattr(feed, 'bozo_exception', '無回應')}")
    raise RuntimeError("所有 RSS 來源均無法取得資料")


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def extract_image(entry) -> str | None:
    """從 RSS entry 擷取第一張圖片 URL"""
    # 方法 1：feedparser media_content
    if hasattr(entry, "media_content"):
        for media in entry.media_content:
            if media.get("medium") == "image" or media.get("url", "").endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                return media["url"]

    # 方法 2：feedparser media_thumbnail
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")

    # 方法 3：從 summary HTML 的 <img> 標籤抓
    if hasattr(entry, "summary"):
        match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', entry.summary)
        if match:
            img_url = match.group(1)
            # 把 nitter 圖片轉換成 Twitter 原始 URL
            if "/pic/media%2F" in img_url or "/pic/enc/" in img_url:
                decoded = requests.utils.unquote(img_url.split("/pic/")[-1])
                return f"https://pbs.twimg.com/{decoded}"
            return img_url

    return None


def translate(text: str) -> str:
    try:
        # 1. 保護已知術語
        protected, placeholders = protect_terms(text)
        # 2. 翻譯
        result = translator.translate(protected)
        # 3. 還原術語
        result = restore_terms(result, placeholders)
        # 4. 套用字典修正殘留錯誤
        result = apply_dictionary(result)
        return result
    except Exception as e:
        print(f"[翻譯失敗] {e}")
        return text


def send_to_discord(original: str, translated: str, link: str, image_url: str | None = None):
    embed = {
        "author": {
            "name": f"@{TARGET_USERNAME}",
            "url": f"https://x.com/{TARGET_USERNAME}",
        },
        "title": "🔗 推文原文連結",
        "url":   link,
        "color": 0x1D9BF0,
        "fields": [
            {"name": "原文",     "value": original[:1024],   "inline": False},
            {"name": "繁體中文", "value": translated[:1024],  "inline": False},
        ],
        "footer":    {"text": "X → Discord Bot"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if image_url:
        embed["image"] = {"url": image_url}

    payload = {"embeds": [embed]}
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
        image_url  = extract_image(entry)
        send_to_discord(text, translated, entry.link, image_url)
        time.sleep(1)

    save_last_id(entries[0].id)
    print(f"共處理 {len(new_entries)} 則推文")


if __name__ == "__main__":
    main()
