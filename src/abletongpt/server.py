from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .backends import FallbackBridge
from .bridge import AbletonBridge
from .composition import build_song_plan
from .config import setting
from .audio import (
    detect_onsets,
    estimate_chords,
    estimate_key,
    estimate_tempo,
    extract_melody,
    extract_spectral_features,
    segment_structure,
    track_beats,
)
from .contextual import analyze_midi_context, build_complementary_track_plan
from .expression import AUTOMATION_SHAPES, build_expression_plan
from .extensions_bridge import ExtensionsBridge
from .instruments import build_instrument_plan, build_role_selection
from .loudness import analyze_loudness_file
from .snapshots import build_snapshot, diff_snapshots
from .transcription import build_midi_from_melody
from .vocal import build_vocal_plan


#: Accepted ``backend`` config values mapped to their canonical name. The Remote Script
#: is the default; ``extensions`` opts into the Ableton Extensions SDK companion.
_BACKEND_ALIASES = {
    "": "remote_script",
    "default": "remote_script",
    "remote": "remote_script",
    "remote_script": "remote_script",
    "extension": "extensions",
    "extensions": "extensions",
    "auto": "auto",
}


def resolve_backend_name() -> str:
    """Return the canonical backend name from config/env (raises on an unknown value)."""
    raw = str(setting("backend", "remote_script")).strip().lower()
    if raw not in _BACKEND_ALIASES:
        raise ValueError(
            "unknown backend %r; use 'remote_script', 'extensions' or 'auto'" % raw
        )
    return _BACKEND_ALIASES[raw]


def select_backend() -> AbletonBridge | ExtensionsBridge | FallbackBridge:
    """Build the configured Live backend. All share the same ``call`` contract.

    ``remote_script`` (default) talks to the Control Surface Remote Script; ``extensions``
    talks to the Ableton Extensions SDK companion (Live 12 Suite Beta 12.4.5+); ``auto``
    prefers the Extensions companion and falls back to the Remote Script if it is
    unreachable. The connection is lazy, so selecting a backend never opens a socket on
    its own.
    """
    name = resolve_backend_name()
    if name == "extensions":
        return ExtensionsBridge()
    if name == "auto":
        return FallbackBridge(ExtensionsBridge(), AbletonBridge())
    return AbletonBridge()


