# AbletonGPT

Ableton Live で作曲・編曲・MIDI生成・音源選択・LUFS解析・AIボーカル導入までを一貫して扱う Python ベースのプロジェクトです。
本プロジェクトは、自然言語の依頼を SongSpec や構成案へ変換し、CLI と UI から Ableton Live と連携できるように設計されています。

## 概要

AbletonGPT は、以下のようなワークフローを支援します。

- 自然言語からの曲の方向性生成
- 進行・コード・テンポ・キー・ムードの構成案生成
- MIDI トラック / クリップ / インストゥルメントの自動作成
- Live でのトラック・デバイス・パラメータ操作
- MIDI の表現付け（swing / humanize / accent）
- LUFS / LRA / peak / RMS のオフライン分析
- 書き出しの受け渡しと検証（`plan_audio_export` / `wait_for_audio_export` / `verify_audio_export`）。
  境界と手順は [書き出しワークフロー](docs/EXPORT_WORKFLOW_JA.md) にまとめています
- AI ボーカルのガイド作成と取り込み
- local UI での手軽な操作

特徴:
- ローカル実行前提
- CLI と Web UI を両対応
- Ableton Live 連携を含む
- 生成ロジックと Live 操作が分離されている
- 実際に CLI / UI / Live flow の検証済み

---

## 現在の確認済み状態

このリポジトリは、現在の実装で次の確認を完了しています。

- CLI エントリポイントが正常に動作
- `compose`, `intent`, `ui`, `live-flow` を含む主要サブコマンドが利用可能
- 実際の pytest により対象回帰テストが通過
- 実CLIから SongSpec 生成が成功
- Arrange / Jobs の `place_scene` 実行パスが Live 連携向けに修正済み

最新の検証結果:

```bash
cd /Users/user/MusicAI/abletongpt
PYTHONPATH=src .venv/bin/pytest tests/test_job_runner.py tests/test_ableton_step_executor.py -q
```

結果:

```text
36 passed in 0.36s
```

実際の CLI も確認済みです:

```bash
cd /Users/user/MusicAI/abletongpt
PYTHONPATH=src .venv/bin/python -m abletongpt.cli.main --help
PYTHONPATH=src .venv/bin/python -m abletongpt.cli.main intent --json "110 BPM, D# minor, Mutation Funk, Dub, Tech House, 5 minutes"
```

---

## 必要環境

- Python 3.11 以上
- Ableton Live 11 以上
- macOS を想定したセットアップ
- `pip` または `venv` を利用可能

---

## セットアップ

### 1. 仮想環境を作成

```bash
cd /Users/user/MusicAI/abletongpt
python3 -m venv .venv
source .venv/bin/activate
```

### 2. 依存関係をインストール

```bash
pip install -U pip
pip install -e '.[dev]'
```

### 3. CLI の動作確認

```bash
PYTHONPATH=src .venv/bin/python -m abletongpt.cli.main --help
```

---

## 実行例

### Intent: 自然言語を SongSpec に変換

```bash
cd /Users/user/MusicAI/abletongpt
PYTHONPATH=src .venv/bin/python -m abletongpt.cli.main intent --json "110 BPM, D# minor, Mutation Funk, Dub, Tech House, 5 minutes"
```

例:

```json
{
  "genre": "tech_house",
  "key": "D#",
  "mode": "minor",
  "tempo": 110.0,
  "bars": 64,
  "duration_seconds": 300.0
}
```

### Compose: 曲案を作成

```bash
cd /Users/user/MusicAI/abletongpt
PYTHONPATH=src .venv/bin/python -m abletongpt.cli.main compose --genre tech_house --mood dark --bars 64
```

### UI を起動

```bash
cd /Users/user/MusicAI/abletongpt
PYTHONPATH=src .venv/bin/python -m abletongpt.cli.main ui --host 127.0.0.1 --port 8787
```

### Live flow を実行

