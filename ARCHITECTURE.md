# AttendAI — Production Architecture

> AI-powered multi-image smart attendance platform for classrooms, laboratories, and seminar halls.
> Stack: React + TypeScript + Tailwind · FastAPI · PostgreSQL + pgvector · InsightFace · JWT.
> This document is the approved contract for incremental implementation.

## 1. High-Level Architecture

**Style: Modular monolith, layered, containerized.** Face pipeline, attendance workflow, and reporting share one transactional DB; strict internal boundaries (router → service → repository) keep modules extractable later (the face pipeline is isolated behind a plain-Python interface so it can become a GPU worker service if load demands).

```
Browser (Teacher/Admin) — React SPA
        │ HTTPS · REST/JSON · JWT Bearer · multipart (images)
Nginx — serves SPA build, proxies /api → backend
        │
FastAPI Backend
   API Layer (routers, deps, validation)
      → Services (business logic)
         → Repositories (all SQL)
         → Face Pipeline (InsightFace detect/embed, pgvector match, dedupe)
         → Storage Adapter (local FS now, S3 later)
        │
PostgreSQL 16 + pgvector (embeddings, ANN cosine search, HNSW index)
```

### Key decisions

| Decision | Choice | Reasoning |
|---|---|---|
| Embedding storage | PostgreSQL + pgvector, `VECTOR(512)`, HNSW cosine index | ANN similarity search inside the transactional DB — no second datastore to sync with student records |
| Face model | InsightFace `buffalo_l` (RetinaFace + ArcFace) on **ONNX Runtime CPU** (`CPUExecutionProvider`), singleton loaded at startup; `det_size` configurable (640 default, 320 for low-end laptops) | Runs on a normal laptop, no GPU. Deployable to Railway/Render CPU instances. Model name stored with every embedding for future re-enrollment |
| Attendance processing | Session **state machine** (`processing → pending_review → confirmed` / `failed`), processed via FastAPI `BackgroundTasks` | Never block the upload request; teacher verification already forces async UX (upload → poll → review → confirm). Interface is queue-agnostic — Celery can slot in later |
| Auth | JWT access (15 min) + rotating refresh tokens (hashed in DB, revocable); roles `admin`, `teacher`; bcrypt passwords | Stateless fast access checks + real logout/revocation — required for biometric data |
| ORM / migrations | SQLAlchemy 2.0 async + Alembic | Standard, auditable schema history |
| Reports | WeasyPrint (Jinja HTML → PDF) + openpyxl (Excel), streamed responses | Maintainable templated layout; no memory buffering |
| File storage | `StorageAdapter` protocol (save/get/delete/url); local volume now, S3/MinIO later | Dependency Inversion — one-class swap |
| Frontend data | TanStack Query + Axios for all server state; Zustand only for auth | Server cache with invalidation, minimal global state |

### Privacy & security posture

- Embeddings + enrollment photos deletable per student (right-to-erasure endpoint).
- Teachers can only access classes they own — enforced in the service layer.
- Uploads validated by magic bytes + size limit; stored under UUID names outside web root.
- Audit log on every confirmation/override.

## 2. Database Schema

```
users ──< refresh_tokens
users ──< classes (teacher_id)
classes ──< enrollments >── students
students ──< student_face_images ──< face_embeddings   (pgvector)
classes ──< attendance_sessions >── users (teacher)
attendance_sessions ──< session_images ──< face_detections
attendance_sessions ──< attendance_records >── students
users ──< audit_logs
```

