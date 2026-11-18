import base64
import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('FACE_SERVICE_KEY', 's' * 32)
    with TestClient(app.app) as client:
        yield client


HEADERS = {'X-Face-Service-Key': 's' * 32}


def encoded(image):
    ok, buffer = cv2.imencode('.jpg', image)
    assert ok
    return base64.b64encode(buffer).decode()


def test_requires_service_auth(client):
    response = client.post('/v1/face/enroll', json={'image': ''})
    assert response.status_code == 401


@pytest.mark.parametrize('value', ['invalid?', base64.b64encode(b'not an image').decode()])
def test_rejects_invalid_image(client, value):
    assert client.post('/v1/face/enroll', headers=HEADERS, json={'image': value}).status_code == 422


def test_real_model_blank_image(client):
    response = client.post('/v1/face/enroll', headers=HEADERS, json={'image': encoded(np.zeros((320, 320, 3), np.uint8))})
    assert response.status_code == 200
    assert response.json()['reason'] == 'NO_FACE'
    assert response.json()['template'] is None


def test_missing_model_fails_closed(monkeypatch, client, tmp_path):
    monkeypatch.setattr(app, 'engine', None)
    monkeypatch.setattr(app, 'ROOT', tmp_path)
    assert client.get('/health/ready').status_code == 503


def test_checksum_mismatch_fails_closed(monkeypatch, client, tmp_path):
    import json
    folder = tmp_path / 'models'
    folder.mkdir()
    (folder / 'manifest.json').write_text(json.dumps({'yunet': {'file': 'bad.onnx', 'sha256': '0' * 64}}))
    (folder / 'bad.onnx').write_bytes(b'bad')
    monkeypatch.setattr(app, 'engine', None)
    monkeypatch.setattr(app, 'ROOT', tmp_path)
    assert client.get('/health/ready').status_code == 503


def test_old_model_template_is_rejected(client):
    response = client.post('/v1/face/verify', headers=HEADERS,
        json={'image': '', 'template': [1.] * 128, 'modelVersion': 'old'})
    assert response.status_code == 409


def test_no_template_authority_from_extra_fields(client):
    response = client.post('/v1/face/enroll', headers=HEADERS, json={'image': '', 'matched': True})
    assert response.status_code == 422


def test_huge_body_rejected(client):
    assert client.post('/v1/face/enroll', headers=HEADERS, content=b'x' * (3 * 1024 * 1024 + 1)).status_code == 413


def test_empty_template_rejected(client):
    model = app.get_engine()
    response = client.post('/v1/face/verify', headers=HEADERS,
        json={'image': '', 'template': [0.] * 128, 'modelVersion': model.version})
    assert response.status_code == 422


def test_phone_size_image_is_bounded_before_detection(client):
    response = client.post('/v1/face/enroll', headers=HEADERS,
        json={'image': encoded(np.zeros((2560, 1920, 3), np.uint8))})
    assert response.status_code == 200
    assert response.json()['reason'] == 'NO_FACE'
    assert response.json()['quality']['processingHeight'] == 960
    assert response.json()['quality']['processingWidth'] == 720


def test_excessive_dimensions_still_rejected(client):
    buffer = io.BytesIO()
    Image.new('RGB', (4000, 3001)).save(buffer, format='PNG')
    response = client.post('/v1/face/enroll', headers=HEADERS,
        json={'image': base64.b64encode(buffer.getvalue()).decode()})
    assert response.status_code == 422
    assert response.json()['detail'] == 'IMAGE_DIMENSIONS_TOO_LARGE'


def test_small_face_is_not_enlarged_to_pass():
    from unittest.mock import Mock
    model = app.get_engine()
    detector = Mock()
    detector.detect.return_value = (None, np.array([[10, 10, 30, 40] + [0]*11], dtype=np.float32))
    from unittest.mock import patch
    with patch.object(model, 'detector', detector):
        feature, reason, quality = model.analyze(np.zeros((100, 100, 3), np.uint8))
    assert feature is None and reason == 'LOW_QUALITY'
    assert quality['issue'] == 'FACE_TOO_SMALL'
    assert quality['processingWidth'] == 100


def test_blur_returns_specific_diagnostic():
    from unittest.mock import Mock, patch
    model = app.get_engine()
    detector = Mock()
    detector.detect.return_value = (None, np.array([[10, 10, 150, 150] + [0]*11], dtype=np.float32))
    with patch.object(model, 'detector', detector):
        feature, reason, quality = model.analyze(np.zeros((200, 200, 3), np.uint8))
    assert feature is None and reason == 'LOW_QUALITY'
    assert quality['issue'] == 'FACE_TOO_BLURRY'
    assert quality['sharpness'] == 0


def test_real_portrait_pair_and_two_faces(client):
    """Public NASA portraits, downloaded separately; never use staff data in Git."""
    root = Path(__file__).parent / 'fixtures'
    if not (root / 'astronaut.png').exists() or not (root / 'grace_hopper.jpg').exists():
        pytest.skip('Run tests/download_fixtures.py for real-model portrait acceptance')
    first = cv2.imread(str(root / 'astronaut.png'))
    second = cv2.imread(str(root / 'grace_hopper.jpg'))
    enrollment = client.post('/v1/face/enroll', headers=HEADERS, json={'image': encoded(first)}).json()
    assert enrollment['accepted'], enrollment['reason']
    reference = {'template': enrollment['template'], 'modelVersion': enrollment['modelVersion']}
    # Use a distinct image encoding and exposure, rather than comparing identical bytes.
    changed = cv2.convertScaleAbs(first, alpha=.9, beta=8)
    same = client.post('/v1/face/verify', headers=HEADERS, json={**reference, 'image': encoded(changed)}).json()
    different = client.post('/v1/face/verify', headers=HEADERS, json={**reference, 'image': encoded(second)}).json()
    assert same['matched'] is True
    assert different['matched'] is False and different['reason'] == 'NO_MATCH'
    double = client.post('/v1/face/enroll', headers=HEADERS, json={'image': encoded(np.concatenate([first, first], axis=1))}).json()
    assert double['accepted'] is False and double['reason'] == 'MULTIPLE_FACES'
    blurred = cv2.GaussianBlur(first, (41, 41), 0)
    degraded = client.post('/v1/face/enroll', headers=HEADERS, json={'image': encoded(blurred)}).json()
    assert degraded['accepted'] is False
