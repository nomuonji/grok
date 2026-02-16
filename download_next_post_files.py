import os
import json
import re
import sys
import requests
import codecs
from pathlib import Path
import gdown
from dotenv import load_dotenv

def get_folder_files_public(folder_id):
    """
    公開フォルダのHTMLをパースしてファイル名とIDのリストを取得する
    """
    urls = [
        f"https://drive.google.com/embeddedfolderview?id={folder_id}",
        f"https://drive.google.com/drive/folders/{folder_id}"
    ]
    
    items_dict = {} # 名前をキーにして重複を防ぐ
    for url in urls:
        try:
            print(f"フォルダ情報を取得中: {url}")
            response = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36'
            })
            response.raise_for_status()
            html = response.text
            
            # --- 抽出パターン1: ["ID", "名前"] ---
            matches = re.findall(r'\["([a-zA-Z0-9_-]{20,})","([^"]+)"', html)
            for file_id, name in matches:
                name_lower = name.lower()
                if any(noise in name_lower for noise in ['drive_2020q4', 'branding', 'product', 'logo', 'favicon']):
                    continue
                if any(ext in name_lower for ext in ['.png', '.mp4', '.mov', '.jpg']):
                    if not name.startswith('http') and '.' not in file_id:
                        try: name = codecs.decode(name, 'unicode_escape')
                        except: pass
                        if len(name) > 3:
                            items_dict[name] = {"id": file_id, "name": name}

            # --- 抽出パターン2: flip-entry (HTML直接パース) ---
            # id="entry-XXXX" ... >TITLE</div>
            entry_matches = re.finditer(r'id="entry-([a-zA-Z0-9_-]+)"[^>]*>.*?class="flip-entry-title">([^<]+)</div>', html, re.DOTALL)
            for m in entry_matches:
                file_id, name = m.group(1), m.group(2)
                if any(ext in name.lower() for ext in ['.png', '.mp4', '.mov', '.jpg']):
                    items_dict[name] = {"id": file_id, "name": name}

            # --- 抽出パターン3: 拡張子から遡ってIDを探す ---
            for ext in ['.png', '.mp4']:
                raw_matches = re.finditer(r'"([^"]+' + re.escape(ext) + r')"', html)
                for m in raw_matches:
                    name = m.group(1)
                    if any(noise in name.lower() for noise in ['drive_2020q4', 'branding', 'product']):
                        continue
                    start_pos = max(0, m.start() - 500)
                    chunk = html[start_pos : m.start()]
                    id_matches = re.findall(r'["\']([a-zA-Z0-9_-]{25,})["\']', chunk)
                    if id_matches:
                        file_id = id_matches[-1]
                        if name not in items_dict:
                            items_dict[name] = {"id": file_id, "name": name}

            if items_dict:
                print(f"  -> {len(items_dict)} 個のファイルを発見しました")
                break
            else:
                # 何も見つからない場合のみHTMLの断片を表示
                print(f"  HTML スニペット (1000文字): {html[:1000]}")
                
        except Exception as e:
            print(f"警告: {url} からの取得に失敗しました: {e}")
            
    return list(items_dict.values())

def download_file(file_id, output_path):
    """gdownを使用して特定のファイルをダウンロード"""
    url = f"https://drive.google.com/uc?id={file_id}"
    print(f"ダウンロード開始: {output_path}")
    gdown.download(url, str(output_path), quiet=False)

def main():
    # .envがあれば読み込む（ローカルテスト用）
    load_dotenv()
    
    # 1. ステータスを読み込んで次回の投稿対象を特定
    status_file = Path("post_status.json")
    if not status_file.exists():
        print("エラー: post_status.json が見つかりません。")
        sys.exit(1)
        
    with open(status_file, "r", encoding="utf-8") as f:
        status = json.load(f)
    
    thumbnails_folder_id = os.getenv("GDRIVE_THUMBNAILS_FOLDER_ID")
    originals_folder_id = os.getenv("GDRIVE_ORIGINALS_FOLDER_ID")
    
    if not thumbnails_folder_id or not originals_folder_id:
        print("エラー: 環境変数 GDRIVE_THUMBNAILS_FOLDER_ID または GDRIVE_ORIGINALS_FOLDER_ID が設定されていません。")
        sys.exit(1)
        
    print("Google Drive からファイルリストを取得中...")
    thumbnail_files = get_folder_files_public(thumbnails_folder_id)
    originals_files = get_folder_files_public(originals_folder_id)
    
    print(f"サムネイル候補: {len(thumbnail_files)}件, 動画候補: {len(originals_files)}件")
    
    # デバッグ: 取得できたファイル名をいくつか表示
    if thumbnail_files:
        print(f"サムネイル例: {[f['name'] for f in thumbnail_files[:5]]}")
    if originals_files:
        print(f"動画例: {[f['name'] for f in originals_files[:5]]}")
    
    # フォルダ作成（常に作成しておくことで後続のエラーを防ぐ）
    Path("thumbnails").mkdir(exist_ok=True)
    Path("originals").mkdir(exist_ok=True)
    
    # 投稿済みの名前セット
    posted_names = set(status.get("posted", []))
    
    # ペアを組む
    pairs = []
    originals_map = {Path(f["name"]).stem: f["id"] for f in originals_files if f["name"].endswith(".mp4")}
    
    for thumb in thumbnail_files:
        if not thumb["name"].endswith(".png"):
            continue
        name = Path(thumb["name"]).stem
        if name in originals_map and name not in posted_names:
            pairs.append({
                "name": name,
                "thumb_id": thumb["id"],
                "video_id": originals_map[name]
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
    Path("originals").mkdir(exist_ok=True)
    
    # ダウンロード実行
    try:
        download_file(next_pair["thumb_id"], Path("thumbnails") / f"{next_pair['name']}.png")
        download_file(next_pair["video_id"], Path("originals") / f"{next_pair['name']}.mp4")
        print("\n必要なファイルのダウンロードが完了しました。")
    except Exception as e:
        print(f"\nダウンロード中にエラーが発生しました: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
