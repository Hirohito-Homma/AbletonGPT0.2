# アレンジCLIガイド（arrange / jobs）

MCPサーバーとは別に、AbletonGPTには**アレンジ（曲構成）を計画・実行するためのコマンドラインツール**が2つ付属します。

- `python -m abletongpt.cli.arrange` — アレンジプランJSON（曲のセクション構成）の生成・検証
- `python -m abletongpt.cli.jobs` — アレンジプランからジョブプランを作り、実行・再開・状態確認する。`arrange-run` はこれらを1コマンドにまとめたワンショット経路

データの流れは一方向です。

```text
arrange (アレンジプラン) -> jobs create (ジョブプラン) -> jobs run -> Ableton Live
                                              \-> arrange-run（生成→計画→実行を一括）
```

`run` / `resume` と、`--dry-run` を付けない `arrange-run` だけがAbleton Liveへ接続します。それ以外（`template` / `create-simple` / `validate` / `create` / `status` / `--dry-run*` / `--describe-*` / `--list-styles`）はすべて**純ロジックで、Live接続もファイル破壊もしません**。

すべてのサブコマンドは `--json` を受け付け、機械可読な出力に切り替えられます（後述）。

---

## 1. `arrange` — アレンジプランの作成と検証

アレンジプランは「セクション（intro / drop など）を小節位置に並べたJSON」です。手書きも、以下のコマンドで生成もできます。

### template / create-simple

編集の出発点、またはそのまま使える既定レイアウトを書き出します。

```bash
# 編集用のたたき台
python -m abletongpt.cli.arrange template --name my_song --out arr.json

# そのまま使える既定レイアウト
python -m abletongpt.cli.arrange create-simple --name my_song --out arr.json
```

`--json` を付けると、書き出したファイルの要約を返します。

```json
{
  "name": "my_song",
  "path": "/abs/arr.json",
  "section_count": 5,
  "total_bars": 57
}
```

### validate

アレンジプランJSONの問題を報告します。

```bash
python -m abletongpt.cli.arrange validate --arrangement arr.json
```

常時チェックする項目:

- セクションが空
- `section_id` の重複
- `start_bar` / `length_bars` が正でない
- セクション同士の**バー範囲の重なり**（overlap）

`--strict` を付けると、さらに「**bar 1 から始まる完全連続**」を要求し、先頭のずれとセクション間のギャップ（未使用小節）も報告します。ギャップは既定では正当（無音）として許容されます。

```bash
python -m abletongpt.cli.arrange validate --arrangement arr.json --strict
# invalid arrangement: gap between section 'a' and 'b' (bars 9-19 unused)   (exit 1)
```

`--json` を付けると結果をJSONで返します（`errors` は payload 内、終了コードは 0=正常 / 1=不正）。

```json
{
  "valid": false,
  "name": "g",
  "section_count": 2,
  "total_bars": 28,
  "errors": ["gap between section 'a' and 'b' (bars 9-19 unused)"]
}
```

読み込み・パースに失敗した場合も、`valid: false`・要約フィールドは `null`・例外メッセージを `errors` に入れた**整形済みJSON**を返します。

---

## 2. `jobs` — ジョブプランの作成・実行

ジョブプランは、アレンジプランを実行可能なステップ列（`set_tempo` / `place_scene`）へ変換したものです。

```bash
# アレンジプラン -> ジョブプラン
python -m abletongpt.cli.jobs create --arrangement arr.json --out plan.json

# 実行（Ableton Liveへ接続）
python -m abletongpt.cli.jobs run --plan plan.json

# 途中まで完了したプランを、未完了ステップだけ再実行
python -m abletongpt.cli.jobs resume --plan plan.json

# 実行せずに進捗だけ確認
python -m abletongpt.cli.jobs status --plan plan.json
# completed=0 failed=0 pending=5
```

`create` と `status` は `--json` に対応します。

```bash
python -m abletongpt.cli.jobs status --plan plan.json --json
```
```json
{ "completed": 0, "failed": 0, "pending": 5, "total": 5 }
```

---

## 3. `arrange-run` — ワンショット（生成→計画→実行）

スタイルプリセットから「アレンジ生成 → ジョブプラン化 → （任意で保存）→ 実行」を1コマンドで行います。

```bash
# 既定スタイルで生成して実行（Ableton Liveへ接続）
python -m abletongpt.cli.jobs arrange-run

# スタイル・テンポ・尺・名前を指定
python -m abletongpt.cli.jobs arrange-run --style deep-house --tempo 124 --bars 64 --name late_night
```

