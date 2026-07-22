# AbletonGPT

ChatGPT、Codex、その他のMCPクライアントからAbleton Liveを操作し、初心者向け作曲からプロ向けMIDI生成、エフェクト制御、LUFS解析、AIボーカル連携まで扱う統合プロジェクトです。

```text
ChatGPT / Codex -> MCP server -> localhost TCP -> Ableton Remote Script -> Live Object Model
```

公開する操作は、接続確認、状態取得、初心者向け作曲スケッチ、MIDIクリップ／ノート生成、MIDI/オーディオトラック作成、純正デバイス挿入、エフェクト一覧・オン/オフ・パラメーター変更、再生/停止、テンポ、トラック音量、録音待機、Sessionクリップ起動、SessionからArrangementへの安全なコピーです。任意Python実行、トラックやファイルの削除、Live Set保存は実装していません。

## 現在の構成

- 初心者モード: 雰囲気、キー、BPM、小節数から4パートを生成
- プロモード: 度数進行、7th/9th、ボイスリーディング、密度、スウィング、ヒューマナイズ、seed
- 部分再生成: 一つのパートだけを別Sessionスロットへ生成してA/B比較
- AI音源選択: ジャンル、ムード、パート役割、Liveエディションから純正インストゥルメントを選択
- コンテキスト作曲: 利用者の既存MIDIクリップを解析し、調和する補完トラックを生成
- Live操作: トラック、クリップ、テンポ、再生、録音待機
- Arrangementコピー: 単体SessionクリップまたはScene全体を指定拍へ非破壊配置
- Audio参照: Session／Arrangementクリップの元ファイルパスとWarp情報を読み取り専用で取得
- ミックス基礎: 音量、パン、Mute、Solo、Send／瞬間メータースナップショット
- ラウドネス解析: WAV/AIFFのIntegrated／Momentary／Short-term LUFS、LRA、Peak、RMS、Crest Factor
- エフェクト: 純正デバイス挿入、一覧、オン/オフ、パラメーター変更
- AIボーカル: 歌詞・Vocal Guide設計、MIDI作成、レンダリング済みWAV取り込み
- 安全性: localhost限定、共有トークン、入力検証、削除・上書き・任意コード実行なし

設計の詳細は [Architecture](docs/ARCHITECTURE.md)、プロンプト例は [Prompt examples](examples/prompts_ja.md) を参照してください。曲構成を計画・実行するコマンドライン（`arrange` / `jobs` / `arrange-run`）の使い方は [アレンジCLIガイド](docs/CLI_ARRANGE_JA.md)、純ロジックエンジンのCLI（`instruments` / `loudness` / `vocal` / `compose` / `contextual` / `expression`）は [エンジンCLIガイド](docs/CLI_ENGINES_JA.md) にまとめています。これらは統合エントリポイント `abletongpt-cli <サブコマンド>` からも呼び出せます。

## 必要なもの

- Ableton Live 11以降
- Python 3.11以降
- `uv`（推奨）または `pip`

## 1. Python環境

macOSの推奨セットアップ:

```bash
python3 scripts/setup_macos.py
```

詳細は [クイックスタート](docs/QUICKSTART_JA.md) を参照してください。

手動でPython環境だけを作る場合:

```bash
uv sync --extra dev
uv run pytest
```

pytestを導入せずに統合チェックだけを行う場合:

```bash
.venv/bin/python scripts/run_checks.py
```

`uv`を使わない場合:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

## 2. Ableton Remote Script

macOSでは次のフォルダを作り、このリポジトリの `ableton_remote_script/AbletonGPT/__init__.py` をコピーします。

```text
~/Music/Ableton/User Library/Remote Scripts/AbletonGPT_MCP/__init__.py
```

Liveを再起動し、`Settings > Link, Tempo & MIDI > Control Surface` で `AbletonGPT_MCP` を選択します。Input/Outputは `None` で構いません。

## 3. MCPクライアントへ登録

stdio対応クライアントでは、次のコマンドをMCPサーバーとして登録します。

```text
/absolute/path/to/repository/.venv/bin/abletongpt
```

