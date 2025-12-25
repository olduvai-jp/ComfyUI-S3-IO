# ComfyUI Downloader Helper 連携計画（SaveImageS3 / VideoCombineS3）

目的: S3 へのアップロードは継続しつつ、**ダウンロードはローカル出力を直接取得**して高速化する。

## 背景調査（現状把握）
### 保存ノードの挙動（S3 IO 側）
- `SaveImageS3` はローカルに保存後、S3 へアップロードする。`ui.images` にはローカルの `filename/subfolder/type` が返る。(`s3_nodes.py`)
- `VideoCombineS3` はローカルに出力したファイル群を S3 へアップロードする。`ui.gifs` にローカルの `filename/subfolder/type` が返る。(`s3_nodes.py`, `s3_vhs/nodes.py`)

### UI への出力経路（ComfyUI 側）
- WebSocket `executed` は `ui` 出力のみを送る。(`execution.py`)
- フロントエンドは `node.onExecuted(detail.output)` を呼ぶ。(`ComfyUI_frontend/src/scripts/app.ts`)
- `SaveImageS3` の `ui` は `images: [{ filename, subfolder, type }]` 形式。
- `VideoCombineS3` の `ui` は `gifs: [{ filename, subfolder, type, format, fullpath, ... }]` 形式。(`s3_vhs/nodes.py`)

### ローカル出力の取得方法（ComfyUI）
- `/view?filename=...&subfolder=...&type=output|temp` でローカルファイルを配信できる。(`server.py`)
- `type` に応じて `output` / `temp` のディレクトリが使用される。

### Chrome 拡張の制約（ユーザー提示仕様）
- `window.comfyuiDL.requestDownload({ url, relativePath, size })` を呼ぶと自動保存。
- `relativePath` は `..` や先頭 `/` 不可。`subfolder/filename` 形式は許可。
- 拡張側の許可オリジンに ComfyUI の URL を追加する必要がある。

## 課題
- `executed` の `output` から **ローカル URL を生成する**必要がある。
- `VideoCombineS3` の `type` が `temp` の場合にダウンロードするかどうかを決める必要がある。

## 方針（設計案）
### データフロー（推奨）
1) `SaveImageS3` / `VideoCombineS3` の `output` から `filename/subfolder/type` を取得。
2) `/view` URL を組み立てて **ローカルから直接ダウンロード**。
3) `window.comfyuiDL.requestDownload(...)` を呼び出す。

### URL 生成ルール
```
url = `${origin}/view?filename=${encode(filename)}&subfolder=${encode(subfolder)}&type=${type}`
relativePath = subfolder ? `${subfolder}/${filename}` : filename
```
- `type` は `output` または `temp`。
- `relativePath` は拡張の制約に合わせて `/` 始まりや `..` を禁止。

## 具体的な対応案
### Python 側（S3 IO）
- `VideoCombineS3` の `ui` に `downloads` を追加し、`output_files` から実在ファイルだけを列挙する。
  - `output_files[0]` のメタ PNG は除外する。
  - `temp` 出力も含める（`type` を `temp` で付与）。
  - audio 付きで 2 ファイル出る場合は両方を含める。

### JS 側（ComfyUI UI）
1) `web/js/s3_io_download.js` を追加（`WEB_DIRECTORY` 配下）
   - `app.registerExtension` で `SaveImageS3` / `VideoCombineS3` の `onExecuted` をフック。
   - `output.downloads` / `output.images` / `output.gifs` を走査し、`/view` URL を生成。
   - `window.comfyuiDL?.requestDownload()` を呼ぶ。
   - `temp` 出力も対象に含める。
2) 失敗時の UI
   - `app.extensionManager?.toast?.add` で簡易通知（既存の upload UI と同様）。

### Python 側（S3 IO）
- 変更不要（`ui` が既に必要情報を持つため）。

## 実装ステップ（案）
1) `VideoCombineS3` に `downloads` を追加してローカル出力一覧を UI に返す。
2) JS 拡張ファイル `web/js/s3_io_download.js` を追加。
3) `SaveImageS3` / `VideoCombineS3` の `onExecuted` をフックして `/view` URL 生成。
4) README/運用メモを追記（拡張の許可オリジン設定、保存先フォルダなど）。
5) 手動テスト（下記）。

## 手動テスト案
1) Chrome 拡張で ComfyUI の origin を許可に追加。
2) `SaveImageS3` で画像保存 → `comfyui-downloads/` に同名ファイルが保存されること。
3) `VideoCombineS3` で動画保存 → `comfyui-downloads/` に動画ファイルが保存されること。
4) `save_output=False` の場合は `temp` 出力も含めてダウンロードされること。

## 未確定事項（要確認）
- `temp` 出力もダウンロード対象にする（決定）。
- `VideoCombineS3` で audio 出力がある場合、**出力が2つ作られるなら両方落とす**（決定）。
- 拡張側で `size` パラメータを使う必要があるか（現状は未使用で可）。
