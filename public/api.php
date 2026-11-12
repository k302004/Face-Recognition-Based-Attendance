<?php

declare(strict_types=1);

session_start();
header('Content-Type: application/json');
set_error_handler(static function (int $severity, string $message, string $file, int $line): bool {
    throw new ErrorException($message, 0, $severity, $file, $line);
});
set_exception_handler(static function (Throwable $error): never {
    http_response_code(500);
    echo json_encode([
        'message' => 'The server encountered an error while processing your request.',
        'details' => $error->getMessage(),
        'file' => $error->getFile(),
        'line' => $error->getLine(),
    ], JSON_THROW_ON_ERROR);
    exit;
});
register_shutdown_function(static function (): void {
    $error = error_get_last();
    if (! $error) {
        return;
    }
    $fatalErrors = [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR, E_USER_ERROR];
    if (! in_array($error['type'], $fatalErrors, true)) {
        return;
    }
    http_response_code(500);
    echo json_encode([
        'message' => 'The server encountered a fatal error while processing your request.',
        'details' => $error['message'],
        'file' => $error['file'],
        'line' => $error['line'],
    ], JSON_THROW_ON_ERROR);
});
require __DIR__.'/db.php';

function data(): array
{
    $value = json_decode(file_get_contents('php://input'), true);

    return is_array($value) ? $value : $_POST;
}
function reply(array $value, int $status = 200): never
{
    http_response_code($status);
    echo json_encode($value);
    exit;
}
function user(): array
{
    return $_SESSION['user'] ?? [];
}
function requireLogin(): void
{
    if (! user()) {
        reply(['message' => 'Login required.'], 401);
    }
}
function cameraPythonCandidates(): array
{
    if (stripos(PHP_OS, 'WIN') === 0) {
        $candidates = [];
        $localAppData = getenv('LOCALAPPDATA');
        if (! is_string($localAppData) || $localAppData === '') {
            $userProfile = getenv('USERPROFILE');
            if (is_string($userProfile) && $userProfile !== '') {
                $localAppData = $userProfile.DIRECTORY_SEPARATOR.'AppData'.DIRECTORY_SEPARATOR.'Local';
            }
        }
        if (is_string($localAppData) && $localAppData !== '') {
            foreach ([
                $localAppData.DIRECTORY_SEPARATOR.'Microsoft'.DIRECTORY_SEPARATOR.'WindowsApps'.DIRECTORY_SEPARATOR.'PythonSoftwareFoundation.Python.*'.DIRECTORY_SEPARATOR.'python.exe',
                $localAppData.DIRECTORY_SEPARATOR.'Programs'.DIRECTORY_SEPARATOR.'Python'.DIRECTORY_SEPARATOR.'Python*'.DIRECTORY_SEPARATOR.'python.exe',
            ] as $pattern) {
                foreach (glob($pattern) ?: [] as $candidate) {
                    $candidates[] = $candidate;
                }
            }
        }
        $candidates[] = 'python3';
        $candidates[] = 'python';
        $candidates = array_values(array_unique($candidates));

        $opencvCandidates = [];
        foreach ($candidates as $candidate) {
            $probe = shell_exec(escapeshellarg($candidate).' -c "import cv2" 2>nul && echo OK');
            if (trim((string) $probe) === 'OK') {
                $opencvCandidates[] = $candidate;
            }
        }

        return $opencvCandidates ?: $candidates;
    }

    foreach (['/usr/bin/python3', 'python3', 'python'] as $candidate) {
        $probe = shell_exec(escapeshellarg($candidate).' -c "import cv2" 2>/dev/null && echo OK');
        if (trim((string) $probe) === 'OK') {
            return [$candidate];
        }
    }

    return ['python3'];
}
function deviceToken(): string
{
    $configuredToken = getenv('ATTENDANCE_DEVICE_TOKEN');
    if ($configuredToken !== false && trim($configuredToken) !== '') {
        return trim($configuredToken);
    }
    $configPath = __DIR__.DIRECTORY_SEPARATOR.'device_config.php';
    if (is_file($configPath)) {
        $config = require $configPath;
        if (is_array($config) && ! empty($config['token'])) {
            return (string) $config['token'];
        }
    }

    return '';
}
function generateVerificationCode(): string
{
    return str_pad((string) random_int(0, 999999), 6, '0', STR_PAD_LEFT);
}
function sendVerificationEmail(string $recipient, string $code): bool
{
    $configPath = __DIR__.DIRECTORY_SEPARATOR.'mail-config.php';
    $config = is_file($configPath) ? require $configPath : [];
    if (! is_array($config) || empty($config['host']) || empty($config['username']) || empty($config['password'])) {
        return false;
    }

    $host = (string) $config['host'];
    $port = (int) ($config['port'] ?? 587);
    $encryption = strtolower((string) ($config['encryption'] ?? 'tls'));
    $from = (string) ($config['from'] ?? $config['username']);
    $fromName = (string) ($config['from_name'] ?? 'DRLCEFI Attendance');
    $remote = ($encryption === 'ssl' ? 'ssl://' : '').$host.':'.$port;
    $context = stream_context_create(['ssl' => ['verify_peer' => true, 'verify_peer_name' => true]]);
    $socket = @stream_socket_client($remote, $errorNumber, $errorMessage, 15, STREAM_CLIENT_CONNECT, $context);
    if (! $socket) {
        return false;
    }
    stream_set_timeout($socket, 15);

    $read = static function () use ($socket): string {
        $response = '';
        while (($line = fgets($socket, 515)) !== false) {
            $response .= $line;
            if (strlen($line) < 4 || $line[3] === ' ') {
                break;
            }
        }

        return $response;
    };
    $write = static function (string $command) use ($socket, $read): bool {
        fwrite($socket, $command."\r\n");

        return (int) substr($read(), 0, 3) < 400;
    };

    $ready = (int) substr($read(), 0, 3) < 400;
    $ready = $ready && $write('EHLO localhost');
    if ($ready && $encryption === 'tls') {
        $ready = $write('STARTTLS') && @stream_socket_enable_crypto($socket, true, STREAM_CRYPTO_METHOD_TLS_CLIENT);
        $ready = $ready && $write('EHLO localhost');
    }
    $ready = $ready && $write('AUTH LOGIN');
    $ready = $ready && $write(base64_encode((string) $config['username']));
    $ready = $ready && $write(base64_encode((string) $config['password']));
    $ready = $ready && $write('MAIL FROM:<'.$from.'>');
    $ready = $ready && $write('RCPT TO:<'.$recipient.'>');
    $ready = $ready && $write('DATA');
    if ($ready) {
        $subject = 'DRLCEFI password reset verification code';
        $body = "Your DRLCEFI verification code is: {$code}\r\n\r\nThis code expires in 15 minutes. If you did not request a password reset, you can ignore this email.";
        $message = 'From: '.$fromName.' <'.$from.">\r\n"
            .'To: <'.$recipient.">\r\n"
            .'Subject: '.$subject."\r\n"
            ."MIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n"
            .$body;
        $message = preg_replace('/^\./m', '..', $message)."\r\n.";
        fwrite($socket, $message."\r\n");
        $ready = (int) substr($read(), 0, 3) < 400;
    }
    $write('QUIT');
    fclose($socket);

    return $ready;
}
function audit(PDO $db, string $action): void
{
    $actor = user()['name'] ?? 'System';
    $statement = $db->prepare('INSERT INTO audit_logs (action, actor) VALUES (?, ?)');
    $statement->execute([$action, $actor]);
}
function scheduleTime(string $time): ?DateTime
{
    $date = DateTime::createFromFormat('Y-m-d g:i A', date('Y-m-d').' '.trim($time));

    return $date ?: null;
}
function markCompletedSchedulesAbsent(PDO $db): void
{
    $today = date('F j, Y');
    $day = date('l');
    $schedules = $db->prepare('SELECT subject, start_time, end_time, school_year FROM schedules WHERE day = ? AND is_archived = 0');
    $schedules->execute([$day]);
    $insert = $db->prepare('INSERT INTO attendance (student_id, student_name, course, attendance_date, subject, time_in, time_out, status, school_year) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)');
    foreach ($schedules->fetchAll() as $schedule) {
        $end = scheduleTime((string) $schedule['end_time']);
        if (! $end || new DateTime <= $end) {
            continue;
        }
        $students = $db->prepare('SELECT student_id, full_name, course, school_year FROM students WHERE is_archived = 0 AND school_year = ?');
        $students->execute([$schedule['school_year']]);
        foreach ($students->fetchAll() as $student) {
            $existing = $db->prepare('SELECT id FROM attendance WHERE student_id = ? AND attendance_date = ? AND subject = ? LIMIT 1');
            $existing->execute([$student['student_id'], $today, $schedule['subject']]);
            if (! $existing->fetch()) {
                $insert->execute([$student['student_id'], $student['full_name'], $student['course'], $today, $schedule['subject'], '--', '--', 'Absent', $student['school_year']]);
            }
        }
    }
}
function statusForScan(PDO $db, string $subject): string
{
    $schedule = $db->prepare('SELECT start_time FROM schedules WHERE subject = ? AND day = ? AND is_archived = 0 ORDER BY start_time LIMIT 1');
    $schedule->execute([$subject, date('l')]);
    $record = $schedule->fetch();
    if (! $record) {
        return 'Present';
    }
    $start = scheduleTime((string) $record['start_time']);

    return $start && new DateTime > $start ? 'Late' : 'Present';
}

