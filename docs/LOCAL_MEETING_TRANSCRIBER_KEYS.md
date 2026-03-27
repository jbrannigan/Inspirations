# Meeting Transcriber Keys (Local)

Single source of truth for local meeting-transcription credentials used by tools in this project.

## Stable macOS Keychain service names

Keep these service names stable:

1. `openai_api_key`
2. `huggingface_api_token`

## What each key is for

- `openai_api_key`
  Used for the current cloud transcription workflow in [meeting_transcriber_gui.py](/Users/minime/Projects/Inspirations/tools/meeting_transcriber_gui.py): OpenAI transcription, diarization, and summary generation.

- `huggingface_api_token`
  Used for the local `WhisperX + pyannote` diarization workflow in [meeting_transcriber_gui.py](/Users/minime/Projects/Inspirations/tools/meeting_transcriber_gui.py). This token must have read access and the account must accept the gated model terms for `pyannote/speaker-diarization-community-1`.

## Current resolution behavior

Today, [meeting_transcriber_gui.py](/Users/minime/Projects/Inspirations/tools/meeting_transcriber_gui.py) resolves the OpenAI key in this order:

1. Environment variable: `OPENAI_API_KEY`
2. macOS Keychain generic password service: `openai_api_key`

For local WhisperX diarization, it resolves the Hugging Face token in this order:

1. Environment variable: `HF_TOKEN`
2. Environment variable: `HUGGINGFACE_TOKEN`
3. macOS Keychain generic password service: `huggingface_api_token`

## Local runtime path

The current local diarization setup on this machine uses:

1. Homebrew Python: `/opt/homebrew/bin/python3.11`
2. Virtualenv: `~/.venvs/whisperx`
3. WhisperX entrypoint: `~/.venvs/whisperx/bin/python -m whisperx`

## Verify keys exist in Keychain

```bash
security find-generic-password -s openai_api_key >/dev/null && echo "openai: found"
security find-generic-password -s huggingface_api_token >/dev/null && echo "huggingface: found"
```

## Add or update keys in Keychain

### OpenAI

```bash
security add-generic-password -U \
  -a "$USER" \
  -s openai_api_key \
  -w 'sk-proj-REPLACE_WITH_REAL_KEY'
```

### Hugging Face

```bash
security add-generic-password -U \
  -a "$USER" \
  -s huggingface_api_token \
  -w 'hf_REPLACE_WITH_REAL_TOKEN'
```

## Hugging Face prerequisites for local diarization

Before using `WhisperX + pyannote`, do both:

1. Create a Hugging Face access token with read access.
2. Accept the model terms on [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1).

If the terms are not accepted, the usual failure mode is `401` or `403` even when the token is valid.

## Notes

- Do not commit real API keys to git.
- Prefer Keychain for local persistence; use env vars only for temporary shell overrides.
- Keep service names stable so scripts and future tooling can depend on them without per-machine edits.

## Speaker reference clips for cloud identification

Cloud transcription in [meeting_transcriber_gui.py](/Users/minime/Projects/Inspirations/tools/meeting_transcriber_gui.py) can auto-match stored voice samples to names entered in `Known participants`.

Stable local path:

- `/Users/minime/Projects/Inspirations/data/speaker_references/`

Current convention:

- one subfolder per person, for example:
  - `/Users/minime/Projects/Inspirations/data/speaker_references/jim/`
  - `/Users/minime/Projects/Inspirations/data/speaker_references/leslie/`
- place one or more short audio clips in that folder

Recommended clip shape:

- `2` to `10` seconds
- one speaker only
- no overlapping voices
- normal speaking voice

Current upload behavior:

- the cloud path auto-transcodes matched reference clips to short mono `m4a` files before sending them to OpenAI
- this keeps each reference part under the API size limit

Current matching behavior:

- the cloud path looks at the names entered in `Known participants`
- it tries to match each participant against folder names and file names in `data/speaker_references/`
- it uses up to `4` matched reference clips per OpenAI transcription request

Current local examples:

- [jim-voice-sample.wav](/Users/minime/Projects/Inspirations/data/speaker_references/jim/jim-voice-sample.wav)
- [leslie-voice-sample.2.wav](/Users/minime/Projects/Inspirations/data/speaker_references/leslie/leslie-voice-sample.2.wav)
