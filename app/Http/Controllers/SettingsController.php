<?php

namespace App\Http\Controllers;

use App\Models\AuditLog;
use App\Models\NotificationSetting;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Auth;

class SettingsController extends Controller
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
        foreach (['absent', 'late', 'checkIn'] as $key) {
            if ($request->has($key)) {
                NotificationSetting::updateOrCreate(
                    ['setting_key' => $key],
                    ['setting_value' => ! empty($request->input($key)) ? 'true' : 'false']
                );
            }
        }
        foreach (['sms_time_in_enabled', 'sms_time_out_enabled'] as $key) {
            if ($request->has($key)) {
                NotificationSetting::updateOrCreate(
                    ['setting_key' => $key],
                    ['setting_value' => ! empty($request->input($key)) ? 'true' : 'false']
                );
            }
        }
        foreach (['sms_time_in_message', 'sms_time_out_message'] as $key) {
            if ($request->has($key)) {
                NotificationSetting::updateOrCreate(
                    ['setting_key' => $key],
                    ['setting_value' => (string) $request->input($key)]
                );
            }
        }
        $this->audit('Updated notification settings');

        return response()->json(['message' => 'Settings saved.']);
    }
}
