<?php

namespace App\Http\Controllers;

use App\Models\AuditLog;
use App\Models\Schedule;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Auth;

class ScheduleController extends Controller
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

    public function store(Request $request): JsonResponse
    {
        if ($deny = $this->requireAdmin()) {
            return $deny;
        }
        $schoolYear = trim((string) $request->input('schoolYear', ''));
        if (! preg_match('/^\d{4}-\d{4}$/', $schoolYear) || (int) substr($schoolYear, 5) !== (int) substr($schoolYear, 0, 4) + 1) {
            return response()->json(['message' => 'Please provide a valid school year, such as 2026-2027.'], 400);
        }
        $id = $request->input('id');
        if (! empty($id)) {
            Schedule::where('id', $id)->update([
                'subject' => $request->input('subject'),
                'instructor' => $request->input('teacher'),
                'room' => $request->input('room'),
                'day' => $request->input('day'),
                'start_time' => $request->input('startTime'),
                'end_time' => $request->input('endTime'),
                'school_year' => $schoolYear,
            ]);
            $this->audit('Updated schedule '.$request->input('subject'));
        } else {
            Schedule::create([
                'subject' => $request->input('subject'),
                'instructor' => $request->input('teacher'),
                'room' => $request->input('room'),
                'day' => $request->input('day'),
                'start_time' => $request->input('startTime'),
                'end_time' => $request->input('endTime'),
                'school_year' => $schoolYear,
                'created_at' => now()->format('Y-m-d H:i:s'),
            ]);
            $this->audit('Added schedule '.$request->input('subject'));
        }

        return response()->json(['message' => 'Schedule added.']);
    }

    public function destroy(Request $request): JsonResponse
    {
        if ($deny = $this->requireAdmin()) {
            return $deny;
        }
        Schedule::where('id', $request->input('id'))->delete();
        $this->audit('Deleted schedule');

        return response()->json(['message' => 'Schedule deleted.']);
    }
}
