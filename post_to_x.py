"""
X (Twitter) 投稿スクリプト

このスクリプトは、サムネイル画像とブラー処理済み動画を
X (Twitter) に投稿します。

機能:
- サムネイル画像を投稿
- その投稿へのリプライとしてブラー動画を投稿
- ステータスファイルで投稿済みを管理
- 一度の実行で1セットを投稿
"""

import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
import tweepy


# 設定ファイルのパス
STATUS_FILE = Path(__file__).parent / "post_status.json"
TEXTS_FILE = Path(__file__).parent / "post_texts.txt"


def load_env():
    """環境変数を読み込み"""
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)
    
    required_vars = [
        "X_API_KEY",
        "X_API_SECRET", 
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
        "LOCAL_THUMBNAILS_PATH",
        "LOCAL_BLURRED_PATH"
    ]
    
    missing = [var for var in required_vars if not os.getenv(var) or os.getenv(var).startswith("your_")]
    
    if missing:
        print("エラー: 以下の環境変数が設定されていません:")
        for var in missing:
            print(f"  - {var}")
        print("\n.envファイルを編集してください。")
        sys.exit(1)
    
    return {
        "api_key": os.getenv("X_API_KEY"),
        "api_secret": os.getenv("X_API_SECRET"),
        "access_token": os.getenv("X_ACCESS_TOKEN"),
        "access_token_secret": os.getenv("X_ACCESS_TOKEN_SECRET"),
        "bearer_token": os.getenv("X_BEARER_TOKEN"),
        "thumbnails_path": Path(os.getenv("LOCAL_THUMBNAILS_PATH")),
        "blurred_path": Path(os.getenv("LOCAL_BLURRED_PATH"))
    }


def get_twitter_client(config: dict) -> tuple[tweepy.Client, tweepy.API]:
    """Twitter API クライアントを作成"""
    # v2 API Client
    client = tweepy.Client(
        bearer_token=config["bearer_token"],
        consumer_key=config["api_key"],
        consumer_secret=config["api_secret"],
        access_token=config["access_token"],
        access_token_secret=config["access_token_secret"],
        wait_on_rate_limit=True
    )
    
    # v1.1 API (メディアアップロード用)
    auth = tweepy.OAuth1UserHandler(
        config["api_key"],
        config["api_secret"],
        config["access_token"],
        config["access_token_secret"]
    )
    api = tweepy.API(auth, wait_on_rate_limit=True)
    
    return client, api


def load_status() -> dict:
    """ステータスファイルを読み込み"""
    if STATUS_FILE.exists():
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"posted": [], "current_index": 0, "text_index": 0}


def save_status(status: dict):
    """ステータスファイルを保存"""
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def get_file_pairs(thumbnails_path: Path, blurred_path: Path) -> list[dict]:
    """サムネイルとブラー動画のペアを取得"""
    pairs = []
    
    # サムネイルファイルを取得
    thumbnail_files = sorted([f for f in thumbnails_path.iterdir() 
                              if f.is_file() and f.suffix.lower() == ".png"])
    
    for thumbnail in thumbnail_files:
        # 対応するブラー動画を探す
        video_name = thumbnail.stem + ".mp4"
        video_path = blurred_path / video_name
        
        if video_path.exists():
            pairs.append({
                "name": thumbnail.stem,
                "thumbnail": thumbnail,
                "video": video_path
            })
    
    return pairs


