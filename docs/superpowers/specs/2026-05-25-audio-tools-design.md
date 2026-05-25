# audio-tools 設計仕様書

**Date**: 2026-05-25
**Status**: Draft (ブレスト完了、ユーザーレビュー待ち)

## 1. 目的

Linux 上で動作するデスクトップ音楽管理アプリ。次の 2 つのコアワークフローに特化する:

1. **ムード・テンポ分析とプレイリスト自動生成** — ローカルライブラリを分析し、k-means クラスタリングで自動的にグループ化、各クラスタを m3u プレイリストとして書き出す
2. **メディアプレーヤーへのサイズ最適化転送** — デバイスプロファイルに従って自動でビットレートを調整しながら、上限容量に収まるようにトランスコード+転送する

両機能は同一ウィンドウ内で完結する。

## 2. スコープ

### 含む(初版)
- ローカルディレクトリの再帰スキャン(増分対応: mtime + sha1)
- Essentia によるローカル特徴量抽出(BPM, key, mood, danceability, MusiCNN embedding)
- scikit-learn による k-means クラスタリングと増分割り当て
- クラスタへのユーザーラベル付け、手動曲移動
- m3u プレイリスト書き出し
- FFmpeg によるトランスコード(コーデック: opus / mp3 / aac、`copy` 可)
- 埋め込みアルバムアートの保持(再エンコードせず透過コピー)
- USB ストレージマウントへの転送
- Android MTP デバイスへの転送(gvfs 経由)
- デバイスプロファイル(YAML)による設定
- バランス型サイズ最適化(段階的ビットレート低下 + 末尾ドロップ)
- SQLite による分析結果・転送履歴の永続化

### 含まない(YAGNI、将来検討)
- ❌ オンラインメタデータ取得(MusicBrainz, Last.fm)
- ❌ 別ファイルのアルバムアート(cover.jpg)転送
- ❌ MusicBrainz からのアルバムアート取得・埋め込み
- ❌ 曲再生機能(将来プレビュー再生として検討)
- ❌ ストリーミングサービス連携
- ❌ レコメンド機能
- ❌ クラウド同期 / マルチデバイス同期
- ❌ 歌詞表示
- ❌ DSP プラグイン
- ❌ ルールベースのプレイリスト定義(クラスタリングに一本化)
- ❌ DLNA / SSH / Syncthing 等のネットワーク転送

## 3. 技術スタック

| レイヤー | 選定 | 理由 |
|---|---|---|
| 言語 | Python 3.11+ | Essentia/scikit-learn の Python バインディングが一級市民 |
| GUI | PySide6 (Qt6, LGPL) | `QAbstractItemModel` で 1 万曲規模の仮想スクロールが軽い、波形描画も強い |
| 分析 | `essentia-tensorflow` | BPM/key/mood の事前学習モデルが公式提供 |
| クラスタリング | `scikit-learn` | k-means、エルボー法 |
| タグ I/O | `mutagen` | 全主要フォーマット対応、純Python |
| トランスコード | `ffmpeg`(subprocess) | コーデック網羅性、画像ストリーム保持 |
| DB | SQLite + SQLAlchemy + Alembic | 単一ファイル、WAL、ロックレス読み |
| MTP | `gvfs-mtp`(マウント済みとして扱う) | システム標準、特別な Python ライブラリ不要 |
| パッケージ | `pyproject.toml` + `pip` | Flatpak 化は将来 |

## 4. アーキテクチャ

3 層構造:

```
┌──────────────────────────────────────────────────────┐
│ ① プレゼンテーション層 (PySide6)                      │
│   LibraryView / ClusterEditor / TransferDialog /     │
│   SettingsPane                                       │
├──────────────────────────────────────────────────────┤
│ ② コア層 (純Python、UI非依存)                         │
│   Scanner / Analyzer / Clusterer / PlaylistBuilder / │
│   TransferPlanner / Transcoder / DeviceProfile       │
├──────────────────────────────────────────────────────┤
│ ③ I/O・外部依存層                                     │
│   SQLite / FFmpeg / Essentia+TF / gvfs / mutagen     │
└──────────────────────────────────────────────────────┘
```