Codex CLIの例:

```bash
codex mcp add abletongpt -- /absolute/path/to/repository/.venv/bin/abletongpt
```

登録後、まず「Abletonとの接続を確認して」「Liveの状態を見せて」と依頼してください。

初心者向け作曲の例:

- 「ジャンルはPop、ムードはUplifting、Cメジャー、110 BPM、8小節で設計して」
- 設計図を確認後、「この案でAbletonに作って」
- Chords、Bass、Melody、Drumsの4つのMIDIトラックと編集可能なクリップが作られます。

`plan_song_sketch`はLiveを変更しません。初心者向けの説明とノート構成を確認してから、`create_song_sketch`で反映してください。生成されるのは音声ではなくMIDIなので、音色、コード、メロディ、リズムを後から自由に直せます。

ジャンルとムードは独立した設定です。

- `genre`: `pop` / `rock` / `edm` / `hiphop` / `rnb` / `jazz` / `lofi`
- `mood`: `bright` / `uplifting` / `chill` / `dark` / `bittersweet` / `tense`

ジャンルはドラム、ベース、演奏語法を決め、ムードは既定のコード進行と音楽的な明暗を決めます。例えば`genre=rock, mood=chill`や`genre=hiphop, mood=uplifting`のように自由に組み合わせられます。`progression`を明示した場合は、ムードの既定進行よりカスタム進行が優先されます。

上級者向けには `plan_pro_composition` と `create_pro_composition` を使います。

- `genre`: リズム／ベース／演奏語法
- `mood`: コード進行／明暗／緊張感
- `progression`: 1〜7の度数進行。例: `[2, 5, 1, 6]`
- `chord_complexity`: `triad` / `seventh` / `ninth`
- `harmonic_rhythm_beats`: 1 / 2 / 4 / 8拍ごとのコードチェンジ
- `melody_density`: 0.05〜1.0
- `swing`: 0.0〜1.0
- `humanize`: 0.0〜1.0
- `seed`: 同じ設定の再現、または別テイク生成に使う整数

コードは転回形を含む候補から前のコードとの移動量が小さいボイシングを選びます。`create_part_variation`を使うと、コードやテンポを固定したままMelodyなど一つのパートだけを別のSessionスロットへ生成でき、seed違いをA/B比較できます。低レベルの`create_midi_clip`も公開されているため、AIが生成した任意のMIDIノート列を直接配置できます。

### AIによるLiveインストゥルメント選択

`plan_live_instruments`はLiveを変更せず、ジャンル、ムード、パート役割から純正インストゥルメントの第一候補とフォールバック候補を選びます。対応する役割は`chords`、`bass`、`melody`、`lead`、`pad`、`keys`、`pluck`、`drums`です。

選択対象:

- Drift / Wavetable / Operator / Analog / Meld
- Electric / Tension / Collision
- Drum Rack / Impulse

使用例:

- 「Pop、UpliftingのChords、Bass、Melody、Drumsに合うLive純正音源を選んで。まだ挿入しないで」
- 「確認した候補をChordsトラックへ適用して」

確認後、`apply_live_instrument_selection`を1トラックずつ呼び出します。第一候補が現在のLiveにない場合は候補順にフォールバックします。既存のインストゥルメントは削除も置換もせず、すでに音源があるトラックへの挿入は拒否します。`preferred_instrument`を指定すると、許可済みで役割に対応する純正音源だけを第一候補にできます。

自動挿入にはAbleton Live 12.3以降が必要です。Intro、Standard、Suiteやインストール済みPackによって利用可能な音源が異なるため、Live側で実在する候補を最終確認します。Drum RackとImpulseはデバイスを挿入した後にキットまたはサンプルの読み込みが必要です。

### 利用者のMIDIトラックを解析した補完作曲

利用者が作った既存MIDIクリップを読み取り、次の音楽的特徴を解析できます。

- 推定パート役割、キー、メジャー／マイナー
- 小節ごとの推定ハーモニールート
- 音域、ノート密度、リズムグリッド、平均音価
- Velocity、同時発音率、使用ピッチ

