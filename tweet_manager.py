"""
ツイートデータ管理モジュール

tweets.json を読み書きし、IDと投稿日時のリストを管理する。
"""

import json
from pathlib import Path
from datetime import datetime, timezone

TWEETS_FILE = Path(__file__).parent / "tweets.json"

def parse_date(date_str: str) -> datetime:
    if not date_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        pass
    try:
        return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        pass
    return datetime.min.replace(tzinfo=timezone.utc)


def load_tweets() -> list[dict]:
    """ツイートリストを読み込む"""
    if not TWEETS_FILE.exists():
        return []
    
    try:
        with open(TWEETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_tweets(tweets: list[dict]):
    """ツイートリストを保存する（日時順にソート）"""
    # created_at でソート（古い順）
    # datetime型にパースして比較する
    tweets.sort(key=lambda x: parse_date(x.get("created_at") or ""))
    
    with open(TWEETS_FILE, "w", encoding="utf-8") as f:
        json.dump(tweets, f, indent=2, ensure_ascii=False)

def add_tweet(tweet_id: str, created_at: str, text: str = ""):
    """新しいツイートを追加"""
    tweets = load_tweets()
    
    # 重複チェック
    if any(t["id"] == str(tweet_id) for t in tweets):
        return

    tweets.append({
        "id": str(tweet_id),
        "created_at": created_at,
        "text": text
    })
    save_tweets(tweets)

def get_oldest_tweet() -> dict | None:
    """最も古いツイートを取得"""
    tweets = load_tweets()
    if not tweets:
        return None
    # ソート済み前提だが、念のためパースしてソートする
    tweets.sort(key=lambda x: parse_date(x.get("created_at") or ""))
    return tweets[0]

def remove_tweet(tweet_id: str):
    """ツイートを削除"""
    tweets = load_tweets()
    tweets = [t for t in tweets if t["id"] != str(tweet_id)]
    save_tweets(tweets)

def get_count() -> int:
    """保存されているツイート数を取得"""
    return len(load_tweets())
