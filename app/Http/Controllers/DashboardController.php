<?php

namespace App\Http\Controllers;

use App\Models\Attendance;
use App\Models\AuditLog;
use App\Models\NotificationSetting;
use App\Models\Schedule;
use App\Models\Student;
use Illuminate\Http\JsonResponse;

class DashboardController extends Controller
{
    public function dashboard(): JsonResponse
    {
        $students = Student::orderBy('full_name')->get([
            'id', 'student_id', 'full_name', 'course', 'year', 'age',
            'school_year', 'status', 'parent_phone', 'is_archived',
            'archived_school_year', 'face_image_path',
        ]);
        $schedules = Schedule::orderBy('day')->orderBy('start_time')->get([
            'id', 'subject', 'instructor', 'room', 'day', 'start_time',
            'end_time', 'school_year', 'is_archived', 'archived_school_year',
        ]);
        $attendance = Attendance::orderBy('id', 'desc')->get([
            'student_id', 'student_name', 'course', 'attendance_date',
            'subject', 'time_in', 'time_out', 'status', 'school_year',
            'is_archived', 'archived_school_year',
        ]);
        $audit = AuditLog::orderBy('id', 'desc')->limit(20)->get(['action', 'actor', 'created_at']);
        $settings = NotificationSetting::all();
        $notificationSettings = [];
        foreach ($settings as $s) {
            $notificationSettings[$s->setting_key] = $s->setting_value;
        }

        return response()->json([
            'students' => $students,
            'schedules' => $schedules,
            'attendance' => $attendance,
            'audit' => $audit,
            'notificationSettings' => $notificationSettings,
        ]);
    }
}
