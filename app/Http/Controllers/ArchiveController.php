<?php

namespace App\Http\Controllers;

use App\Models\Attendance as AttendanceModel;
use App\Models\AuditLog;
use App\Models\Schedule;
use App\Models\Student;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Auth;

class ArchiveController extends Controller
{
    private function audit(string $action): void
    {
        AuditLog::create(['action' => $action, 'actor' => Auth::user()?->name ?? 'System', 'created_at' => now()->format('Y-m-d H:i:s')]);
    }

    private function requireAdmin(): ?JsonResponse
    {
        if ((Auth::user()?->role ?? '') !== 'Administrator') {
            return response()->json(['message' => 'Administrator permission required.'], 403);
        }

        return null;
    }

    public function archiveYear(Request $request): JsonResponse
    {
        if ($deny = $this->requireAdmin()) {
            return $deny;
        }
        $schoolYear = trim((string) $request->input('schoolYear', ''));
        $course = trim((string) $request->input('course', ''));
        if ($schoolYear === '') {
            return response()->json(['message' => 'A school year is required.'], 400);
        }
        $q = Student::where('is_archived', 0)->where('school_year', $schoolYear);
        if ($course !== '') {
            $q->where('course', $course);
        }
        $q->update(['is_archived' => 1, 'archived_school_year' => $schoolYear]);

        $attendanceQ = AttendanceModel::where('is_archived', 0)->whereIn('student_id', function ($sub) use ($schoolYear, $course) {
            $sub->select('student_id')->from('students')->where('school_year', $schoolYear);
            if ($course !== '') {
                $sub->where('course', $course);
            }
        });
        $attendanceQ->update(['is_archived' => 1, 'school_year' => $schoolYear, 'archived_school_year' => $schoolYear]);

        if ($course === '') {
            Schedule::where('is_archived', 0)->where('school_year', $schoolYear)->update(['is_archived' => 1, 'archived_school_year' => $schoolYear]);
        }
        $this->audit('Archived '.($course !== '' ? $course.' students for ' : 'students for ').$schoolYear);

        return response()->json(['message' => 'Selected records archived for '.$schoolYear.($course !== '' ? ' ('.$course.')' : '').'.']);
    }

    public function archiveAttendanceDate(Request $request): JsonResponse
    {
        if ($deny = $this->requireAdmin()) {
            return $deny;
        }
        $dateKey = trim((string) $request->input('date', ''));
        $schoolYear = trim((string) $request->input('schoolYear', ''));
        $date = \DateTime::createFromFormat('!Y-m-d', $dateKey);
        if (! $date || $date->format('Y-m-d') !== $dateKey) {
            return response()->json(['message' => 'A valid attendance date is required.'], 400);
        }
        if (! preg_match('/^\d{4}-\d{4}$/', $schoolYear) || (int) substr($schoolYear, 5) !== (int) substr($schoolYear, 0, 4) + 1) {
            return response()->json(['message' => 'A valid school year is required.'], 400);
        }
        $displayDate = $date->format('F j, Y');
        AttendanceModel::where('attendance_date', $displayDate)->where('is_archived', 0)->update(['is_archived' => 1, 'school_year' => $schoolYear, 'archived_school_year' => $schoolYear]);
        $this->audit('Archived attendance for '.$displayDate.' ('.$schoolYear.')');

        return response()->json(['message' => 'Attendance archived for '.$displayDate.'.']);
    }

    public function restoreYear(Request $request): JsonResponse
    {
        if ($deny = $this->requireAdmin()) {
            return $deny;
        }
        $schoolYear = trim((string) $request->input('schoolYear', ''));
        if ($schoolYear === '') {
            return response()->json(['message' => 'A school year is required.'], 400);
        }
        Student::where('archived_school_year', $schoolYear)->update(['is_archived' => 0, 'archived_school_year' => null]);
        AttendanceModel::where('archived_school_year', $schoolYear)->update(['is_archived' => 0, 'archived_school_year' => null]);
        Schedule::where('archived_school_year', $schoolYear)->update(['is_archived' => 0, 'archived_school_year' => null]);
        $this->audit('Restored students for school year '.$schoolYear);

        return response()->json(['message' => 'Students restored for '.$schoolYear.'.']);
    }
}