def load_post_texts() -> list[str]:
    """投稿テキストのストックを読み込み"""
    if not TEXTS_FILE.exists():
        print(f"警告: {TEXTS_FILE.name} が見つかりません。デフォルトテキストを使用します。")
        return ["🎬 新着動画プレビュー"]
    
    texts = []
    with open(TEXTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 空行とコメント行をスキップ
            if line and not line.startswith("#"):
                texts.append(line)
    
    if not texts:
        return ["🎬 新着動画プレビュー"]
    
    return texts


def get_next_text(texts: list[str], status: dict) -> tuple[str, int]:
    """次に使用するテキストを取得（ループ）"""
    text_index = status.get("text_index", 0) % len(texts)
    return texts[text_index], text_index


def upload_media(api: tweepy.API, file_path: Path, media_type: str = "image") -> str:
    """メディアをアップロードしてmedia_idを取得"""
    print(f"  アップロード中: {file_path.name}")
    
    if media_type == "video":
        # 動画アップロード（チャンク形式）
        media = api.media_upload(
            filename=str(file_path),
            media_category="tweet_video",
            chunked=True
        )
        
        # 動画処理完了を待つ
        print("  動画処理中...")
        while True:
            status = api.get_media_upload_status(media.media_id)
            if hasattr(status, 'processing_info'):
                state = status.processing_info.get('state')
                if state == 'succeeded':
                    break
                elif state == 'failed':
                    error = status.processing_info.get('error', {})
                    raise Exception(f"動画処理失敗: {error}")
                else:
                    wait_secs = status.processing_info.get('check_after_secs', 5)
                    time.sleep(wait_secs)
            else:
                break
    else:
        # 画像アップロード
        media = api.media_upload(filename=str(file_path))
    
    print(f"  ✓ アップロード完了: media_id={media.media_id}")
    return str(media.media_id)


def post_to_x(client: tweepy.Client, api: tweepy.API, 
              thumbnail_path: Path, video_path: Path,
              thumbnail_text: str = "", video_text: str = "") -> dict:
    """
    サムネイルとブラー動画をXに投稿
    
    Returns:
        投稿結果の辞書
    """
    result = {}
    
    # 1. サムネイル画像をアップロード
    print("\n[1/4] サムネイル画像をアップロード...")
    thumbnail_media_id = upload_media(api, thumbnail_path, "image")
    
    # 2. サムネイル投稿
    print("[2/4] サムネイル投稿...")
    thumbnail_response = client.create_tweet(
        text=thumbnail_text,
        media_ids=[thumbnail_media_id]
    )
    thumbnail_tweet_id = thumbnail_response.data["id"]
    result["thumbnail_tweet_id"] = thumbnail_tweet_id
    print(f"  ✓ 投稿完了: https://twitter.com/i/status/{thumbnail_tweet_id}")
    
    # 3. ブラー動画をアップロード
    print("[3/4] ブラー動画をアップロード...")
    video_media_id = upload_media(api, video_path, "video")
    
    # 4. リプライとして動画を投稿
    print("[4/4] リプライ投稿...")
    video_response = client.create_tweet(
        media_ids=[video_media_id],
        in_reply_to_tweet_id=thumbnail_tweet_id
    )
    video_tweet_id = video_response.data["id"]
    result["video_tweet_id"] = video_tweet_id
    print(f"  ✓ 投稿完了: https://twitter.com/i/status/{video_tweet_id}")
    
    return result


def main():
    """メイン処理"""
    print("=== X投稿スクリプト ===\n")
    
    # 環境変数を読み込み
    config = load_env()
    
    # ステータスを読み込み
    status = load_status()
    
    # ファイルペアを取得
    pairs = get_file_pairs(config["thumbnails_path"], config["blurred_path"])
    
    if not pairs:
        print("エラー: 投稿可能なファイルペアが見つかりません。")
        return
    
    print(f"検出されたファイルペア: {len(pairs)}セット")
    
    # 未投稿のペアを探す
    posted_names = set(status["posted"])
    unpaired = [p for p in pairs if p["name"] not in posted_names]
    
    if not unpaired:
        print("\n全てのファイルが投稿済みです。")
        print("ステータスをリセットするには post_status.json を削除してください。")
        return
    
    print(f"未投稿: {len(unpaired)}セット")
    
    # 次に投稿するペアを取得
    next_pair = unpaired[0]
    
    print(f"\n--- 投稿対象 ---")
    print(f"名前: {next_pair['name']}")
    print(f"サムネイル: {next_pair['thumbnail'].name}")
    print(f"動画: {next_pair['video'].name}")
    
    # 投稿テキストを取得
    texts = load_post_texts()
    post_text, text_index = get_next_text(texts, status)
    print(f"投稿テキスト: {post_text}")
    
    try:
        # Twitter APIクライアントを作成
        client, api = get_twitter_client(config)
        
        # 投稿実行
        result = post_to_x(
            client, api,
            next_pair["thumbnail"],
            next_pair["video"],
            thumbnail_text=post_text,
            video_text=""  # ブラー動画はテキストなし
        )
        
        # ステータスを更新
        status["posted"].append(next_pair["name"])
        status["current_index"] = len(status["posted"])
        status["text_index"] = (text_index + 1) % len(texts)  # 次のテキストへ
        save_status(status)
        
        print(f"\n=== 投稿完了 ===")
        print(f"進捗: {len(status['posted'])}/{len(pairs)} セット投稿済み")
        
    except tweepy.TweepyException as e:
        print(f"\n✗ Twitter APIエラー: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
