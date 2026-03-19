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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image
from generate_post_text import generate_post_text_gemini
import tweet_manager

# 設定ファイルのパス
STATUS_FILE = Path(__file__).parent / "post_status.json"
TEXTS_FILE = Path(__file__).parent / "post_texts.txt"
TEXTS_EN_FILE = Path(__file__).parent / "post_texts_en.txt"
# META_TOKENS_FILE は Gist管理にするため削除


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

    # Gemini API (投稿文生成用)
    config["gemini_api_key"] = os.getenv("GEMINI_API_KEY")

    # Gist (トークン管理用)
    config["gist_id"] = os.getenv("GIST_ID")
    config["gist_token"] = os.getenv("GIST_TOKEN")

    # Gistからトークンを読み込み
    if config["gist_id"] and config["gist_token"]:
        meta_tokens = load_tokens_from_gist(config["gist_id"], config["gist_token"])
        
        if meta_tokens:
            try:
                updated = False
                
                # Instagramトークン処理
                if "instagram" in meta_tokens:
                    ig_data = meta_tokens["instagram"]
                    # user_id はローカル.envを優先（Gistに書かないため）
                    
                    # リフレッシュチェック
                    new_token = check_and_refresh_token(
                        "instagram", 
                        ig_data.get("access_token"), 
                        ig_data.get("expires_at")
                    )
                    if new_token:
                        config["instagram_access_token"] = new_token
                        # ファイル更新用データ
                        meta_tokens["instagram"]["access_token"] = new_token
                        meta_tokens["instagram"]["updated_at"] = datetime.now(timezone(timedelta(hours=9))).isoformat()
                        # 有効期限を更新（60日後）
                        meta_tokens["instagram"]["expires_at"] = (datetime.now(timezone(timedelta(hours=9))) + timedelta(days=60)).isoformat()
                        updated = True
                    else:
                        config["instagram_access_token"] = ig_data.get("access_token", config["instagram_access_token"])

                # Threadsトークン処理
                if "threads" in meta_tokens:
                    th_data = meta_tokens["threads"]
                    # user_id はローカル.envを優先
                    
                    # リフレッシュチェック
                    new_token = check_and_refresh_token(
                        "threads", 
                        th_data.get("access_token"), 
                        th_data.get("expires_at")
                    )
                    if new_token:
                        config["threads_access_token"] = new_token
                        meta_tokens["threads"]["access_token"] = new_token
                        meta_tokens["threads"]["updated_at"] = datetime.now(timezone(timedelta(hours=9))).isoformat()
                        meta_tokens["threads"]["expires_at"] = (datetime.now(timezone(timedelta(hours=9))) + timedelta(days=60)).isoformat()
                        updated = True
                    else:
                        config["threads_access_token"] = th_data.get("access_token", config["threads_access_token"])
                
                # 更新があればGistに保存
                if updated:
                    save_tokens_to_gist(meta_tokens, config["gist_id"], config["gist_token"])
                    
            except Exception as e:
                print(f"警告: トークンデータの更新処理に失敗しました: {e}")
    else:
        print("ℹ️ Gist設定が見つからないため、トークン自動更新機能はスキップします。")
            
    return config


def load_tokens_from_gist(gist_id: str, token: str) -> dict | None:
    """GistからトークンJSONを読み込む"""
    try:
        url = f"https://api.github.com/gists/{gist_id}"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        res = requests.get(url, headers=headers, timeout=30)
        res.raise_for_status()
        
        data = res.json()
        files = data.get("files", {})
        
        if "grok_meta_tokens.json" in files:
            content = files["grok_meta_tokens.json"]["content"]
            return json.loads(content)
        
        print("警告: grok_meta_tokens.json がGistに見つかりません")
        return None
        
    except Exception as e:
        print(f"警告: Gist読み込みエラー: {e}")
        return None


def save_tokens_to_gist(tokens: dict, gist_id: str, token: str):
    """GistにトークンJSONを保存"""
    print("💾 Gistのトークン情報を更新中...")
    try:
        url = f"https://api.github.com/gists/{gist_id}"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        payload = {
            "files": {
                "grok_meta_tokens.json": {
                    "content": json.dumps(tokens, indent=2, ensure_ascii=False)
                }
            }
        }
        
        res = requests.patch(url, headers=headers, json=payload, timeout=30)
        res.raise_for_status()
        print("  ✓ Gistを更新しました")
        
    except Exception as e:
        print(f"  ✗ Gist更新エラー: {e}")