$action = $_GET['action'] ?? '';
$method = $_SERVER['REQUEST_METHOD'];
$payload = data();

if ($method === 'POST' && $action === 'signup') {
    $name = trim((string) ($payload['name'] ?? ''));
    $email = strtolower(trim((string) ($payload['email'] ?? '')));
    $password = (string) ($payload['password'] ?? '');
    $role = 'Administrator';
    if ($name === '' || ! filter_var($email, FILTER_VALIDATE_EMAIL) || strlen($password) < 6) {
        reply(['message' => 'Please provide valid account details.'], 400);
    }
    try {
        $statement = $db->prepare('INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)');
        $statement->execute([$name, $email, password_hash($password, PASSWORD_DEFAULT), $role]);
        $_SESSION['user'] = ['id' => (int) $db->lastInsertId(), 'name' => $name, 'email' => $email, 'role' => $role, 'profileImage' => null];
        audit($db, 'Created account');
        reply(['user' => user()], 201);
    } catch (PDOException $error) {
        if (($error->errorInfo[0] ?? '') === '23000') {
            reply(['message' => 'An account with this email already exists.'], 409);
        }
        reply(['message' => 'Unable to create the account.'], 500);
    }
}

if ($method === 'POST' && $action === 'login') {
    $email = strtolower(trim((string) ($payload['email'] ?? '')));
    $statement = $db->prepare('SELECT id, name, email, role, password_hash, profile_image FROM users WHERE email = ? LIMIT 1');
    $statement->execute([$email]);
    $record = $statement->fetch();

    if (! $record) {
        reply(['message' => 'Incorrect email or password.'], 401);
    }

    $attemptStatement = $db->prepare('SELECT failed_attempts, locked_until FROM login_attempts WHERE email = ? LIMIT 1');
    $attemptStatement->execute([$email]);
    $attemptRecord = $attemptStatement->fetch();

    $now = time();
    if ($attemptRecord && (int) $attemptRecord['locked_until'] > $now) {
        reply(['message' => 'Too many failed attempts. Please try again in 60 seconds.', 'retryAfter' => (int) $attemptRecord['locked_until'] - $now], 429);
    }

    if (! password_verify((string) ($payload['password'] ?? ''), $record['password_hash'])) {
        $failedAttempts = $attemptRecord ? ((int) $attemptRecord['failed_attempts'] + 1) : 1;
        $lockedUntil = 0;

        if ($failedAttempts >= 3) {
            $lockedUntil = $now + 60;
            $failedAttempts = 3;
            $db->prepare('INSERT INTO login_attempts (email, failed_attempts, locked_until, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(email) DO UPDATE SET failed_attempts = excluded.failed_attempts, locked_until = excluded.locked_until, updated_at = excluded.updated_at')
                ->execute([$email, $failedAttempts, $lockedUntil, date('c')]);
            reply(['message' => 'Too many failed attempts. Please try again in 60 seconds.', 'retryAfter' => 60], 429);
        }

        $db->prepare('INSERT INTO login_attempts (email, failed_attempts, locked_until, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(email) DO UPDATE SET failed_attempts = excluded.failed_attempts, locked_until = excluded.locked_until, updated_at = excluded.updated_at')
            ->execute([$email, $failedAttempts, $lockedUntil, date('c')]);

        reply(['message' => 'Incorrect email or password.'], 401);
    }

    $db->prepare('DELETE FROM login_attempts WHERE email = ?')->execute([$email]);

    $_SESSION['user'] = ['id' => (int) $record['id'], 'name' => $record['name'], 'email' => $record['email'], 'role' => $record['role'], 'profileImage' => $record['profile_image']];
    reply(['user' => user()]);
}

if ($action === 'me') {
    requireLogin();
    $statement = $db->prepare('SELECT id, name, email, role, profile_image FROM users WHERE email = ? LIMIT 1');
    $statement->execute([user()['email'] ?? '']);
    $record = $statement->fetch();
    if ($record) {
        $_SESSION['user'] = ['id' => (int) $record['id'], 'name' => $record['name'], 'email' => $record['email'], 'role' => $record['role'], 'profileImage' => $record['profile_image']];
    }
    reply(['user' => user()]);
}

