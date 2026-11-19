"""Internal, stateless avatar verification. No camera frames are persisted."""
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import threading
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path


def native_threads():
    """Bound native pools before importing NumPy/OpenCV, including BLAS pools."""
    try:
        value = int(os.getenv('FACE_NATIVE_THREADS', '1'))
        if not 1 <= value <= 2:
            raise ValueError()
    except ValueError:
        raise ValueError('FACE_NATIVE_THREADS must be 1 or 2') from None
    return value


NATIVE_THREADS = native_threads()
for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = str(NATIVE_THREADS)

import cv2
import numpy as np
from anyio import to_thread
from PIL import Image, ImageOps
from fastapi import FastAPI, Header, HTTPException, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

cv2.setNumThreads(NATIVE_THREADS)

ROOT = Path(__file__).parent
MAX_IMAGE = 2 * 1024 * 1024
MAX_PIXELS = 12_000_000
PROCESSING_EDGE = 960
QUALITY_EDGE = 160
PIPELINE_VERSION = 'bounded-exif-960-quality160-v2'
LOCK = threading.Lock()
INIT_LOCK = threading.Lock()
ADMISSION = threading.BoundedSemaphore(1)
engine = None
initialization_error = None


@asynccontextmanager
async def lifespan(_app):
    global initialization_error
    initialization_error = None
    try:
        if len(os.getenv('FACE_SERVICE_KEY', '')) < 32:
            raise ValueError('SERVICE_KEY_NOT_CONFIGURED')
        await to_thread.run_sync(get_engine)
    except Exception:
        # Keep health available for the installer; never serve verification as ready.
        initialization_error = 'MODEL_NOT_READY'
        logging.error('FACE_STARTUP_NOT_READY: check service configuration and pinned models')
    yield


app = FastAPI(title="MAR Face verification", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def bounded_body(request: Request, call_next):
    if not request.url.path.startswith('/v1/'):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response
    try:
        authorized(request.headers.get('X-Face-Service-Key', ''))
    except HTTPException:
        return JSONResponse({'detail': 'SERVICE_AUTH_REQUIRED'}, status_code=401,
                            headers={'Cache-Control': 'no-store'})
    if initialization_error is not None:
        return JSONResponse({'detail': 'MODEL_NOT_READY'}, status_code=503,
                            headers={'Cache-Control': 'no-store', 'Retry-After': '1'})
    # Admit before reading a body: excess clients never queue images in memory.
    if not ADMISSION.acquire(blocking=False):
        return JSONResponse({'detail': 'FACE_BUSY'}, status_code=429,
                            headers={'Cache-Control': 'no-store', 'Retry-After': '1'})
    try:
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 3 * 1024 * 1024:
                return JSONResponse({'detail': 'IMAGE_TOO_LARGE'}, status_code=413,
                                    headers={'Cache-Control': 'no-store'})
        request._body = bytes(data)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response
    finally:
        ADMISSION.release()


@contextmanager
def inference_slot():
    # Also guard native work if a client disconnects while its thread is finishing.
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, 'FACE_BUSY', headers={'Retry-After': '1'})
    try:
        yield
    finally:
        LOCK.release()


def authorized(x_face_service_key: str = Header(default="")):
    expected = os.getenv("FACE_SERVICE_KEY", "")
    if len(expected) < 32 or not hmac.compare_digest(expected, x_face_service_key):
        raise HTTPException(401, "SERVICE_AUTH_REQUIRED")


class Enroll(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: str = Field(max_length=2800000)


class Verify(Enroll):
    template: list[float] = Field(min_length=128, max_length=128)
    modelVersion: str


def decode(value):
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) > MAX_IMAGE:
            raise ValueError()
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError()
            if probe.width * probe.height > MAX_PIXELS:
                raise HTTPException(422, "IMAGE_DIMENSIONS_TOO_LARGE")
            oriented = ImageOps.exif_transpose(probe).convert('RGB')
            return cv2.cvtColor(np.asarray(oriented), cv2.COLOR_RGB2BGR)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "INVALID_IMAGE") from None


