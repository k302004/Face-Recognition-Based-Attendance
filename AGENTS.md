# AGENTS.md

## Project

Thesis "Face Recognition-Based Attendance and Feedback System". Hybrid app:
- Laravel 13 backend (`app/`, `routes/`, `resources/`) serves the dashboard view and proxies the camera stream.
- Plain-PHP attendance API in `public/api.php` + `public/db.php`, backed by `public/attendance.sqlite`.
- Vanilla JS frontend (`public/js/script.js`, `resources/views/attendance-app.blade.php`).
- Python camera stream (`scripts/camera_stream.py`) does face recognition and pushes events.

Two SQLite databases, do not confuse them:
- `public/attendance.sqlite` — main attendance data (students, schedules, attendance). Auto-created/migrated by `public/db.php` on first access. Gitignored.
- `database/database.sqlite` — Laravel's DB (users, sessions, cache, jobs).

## Setup

```sh
composer install
npm install
php artisan key:generate
php artisan migrate
npm run build
```
or `composer run setup`. Python deps: `pip3 install face_recognition opencv-python numpy` (plus `websockets` for the WS event channel). Mail: create `public/mail-config.php` from its example; device token: create `public/device_config.php` from its example (gitignored).

## Running

Three processes must run together:
1. Laravel: `composer run dev` (server + Reverb + queue + pail + Vite) — or Lerd serves `https://attendance.test`.
2. Camera stream: `python3 scripts/camera_stream.py` (ports 8090 HTTP / 8091 WS). Operation Mode depends on it; `CameraController` proxies `127.0.0.1:8090`.
3. (Optional) Raspberry Pi client — see `raspberry_pi/README.md`.

Lerd config: PHP 8.4, Node 24, `soketi` service, `queue` + `reverb` workers.

## Commands

- Tests: `composer run test` (clears config, then PHPUnit) or `php artisan test --compact` / `vendor/bin/phpunit --filter=Name`. PHPUnit uses `:memory:` for the Laravel DB, so it never touches `attendance.sqlite`.
- Lint/format: `vendor/bin/pint --dirty --format agent`.
- Assets: `npm run build` / `npm run dev`.

## Conventions & gotchas

- Attendance schema lives in `public/db.php` as `CREATE TABLE IF NOT EXISTS` + idempotent `ALTER TABLE ... ADD COLUMN` wrapped in try/catch. Add columns the same way; there is no migration framework for this DB.
- `public/api.php` is the attendance API (sessions, JSON errors). Frontend `public/js/script.js` calls it; keep response shapes stable.
- Face images are stored in `public/face_images/` (gitignored); the stream reads them and `public/attendance.sqlite`.
- Do not commit `attendance.sqlite`, `face_images/`, `device_config.php`, `camera.config`, `.env`, or `storage/framework`.
- `php/` is a bundled Windows PHP runtime for portable deployment (`Start Attendance.vbs`); do not edit it.
- `BROADCAST_CONNECTION`/Reverb vs `soketi`: `.env` carries both Reverb and Pusher (soketi) keys; the Lerd service is `soketi`. Check `config/broadcasting.php` before changing either.
- Lint with Pint before finalizing PHP changes.<|end|><|start|><|start|>assistant<|channel|>final<|message|>Done. I replaced the stale Laravel Boost dump in `/Users/dbuelo/dev/attendance/AGENTS.md` with a compact, repo-specific instruction file covering the hybrid architecture, the two SQLite databases, setup/run commands, test/lint commands, and the non-obvious gotchas (schema in `public/db.php`, camera stream dependency, gitignored runtime files, bundled Windows PHP).<|end|><|start|>tool_call_begin|xml<|message|><rfl:parameter name="name">
submit<|message|><|end|><|start|>tool_call_begin|xml<|message|><rfl:parameter name="name">
submit