if ($method === 'POST' && $action === 'record-attendance') {
    requireLogin();
    $studentId = trim((string) ($payload['studentId'] ?? ''));
    $subject = trim((string) ($payload['subject'] ?? ''));
    markCompletedSchedulesAbsent($db);
    if ($subject === '') {
        // Use today's first active schedule, or a default.
        $scheduleStatement = $db->prepare('SELECT subject FROM schedules WHERE day = ? AND is_archived = 0 ORDER BY start_time LIMIT 1');
        $scheduleStatement->execute([date('l')]);
        $scheduleRecord = $scheduleStatement->fetch();
        $subject = $scheduleRecord ? (string) $scheduleRecord['subject'] : 'General';
    }
    $status = statusForScan($db, $subject);
    $timeIn = date('g:i A');
    $timeOut = '--';
    if ($studentId === '' || ! in_array($status, ['Present', 'Late'], true)) {
        reply(['message' => 'studentId and a valid status are required.'], 400);
    }
    $studentStatement = $db->prepare('SELECT student_id, full_name, course, school_year, parent_phone FROM students WHERE student_id = ? AND is_archived = 0 LIMIT 1');
    $studentStatement->execute([$studentId]);
    $student = $studentStatement->fetch();
    if (! $student) {
        reply(['message' => 'Student was not found or is archived.'], 404);
    }
    $attendanceDate = date('F j, Y');
    $duplicateStatement = $db->prepare('SELECT id FROM attendance WHERE student_id = ? AND attendance_date = ? AND subject = ? LIMIT 1');
    $duplicateStatement->execute([$studentId, $attendanceDate, $subject]);
    $existingAttendance = $duplicateStatement->fetch();
    if ($existingAttendance) {
        $timeOut = date('g:i A');
        $update = $db->prepare("UPDATE attendance SET time_out = ? WHERE id = ? AND (time_out = '--' OR time_out = '')");
        $update->execute([$timeOut, $existingAttendance['id']]);
        if ($update->rowCount() === 0) {
            reply(['message' => 'Time out already recorded for this student and subject today.', 'studentId' => $studentId, 'studentName' => $student['full_name'], 'action' => 'already_recorded']);
        }
        audit($db, 'Recorded time out for '.$studentId);
        reply(['message' => 'Time out recorded.', 'studentId' => $studentId, 'studentName' => $student['full_name'], 'parentPhone' => $student['parent_phone'], 'date' => $attendanceDate, 'timeOut' => $timeOut, 'action' => 'time_out']);
    }
    $statement = $db->prepare('INSERT INTO attendance (student_id, student_name, course, attendance_date, subject, time_in, time_out, status, school_year) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)');
    $statement->execute([$student['student_id'], $student['full_name'], $student['course'], $attendanceDate, $subject, $timeIn, $timeOut, $status, $student['school_year']]);
    audit($db, 'Recorded '.$status.' attendance for '.$studentId);
    reply(['message' => 'Attendance recorded.', 'studentId' => $studentId, 'studentName' => $student['full_name'], 'parentPhone' => $student['parent_phone'], 'date' => $attendanceDate, 'timeIn' => $timeIn, 'subject' => $subject, 'status' => $status, 'action' => 'time_in']);
}

if ($method === 'POST' && $action === 'device-attendance') {
    $configuredToken = deviceToken();
    $requestToken = $_SERVER['HTTP_X_DEVICE_TOKEN'] ?? ($payload['deviceToken'] ?? '');
    if ($configuredToken === '' || ! is_string($requestToken) || ! hash_equals($configuredToken, $requestToken)) {
        reply(['message' => 'Invalid device token.'], 401);
    }

    $studentId = trim((string) ($payload['studentId'] ?? ''));
    $subject = trim((string) ($payload['subject'] ?? ''));
    markCompletedSchedulesAbsent($db);
    $status = statusForScan($db, $subject);
    $timeIn = date('g:i A');
    $timeOut = trim((string) ($payload['timeOut'] ?? '--'));
    if ($studentId === '' || $subject === '' || ! in_array($status, ['Present', 'Late'], true)) {
        reply(['message' => 'studentId, subject, and a valid status are required.'], 400);
    }

    $studentStatement = $db->prepare('SELECT student_id, full_name, course, school_year, parent_phone FROM students WHERE student_id = ? AND is_archived = 0 LIMIT 1');
    $studentStatement->execute([$studentId]);
    $student = $studentStatement->fetch();
    if (! $student) {
        reply(['message' => 'Student was not found or is archived.'], 404);
    }

    $attendanceDate = date('F j, Y');
    $duplicateStatement = $db->prepare('SELECT id FROM attendance WHERE student_id = ? AND attendance_date = ? AND subject = ? LIMIT 1');
    $duplicateStatement->execute([$studentId, $attendanceDate, $subject]);
    $existingAttendance = $duplicateStatement->fetch();
    if ($existingAttendance) {
        $timeOut = date('g:i A');
        $update = $db->prepare("UPDATE attendance SET time_out = ? WHERE id = ? AND (time_out = '--' OR time_out = '')");
        $update->execute([$timeOut, $existingAttendance['id']]);
        if ($update->rowCount() === 0) {
            reply(['message' => 'Time out already recorded for this student and subject today.'], 409);
        }
        audit($db, 'Device recorded time out for '.$studentId);
        reply(['message' => 'Time out recorded.', 'studentId' => $studentId, 'studentName' => $student['full_name'], 'parentPhone' => $student['parent_phone'], 'date' => $attendanceDate, 'timeOut' => $timeOut, 'action' => 'time_out']);
    }

    $statement = $db->prepare('INSERT INTO attendance (student_id, student_name, course, attendance_date, subject, time_in, time_out, status, school_year) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)');
    $statement->execute([$student['student_id'], $student['full_name'], $student['course'], $attendanceDate, $subject, $timeIn, $timeOut, $status, $student['school_year']]);
    audit($db, 'Device recorded '.$status.' attendance for '.$studentId);
    reply(['message' => 'Attendance recorded.', 'studentId' => $studentId, 'studentName' => $student['full_name'], 'parentPhone' => $student['parent_phone'], 'date' => $attendanceDate]);
}

if ($method === 'POST' && $action === 'logout') {
    $_SESSION = [];
    session_destroy();
    reply(['message' => 'Logged out.']);
}