**原則**:
- コア層は GUI を一切インポートしない。CLI からも叩ける形で書く
- 重い処理(分析・トランスコード・転送)は `QThreadPool` でバックグラウンド実行
- ワーカー → UI は Qt シグナルで進捗・エラーを通知(直接 UI を触らない)
- メインウィンドウはサイドバーナビ(ライブラリ / クラスタ / 転送 / デバイス / 設定)+ 右側ペイン

## 5. データモデル

SQLAlchemy ORM、SQLite WAL モード。

```
tracks
  id              INTEGER PK
  path            TEXT UNIQUE
  mtime           REAL
  size            INTEGER
  sha1            TEXT INDEX           -- ファイル移動検知用
  title, artist, album, duration_s, codec, bitrate
  last_analysis_error  TEXT NULL       -- 分析失敗時のエラー文字列

features
  track_id        INTEGER PK/FK → tracks.id
  bpm, key, scale, energy, danceability,
  mood_happy, mood_sad, mood_aggressive, mood_relaxed,
  loudness, spectral_centroid
  embedding       BLOB                  -- numpy float32 配列(200次元)

clusters
  id              INTEGER PK
  name            TEXT                  -- ユーザー命名("Workout" 等)
  color           TEXT                  -- UI 表示色
  k_value         INTEGER               -- 生成時の k
  centroid        BLOB                  -- 重心(増分割り当てに使う)
  created_at      DATETIME

cluster_assignments
  track_id        INTEGER PK/FK
  cluster_id      INTEGER FK
  distance        REAL                  -- 重心からの距離

device_profiles
  id              INTEGER PK
  name            TEXT UNIQUE
  mount_hint      TEXT                  -- 例: /run/media/$USER/WALKMAN
  codec           TEXT                  -- opus|mp3|aac|copy
  container       TEXT                  -- ogg|mp3|m4a
  max_bitrate     INTEGER               -- kbps
  min_bitrate     INTEGER
  bitrate_step    INTEGER
  max_size_bytes  INTEGER
  sample_rate_max INTEGER
  m3u_path_style  TEXT                  -- relative|windows_backslash|absolute
  folder_layout   TEXT                  -- 例: "{artist}/{album}/{track:02d} - {title}"

transfer_sessions
  id              INTEGER PK
  profile_id      INTEGER FK
  started_at, finished_at  DATETIME
  status          TEXT                  -- running|completed|aborted|failed
  bytes_transferred  INTEGER
```

**インデックス**: `tracks.path` (UNIQUE)、`tracks.sha1`、`cluster_assignments.cluster_id`。

## 6. 分析パイプライン

```
[ユーザー: スキャン開始]
   ↓
Scanner: ディレクトリ走査
   - mtime 変更 or 新規パス → 候補リスト
   - sha1 一致する既存 track があれば path だけ更新(ファイル移動検知)
   ↓
[QThreadPool: N=CPU 並列]
   ↓
Analyzer: 1曲ずつ Essentia 実行
   - MusicExtractor → BPM, key, loudness, danceability, spectral_*
   - TF モデル → mood_*, MusiCNN embedding (200次元)
   - タイムアウト 5 分、超過は skip(last_analysis_error 記録)
   - 例外も同様(壊れたファイル等)
   ↓
features に UPSERT(track_id PK で冪等)
   ↓
進捗シグナル → UI のステータスバー
```

**増分**: スキャン済みファイル数を `tracks` テーブルが保持しているので、再スキャン時は変更分のみ処理される。

## 7. クラスタリングとプレイリスト生成

**初回クラスタリング**:
- 全 `features.embedding` を読み込み、scikit-learn `KMeans(n_clusters=k, random_state=固定)` 実行
- k のデフォルトは 6。UI でエルボー法のグラフを見て調整可能
- 各クラスタの重心を `clusters.centroid` に保存
- `cluster_assignments` を全更新

**増分割り当て**(新曲が一定数 — デフォルト 50 曲 — 追加されたとき自動、または明示ボタン):
- 既存 `clusters.centroid` を使い、新曲のみ最近傍クラスタへ割り当て
- 既存曲のアサインは触らない → ユーザーが見慣れたプレイリストが勝手に変わらない

