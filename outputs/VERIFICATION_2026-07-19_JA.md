# AbletonGPT 0.2 実機検証結果

検証日時: 2026-07-19 01:06 JST  
対象: Ableton Live 12 Suite、localhost bridge `127.0.0.1:9877`

## 総評

- 自動テスト: `pytest` 24件すべて成功
- 統合チェック: 34件すべて成功
- Live実機シナリオ: 21項目中19成功、2項目で実装上の問題を検出
- 元のTempo `20 BPM`、停止状態、検証対象トラックのMute/Solo/Arm/Volume/Panは復元済み
- 削除機能がないため、検証用に追加した11トラックとクリップはLive Setに残している

## 機能別結果

| 機能 | 判定 | 実機で確認した内容 |
|---|---|---|
| 初心者モード | 成功 | C major、110 BPM、4小節からChords/Bass/Melody/Drumsを作成。12/16/23/48ノートをLiveへ配置 |
| プロモード | 成功 | `[2,5,1,6]`、ninth、2拍ハーモニックリズム、密度0.55、swing 0.4、humanize 0.3、seed 42を反映。Live上で8コードすべて5音、合計40ノート |
| 7th/9th・密度・seed | 成功 | triad/seventh/ninthは4コードで12/16/20ノート。密度0.1/1.0は2/32ノート。同一seedは完全一致、別seedは和声を保ってMelodyが変化 |
| ボイスリーディング | 成功 | Liveへ転送後の8個のninthコードで、隣接コード間の総移動量は最大10 semitones |
| 部分再生成 | 成功 | Pro MelodyのSession slot 1をA、slot 2をseed 43のBとして作成。19ノート対15ノートで内容が相違 |
| AI音源選択 | **問題あり** | 役割・genre・mood・edition別の候補選定は成功。Wavetable自体も挿入されたが、実装がLiveのdevice typeを誤判定して例外を返した |
| コンテキスト作曲 | 成功 | 既存ChordsクリップからC major、C/F/G/Cを推定し、元を変更せず新規Bassトラックへ16ノートを生成。fingerprint照合も成功 |
| Live操作 | **一部問題あり** | Tempo、Arm、Clip fire、Play、Stopは実状態で成功。ただしStop直後のレスポンスだけが更新前の`is_playing: true`を返す |
| ミックス基礎 | 一部対応 | Volume、Pan、Mute、Solo、Send値読み取り、瞬間メータースナップショットは成功。Send値を変更するMCPツールは存在しない |
| ラウドネス解析 | 成功 | 48 kHz/24-bit WAVと48 kHz/16-bit AIFFでIntegrated/Momentary/Short-term LUFS、LRA、Peak、True Peak推定、RMS、Crest Factorを取得。解析前後のSHA-256が一致 |
| エフェクト | 成功 | Auto Filterを挿入し、一覧取得、OFF/ON、Frequencyをnormalized 0.35へ変更、既定値へreset |
| AIボーカル | 成功 | 日本語歌詞を28イベントへ割当、Vocal Guide MIDIを作成し、48 kHz/24-bitのレンダリング済みWAV相当ファイルを新規Audioトラックへ取り込み |
| 安全性 | 成功 | 実listenerが`127.0.0.1:9877`限定。共有tokenあり、誤token拒否、範囲外BPM/MIDI拒否、既存clip上書き拒否、delete/任意code command拒否、MCPに破壊的ツールなし |

## 検出した問題

### 1. 純正インストゥルメントのdevice type判定が逆

実機値はWavetableが`type=1`、Auto Filterが`type=2`だった。一方、Remote Scriptは`type == 2`をインストゥルメントとして扱っている。このため次の二つが起きる。

- Wavetableの挿入自体は成功するが、その直後に「instrumentではない」として失敗応答を返す
- Audio Effectを既存インストゥルメントと誤認し、挿入を拒否する可能性がある

該当箇所: `ableton_remote_script/AbletonGPT/__init__.py` の既存音源判定と挿入後判定。

### 2. Stopの戻り値が1ティック古い

`song.stop_playing()`の直後に`bool(song.is_playing)`を返すため、レスポンスは`true`のままだが、直後の`get_state`では`false`になっていた。停止操作そのものは成功しているが、応答だけが誤解を招く。

### 3. Sendは読み取り専用

スナップショットには各Send値が含まれるが、`set_track_send`相当の公開ツールはない。「Send操作」を要件に含める場合は未実装。

## 実機に残した検証物

- Beginner: tracks 1-4、Session slot 0
- Pro: tracks 5-8、Session slot 1
- Melody variation: track 7、Session slot 2
- Context Bass: track 9、Session slot 0
- Vocal Guide: track 10、Session slot 3
- Vocal Take: track 11、Session slot 4
- WavetableとAuto Filter: Beginner Melody track

詳細な機械可読結果は `outputs/live_verification_20260719_010623.json` を参照。
