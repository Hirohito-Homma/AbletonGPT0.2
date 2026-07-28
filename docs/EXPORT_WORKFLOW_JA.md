# Live Set保存・オーディオ書き出しワークフロー

## 境界

公開Live Object Modelには、現在のLive Setを保存する関数と、Main出力をWAV/AIFFへレンダーする関数がありません。AbletonGPTはこの境界を隠さず、次の2段階を提供します。

1. `plan_audio_export`: Liveを変更せず、保存先、Arrangement範囲、形式、Normalize、上書き警告、検証条件をmanifestとして固定する。
2. `verify_audio_export`: Liveで手動書き出ししたWAV/AIFFを変更せず、manifestと照合する。

自動クリック、任意シェル実行、既存ファイルの無確認上書きは行いません。

## 1. 書き出しmanifest

64小節、122 BPM、48 kHz／24-bitステレオWAVの例:

```text
plan_audio_export(
  title="Submerged Signal",
  project_directory="/Volumes/NO NAME/Live14.3.５b/Submerged Signal Project",
  render_start_beats=0,
  render_length_beats=256,
  tempo=122,
  sample_rate_hz=48000,
  bit_depth=24,
  channels=2,
  normalize=false,
  dither="none",
  target_lufs=-7.5,
  target_true_peak_dbtp=-1.0
)
```

manifestには次が含まれます。

- 想定Live Setパスとオーディオパス
- Rendered Track、Render Start、Render Length
- Sample Rate、Bit Depth、チャンネル、Normalize、Dither
- 既存ファイルの有無と上書き確認の必要性
- macOS／Windows用の保存・書き出しショートカット
- 書き出し後の形式、尺、LUFS、True Peak検証条件

`plan_audio_export`はファイルを作成・変更しません。

## 2. Liveで明示的に保存・書き出し

manifestの`manual_steps`に従います。macOSでは通常、Set保存が`Cmd+S`、Export Audio/Videoが`Cmd+Shift+R`です。

Mainマスターをピーク管理した状態で渡す場合は、原則としてNormalizeをOffにします。NormalizeをOnにすると、書き出し後の最大ピークが利用可能な最大値まで増幅されるため、True Peak目標を超える場合があります。

既存の`.als`またはWAV/AIFFを置き換える操作はLiveのダイアログで利用者が明示的に確認します。

## 3. 書き出し検証

書き出し後、`plan_audio_export`が返したmanifestをそのまま渡します。

```text
verify_audio_export(
  file_path="/Volumes/NO NAME/Live14.3.５b/Submerged Signal Project/Submerged Signal.wav",
  manifest=<plan_audio_exportの戻り値>
)
```

必須検証:

- コンテナ（WAV／AIFF）
- Sample Rate
- Bit Depth
- モノ／ステレオ
- Arrangementの想定尺
- 推定True Peak上限

警告扱い:

- manifestと異なる保存先
- Normalize Offなのに0 dBFS付近へ到達しているファイル
- LUFS目標との差

LUFSは音楽的な目標であり、True Peakを超えてまで機械的に合わせる条件にはしていません。`status=pass`または`warning`かつ`safe_to_deliver=true`なら必須条件は満たしています。`status=fail`では`blocking_failures`と`guidance`を確認して再書き出します。

`ffmpeg`がPATHにある環境では、ネイティブのEBU R128フィルターを自動使用して解析を高速化します。結果の`analysis_engine.accelerated`で高速経路を確認できます。`ffmpeg`がない環境や実行に失敗した場合は、従来の純Python解析へ自動的にフォールバックします。

True Peak値は高速経路ではFFmpegの4倍オーバーサンプリング、フォールバックでは4倍補間による推定です。最終納品仕様が厳密な場合は、認証済みTrue Peakメーターとも照合してください。