if ($method === 'POST' && $action === 'request-password-reset') {
    $email = strtolower(trim((string) ($payload['email'] ?? '')));
    if (! filter_var($email, FILTER_VALIDATE_EMAIL)) {
        reply(['message' => 'Please provide a valid email address.'], 400);
    }

    $statement = $db->prepare('SELECT id, name, email FROM users WHERE email = ? LIMIT 1');
    $statement->execute([$email]);
    $user = $statement->fetch();

    if ($user) {
        $db->prepare('DELETE FROM password_reset_tokens WHERE email = ?')->execute([$email]);
        $code = generateVerificationCode();
        $expiresAt = time() + 900;
        $tokenStatement = $db->prepare('INSERT INTO password_reset_tokens (user_id, email, token_hash, expires_at) VALUES (?, ?, ?, ?)');
        $tokenStatement->execute([(int) $user['id'], $email, password_hash($code, PASSWORD_DEFAULT), $expiresAt]);

        $sent = sendVerificationEmail($email, $code);
        if (! $sent) {
            error_log('Password reset email delivery failed for: '.$email);
            audit($db, 'Password reset email delivery failed for '.$email);
            reply(['message' => 'Unable to send the verification code right now. Please check the email configuration and try again.'], 500);
        }
    }

    reply(['message' => 'If that account exists, a 6-digit verification code has been sent to your email.']);
}

if ($method === 'POST' && $action === 'reset-password') {
    $email = strtolower(trim((string) ($payload['email'] ?? '')));
    $code = trim((string) ($payload['code'] ?? ''));
    $newPassword = (string) ($payload['newPassword'] ?? '');

    if (! filter_var($email, FILTER_VALIDATE_EMAIL)) {
        reply(['message' => 'A valid email address is required.'], 400);
    }
    if (! preg_match('/^[0-9]{6}$/', $code)) {
        reply(['message' => 'Please enter the 6-digit verification code.'], 400);
    }
    if (strlen($newPassword) < 6) {
        reply(['message' => 'The new password must be at least 6 characters.'], 400);
    }

    $tokenStatement = $db->prepare('SELECT id, token_hash, expires_at FROM password_reset_tokens WHERE email = ? ORDER BY expires_at DESC LIMIT 1');
    $tokenStatement->execute([$email]);
    $tokenRecord = $tokenStatement->fetch();

    if (! $tokenRecord || ! password_verify($code, (string) $tokenRecord['token_hash']) || (int) $tokenRecord['expires_at'] < time()) {
        reply(['message' => 'The verification code is invalid or has expired. Please request a new one.'], 400);
    }

    $db->prepare('UPDATE users SET password_hash = ? WHERE email = ?')->execute([password_hash($newPassword, PASSWORD_DEFAULT), $email]);
    $db->prepare('DELETE FROM password_reset_tokens WHERE email = ?')->execute([$email]);
    audit($db, 'Reset password for '.$email);
    reply(['message' => 'Your password has been updated successfully.']);
}

requireLogin();

if ($method === 'POST' && $action === 'profile') {
    $name = trim((string) ($payload['name'] ?? ''));
    $profileImage = (string) ($payload['profileImage'] ?? '');
    if ($name === '') {
        reply(['message' => 'A full name is required.'], 400);
    }
    if ($profileImage !== '' && ! preg_match('/^data:image\/(jpeg|png|webp);base64,([A-Za-z0-9+\/=]+)$/', $profileImage, $matches)) {
        reply(['message' => 'Please upload a valid JPG, PNG, or WebP image.'], 400);
    }
    if ($profileImage !== '' && strlen($profileImage) > 2 * 1024 * 1024 * 1.4) {
        reply(['message' => 'The profile photo must be 2 MB or smaller.'], 400);
    }
    $statement = $db->prepare('UPDATE users SET name = ?, profile_image = ? WHERE id = ?');
    $statement->execute([$name, $profileImage !== '' ? $profileImage : (user()['profileImage'] ?? null), user()['id']]);
    $_SESSION['user']['name'] = $name;
    if ($profileImage !== '') {
        $_SESSION['user']['profileImage'] = $profileImage;
    }
    audit($db, 'Updated administrator profile');
    reply(['user' => user(), 'message' => 'Profile saved.']);
}

if ($method === 'POST' && $action === 'password') {
    $currentPassword = (string) ($payload['currentPassword'] ?? '');
    $newPassword = (string) ($payload['newPassword'] ?? '');
    if (strlen($newPassword) < 6) {
        reply(['message' => 'The new password must be at least 6 characters.'], 400);
    }
    $statement = $db->prepare('SELECT password_hash FROM users WHERE id = ? LIMIT 1');
    $statement->execute([user()['id'] ?? 0]);
    $record = $statement->fetch();
    if (! $record || ! password_verify($currentPassword, $record['password_hash'])) {
        reply(['message' => 'The current password is incorrect.'], 400);
    }
    $statement = $db->prepare('UPDATE users SET password_hash = ? WHERE id = ?');
    $statement->execute([password_hash($newPassword, PASSWORD_DEFAULT), user()['id']]);
    audit($db, 'Changed administrator password');
    reply(['message' => 'Password changed successfully.']);
}

if ($method === 'GET' && $action === 'dashboard') {
    markCompletedSchedulesAbsent($db);
    $students = $db->query('SELECT id, student_id, full_name, course, year, age, school_year, status, parent_phone, is_archived, archived_school_year, face_image_path FROM students ORDER BY full_name COLLATE NOCASE')->fetchAll();
    $schedules = $db->query('SELECT id, subject, instructor, room, day, start_time, end_time, school_year, is_archived, archived_school_year FROM schedules ORDER BY day, start_time')->fetchAll();
    $attendance = $db->query('SELECT student_id, student_name, course, attendance_date, subject, time_in, time_out, status, school_year, is_archived, archived_school_year FROM attendance ORDER BY id')->fetchAll();
    $audit = $db->query('SELECT action, actor, created_at FROM audit_logs ORDER BY id DESC LIMIT 20')->fetchAll();
    $settings = $db->query('SELECT setting_key, setting_value FROM notification_settings')->fetchAll();
    $notificationSettings = [];
    foreach ($settings as $setting) {
        $notificationSettings[$setting['setting_key']] = $setting['setting_value'] === 'true';
    }
    reply(['students' => $students, 'schedules' => $schedules, 'attendance' => $attendance, 'audit' => $audit, 'notificationSettings' => $notificationSettings]);
}

