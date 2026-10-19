from types import SimpleNamespace
from pathlib import Path
from test_knowledge import client, login
from navigator import speech


def test_speech_requires_membership_and_explicit_local_configuration(client, monkeypatch):
    assert client.get('/speech/capabilities').status_code == 403
    login(client)
    monkeypatch.delenv('SPEECH_PIPER_PYTHON', raising=False)
    assert client.get('/speech/capabilities').json()['available'] is False
    assert client.post('/speech/synthesize', json={'text': 'Hello', 'language': 'en'}).status_code == 503


def test_speech_passes_the_displayed_text_to_local_engine(client, monkeypatch, tmp_path):
    login(client)
    executable = tmp_path / 'python.exe'; executable.touch()
    model = tmp_path / 'voice.onnx'; model.touch()
    monkeypatch.setenv('SPEECH_PIPER_PYTHON', str(executable))
    monkeypatch.setenv('SPEECH_MODEL_FR', str(model))
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        Path(args[-1]).write_bytes(b'RIFF' + b'\0' * 40)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(speech.subprocess, 'run', run)
    text = 'Une plateforme pour les complémentarités à Berne.'
    response = client.post('/speech/synthesize', json={'text': text, 'language': 'fr'})
    assert response.status_code == 200 and response.headers['content-type'] == 'audio/wav'
    assert response.headers['cache-control'] == 'no-store'
    assert calls[0][1]['input'] == text
    assert calls[0][0][:3] == [str(executable), '-m', 'piper']
    assert 'shell' not in calls[0][1]