**全体再クラスタ**(明示ボタンのみ):
- 全 embedding で重心を作り直す
- 旧クラスタ → 新クラスタの対応は重心類似度で提案(「Workout に最も近いのは新クラスタ3」)
- 最終確定はユーザー(ラベル引き継ぎ確認ダイアログ)

**プレイリスト書き出し**:
- 各クラスタごとに `~/.local/share/audio-tools/playlists/<name>.m3u` を生成
- 拡張 m3u(EXTM3U, 各曲に EXTINF)
- パスは絶対パス(ローカル参照用)
- 転送時はデバイスプロファイルの `m3u_path_style` に従って書き換え

## 8. デバイスプロファイルと転送ロジック

**プロファイル例**(`~/.config/audio-tools/devices/<name>.yaml`):

```yaml
name: "Walkman (USB 16GB)"
mount_hint: "/run/media/$USER/WALKMAN"
codec: opus
container: ogg
max_bitrate: 128
min_bitrate: 64
bitrate_step: 32
max_size_bytes: 14000000000   # 14 GB(安全マージン込み)
sample_rate_max: 48000
m3u_path_style: relative
folder_layout: "{artist}/{album}/{track:02d} - {title}"
```

**TransferPlanner アルゴリズム**:

```
入力: 選択プレイリスト集合, デバイスプロファイル
1. 全曲について predict_size(bitrate) を計算
     - codec=copy なら元サイズ
     - トランスコードなら duration_s * bitrate / 8 * 1.05(5%安全マージン)
2. for bitrate in [max..min] step -bitrate_step:
       total = sum(predict_size(b))
       if total <= max_size_bytes: break
   else:
       # 下限まで下げてもダメ → 末尾ドロップ
       while total > max_size_bytes:
           drop = tracks.pop_last()
           dropped.append(drop)
           total -= predict_size(min_bitrate, drop)
3. 結果を {bitrate, kept_tracks, dropped_tracks} で返す
4. UI でプレビュー("96kbps、12曲ドロップ"、ドロップ曲一覧を表示)
5. ユーザー承認 → 実行フェーズへ
```

**末尾の定義**:
- 単一プレイリスト選択時: プレイリスト内の並び順末尾(順序はユーザー設定: 距離順 / アーティスト順 / ランダム / 手動)
- 複数プレイリスト選択時: 各プレイリストを丸ごと優先度順(UI でドラッグ並び替え)、低優先度のプレイリストから末尾を順次ドロップ。同一プレイリスト内も末尾から。

**実行フェーズ**:
- Transcoder: FFmpeg を `QThreadPool` で並列(N=CPU)
- 出力は OS のテンポラリ → 完了曲から順次デバイスへコピー
- コピー前にデバイス側で同一パス+同一ハッシュなら skip(rsync 風)
- m3u は全曲コピー完了後に一括書き出し
- 失敗曲は m3u に含めない
- セッション情報を `transfer_sessions` に記録

**埋め込みアルバムアートの保持**:
- 入力に画像ストリームがあれば `-map 0:a -map 0:v? -c:v copy` で透過コピー
- MP3 出力: `-id3v2_version 3 -write_id3v1 0` で APIC を書く
- M4A 出力: ネイティブ対応、追加指定不要
- Opus(ogg)出力: FFmpeg の Ogg muxer による画像保持は historically 不安定なため、**mutagen による事後埋め込み**を採用する。トランスコード時は `-vn` で画像を捨て、完了後に元ファイルから画像を抽出して mutagen で `METADATA_BLOCK_PICTURE` を書き込む。PNG/JPEG 以外は JPEG へ再エンコードしてから埋め込む。
- 画像なし曲は処理スキップ

## 9. GUI

メインウィンドウはサイドバーナビ + 右ペイン構成。

- **ライブラリ**: 曲一覧テーブル(タイトル / BPM / キー / ムードタグ / クラスタ / 分析状態)、上部にスキャン・分析・再クラスタボタン、検索欄
- **クラスタ**: 各クラスタのカード表示(代表曲 + ラベル編集 + 色)、クリックでメンバー曲一覧、ドラッグで他クラスタへ移動
- **転送**: デバイス選択 → プレイリスト選択 → サイズプレビュー(円グラフ + ドロップ曲リスト) → 実行 → 進捗
- **デバイス**: プロファイル一覧、新規追加・編集(フォーム + 直接 YAML 編集ボタン)
- **設定**: ライブラリパス、Essentia モデルパス、FFmpeg バイナリパス、並列度
- **ステータスバー**(常設): 「8,432 曲 / 7,901 分析済 / 5 クラスタ」+ バックグラウンドジョブ進捗

