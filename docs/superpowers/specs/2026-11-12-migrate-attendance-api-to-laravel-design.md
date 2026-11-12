# Design: Migrate the attendance API into Laravel

Date: 2026-11-12
Status: Draft (pending approval)

## Intent

Move the plain-PHP attendance backend (`public/api.php`, ~28 actions) into Laravel, one slice at a time (strangler pattern), while keeping the existing `public/attendance.sqlite` data and the frontend working at every step. Auth (login/signup/logout/password reset) moves into Laravel so a single Laravel session guards all endpoints. Camera/streaming endpoints stay in `public/api.php`.

## Why

- `public/api.php` is a 1000+ line procedural file mixing routing, auth, DB access, and business logic; hard to test and extend.
- Laravel already hosts the app (`/` view, `CameraController`), so consolidating removes the split backend.
- Keeps the thesis demo deployable on Windows (portable PHP) without rewriting the camera side.

## Goals

- All data/auth/CRUD endpoints served by Laravel controllers + routes.
- Frontend JS calls Laravel routes instead of `api.php?action=...`.
- Existing `public/attendance.sqlite` data preserved; no data migration required.
- Laravel session replaces `$_SESSION['user']` auth.
- Tests added for migrated endpoints (PHPUnit feature tests).

## Non-goals

- Camera/streaming endpoints (`camera-*`, `camera-feed`, `face-events`, `camera-current-student`, `camera-pose`, `camera-stream-*`) stay in `public/api.php`.
- No change to the Python stream or face-recognition logic.
- No UI redesign; only endpoint URLs change.
- No framework switch (still Laravel 13, SQLite).

## Anti-goals (what would make this a failure)

- Breaking the running demo mid-migration.
- Losing or corrupting `attendance.sqlite` data.
- Ending with two divergent auth systems.
- Leaving `api.php` actions half-migrated with no clear ownership.

## Constraints

- PHP 8.4, Laravel 13, SQLite only (no MySQL/Postgres).
- Attendance DB is `public/attendance.sqlite`; Laravel's own DB is `database/database.sqlite`. Both must coexist.
- Frontend is vanilla JS using `fetch('api.php?action=...')` with `credentials: 'same-origin'`.
- `public/db.php` auto-creates the attendance schema on first access; must keep working for fresh Windows installs.
- Device-attendance endpoint is token-authenticated (no session) and must remain callable by Raspberry Pi clients.

## Chosen approach: Strangler (incremental)

Migrate one vertical slice at a time. Each slice: add Laravel route + controller + (optional) model, update JS call, remove the `api.php` action, run tests, verify in browser. Keep `api.php` until all non-camera actions are gone; then delete it.

### Slices (in order)

1. **DB wiring + models** — add `attendance` connection in `config/database.php` pointing at `public/attendance.sqlite`; create Eloquent models (`Attendance`, `Student`, `Schedule`, `AuditLog`, `NotificationSetting`) with `$table`/`$connection = 'attendance'`. No routes yet. (No data touched.)
2. **Auth** — Laravel login/signup/logout/password-reset controllers + routes (`/api/login`, `/api/signup`, `/api/logout`, `/api/request-password-reset`, `/api/reset-password`, `/api/profile`, `/api/password`). Migrate `users` table usage: either point Laravel's default connection at attendance.sqlite's `users` table or keep `database/database.sqlite` users. **Decision needed in implementation:** keep Laravel's `users` table in `database/database.sqlite` (current) and seed/migrate admin there; simpler and matches existing Laravel auth. Plain-PHP `users` table in attendance.sqlite becomes unused for new logins.
   - Actually: to minimize risk, keep using the existing `users` table in `attendance.sqlite` via the `attendance` connection and make `App\Models\User` use `connection = 'attendance'`. Then no data migration and existing admin accounts work. **Chosen.**
3. **Dashboard read** — `GET /api/dashboard` returning students/schedules/attendance/audit/notificationSettings. Update JS `refreshAttendanceRecords` + initial load.
4. **Students CRUD** — create/update/archive/delete/restore student. Update JS.
5. **Schedules CRUD** — create/delete schedule.
6. **Attendance recording** — `record-attendance` (+ `device-attendance` stays token-based). Update Operation Mode JS.
7. **Archives** — archive student, archive school year, archive attendance date, restore year, archive views data.
8. **Settings** — notification settings.
9. **Cleanup** — remove migrated actions from `api.php`; delete `api.php` once only camera actions remain (move those to a dedicated `public/camera-api.php` or keep).

### Auth details

- `App\Models\User` set `$connection = 'attendance'` and `$table = 'users'`; map columns (`name`→`name`, `email`, `password`→`password_hash`? or rename). **Decision:** keep column names as-is (`password_hash`, `profile_image`) and override `getAuthPassword()` to return `password_hash`; use Laravel's `Auth::attempt` with a custom credential key. Alternatively rename columns via migration. **Chosen:** override `getAuthPassword()` and use `password_hash` column; no rename. Simpler, no data migration.
- Session driver stays `file` (current). Laravel session cookie name default; frontend uses `credentials: 'same-origin'`, fine.
- Password reset: use Laravel's `Password` broker with a custom table? The current flow sends a 6-digit code via SMTP. **Decision:** reimplement the existing code-based reset in a controller using the same `mail-config.php`/SMTP settings, not Laravel's token link flow. Keeps UX identical.