```sql
users (
  id UUID PK, email CITEXT UNIQUE NOT NULL, hashed_password TEXT NOT NULL,
  full_name TEXT NOT NULL, role user_role NOT NULL,          -- ENUM('admin','teacher')
  is_active BOOL DEFAULT true, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ
)

refresh_tokens (
  id UUID PK, user_id UUID FK→users CASCADE, token_hash TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ, created_at TIMESTAMPTZ
)

classes (
  id UUID PK, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  teacher_id UUID FK→users,
  room_type room_type DEFAULT 'classroom',   -- ENUM('classroom','laboratory','seminar_hall')
  is_active BOOL DEFAULT true, created_at TIMESTAMPTZ
)

students (
  id UUID PK, reg_number TEXT UNIQUE NOT NULL, full_name TEXT NOT NULL,
  email CITEXT, is_active BOOL DEFAULT true, created_at TIMESTAMPTZ
)

enrollments (
  id UUID PK, class_id UUID FK→classes CASCADE, student_id UUID FK→students CASCADE,
  enrolled_at TIMESTAMPTZ, UNIQUE (class_id, student_id)
)

student_face_images (
  id UUID PK, student_id UUID FK→students CASCADE, image_path TEXT NOT NULL,
  uploaded_by UUID FK→users, created_at TIMESTAMPTZ
)

face_embeddings (
  id UUID PK, student_id UUID FK→students CASCADE,
  source_image_id UUID FK→student_face_images CASCADE,
  embedding VECTOR(512) NOT NULL,            -- L2-normalized
  model_name TEXT NOT NULL, quality_score REAL, created_at TIMESTAMPTZ
)
-- INDEX: HNSW (embedding vector_cosine_ops); (student_id)

attendance_sessions (
  id UUID PK, class_id UUID FK→classes, teacher_id UUID FK→users,
  session_date DATE NOT NULL, period_label TEXT,
  status session_status DEFAULT 'processing',
      -- ENUM('processing','pending_review','confirmed','failed')
  error_message TEXT, created_at TIMESTAMPTZ, confirmed_at TIMESTAMPTZ
)
-- INDEX: (class_id, session_date)

session_images (
  id UUID PK, session_id UUID FK→attendance_sessions CASCADE,
  image_path TEXT NOT NULL, faces_detected INT DEFAULT 0, created_at TIMESTAMPTZ
)

face_detections (
  id UUID PK, session_image_id UUID FK→session_images CASCADE,
  bbox JSONB NOT NULL, crop_path TEXT NOT NULL,
  matched_student_id UUID FK→students,       -- NULL = unknown
  confidence REAL,
  match_status match_status NOT NULL,
      -- ENUM('matched','duplicate','unknown','low_quality')
  resolved_student_id UUID FK→students,      -- teacher assigns an unknown face
  resolved_by UUID FK→users, created_at TIMESTAMPTZ
)

attendance_records (
  id UUID PK, session_id UUID FK→attendance_sessions CASCADE,
  student_id UUID FK→students,
  status attendance_status NOT NULL,         -- ENUM('present','absent','late','excused')
  source record_source NOT NULL,             -- ENUM('ai','manual')
  confidence REAL, detection_id UUID FK→face_detections,
  marked_by UUID FK→users, updated_at TIMESTAMPTZ,
  UNIQUE (session_id, student_id)
)
-- INDEX: (student_id), (session_id)

audit_logs (
  id BIGSERIAL PK, user_id UUID FK→users, action TEXT NOT NULL,
  entity_type TEXT NOT NULL, entity_id UUID, metadata JSONB, created_at TIMESTAMPTZ
)
```

**Design notes**

- `face_detections` = AI **evidence** (per face, per image). `attendance_records` = **verdict** (per student, per session, unique-constrained). Teacher verification transforms evidence into verdict.
- **Duplicate elimination:** a student in multiple images → several detections (one `matched`, rest `duplicate`) but exactly one record (highest confidence wins).
- **Unknown faces:** `match_status='unknown'` detections with stored crops; teacher can ignore or assign (`resolved_student_id`), optionally feeding the crop back into enrollment.
- Multiple embeddings per student (3–5 enrollment photos); matching takes max similarity across them.

## 3. Backend Folder Structure

```
backend/
├── app/
│   ├── main.py                    # App factory: middleware, routers, lifespan (loads face model once)
│   ├── core/                      # Cross-cutting, no business logic
│   │   ├── config.py              #   Pydantic Settings from env
│   │   ├── security.py            #   JWT encode/decode, bcrypt
│   │   ├── exceptions.py          #   Domain exceptions + global handlers
│   │   └── logging.py             #   Structured JSON logging
│   ├── db/
│   │   ├── session.py             #   Async engine, session factory, get_db
│   │   └── base.py                #   Declarative base, model registry for Alembic
│   ├── models/                    # SQLAlchemy ORM, one file per aggregate
│   │   ├── user.py  student.py  classroom.py  attendance.py  face.py  audit.py
│   ├── schemas/                   # Pydantic request/response — the API contract
│   │   ├── auth.py  student.py  classroom.py  attendance.py  analytics.py  common.py
│   ├── repositories/              # ALL SQL lives here
│   │   ├── base.py                #   Generic CRUD repository
│   │   ├── user_repo.py  student_repo.py  class_repo.py  attendance_repo.py
│   │   └── embedding_repo.py      #   pgvector similarity queries
│   ├── services/                  # Business logic, ownership enforcement, transactions
│   │   ├── auth_service.py        #   login, refresh rotation, revocation
│   │   ├── student_service.py     #   CRUD + enrollment photo → embedding
│   │   ├── class_service.py
│   │   ├── attendance_service.py  #   session state machine, verification, overrides
│   │   ├── analytics_service.py   #   aggregations
│   │   ├── report_service.py      #   PDF + Excel generation
│   │   └── face/                  # ★ isolated CV module
│   │       ├── engine.py          #   InsightFace singleton (only file importing insightface)
│   │       ├── matcher.py         #   cosine matching, thresholds, cross-image dedupe
│   │       └── pipeline.py        #   multi-image orchestration → detections + draft records
│   ├── api/
│   │   ├── deps.py                #   get_current_user, require_role, ownership guard
│   │   └── v1/
│   │       ├── router.py
│   │       └── endpoints/  auth.py students.py classes.py attendance.py analytics.py reports.py
│   ├── storage/
│   │   ├── base.py                #   StorageAdapter protocol
│   │   └── local.py               #   local-volume impl (s3.py later)
│   └── templates/reports/         # Jinja HTML templates for PDF
├── alembic/
├── tests/
│   ├── unit/                      #   services with mocked repos; matcher with synthetic embeddings
│   └── integration/               #   API tests against a test DB
├── pyproject.toml  Dockerfile  .env.example
```

