# Roadmap

## Implemented in 0.2

- MCP/localhost Remote Script bridge with shared-token support
- Beginner and professional deterministic MIDI composition
- Chords, bass, melody, drums, part variations and editable Session clips
- Existing MIDI clip analysis and complementary chords/bass/pad/melody/countermelody/drums
- Track, transport and basic mixer control
- Collision-safe Session clip and Scene copy to Arrangement View
- Native Live device insertion on Live 12.3+
- Role/genre/mood/edition-aware native-instrument selection with safe fallback
- Existing device inspection and parameter control
- AI vocal guide planning and rendered-audio import
- Offline WAV/AIFF analysis for Integrated/Momentary/Short-term LUFS, LRA, peak, RMS and crest factor
- macOS setup, diagnostics, MCP configuration examples and automated checks

## Next: arrangement and production

- Intro / verse / pre-chorus / chorus / bridge section graph
- Reusable song-form templates for Arrangement View
- Preset, Pack and kit browsing with exact installed-content availability
- Audio-track key, tempo, chord and melody extraction for contextual composition
- Clip automation, probability and expressive MIDI editing (expression engine and plan_expression / apply_expression landed: accent / swing / humanize / weak-beat probability are planned and applied to clip notes; MIDI CC automation is planned but not yet written back to Live)
- Non-destructive project snapshots and rollback bundles

## Next: mix intelligence

- Multi-file bounced-stem analysis and certified true-peak backend integration
- Spectrum, masking, phase correlation and stereo-width analysis
- Reference-track comparison
- Mix proposal diff, explicit approval, batch apply and rollback
- Gain staging, routing, return effects and automation workflows

The current Live meter snapshot is not a replacement for the implemented offline audio analysis.

## Next: trackdown and mastering

- Validated export manifests for stems, sample rate, bit depth, dither and tails
- Export completion verification and naming conventions
- Mastering target profiles and loudness-matched A/B versions
- Platform delivery checks without blindly forcing a single LUFS target

Export and mastering remain manual until a reliable, inspectable and reversible workflow is implemented.

## Next: AI vocals

- Provider adapter interface for licensed singing engines
- Phoneme timing and language-specific lyric segmentation
- Harmony and double generation
- Vocal comping, breath/noise management and vocal-chain proposals
- Consent provenance for custom or cloned voice models