def check_and_refresh_token(platform: str, current_token: str, expires_at_str: str) -> str | None:
    """
    トークンの有効期限をチェックし、期限が近い場合はリフレッシュする
    Returns: 新しいトークン (更新なしの場合は None)
    """
    if not current_token:
        return None
        
    should_refresh = False
    
    if not expires_at_str:
        should_refresh = True
    else:
        try:
            # ISOフォーマットパース
            expires_at = datetime.fromisoformat(expires_at_str)
            now = datetime.now(expires_at.tzinfo)
            days_left = (expires_at - now).days
            
            # 残り7日未満なら更新
            if days_left < 7:
                print(f"ℹ️ {platform} トークンの有効期限が残り {days_left} 日です。リフレッシュを試みます。")
                should_refresh = True
            else:
                # print(f"  {platform} トークン有効期限: あと {days_left} 日")
                pass
        except ValueError:
            should_refresh = True
            
    if should_refresh:
        return refresh_access_token_api(platform, current_token)
    
    return None


def refresh_access_token_api(platform: str, token: str) -> str | None:
    """APIを叩いてトークンをリフレッシュ"""
    print(f"🔄 {platform} トークンをリフレッシュ中...")
    
    try:
        url = ""
        params = {
            "grant_type": "ig_refresh_token", # Threadsも基本はこれだが、th_refresh_tokenの場合も考慮
            "access_token": token
        }
        
        if platform == "instagram":
            url = "https://graph.instagram.com/refresh_access_token"
        elif platform == "threads":
            url = "https://graph.threads.net/refresh_access_token"
            # Threadsは th_refresh_token の可能性があるため、エラーなら再試行するロジックを入れても良いが
            # 現状は ig_refresh_token で試行。
            
        res = requests.get(url, params=params, timeout=30)
        
        if res.status_code != 200:
            # Threadsの場合、th_refresh_tokenを試す
            if platform == "threads":
                params["grant_type"] = "th_refresh_token"
                res = requests.get(url, params=params, timeout=30)
        
        if res.status_code == 200:
            data = res.json()
            new_token = data.get("access_token")
            if new_token:
                print(f"  ✓ {platform} トークンリフレッシュ成功")
                return new_token
        
        print(f"  ✗ リフレッシュ失敗: {res.text}")
        return None
        
    except Exception as e:
        print(f"  ✗ リフレッシュ例外: {e}")
        return None


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


def load_post_texts(file_path: Path = None, default_text: str = "🎬 新着動画プレビュー") -> list[str]:
    """投稿テキストのストックを読み込み"""
    if file_path is None:
        file_path = TEXTS_FILE
    
    if not file_path.exists():
        print(f"警告: {file_path.name} が見つかりません。デフォルトテキストを使用します。")
        return [default_text]
    
    texts = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 空行とコメント行をスキップ
            if line and not line.startswith("#"):
                texts.append(line)
    
    if not texts:
        return [default_text]
    
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
              thumbnail_text: str = "", video_text: str = "",
              community_text: str = "") -> dict:
    """
    サムネイルと動画をXに投稿（1つのツイートにまとめる）
    + コミュニティにも投稿
    
    Returns:
        投稿結果の辞書
    """
    result = {}
    
    # コミュニティIDリスト
    COMMUNITY_IDS = [
        "1974877054194553068",
        "2010978695356219537",
    ]
    
    # 1. サムネイル画像をアップロード
    print("\n[X 1/2] メディアをアップロード...")
    thumbnail_media_id = upload_media(api, thumbnail_path, "image")
    print(f"  画像ID: {thumbnail_media_id}")
    
    # 2. 動画をアップロード
    video_media_id = upload_media(api, video_path, "video")
    print(f"  動画ID: {video_media_id}")
    
    # 3. メインツイートを投稿
    print("[X 2/2] ツイート投稿...")
    # 画像と動画を同時に添付（Mixed Media）
    response = client.create_tweet(
        text=thumbnail_text,
        media_ids=[thumbnail_media_id, video_media_id]
    )
    tweet_id = response.data["id"]
    result["tweet_id"] = tweet_id # キー名を統一
    result["thumbnail_tweet_id"] = tweet_id # 互換性のため残す
    
    print(f"  ✓ 投稿完了: https://twitter.com/i/status/{tweet_id}")
    
    # 4. コミュニティにも投稿
    result["community_posts"] = []
    for community_id in COMMUNITY_IDS:
        try:
            print(f"\n[X Community] コミュニティ {community_id} に投稿中...")
            # コミュニティ投稿用にメディアを再アップロード
            # （同じmedia_idは別ツイートで再利用できないため）
            cm_thumbnail_media_id = upload_media(api, thumbnail_path, "image")
            cm_video_media_id = upload_media(api, video_path, "video")
            
            cm_response = client.create_tweet(
                text=community_text if community_text else thumbnail_text,
                media_ids=[cm_thumbnail_media_id, cm_video_media_id],
                community_id=community_id
            )
            cm_tweet_id = cm_response.data["id"]
            result["community_posts"].append({
                "community_id": community_id,
                "tweet_id": cm_tweet_id
            })
            print(f"  ✓ コミュニティ投稿完了: https://twitter.com/i/status/{cm_tweet_id}")
        except Exception as e:
            print(f"  ✗ コミュニティ {community_id} への投稿失敗: {e}")
            result["community_posts"].append({
                "community_id": community_id,
                "error": str(e)
            })
    
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