## 4. Frontend Folder Structure (feature-sliced)

```
frontend/
├── src/
│   ├── app/                       # App.tsx, router.tsx (role-guarded routes), providers.tsx
│   ├── api/                       # client.ts (Axios + 401→refresh→retry interceptor), endpoints.ts
│   ├── features/                  # each: components/ hooks/ api.ts types.ts
│   │   ├── auth/                  #   login, useAuth, ProtectedRoute
│   │   ├── dashboard/             #   today's classes, pending reviews
│   │   ├── classes/               #   class CRUD, roster
│   │   ├── students/              #   student CRUD + face-enrollment upload
│   │   ├── attendance/            # ★ ImageUploader, ProcessingStatus (polling),
│   │   │                          #   ReviewBoard (crops + matches + confidence),
│   │   │                          #   UnknownFacesPanel (assign/ignore), AbsenteeList (override)
│   │   ├── analytics/             #   trends, per-student %, at-risk list
│   │   └── reports/               #   pickers → PDF/Excel download
│   ├── components/
│   │   ├── ui/                    #   Button, Input, Modal, Table, Badge, Skeleton
│   │   └── layout/                #   AppShell, Sidebar (→ bottom nav on mobile), Topbar
│   ├── hooks/  lib/  types/  styles/
│   └── stores/authStore.ts        #   Zustand: user + tokens — the ONLY global client state
├── Dockerfile (multi-stage → nginx)  tailwind.config.ts  vite.config.ts  .env.example
```

Rules: features never import from other features (shared code promotes to `components/`/`hooks/`/`lib/`); all server state via TanStack Query hooks in each feature's `api.ts`.

## 5. Module Communication

### Core flow — multi-image attendance

1. `POST /api/v1/attendance/sessions` (class_id + 3–5 images, multipart) → validate images → StorageAdapter.save → insert session `processing` → enqueue BackgroundTask → **202 {session_id}**.
2. Pipeline (per image): detect faces → embed → pgvector ANN match vs class gallery → **cross-image dedupe** (best confidence per student) → classify matched/unknown/low_quality → draft records (matched→present(ai), rest of roster→absent) → status `pending_review`.
3. Frontend polls `GET /sessions/{id}` (2s) until `pending_review`; renders ReviewBoard + UnknownFacesPanel + AbsenteeList.
4. Teacher edits: `PATCH /sessions/{id}/records/{student_id}` (override, source=manual); `POST /sessions/{id}/detections/{detection_id}/resolve` (assign unknown).
5. `POST /sessions/{id}/confirm` → status `confirmed` + audit log → analytics/reports include the session.

### Layer contracts

| Boundary | Contract |
|---|---|
| Frontend ↔ Backend | REST/JSON `/api/v1`, JWT Bearer, multipart only for uploads, error envelope `{detail, code}`; frontend `types/` mirrors backend `schemas/` |
| Router → Service | Pydantic in, domain out; zero business logic in routers; domain exceptions → HTTP via global handlers |
| Service → Repository | Typed query methods, no SQL in services; transaction boundary owned by the service |
| Service → Face Pipeline | `pipeline.process(session_id)` plain-Python, dataclass results; run off the event loop; queue-swappable |
| Service → Storage | `StorageAdapter` protocol only |
| AuthZ | `get_current_user` + `require_role` + class-ownership check in services — always server-side |

Analytics and reports are **read-only consumers** of confirmed sessions; report_service reuses analytics aggregations through Jinja→WeasyPrint / openpyxl. One-way dependency, no cycles.

## 6. Deployment

```
docker-compose.yml
├── db:       pgvector/pgvector:pg16   (volume: pgdata)
├── backend:  FastAPI + uvicorn        (volumes: media/, model cache; healthcheck /health; alembic on startup)
└── frontend: nginx serving SPA build, proxying /api → backend
```

Secrets via env; CORS locked to frontend origin; HTTPS at nginx; InsightFace models baked into the image (no runtime download). **CPU-only everywhere** — ONNX Runtime `CPUExecutionProvider`, works on a normal laptop and on Railway/Render CPU instances (single Dockerfile per service, `PORT` env respected, no GPU dependencies in the image).

## 7. Implementation Order (proposed)

1. Backend scaffold: core/, db/, models/, Alembic initial migration, docker-compose (db + backend)
2. Auth module (JWT + refresh rotation) end-to-end incl. tests
3. Classes & students CRUD + enrollments
4. Face enrollment: photo upload → engine → embeddings
5. Attendance pipeline: session state machine, multi-image processing, dedupe, unknowns
6. Verification endpoints + confirm flow
7. Frontend scaffold: app/, api client, auth feature, layout
8. Frontend features: classes/students → attendance flow → analytics → reports
9. Analytics + report generation (backend), then wiring
10. Hardening: audit logs, rate limiting, e2e pass, deployment docs
```
