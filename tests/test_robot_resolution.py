"""Real model at the robot's VGA resolution, using public fixtures only."""
import base64
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
import app


def vga(image):
    scale = min(640 / image.shape[1], 480 / image.shape[0])
    resized = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    canvas = np.zeros((480, 640, 3), np.uint8)
    h, w = resized.shape[:2]
    canvas[(480-h)//2:(480-h)//2+h, (640-w)//2:(640-w)//2+w] = resized
    return canvas


def jpeg(image):
    ok, data = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    assert ok
    return base64.b64encode(data).decode()


def test_real_model_vga_match_and_wrong_person(monkeypatch):
    root = Path(__file__).parent / 'fixtures'
    if not all((root / name).exists() for name in ('astronaut.png', 'grace_hopper.jpg')):
        pytest.skip('Download public fixtures first')
    monkeypatch.setenv('FACE_SERVICE_KEY', 's' * 32)
    headers = {'X-Face-Service-Key': 's' * 32}
    first = cv2.imread(str(root / 'astronaut.png'))
    second = cv2.imread(str(root / 'grace_hopper.jpg'))
    with TestClient(app.app) as client:
        enrolled = client.post('/v1/face/enroll', headers=headers, json={'image': jpeg(first)}).json()
        assert enrolled['accepted'], enrolled['reason']
        reference = {key: enrolled[key] for key in ('template', 'modelVersion')}
        for source, expected in ((cv2.convertScaleAbs(first, alpha=.9, beta=8), True), (second, False)):
            response = client.post('/v1/face/verify', headers=headers,
                                   json={**reference, 'image': jpeg(vga(source))})
            assert response.status_code == 200
            result = response.json()
            assert result['quality']['processingWidth'] == 640
            assert result['quality']['processingHeight'] == 480
            assert result['matched'] is expected, result['reason']
            assert result['reason'] == ('MATCH' if expected else 'NO_MATCH')
