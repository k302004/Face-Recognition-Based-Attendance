<?php

namespace Tests\Feature;

use App\Models\User;
use App\Services\MonitorState;
use Illuminate\Http\Client\Factory;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class MonitorTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        Cache::setDefaultDriver('array');
        Cache::flush();
        config(['database.connections.attendance.database' => ':memory:']);
        DB::purge('attendance');
        Http::preventStrayRequests();
        Http::swap(new Factory);
        Http::preventStrayRequests();
        Http::fake(['*' => Http::response(['face_detected' => false, 'student' => null])]);
    }

    protected function tearDown(): void
    {
        DB::purge('attendance');
        parent::tearDown();
    }

    public function test_camera_frames_are_gated_by_operation_mode_and_relay_jpeg_only(): void
    {
        $this->get('/api/monitor/frame')->assertStatus(409);
        Http::assertNothingSent();
        $session = app(MonitorState::class)->start('time_in')['session'];
        Http::swap(new Factory);
        Http::preventStrayRequests();
        Http::fake(['*' => Http::response("\xff\xd8test-jpeg", 200, ['Content-Type' => 'image/jpeg'])]);
        $this->get('/api/monitor/frame')->assertOk()->assertHeader('Content-Type', 'image/jpeg')->assertContent("\xff\xd8test-jpeg");
        Http::swap(new Factory);
        Http::preventStrayRequests();
        Http::fake(['*' => Http::response('Camera unavailable', 503)]);
        $this->get('/api/monitor/frame')->assertStatus(503);
        app(MonitorState::class)->control($session, true);
        $this->get('/api/monitor/frame')->assertStatus(409);
    }

    public function test_live_face_information_uses_registered_student_and_excludes_private_contact_data(): void
    {
        DB::connection('attendance')->statement('CREATE TABLE students (student_id TEXT, full_name TEXT, course TEXT, year TEXT, age INTEGER, school_year TEXT, status TEXT, face_image_path TEXT, is_archived INTEGER, parent_phone TEXT)');
        DB::connection('attendance')->table('students')->insert(['student_id' => 'FACE-TEST', 'full_name' => 'Registered Student', 'course' => 'BSIT', 'year' => '2', 'age' => 19, 'school_year' => '2026-2027', 'status' => 'Active', 'face_image_path' => 'face_images/test.jpg', 'is_archived' => 0, 'parent_phone' => 'private']);
        app(MonitorState::class)->start('time_in');
        Http::swap(new Factory);
        Http::preventStrayRequests();
        Http::fake(['*' => Http::response(['face_detected' => true, 'student' => ['student_id' => 'FACE-TEST', 'name' => 'Stale camera name', 'parent_phone' => 'private']])]);
        $response = $this->getJson('/api/monitor/status')->assertOk()->assertJsonPath('student.name', 'Registered Student')->assertJsonPath('student.course', 'BSIT')->assertJsonPath('student.photo', '/face_images/test.jpg');
        $this->assertArrayNotHasKey('parent_phone', $response->json('student'));
        $this->assertEmpty($response->json('events'), 'Recognition alone must not claim attendance was recorded.');
        Http::swap(new Factory);
        Http::preventStrayRequests();
        Http::fake(['*' => Http::response(['face_detected' => true, 'student' => ['student_id' => 'orphan-photo-hash']])]);
        $this->getJson('/api/monitor/status')->assertJsonPath('student', null)->assertJsonPath('faceDetected', true);
    }

    public function test_public_display_waits_and_controls_require_login(): void
    {
        $this->get('/monitor')->assertOk()->assertSee('Waiting for Operation Mode');
        $this->getJson('/api/monitor/status')->assertOk()->assertJson(['active' => false, 'events' => []]);
        $this->postJson('/api/monitor/start', ['mode' => 'time_in'])->assertUnauthorized();
        $this->postJson('/api/monitor/stop', ['session' => 'fake'])->assertUnauthorized();
    }

    public function test_session_heartbeat_stop_and_stale_session_protection(): void
    {
        $this->actingAs((new User)->forceFill(['id' => 1, 'name' => 'Monitor Operator']));
        $this->postJson('/api/monitor/start', ['mode' => 'invalid'])->assertUnprocessable();
        $session = $this->postJson('/api/monitor/start', ['mode' => 'time_in'])->assertOk()->json('session');
        $this->travel(10)->seconds();
        $this->postJson('/api/monitor/heartbeat', ['session' => $session])->assertOk();
        $this->travel(11)->seconds();
        $this->getJson('/api/monitor/status')->assertJson(['active' => true, 'mode' => 'time_in'])->assertJsonMissingPath('session');
        $next = $this->postJson('/api/monitor/start', ['mode' => 'time_out'])->assertOk()->json('session');
        $this->postJson('/api/monitor/stop', ['session' => $session])->assertStatus(409);
        $this->postJson('/api/monitor/stop', ['session' => $next])->assertOk();
        $this->getJson('/api/monitor/status')->assertJson(['active' => false]);
    }

    public function test_events_are_limited_to_active_session_and_expire(): void
    {
        $monitor = app(MonitorState::class);
        $session = $monitor->start('time_out')['session'];
        $student = (object) ['student_id' => 'TEST-01', 'full_name' => 'Test Student', 'parent_phone' => 'private', 'face_image_path' => 'face_images/test.jpg'];
        $monitor->publish('wrong-session', $student, 'time_out', '8:00 AM');
        $monitor->publish($session, $student, 'time_in', '8:00 AM');
        $this->assertEmpty($monitor->status()['events']);
        $monitor->publish($session, $student, 'time_out', '8:00 AM');
        $event = $this->getJson('/api/monitor/status')->assertOk()->json('events.0');
        $this->assertSame('Test Student', $event['name']);
        $this->assertSame('/face_images/test.jpg', $event['photo']);
        $this->assertArrayNotHasKey('parent_phone', $event);
        $this->travel(16)->seconds();
        $this->assertEmpty($monitor->status()['events']);
        $this->travel(5)->seconds();
        $this->assertFalse($monitor->status()['active']);
        $this->assertFalse($monitor->control($session));
    }
}