if ($method === 'POST' && $action === 'student') {
    if ((user()['role'] ?? '') !== 'Administrator') {
        reply(['message' => 'Administrator permission required.'], 403);
    }
    $studentId = trim((string) ($payload['studentId'] ?? ''));
    $fullName = trim((string) ($payload['fullName'] ?? ''));
    $course = trim((string) ($payload['course'] ?? ''));
    $year = trim((string) ($payload['year'] ?? ''));
    $age = (int) ($payload['age'] ?? 0);
    if ($age <= 0) {
        $age = null;
    }
    $status = trim((string) ($payload['status'] ?? ''));
    $existingId = trim((string) ($payload['id'] ?? ''));

    if ($studentId === '') {
        reply(['message' => 'Student ID is required.'], 400);
    }
    if ($fullName === '') {
        reply(['message' => 'Full name is required.'], 400);
    }
    if ($course === '') {
        reply(['message' => 'Course is required.'], 400);
    }
    if ($year === '') {
        reply(['message' => 'Year is required.'], 400);
    }
    if ($status === '') {
        reply(['message' => 'Status is required.'], 400);
    }

    $schoolYear = trim((string) ($payload['schoolYear'] ?? ''));
    if (! preg_match('/^\d{4}-\d{4}$/', $schoolYear) || (int) substr($schoolYear, 5) !== (int) substr($schoolYear, 0, 4) + 1) {
        reply(['message' => 'Please provide a valid school year, such as 2026-2027.'], 400);
    }
    $parentPhone = trim((string) ($payload['parentPhone'] ?? ''));
    $phoneDigits = preg_replace('/\D+/', '', $parentPhone);
    if (strlen($phoneDigits) < 7 || strlen($phoneDigits) > 15) {
        reply(['message' => 'Please provide a valid parent phone number.'], 400);
    }
    if (str_starts_with($phoneDigits, '63')) {
        $parentPhone = '+'.$phoneDigits;
    } elseif (str_starts_with($phoneDigits, '0')) {
        $parentPhone = '+63'.substr($phoneDigits, 1);
    } else {
        $parentPhone = '+'.$phoneDigits;
    }
    $imageDirectory = __DIR__.DIRECTORY_SEPARATOR.'face_images';
    if (! is_dir($imageDirectory) && ! mkdir($imageDirectory, 0755, true)) {
        reply(['message' => 'Unable to create the face photo folder.'], 500);
    }
    $relativeImagePaths = [];

    $facePhotos = [];
    if (isset($payload['facePhotos']) && is_array($payload['facePhotos'])) {
        $facePhotos = $payload['facePhotos'];
    } elseif (isset($payload['facePhoto']) && (string) $payload['facePhoto'] !== '') {
        $facePhotos = [(string) $payload['facePhoto']];
    }

    $photoIndex = 0;
    foreach ($facePhotos as $facePhoto) {
        $facePhoto = (string) $facePhoto;
        if ($facePhoto === '') {
            continue;
        }
        if (! preg_match('/^data:image\/(jpeg|png|webp);base64,([A-Za-z0-9+\/=]+)$/', $facePhoto, $matches)) {
            reply(['message' => 'Please provide a valid face photo (JPG, PNG, or WebP).'], 400);
        }
        $imageData = base64_decode($matches[2], true);
        if ($imageData === false || strlen($imageData) > 5 * 1024 * 1024) {
            reply(['message' => 'The face photo must be 5 MB or smaller.'], 400);
        }
        $imageInfo = @getimagesizefromstring($imageData);
        if (! $imageInfo || ! in_array($imageInfo['mime'], ['image/jpeg', 'image/png', 'image/webp'], true)) {
            reply(['message' => 'The face photo is not a supported image.'], 400);
        }
        $extension = $matches[1] === 'jpeg' ? 'jpg' : $matches[1];
        $imageName = hash('sha256', $studentId.'_'.$photoIndex).'.'.$extension;
        $imagePath = $imageDirectory.DIRECTORY_SEPARATOR.$imageName;
        if (file_put_contents($imagePath, $imageData) === false) {
            reply(['message' => 'Unable to save the face photo.'], 500);
        }
        $relativeImagePaths[] = 'face_images/'.$imageName;
        $photoIndex++;
    }
    $relativeImagePath = $relativeImagePaths ? implode(',', $relativeImagePaths) : null;

    if ($existingId !== '') {
        $existingStudent = $db->prepare('SELECT student_id, face_image_path FROM students WHERE id = ? LIMIT 1');
        $existingStudent->execute([$existingId]);
        $existingRecord = $existingStudent->fetch();
        if (! $existingRecord) {
            reply(['message' => 'Student not found.'], 404);
        }
        $newStudentId = $studentId !== '' ? $studentId : (string) $existingRecord['student_id'];
        $fields = 'student_id = ?, full_name = ?, course = ?, year = ?, age = ?, school_year = ?, status = ?, parent_phone = ?';
        $parameters = [$newStudentId, $fullName, $course, $year, $age, $schoolYear, $status, $parentPhone];
        if ($relativeImagePath !== null) {
            $fields .= ', face_image_path = ?';
            $parameters[] = $relativeImagePath;
        }
        $parameters[] = $existingId;
        $statement = $db->prepare('UPDATE students SET '.$fields.' WHERE id = ?');
        $statement->execute($parameters);
        audit($db, 'Updated student '.$newStudentId);
        reply(['message' => 'Student updated.']);
    }

    $statement = $db->prepare('INSERT INTO students (student_id, full_name, course, year, age, school_year, status, parent_phone, face_image_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)');
    try {
        $statement->execute([$studentId, $fullName, $course, $year, $age, $schoolYear, $status, $parentPhone, $relativeImagePath ?? '']);
    } catch (PDOException $error) {
        if ($relativeImagePath !== null) {
            $imagePath = $imageDirectory.DIRECTORY_SEPARATOR.basename($relativeImagePath);
            @unlink($imagePath);
        }
        if (($error->errorInfo[0] ?? '') === '23000') {
            reply(['message' => 'A student with this ID already exists.'], 409);
        }
        reply(['message' => 'Unable to add the student: '.$error->getMessage()], 500);
    }
    audit($db, 'Added student '.$studentId);
    reply(['message' => 'Student added.']);
}

if ($method === 'POST' && $action === 'archive-student') {
    if ((user()['role'] ?? '') !== 'Administrator') {
        reply(['message' => 'Administrator permission required.'], 403);
    }
    $value = (int) ($payload['archived'] ?? 0);
    $statement = $db->prepare('UPDATE students SET is_archived = ? WHERE student_id = ?');
    $statement->execute([$value, $payload['studentId']]);
    audit($db, ($value ? 'Archived ' : 'Restored ').'student '.$payload['studentId']);
    reply(['message' => 'Student updated.']);
}

if ($method === 'POST' && $action === 'delete-student') {
    if ((user()['role'] ?? '') !== 'Administrator') {
        reply(['message' => 'Administrator permission required.'], 403);
    }
    $studentId = trim((string) ($payload['studentId'] ?? ''));
    if ($studentId === '') {
        reply(['message' => 'Student ID is required.'], 400);
    }

    // Get student's face image path before deleting
    $statement = $db->prepare('SELECT face_image_path FROM students WHERE student_id = ? LIMIT 1');
    $statement->execute([$studentId]);
    $student = $statement->fetch();

    if ($student && ! empty($student['face_image_path'])) {
        foreach (explode(',', (string) $student['face_image_path']) as $path) {
            $path = trim($path);
            $path = ltrim($path, '/\\\\');
            if ($path === '') {
                continue;
            }
            $imagePath = __DIR__.DIRECTORY_SEPARATOR.$path;
            if (is_file($imagePath)) {
                @unlink($imagePath);
            }
        }
    }

    // Also clean up any orphaned face images matching this student's ID hash.
    $imageDirectory = __DIR__.DIRECTORY_SEPARATOR.'face_images';
    if (is_dir($imageDirectory)) {
        foreach (glob($imageDirectory.DIRECTORY_SEPARATOR.'*') as $file) {
            // Image filenames are sha256(studentId_index).ext — check by re-hashing.
            $basename = pathinfo($file, PATHINFO_FILENAME);
            for ($i = 0; $i < 10; $i++) {
                if (hash('sha256', $studentId.'_'.$i) === $basename) {
                    @unlink($file);
                    break;
                }
            }
        }
    }

    // Delete student from database
    $statement = $db->prepare('DELETE FROM students WHERE student_id = ?');
    $statement->execute([$studentId]);

    // Also delete related attendance records
    $attendanceStatement = $db->prepare('DELETE FROM attendance WHERE student_id = ?');
    $attendanceStatement->execute([$studentId]);

    audit($db, 'Deleted student '.$studentId);
    reply(['message' => 'Student deleted successfully.']);
}

