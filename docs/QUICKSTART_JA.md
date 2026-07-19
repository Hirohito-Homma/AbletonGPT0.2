# AbletonGPT クイックスタート

## macOS

プロジェクトのルートで実行します。

```bash
python3 scripts/setup_macos.py
```

既存のAbletonGPT Remote Scriptを更新する場合:

```bash
python3 scripts/setup_macos.py --force
```

セットアップは次を行います。

1. `uv sync --extra dev`
2. 共有トークンを含む設定ファイルの作成
3. Ableton User LibraryへのRemote Script配置
4. MCP実行コマンドの表示

Ableton Liveを完全に再起動し、`Settings > Link, Tempo & MIDI` のControl Surfaceに`AbletonGPT_MCP`を選びます。Input/Outputは`None`で構いません。

診断:

```bash
.venv/bin/abletongpt-doctor
```

## Codexへ登録

```bash
codex mcp add abletongpt -- /absolute/path/to/project/.venv/bin/abletongpt
```

登録後はCodexを再起動し、「Abletonとの接続を確認して」と依頼します。

## ChatGPT Apps / Developer Mode

ローカル検証用のHTTPモード:

```bash
ABLETONGPT_TRANSPORT=streamable-http .venv/bin/abletongpt
```

既定では`127.0.0.1:8000/mcp`です。これはローカル開発用です。認証のない状態でインターネットへ公開しないでください。ChatGPTからリモート接続する本番構成では、認証付きHTTPSゲートウェイが別途必要です。Abletonブリッジの9877番ポートは外部公開しません。

## Windows

1. Python 3.11+で仮想環境を作り、`pip install -e ".[dev]"`を実行。
2. `ableton_remote_script/AbletonGPT`の内容を`Documents/Ableton/User Library/Remote Scripts/AbletonGPT_MCP/`へコピー。
3. `%APPDATA%/AbletonGPT/config.json`を`config.example.json`から作成し、十分に長いランダムなtokenを設定。
4. Liveを再起動し、Control SurfaceでAbletonGPT_MCPを選択。
