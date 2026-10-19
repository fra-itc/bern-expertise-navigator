"""Local, optional Piper narration. No browser/cloud speech service."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .knowledge_access import require_member

router = APIRouter()
_slot = threading.BoundedSemaphore(1)


def configuration():
    python = os.getenv('SPEECH_PIPER_PYTHON', '')
    voices = {lang: os.getenv('SPEECH_MODEL_' + lang.upper(), '') for lang in ('en', 'de', 'fr')}
    return python, {lang: model for lang, model in voices.items() if model and Path(model).is_file()}


@router.get('/speech/capabilities')
def capabilities(user=Depends(require_member)):
    python, voices = configuration()
    available = bool(python and Path(python).is_file() and voices)
    return {'available': available, 'languages': sorted(voices) if available else [], 'engine': 'piper'}


class SpeechInput(BaseModel):
    text: str = Field(min_length=1, max_length=3500)
    language: Literal['en', 'de', 'fr']


@router.post('/speech/synthesize')
def synthesize(body: SpeechInput, user=Depends(require_member)):
    python, voices = configuration()
    if not python or not Path(python).is_file() or body.language not in voices:
        raise HTTPException(503, 'Local narration is not configured for this language.')
    if not body.text.strip():
        raise HTTPException(422, 'Text is required.')
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, 'Narration is busy. Please try again shortly.')
    try:
        with tempfile.TemporaryDirectory(prefix='bern-narration-') as folder:
            output = Path(folder) / 'speech.wav'
            result = subprocess.run([python, '-m', 'piper', '--model', voices[body.language], '--output-file', str(output)],
                                    input=body.text, encoding='utf-8', capture_output=True, timeout=60,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode or not output.is_file():
                raise HTTPException(503, 'Local narration is temporarily unavailable.')
            audio = output.read_bytes()
            if not audio.startswith(b'RIFF'):
                raise HTTPException(503, 'Local narration returned an invalid audio file.')
            return Response(audio, media_type='audio/wav', headers={'Cache-Control': 'no-store'})
    except (OSError, subprocess.TimeoutExpired):
        raise HTTPException(503, 'Local narration is temporarily unavailable.') from None
    finally:
        _slot.release()