解析結果から、`chords`、`bass`、`pad`、`melody`、`countermelody`、`drums`の補完トラックを設計できます。

1. `analyze_live_midi_clip`で既存クリップを読み取り専用で解析する。
2. `plan_complementary_midi_track`で補完パートを確認する。
3. `create_complementary_midi_track`で新規MIDIトラックとクリップを作成する。
4. AIが提案した純正インストゥルメントを確認して適用する。

使用例:

- 「0番トラックの0番クリップを解析して、合うBassを設計して。まだ作らないで」
- 「このコードクリップの空いているタイミングにCounter Melodyを作って」
- 「seed 12の案を新しいMIDIトラックとして作って」

元クリップには指紋を付け、設計確認後に内容が変わった場合は古い案の適用を拒否できます。生成先は新規MIDIトラックで、元クリップを上書きしません。ドラムクリップだけから和音系パートを作る場合は、`key_override`と`mode_override`でキーを指定します。

現在のコンテキスト作曲はMIDIクリップが対象です。音声トラックからキー、BPM、コード、メロディを抽出する機能は、LUFS解析とは別の音響解析として今後追加します。

### 既存クリップの表情付け

既存MIDIクリップに、拍位置に応じたベロシティのアクセント・スイング・タイミング/ベロシティのヒューマナイズ・裏拍のノート確率・MIDI CCオートメーション曲線（ramp/arch/sine）を**決定論的に**与えます。

1. `plan_expression`で表情付けの計画を**読み取り専用**に取得して確認する（ノート数は不変）。
2. `apply_expression`で、確認した表情を既存クリップのノートへ適用する。`expected_source_fingerprint`を渡せば、確認後にクリップが変わっていた場合は適用を拒否できる。適用は**LiveのUndoで戻せます**。

`apply_expression`はノート（ベロシティ/タイミング/確率）の差し替えのみを行い、**MIDI CCオートメーションの書き戻しは現時点では対象外**です（プランには含まれます。公開LOMに安定したCCエンベロープ書き込みAPIが無いため、別途対応予定）。同じ表情付けロジックはCLI [`abletongpt-cli expression`](docs/CLI_ENGINES_JA.md) でも計画として使えます。

### AIボーカル

AIボーカルは特定の非公式サービスAPIへ固定せず、次の共通フローにしています。

1. `plan_ai_vocal`で歌詞、音程、タイミング、レンダリング条件を確認する。
2. `create_vocal_guide`で編集可能なVocal Guide MIDIを作る。
3. Synthesizer V、ACE Studioなど、利用権を確認済みの歌声エンジンでドライWAVを書き出す。
4. `import_vocal_take`でWAVを新規Audioトラックへ戻す。
5. Ableton上でコンピング、EQ、コンプレッション、空間処理を行う。

推奨受け渡し形式は48 kHz/24-bit WAV、エフェクトなし、1小節目からの書き出しです。声を学習・クローンする場合は、声の本人から用途を含む明示的同意を得た素材だけを使用してください。著名人や第三者になりすます用途は対象外です。

トラック作成の例:

- 「末尾にBassというMIDIトラックを作って」
- 「先頭にVocalというオーディオトラックを作って」

エフェクト操作の例:

- 「Vocalトラックにあるエフェクトとパラメーターを見せて」
- 「Vocalの末尾にEQ Eightを追加して」
- 「Vocalの最初のエフェクトをバイパスして」
- 「Auto FilterのFrequencyを範囲の35%にして」
- 「変更前に現在値と変更後の値を説明してから適用して」

パラメーター番号や内部値はデバイスごとに異なるため、変更前に必ず `get_track_devices` で最新状態を取得してください。自動化、Rack Macro、`live.remote~` などで直接操作できないパラメーターは変更を拒否します。

純正デバイスの挿入にはAbleton Live 12.3以降が必要です。現在の公式APIでは、`add_native_device`によるMax for LiveデバイスやVST/AUプラグインの挿入には対応していません。Live 11〜12.2でも、AIによる候補選択と、すでに配置済みのデバイスの読み取り／パラメーター変更は利用できます。