mcp = FastMCP(
    "AbletonGPT",
    instructions=(
        "Ableton Liveを操作します。変更系ツールを呼ぶ前に対象トラックやクリップを明示し、"
        "曖昧な場合は先にget_live_stateを使ってください。"
    ),
    host=os.getenv("ABLETONGPT_MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("ABLETONGPT_MCP_PORT", "8000")),
)
bridge = select_backend()


@mcp.tool()
def get_abletongpt_capabilities() -> dict[str, Any]:
    """AbletonGPTの機能、互換性、安全上の制限を返す。Liveへの接続は不要。"""
    return {
        "version": "0.2.0",
        "live_support": "Ableton Live 11+; native device insertion requires Live 12.3+",
        "backend": resolve_backend_name(),
        "available_backends": ["remote_script", "extensions", "auto"],
        "features": [
            "transport and track control",
            "beginner song sketches",
            "professional deterministic composition",
            "part variations",
            "MIDI clip and note creation",
            "single-command quantized clip-group launch",
            "atomic full-scene launch including audio clips",
            "non-overwriting Session clip duplication",
            "collision-safe Session-to-Arrangement clip and scene copy",
            "read-only Session and Arrangement audio source-path inspection",
            "non-destructive normalized mix-state snapshots and snapshot diffing",
            "read-only Live browser navigation for presets and kits",
            "loading a browsed preset/kit onto a track (additive; refuses tracks that already have an instrument)",
            "device and effect parameter control",
            "AI native-instrument selection with safe fallback",
            "existing MIDI clip analysis and complementary track generation",
            "expressive-performance planning for a MIDI clip and applying it to the clip notes (accent/swing/humanize/probability; CC automation is plan-only for now)",
            "AI vocal guide planning",
            "rendered vocal audio import",
            "offline WAV/AIFF loudness analysis",
            "offline WAV/AIFF tempo (BPM) estimation (requires the audio extra: NumPy)",
            "offline WAV/AIFF key estimation (requires the audio extra: NumPy)",
            "offline WAV/AIFF chord-progression extraction (requires the audio extra: NumPy)",
            "offline WAV/AIFF monophonic melody extraction (requires the audio extra: NumPy)",
            "offline WAV/AIFF onset/transient detection (requires the audio extra: NumPy)",
            "offline WAV/AIFF beat-grid tracking (requires the audio extra: NumPy)",
            "offline WAV/AIFF timbral spectral features (requires the audio extra: NumPy)",
            "offline WAV/AIFF structural segmentation (requires the audio extra: NumPy)",
            "audio-to-MIDI: transcribing an extracted monophonic melody into an editable MIDI clip",
            "selectable Live backend: Remote Script (default) or the opt-in Ableton Extensions SDK companion",
        ],
        "safety": [
            "localhost-only Ableton bridge",
            "no arbitrary Python execution",
            "no track/file deletion tools",
            "no automatic Live Set overwrite or export",
            "loudness analysis never modifies the source audio",
        ],
        "external_vocal_engine_required": True,
    }


@mcp.tool()
def ping_ableton() -> dict[str, Any]:
    """Ableton Liveとの接続を確認する。"""
    return bridge.call("ping")


@mcp.tool()
def get_live_state() -> dict[str, Any]:
    """再生状態、テンポ、拍子、トラック一覧を取得する。"""
    return bridge.call("get_state")


@mcp.tool()
def get_audio_clip_paths(
    track_index: int,
    view: str = "both",
) -> dict[str, Any]:
    """指定トラックのSession／Arrangement audioクリップと元ファイルパスを読み取り専用で取得する。"""
    if track_index < 0:
        raise ValueError("track_index must be non-negative")
    if view not in {"session", "arrangement", "both"}:
        raise ValueError("view must be session, arrangement, or both")
    return bridge.call(
        "get_audio_clip_paths",
        track_index=track_index,
        view=view,
    )


@mcp.tool()
def analyze_live_midi_clip(
    track_index: int,
    clip_index: int,
    source_role: str = "auto",
) -> dict[str, Any]:
    """Liveを変更せず、既存MIDIクリップのキー、役割、音域、密度、リズム、ハーモニーを解析する。"""
    clip_data = _read_midi_clip(track_index, clip_index)
    return analyze_midi_context(clip_data, source_role)


@mcp.tool()
def plan_complementary_midi_track(
    track_index: int,
    clip_index: int,
    target_role: str,
    source_role: str = "auto",
    genre: str = "pop",
    mood: str = "bright",
    key_override: str = "",
    mode_override: str = "",
    seed: int = 0,
    title: str = "",
) -> dict[str, Any]:
    """Liveを変更せず、既存MIDIクリップを解析して調和する補完トラックを設計する。"""
    clip_data = _read_midi_clip(track_index, clip_index)
    return build_complementary_track_plan(
        clip_data,
        target_role,
        source_role,
        genre,
        mood,
        key_override,
        mode_override,
        seed,
        title,
    )


@mcp.tool()
def create_complementary_midi_track(
    track_index: int,
    clip_index: int,
    target_role: str,
    source_role: str = "auto",
    genre: str = "pop",
    mood: str = "bright",
    key_override: str = "",
    mode_override: str = "",
    seed: int = 0,
    new_track_name: str = "",
    destination_clip_index: int = 0,
    expected_source_fingerprint: str = "",
) -> dict[str, Any]:
    """確認済み設計を、既存MIDIクリップに調和する新規MIDIトラックとして作成する。"""
    if destination_clip_index < 0:
        raise ValueError("destination_clip_index must be non-negative")
    clip_data = _read_midi_clip(track_index, clip_index)
    plan = build_complementary_track_plan(
        clip_data,
        target_role,
        source_role,
        genre,
        mood,
        key_override,
        mode_override,
        seed,
        new_track_name,
    )
    fingerprint = plan["generation"]["source_fingerprint"]
    if expected_source_fingerprint and expected_source_fingerprint != fingerprint:
        raise ValueError("source MIDI clip changed after the plan was reviewed")
    state = bridge.call("get_state")
    scene_count = int(state.get("scene_count", 0))
    if destination_clip_index >= scene_count:
        raise ValueError("destination_clip_index is outside the current Live scenes")
    new_track_index = len(state["tracks"])
    target = plan["target_track"]
    bridge.call("create_track", track_type="midi", name=target["name"], index=-1)
    clip = bridge.call(
        "create_midi_clip",
        track_index=new_track_index,
        clip_index=destination_clip_index,
        name="%s - Generated" % target["name"],
        length_beats=target["length_beats"],
        notes=target["notes"],
    )
    return {
        "source_analysis": plan["source_analysis"],
        "generation": plan["generation"],
        "track_index": new_track_index,
        "clip": clip,
        "instrument_selection": plan["instrument_selection"],
        "next_step": "生成結果を再生して確認し、必要ならseedを変えて別Sessionスロットへ生成してください。",
    }


@mcp.tool()
def plan_expression(
    track_index: int,
    clip_index: int,
    accent: float = 0.0,
    swing: float = 0.0,
    humanize: float = 0.0,
    weak_beat_probability: float = 1.0,
    beats_per_bar: int = 4,
    grid_beats: float = 0.5,
    automation_shape: str = "",
    automation_cc: int = 1,
    automation_depth: int = 64,
    automation_base: int = 0,
    automation_cycles: int = 1,
    automation_resolution_beats: float = 0.25,
    seed: int = 0,
) -> dict[str, Any]:
    """Liveを変更せず、既存MIDIクリップへ与える表情付け（アクセント/スイング/ヒューマナイズ/裏拍確率/CCオートメーション）を計画する。適用はapply_expressionで確認後に行う。"""
    if automation_shape and automation_shape not in AUTOMATION_SHAPES:
        raise ValueError(
            "automation_shape must be empty or one of %s" % ", ".join(AUTOMATION_SHAPES)
        )
    clip_data = _read_midi_clip(track_index, clip_index)
    return build_expression_plan(
        clip_data,
        accent=accent,
        swing=swing,
        humanize=humanize,
        weak_beat_probability=weak_beat_probability,
        beats_per_bar=beats_per_bar,
        grid_beats=grid_beats,
        automation_shape=automation_shape or None,
        automation_cc=automation_cc,
        automation_depth=automation_depth,
        automation_base=automation_base,
        automation_cycles=automation_cycles,
        automation_resolution_beats=automation_resolution_beats,
        seed=seed,
    )


@mcp.tool()
def apply_expression(
    track_index: int,
    clip_index: int,
    accent: float = 0.0,
    swing: float = 0.0,
    humanize: float = 0.0,
    weak_beat_probability: float = 1.0,
    beats_per_bar: int = 4,
    grid_beats: float = 0.5,
    seed: int = 0,
    expected_source_fingerprint: str = "",
) -> dict[str, Any]:
    """plan_expressionで確認した表情付けを、既存MIDIクリップのノートへ適用する。ノート数は不変で、LiveのUndoで戻せる。CCオートメーションの書き戻しはまだ対象外。expected_source_fingerprintを渡すと、確認後にクリップが変わっていた場合は適用を拒否する。"""
    if track_index < 0 or clip_index < 0:
        raise ValueError("indices must be non-negative")
    clip_data = _read_midi_clip(track_index, clip_index)
    plan = build_expression_plan(
        clip_data,
        accent=accent,
        swing=swing,
        humanize=humanize,
        weak_beat_probability=weak_beat_probability,
        beats_per_bar=beats_per_bar,
        grid_beats=grid_beats,
        seed=seed,
    )
    fingerprint = plan["source"]["fingerprint"]
    if expected_source_fingerprint and expected_source_fingerprint != fingerprint:
        raise ValueError("source MIDI clip changed after the plan was reviewed")
    length = plan["source"]["length_beats"]
    _validate_midi_clip(track_index, clip_index, length, plan["notes"])
    applied = bridge.call(
        "apply_expression_to_clip",
        track_index=track_index,
        clip_index=clip_index,
        length_beats=length,
        notes=plan["notes"],
    )
    return {
        "source": plan["source"],
        "settings": plan["settings"],
        "diff": plan["diff"],
        "applied": applied,
        "next_step": "クリップを再生して表情を確認してください。元に戻すにはLiveのUndoを使えます。",
    }


@mcp.tool()
def get_mix_snapshot() -> dict[str, Any]:
    """全トラックとMasterの音量、パン、Mute、Solo、Send、瞬間メーターレベルを取得する。LUFS解析ではない。"""
    return bridge.call("get_mix_snapshot")


@mcp.tool()
def capture_state_snapshot(label: str | None = None) -> dict[str, Any]:
    """現在のテンポ／拍子／全トラック・Return・Masterのミックス状態を、瞬間メーターを除いた
    安定した正規化スナップショットとして読み取り専用で取得する。編集の前後で撮って
    diff_state_snapshotsで差分比較できる。Liveは一切変更しない。"""
    state = bridge.call("get_state")
    mix = bridge.call("get_mix_snapshot")
    captured_at = datetime.now(timezone.utc).isoformat()
    return build_snapshot(state, mix, label=label, captured_at=captured_at)


@mcp.tool()
def diff_state_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """capture_state_snapshotで撮った2つのスナップショットを比較し、テンポ／拍子と各トラック・
    Return・Masterのボリューム／パン／Mute／Solo／Arm／Sendの変化を構造化して返す。純ロジック・読み取り専用。"""
    return diff_snapshots(before, after)


@mcp.tool()
def analyze_audio_loudness(
    file_path: str,
    target_lufs: float | None = None,
    target_true_peak_dbtp: float = -1.0,
) -> dict[str, Any]:
    """WAV/AIFFを変更せず、LUFS、LRA、True Peak推定、RMS、Crest Factorを解析する。target_lufsは任意。"""
    return analyze_loudness_file(file_path, target_lufs, target_true_peak_dbtp)


@mcp.tool()
def analyze_audio_tempo(
    file_path: str,
    min_bpm: float = 60.0,
    max_bpm: float = 200.0,
) -> dict[str, Any]:
    """WAV/AIFFを変更せず、テンポ(BPM)をオフライン推定する。NumPy(`abletongpt[audio]`)が必要。読み取り専用。"""
    return estimate_tempo(file_path, min_bpm=min_bpm, max_bpm=max_bpm)


@mcp.tool()
def analyze_audio_key(file_path: str) -> dict[str, Any]:
    """WAV/AIFFを変更せず、キー(調)をオフライン推定する。NumPy(`abletongpt[audio]`)が必要。読み取り専用。"""
    return estimate_key(file_path)


@mcp.tool()
def analyze_audio_chords(file_path: str, window_seconds: float = 0.5) -> dict[str, Any]:
    """WAV/AIFFを変更せず、コード進行(メジャー/マイナー三和音)をオフライン抽出する。NumPy必須。読み取り専用。"""
    return estimate_chords(file_path, window_seconds=window_seconds)


@mcp.tool()
def analyze_audio_melody(file_path: str, min_f0: float = 65.0, max_f0: float = 1047.0) -> dict[str, Any]:
    """WAV/AIFFを変更せず、単音メロディ(音符列)をYINでオフライン抽出する。単旋律前提。NumPy必須。読み取り専用。"""
    return extract_melody(file_path, min_f0=min_f0, max_f0=max_f0)


@mcp.tool()
def analyze_audio_onsets(file_path: str, delta: float = 0.07) -> dict[str, Any]:
    """WAV/AIFFを変更せず、ノート/トランジェントのオンセット時刻(秒)をオフライン検出する。deltaは感度(小さいほど鋭敏)。NumPy必須。読み取り専用。"""
    return detect_onsets(file_path, delta=delta)


@mcp.tool()
def analyze_audio_beats(file_path: str, beats_per_bar: int = 4) -> dict[str, Any]:
    """WAV/AIFFを変更せず、ビートグリッド(拍の時刻・秒)をオフライン推定する。テンポ推定＋オンセットへの位相合わせ。
    beats_per_barで小節頭(bar_start_times)もまとめる(先頭拍を1拍目と仮定・拍子検出はしない)。NumPy必須。読み取り専用。"""
    return track_beats(file_path, beats_per_bar=beats_per_bar)


@mcp.tool()
def analyze_audio_spectral(file_path: str, rolloff_percent: float = 0.85) -> dict[str, Any]:
    """WAV/AIFFを変更せず、音色のスペクトル特徴(セントロイド=明るさ・バンド幅・ロールオフ・フラットネス・
    ゼロ交差率・RMS)をオフライン抽出する。有音フレームで平均/標準偏差/最小/最大を集計。NumPy必須。読み取り専用。"""
    return extract_spectral_features(file_path, rolloff_percent=rolloff_percent)


@mcp.tool()
def analyze_audio_structure(file_path: str, window_seconds: float = 1.0) -> dict[str, Any]:
    """WAV/AIFFを変更せず、曲構造(セクション境界・秒)をオフライン推定する。クロマ自己相似行列＋Footeノベルティで
    境界を検出し、各セクションを和声の類似度でA/B/Cラベル付け(学習型ではない)。NumPy必須。読み取り専用。"""
    return segment_structure(file_path, window_seconds=window_seconds)


@mcp.tool()
def plan_midi_from_audio_melody(
    file_path: str,
    tempo: float,
    quantize: float = 0.0,
    min_f0: float = 65.0,
    max_f0: float = 1047.0,
) -> dict[str, Any]:
    """WAV/AIFFの単音メロディをYINで抽出し、指定tempo(BPM)でMIDIクリップ用のノート(拍単位)へ変換する計画を返す。
    quantizeは拍グリッド(例:0.25=1/16、0=なし)。読み取り専用。create前のレビュー用。NumPy必須。"""
    melody = extract_melody(file_path, min_f0=min_f0, max_f0=max_f0)
    return build_midi_from_melody(melody, tempo, quantize=quantize)


@mcp.tool()
def create_midi_from_audio_melody(
    file_path: str,
    track_index: int,
    clip_index: int,
    tempo: float,
    name: str = "Audio Melody",
    quantize: float = 0.0,
    min_f0: float = 65.0,
    max_f0: float = 1047.0,
) -> dict[str, Any]:
    """WAV/AIFFの単音メロディを抽出し、空のSessionスロットへ編集可能なMIDIクリップとして書き出す(オーディオ→MIDI)。
    既存クリップは上書きしない。まずplan_midi_from_audio_melodyで内容を確認すること。NumPy必須。"""
    melody = extract_melody(file_path, min_f0=min_f0, max_f0=max_f0)
    plan = build_midi_from_melody(melody, tempo, quantize=quantize)
    _validate_midi_clip(track_index, clip_index, plan["length_beats"], plan["notes"])
    result = bridge.call(
        "create_midi_clip",
        track_index=track_index,
        clip_index=clip_index,
        name=name[:200],
        length_beats=plan["length_beats"],
        notes=plan["notes"],
    )
    result["source"] = "audio_melody"
    result["note_count"] = plan["note_count"]
    return result


@mcp.tool()
def plan_live_instruments(
    genre: str = "pop",
    mood: str = "bright",
    roles: list[str] | None = None,
    live_edition: str = "unknown",
) -> dict[str, Any]:
    """Liveを変更せず、ジャンル、ムード、パート役割から純正インストゥルメント候補を選ぶ。"""
    return build_instrument_plan(genre, mood, roles, live_edition)


@mcp.tool()
def apply_live_instrument_selection(
    track_index: int,
    role: str,
    genre: str = "pop",
    mood: str = "bright",
    live_edition: str = "unknown",
    preferred_instrument: str = "",
    index: int = -1,
) -> dict[str, Any]:
    """確認済みのAI選択をMIDIトラックへ適用する。第一候補がなければ純正候補へフォールバックする。Live 12.3以降。"""
    if track_index < 0 or index < -1:
        raise ValueError("track_index must be non-negative and index must be -1 or non-negative")
    selection = build_role_selection(
        role, genre, mood, live_edition, preferred_instrument.strip()
    )
    applied = bridge.call(
        "insert_first_available_instrument",
        track_index=track_index,
        candidates=selection["candidates"],
        index=index,
    )
    return {
        "selection": selection,
        "applied": applied,
        "next_step": (
            selection["content_note"]
            or "再生して音域と音色を確認し、必要ならデバイスのパラメーターを調整してください。"
        ),
    }


@mcp.tool()
def create_track(track_type: str, name: str = "", index: int = -1) -> dict[str, Any]:
    """MIDIまたはaudioトラックを作成する。index=-1なら末尾、それ以外は0始まりの挿入位置。"""
    if track_type not in {"midi", "audio"}:
        raise ValueError("track_type must be 'midi' or 'audio'")
    if index < -1:
        raise ValueError("index must be -1 or non-negative")
    if len(name) > 200:
        raise ValueError("name must be 200 characters or fewer")
    return bridge.call("create_track", track_type=track_type, name=name, index=index)


@mcp.tool()
def create_midi_clip(
    track_index: int,
    clip_index: int,
    name: str,
    length_beats: float,
    notes: list[dict[str, Any]],
) -> dict[str, Any]:
    """空のSessionスロットへ編集可能なMIDIクリップとノートを作成する。"""
    _validate_midi_clip(track_index, clip_index, length_beats, notes)
    return bridge.call(
        "create_midi_clip",
        track_index=track_index,
        clip_index=clip_index,
        name=name[:200],
        length_beats=length_beats,
        notes=notes,
    )


@mcp.tool()
def plan_song_sketch(
    title: str,
    genre: str = "pop",
    mood: str = "bright",
    key: str = "C",
    mode: str = "major",
    tempo: float = 110,
    bars: int = 8,
) -> dict[str, Any]:
    """Liveを変更せず初心者向け構成案と純正音源候補を作る。genreは演奏語法、moodは進行と明暗を決める。"""
    return _attach_instrument_plan(
        build_song_plan(title, genre, mood, key, mode, tempo, bars)
    )


@mcp.tool()
def plan_pro_composition(
    title: str,
    progression: list[int] | None = None,
    genre: str = "pop",
    mood: str = "bright",
    key: str = "C",
    mode: str = "major",
    tempo: float = 110,
    bars: int = 8,
    chord_complexity: str = "seventh",
    harmonic_rhythm_beats: float = 4.0,
    melody_density: float = 0.7,
    swing: float = 0.0,
    humanize: float = 0.25,
    seed: int = 0,
) -> dict[str, Any]:
    """Liveを変更せず、進行・テンション・密度・グルーヴを指定した上級者向け構成案を作る。progressionは1〜7の度数列。"""
    plan = build_song_plan(
        title, genre, mood, key, mode, tempo, bars,
        progression=progression,
        chord_complexity=chord_complexity,
        harmonic_rhythm_beats=harmonic_rhythm_beats,
        melody_density=melody_density,
        swing=swing,
        humanize=humanize,
        seed=seed,
    )
    return _attach_instrument_plan(plan)


@mcp.tool()
def create_song_sketch(
    title: str,
    genre: str = "pop",
    mood: str = "bright",
    key: str = "C",
    mode: str = "major",
    tempo: float = 110,
    bars: int = 8,
    clip_index: int = 0,
) -> dict[str, Any]:
    """plan_song_sketchの確認後、4つのMIDIトラックと編集可能なSessionクリップをLiveへ作成する。"""
    if clip_index < 0:
        raise ValueError("clip_index must be non-negative")
    plan = build_song_plan(title, genre, mood, key, mode, tempo, bars)
    return _apply_song_plan(plan, clip_index)


@mcp.tool()
def create_pro_composition(
    title: str,
    progression: list[int] | None = None,
    genre: str = "pop",
    mood: str = "bright",
    key: str = "C",
    mode: str = "major",
    tempo: float = 110,
    bars: int = 8,
    chord_complexity: str = "seventh",
    harmonic_rhythm_beats: float = 4.0,
    melody_density: float = 0.7,
    swing: float = 0.0,
    humanize: float = 0.25,
    seed: int = 0,
    clip_index: int = 0,
) -> dict[str, Any]:
    """plan_pro_compositionの確認後、上級設定を反映した4パートをLiveへ作成する。"""
    if clip_index < 0:
        raise ValueError("clip_index must be non-negative")
    plan = build_song_plan(
        title, genre, mood, key, mode, tempo, bars,
        progression=progression,
        chord_complexity=chord_complexity,
        harmonic_rhythm_beats=harmonic_rhythm_beats,
        melody_density=melody_density,
        swing=swing,
        humanize=humanize,
        seed=seed,
    )
    return _apply_song_plan(plan, clip_index)


@mcp.tool()
def create_part_variation(
    track_index: int,
    clip_index: int,
    role: str,
    title: str,
    seed: int,
    progression: list[int] | None = None,
    genre: str = "pop",
    mood: str = "bright",
    key: str = "C",
    mode: str = "major",
    tempo: float = 110,
    bars: int = 8,
    chord_complexity: str = "seventh",
    harmonic_rhythm_beats: float = 4.0,
    melody_density: float = 0.7,
    swing: float = 0.0,
    humanize: float = 0.25,
) -> dict[str, Any]:
    """指定パートだけを別の空Sessionスロットへ生成し、seed違いの案をA/B比較できるようにする。roleはchords/bass/melody/drums。"""
    if track_index < 0 or clip_index < 0:
        raise ValueError("indices must be non-negative")
    if role not in {"chords", "bass", "melody", "drums"}:
        raise ValueError("unsupported role")
    plan = build_song_plan(
        title, genre, mood, key, mode, tempo, bars,
        progression=progression,
        chord_complexity=chord_complexity,
        harmonic_rhythm_beats=harmonic_rhythm_beats,
        melody_density=melody_density,
        swing=swing,
        humanize=humanize,
        seed=seed,
    )
    part = next(track for track in plan["tracks"] if track["role"] == role)
    return bridge.call(
        "create_midi_clip",
        track_index=track_index,
        clip_index=clip_index,
        name="%s - %s v%d" % (plan["title"], part["name"], seed),
        length_beats=part["length_beats"],
        notes=part["notes"],
    )


@mcp.tool()
def plan_ai_vocal(
    title: str,
    lyrics: str,
    genre: str = "pop",
    mood: str = "bright",
    key: str = "C",
    mode: str = "major",
    tempo: float = 110,
    bars: int = 8,
    melody_density: float = 0.7,
    seed: int = 0,
) -> dict[str, Any]:
    """Liveを変更せず、歌詞をMIDIメロディへ割り当てたAI歌声レンダリング用設計図を作る。"""
    return build_vocal_plan(
        title, lyrics, genre, mood, key, mode, tempo, bars, seed, melody_density
    )


@mcp.tool()
def create_vocal_guide(
    title: str,
    lyrics: str,
    genre: str = "pop",
    mood: str = "bright",
    key: str = "C",
    mode: str = "major",
    tempo: float = 110,
    bars: int = 8,
    melody_density: float = 0.7,
    seed: int = 0,
    clip_index: int = 0,
) -> dict[str, Any]:
    """歌声エンジンへ渡すためのVocal Guide MIDIトラックを作り、歌詞とノートの対応を返す。"""
    if clip_index < 0:
        raise ValueError("clip_index must be non-negative")
    plan = build_vocal_plan(
        title, lyrics, genre, mood, key, mode, tempo, bars, seed, melody_density
    )
    state = bridge.call("get_state")
    track_index = len(state["tracks"])
    bridge.call("set_tempo", bpm=tempo)
    bridge.call("create_track", track_type="midi", name="Vocal Guide", index=-1)
    clip = bridge.call(
        "create_midi_clip",
        track_index=track_index,
        clip_index=clip_index,
        name="%s - Vocal Guide" % plan["title"],
        length_beats=float(bars * 4),
        notes=plan["midi_notes"],
    )
    return {
        "track_index": track_index,
        "clip": clip,
        "vocal_events": plan["vocal_events"],
        "render_contract": plan["render_contract"],
        "next_step": "歌声エンジンでドライWAVを書き出し、import_vocal_takeでLiveへ戻してください。",
    }


@mcp.tool()
def import_vocal_take(
    file_path: str,
    track_name: str = "AI Vocal",
    clip_name: str = "AI Vocal Take",
    clip_index: int = 0,
) -> dict[str, Any]:
    """歌声エンジンがレンダリングしたローカル音声を、新規AudioトラックのSessionスロットへ取り込む。"""
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("vocal audio file does not exist")
    if path.suffix.lower() not in {".wav", ".aif", ".aiff", ".flac", ".mp3"}:
        raise ValueError("unsupported vocal audio format")
    if clip_index < 0:
        raise ValueError("clip_index must be non-negative")
    state = bridge.call("get_state")
    track_index = len(state["tracks"])
    bridge.call("create_track", track_type="audio", name=track_name[:200], index=-1)
    result = bridge.call(
        "import_audio_clip",
        track_index=track_index,
        clip_index=clip_index,
        file_path=str(path),
        name=clip_name[:200],
    )
    return {"track_index": track_index, **result}


def _apply_song_plan(plan: dict[str, Any], clip_index: int) -> dict[str, Any]:
    state = bridge.call("get_state")
    first_track_index = len(state["tracks"])
    bridge.call("set_tempo", bpm=plan["tempo"])
    created = []
    for offset, track_plan in enumerate(plan["tracks"]):
        track_index = first_track_index + offset
        bridge.call("create_track", track_type="midi", name=track_plan["name"], index=-1)
        clip = bridge.call(
            "create_midi_clip",
            track_index=track_index,
            clip_index=clip_index,
            name="%s - %s" % (plan["title"], track_plan["name"]),
            length_beats=track_plan["length_beats"],
            notes=track_plan["notes"],
        )
        created.append({"track_index": track_index, **clip})
    return {
        "title": plan["title"],
        "tempo": plan["tempo"],
        "key": "%s %s" % (plan["key"], plan["mode"]),
        "bars": plan["bars"],
        "professional_settings": plan["professional_settings"],
        "created": created,
        "instrument_plan": build_instrument_plan(
            plan["genre"], plan["mood"], [track["role"] for track in plan["tracks"]]
        ),
        "next_step": "AIの純正音源候補を確認し、apply_live_instrument_selectionで各トラックへ1つずつ適用してください。",
    }


def _attach_instrument_plan(plan: dict[str, Any]) -> dict[str, Any]:
    plan["instrument_plan"] = build_instrument_plan(
        plan["genre"], plan["mood"], [track["role"] for track in plan["tracks"]]
    )
    return plan


@mcp.tool()
def get_track_devices(track_index: int) -> dict[str, Any]:
    """トラック上のデバイスと、操作可能な全パラメーターの現在値・範囲を取得する。"""
    if track_index < 0:
        raise ValueError("track_index must be non-negative")
    return bridge.call("get_track_devices", track_index=track_index)


#: Top-level Live browser roots that :func:`browse_device_presets` may enumerate. Each maps
#: to a ``BrowserItem`` on ``Application.browser``. Browsing is strictly read-only.
_BROWSER_CATEGORIES = (
    "instruments",
    "sounds",
    "drums",
    "audio_effects",
    "midi_effects",
    "samples",
    "plugins",
    "max_for_live",
    "packs",
    "user_library",
)


@mcp.tool()
def browse_device_presets(
    category: str,
    path: list[str] | None = None,
    max_items: int = 200,
) -> dict[str, Any]:
    """Liveブラウザの内容を読み取り専用で列挙する。categoryはinstruments/sounds/drums/
    audio_effects/midi_effects/samples/plugins/max_for_live/packs/user_libraryのいずれか。
    pathでフォルダを1階層ずつ辿る。各項目はname/is_folder/is_loadable/is_device/uri/sourceを返す。
    プリセットのロードや挿入は一切行わない。"""
    if category not in _BROWSER_CATEGORIES:
        raise ValueError("category must be one of: %s" % ", ".join(_BROWSER_CATEGORIES))
    if path is not None and (
        not isinstance(path, list) or any(not isinstance(segment, str) for segment in path)
    ):
        raise ValueError("path must be a list of folder-name strings")
    if not 1 <= max_items <= 1000:
        raise ValueError("max_items must be between 1 and 1000")
    return bridge.call(
        "browse_presets",
        category=category,
        path=list(path or []),
        max_items=max_items,
    )


@mcp.tool()
def load_browser_preset(
    track_index: int,
    category: str,
    name: str,
    path: list[str] | None = None,
) -> dict[str, Any]:
    """browse_device_presetsで見つけたプリセット／キットを、指定トラックへLiveブラウザからロードするMutation。
    categoryとpath（フォルダ名列）で場所を特定し、そのフォルダ直下のnameという読み込み可能項目をロードする。
    安全のため、既にインストゥルメントを持つトラックへのロードは拒否する（既存楽器を置き換えない・追加のみ）。
    1回1トラック。まずbrowse_device_presetsでname/pathを確認すること。"""
    if track_index < 0:
        raise ValueError("track_index must be non-negative")
    if category not in _BROWSER_CATEGORIES:
        raise ValueError("category must be one of: %s" % ", ".join(_BROWSER_CATEGORIES))
    if not name.strip() or len(name) > 300:
        raise ValueError("name must contain 1 to 300 characters")
    if path is not None and (
        not isinstance(path, list) or any(not isinstance(segment, str) for segment in path)
    ):
        raise ValueError("path must be a list of folder-name strings")
    return bridge.call(
        "load_preset",
        track_index=track_index,
        category=category,
        path=list(path or []),
        name=name.strip(),
    )


@mcp.tool()
def add_native_device(track_index: int, device_name: str, index: int = -1) -> dict[str, Any]:
    """Live 12.3以降で、名前を指定して純正Liveデバイスをトラックへ挿入する。index=-1なら末尾。"""
    if track_index < 0 or index < -1:
        raise ValueError("track_index must be non-negative and index must be -1 or non-negative")
    if not device_name.strip() or len(device_name) > 200:
        raise ValueError("device_name must contain 1 to 200 characters")
    return bridge.call(
        "add_native_device",
        track_index=track_index,
        device_name=device_name.strip(),
        index=index,
    )


@mcp.tool()
def set_device_power(track_index: int, device_index: int, enabled: bool) -> dict[str, Any]:
    """トラック上のデバイスをオンまたはオフにする。"""
    if track_index < 0 or device_index < 0:
        raise ValueError("indices must be non-negative")
    return bridge.call(
        "set_device_power",
        track_index=track_index,
        device_index=device_index,
        enabled=enabled,
    )


@mcp.tool()
def set_device_parameter(
    track_index: int,
    device_index: int,
    parameter_index: int,
    value: float,
    normalized: bool = False,
) -> dict[str, Any]:
    """エフェクトのパラメーターを設定する。normalized=trueならvalueは0.0〜1.0。先にget_track_devicesで範囲を確認する。"""
    if track_index < 0 or device_index < 0 or parameter_index < 0:
        raise ValueError("indices must be non-negative")
    if normalized and not 0 <= value <= 1:
        raise ValueError("normalized value must be between 0 and 1")
    return bridge.call(
        "set_device_parameter",
        track_index=track_index,
        device_index=device_index,
        parameter_index=parameter_index,
        value=value,
        normalized=normalized,
    )


@mcp.tool()
def reset_device_parameter(
    track_index: int, device_index: int, parameter_index: int
) -> dict[str, Any]:
    """連続値パラメーターをAbleton Liveが示す既定値へ戻す。"""
    if track_index < 0 or device_index < 0 or parameter_index < 0:
        raise ValueError("indices must be non-negative")
    return bridge.call(
        "reset_device_parameter",
        track_index=track_index,
        device_index=device_index,
        parameter_index=parameter_index,
    )


@mcp.tool()
def set_transport(action: str) -> dict[str, Any]:
    """トランスポートを操作する。actionは play または stop のみ。"""
    if action not in {"play", "stop"}:
        raise ValueError("action must be 'play' or 'stop'")
    return bridge.call("set_transport", action=action)


@mcp.tool()
def set_tempo(bpm: float) -> dict[str, Any]:
    """テンポを20〜999 BPMの範囲で設定する。"""
    if not 20 <= bpm <= 999:
        raise ValueError("bpm must be between 20 and 999")
    return bridge.call("set_tempo", bpm=bpm)


@mcp.tool()
def set_track_volume(track_index: int, volume: float) -> dict[str, Any]:
    """0始まりのトラック番号を指定し、音量を0.0〜1.0で設定する。"""
    if track_index < 0 or not 0 <= volume <= 1:
        raise ValueError("invalid track_index or volume")
    return bridge.call("set_track_volume", track_index=track_index, volume=volume)


@mcp.tool()
def set_track_pan(track_index: int, pan: float) -> dict[str, Any]:
    """0始まりのトラック番号を指定し、パンを-1.0（左）〜1.0（右）で設定する。"""
    if track_index < 0 or not -1 <= pan <= 1:
        raise ValueError("invalid track_index or pan")
    return bridge.call("set_track_pan", track_index=track_index, pan=pan)


@mcp.tool()
def set_track_mute(track_index: int, muted: bool) -> dict[str, Any]:
    """トラックのMuteを切り替える。"""
    if track_index < 0:
        raise ValueError("track_index must be non-negative")
    return bridge.call("set_track_mute", track_index=track_index, muted=muted)


@mcp.tool()
def set_track_solo(track_index: int, soloed: bool) -> dict[str, Any]:
    """トラックのSoloを切り替える。"""
    if track_index < 0:
        raise ValueError("track_index must be non-negative")
    return bridge.call("set_track_solo", track_index=track_index, soloed=soloed)


@mcp.tool()
def set_track_arm(track_index: int, armed: bool) -> dict[str, Any]:
    """0始まりのトラック番号を指定し、録音待機を切り替える。"""
    if track_index < 0:
        raise ValueError("track_index must be non-negative")
    return bridge.call("set_track_arm", track_index=track_index, armed=armed)


@mcp.tool()
def stop_track_clips(track_index: int) -> dict[str, Any]:
    """指定トラックで再生中または起動待ちのSessionクリップを停止する。"""
    if track_index < 0:
        raise ValueError("track_index must be non-negative")
    return bridge.call("stop_track_clips", track_index=track_index)


@mcp.tool()
def fire_clip(track_index: int, clip_index: int) -> dict[str, Any]:
    """0始まりのトラック番号とSessionクリップスロット番号を指定してクリップを起動する。"""
    if track_index < 0 or clip_index < 0:
        raise ValueError("indices must be non-negative")
    return bridge.call("fire_clip", track_index=track_index, clip_index=clip_index)


@mcp.tool()
def fire_clip_group(track_indices: list[int], clip_index: int) -> dict[str, Any]:
    """複数トラックの同じSessionスロットを1リクエストで検証・同期起動する。"""
    if clip_index < 0:
        raise ValueError("clip_index must be non-negative")
    if not track_indices or len(track_indices) > 256:
        raise ValueError("track_indices must contain between 1 and 256 entries")
    if any(index < 0 for index in track_indices):
        raise ValueError("track indices must be non-negative")
    if len(set(track_indices)) != len(track_indices):
        raise ValueError("track_indices must not contain duplicates")
    return bridge.call(
        "fire_clip_group",
        track_indices=track_indices,
        clip_index=clip_index,
    )


@mcp.tool()
def duplicate_clip_to_slot(
    track_index: int,
    source_clip_index: int,
    destination_clip_index: int,
    name: str = "",
) -> dict[str, Any]:
    """MIDIまたはaudioのSessionクリップを空きスロットへ複製する。既存クリップは上書きしない。"""
    if track_index < 0 or source_clip_index < 0 or destination_clip_index < 0:
        raise ValueError("indices must be non-negative")
    if source_clip_index == destination_clip_index:
        raise ValueError("source and destination clip indices must differ")
    if len(name) > 200:
        raise ValueError("name must be 200 characters or fewer")
    return bridge.call(
        "duplicate_clip_to_slot",
        track_index=track_index,
        source_clip_index=source_clip_index,
        destination_clip_index=destination_clip_index,
        name=name,
    )


@mcp.tool()
def fire_scene(scene_index: int) -> dict[str, Any]:
    """指定Sceneを1回だけ発火し、MIDIとaudioを含む全スロットを同期起動する。"""
    if scene_index < 0:
        raise ValueError("scene_index must be non-negative")
    return bridge.call("fire_scene", scene_index=scene_index)


@mcp.tool()
def copy_session_clip_to_arrangement(
    track_index: int,
    clip_index: int,
    destination_time_beats: float,
    name: str = "",
) -> dict[str, Any]:
    """SessionクリップをArrangementの指定拍へ複製する。既存クリップとの重複は拒否する。"""
    if track_index < 0 or clip_index < 0:
        raise ValueError("indices must be non-negative")
    if not 0 <= destination_time_beats <= 1576800:
        raise ValueError("destination_time_beats is outside Live's supported range")
    if len(name) > 200:
        raise ValueError("name must be 200 characters or fewer")
    return bridge.call(
        "copy_session_clip_to_arrangement",
        track_index=track_index,
        clip_index=clip_index,
        destination_time_beats=destination_time_beats,
        name=name,
    )


@mcp.tool()
def copy_scene_to_arrangement(
    scene_index: int,
    destination_time_beats: float,
    track_indices: list[int] | None = None,
) -> dict[str, Any]:
    """Scene内のMIDI/audioクリップを同じ開始拍でArrangementへ一括複製する。重複時は全体を拒否する。"""
    if scene_index < 0:
        raise ValueError("scene_index must be non-negative")
    if not 0 <= destination_time_beats <= 1576800:
        raise ValueError("destination_time_beats is outside Live's supported range")
    if track_indices is not None:
        if not track_indices or len(track_indices) > 256:
            raise ValueError("track_indices must contain between 1 and 256 entries")
        if any(index < 0 for index in track_indices):
            raise ValueError("track indices must be non-negative")
        if len(set(track_indices)) != len(track_indices):
            raise ValueError("track_indices must not contain duplicates")
    return bridge.call(
        "copy_scene_to_arrangement",
        scene_index=scene_index,
        destination_time_beats=destination_time_beats,
        track_indices=track_indices,
    )


def _validate_midi_clip(
    track_index: int,
    clip_index: int,
    length_beats: float,
    notes: list[dict[str, Any]],
) -> None:
    if track_index < 0 or clip_index < 0:
        raise ValueError("indices must be non-negative")
    if not 0 < length_beats <= 4096:
        raise ValueError("length_beats must be between 0 and 4096")
    if len(notes) > 4096:
        raise ValueError("a clip may contain at most 4096 notes per request")
    for midi_note in notes:
        pitch = int(midi_note["pitch"])
        start = float(midi_note["start_time"])
        duration = float(midi_note["duration"])
        velocity = float(midi_note.get("velocity", 100))
        if not 0 <= pitch <= 127:
            raise ValueError("note pitch must be between 0 and 127")
        if start < 0 or start >= length_beats or duration <= 0:
            raise ValueError("note timing is outside the clip")
        if not 0 <= velocity <= 127:
            raise ValueError("note velocity must be between 0 and 127")


def _read_midi_clip(track_index: int, clip_index: int) -> dict[str, Any]:
    if track_index < 0 or clip_index < 0:
        raise ValueError("indices must be non-negative")
    return bridge.call(
        "get_midi_clip_notes",
        track_index=track_index,
        clip_index=clip_index,
    )


def main() -> None:
    transport = os.getenv("ABLETONGPT_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
