# S3選択時にプレビューが出ない件 - 調査と計画

## ゴール
- S3にのみ存在する画像を選択した時点でノード上のプレビューが表示される。
- LoadImageS3の実行ロジック（S3ダウンロード/キャッシュ/サムネ利用）を維持する。

## 調査メモ（事実ベース）
- `LoadImageS3.INPUT_TYPES` はS3のキー一覧を返し、`image_upload: True` のみ指定している。`image_folder` は未指定。`s3_nodes.py`
- `image_upload` のプレビューはフロント側で `useImageUploadWidget` が作る。
  - `image_folder` のデフォルトは `input`。
  - combo変更時に `nodeOutputStore.setNodeOutputs` へ値を渡し、`/view?type=input` を使ったプレビューにする。`ComfyUI_frontend/src/renderer/extensions/vueNodes/widgets/composables/useImageUploadWidget.ts`, `ComfyUI_frontend/src/stores/imagePreviewStore.ts`
- `/view` は `input/output/temp` のローカルフォルダからのみ読み込む。`ComfyUI/server.py`
- `LoadImageS3.load_image` は実行時のみプレビュー用ファイルを作る。
  - S3から取得したファイルは `download_to_cache` で `temp/s3-io/...` に保存。
  - `ui` 返却では `local_temp_preview_path` で `temp` 配下のプレビューを参照させている。`s3_nodes.py`, `s3_helpers.py`
- S3のサムネイルは `S3IO_THUMB_PREFIX` に `.jpg` で保存済み。`ensure_thumbnail` はアップロード時に作成。`s3_helpers.py`, `README.md`

## 問題の整理
- 選択時のプレビューは「ローカル input にある前提」で `/view?type=input` を叩くため、S3にのみ存在するファイルはプレビューが表示されない。
- S3サムネイルは実行時にしか取得されず、選択時にはダウンロードしない。

## 方針（決定）
- 選択時にS3からサムネイル（無ければ原本）を取得して `temp` に置き、UIプレビューのみ差し替える。
- 入力値（選択値）はS3キーのまま維持し、実行時のロード/キャッシュ仕様は変えない。

## 実装タスク
1) **プレビュー取得APIの追加**
   - `GET /s3io/preview/image?name=...` を追加。
   - `name` からS3キーを解決し、サムネイルがあれば `download_to_cache(kind="thumbs")`、無ければ `download_to_cache(kind="objects")`。
   - `temp` からの相対パスに変換して `{filename, subfolder, type: "temp"}` を返す。
   - 実装: `s3_server.py`（必要なら `s3_helpers.py` に相対パス化のヘルパを追加）
2) **フロント側で選択時プレビューを差し替え**
   - `LoadImageS3` の combo widget 変更時に上記APIを呼び、返却値で `app.nodeOutputs[node.id]` を更新。
   - 例: `app.nodeOutputs[node.id] = { images: [entry], animated: [false] }` を設定し `node.graph.setDirtyCanvas(true)` で再描画。
   - 連続選択に備えて「最新リクエストのみ反映」するトークン管理を入れる。
   - 実装: `web/js/s3_io_preview.js` を新規追加（または `web/js/s3_io_upload.js` を拡張）
3) **README追記**
   - S3のみの画像選択時はサムネイルを `temp` にキャッシュしてプレビューを出す旨を記載。
   - 実装: `README.md`

## 影響範囲（候補）
- `s3_server.py`
- `s3_helpers.py`（必要なら）
- `web/js/s3_io_preview.js` もしくは `web/js/s3_io_upload.js`
- `README.md`

## 検証観点
- S3にのみ存在する画像を選択した瞬間にノードプレビューが表示される。
- ローカル input にある画像は従来通り即プレビュー（回帰なし）。
- 連続で別の画像を選んだ場合でも最新のプレビューだけが表示される。
- 実行時の画像ロード（S3ダウンロード/サムネ利用）が壊れていない。
