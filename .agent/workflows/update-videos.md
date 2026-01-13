---
description: サムネイルとブラー動画を最新の状態に更新する
---

# 動画処理の更新

originalsフォルダに新しい動画を追加した後、サムネイルとブラー動画を生成するためのワークフローです。

## 手順

// turbo-all

1. サムネイルを抽出する
```powershell
python extract_thumbnails.py
```

2. ブラー動画を生成する
```powershell
python blur_videos.py
```

3. 処理結果を確認する
```powershell
Get-ChildItem originals, thumbnails, blurred | Format-Table Name, Count
```

## 注意事項

- 処理済みのファイルは自動でスキップされます
- 新しい動画を追加したら、このワークフローを実行してください
- Google Driveの公開フォルダにも自動で同期されます
