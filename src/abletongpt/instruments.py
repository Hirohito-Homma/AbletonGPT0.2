from __future__ import annotations

from typing import Any

from .composition import GENRE_PROFILES, MOOD_PROGRESSIONS


INSTRUMENTS: dict[str, dict[str, Any]] = {
    "Drift": {
        "family": "analog_synth",
        "character": "素早く音作りできる、温かく現代的なアナログ系シンセ",
        "roles": {"chords", "bass", "melody", "lead", "pad", "keys", "pluck"},
        "core_fallback": True,
        "requires_content": False,
    },
    "Wavetable": {
        "family": "wavetable_synth",
        "character": "明るいデジタル音から動きのあるパッド、リードまで対応",
        "roles": {"chords", "bass", "melody", "lead", "pad", "pluck"},
        "core_fallback": False,
        "requires_content": False,
    },
    "Operator": {
        "family": "fm_synth",
        "character": "輪郭のあるベース、ベル、プラックに強いFMシンセ",
        "roles": {"chords", "bass", "melody", "lead", "keys", "pluck"},
        "core_fallback": False,
        "requires_content": False,
    },
    "Analog": {
        "family": "analog_synth",
        "character": "クラシックなベース、パッド、コードに向くアナログ系シンセ",
        "roles": {"chords", "bass", "melody", "lead", "pad", "keys"},
        "core_fallback": False,
        "requires_content": False,
    },
    "Meld": {
        "family": "macro_oscillator_synth",
        "character": "複雑な質感、モーション、実験的な音色に向くシンセ",
        "roles": {"chords", "bass", "melody", "lead", "pad", "pluck"},
        "core_fallback": False,
        "requires_content": False,
    },
    "Electric": {
        "family": "electric_piano",
        "character": "R&B、Jazz、Lo-fiのコードに合うエレクトリックピアノ",
        "roles": {"chords", "melody", "keys"},
        "core_fallback": False,
        "requires_content": False,
    },
    "Tension": {
        "family": "physical_modeling_strings",
        "character": "弦のアタックと有機的な響きを作れる物理モデリング音源",
        "roles": {"chords", "bass", "melody", "lead", "pluck"},
        "core_fallback": False,
        "requires_content": False,
    },
    "Collision": {
        "family": "physical_modeling_mallet",
        "character": "マレット、ベル、パーカッシブな旋律に向く物理モデリング音源",
        "roles": {"chords", "melody", "keys", "pluck"},
        "core_fallback": False,
        "requires_content": False,
    },
    "Drum Rack": {
        "family": "drum_sampler",
        "character": "キット、サンプル、Drum Synthをまとめる標準ドラム環境",
        "roles": {"drums"},
        "core_fallback": True,
        "requires_content": True,
    },
    "Impulse": {
        "family": "drum_sampler",
        "character": "8スロットで素早く組めるシンプルなドラムサンプラー",
        "roles": {"drums"},
        "core_fallback": True,
        "requires_content": True,
    },
}

SUPPORTED_ROLES = {"chords", "bass", "melody", "lead", "pad", "keys", "pluck", "drums"}
LIVE_EDITIONS = {"unknown", "intro", "standard", "suite"}


_ROLE_ALIASES = {
    "lead": "melody",
    "pad": "chords",
    "keys": "chords",
    "pluck": "melody",
}


_GENRE_CHOICES: dict[str, dict[str, list[str]]] = {
    "chords": {
        "pop": ["Wavetable", "Drift", "Analog", "Electric"],
        "rock": ["Drift", "Analog", "Electric", "Tension"],
        "edm": ["Wavetable", "Meld", "Operator", "Drift"],
        "hiphop": ["Electric", "Drift", "Wavetable", "Operator"],
        "rnb": ["Electric", "Analog", "Wavetable", "Drift"],
        "jazz": ["Electric", "Tension", "Collision", "Drift"],
        "lofi": ["Electric", "Analog", "Drift", "Wavetable"],
    },
    "bass": {
        "pop": ["Drift", "Operator", "Analog", "Wavetable"],
        "rock": ["Drift", "Analog", "Tension", "Operator"],
        "edm": ["Operator", "Wavetable", "Meld", "Drift"],
        "hiphop": ["Operator", "Drift", "Wavetable", "Analog"],
        "rnb": ["Operator", "Analog", "Drift", "Wavetable"],
        "jazz": ["Tension", "Analog", "Operator", "Drift"],
        "lofi": ["Analog", "Drift", "Operator", "Wavetable"],
    },
    "melody": {
        "pop": ["Wavetable", "Drift", "Meld", "Electric"],
        "rock": ["Drift", "Tension", "Analog", "Wavetable"],
        "edm": ["Wavetable", "Meld", "Operator", "Drift"],
        "hiphop": ["Operator", "Wavetable", "Electric", "Drift"],
        "rnb": ["Electric", "Wavetable", "Operator", "Drift"],
        "jazz": ["Electric", "Collision", "Tension", "Drift"],
        "lofi": ["Electric", "Collision", "Drift", "Analog"],
    },
    "drums": {
        genre: ["Drum Rack", "Impulse"] for genre in GENRE_PROFILES
    },
}


_MOOD_PREFERENCES = {
    "bright": ["Wavetable", "Drift", "Electric", "Collision"],
    "uplifting": ["Wavetable", "Meld", "Drift", "Electric"],
    "chill": ["Electric", "Analog", "Drift", "Collision"],
    "dark": ["Operator", "Meld", "Analog", "Wavetable"],
    "bittersweet": ["Electric", "Tension", "Analog", "Drift"],
    "tense": ["Meld", "Operator", "Wavetable", "Tension"],
}


