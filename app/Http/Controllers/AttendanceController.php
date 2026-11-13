<?php

namespace App\Http\Controllers;

use App\Models\AuditLog;
use App\Services\SmsService;
use Illuminate\Database\Connection;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class AttendanceController extends Controller
{
    private function audit(string $action): void
    {
        AuditLog::create(['action' => $action, 'actor' => Auth::user()?->name ?? 'System', 'created_at' => now()->format('Y-m-d H:i:s')]);
    }

    private function db(): Connection
    {
        return DB::connection('attendance');
    }

    public function record(Request $request): JsonResponse
    {
        $studentId = trim((string) $request->input('studentId', ''));
        $subject = 'General';
        $attendanceAction = trim((string) $request->input('attendanceAction', 'time_in'));
        $status = 'Present';
        $timeIn = now()->format('g:i A');
        $timeOut = '--';
        if ($studentId === '') {
            return response()->json(['message' => 'studentId is required.'], 400);
        }
        $student = $this->db()->table('students')->where('student_id', $studentId)->where('is_archived', 0)->first();
        if (! $student) {
            return response()->json(['message' => 'Student was not found or is archived.'], 404);
        }
        $attendanceDate = now()->format('F j, Y');
        $open = $this->db()->table('attendance')
            ->where('student_id', $studentId)
            ->where('attendance_date', $attendanceDate)
            ->where('time_in', '<>', '--')
            ->where('time_in', '<>', '')
            ->where(function ($q) {
                $q->where('time_out', '--')->orWhere('time_out', '');
            })
            ->orderBy('id', 'desc')
            ->first();

        if ($attendanceAction === 'time_out') {
            if (! $open) {
                $exists = $this->db()->table('attendance')
                    ->where('student_id', $studentId)
                    ->where('attendance_date', $attendanceDate)
                    ->where('time_in', '<>', '--')
                    ->where('time_in', '<>', '')
                    ->first();
                if (! $exists) {
                    return response()->json(['message' => 'No open time in record found for this student today.', 'studentId' => $studentId, 'studentName' => $student->full_name, 'action' => 'no_time_in'], 200);
                }

                return response()->json(['message' => 'Time out already recorded for this student today.', 'studentId' => $studentId, 'studentName' => $student->full_name, 'action' => 'already_recorded', 'timeIn' => (string) ($exists->time_in ?? '--'), 'timeOut' => (string) ($exists->time_out ?? '--')], 200);
            }
            $timeOut = now()->format('g:i A');
            $affected = $this->db()->table('attendance')
                ->where('id', $open->id)
                ->where(function ($q) {
                    $q->where('time_out', '--')->orWhere('time_out', '');
                })
                ->update(['time_out' => $timeOut]);
            if ($affected === 0) {
                return response()->json(['message' => 'Time out already recorded for this student today.', 'studentId' => $studentId, 'studentName' => $student->full_name, 'action' => 'already_recorded', 'timeIn' => (string) ($open->time_in ?? '--'), 'timeOut' => (string) ($open->time_out ?? '--')], 200);
            }
            $this->audit('Recorded time out for '.$studentId);
            $this->sendAttendanceSms($student, 'time_out', $timeOut, $attendanceDate);

            return response()->json(['message' => 'Time out recorded.', 'studentId' => $studentId, 'studentName' => $student->full_name, 'parentPhone' => $student->parent_phone, 'date' => $attendanceDate, 'timeOut' => $timeOut, 'subject' => $subject, 'status' => $status, 'action' => 'time_out']);
        }

        if ($open) {
            return response()->json(['message' => 'Time in already recorded for this student today.', 'studentId' => $studentId, 'studentName' => $student->full_name, 'action' => 'already_recorded', 'timeIn' => (string) ($open->time_in ?? '--'), 'timeOut' => (string) ($open->time_out ?? '--')], 200);
        }
        $this->db()->table('attendance')->insert([
            'student_id' => $student->student_id,
            'student_name' => $student->full_name,
            'course' => $student->course,
            'attendance_date' => $attendanceDate,
            'subject' => $subject,
            'time_in' => $timeIn,
            'time_out' => $timeOut,
            'status' => $status,
            'school_year' => $student->school_year,
            'created_at' => now()->format('Y-m-d H:i:s'),
        ]);
        $this->audit('Recorded '.$status.' attendance for '.$studentId);
        $this->sendAttendanceSms($student, 'time_in', $timeIn, $attendanceDate);

        return response()->json(['message' => 'Attendance recorded.', 'studentId' => $studentId, 'studentName' => $student->full_name, 'parentPhone' => $student->parent_phone, 'date' => $attendanceDate, 'timeIn' => $timeIn, 'subject' => $subject, 'status' => $status, 'action' => 'time_in']);
    }

    public function device(Request $request): JsonResponse
    {
        $configuredToken = $this->deviceToken();
        $requestToken = (string) ($request->header('X-Device-Token') ?: $request->input('deviceToken', ''));
        if ($configuredToken === '' || ! hash_equals($configuredToken, $requestToken)) {
            return response()->json(['message' => 'Invalid device token.'], 401);
        }
        $studentId = trim((string) $request->input('studentId', ''));
        $subject = 'General';
        $status = 'Present';
        $timeIn = now()->format('g:i A');
        $timeOut = trim((string) $request->input('timeOut', '--'));
        if ($studentId === '') {
            return response()->json(['message' => 'studentId is required.'], 400);
        }
        $student = $this->db()->table('students')->where('student_id', $studentId)->where('is_archived', 0)->first();
        if (! $student) {
            return response()->json(['message' => 'Student was not found or is archived.'], 404);
        }
        $attendanceDate = now()->format('F j, Y');
        $open = $this->db()->table('attendance')
            ->where('student_id', $studentId)
            ->where('attendance_date', $attendanceDate)
            ->where('time_in', '<>', '--')
            ->where('time_in', '<>', '')
            ->where(function ($q) {
                $q->where('time_out', '--')->orWhere('time_out', '');
            })
            ->orderBy('id', 'desc')
            ->first();
        if ($open) {
            $timeOut = now()->format('g:i A');
            $affected = $this->db()->table('attendance')
                ->where('id', $open->id)
                ->where(function ($q) {
                    $q->where('time_out', '--')->orWhere('time_out', '');
                })
                ->update(['time_out' => $timeOut]);
            if ($affected === 0) {
                return response()->json(['message' => 'Time out already recorded for this student today.'], 409);
            }
            $this->audit('Device recorded time out for '.$studentId);

            return response()->json(['message' => 'Time out recorded.', 'studentId' => $studentId, 'studentName' => $student->full_name, 'parentPhone' => $student->parent_phone, 'date' => $attendanceDate, 'timeOut' => $timeOut, 'action' => 'time_out']);
        }
        $this->db()->table('attendance')->insert([
            'student_id' => $student->student_id,
            'student_name' => $student->full_name,
            'course' => $student->course,
            'attendance_date' => $attendanceDate,
            'subject' => $subject,
            'time_in' => $timeIn,
            'time_out' => $timeOut,
            'status' => $status,
            'school_year' => $student->school_year,
            'created_at' => now()->format('Y-m-d H:i:s'),
        ]);
        $this->audit('Device recorded attendance for '.$studentId);

        return response()->json(['message' => 'Attendance recorded.', 'studentId' => $studentId, 'studentName' => $student->full_name, 'parentPhone' => $student->parent_phone, 'date' => $attendanceDate, 'timeIn' => $timeIn, 'action' => 'time_in']);
    }

    private function setting(string $key): ?string
    {
        $row = $this->db()->table('notification_settings')->where('setting_key', $key)->first();

        return $row ? (string) $row->setting_value : null;
    }

    private function sendAttendanceSms(object $student, string $action, string $time, string $attendanceDate): void
    {
        $enabledKey = $action === 'time_in' ? 'sms_time_in_enabled' : 'sms_time_out_enabled';
        $messageKey = $action === 'time_in' ? 'sms_time_in_message' : 'sms_time_out_message';
        $provider = strtolower((string) env('SMS_PROVIDER', 'textbee'));
        // When the Raspberry Pi is the SMS backend, sending is always enabled.
        if ($provider !== 'raspberry_pi' && $this->setting($enabledKey) !== 'true') {
            return;
        }
        $phone = trim((string) ($student->parent_phone ?? ''));
        if ($provider === 'raspberry_pi') {
            Log::info('Dispatching SMS to Pi', [
                'action' => $action,
                'phone' => $phone,
                'student' => $student->full_name,
            ]);
        }
        if ($phone === '') {
            return;
        }
        $template = $this->setting($messageKey);
        if ($template === null || trim($template) === '') {
            $template = $action === 'time_in'
                ? 'Good day! Your student, {{student_name}}, has arrived at school. Attendance recorded at {{time}} {{date}}.'
                : 'Good day! Your student, {{student_name}}, has departed from school. Attendance recorded at {{time}} {{date}}.';
        }
        $message = SmsService::render($template, [
            'time' => $time,
            'student_name' => $student->full_name,
            'student_id' => $student->student_id,
            'date' => $attendanceDate,
            'status' => 'Present',
            'course' => $student->course,
        ]);

        if ($provider === 'raspberry_pi') {
            $this->sendAttendanceSmsViaPi($phone, $message, $student->full_name);

            return;
        }
        (new SmsService)->send($phone, $message);
    }

    private function resolvePython(): string
    {
        $isWindows = stripos(PHP_OS_FAMILY, 'Windows') !== false;
        $relative = $isWindows ? 'Scripts'.DIRECTORY_SEPARATOR.'python.exe' : 'bin'.DIRECTORY_SEPARATOR.'python';
        $candidates = [
            base_path('.venv'.DIRECTORY_SEPARATOR.$relative),
            base_path('raspberry_pi'.DIRECTORY_SEPARATOR.'.venv'.DIRECTORY_SEPARATOR.$relative),
            base_path('venv'.DIRECTORY_SEPARATOR.$relative),
        ];
        foreach ($candidates as $candidate) {
            if (is_file($candidate)) {
                return $candidate;
            }
        }

        return $isWindows ? 'python' : 'python3';
    }

    private function sendAttendanceSmsViaPi(string $phone, string $message, string $name): void
    {
        $configured = (string) env('PI_SMS_URL', 'http://host.docker.internal:8092/send-sms');
        $parts = parse_url($configured);
        $port = $parts['port'] ?? 8092;
        $path = $parts['path'] ?? '/send-sms';
        $hosts = array_values(array_unique(array_filter([
            $parts['host'] ?? null,
            'host.docker.internal',
            '127.0.0.1',
            'localhost',
        ])));
        $urls = [];
        foreach ($hosts as $host) {
            $scheme = $parts['scheme'] ?? 'http';
            $urls[] = "{$scheme}://{$host}:{$port}{$path}";
        }
        $urls = array_values(array_unique($urls));

        foreach ($urls as $url) {
            Log::info('Pi SMS HTTP dispatch starting', ['url' => $url, 'phone' => $phone]);
            try {
                $response = Http::timeout(5)->post($url, [
                    'phone' => $phone,
                    'message' => $message,
                    'name' => $name,
                ]);
                Log::info('Pi SMS HTTP dispatch finished', ['url' => $url, 'status' => $response->status(), 'body' => $response->body()]);
                if ($response->successful()) {
                    return;
                }
                Log::warning('Pi SMS HTTP dispatch failed', ['url' => $url, 'status' => $response->status(), 'body' => $response->body()]);
            } catch (\Throwable $e) {
                Log::warning('Pi SMS HTTP dispatch exception', ['url' => $url, 'error' => $e->getMessage()]);
                continue;
            }
        }
        Log::error('Pi SMS HTTP dispatch failed on all candidate URLs', ['urls' => $urls]);
    }

    private function deviceToken(): string
    {
        $path = public_path('device_config.php');
        if (! is_file($path)) {
            return '';
        }
        $config = require $path;

        return is_array($config) ? (string) ($config['token'] ?? '') : '';
    }
}
