"""
動画サムネイル抽出スクリプト

このスクリプトは、指定されたフォルダ内の動画ファイルから
最初のフレームを静止画として抽出し、別フォルダに保存します。

機能:
- 元動画はそのまま保持
- 処理済みファイルはスキップ
- FFmpegを使用して最初のフレームを抽出
"""

import os
import subprocess
import sys
from pathlib import Path


def get_video_files(folder_path: Path) -> list[Path]:
    """動画ファイルの一覧を取得"""
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm'}
    video_files = []
    
    for file in folder_path.iterdir():
        if file.is_file() and file.suffix.lower() in video_extensions:
            video_files.append(file)
    
    return video_files


def extract_first_frame(input_path: Path, output_path: Path) -> bool:
    """
    動画の最初のフレームを画像として抽出
    
    Args:
        input_path: 入力動画のパス
        output_path: 出力画像のパス（.png）
    
    Returns:
        処理成功時True、失敗時False
    """
    # FFmpegコマンド: 最初のフレームをPNG（可逆圧縮・劣化なし）として抽出
    cmd = [
        'ffmpeg',
        '-y',  # 上書き確認なし
        '-i', str(input_path),
        '-vframes', '1',  # 1フレームのみ
        '-c:v', 'png',  # PNG形式（可逆圧縮、最高画質）
        '-compression_level', '0',  # 最速圧縮（画質に影響なし）
        str(output_path)
    ]
    
    try:
        print(f"  抽出中: {input_path.name}")
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            check=True,
            encoding='utf-8',
            errors='replace'
        )
        print(f"  ✓ 完了: {output_path.name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ✗ エラー: {input_path.name}")
        print(f"    詳細: {e.stderr[:500] if e.stderr else 'Unknown error'}")
        return False


def extract_thumbnails(source_folder: str, output_folder_name: str = "thumbnails") -> None:
    """
    フォルダ内の全動画から最初のフレームを抽出
    
    Args:
        source_folder: 元動画が格納されているフォルダのパス
        output_folder_name: 出力フォルダ名（ソースフォルダ内に作成）
    """
    source_path = Path(source_folder)
    
    if not source_path.exists():
        print(f"エラー: フォルダが存在しません: {source_folder}")
        sys.exit(1)
    
    # 出力フォルダを作成（親ディレクトリに作成）
    output_path = source_path.parent / output_folder_name
    output_path.mkdir(exist_ok=True)
    
    print(f"=== サムネイル抽出 ===")
    print(f"入力フォルダ: {source_path}")
    print(f"出力フォルダ: {output_path}")
    print()
    
    # 動画ファイルを取得
    video_files = get_video_files(source_path)
    
    if not video_files:
        print("処理対象の動画ファイルが見つかりませんでした。")
        return
    
    print(f"検出された動画ファイル数: {len(video_files)}")
    print()
    
    processed_count = 0
    skipped_count = 0
    error_count = 0
    
    for video_file in video_files:
        # 出力ファイル名: 動画名.png
        output_file = output_path / f"{video_file.stem}.png"
        
        # 既に処理済みの場合はスキップ
        if output_file.exists():
            print(f"  スキップ（処理済み）: {video_file.name}")
            skipped_count += 1
            continue
        
        # 最初のフレームを抽出
        if extract_first_frame(video_file, output_file):
            processed_count += 1
        else:
            error_count += 1
    
    print()
    print(f"=== 処理結果 ===")
    print(f"処理完了: {processed_count} ファイル")
    print(f"スキップ: {skipped_count} ファイル")
    print(f"エラー:   {error_count} ファイル")


if __name__ == "__main__":
    # デフォルトのソースフォルダはoriginalsフォルダ
    default_source = Path(__file__).parent / "originals"
    
    # コマンドライン引数があれば使用
    if len(sys.argv) > 1:
        source_folder = sys.argv[1]
    else:
        source_folder = str(default_source)
    
    # 出力フォルダ名（オプション）
    output_folder_name = sys.argv[2] if len(sys.argv) > 2 else "thumbnails"
    
    extract_thumbnails(source_folder, output_folder_name)