if ($method === 'POST' && $action === 'archive-year') {
    if ((user()['role'] ?? '') !== 'Administrator') {
        reply(['message' => 'Administrator permission required.'], 403);
    }
    $schoolYear = trim((string) ($payload['schoolYear'] ?? ''));
    $course = trim((string) ($payload['course'] ?? ''));
    if ($schoolYear === '') {
        reply(['message' => 'A school year is required.'], 400);
    }
    $studentQuery = 'UPDATE students SET is_archived = 1, archived_school_year = ? WHERE is_archived = 0 AND school_year = ?';
    $studentParameters = [$schoolYear, $schoolYear];
    if ($course !== '') {
        $studentQuery .= ' AND course = ?';
        $studentParameters[] = $course;
    }
    $db->prepare($studentQuery)->execute($studentParameters);

    $attendanceQuery = 'UPDATE attendance SET is_archived = 1, school_year = ?, archived_school_year = ? WHERE is_archived = 0 AND student_id IN (SELECT student_id FROM students WHERE school_year = ?';
    $attendanceParameters = [$schoolYear, $schoolYear, $schoolYear];
    if ($course !== '') {
        $attendanceQuery .= ' AND course = ?';
        $attendanceParameters[] = $course;
    }
    $attendanceQuery .= ')';
    $db->prepare($attendanceQuery)->execute($attendanceParameters);

    if ($course === '') {
        $db->prepare('UPDATE schedules SET is_archived = 1, archived_school_year = ? WHERE is_archived = 0 AND school_year = ?')->execute([$schoolYear, $schoolYear]);
    }
    audit($db, 'Archived '.($course !== '' ? $course.' students for ' : 'students for ').$schoolYear);
    reply(['message' => 'Selected records archived for '.$schoolYear.($course !== '' ? ' ('.$course.')' : '').'.']);
}

if ($method === 'POST' && $action === 'archive-attendance-date') {
    if ((user()['role'] ?? '') !== 'Administrator') {
        reply(['message' => 'Administrator permission required.'], 403);
    }
    $dateKey = trim((string) ($payload['date'] ?? ''));
    $schoolYear = trim((string) ($payload['schoolYear'] ?? ''));
    $date = DateTime::createFromFormat('!Y-m-d', $dateKey);
    if (! $date || $date->format('Y-m-d') !== $dateKey) {
        reply(['message' => 'A valid attendance date is required.'], 400);
    }
    if (! preg_match('/^\d{4}-\d{4}$/', $schoolYear) || (int) substr($schoolYear, 5) !== (int) substr($schoolYear, 0, 4) + 1) {
        reply(['message' => 'A valid school year is required.'], 400);
    }
    $displayDate = $date->format('F j, Y');
    $statement = $db->prepare('UPDATE attendance SET is_archived = 1, school_year = ?, archived_school_year = ? WHERE attendance_date = ? AND is_archived = 0');
    $statement->execute([$schoolYear, $schoolYear, $displayDate]);
    audit($db, 'Archived attendance for '.$displayDate.' ('.$schoolYear.')');
    reply(['message' => 'Attendance archived for '.$displayDate.'.']);
}

if ($method === 'POST' && $action === 'restore-year') {
    if ((user()['role'] ?? '') !== 'Administrator') {
        reply(['message' => 'Administrator permission required.'], 403);
    }
    $schoolYear = trim((string) ($payload['schoolYear'] ?? ''));
    if ($schoolYear === '') {
        reply(['message' => 'A school year is required.'], 400);
    }
    $statement = $db->prepare('UPDATE students SET is_archived = 0, archived_school_year = NULL WHERE archived_school_year = ?');
    $statement->execute([$schoolYear]);
    $attendanceStatement = $db->prepare('UPDATE attendance SET is_archived = 0, archived_school_year = NULL WHERE archived_school_year = ?');
    $attendanceStatement->execute([$schoolYear]);
    $scheduleStatement = $db->prepare('UPDATE schedules SET is_archived = 0, archived_school_year = NULL WHERE archived_school_year = ?');
    $scheduleStatement->execute([$schoolYear]);
    audit($db, 'Restored students for school year '.$schoolYear);
    reply(['message' => 'Students restored for '.$schoolYear.'.']);
}

if ($method === 'POST' && $action === 'schedule') {
    if ((user()['role'] ?? '') !== 'Administrator') {
        reply(['message' => 'Administrator permission required.'], 403);
    }
    $schoolYear = trim((string) ($payload['schoolYear'] ?? ''));
    if (! preg_match('/^\d{4}-\d{4}$/', $schoolYear) || (int) substr($schoolYear, 5) !== (int) substr($schoolYear, 0, 4) + 1) {
        reply(['message' => 'Please provide a valid school year, such as 2026-2027.'], 400);
    }
    if (! empty($payload['id'])) {
        $statement = $db->prepare('UPDATE schedules SET subject = ?, instructor = ?, room = ?, day = ?, start_time = ?, end_time = ?, school_year = ? WHERE id = ?');
        $statement->execute([$payload['subject'], $payload['teacher'], $payload['room'], $payload['day'], $payload['startTime'], $payload['endTime'], $schoolYear, $payload['id']]);
        audit($db, 'Updated schedule '.$payload['subject']);
    } else {
        $statement = $db->prepare('INSERT INTO schedules (subject, instructor, room, day, start_time, end_time, school_year) VALUES (?, ?, ?, ?, ?, ?, ?)');
        $statement->execute([$payload['subject'], $payload['teacher'], $payload['room'], $payload['day'], $payload['startTime'], $payload['endTime'], $schoolYear]);
        audit($db, 'Added schedule '.$payload['subject']);
    }
    reply(['message' => 'Schedule added.']);
}

