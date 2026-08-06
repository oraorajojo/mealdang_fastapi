# FastAPI 진입점
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings

# FastAPI 앱 생성
app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    debug=settings.APP_DEBUG,
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 라우터 등록 자리 (준비되면 app.include_router(...) 추가)

# 홈 경로
@app.get("/", summary="api root")
def root():
    return {"message": "MealDang FastAPI 서버 준비 완료!"}
