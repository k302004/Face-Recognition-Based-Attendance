<?php

namespace Tests\Feature;

use App\Http\Controllers\AttendanceController;
use App\Services\MonitorState;
use Illuminate\Http\Request;
use Illuminate\Support\Env;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class AttendanceSmsTest extends TestCase
{
    private mixed $provider;

    protected function setUp(): void
    {
        parent::setUp();
        config(['database.connections.attendance.database' => ':memory:']);
        DB::purge('attendance');
        $db = DB::connection('attendance');
        $db->statement('CREATE TABLE students (student_id TEXT, full_name TEXT, course TEXT, school_year TEXT, parent_phone TEXT, is_archived INTEGER)');
        $db->statement('CREATE TABLE attendance (id INTEGER PRIMARY KEY, student_id TEXT, student_name TEXT, course TEXT, attendance_date TEXT, subject TEXT, time_in TEXT, time_out TEXT, status TEXT, school_year TEXT, created_at TEXT)');
        $db->statement('CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, action TEXT, actor TEXT, created_at TEXT)');
        $db->statement('CREATE TABLE notification_settings (setting_key TEXT, setting_value TEXT)');
        $db->table('students')->insert(['student_id' => 'TEST-001', 'full_name' => 'Test Student', 'course' => 'Test', 'school_year' => '2026-2027', 'parent_phone' => '+639000000000', 'is_archived' => 0]);
        $this->provider = env('SMS_PROVIDER');
        Env::getRepository()->set('SMS_PROVIDER', 'raspberry_pi');
        Http::preventStrayRequests();
        Http::fake(['*' => Http::response(['ok' => true, 'state' => 'queued'], 202)]);
    }

    protected function tearDown(): void
    {
        if ($this->provider === null) {
            Env::getRepository()->clear('SMS_PROVIDER');
        } else {
            Env::getRepository()->set('SMS_PROVIDER', $this->provider);
        }
        DB::purge('attendance');
        parent::tearDown();
    }

    private function record(string $action): string
    {
        return (new AttendanceController)->record(Request::create('/api/record-attendance', 'POST', [
            'studentId' => 'TEST-001', 'attendanceAction' => $action,
        ]))->getData()->action;
    }

    public function test_monitor_displays_only_new_successfully_recorded_attendance(): void
    {
        $monitor = app(MonitorState::class);
        $session = $monitor->start('time_in')['session'];
        $request = Request::create('/api/record-attendance', 'POST', [
            'studentId' => 'TEST-001', 'attendanceAction' => 'time_in', 'monitorSession' => $session,
        ]);
        $controller = new AttendanceController;
        $this->assertSame('time_in', $controller->record($request)->getData()->action);
        $this->assertCount(1, $monitor->status()['events']);
        $this->assertSame('already_recorded', $controller->record($request)->getData()->action);
        $this->assertCount(1, $monitor->status()['events']);
    }

    public function test_time_in_sms_precedes_time_out_and_repeated_scans_do_not_resend(): void
    {
        $this->assertSame('time_in', $this->record('time_in'));
        $this->assertSame('already_recorded', $this->record('time_in'));
        $this->assertSame('time_out', $this->record('time_out'));
        $this->assertSame('already_recorded', $this->record('time_out'));
        Http::assertSentCount(2);
        $messages = Http::recorded()->map(fn ($pair) => $pair[0]['message'])->all();
        $this->assertStringContainsString('arrived', $messages[0]);
        $this->assertStringContainsString('departed', $messages[1]);
        $events = Http::recorded()->map(fn ($pair) => $pair[0]['action'])->all();
        $this->assertSame(['time_in', 'time_out'], $events);
    }

    public function test_time_out_before_time_in_does_not_send_sms(): void
    {
        $this->assertSame('no_time_in', $this->record('time_out'));
        Http::assertNothingSent();
    }

    public function test_lcd_receives_attendance_even_when_sms_is_disabled_and_phone_is_missing(): void
    {
        DB::connection('attendance')->table('notification_settings')->insert([
            'setting_key' => 'sms_time_in_enabled', 'setting_value' => 'false',
        ]);
        DB::connection('attendance')->table('students')->update(['parent_phone' => '']);
        $this->assertSame('time_in', $this->record('time_in'));
        Http::assertSentCount(1);
        Http::assertSent(fn ($request) => $request['send_sms'] === false
            && $request['action'] === 'time_in'
            && $request['name'] === 'Test Student'
            && $request['student_id'] === 'TEST-001'
            && strlen($request['event_id']) === 32);
    }
}