右クリックメニュー: 「いま転送」(現在曲を選択中のデバイスへ即転送)、「クラスタ移動」、「分析再実行」、「ファイラで開く」。

## 10. エラー処理

| 場面 | 検出 | 対処 |
|---|---|---|
| Essentia 例外(壊れた MP3 等) | try/except | `tracks.last_analysis_error` に記録、UI でフィルタ可能 |
| TF モデル未配置 | 起動時の存在チェック | ダイアログでダウンロード案内 |
| 巨大ファイル | 分析タイムアウト 5 分 | skip、エラー文字列に "timeout" |
| デバイス未マウント | プロファイル `mount_hint` のチェック | 警告 + 手動指定ダイアログ |
| 容量不足(ENOSPC) | コピー時 IOError | その曲を skip、残りを再評価して継続 |
| FFmpeg 非ゼロ終了 | returncode チェック | stderr 保存、当該曲のみ skip、全体は継続 |
| デバイス突然抜け | I/O エラー連発(閾値) | セッションを `aborted` で確定、書きかけ削除 |
| DB スキーマ不一致 | 起動時 | Alembic で自動マイグレーション |

**UI 側の方針**: ワーカーは `error(track_id, message)` シグナルだけ発火、メインスレッドが集約してエラータブに表示。**モーダルダイアログを連発しない**。

## 11. テスト戦略

| 種別 | ツール | 対象 |
|---|---|---|
| ユニット | `pytest` | `core/` 配下全モジュール(GUI 非依存) |
| ゴールデン | `pytest` + fixture WAV | `Analyzer` の出力(BPM ±2 などの許容範囲) |
| プロパティ | `hypothesis` | `TransferPlanner`(任意の曲集合・上限値で破綻しない) |
| 統合 | `pytest` + `ffmpeg` 実バイナリ | `Transcoder`(コーデック別)、埋め込みアート保持 |
| GUI スモーク | `pytest-qt` | 主要ウィンドウが起動・閉じ可能 |

**CI**: GitHub Actions、`ffmpeg` を apt インストール、Essentia は Python wheel から、TF モデルは fixture として小型版を同梱。

**埋め込みアートのゴールデンテスト**: 各コーデック(mp3/m4a/opus)に対し「入力に画像 → トランスコード後 mutagen で取り出せる」ことを 1 ケースずつ確認。

## 12. ディレクトリ構成(予定)

```
audio-tools/
├── pyproject.toml
├── src/audio_tools/
│   ├── core/
│   │   ├── scanner.py
│   │   ├── analyzer.py
│   │   ├── clusterer.py
│   │   ├── playlist_builder.py
│   │   ├── transfer_planner.py
│   │   ├── transcoder.py
│   │   ├── device_profile.py
│   │   └── db.py
│   ├── gui/
│   │   ├── main_window.py
│   │   ├── library_view.py
│   │   ├── cluster_editor.py
│   │   ├── transfer_dialog.py
│   │   └── settings_pane.py
│   ├── cli.py
│   └── __main__.py
├── tests/
│   ├── unit/
│   ├── golden/
│   │   └── fixtures/  *.wav, *.mp3, *.flac
│   └── integration/
├── docs/
│   └── superpowers/specs/
└── alembic/  (DB マイグレーション)
```

## 13. 設定・データの配置

XDG Base Directory に準拠:
- 設定: `~/.config/audio-tools/`
  - `config.yaml`(ライブラリパス、モデルパス等)
  - `devices/*.yaml`(デバイスプロファイル)
- データ: `~/.local/share/audio-tools/`
  - `audio_tools.db`(SQLite)
  - `playlists/*.m3u`(生成プレイリスト)
- キャッシュ: `~/.cache/audio-tools/`
  - トランスコード一時ファイル
