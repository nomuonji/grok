"""
X (Twitter) / Instagram / Threads 投稿スクリプト

このスクリプトは、サムネイル画像とブラー処理済み動画を
X (Twitter) に投稿し、同じサムネイル画像を
Instagram と Threads にも投稿します。

機能:
- サムネイル画像をXに投稿（+ リプライとしてブラー動画を投稿）
- サムネイル画像をInstagramに投稿（画像のみ）
- サムネイル画像をThreadsに投稿（画像+テキスト）
- ステータスファイルで投稿済みを管理
- 一度の実行で1セットを投稿
"""

import json
import os
import sys
import time
import base64
from pathlib import Path
from dotenv import load_dotenv
import tweepy
import requests


# 設定ファイルのパス
STATUS_FILE = Path(__file__).parent / "post_status.json"
TEXTS_FILE = Path(__file__).parent / "post_texts.txt"


def load_env():
    """環境変数を読み込み"""
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)
    
    # X (Twitter) は必須
    required_vars = [
        "X_API_KEY",
        "X_API_SECRET", 
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
        "LOCAL_THUMBNAILS_PATH",
        "LOCAL_ORIGINALS_PATH"
    ]
    
    missing = [var for var in required_vars if not os.getenv(var) or os.getenv(var).startswith("your_")]
    
    if missing:
        print("エラー: 以下の環境変数が設定されていません:")
        for var in missing:
            print(f"  - {var}")
        print("\n.envファイルを編集してください。")
        sys.exit(1)
    
    config = {
        "api_key": os.getenv("X_API_KEY"),
        "api_secret": os.getenv("X_API_SECRET"),
        "access_token": os.getenv("X_ACCESS_TOKEN"),
        "access_token_secret": os.getenv("X_ACCESS_TOKEN_SECRET"),
        "bearer_token": os.getenv("X_BEARER_TOKEN"),
        "thumbnails_path": Path(os.getenv("LOCAL_THUMBNAILS_PATH")),
        "originals_path": Path(os.getenv("LOCAL_ORIGINALS_PATH")),
    }
    
    # Instagram (任意)
    config["instagram_user_id"] = os.getenv("INSTAGRAM_USER_ID")
    config["instagram_access_token"] = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    
    # Threads (任意)
    config["threads_user_id"] = os.getenv("THREADS_USER_ID")
    config["threads_access_token"] = os.getenv("THREADS_ACCESS_TOKEN")
    
    # imgBB (Instagram/Threads使用時に必要)
    config["imgbb_api_key"] = os.getenv("IMGBB_API_KEY")
    
    return config


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


def get_file_pairs(thumbnails_path: Path, originals_path: Path) -> list[dict]:
    """サムネイルとオリジナル動画のペアを取得"""
    pairs = []
    
    # パスの存在確認
    if not thumbnails_path.exists() or not originals_path.exists():
        print(f"ディレクトリが見つかりません: {thumbnails_path} または {originals_path}")
        return []
    
    # サムネイルファイルを取得
    thumbnail_files = sorted([f for f in thumbnails_path.iterdir() 
                              if f.is_file() and f.suffix.lower() == ".png"])
    
    for thumbnail in thumbnail_files:
        # 対応するオリジナル動画を探す
        video_name = thumbnail.stem + ".mp4"
        video_path = originals_path / video_name
        
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
    print("\n[X 1/4] サムネイル画像をアップロード...")
    thumbnail_media_id = upload_media(api, thumbnail_path, "image")
    
    # 2. サムネイル投稿
    print("[X 2/4] サムネイル投稿...")
    thumbnail_response = client.create_tweet(
        text=thumbnail_text,
        media_ids=[thumbnail_media_id]
    )
    thumbnail_tweet_id = thumbnail_response.data["id"]
    result["thumbnail_tweet_id"] = thumbnail_tweet_id
    print(f"  ✓ 投稿完了: https://twitter.com/i/status/{thumbnail_tweet_id}")
    
    # 3. ブラー動画をアップロード
    print("[X 3/4] ブラー動画をアップロード...")
    video_media_id = upload_media(api, video_path, "video")
    
    # 4. リプライとして動画を投稿
    print("[X 4/4] リプライ投稿...")
    video_response = client.create_tweet(
        media_ids=[video_media_id],
        in_reply_to_tweet_id=thumbnail_tweet_id
    )
    video_tweet_id = video_response.data["id"]
    result["video_tweet_id"] = video_tweet_id
    print(f"  ✓ 投稿完了: https://twitter.com/i/status/{video_tweet_id}")
    
    return result


