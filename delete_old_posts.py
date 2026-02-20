"""
X (Twitter) の古い投稿を削除するスクリプト

1回の実行につき、「最も古い投稿」を1つ削除します。
GitHub Actionsで定期実行（1日5回程度）することで、
「1日5個ペースで古い投稿が消える」を実現します。
"""

import os
import sys
from pathlib import Path
import tweepy
from dotenv import load_dotenv

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
    client = get_twitter_client()
    
    # 自分のユーザーIDを取得
    me = client.get_me()
    user_id = me.data.id
    print(f"User ID: {user_id}")
    
    # ツイートを取得
    # 一番古いツイートを見つけるため、ページングして最後まで取得する必要があるが、
    # API制限を考慮し、ここでは「取得できた範囲の中で最も古いツイート」を対象とする。
    # max_results=100 で取得し、その中で一番古い（リストの末尾）ものを削除候補とする。
    # ※ 投稿数が膨大な場合、本当に「一番最初の投稿」ではない可能性があるが、運用上はこれで「古いものから」消えていく。
    
    # Paginatorを使ってツイートを取得
    # limit=None にすると全件取得しようとするが、API制限に注意
    # ここでは1回の実行につき最大1000件程度まで遡る設定にする
    tweets = []
    try:
        for tweet in tweepy.Paginator(
            client.get_users_tweets,
            id=user_id,
            max_results=100,
            tweet_fields=["created_at"]
        ).flatten(limit=1000):
            tweets.append(tweet)
    except Exception as e:
        print(f"ツイート取得エラー: {e}")
        return

    if not tweets:
        print("削除対象のツイートが見つかりませんでした（投稿数0）。")
        return
    
    # 新しい順に取得されるので、リストの末尾が一番古い
    oldest_tweet = tweets[-1]
    
    print(f"削除対象: {oldest_tweet.id} ({oldest_tweet.created_at})")
    print(f"内容: {oldest_tweet.text[:30]}...")
    
    # 削除実行
    try:
        client.delete_tweet(oldest_tweet.id)
        print(f"✓ 削除成功: {oldest_tweet.id}")
    except Exception as e:
        print(f"✗ 削除失敗: {e}")
        sys.exit(1)

if __name__ == "__main__":
    delete_oldest_tweet()
