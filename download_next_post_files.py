import os
import json
import re
import sys
import requests
import codecs
from pathlib import Path
import gdown

def get_folder_files_public(folder_id):
    """
    公開フォルダのHTMLをパースしてファイル名とIDのリストを取得する
    """
    # 複数のURLパターンを試す
    urls = [
        f"https://drive.google.com/embeddedfolderview?id={folder_id}",
        f"https://drive.google.com/drive/folders/{folder_id}"
    ]
    
    items = []
    for url in urls:
        try:
            print(f"フォルダ情報を取得中: {url}")
            response = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            })
            response.raise_for_status()
            html = response.text
            
            # Google Driveの内部データ構造に含まれるファイル名とIDのペアを探す
            # パターン 1: ["id", "name"]
            matches = re.findall(r'\["([a-zA-Z0-9_-]{20,})","([^"]+)"', html)
            for file_id, name in matches:
                # 重複排除とノイズ除去（.js や .css は除外）
                if len(file_id) > 20 and not any(ext in name for ext in ['.js', '.css', '.html']):
                    # Unicodeエスケープの処理 (例: \u0028 -> ()
                    try:
                        name = codecs.decode(name, 'unicode_escape')
                    except:
                        print(f"デコード失敗: {name}")
                        pass
                    items.append({"id": file_id, "name": name})
            
            if items:
                break # 取得できたら終了
        except Exception as e:
            print(f"警告: {url} からの取得に失敗しました: {e}")
            
    # 名前で一意にする
    unique_items = {item['name']: item for item in items}.values()
    return list(unique_items)

def download_file(file_id, output_path):
    """gdownを使用して特定のファイルをダウンロード"""
    url = f"https://drive.google.com/uc?id={file_id}"
    print(f"ダウンロード開始: {output_path}")
    gdown.download(url, str(output_path), quiet=False)

def main():
    # 1. ステータスを読み込んで次回の投稿対象を特定
    status_file = Path("post_status.json")
    if not status_file.exists():
        print("エラー: post_status.json が見つかりません。")
        sys.exit(1)
        
    with open(status_file, "r", encoding="utf-8") as f:
        status = json.load(f)
    
    thumbnails_folder_id = os.getenv("GDRIVE_THUMBNAILS_FOLDER_ID")
    blurred_folder_id = os.getenv("GDRIVE_BLURRED_FOLDER_ID")
    
    if not thumbnails_folder_id or not blurred_folder_id:
        print("エラー: 環境変数 GDRIVE_THUMBNAILS_FOLDER_ID または GDRIVE_BLURRED_FOLDER_ID が設定されていません。")
        sys.exit(1)
        
    print("Google Drive からファイルリストを取得中...")
    thumbnail_files = get_folder_files_public(thumbnails_folder_id)
    blurred_files = get_folder_files_public(blurred_folder_id)
    
    print(f"サムネイル候補: {len(thumbnail_files)}件, 動画候補: {len(blurred_files)}件")
    
    # デバッグ: 取得できたファイル名をいくつか表示
    if thumbnail_files:
        print(f"サムネイル例: {[f['name'] for f in thumbnail_files[:5]]}")
    if blurred_files:
        print(f"動画例: {[f['name'] for f in blurred_files[:5]]}")
    
    # フォルダ作成（常に作成しておくことで後続のエラーを防ぐ）
    Path("thumbnails").mkdir(exist_ok=True)
    Path("blurred").mkdir(exist_ok=True)
    
    # 投稿済みの名前セット
    posted_names = set(status.get("posted", []))
    
    # ペアを組む
    pairs = []
    blurred_map = {Path(f["name"]).stem: f["id"] for f in blurred_files if f["name"].endswith(".mp4")}
    
    for thumb in thumbnail_files:
        if not thumb["name"].endswith(".png"):
            continue
        name = Path(thumb["name"]).stem
        if name in blurred_map and name not in posted_names:
            pairs.append({
                "name": name,
                "thumb_id": thumb["id"],
                "video_id": blurred_map[name]
            })
    
    # 名前でソート（一貫性のため）
    pairs.sort(key=lambda x: x["name"])
    
    if not pairs:
        print("次に投稿可能な新しいペアが見つかりませんでした。")
        sys.exit(0)
    
    # 次に投稿すべき1件を選択
    next_pair = pairs[0]
    print(f"\n次の投稿対象: {next_pair['name']}")
    
    # フォルダ作成
    Path("thumbnails").mkdir(exist_ok=True)
    Path("blurred").mkdir(exist_ok=True)
    
    # ダウンロード実行
    try:
        download_file(next_pair["thumb_id"], Path("thumbnails") / f"{next_pair['name']}.png")
        download_file(next_pair["video_id"], Path("blurred") / f"{next_pair['name']}.mp4")
        print("\n必要なファイルのダウンロードが完了しました。")
    except Exception as e:
        print(f"\nダウンロード中にエラーが発生しました: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
