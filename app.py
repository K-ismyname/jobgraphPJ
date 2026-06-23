# HF Spaces 진입점 — FastAPI 앱을 그대로 노출
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from src.api.main import app  # noqa: F401, E402 — HF Spaces가 이 변수를 찾음
