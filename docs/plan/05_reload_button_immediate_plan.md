# Reload入力廃止 + ComfyUI Refresh運用 - 調査と計画

## ゴール
- `reload` 入力を廃止し、ComfyUIのRefresh操作だけで一覧更新が完結する。
- S3一覧キャッシュを無効化し、Refresh時に常に最新のS3一覧を取得する。

## 調査メモ（事実ベース）
- `reload` はノード実行時のみ参照される。
  - `LoadImageS3.load_image` / `LoadVideoUploadS3.load_video` で `reload` が `True` のとき `s3_helpers.invalidate_list_cache()` を呼ぶ。`custom_nodes/ComfyUI-S3-IO/s3_nodes.py`
- 一覧は `INPUT_TYPES` でS3の一覧を作るが、ここでは `reload` 入力は使われない。
  - `LoadImageS3.INPUT_TYPES` / `LoadVideoUploadS3.INPUT_TYPES` は `list_media_keys` を呼んで候補を作成。`custom_nodes/ComfyUI-S3-IO/s3_nodes.py`
- S3一覧は 30 分キャッシュされる。
  - `list_objects` が `_list_cache` と `_force_refresh` を使う。`invalidate_list_cache()` が `_force_refresh` を立てる。`custom_nodes/ComfyUI-S3-IO/s3_helpers.py`
- UI側で「ノード定義の再取得」は可能。
  - `app.refreshComboInNodes()` が `/object_info` を叩き、各ノードのcombo候補を更新。`ComfyUI_frontend/src/scripts/app.ts`
  - UIのRefreshボタンやコマンド `Comfy.RefreshNodeDefinitions` も同じ関数を呼ぶ。`ComfyUI_frontend/src/scripts/ui.ts`, `ComfyUI_frontend/src/composables/useCoreCommands.ts`
- UI拡張は `web/js` で `app.registerExtension` を使ってフック可能。
  - 既に `s3_io_upload.js` が `onNodeCreated` でウィジェットにフックしている。`custom_nodes/ComfyUI-S3-IO/web/js/s3_io_upload.js`
- フロントエンドには「remote combo」機構があり、refreshボタン付きでHTTP取得も可能。
  - combo inputに `remote` を付けると `useRemoteWidget` が更新を扱う。`ComfyUI_frontend/src/renderer/extensions/vueNodes/widgets/composables/useComboWidget.ts`, `ComfyUI_frontend/src/renderer/extensions/vueNodes/widgets/composables/useRemoteWidget.ts`

## 問題の整理
- `reload` は「一覧のキャッシュ無効化」を **ノード実行時** にしか起動しない。
- UI側の `reload` トグルは値が変わるだけで、一覧更新の再取得を発火しない。
- ComfyUIのRefreshは `/object_info` を再取得するが、S3側キャッシュが残っていると一覧が古いままになる。

## 方針（決定）
- `reload` 入力を削除する。
- S3一覧キャッシュを無効化し、`/object_info` 取得時に常にS3を参照する。
- ユーザー操作は「ComfyUIのRefresh」だけに統一する。

## 実装タスク
1) **S3一覧キャッシュの無効化**
   - `list_objects` が常にS3を読みに行くようにする（TTLを0にする or 常時refreshを使う）。
   - 実装: `custom_nodes/ComfyUI-S3-IO/s3_helpers.py`
2) **`reload` 入力の削除**
   - `LoadImageS3` / `LoadVideoUploadS3` の `INPUT_TYPES` から `reload` を削除。
   - `load_image` / `load_video` の引数・ロジックから `reload` を削除（`download_to_cache(refresh=...)` も整理）。
   - 実装: `custom_nodes/ComfyUI-S3-IO/s3_nodes.py`
3) **README更新**
   - `reload` の説明を削除し、ComfyUIのRefreshで一覧更新する方針を明記。
   - 実装: `custom_nodes/ComfyUI-S3-IO/README.md`

## 影響範囲（候補）
- `custom_nodes/ComfyUI-S3-IO/s3_nodes.py`
- `custom_nodes/ComfyUI-S3-IO/s3_helpers.py`
- `custom_nodes/ComfyUI-S3-IO/README.md`

## 検証観点
- ComfyUIのRefreshで一覧が更新される（S3側の最新が反映される）。
- Runせずに一覧が更新されること（UIのcombo値が変わる）。
- 既存のロード/ダウンロード/アップロードが壊れていない。