# ============================================================
# imgBB / Instagram / Threads
# ============================================================

def upload_to_imgbb(image_path: Path, api_key: str) -> str:
    """
    画像をimgBBにアップロードしてパブリックURLを取得
    
    Returns:
        画像のパブリックURL
    """
    print(f"\n[imgBB] 画像をアップロード中: {image_path.name}")
    
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")
    
    response = requests.post(
        "https://api.imgbb.com/1/upload",
        data={
            "key": api_key,
            "image": image_data,
            "name": image_path.stem
        },
        timeout=60
    )
    response.raise_for_status()
    result = response.json()
    
    if result.get("success"):
        url = result["data"]["url"]
        print(f"  ✓ アップロード完了: {url}")
        return url
    else:
        raise Exception(f"imgBBアップロード失敗: {result}")


def post_to_instagram(image_url: str, caption: str, 
                      user_id: str, access_token: str) -> str:
    """
    Instagramに画像を投稿
    
    Args:
        image_url: パブリックな画像URL
        caption: 投稿キャプション
        user_id: InstagramユーザーID
        access_token: Instagramアクセストークン
    
    Returns:
        投稿のメディアID
    """
    api_version = "v22.0"
    base_url = f"https://graph.instagram.com/{api_version}"
    
    # Step 1: メディアコンテナを作成
    print("\n[Instagram 1/2] メディアコンテナを作成中...")
    response = requests.post(
        f"{base_url}/{user_id}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": access_token
        },
        timeout=60
    )
    response.raise_for_status()
    container_id = response.json()["id"]
    print(f"  ✓ コンテナ作成完了: {container_id}")
    
    # 処理完了を待つ
    print("[Instagram] 画像処理中（10秒待機）...")
    time.sleep(10)
    
    # Step 2: 公開
    print("[Instagram 2/2] 投稿を公開中...")
    response = requests.post(
        f"{base_url}/{user_id}/media_publish",
        data={
            "creation_id": container_id,
            "access_token": access_token
        },
        timeout=60
    )
    response.raise_for_status()
    media_id = response.json()["id"]
    print(f"  ✓ Instagram投稿完了: media_id={media_id}")
    
    return media_id


def post_to_threads(image_url: str, text: str,
                    user_id: str, access_token: str) -> str:
    """
    Threadsに画像を投稿
    
    Args:
        image_url: パブリックな画像URL
        text: 投稿テキスト
        user_id: ThreadsユーザーID  
        access_token: Threadsアクセストークン
    
    Returns:
        投稿のメディアID
    """
    base_url = "https://graph.threads.net/v1.0"
    
    # Step 1: メディアコンテナを作成
    print("\n[Threads 1/2] メディアコンテナを作成中...")
    response = requests.post(
        f"{base_url}/{user_id}/threads",
        data={
            "media_type": "IMAGE",
            "image_url": image_url,
            "text": text,
            "access_token": access_token
        },
        timeout=60
    )
    response.raise_for_status()
    container_id = response.json()["id"]
    print(f"  ✓ コンテナ作成完了: {container_id}")
    
    # Metaのサーバーが処理する時間を確保（公式推奨: 30秒）
    print("[Threads] 画像処理中（30秒待機）...")
    time.sleep(30)
    
    # Step 2: 公開
    print("[Threads 2/2] 投稿を公開中...")
    response = requests.post(
        f"{base_url}/{user_id}/threads_publish",
        data={
            "creation_id": container_id,
            "access_token": access_token
        },
        timeout=60
    )
    response.raise_for_status()
    media_id = response.json()["id"]
    print(f"  ✓ Threads投稿完了: media_id={media_id}")
    
    return media_id


def can_post_instagram(config: dict) -> bool:
    """Instagram投稿が可能かチェック"""
    return bool(
        config.get("instagram_user_id") 
        and config.get("instagram_access_token")
        and config.get("imgbb_api_key")
    )


def can_post_threads(config: dict) -> bool:
    """Threads投稿が可能かチェック"""
    return bool(
        config.get("threads_user_id")
        and config.get("threads_access_token")
        and config.get("imgbb_api_key")
    )