_ROLE_NAMES_JA = {
    "chords": "コード",
    "bass": "ベース",
    "melody": "メロディ",
    "lead": "リード",
    "pad": "パッド",
    "keys": "鍵盤",
    "pluck": "プラック",
    "drums": "ドラム",
}


def build_instrument_plan(
    genre: str,
    mood: str,
    roles: list[str] | None = None,
    live_edition: str = "unknown",
) -> dict[str, Any]:
    """Build an edition-aware, deterministic native-instrument plan."""
    if genre not in GENRE_PROFILES:
        raise ValueError("unsupported genre")
    if mood not in MOOD_PROGRESSIONS:
        raise ValueError("unsupported mood")
    if live_edition not in LIVE_EDITIONS:
        raise ValueError("live_edition must be unknown, intro, standard, or suite")
    selected_roles = roles or ["chords", "bass", "melody", "drums"]
    if not selected_roles or len(selected_roles) > 16:
        raise ValueError("roles must contain between 1 and 16 entries")
    if any(role not in SUPPORTED_ROLES for role in selected_roles):
        raise ValueError("unsupported instrument role")

    selections = [
        _build_role_selection(role, genre, mood, live_edition)
        for role in selected_roles
    ]
    edition_note = (
        "Liveのエディションが不明なため、実際にインストール済みの候補からフォールバックします。"
        if live_edition == "unknown"
        else "%sエディションを優先条件に使いますが、Packや個別購入による差はLive側で確認します。"
        % live_edition.capitalize()
    )
    return {
        "genre": genre,
        "mood": mood,
        "live_edition": live_edition,
        "selections": selections,
        "selection_policy": [
            "ジャンルで音源の基本的な演奏語法を選びます。",
            "ムードで音色の明暗、質感、アタックの方向を補正します。",
            "Intro/Standardでは導入可能性の高いコア候補を優先します。",
            "第一候補を挿入できない場合は、候補順に次の純正音源を試します。",
        ],
        "edition_note": edition_note,
        "apply_contract": {
            "tool": "apply_live_instrument_selection",
            "requires_confirmation": True,
            "minimum_live_version": "12.3",
            "one_track_per_call": True,
            "deletes_or_replaces_existing_instrument": False,
        },
    }


def build_role_selection(
    role: str,
    genre: str,
    mood: str,
    live_edition: str = "unknown",
    preferred_instrument: str = "",
) -> dict[str, Any]:
    plan = build_instrument_plan(genre, mood, [role], live_edition)
    selection = plan["selections"][0]
    if preferred_instrument:
        if preferred_instrument not in INSTRUMENTS:
            raise ValueError("preferred_instrument is not an allowed native instrument")
        if role not in INSTRUMENTS[preferred_instrument]["roles"]:
            raise ValueError("preferred_instrument does not support this role")
        candidates = [preferred_instrument] + [
            name for name in selection["candidates"] if name != preferred_instrument
        ]
        selection = dict(selection)
        selection["selected_instrument"] = preferred_instrument
        selection["candidates"] = candidates
        selection["reason"] = (
            "ユーザー指定の%sを第一候補にし、利用できない場合はAI候補へフォールバックします。"
            % preferred_instrument
        )
        selection["instrument"] = _instrument_summary(preferred_instrument)
    return selection


def _build_role_selection(
    role: str,
    genre: str,
    mood: str,
    live_edition: str,
) -> dict[str, Any]:
    base_role = _ROLE_ALIASES.get(role, role)
    base = list(_GENRE_CHOICES[base_role][genre])
    mood_preferences = _MOOD_PREFERENCES[mood]
    scores: dict[str, float] = {}
    for position, name in enumerate(base):
        scores[name] = 100.0 - position * 10.0
    for position, name in enumerate(mood_preferences):
        if name in scores:
            scores[name] += 12.0 - position * 2.0
    if live_edition in {"intro", "standard"}:
        for name in scores:
            if INSTRUMENTS[name]["core_fallback"]:
                scores[name] += 35.0
    ordered = sorted(base, key=lambda name: (-scores[name], base.index(name)))
    if role != "drums" and "Drift" not in ordered:
        ordered.append("Drift")
    candidates = ordered[:5]
    selected = candidates[0]
    profile = INSTRUMENTS[selected]
    role_name = _ROLE_NAMES_JA[role]
    reason = (
        "%sの%sパートに対して、%sの演奏語法と%sの質感を両立しやすいため%sを選択しました。"
        % (genre, role_name, genre, mood, selected)
    )
    content_note = None
    if profile["requires_content"]:
        content_note = (
            "デバイス挿入後にキットまたはサンプルの読み込みが必要です。"
            "現在の自動挿入だけではドラム音は確定しません。"
        )
    return {
        "role": role,
        "role_name_ja": role_name,
        "selected_instrument": selected,
        "candidates": candidates,
        "reason": reason,
        "instrument": _instrument_summary(selected),
        "requires_content": bool(profile["requires_content"]),
        "content_note": content_note,
    }


def _instrument_summary(name: str) -> dict[str, Any]:
    profile = INSTRUMENTS[name]
    return {
        "name": name,
        "family": profile["family"],
        "character": profile["character"],
        "availability": (
            "core_candidate" if profile["core_fallback"] else "check_live_edition_and_installation"
        ),
    }
