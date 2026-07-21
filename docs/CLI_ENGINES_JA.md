# エンジンCLIガイド（instruments / loudness / vocal）

AbletonGPTの純ロジックエンジンは、MCPサーバーを介さずコマンドラインからも直接使えます。いずれも**決定論的**で、**Ableton Liveへ接続しません**（loudnessはファイルを読むだけ、他はファイルI/Oもなし）。すべて `--json` で機械可読出力に切り替えられます。

- `python -m abletongpt.cli.instruments` — ジャンル/ムードから純正音源の選定プランを出力
- `python -m abletongpt.cli.loudness` — WAV/AIFF のLUFS等をオフライン解析（読み取り専用）
- `python -m abletongpt.cli.vocal` — 歌詞から Vocal Guide メロディの計画を出力

アレンジ計画（`arrange` / `jobs` / `arrange-run`）については [アレンジCLIガイド](CLI_ARRANGE_JA.md) を参照してください。

---

## 1. `instruments` — 純正音源の選定プラン

ジャンル・ムード・パート役割から、挿入候補の純正インストゥルメントを決定論的に選びます。挿入自体は行いません（Live側の確認付き操作）。

```bash
python -m abletongpt.cli.instruments --genre edm --mood uplifting
python -m abletongpt.cli.instruments --genre lofi --mood chill --roles keys bass drums
python -m abletongpt.cli.instruments --genre pop --mood bright --edition standard --json
```

出力例:

```text
$ python -m abletongpt.cli.instruments --genre edm --mood uplifting --roles bass drums --edition standard
genre: edm  mood: uplifting  edition: standard
  bass     ベース      -> Drift        [Drift, Wavetable, Operator, Meld]
  drums    ドラム      -> Drum Rack    [Drum Rack, Impulse]
```

| 引数 | 必須 | 説明 |
| --- | --- | --- |
| `--genre` | ○ | `edm, hiphop, jazz, lofi, pop, rnb, rock` |
| `--mood` | ○ | `bittersweet, bright, chill, dark, tense, uplifting` |
| `--roles` | | 複数指定可。既定は `chords bass melody drums`。候補: `bass chords drums keys lead melody pad pluck` |
| `--edition` | | `intro, standard, suite, unknown`（既定 `unknown`） |
| `--json` | | 完全プラン（selections / reason / apply_contract）をJSONで出力 |

不正な値は argparse が exit 2 で弾きます。`--json` の JSON にはロール別の選定理由や、挿入時の契約（確認必須・1トラック1回・既存音源を置換しない）が含まれます。

---

## 2. `loudness` — ラウドネス解析（読み取り専用）

WAV/AIFF を ITU-R BS.1770 / EBU R128 で解析します。ファイルは**一切書き換えません**。

```bash
python -m abletongpt.cli.loudness --file master.wav
python -m abletongpt.cli.loudness --file master.wav --target-lufs -14
python -m abletongpt.cli.loudness --file master.aiff --json
```

出力例:

```text
file: master.wav  (WAV, 48000 Hz, 16-bit, 2ch, 2s)
integrated: -20.04 LUFS   range: n/a LU
true peak:  -20 dBTP   sample peak: -20 dBFS
rms: -23.01 dBFS   crest: 3.01 dB
target: -14 LUFS -> gain 6.04 dB   peak control: no
```

| 引数 | 必須 | 説明 |
| --- | --- | --- |
| `--file` | ○ | 解析する WAV/AIFF ファイル |
| `--target-lufs` | | 目標ラウドネス（-36〜-5）。指定するとゲイン誘導行を追加 |
| `--target-true-peak` | | True Peak 上限（-9〜0、既定 -1.0） |
| `--json` | | 完全レポート（file / measurements / analysis / quality_notes）をJSONで出力 |

無音などで測定不能な値は人間向け表示で `n/a`、JSONでは `null` になります。ファイル無し・非対応形式・範囲外ターゲットは exit 2（明確なメッセージ）。True Peak は 4x 補間の推定値で、認証メーターの代替ではありません。

---

## 3. `vocal` — Vocal Guide の計画

歌詞を決定論的メロディ（作曲エンジン）にマッピングし、編集可能な Vocal Guide を出力します。音声レンダリングは別ハンドオフです。

```bash
python -m abletongpt.cli.vocal --title Neon --lyrics "la la shine on" \
    --genre pop --mood bright --key A --mode minor --tempo 120 --bars 8
python -m abletongpt.cli.vocal ... --seed 7 --json
```

出力例:

```text
title: Neon  key: A minor  tempo: 120  bars: 8  seed: 7
language: en   vocal events: 49
  la       pitch 69  @   0.00  (0.42)
  la       pitch 88  @   0.50  (0.42)
  shine    pitch 69  @   1.00  (0.42)
  ...
  ... 43 more
```

| 引数 | 必須 | 説明 |
| --- | --- | --- |
| `--title` / `--lyrics` | ○ | タイトルと歌詞テキスト |
| `--genre` / `--mood` | ○ | instruments と同じ候補 |
| `--key` | ○ | `A A# Ab B Bb C C# D D# Db E Eb F F# G G# Gb` |
| `--mode` | ○ | `major, minor` |
| `--tempo` | ○ | BPM（40〜240） |
| `--bars` | ○ | `4, 8, 16, 32` |
| `--seed` | | 決定論シード（既定 0）。同じseedなら同じ結果 |
| `--density` | | メロディ密度 0.05〜1.0（既定 0.7） |
| `--json` | | 完全プラン（vocal_events / midi_notes / render_contract）をJSONで出力 |

enum系は argparse が検証（exit 2）。空歌詞や tempo/density の範囲外はエンジンが検出し、明確なメッセージで exit 2 になります。

---

## 共通仕様

- すべてのコマンドが `--json` を受け付け、標準出力に整形済みJSONを返します（日本語ラベルは読みやすさのため非エスケープ）。
- どれも **Ableton Live へ接続しません**。loudnessはファイルを読むだけ、instruments/vocalはファイルI/Oもありません。
- 不正な引数値は終了コード **2** で報告します。
