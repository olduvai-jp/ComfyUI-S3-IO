# S3 output rename plan (Save Image / Video Combine)

## Goal
- Save Image to S3 / Video Combine to S3 で、S3 側に同名がある場合は上書きを避けてリネーム保存する。
- 本ドキュメントは実装計画書。

## Research summary (current behavior)
- Save Image to S3
  - `SaveImageS3.save_images` は `comfy_nodes.SaveImage.save_images` の結果を使い、`s3_helpers.upload_file` で S3 にアップロードするだけ。
  - S3 側の存在確認やリネームはしていないため、同名キーがあると上書きされる。
  - ローカルのファイル名は `folder_paths.get_save_image_path` が作る連番で、ローカル出力のみを見て決まる。
  - Ref: `s3_nodes.py`, `ComfyUI/nodes.py`。

- Video Combine to S3
  - `VideoCombineS3.combine_video` が `vhs_nodes.VideoCombine.combine_video` の出力ファイル群を受け取り、各ファイルを `s3_helpers.upload_file` でアップロードするだけ。
  - S3 側の存在確認やリネームはしていないため、同名キーがあると上書きされる。
  - 生成されるファイル名は `folder_paths.get_save_image_path` とローカル出力フォルダの既存ファイルを見て決まるため、S3 既存は考慮されない。
  - Ref: `s3_nodes.py`, `s3_vhs/nodes.py`。

- 参考: Upload API は S3 既存チェック付きのリネームがある
  - `/s3io/upload/image` と `/s3io/upload/video` は `overwrite` が無い場合に `(... (i))` サフィックスでリネームして衝突回避。
  - ローカルの存在と S3 の存在を両方チェック。
  - UI からは `overwrite` を送っていないため、デフォルトはリネーム動作。
  - Ref: `s3_server.py`, `web/js/s3_io_upload.js`。

- 既存 helper
  - `s3_helpers.object_exists(key)` があるが、出力用のリネーム helper はない。
  - Ref: `s3_helpers.py`。

## Design options
1) Always rename on S3 (default)
   - 衝突時は `filename (i).ext` で S3 キーを変える。
   - ローカルファイル名は変えず、S3 キーだけ変更。
   - UI への影響が最小だが、S3 とローカルのファイル名が一致しなくなる。

2) Optional overwrite/rename
   - Node 入力 or 環境変数で `overwrite` を選べるようにする。
   - 既存の挙動を維持したいユーザー向けに互換性を持たせる。

3) Rename local file too
   - S3 とローカル名を一致させるため、ローカルファイル名も変更し UI の `filename` を更新する。
   - 既存フローへの影響が大きいので慎重に検討が必要。

## Proposed approach (recommended)
- まずは Option 1 (S3 only rename) を実装。
- 追加要望があれば Option 2 の `overwrite` 追加を検討。

### Algorithm idea
- 新 helper: `resolve_unique_output_key(subfolder, filename)`
  - `output_key_for(subfolder, filename)` を作成。
  - `object_exists(key)` が True の間、`filename` に ` (i)` を付けて再試行。
  - 拡張子は `os.path.splitext` で保持。
  - 返すのは S3 キーと最終ファイル名(必要なら)。

- Save Image to S3
  - `SaveImageS3.save_images` で `entry` ごとにユニークキーを求め、`upload_file` に渡す。

- Video Combine to S3
  - `output_files` をループする直前に、各 `file_path` から `subfolder` + `filename` を取得しユニークキーを生成。
  - Video Combine の出力は `xxx_00001.png` と `xxx_00001.mp4` など同じベース名のセットがあるため、
    可能なら「同じベース名に同じサフィックス」を適用する。
    - 例: `xxx_00001` が衝突したら `xxx_00001 (1)` を png/mp4/audio で共有。
    - 実装案: 先にベース名単位で衝突判定して、生成した suffix をファイル群に適用。

## Implementation steps
1) `s3_helpers.py`
   - 出力用のユニークキー生成 helper を追加。
   - 既存の `/s3io/upload/*` のロジックと近いサフィックス規則に揃える。

2) `s3_nodes.py`
   - `SaveImageS3.save_images` にユニークキー生成を追加。
   - `VideoCombineS3.combine_video` にユニークキー生成を追加。
   - Video Combine は「ベース名でまとめて suffix を揃える」方式が必要なら、
     `output_files` をグルーピングする処理を追加。

3) (Optional) Configuration
   - `overwrite` を node input で追加するか、環境変数 `S3IO_OUTPUT_OVERWRITE` を追加。

## Open questions
- S3 側のリネームは「常時オン」で良いか、それとも `overwrite` を UI で選べる方が良いか。
- Video Combine の複数出力ファイルは同一サフィックスで揃えるか、個別で良いか。
- S3 キーとローカルファイル名が一致しないことを許容するか。

