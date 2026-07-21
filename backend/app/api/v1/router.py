"""API v1 aggregate router — endpoint modules mount here as they land."""

from fastapi import APIRouter

from app.api.v1.endpoints import attendance, auth, classes, students

api_v1_router = APIRouter()
api_v1_router.include_router(auth.router)
api_v1_router.include_router(classes.router)
api_v1_router.include_router(students.router)
api_v1_router.include_router(attendance.router)