class Engine:
    def __init__(self):
        manifest = json.loads((ROOT / "models/manifest.json").read_text())
        paths = {}
        for name, item in manifest.items():
            path = ROOT / 'models' / item['file']
            if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError("MODEL_CHECKSUM_MISMATCH")
            paths[name] = str(path)
        self.version = hashlib.sha256((json.dumps(manifest, sort_keys=True) + PIPELINE_VERSION).encode()).hexdigest()
        self.detector = cv2.FaceDetectorYN.create(paths['yunet'], '', (320, 320), 0.9)
        self.recognizer = cv2.FaceRecognizerSF.create(paths['sface'], '')
        self.threshold = float(os.getenv('FACE_COSINE_THRESHOLD', '0.363'))
        if not -1 <= self.threshold <= 1:
            raise ValueError('INVALID_THRESHOLD')

    def warmup(self):
        # Synthetic pixels only. Load both native graphs before readiness succeeds.
        self.analyze(np.zeros((480, 640, 3), dtype=np.uint8))
        self.recognizer.feature(np.zeros((112, 112, 3), dtype=np.uint8))

    def feature(self, image):
        feature, reason, _ = self.analyze(image)
        return feature, reason

    def analyze(self, image):
        # Downsample only; never enlarge a small face to pass the size gate.
        h, w = image.shape[:2]
        scale = min(1., PROCESSING_EDGE / max(h, w))
        if scale < 1:
            image = cv2.resize(image, (max(1, round(w*scale)), max(1, round(h*scale))), interpolation=cv2.INTER_AREA)
        quality = {'processingWidth': image.shape[1], 'processingHeight': image.shape[0],
                   'minFacePixels': 80, 'sharpnessThreshold': 40, 'qualityEdge': QUALITY_EDGE}
        with inference_slot():
            h, w = image.shape[:2]
            self.detector.setInputSize((w, h))
            _, faces = self.detector.detect(image)
            if faces is None or len(faces) == 0:
                return None, 'NO_FACE', quality
            if len(faces) != 1:
                return None, 'MULTIPLE_FACES', quality
            face = faces[0]
            x, y, width, height = face[:4].astype(int)
            crop = image[max(0,y):min(h,y+height), max(0,x):min(w,x+width)]
            quality.update(faceWidth=int(width), faceHeight=int(height))
            if crop.size == 0 or min(crop.shape[:2]) < 80:
                quality['issue'] = 'FACE_TOO_SMALL'
                return None, 'LOW_QUALITY', quality
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            quality_scale = min(1., QUALITY_EDGE / max(gray.shape))
            if quality_scale < 1:
                gray = cv2.resize(gray, (max(1, round(gray.shape[1]*quality_scale)), max(1, round(gray.shape[0]*quality_scale))), interpolation=cv2.INTER_AREA)
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            quality['sharpness'] = round(sharpness, 2)
            if sharpness < 40:
                quality['issue'] = 'FACE_TOO_BLURRY'
                return None, 'LOW_QUALITY', quality
            aligned = self.recognizer.alignCrop(image, face)
            feature = self.recognizer.feature(aligned).flatten()
            norm = np.linalg.norm(feature)
            if not np.isfinite(feature).all() or norm <= 0:
                quality['issue'] = 'INVALID_FACE_FEATURE'
                return None, 'LOW_QUALITY', quality
            return feature / norm, 'OK', quality


def get_engine():
    global engine, initialization_error
    if initialization_error is not None:
        raise HTTPException(503, 'MODEL_NOT_READY')
    if engine is None:
        with INIT_LOCK:
            if initialization_error is not None:
                raise HTTPException(503, 'MODEL_NOT_READY')
            if engine is None:
                try:
                    candidate = Engine()
                    candidate.warmup()
                    engine = candidate
                except Exception:
                    initialization_error = 'MODEL_NOT_READY'
                    raise HTTPException(503, 'MODEL_NOT_READY') from None
    return engine


@app.get('/health/ready')
def ready():
    model = get_engine()
    if len(os.getenv('FACE_SERVICE_KEY', '')) < 32:
        raise HTTPException(503, 'SERVICE_KEY_NOT_CONFIGURED')
    return {'ready': True, 'modelVersion': model.version, 'liveness': False}


@app.post('/v1/face/enroll', dependencies=[Depends(authorized)])
def enroll(body: Enroll):
    model = get_engine()
    feature, reason, quality = model.analyze(decode(body.image))
    return {'accepted': feature is not None, 'reason': reason, 'modelVersion': model.version,
            'template': feature.tolist() if feature is not None else None, 'quality': quality}


@app.post('/v1/face/verify', dependencies=[Depends(authorized)])
def verify(body: Verify):
    model = get_engine()
    if body.modelVersion != model.version:
        raise HTTPException(409, 'MODEL_VERSION_CHANGED')
    reference = np.asarray(body.template, dtype=np.float32)
    norm = np.linalg.norm(reference)
    if not np.isfinite(reference).all() or not np.isfinite(norm) or norm <= 0:
        raise HTTPException(422, 'INVALID_TEMPLATE')
    feature, reason, quality = model.analyze(decode(body.image))
    score = float(np.dot(feature, reference / norm)) if feature is not None else None
    matched = score is not None and score >= model.threshold
    return {'matched': matched, 'reason': ('MATCH' if matched else 'NO_MATCH') if feature is not None else reason,
            'score': score, 'modelVersion': model.version, 'quality': quality}
