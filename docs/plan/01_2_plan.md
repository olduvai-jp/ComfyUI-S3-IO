# ComfyUI S3 IO ノード 実装計画

目的: `docs/plan/memo.md` に挙がっている S3 版ノード（Load/Save Image、Load Video Upload、Video Combine）を追加し、従来の入出力動作を維持しつつ S3 と同期させる。

## 前提・ポリシー（ユーザー指定）
- 認証/バケット/パス: 環境変数で渡す。
- 一覧取得: 基本 30 分に 1 回自動更新。UI にリロードボタンを付けて手動更新可。
- ロード選択: 一度選択したオブジェクトはプレビュー用にダウンロードして取り込む。
- 保存: 既存のローカル output への書き出しを行った後、S3 にアップロードする（両方残す）。
- 動画 I/O: S3 からダウンロード → ローカル処理 → S3 へアップロードのバッチ型。
- Video Combine: 既存の出力動作 + S3 アップロード。
- 依存追加: `requirements.txt` に追加（boto3 想定）。
- 他 custom_nodes の import 禁止: 必要なコードはコピーするかサブモジュールとして同梱。
- Upload File での初回アップロード時に小さいサムネイルも S3 に保存し、プレビューはサムネイルを使用。

## 設計概要
### S3 設定
- 環境変数例: `S3IO_ENDPOINT_URL`, `S3IO_REGION`, `S3IO_ACCESS_KEY_ID`, `S3IO_SECRET_ACCESS_KEY`, `S3IO_BUCKET`, `S3IO_INPUT_PREFIX`, `S3IO_OUTPUT_PREFIX`。
- 認証と設定は共通ヘルパーにまとめ、boto3 想定。存在チェックで不足時はノードエラーを返す。

### 一覧取得・キャッシュ
- S3 input プレフィックスを `list_objects_v2` で取得し、30 分 TTL のキャッシュを保持。
- UI: リロードボタンでキャッシュ無視フラグをセットし再取得。
- プレビュー用: 選択されたキーは即ダウンロード（キャッシュ TTL とは別に個別保存）。

### サムネイル
- Upload File で S3 へ PUT する際に、縮小版（例: 最大 256px 程度）も生成して同時アップロード。
- サムネイルは固定のサフィックス or プレフィックス（例: `thumbs/<key>.jpg`）で保存し、プレビューではそちらを優先。
- サムネイルが存在しない場合のみ元画像をプレビューに使用。

### Load Image from S3
- 既存 LoadImage 相当の UI（選択・アップロード許可）を維持しつつ、選択肢は S3 リストから生成。
- 選択時にダウンロードし、元の `LoadImage.load_image` ロジックに渡して (IMAGE, MASK) を返却。
- IS_CHANGED: S3 ETag + Key（必要なら LastModified）を組み合わせたハッシュ。
- VALIDATE: `head_object` 成功で True。

### Save Image to S3
- SaveImage 相当を継承/ラップし、ローカル output へ保存後に対象ファイルを S3 output プレフィックスへアップロード。
- メタデータは既存通り PNG に埋め込む（アップロードはローカルファイルをそのまま PUT）。
- UI 返却 `{"ui": {"images": [...]}}` はローカル保存分を使用し、S3 へのアップロード結果はログ/追加フィールドで通知（検討: `s3_url` をオプションで付与）。

### Load Video (Upload) from S3
- VideoHelperSuite の LoadVideoUpload と同等の入力項目を維持。
- S3 一覧を表示 → 選択後にダウンロードして既存 `load_video` パイプラインに渡す。
- IS_CHANGED/VALIDATE は画像版と同様に ETag/HeadObject で行う。
- 中間ファイルの一時ディレクトリは ComfyUI の temp もしくは専用サブフォルダを使用し、処理後クリーンアップ。

### Video Combine to S3
- 既存 Video Combine の挙動（gif/webp/ffmpeg 書き出し、`save_output` フラグ）を維持。
- ローカル出力が生成された場合のみ、同名ファイルを S3 output プレフィックスに PUT。
- `save_output=False` の場合は S3 アップロードをスキップ（ローカルファイルも無いので一致）。

## 実装タスク
1) S3 クライアントヘルパー作成
   - boto3 初期化、環境変数ロード、ヘルスチェック（list/head/put の薄いラッパー）、キャッシュ TTL 実装。
2) UI 連携・リスト更新
   - ノード入力に「リロード」トグルを追加し、TTL 無視を可能にする。
   - S3 一覧から選択リストを生成（画像/動画で拡張子フィルタ）。
3) サムネイル生成・プレビュー対応
   - Upload File のアップロード時にサムネイルを生成して S3 へ PUT。
   - プレビューはサムネイルのキーを優先し、存在しない場合のみ元画像を使用。
4) Load Image from S3 ノード
   - 選択/アップロードを許可し、選択時ダウンロード→既存 LoadImage ロジック再利用。
   - IS_CHANGED/VALIDATE を S3 向けに実装。
5) Save Image to S3 ノード
   - 既存 SaveImage を呼び出してローカル保存 → S3 アップロード。
   - 失敗時のリトライ/ログ方針を決める（少なくとも 3 回程度のリトライ）。
6) Load Video (Upload) from S3 ノード
   - VideoHelperSuite の LoadVideoUpload をラップ/派生して、入力ディレクトリ列挙部分を S3 化。
   - ダウンロード→`load_video` 呼び出し→一時ファイルクリーンアップ。
7) Video Combine to S3 ノード
   - 既存 Combine 実行後の出力ファイルを S3 に PUT（save_output True の時のみ）。
   - UI 返却は既存を使用し、S3 アップロード情報をログ/付加情報で提示。
8) エラーハンドリング/テスト
   - 環境変数不足、バケット/権限エラー時のメッセージ。
   - キャッシュ切り替え・リロードボタンの確認。
   - 画像/動画の基本フロー手動テスト。

## 残課題・確認
- boto3 を `requirements.txt` に追加。
- temp ディレクトリの扱い: サイズ上限・掃除タイミングの方針（動画ダウンロード後の削除）。
- S3 パス命名: `input/`/`output/` のサフィックスや日付サブフォルダをどうするか（環境変数でプレフィックス指定とする想定）。
