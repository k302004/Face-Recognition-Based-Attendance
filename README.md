# Face Recognition Attendance System

Thesis project: "Developing and Pilot Testing of Face Recognition-Based Attendance and Feedback System"

## Overview

This project is a full attendance management system built around face recognition, student tracking, and schedule monitoring. It supports:

- Administrator login and account management
- Student enrollment with face image capture
- Attendance recording by subject and date
- Schedule creation, maintenance, and archival
- Attendance reports and archive/history views
- Password reset through email verification
- Optional Raspberry Pi device integration for on-site attendance capture

## Project structure

- `api.php` – main attendance API and request handlers
- `db.php` – SQLite schema initialization and database setup
- `index.html` and `script.js` – attendance dashboard frontend
- `public/` – static assets, images, and served files
- `raspberry_pi/` – Raspberry Pi client and setup instructions
- `php/` – portable PHP runtime used for local Windows deployment

## Local startup

For the packaged Windows setup:

1. Double-click `Start Attendance.vbs`.
2. Open the app at `http://127.0.0.1:8080`.
3. When finished, double-click `Stop Attendance.vbs`.

Keep the app folder together, including the `php` directory and the `attendance.sqlite` database file.

## Password reset email setup

1. Copy `mail-config.php.example` to `mail-config.php`.
2. Update the SMTP details for the email account that sends verification codes.
3. For Gmail, use an App Password instead of the regular password.
4. Restart the app and test the Forgot password flow.

## Raspberry Pi integration

The Raspberry Pi client and deployment notes are located in the `raspberry_pi/` directory. Read the setup guide there before connecting the device.

## Notes

- The database file is `attendance.sqlite`.
- Student face images are stored in the `face_images` folder.
- Back up the database and `face_images` folder while the app is stopped.