if ($method === 'POST' && $action === 'delete-schedule') {
    if ((user()['role'] ?? '') !== 'Administrator') {
        reply(['message' => 'Administrator permission required.'], 403);
    }
    $statement = $db->prepare('DELETE FROM schedules WHERE id = ?');
    $statement->execute([$payload['id']]);
    audit($db, 'Deleted schedule');
    reply(['message' => 'Schedule deleted.']);
}

if ($method === 'POST' && $action === 'settings') {
    foreach (['absent', 'late', 'checkIn'] as $key) {
        $statement = $db->prepare('INSERT INTO notification_settings (setting_key, setting_value) VALUES (?, ?) ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value');
        $statement->execute([$key, ! empty($payload[$key]) ? 'true' : 'false']);
    }
    audit($db, 'Updated notification settings');
    reply(['message' => 'Settings saved.']);
}

if ($method === 'GET' && $action === 'camera-list') {
    $script = dirname(__DIR__).DIRECTORY_SEPARATOR.'scripts'.DIRECTORY_SEPARATOR.'list_cameras.py';
    $output = '';
    foreach (cameraPythonCandidates() as $python) {
        $command = escapeshellarg($python).' '.escapeshellarg($script);
        $output = shell_exec($command);
        $decoded = json_decode((string) $output, true);
        if (is_array($decoded) && isset($decoded['cameras']) && is_array($decoded['cameras'])) {
            reply(['cameras' => $decoded['cameras']]);
        }
    }
    reply(['message' => 'Unable to detect cameras.', 'details' => trim((string) $output)], 500);
}

if ($method === 'GET' && $action === 'camera-config') {
    $path = __DIR__.DIRECTORY_SEPARATOR.'camera.config';
    if (! is_file($path)) {
        reply(['config' => null]);
    }
    $content = file_get_contents($path);
    $decoded = json_decode((string) $content, true);
    reply(['config' => is_array($decoded) ? $decoded : null]);
}

if ($method === 'POST' && $action === 'camera-save') {
    $cameraId = trim((string) ($payload['id'] ?? ''));
    $cameraName = trim((string) ($payload['name'] ?? ''));
    if ($cameraId === '' || $cameraName === '') {
        reply(['message' => 'Camera id and name are required.'], 400);
    }
    $config = [
        'id' => $cameraId,
        'name' => $cameraName,
        'modelId' => $payload['modelId'] ?? null,
        'uniqueId' => $payload['uniqueId'] ?? null,
        'savedAt' => date('c'),
    ];
    $path = __DIR__.DIRECTORY_SEPARATOR.'camera.config';
    if (file_put_contents($path, json_encode($config, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES)) === false) {
        reply(['message' => 'Unable to save camera config.'], 500);
    }
    reply(['message' => 'Camera saved.', 'config' => $config]);
}

if ($method === 'POST' && $action === 'camera-stream-start') {
    $pidFile = dirname(__DIR__).DIRECTORY_SEPARATOR.'storage'.DIRECTORY_SEPARATOR.'framework'.DIRECTORY_SEPARATOR.'camera_stream.pid';
    $logFile = dirname(__DIR__).DIRECTORY_SEPARATOR.'storage'.DIRECTORY_SEPARATOR.'logs'.DIRECTORY_SEPARATOR.'camera_stream.log';
    $errorLogFile = dirname(__DIR__).DIRECTORY_SEPARATOR.'storage'.DIRECTORY_SEPARATOR.'logs'.DIRECTORY_SEPARATOR.'camera_stream_error.log';
    $launchErrorLogFile = dirname(__DIR__).DIRECTORY_SEPARATOR.'storage'.DIRECTORY_SEPARATOR.'logs'.DIRECTORY_SEPARATOR.'camera_stream_launch_error.log';
    $script = dirname(__DIR__).DIRECTORY_SEPARATOR.'scripts'.DIRECTORY_SEPARATOR.'camera_stream.py';

    if (is_file($pidFile)) {
        $existingPid = (int) trim((string) file_get_contents($pidFile));
        if ($existingPid > 0) {
            if (stripos(PHP_OS, 'WIN') === 0) {
                shell_exec('taskkill /PID '.$existingPid.' /T /F 2>nul');
            } else {
                shell_exec('kill '.$existingPid.' 2>/dev/null');
            }
        }
        @unlink($pidFile);
    }
    // Also stop any stray stream processes so the new dimensions take effect.
    if (stripos(PHP_OS, 'WIN') === 0) {
        shell_exec('taskkill /F /IM python.exe /FI "WINDOWTITLE eq camera_stream*" 2>nul');
    } else {
        shell_exec('pkill -f "[c]amera_stream.py" 2>/dev/null');
    }
    usleep(300000);

    $cameraIndex = 0;
    $configPath = __DIR__.DIRECTORY_SEPARATOR.'camera.config';
    if (is_file($configPath)) {
        $config = json_decode((string) file_get_contents($configPath), true);
        if (is_array($config) && isset($config['id']) && ctype_digit((string) $config['id'])) {
            $cameraIndex = (int) $config['id'];
        }
    }

    $port = 8090;
    $targetWidth = isset($payload['width']) ? (int) $payload['width'] : 720;
    $targetHeight = isset($payload['height']) ? (int) $payload['height'] : 1280;
    if ($targetWidth < 100) {
        $targetWidth = 720;
    }
    if ($targetHeight < 100) {
        $targetHeight = 1280;
    }

    $pidOutput = '';
    $pythonCandidates = cameraPythonCandidates();
    $python = $pythonCandidates[0] ?? 'python3';
    if (stripos(PHP_OS, 'WIN') === 0) {
        file_put_contents($logFile, '');
        file_put_contents($errorLogFile, '');
        file_put_contents($launchErrorLogFile, '');
        $quotePowerShell = static function (string $value): string {
            return "'".str_replace("'", "''", $value)."'";
        };
        $commandLine = 'cmd.exe /c ""'.$python.'" -u "'.$script.'" '
            .$cameraIndex.' '.$port.' '.$targetWidth.' '.$targetHeight
            .' > "'.$logFile.'" 2> "'.$errorLogFile.'""';
        $powershellScript = '$ErrorActionPreference = "Stop"; try { $startup = ([wmiclass]"Win32_ProcessStartup").CreateInstance(); $startup.ShowWindow = 0; $result = ([wmiclass]"Win32_Process").Create('
            .$quotePowerShell($commandLine).', '.$quotePowerShell(dirname(__DIR__)).', $startup); if ($result.ReturnValue -ne 0) { throw ("Unable to launch camera process: " + $result.ReturnValue) }; [System.IO.File]::WriteAllText('
            .$quotePowerShell($pidFile).', [string] $result.ProcessId) } catch { [System.IO.File]::WriteAllText('
            .$quotePowerShell($launchErrorLogFile).', $_.ToString()); exit 1 }';
        $encodedScript = iconv('UTF-8', 'UTF-16LE', $powershellScript);
        if ($encodedScript === false) {
            reply(['message' => 'Unable to prepare the camera startup command.'], 500);
        }
        $psCommand = 'powershell.exe -NoProfile -NonInteractive -EncodedCommand '.base64_encode($encodedScript).' >NUL 2>&1';
        shell_exec($psCommand);
        $pid = is_file($pidFile) ? (int) trim((string) file_get_contents($pidFile)) : 0;
    } else {
        $command = 'nohup '.$python.' '.escapeshellarg($script).' '.escapeshellarg((string) $cameraIndex).' '.escapeshellarg((string) $port)
            .' '.escapeshellarg((string) $targetWidth).' '.escapeshellarg((string) $targetHeight)
            .' > '.escapeshellarg($logFile).' 2>&1 & echo $!';
        $pidOutput = shell_exec($command);
        $pid = (int) trim((string) $pidOutput);
    }
    if ($pid > 0) {
        file_put_contents($pidFile, (string) $pid);
    }

    // Return immediately — don't block on stream startup.
    // The frontend will retry loading the feed until it's ready.
    $alive = $pid > 0;
    if (! $alive) {
        if (stripos(PHP_OS, 'WIN') === 0) {
            // On Windows, give the already-launched process more time, then check.
            usleep(5000000);
        } else {
            // macOS may block camera access for the web server process. Fall back to
            // launching the script in Terminal, which usually already has permission.
            if ($pid > 0) {
                shell_exec('kill '.$pid.' 2>/dev/null');
            }
            shell_exec('pkill -f "[c]amera_stream.py" 2>/dev/null');
            usleep(300000);
            $terminalCommand = 'cd '.escapeshellarg(dirname(__DIR__)).' && '.$python.' '.escapeshellarg($script).' '.escapeshellarg((string) $cameraIndex).' '.escapeshellarg((string) $port).' '.escapeshellarg((string) $targetWidth).' '.escapeshellarg((string) $targetHeight);
            $osascript = 'osascript -e '.escapeshellarg('tell application "Terminal" to do script '.json_encode($terminalCommand, JSON_UNESCAPED_SLASHES)).' >/dev/null 2>&1';
            shell_exec($osascript);
            usleep(5000000);
        }
        $healthCheck = shell_exec('curl -s -o '.escapeshellarg($nullDevice).' -w "%{http_code}" --max-time 2 '.$healthUrl.' '.$stderrRedirect);
        if (trim((string) $healthCheck) === '200') {
            reply(['message' => 'Camera stream started.', 'url' => 'http://127.0.0.1:'.$port.'/video_feed']);
        }

        $logTail = '';
        foreach ([$logFile, $errorLogFile, $launchErrorLogFile] as $cameraLogFile) {
            if (is_file($cameraLogFile)) {
                $cameraLog = trim((string) file_get_contents($cameraLogFile));
                if ($cameraLog !== '') {
                    $logTail .= ($logTail === '' ? '' : PHP_EOL).$cameraLog;
                }
            }
        }
        if ($logTail === '') {
            $logTail = trim((string) $pidOutput);
        }
        if (strlen($logTail) > 500) {
            $logTail = substr($logTail, -500);
        }
        if (is_file($pidFile)) {
            unlink($pidFile);
        }
        reply(['message' => 'Camera stream failed to start.', 'details' => $logTail], 500);
    }
    reply(['message' => 'Camera stream started.', 'pid' => $pid, 'url' => 'http://127.0.0.1:'.$port.'/video_feed']);
}

