<?php
declare(strict_types=1);

$databasePath = __DIR__ . DIRECTORY_SEPARATOR . 'attendance.sqlite';
$options = [
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    PDO::ATTR_EMULATE_PREPARES => false,
];

try {
    $db = new PDO('sqlite:' . $databasePath, null, null, $options);
    $db->exec('PRAGMA foreign_keys = ON');
    $db->exec('CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT "Administrator",
        profile_image TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )');
    try {
        $db->exec('ALTER TABLE users ADD COLUMN profile_image TEXT');
    } catch (PDOException $error) {
        // The column already exists on an initialized database.
    }
    $db->exec('CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL UNIQUE,
        full_name TEXT NOT NULL,
        course TEXT NOT NULL,
        year TEXT NOT NULL,
        school_year TEXT NOT NULL DEFAULT \'2026-2027\',
        status TEXT NOT NULL,
        parent_phone TEXT NOT NULL DEFAULT \'\',
        is_archived INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )');
    try {
        $db->exec('ALTER TABLE students ADD COLUMN archived_school_year TEXT');
    } catch (PDOException $error) {
        // The column already exists on an initialized database.
    }
    try {
        $db->exec('ALTER TABLE students ADD COLUMN face_image_path TEXT');
    } catch (PDOException $error) {
        // The column already exists on an initialized database.
    }
    try {
        $db->exec("ALTER TABLE students ADD COLUMN parent_phone TEXT NOT NULL DEFAULT ''");
    } catch (PDOException $error) {
        // The column already exists on an initialized database.
    }
    try {
        $db->exec("ALTER TABLE students ADD COLUMN school_year TEXT NOT NULL DEFAULT '2026-2027'");
    } catch (PDOException $error) {
        // The column already exists on an initialized database.
    }
    $db->exec("UPDATE students SET archived_school_year = '2026-2027' WHERE is_archived = 1 AND archived_school_year IS NULL");
    $db->exec('CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        instructor TEXT NOT NULL,
        room TEXT NOT NULL,
        day TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        school_year TEXT NOT NULL DEFAULT \'2026-2027\',
        is_archived INTEGER NOT NULL DEFAULT 0,
        archived_school_year TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )');
    foreach ([
        "ALTER TABLE schedules ADD COLUMN school_year TEXT NOT NULL DEFAULT '2026-2027'",
        'ALTER TABLE schedules ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0',
        'ALTER TABLE schedules ADD COLUMN archived_school_year TEXT'
    ] as $alterSchedule) {
        try {
            $db->exec($alterSchedule);
        } catch (PDOException $error) {
            // The column already exists on an initialized database.
        }
    }
    $db->exec("UPDATE schedules SET school_year = COALESCE(archived_school_year, '2026-2027') WHERE school_year IS NULL OR school_year = ''");
    $db->exec('CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL,
        student_name TEXT NOT NULL,
        course TEXT NOT NULL,
        attendance_date TEXT NOT NULL,
        subject TEXT NOT NULL,
        time_in TEXT NOT NULL,
        time_out TEXT NOT NULL,
        status TEXT NOT NULL,
        school_year TEXT NOT NULL DEFAULT \'2026-2027\',
        is_archived INTEGER NOT NULL DEFAULT 0,
        archived_school_year TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )');
    $attendanceColumns = $db->query('PRAGMA table_info(attendance)')->fetchAll();
    $hasAttendanceArchiveColumn = false;
    foreach ($attendanceColumns as $column) {
        if ($column['name'] === 'is_archived') {
            $hasAttendanceArchiveColumn = true;
            break;
        }
    }
    if (!$hasAttendanceArchiveColumn) $db->exec('ALTER TABLE attendance ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0');
    try {
        $db->exec("ALTER TABLE attendance ADD COLUMN school_year TEXT NOT NULL DEFAULT '2026-2027'");
    } catch (PDOException $error) {
        // The column already exists on an initialized database.
    }
    try {
        $db->exec('ALTER TABLE attendance ADD COLUMN archived_school_year TEXT');
    } catch (PDOException $error) {
        // The column already exists on an initialized database.
    }
    $db->exec("UPDATE attendance SET school_year = COALESCE(archived_school_year, '2026-2027') WHERE school_year IS NULL OR school_year = ''");
    $db->exec('CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        actor TEXT NOT NULL DEFAULT "System",
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS notification_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        email TEXT NOT NULL,
        token_hash TEXT NOT NULL,
        expires_at INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS login_attempts (
        email TEXT PRIMARY KEY,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )');

    $studentCount = (int) $db->query('SELECT COUNT(*) FROM students')->fetchColumn();
    if ($studentCount === 0) {
        $students = [
            ['2026-001', 'John Cruz', 'BSCS', '1st Year', 'Regular'],
            ['2026-002', 'Maria Santos', 'BSIT', '2nd Year', 'Regular'],
            ['2026-003', 'Anne Reyes', 'BSCS', '3rd Year', 'Regular'],
            ['2026-004', 'Peter Ramos', 'BSOA', '1st Year', 'Regular'],
        ];
        $statement = $db->prepare('INSERT INTO students (student_id, full_name, course, year, status) VALUES (?, ?, ?, ?, ?)');
        foreach ($students as $student) $statement->execute($student);
    }

    $scheduleCount = (int) $db->query('SELECT COUNT(*) FROM schedules')->fetchColumn();
    if ($scheduleCount === 0) {
        $db->exec("INSERT INTO schedules (subject, instructor, room, day, start_time, end_time) VALUES ('Programming 1', 'Prof. Santos', 'Lab 1', 'Monday', '8:00 AM', '10:00 AM')");
    }

    $attendanceCount = (int) $db->query('SELECT COUNT(*) FROM attendance')->fetchColumn();
    if ($attendanceCount === 0) {
        $today = date('F j, Y');
        $attendance = [
            ['2026-001', 'John Cruz', 'BSCS', $today, 'Programming 1', '7:58 AM', '10:00 AM', 'Present'],
            ['2026-002', 'Maria Santos', 'BSIT', $today, 'Database', '8:15 AM', '10:05 AM', 'Late'],
            ['2026-003', 'Peter Ramos', 'BSOA', $today, 'Networking', '--', '--', 'Absent'],
        ];
        $statement = $db->prepare('INSERT INTO attendance (student_id, student_name, course, attendance_date, subject, time_in, time_out, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
        foreach ($attendance as $record) $statement->execute($record);
    }

    if ((int) $db->query('SELECT COUNT(*) FROM notification_settings')->fetchColumn() === 0) {
        $statement = $db->prepare('INSERT INTO notification_settings (setting_key, setting_value) VALUES (?, ?)');
        foreach (['absent' => 'true', 'late' => 'true', 'checkIn' => 'true'] as $key => $value) $statement->execute([$key, $value]);
    }
} catch (PDOException $error) {
    http_response_code(500);
    header('Content-Type: application/json');
    echo json_encode(['message' => 'SQLite could not be opened. Check PHP PDO SQLite support.']);
    exit;
}
