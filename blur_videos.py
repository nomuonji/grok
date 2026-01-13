"""
動画ブラー処理スクリプト

このスクリプトは、指定されたフォルダ内の動画ファイルに対して、
再生開始1秒後からブラー（モザイク）処理をかけて別フォルダに出力します。

機能:
- 元動画はそのまま保持
- 処理済みファイルはスキップ
- FFmpegを使用してブラー処理を適用
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


def get_video_duration(video_path: Path) -> float:
    """動画の長さを取得（秒）"""
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(video_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return 0


def apply_blur_after_2sec(input_path: Path, output_path: Path, blur_strength: int = 5) -> bool:
    """
    動画の2秒後からブラー処理を適用
    
    Args:
        input_path: 入力動画のパス
        output_path: 出力動画のパス
        blur_strength: ブラーの強さ（デフォルト: 5、薄めのブラー）
    
    Returns:
        処理成功時True、失敗時False
    """
    # FFmpegフィルター: 最初の2秒は通常、それ以降はブラー処理
    # boxblurフィルターを使用してブラー効果を適用（薄めのブラー）
    filter_complex = (
        f"[0:v]split=2[v1][v2];"
        f"[v1]trim=0:2,setpts=PTS-STARTPTS[clean];"
        f"[v2]trim=2,setpts=PTS-STARTPTS,boxblur={blur_strength}:{blur_strength}[blurred];"
        f"[clean][blurred]concat=n=2:v=1:a=0[outv]"
    )
    
    # 音声がある場合のコマンド
    cmd = [
        'ffmpeg',
        '-y',  # 上書き確認なし
        '-i', str(input_path),
        '-filter_complex', filter_complex,
        '-map', '[outv]',
        '-map', '0:a?',  # 音声があれば含める（なくてもエラーにならない）
        '-c:v', 'libx264',
        '-preset', 'medium',
        '-crf', '23',
        '-c:a', 'aac',
        '-b:a', '128k',
        str(output_path)
    ]
    
    try:
        print(f"  処理中: {input_path.name}")
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


def process_videos(source_folder: str, output_folder_name: str = "blurred") -> None:
    """
    フォルダ内の全動画にブラー処理を適用
    
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
    
    print(f"=== 動画ブラー処理 ===")
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
        output_file = output_path / video_file.name
        
        # 既に処理済みの場合はスキップ
        if output_file.exists():
            print(f"  スキップ（処理済み）: {video_file.name}")
            skipped_count += 1
            continue
        
        # 動画の長さをチェック（2秒未満の場合はスキップ）
        duration = get_video_duration(video_file)
        if duration < 2.0:
            print(f"  スキップ（2秒未満）: {video_file.name} ({duration:.2f}秒)")
            skipped_count += 1
            continue
        
        # ブラー処理を適用
        if apply_blur_after_2sec(video_file, output_file):
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
    output_folder_name = sys.argv[2] if len(sys.argv) > 2 else "blurred"
    
    process_videos(source_folder, output_folder_name)