### スタイルの一覧・詳細（実行しない）

```bash
python -m abletongpt.cli.jobs arrange-run --list-styles
# dark-tech-house
# deep-house
# minimal-techno
# dub-techno
# pop-song

python -m abletongpt.cli.jobs arrange-run --describe-style deep-house
# style: deep-house
# job plan 'deep_house' with 8 step(s), tempo=122, 64 bar(s)
#   intro          bars 1-8    0:00-0:16 (0:16)
#   groove_a       bars 9-16   0:16-0:31 (0:16)
#   ...
#   outro          bars 57-64  1:50-2:06 (0:16)
```

`pop-song` は電子系のビルド/ドロップ型と違い、intro / verse / pre-chorus / chorus / bridge / outro の**ポップ曲形式**です。両方の verse は同じ `verse` シーンを、全 chorus は同じ `chorus` シーンを参照するので、verse と chorus を1つずつ書けば曲全体に再利用されます（既定 100 BPM・64小節）。

`--describe-all-styles` で全スタイルの要約を出せます。これら一覧・詳細系は `--json` で機械可読にできます（`section_count` / `duration_seconds` / `duration_formatted` / セクション別のタイムラインを含む）。

### 実行前プレビュー（`--dry-run` / `--dry-run-json`）

Live接続も保存もせず、「何が実行されるか」を確認します。

```bash
python -m abletongpt.cli.jobs arrange-run --style deep-house --dry-run
# dry-run: would run job plan 'deep_house' with 8 step(s), tempo=122, 64 bar(s) (no execution)
#   intro          bars 1-8    0:00-0:16 (0:16)
#   ...
#   outro          bars 57-64  1:50-2:06 (0:16)
```

`--dry-run-json` は同じ内容を機械可読JSONで返します（`dry_run: true`、`style`、`section_count`、`duration_*`、`sections`、`steps` を含む）。

```json
{
  "dry_run": true,
  "style": "deep-house",
  "name": "deep_house",
  "step_count": 8,
  "section_count": 7,
  "tempo": 122.0,
  "total_bars": 64,
  "duration_seconds": 125.902,
  "duration_formatted": "2:06",
  "sections": [ /* セクションごとの bar / start / duration */ ],
  "steps":    [ /* place_scene などのステップ */ ]
}
```

### 保存と再開（`--job-path` / `--resume` / `--no-save`）

```bash
# 生成したジョブプランを保存しつつ実行
python -m abletongpt.cli.jobs arrange-run --style deep-house --job-path plan.json

# 保存済みプランを再読込し、未完了ステップだけ実行（--style等は無視され保存済みが優先）
python -m abletongpt.cli.jobs arrange-run --job-path plan.json --resume

# --job-path があっても保存せず実行
python -m abletongpt.cli.jobs arrange-run --style deep-house --job-path plan.json --no-save
```

---

## 4. duration（尺）の算出について

`duration_seconds` は `総小節数 × 4拍 × 60 / テンポ` で求めます（全スタイルプリセットが4/4のため拍数は固定）。テンポが無い（`set_tempo` ステップを持たない）スタイル（例: `dark-tech-house`）では尺は未定義となり、`duration_*` は `null`、人間向け表示は小節数へフォールバックします。`duration_formatted` は `M:SS`（1時間超で `H:MM:SS`）の表示用で、正確な値は常に `duration_seconds` 側が担保します。

---

## 5. 典型的な流れ

```bash
# 1) スタイルを確認
python -m abletongpt.cli.jobs arrange-run --list-styles
python -m abletongpt.cli.jobs arrange-run --describe-style deep-house

# 2) 実行前に中身をプレビュー
python -m abletongpt.cli.jobs arrange-run --style deep-house --tempo 124 --dry-run

# 3) 問題なければ保存しつつ実行（Ableton Liveを起動しておくこと）
python -m abletongpt.cli.jobs arrange-run --style deep-house --tempo 124 --job-path plan.json

# 4) 途中で止まったら未完了分だけ再開
python -m abletongpt.cli.jobs arrange-run --job-path plan.json --resume

# 5) 進捗を確認
python -m abletongpt.cli.jobs status --plan plan.json --json
```

手書きのアレンジを使う場合は `arrange validate` で検証してから `jobs create` → `jobs run` に渡してください。