def resize_image_for_instagram(image_path: Path) -> Path:
    """
    Instagramのフィード投稿要件（アスペクト比 4:5 ~ 1.91:1）に合わせて画像を調整
    縦長すぎる画像（9:16など）は、中央で 4:5 にクロップする
    """
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            aspect_ratio = width / height
            
            # Instagramの許容アスペクト比
            MIN_RATIO = 0.8   # 4:5
            MAX_RATIO = 1.91  # 1.91:1
            
            # アスペクト比が範囲内ならそのまま
            if MIN_RATIO <= aspect_ratio <= MAX_RATIO:
                return image_path
                
            print(f"⚠️ 画像アスペクト比調整: {aspect_ratio:.2f} -> {MIN_RATIO} (Instagram用)")
            
            # 縦長すぎる場合（例: 9:16 = 0.56）-> 上下をカットして 4:5 に
            if aspect_ratio < MIN_RATIO:
                new_height = int(width / MIN_RATIO)
                top = (height - new_height) // 2
                bottom = top + new_height
                
                cropped_img = img.crop((0, top, width, bottom))
                
                # 一時ファイルとして保存
                temp_path = image_path.parent / f"ig_temp_{image_path.name}"
                cropped_img.save(temp_path)
                return temp_path
                
            # 横長すぎる場合 -> 今回は省略（通常縦長動画のサムネなので発生しにくい）
            return image_path
            
    except Exception as e:
        print(f"警告: 画像リサイズ失敗: {e}")
        return image_path


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
    
    max_retries = 3
    container_id = None
    
    for attempt in range(max_retries):
        try:
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
            break
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                print(f"  ✗ コンテナ作成タイムアウト/エラー (試行 {attempt+1}): {e}. 10秒後に再試行します...")
                time.sleep(10)
            else:
                raise

    
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
        print("\n全てのファイルが投稿済みです。リセットして最初から投稿を開始します。")
        status["posted"] = []
        status["current_index"] = 0
        save_status(status)
        unpaired = pairs

    
    print(f"未投稿: {len(unpaired)}セット")
    
    # 次に投稿するペアを取得
    next_pair = unpaired[0]
    
    print(f"\n--- 投稿対象 ---")
    print(f"名前: {next_pair['name']}")
    print(f"サムネイル: {next_pair['thumbnail'].name}")
    print(f"動画: {next_pair['video'].name}")
    
    # テキストインデックスを取得（英語版と同期用）
    texts_fallback = load_post_texts()
    _, text_index = get_next_text(texts_fallback, status)
    
    # 日本語投稿テキストをGemini APIで生成
    post_text = None
    if config.get("gemini_api_key"):
        print("\n🤖 Gemini APIで妄想会話テキストを生成中...")
        post_text = generate_post_text_gemini(
            api_key=config["gemini_api_key"],
            text_index=text_index
        )
    
    if not post_text:
        # フォールバック: 静的テキストファイルを使用
        print("ℹ️ フォールバック: post_texts.txt を使用")
        post_text, text_index = get_next_text(texts_fallback, status)
    
    print(f"\n投稿テキスト (JP): {post_text}")
    
    # コミュニティ用英語テキストを取得
    texts_en = load_post_texts(TEXTS_EN_FILE, default_text="🎬 New video preview")
    community_text, _ = get_next_text(texts_en, status)
    print(f"投稿テキスト (EN/Community): {community_text}")
    
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
            video_text="",
            community_text=community_text
        )
        results["x"] = x_result
        
    except tweepy.TweepyException as e:
        print(f"\n✗ X APIエラー: {e}")
        has_error = True
    except Exception as e:
        print(f"\n✗ Xエラー: {e}")
        has_error = True
    
    # ========== 画像をパブリックURLにアップロード (imgBB) ==========
    # InstagramとThreadsの仕様に合わせて、それぞれ最適な画像をアップロードする
    ig_image_url = None
    th_image_url = None
    
    # Instagram用画像準備
    if can_post_instagram(config):
        try:
            # アスペクト比調整
            ig_image_path = resize_image_for_instagram(next_pair['thumbnail'])
            ig_image_url = upload_to_imgbb(ig_image_path, config["imgbb_api_key"])
            
            # 一時ファイルなら削除
            if ig_image_path != next_pair['thumbnail']:
                try:
                    os.remove(ig_image_path)
                except:
                    pass
        except Exception as e:
            print(f"Instagram用画像準備エラー: {e}")
    
    # Threads用画像準備（元の縦長画像でOK）
    if can_post_threads(config):
        if ig_image_url and next_pair['thumbnail'] == resize_image_for_instagram(next_pair['thumbnail']):
             th_image_url = ig_image_url # 同じで良ければ再利用
        else:
            try:
                th_image_url = upload_to_imgbb(next_pair['thumbnail'], config["imgbb_api_key"])
            except Exception as e:
                print(f"Threads用画像準備エラー: {e}")
    
    # ========== Instagram ==========
    if can_post_instagram(config) and ig_image_url:
        try:
            print("\n" + "=" * 50)
            print("📷 Instagram に投稿中...")
            print("=" * 50)
            
            # Instagram用キャプション: テキスト + ハッシュタグ（3個まで）
            ig_caption = f"{post_text}\n\n#裏垢女子 #AI美女 #AIグラビア"
            
            ig_media_id = post_to_instagram(
                image_url=ig_image_url,
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
    if can_post_threads(config) and th_image_url:
        try:
            print("\n" + "=" * 50)
            print("🧵 Threads に投稿中...")
            print("=" * 50)
            
            threads_media_id = post_to_threads(
                image_url=th_image_url,
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
        status["text_index"] = (text_index + 1) % len(texts_fallback)
        save_status(status)
        
        # tweets.json に追加 (Xのみ)
        if "x" in results:
            try:
                tweet_id = results["x"].get("tweet_id")
                if tweet_id:
                    created_at = datetime.now(timezone(timedelta(hours=9))).isoformat()
                    print(f"  💾 DBに追加: ID={tweet_id}")
                    tweet_manager.add_tweet(tweet_id, created_at, post_text[:50])
            except Exception as e:
                print(f"  ⚠ DB追加失敗: {e}")
        
        print(f"\n{'=' * 50}")
        print(f"=== 投稿完了 ===")
        print(f"{'=' * 50}")
        print(f"進捗: {len(status['posted'])}/{len(pairs)} セット投稿済み")
        print(f"\n投稿結果:")
        if "x" in results:
            print(f"  ✓ X: https://twitter.com/i/status/{results['x']['thumbnail_tweet_id']}")
            if results['x'].get('community_posts'):
                for cp in results['x']['community_posts']:
                    if 'tweet_id' in cp:
                        print(f"  ✓ X Community ({cp['community_id']}): https://twitter.com/i/status/{cp['tweet_id']}")
                    else:
                        print(f"  ✗ X Community ({cp['community_id']}): {cp.get('error', '不明なエラー')}")
        if "instagram" in results:
            print(f"  ✓ Instagram: media_id={results['instagram']['media_id']}")
        if "threads" in results:
            print(f"  ✓ Threads: media_id={results['threads']['media_id']}")
    else:
        print(f"\n✗ 全てのプラットフォームへの投稿に失敗しました。")
        sys.exit(1)


if __name__ == "__main__":
    main()
