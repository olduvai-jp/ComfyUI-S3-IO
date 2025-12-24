# 計画用調査メモ（S3 IOノード）

## 目的
- `docs/plan/memo.md` に記載のとおり、ComfyUI の input/output フォルダ代わりに S3 を使うカスタムノード（Load/Save Image、Video Load/Combine）実装を目指す。

## 既存ノード仕様の抜粋（参考に流用する前提）
- LoadImage（`ComfyUI/nodes.py:1630` 付近）
  - `folder_paths.get_input_directory()` でローカル input を列挙、`image_upload` を許可。
  - PIL→numpy→torch で RGB 化し、アルファ/パレットは MASK として返却。フレーム数が揃わない場合はスキップ。
  - 返り値は `(IMAGE, MASK)`。`IS_CHANGED` はファイルの SHA-256、`VALIDATE` は `folder_paths.exists_annotated_filepath`。
- SaveImage（`ComfyUI/nodes.py:1561` 付近）
  - `folder_paths.get_output_directory()` を出力先に使用。`get_save_image_path` でプレフィックス＋連番を生成。
  - PNG にメタデータ（prompt/extra_pnginfo）を埋め込み、UI には `{"ui": {"images": [...]}}` を返す。

## VideoHelperSuite 関連
- Load Video (Upload)（`custom_nodes/ComfyUI-VideoHelperSuite/videohelpersuite/load_video_nodes.py`）
  - input はローカル input ディレクトリから `video_extensions = [webm, mp4, mkv, gif, mov]` を列挙。
  - Required: `video`, `force_rate`, `custom_width/height`, `frame_load_cap`, `skip_first_frames`, `select_every_nth`。Optional: `meta_batch`, `vae`, `format`（AnimateDiff/Mochi などのプリセット）、Hidden: `unique_id` 等。
  - `load_video` パイプラインではリサイズ/downscale、メモリ上限チェック、必要に応じ VAE エンコード（LATENT 出力）、`lazy_get_audio` で音声遅延読み込み。返却は `(IMAGE or LATENT, frame_count, AUDIO, video_info{fps/duration/size等})`。
  - `IS_CHANGED` はローカルファイルハッシュ、`VALIDATE` はローカルパスの存在確認。
- Video Combine（`custom_nodes/ComfyUI-VideoHelperSuite/videohelpersuite/nodes.py`）
  - Required: `images`, `frame_rate`(default 8), `loop_count`, `filename_prefix`, `format`(gif/webp + ffmpeg フォーマット), `pingpong`, `save_output`。
  - Optional: `audio`, `meta_batch`, `vae`。`save_output` False でプレビューのみ可。
  - 出力は `VHS_FILENAMES`（ファイル名/サブフォルダ情報）。ffmpeg/gifski を利用し進捗は `ProgressBar`。

## 依存・不足
- S3 クライアント系ライブラリ（例: boto3）は現状プロジェクト内で未検出（`rg -n "boto3" /mnt/ssd01/project/ComfyUI` ヒットなし）。

## 計画書で詰めるべき論点（要確認事項）
- S3 認証・バケット/パスの扱い: 環境変数/設定ファイル/UI指定のどれにするか。既定 input/output フォルダに対応する S3 プレフィックスの決定方法。
- 一覧取得と UI 連携: 既存 LoadImage/LoadVideo はローカル列挙＋`image_upload`。S3 一覧の取得頻度/キャッシュ/更新トリガーをどうするか。
- 保存ノードの命名規則とメタデータ: SaveImage 相当の連番付与と PNG メタデータ、UI への戻り値形式 (`ui.images`) を S3 版でどう保持するか。
- キャッシュ/IS_CHANGED: ローカルはファイルハッシュ。S3 版は ETag/HeadObject/mtime など何を用いるか。
- Video 系の I/O 方針: 音声付き書き出し、`meta_batch` 対応、S3 転送のための一時ファイル運用（ダウンロード→処理→アップロード vs ストリーミング）をどう設計するか。
- Video Combine の出力先: `save_output=False` など既存挙動を維持しつつ、S3 へ直接保存する場合のローカル出力抑制や UI 用レスポンスの作り方。
