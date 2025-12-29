# S3選択時にLoad Videoのプレビューが出ない件 - 調査と計画

## ゴール
- S3にのみ存在する動画を選択した時点でノード上のプレビューが表示される。
- LoadVideoUploadS3の実行ロジック（S3ダウンロード/キャッシュ）は維持する。

## 調査メモ（事実ベース）
- `LoadVideoUploadS3.INPUT_TYPES` はS3のキー一覧を返し、`video_upload: True` を指定している。`s3_nodes.py`
- `video_upload` のUIはフロント側の `uploadImage` 拡張が `IMAGEUPLOAD` ウィジェットを追加し、`useImageUploadWidget` がプレビュー処理を行う。`ComfyUI_frontend/src/extensions/core/uploadImage.ts`, `ComfyUI_frontend/src/renderer/extensions/vueNodes/widgets/composables/useImageUploadWidget.ts`
- `useImageUploadWidget` は `image_folder` のデフォルトを `input` とし、選択時に `nodeOutputStore.setNodeOutputs` で `images` を設定する。`ComfyUI_frontend/src/renderer/extensions/vueNodes/widgets/composables/useImageUploadWidget.ts`, `ComfyUI_frontend/src/stores/imagePreviewStore.ts`
- `nodeOutputStore.getNodeImageUrls` は `images` の値から `/view?type=...` を組み立てる。`ComfyUI_frontend/src/stores/imagePreviewStore.ts`
- `/view` はローカルの `input/output/temp` のみを参照する。`ComfyUI/server.py`
- S3の動画は `download_to_cache` で `temp/s3-io/objects/...` に保存され、ETagベースで再ダウンロードが制御される。`s3_helpers.py`

## 問題の整理
- 選択時プレビューは `/view?type=input` 前提でローカル入力を参照するため、S3にのみ存在する動画ではプレビューが出ない。
- 動画プレビュー用のサムネイル生成機構は現状ないため、プレビューには実動画ファイルを使う必要がある。

## 方針（決定）
- 選択時にS3から動画をキャッシュへ取得し、`temp` を参照するプレビューに差し替える。
- 入力値（選択値）はS3キーのまま維持する。

## 実装タスク
1) **動画プレビュー取得APIの追加**
   - `GET /s3io/preview/video?name=...` を追加。
   - `name` からS3キーを解決し、`download_to_cache(kind="objects")` でローカルへ取得。
   - `local_temp_preview_path` で `temp` 相対パスにし、`{filename, subfolder, type: "temp"}` を返す。
   - 実装: `s3_server.py`
2) **LoadVideoUploadS3の選択時プレビューを差し替え**
   - combo選択変更時に上記APIを呼び、`app.nodeOutputs[node.id] = { images: [entry], animated: [false] }` を設定する。
   - 連続選択でも最新だけ反映するようトークン管理を入れる。
   - 実装: `web/js/s3_io_upload.js`（既存のS3プレビュー拡張にLoadVideoUploadS3を追加）
3) **README追記**
   - S3のみの動画選択時はプレビュー用に動画を `temp` にキャッシュする旨を記載。
   - 実装: `README.md`

## 影響範囲（候補）
- `s3_server.py`
- `web/js/s3_io_upload.js`
- `README.md`

## 検証観点
- S3にのみ存在する動画を選択した瞬間にプレビューが表示される。
- ローカル input にある動画は従来通り即プレビュー（回帰なし）。
- 連続で別の動画を選んだ場合でも最新のプレビューだけが表示される。
- 実行時の動画ロード（S3ダウンロード/キャッシュ）が壊れていない。
