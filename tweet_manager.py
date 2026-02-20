"""
ツイートデータ管理モジュール

tweets.json を読み書きし、IDと投稿日時のリストを管理する。
"""

import json
from pathlib import Path
from datetime import datetime

TWEETS_FILE = Path(__file__).parent / "tweets.json"

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
    # 日付形式が混在する可能性があるため、文字列としてソートでも概ねOKだが、
    # 厳密には ISO format を前提とする
    tweets.sort(key=lambda x: (x.get("created_at") or ""))
    
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
    return tweets[0] # ソート済み前提

def remove_tweet(tweet_id: str):
    """ツイートを削除"""
    tweets = load_tweets()
    tweets = [t for t in tweets if t["id"] != str(tweet_id)]
    save_tweets(tweets)

def get_count() -> int:
    """保存されているツイート数を取得"""
    return len(load_tweets())