```bash
cd /Users/user/MusicAI/abletongpt
PYTHONPATH=src .venv/bin/python -m abletongpt.cli.main live-flow --genre tech_house --mood dark --roles bass,chords,melody,drums
```

---

## Ableton Live 連携

### Remote Script の配置

macOS では、Live の Remote Script を次の場所に配置します。

```text
~/Music/Ableton/User Library/Remote Scripts/AbletonGPT_MCP/__init__.py
```

リポジトリ内の `ableton_remote_script/AbletonGPT/__init__.py` をコピーしてください。

その後、Live を再起動して、以下から Control Surface を選択します。

- `Settings > Link, Tempo & MIDI > Control Surface`

選択対象:

```text
AbletonGPT_MCP
```

---

## 主要機能

### 1. SongSpec / AI 構成生成
- 自然言語の依頼を構成候補へ変換
- キー、ムード、BPM、バー数、ジャンルを整理
- CLI と UI の両方で利用可能

### 2. Compose engine
- 曲の雰囲気に応じた構成案を生成
- ジャンルごとのプロファイルとエイリアスを扱う
- Key / Mode / Arrangement / パート構成を出力

### 3. Live flow
- トラック生成
- インストゥルメント挿入
- ロール別の自動構成
- Ableton Live 連携の基本フローを実行

### 4. UI
- ローカルブラウザベースの簡易インターフェース
- 生成・表示・送信をまとめて扱う
- 開発・検証・手動操作に便利

### 5. 表現付け
- accent
- swing
- humanize
- MIDI ノートの微調整

### 6. Loudness / audio analysis
- LUFS
- LRA
- peak
- RMS
- duration / dynamic characteristics

---

## プロジェクト構造

```text
abletongpt/
├── src/
│   └── abletongpt/
├── tests/
├── docs/
├── examples/
├── scripts/
├── outputs/
├── README.md
├── pyproject.toml
├── config.example.json
├── run_live_instrument_flow.py
└── .venv/
```

---

## 開発・検証

テストの実行:

```bash
cd /Users/user/MusicAI/abletongpt
PYTHONPATH=src .venv/bin/python -m pytest -q
```

主要対象テスト:

```bash
.venv/bin/python -m pytest -q \
  tests/test_cli_main.py \
  tests/test_cli_compose.py \
  tests/test_cli_intent.py \
  tests/test_cli_live_flow.py \
  tests/test_cli_ui.py \
  tests/test_drumkits.py
```

---

## 注意事項

- バージョン・環境依存があるため、Live 側の準備と Python 環境の整備を先に行ってください
- 実製品環境では、外部公開や不認証アクセスを避けてください
- Ableton Live のデバイスやオブジェクト API は環境差があるため、実際に利用する前に確認を推奨します
- 生成結果は MIDI / 構成案であり、最終的な音色やミックス調整はユーザー側で継続調整してください

---

## ロードマップ

- Live 連携の強化
- MIDI 生成の精度向上
- AI vocal / arrangement の実運用フロー整備
- 追加の検証ケースと CLI バリエーション
- UI の簡素化と用途別操作画面の追加

---

## まとめ

AbletonGPT は、自然言語から Ableton Live 連携までを一気通貫で扱える構成を目指したプロジェクトです。
現在は CLI・UI・Live flow の主要機能が動作し、実際の回帰テストと CLI 検証を通過しています。

必要に応じて、次に README の日本語表現をさらに短くした「入門版」または「技術版」に分けることも可能です。
5. **マスタリング**: 配信先別ターゲットを盲目的に当てるのではなく、音楽的意図と参照曲を基準に複数案を作り、A/B比較できるようにする。
6. **共同制作メモリ**: 曲の狙い、採用/却下した判断、プラグイン制約、バージョン間の変更理由をLive Set単位で保持する。

重要な操作は「解析 → 提案 → 承認 → 適用 → 検証」を基本フローとし、削除、上書き保存、書き出しは明示的な確認なしに実行しない設計を目指します。