### DB wiring

```php
// config/database.php 'connections'
'attendance' => [
    'driver' => 'sqlite',
    'database' => base_path('public/attendance.sqlite'), // or env ATTENDANCE_DB
    ...
],
```

Wait — `base_path('public/attendance.sqlite')`. Laravel's `database_path` is `database/`. Use `public_path('attendance.sqlite')`? `public_path()` resolves to `public/`. Yes.

Models: `protected $connection = 'attendance';`.

### Migrations

- Add Laravel migrations under `database/migrations/` for each attendance table, guarded by `if (!Schema::hasTable(...))` so they don't fail on existing DBs and fresh installs get schema.
- Run `php artisan migrate` only against the default connection (`database.sqlite`) for Laravel's own tables; attendance migrations run with `--database=attendance`. Document in setup.
- `public/db.php` remains as fallback for Windows portable installs; mark deprecated but don't delete until migrations proven.

### Frontend changes

- Replace `api.php?action=X` fetches with Laravel routes. Introduce a small JS helper `apiUrl(path)` or keep `requestApi(action)` but point at new paths. **Decision:** add `requestApi` overload: if action starts with `/`, treat as full path; else legacy `api.php?action=`. Migrate call sites slice by slice.
- Keep `credentials: 'same-origin'`.

### Testing

- Feature tests per slice using a temp copy of `attendance.sqlite` or in-memory. Use `RefreshDatabase` on the `attendance` connection with migrations.
- Keep existing example tests passing.

### Risks & mitigations

- **Session cookie domain**: Lerd serves `https://attendance.test`; ensure `SESSION_DOMAIN`/`SANCTUM` not needed (session auth, no tokens). Keep `SESSION_DRIVER=file`.
- **CORS/CSRF**: Laravel's `VerifyCsrfToken` middleware applies to web routes. Frontend fetches are same-origin with cookies → need CSRF token. **Decision:** put API routes in `routes/api.php` (stateless, no CSRF) but use session auth via `auth` middleware? Laravel's `api` middleware group doesn't include sessions by default. **Resolution:** use `web` middleware group for these routes (session + CSRF) and have JS read the CSRF token from a meta tag / cookie. Or disable CSRF for these specific routes. Simpler for a thesis app: define routes in `web.php` under an `auth`-protected group and inject `X-CSRF-TOKEN` header from `document.querySelector('meta[name=csrf-token]')`. Add the meta tag to the Blade view. **Chosen.**
- **File paths**: `public/attendance.sqlite` must be writable by PHP-FPM (lerd) and the Python stream. Keep as-is.
- **Data loss during migration**: never run destructive migrations; all schema changes additive with `hasTable`/`hasColumn` guards. Back up `attendance.sqlite` before first migration run.

## What's left to the builder

- Exact controller method signatures and validation.
- Whether to use Form Requests or inline validation (inline, matching current style, is fine).
- Pagination/filtering details (current returns all rows).
- Audit log wording.

## Builder check resolutions

1. **Camera endpoints auth**: drop `requireLogin()` from the camera endpoints that remain in `api.php` (same-origin thesis app). They keep working without a Laravel session.
2. **Route/URL convention**: keep action names as path segments — `/api/login`, `/api/me`, `/api/dashboard`, `/api/student`, etc. `requestApi(action)` migrates to `requestApi('/api/' + action)` mechanically. No RESTful re-shaping.
3. **login_attempts / password_reset_tokens**: keep raw PDO-style queries inside the auth controller (matching current style); no new models. Tables already exist in `attendance.sqlite`.
4. **CSRF**: add `<meta name="csrf-token" content="{{ csrf_token() }}">` to the Blade view and inject `X-CSRF-TOKEN` in `requestApi` for non-GET requests.
5. **User model**: `$connection = 'attendance'`, `$table = 'users'`, override `getAuthPassword()` to return `password_hash`. Columns: `name`, `email`, `password_hash`, `role`, `profile_image`.

## Approval

Resolved. Ready to implement Slice 1 (DB wiring + models).<|end|><|start|><|start|>assistant<|channel|>final<|message|>I've written the design doc to `docs/superpowers/specs/2026-11-12-migrate-attendance-api-to-laravel-design.md`. Key decisions baked in: keep `attendance.sqlite` via a dedicated `attendance` connection, Eloquent models point at it, `App\Models\User` uses `password_hash` column (no rename), code-based password reset reimplemented, CSRF via meta tag, migrations guarded by `hasTable`.

Before you approve, want me to run a "builder check" subagent over the doc to catch gaps, or is there anything you want changed first?<|end|><|start|>user<|channel|>lets do the builder check