### LUFS／ラウドネス解析

`analyze_audio_loudness`は、Ableton Liveから書き出した非圧縮WAVまたはAIFFを変更せずにオフライン解析します。Abletonの瞬間メーターとは別の機能で、Liveを起動していなくても利用できます。

- Integrated LUFS
- 最大Momentary LUFS（400 ms）
- 最大Short-term LUFS（3秒）
- Loudness Range（LRA）
- Sample Peak、推定True Peak
- RMS、Crest Factor

使用例:

- 「`/path/to/mix.wav`のLUFSを解析して」
- 「このマスターを目標-14 LUFS、上限-1 dBTPとして解析して。まだ音声は変更しないで」

`target_lufs`は任意です。指定すると、必要なゲイン量、ゲイン適用後の予測True Peak、ピーク制御が必要になりそうかを返します。自動ノーマライズやリミッター適用は行いません。

LUFSはITU-R BS.1770のK-weightingとEBU R128方式のゲーティングで計算します。True Peakは4倍補間による制作判断用の推定値なので、最終納品では認証済みメーターでも確認してください。現在は非圧縮PCM／IEEE FloatのWAV、AIFF、AIFF-Cに対応し、MP3、AAC、FLACは未対応です。

## ChatGPTから接続する場合

ChatGPTのApps/Developer Modeから使うMCPは、通常はChatGPTから到達できるHTTPSのStreamable HTTPエンドポイントが必要です。ローカルでHTTPモードを起動するには:

```bash
ABLETONGPT_TRANSPORT=streamable-http uv run abletongpt
```

その後、認証付きのHTTPSリバースプロキシまたは安全なトンネルで `/mcp` を公開します。Ableton側のTCPポート `9877` 自体は絶対に外部公開しないでください。本番利用ではMCPエンドポイントにも認証を追加してください。

## 設定

MCPサーバーとRemote Scriptの両方で同じ環境変数を利用できます。

- `ABLETONGPT_HOST`（MCP側のみ、既定 `127.0.0.1`）
- `ABLETONGPT_PORT`（既定 `9877`）
- `ABLETONGPT_TOKEN`（任意の共有トークン）
- `ABLETONGPT_TIMEOUT`（MCP側のみ、既定3秒）
- `ABLETONGPT_TRANSPORT`（`stdio` または `streamable-http`）

Remote ScriptはLiveプロセス内で動くため、Liveを起動した環境に `ABLETONGPT_TOKEN` が渡る必要があります。まずはlocalhost限定で動作確認し、外部公開前に認証方式を追加してください。

## よくある問題

- Control Surfaceに表示されない: フォルダ階層とファイル名を確認し、Liveを完全に再起動する。
- 接続できない: Control Surfaceとして選択済みか、ポート9877が他プロセスに使われていないか確認する。
- Live 12.1以降で古いスクリプトが動かない: `.py`ソースを配置し、古い`.pyc`を持ち込まない。

## ロードマップ

1. **制作**: トラック、デバイス、クリップ、MIDIノート、ルーティングを構造化されたツールで扱う。
2. **理解**: Live Setの構造と書き出し音源のピーク/RMS/LUFSを読み取り、周波数バランス、ダイナミクス、位相、参照曲比較へ拡張する。
3. **安全なミックス**: 変更前スナップショット、提案プレビュー、差分表示、承認後の一括適用、即時ロールバックを備える。
4. **トラックダウン**: 書き出し範囲、ステム、サンプルレート、ビット深度、ディザ、ファイル命名を検証可能なプリセットにする。
5. **マスタリング**: 配信先別ターゲットを盲目的に当てるのではなく、音楽的意図と参照曲を基準に複数案を作り、A/B比較できるようにする。
6. **共同制作メモリ**: 曲の狙い、採用/却下した判断、プラグイン制約、バージョン間の変更理由をLive Set単位で保持する。

重要な操作は「解析 → 提案 → 承認 → 適用 → 検証」を基本フローとし、削除、上書き保存、書き出しは明示的な確認なしに実行しない設計を目指します。
