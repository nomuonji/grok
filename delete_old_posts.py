"""
X (Twitter) の古い投稿を削除するスクリプト

1回の実行につき、「最も古い投稿」を1つ削除します。
GitHub Actionsで定期実行（5時間に1回程度）されます。

変更点 (2025/02/20):
API検索ではなく、ローカルの tweets.json から最古のデータを取得し、
削除後に tweets.json を更新する方式に変更しました。
"""

import os
import sys
import json
from pathlib import Path
import tweepy
from dotenv import load_dotenv

import tweet_manager

# 設定読み込み
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# 認証情報
API_KEY = os.getenv("X_API_KEY")
API_SECRET = os.getenv("X_API_SECRET")
ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

if not all([API_KEY, API_SECRET, ACCESS_TOKEN, token_secret]):
    print("エラー: APIキーなどの環境変数が設定されていません。")
    sys.exit(1)

def get_twitter_client():
    # v2 Client (ツイート取得・削除用)
    client = tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=token_secret,
        wait_on_rate_limit=True
    )
    return client

def delete_oldest_tweet():
    # 1. ローカルDBから最古のツイートを取得
    oldest_data = tweet_manager.get_oldest_tweet()
    
    if not oldest_data:
        print("tweets.json にデータがありません。削除対象なし。")
        return

    tweet_id = oldest_data["id"]
    created_at = oldest_data.get("created_at", "不明")
    text = oldest_data.get("text", "")
    
    print(f"削除対象: ID={tweet_id} (作成日: {created_at})")
    print(f"内容: {text}")
    
    # 2. APIで削除実行
    client = get_twitter_client()
    try:
        response = client.delete_tweet(tweet_id)
        
        # dataが存在し、deleted: true なら成功
        # またはエラーにならず完了した場合も成功とみなす
        if response.data and response.data.get("deleted"):
            print(f"✓ API削除成功: {tweet_id}")
            # 3. ローカルDBからも削除
            tweet_manager.remove_tweet(tweet_id)
            print(f"✓ tweets.jsonから削除しました（残り: {tweet_manager.get_count()}件）")
        else:
            print(f"⚠ APIレスポンス確認: {response}")
            # delete_tweet は削除成功時に { "deleted": true } を返す
            if response.data and response.data.get("deleted"):
                tweet_manager.remove_tweet(tweet_id)
            else:
                # 失敗かもしれないが、とりあえずエラーじゃないならスルー？
                # いや、deleted: false なら失敗
                pass
            
    except tweepy.TweepyException as e:
        print(f"✗ API例外発生: {e}")
        # 404 Not FoundならDBから削除（既に消えてる）
        if "404" in str(e) or "Not Found" in str(e):
            print("  -> 既に存在しないため、tweets.jsonから削除します。")
            tweet_manager.remove_tweet(tweet_id)
        # 403 Forbidden (権限なし) の場合は消さない（解決が必要）
        else:
            sys.exit(1)

if __name__ == "__main__":
    delete_oldest_tweet()
