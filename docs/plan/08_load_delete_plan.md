# Load系ノードの選択ファイル削除 - 調査と計画

## ゴール
- `LoadImageS3` / `LoadVideoUploadS3` で選択中のS3入力ファイルを削除できる（動画も同様に対応）。
- 削除後に一覧・プレビューが更新され、キャッシュの不整合が残らない。

## 調査メモ（事実ベース）
- Load系ノードはS3の一覧を `INPUT_TYPES` で取得する。
  - `LoadImageS3.INPUT_TYPES` / `LoadVideoUploadS3.INPUT_TYPES` が `list_media_keys` を呼ぶ。`s3_nodes.py`
- Load処理は「ローカルがあればS3へアップロード、なければS3からキャッシュへダウンロード」。
  - `LoadImageS3.load_image` / `LoadVideoUploadS3.load_video`。`s3_nodes.py`
- S3一覧はキャッシュされる。
  - `list_objects` が `_list_cache` / `_force_refresh` を使い、`invalidate_list_cache()` で更新トリガー。`s3_helpers.py`
- サーバ側には upload/preview のAPIがあるが delete は無い。
  - `/s3io/upload/*`, `/s3io/preview/*` が `s3_server.py` に定義されている。
- S3のキー安全化は `s3_server._safe_object_name` が担っている。
- 画像のサムネイルは `thumb_prefix` に `thumb_key_for()` で保存される。`s3_helpers.py`
- フロントは `web/js/s3_io_upload.js` がノード生成時にウィジェットへフックしている。
  - `upload` ボタンやS3プレビューの更新はここで行っている。

## 課題の整理
- S3入力ファイルを削除するためのAPIがない。
- UIに削除操作がなく、削除後の一覧/プレビュー更新の導線がない。
- キャッシュ（S3一覧、ローカルキャッシュ、サムネイル）の破棄が必要。

## 方針（案）
- サーバ側に「S3入力ファイル削除」APIを追加。
  - 入力名は `_safe_object_name` を通して `input_prefix` へ解決する。
  - 対象オブジェクトとサムネイル（画像のみ）の削除を試みる。
  - `invalidate_list_cache()` を呼んで一覧更新を可能にする。
  - 可能ならローカルキャッシュ（objects/thumbs）の該当ファイルも削除。
- フロント側で削除ボタンを追加し、選択中の値を削除する。
  - `s3_io_upload.js` にボタン追加、API呼び出し、comboの値削除・再描画を行う。
  - 誤操作防止のため `confirm()` などの軽い確認を入れる。
- 影響はLoad系ノードに限定し、Save/出力側には影響させない。

## 実装タスク
1) **S3削除ヘルパの追加**
   - `s3_helpers.py` に `delete_object` / `delete_input_object` などを追加。
   - サムネイルキー（`thumb_key_for`）の削除とローカルキャッシュ消去もここで扱う。
2) **削除APIの追加**
   - `s3_server.py` に `/s3io/delete/input` を追加。
   - `name` を受け取り `_safe_object_name` + `input_key_for/resolve_input_key` でS3キー化。
   - 成功/失敗はJSONで返し、失敗は 4xx/5xx を返す。
3) **UI拡張（削除ボタン）**
   - `web/js/s3_io_upload.js` に削除ボタンを追加。
   - 選択中の値をAPIへ送信し、成功時に combo から削除・選択解除・プレビュー消去。
4) **ドキュメント更新**
   - `README.md` に削除機能と注意点（不可逆、確認あり等）を追記。

## 影響範囲（候補）
- `s3_helpers.py`
- `s3_server.py`
- `web/js/s3_io_upload.js`
- `README.md`

## 検証観点
- 画像/動画それぞれで削除できる（S3から消える）。
- 削除後に一覧に残らない（Refreshでも再表示されない）。
- プレビューやローカルキャッシュが古い内容を指さない。
- 無効な名前や空選択でAPIが安全にエラーになる。
- 別インスタンスで削除済みのオブジェクトは読み込めない（S3が正）。

## 未決事項
- 削除操作のUXは「ボタン押下で即削除」（確認なし）。
- `VHS_LoadVideo*` など他ノードにも削除UIを広げるか。
