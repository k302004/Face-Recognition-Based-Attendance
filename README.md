# Face Recognition Attendance System

Thesis project: "Developing and Pilot Testing of Face Recognition-Based Attendance and Feedback System"

## Overview

A full attendance management system built around face recognition, student tracking, and schedule monitoring. Features:

- Administrator login and account management
- Student enrollment with face image capture (multi-angle)
- Real-time attendance recording via camera (Operation Mode)
- Schedule creation, maintenance, and archival
- Attendance reports and archive/history views
- Password reset through email verification
- Optional Raspberry Pi device integration for on-site attendance capture

## Requirements

- **PHP 8.4+** (required for Laravel Reverb)
- **Composer** (PHP dependency manager)
- **Node.js 22+** (for frontend assets)
- **Python 3.9+** with `face_recognition`, `opencv-python`, `numpy`
- **SQLite** (bundled with PHP)
- **Lerd** (local PHP dev environment) or any web server (nginx/Apache) with PHP-FPM

## Project structure

- `app/` – Laravel controllers, models, providers
- `public/` – static assets, images, and served files
- `public/api.php` – attendance API (plain PHP, uses `public/attendance.sqlite`)
- `public/js/script.js` – dashboard frontend (vanilla JS)
- `resources/views/` – Blade templates
- `scripts/camera_stream.py` – Python camera stream with face recognition
- `database/` – Laravel migrations and seeders
- `config/` – Laravel configuration (reverb, broadcasting, etc.)
- `routes/` – Laravel routes (web, api, channels)

## Initial setup

### 1. Install PHP dependencies

```bash
composer install
```

### 2. Install Python dependencies

```bash
pip3 install face_recognition opencv-python numpy
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and ensure these are set:

```env
APP_NAME=Laravel
APP_ENV=local
APP_DEBUG=true
APP_URL=https://attendance.test

DB_CONNECTION=sqlite
DB_DATABASE=database/database.sqlite

BROADCAST_CONNECTION=reverb
REVERB_APP_ID=attendance-app
REVERB_APP_KEY=attendance-key
REVERB_APP_SECRET=attendance-secret
REVERB_HOST="localhost"
REVERB_PORT=8081
REVERB_SCHEME=http

SESSION_DRIVER=file
CACHE_STORE=file
QUEUE_CONNECTION=sync
```

### 4. Generate app key

```bash
php artisan key:generate
```

### 5. Run migrations (if using Laravel's database)

```bash
php artisan migrate
```

### 6. Configure camera

Edit `public/camera.config` or use the Setups page in the app to select a camera.

### 7. Configure mail (optional, for password reset)

Copy `public/mail-config.php.example` to `public/mail-config.php` and update SMTP details.

## Running the app

You need **three processes** running simultaneously:

### Terminal 1 — Laravel web server

```bash
php artisan serve --host=0.0.0.0 --port=8000
```

Or with Lerd (recommended), the site is served at `https://attendance.test` automatically.

### Terminal 2 — Reverb WebSocket server (for real-time face detection)

```bash
php artisan reverb:start --port=8081
```

### Terminal 3 — Python camera stream (face recognition)

```bash
python3 scripts/camera_stream.py
```

You should see:
```
[faces] loaded 2 known face(s) from .../public/face_images
Streaming camera index 0 on http://0.0.0.0:8090/video_feed
[faces] recognition enabled with 2 known face(s)
[ws] WebSocket server starting on ws://0.0.0.0:8091
```

### Access the app

- **With Lerd**: `https://attendance.test`
- **With artisan serve**: `http://localhost:8000`

## Operation Mode (real-time attendance)

1. Log in as Administrator.
2. Click "Start Operation Mode" on the Home page.
3. The camera feed appears. When a known face is detected:
   - The **Student Profile Image** panel shows the student's photo.
   - The **Face Information** panel shows the student's details (name, course, year, age, status, etc.).
   - Attendance (time in) is automatically recorded to the database.
   - A second detection records the time out.

## Database

The app uses two SQLite databases:

- `public/attendance.sqlite` — main attendance data (students, schedules, attendance records)
- `database/database.sqlite` — Laravel's database (users, sessions, etc.)

The attendance.sqlite is auto-initialized by `public/db.php` on first access.

## Password reset email setup

1. Copy `mail-config.php.example` to `mail-config.php`.
2. Update the SMTP details for the email account that sends verification codes.
3. For Gmail, use an App Password instead of the regular password.

## Raspberry Pi integration (optional)

See `raspberry_pi/README.md` for device setup instructions. The Pi client sends attendance scans to the `device-attendance` API endpoint using a device token configured in `public/device_config.php`.

## Troubleshooting

### Camera stream not running
- Error: `Camera stream is not running.` or pending requests
- Fix: Start the Python stream: `python3 scripts/camera_stream.py`
- Ensure Python dependencies are installed: `pip3 install face_recognition opencv-python numpy`

### Profile image not showing
- Ensure the student has a `face_image_path` in the database.
- Hard-refresh the browser (`Cmd+Shift+R` / `Ctrl+Shift+R`).
- Check the browser console for errors.

### PHP version mismatch
- Reverb requires PHP 8.4+. Ensure `.php-version` contains `8.4`.
- With Lerd: `lerd site php 8.4` for the attendance site.

### Port conflicts
- Reverb (default port 8081) and camera stream (port 8090/8091) must not conflict with other services.
- Change ports in `.env` (REVERB_PORT) and `scripts/camera_stream.py` (DEFAULT_PORT, WEBSOCKET_PORT) if needed.

## Tech stack

- **Backend**: Laravel 13 (PHP 8.4), plain PHP API (`public/api.php`)
- **Frontend**: Vanilla JavaScript, Blade templates
- **Database**: SQLite
- **Real-time**: WebSocket (Python `websockets` library) + SSE fallback
- **Face recognition**: Python `face_recognition` + OpenCV
- **WebSocket server**: Python `websockets` (port 8091) + Laravel Reverb (port 8081)
- **Web server**: Lerd (nginx + PHP-FPM) or `php artisan serve`