def main():
    """メイン処理"""
    print("=== SNS投稿スクリプト (X / Instagram / Threads) ===\n")
    
    # 環境変数を読み込み
    config = load_env()
    
    # 投稿可能なプラットフォームを表示
    platforms = ["X"]
    if can_post_instagram(config):
        platforms.append("Instagram")
    else:
        print("ℹ️ Instagram: 認証情報未設定のためスキップ")
    if can_post_threads(config):
        platforms.append("Threads")
    else:
        print("ℹ️ Threads: 認証情報未設定のためスキップ")
    
    print(f"投稿先: {', '.join(platforms)}\n")
    
    # ステータスを読み込み
    status = load_status()
    
    # ファイルペアを取得
    pairs = get_file_pairs(config["thumbnails_path"], config["originals_path"])
    
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
    
    # 各プラットフォームの投稿結果を記録
    results = {}
    has_error = False
    
    # ========== X (Twitter) ==========
    try:
        print("\n" + "=" * 50)
        print("📘 X (Twitter) に投稿中...")
        print("=" * 50)
        
        client, api = get_twitter_client(config)
        
        x_result = post_to_x(
            client, api,
            next_pair["thumbnail"],
            next_pair["video"],
            thumbnail_text=post_text,
            video_text=""
        )
        results["x"] = x_result
        
    except tweepy.TweepyException as e:
        print(f"\n✗ X APIエラー: {e}")
        has_error = True
    except Exception as e:
        print(f"\n✗ Xエラー: {e}")
        has_error = True
    
    # ========== 画像をパブリックURLにアップロード (imgBB) ==========
    public_image_url = None
    if can_post_instagram(config) or can_post_threads(config):
        try:
            print("\n" + "=" * 50)
            print("🖼️ imgBBに画像をアップロード中...")
            print("=" * 50)
            
            public_image_url = upload_to_imgbb(
                next_pair["thumbnail"],
                config["imgbb_api_key"]
            )
        except Exception as e:
            print(f"\n✗ imgBBアップロードエラー: {e}")
            print("  Instagram/Threadsへの投稿をスキップします。")
    
    # ========== Instagram ==========
    if can_post_instagram(config) and public_image_url:
        try:
            print("\n" + "=" * 50)
            print("📷 Instagram に投稿中...")
            print("=" * 50)
            
            # Instagram用キャプション: テキスト + ハッシュタグ（3個まで）
            ig_caption = f"{post_text}\n\n#裏垢女子 #AI美女 #AIグラビア"
            
            ig_media_id = post_to_instagram(
                image_url=public_image_url,
                caption=ig_caption,
                user_id=config["instagram_user_id"],
                access_token=config["instagram_access_token"]
            )
            results["instagram"] = {"media_id": ig_media_id}
            
        except requests.exceptions.HTTPError as e:
            print(f"\n✗ Instagram APIエラー: {e}")
            if e.response is not None:
                print(f"  レスポンス: {e.response.text}")
        except Exception as e:
            print(f"\n✗ Instagramエラー: {e}")
    
    # ========== Threads ==========
    if can_post_threads(config) and public_image_url:
        try:
            print("\n" + "=" * 50)
            print("🧵 Threads に投稿中...")
            print("=" * 50)
            
            threads_media_id = post_to_threads(
                image_url=public_image_url,
                text=post_text,
                user_id=config["threads_user_id"],
                access_token=config["threads_access_token"]
            )
            results["threads"] = {"media_id": threads_media_id}
            
        except requests.exceptions.HTTPError as e:
            print(f"\n✗ Threads APIエラー: {e}")
            if e.response is not None:
                print(f"  レスポンス: {e.response.text}")
        except Exception as e:
            print(f"\n✗ Threadsエラー: {e}")
    
    # ========== ステータス更新 ==========
    # X投稿が成功していれば（または少なくとも1つ成功していれば）ステータスを更新
    if results:
        status["posted"].append(next_pair["name"])
        status["current_index"] = len(status["posted"])
        status["text_index"] = (text_index + 1) % len(texts)
        save_status(status)
        
        print(f"\n{'=' * 50}")
        print(f"=== 投稿完了 ===")
        print(f"{'=' * 50}")
        print(f"進捗: {len(status['posted'])}/{len(pairs)} セット投稿済み")
        print(f"\n投稿結果:")
        if "x" in results:
            print(f"  ✓ X: https://twitter.com/i/status/{results['x']['thumbnail_tweet_id']}")
        if "instagram" in results:
            print(f"  ✓ Instagram: media_id={results['instagram']['media_id']}")
        if "threads" in results:
            print(f"  ✓ Threads: media_id={results['threads']['media_id']}")
    else:
        print(f"\n✗ 全てのプラットフォームへの投稿に失敗しました。")
        sys.exit(1)


if __name__ == "__main__":
    main()