if ($method === 'POST' && $action === 'camera-stream-stop') {
    $pidFile = dirname(__DIR__).DIRECTORY_SEPARATOR.'storage'.DIRECTORY_SEPARATOR.'framework'.DIRECTORY_SEPARATOR.'camera_stream.pid';
    if (is_file($pidFile)) {
        $pid = (int) trim((string) file_get_contents($pidFile));
        if ($pid > 0) {
            if (stripos(PHP_OS, 'WIN') === 0) {
                shell_exec('taskkill /PID '.$pid.' /T /F 2>nul');
            } else {
                shell_exec('kill '.$pid.' 2>/dev/null');
            }
        }
        @unlink($pidFile);
    }
    if (stripos(PHP_OS, 'WIN') === 0) {
        shell_exec('taskkill /F /FI "WINDOWTITLE eq camera_stream*" 2>nul');
    } else {
        shell_exec('pkill -f "[c]amera_stream.py" 2>/dev/null');
    }
    reply(['message' => 'Camera stream stopped.']);
}

if ($method === 'GET' && $action === 'camera-pose') {
    $url = 'http://127.0.0.1:8090/face_pose';
    $response = @file_get_contents($url);
    if ($response === false) {
        reply(['pose' => 'none', 'message' => 'Camera stream is not running.'], 502);
    }
    $decoded = json_decode($response, true);
    reply(is_array($decoded) ? $decoded : ['pose' => 'none']);
}

if ($method === 'GET' && $action === 'camera-current-student') {
    $url = 'http://127.0.0.1:8090/current_student';
    $context = stream_context_create(['http' => ['timeout' => 2]]);
    $response = @file_get_contents($url, false, $context);
    if ($response === false) {
        reply(['student' => null, 'face_detected' => false, 'message' => 'Camera stream is not running.'], 502);
    }
    $decoded = json_decode($response, true);
    reply(is_array($decoded) ? $decoded : ['student' => null]);
}

if ($method === 'GET' && $action === 'face-events') {
    set_time_limit(0);
    header('Content-Type: text/event-stream');
    header('Cache-Control: no-cache');
    header('X-Accel-Buffering: no');
    while (ob_get_level() > 0) {
        ob_end_flush();
    }
    $context = stream_context_create(['http' => ['timeout' => 300]]);
    $stream = @fopen('http://127.0.0.1:8090/events', 'r', false, $context);
    if (!$stream) {
        echo "data: " . json_encode(['student' => null, 'face_detected' => false, 'message' => 'Camera stream is not running.']) . "\n\n";
        flush();
        exit;
    }
    while (!feof($stream)) {
        $line = fgets($stream);
        if ($line !== false) {
            echo $line;
            flush();
        }
    }
    fclose($stream);
    exit;
}

if ($method === 'GET' && $action === 'camera-feed') {
    $url = 'http://127.0.0.1:8090/video_feed';
    $stream = @fopen($url, 'r');
    if (! $stream) {
        http_response_code(502);
        echo json_encode(['message' => 'Camera stream is not running.']);
        exit;
    }
    foreach ($http_response_header as $header) {
        if (stripos($header, 'Content-Type:') === 0) {
            header($header);
        }
    }
    header('Cache-Control: no-cache, private');
    header('Pragma: no-cache');
    header('X-Accel-Buffering: no');
    while (ob_get_level() > 0) {
        ob_end_flush();
    }
    set_time_limit(0);
    fpassthru($stream);
    fclose($stream);
    exit;
}

reply(['message' => 'Unknown action.'], 404);
