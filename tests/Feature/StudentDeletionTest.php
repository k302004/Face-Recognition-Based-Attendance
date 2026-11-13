<?php

namespace Tests\Feature;

use App\Http\Controllers\StudentController;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class StudentDeletionTest extends TestCase
{
    public function test_deleting_student_removes_their_attendance_and_preserves_other_students(): void
    {
        config(['database.connections.attendance.database' => ':memory:']);
        DB::purge('attendance');
        // Isolate both the database and face-photo lookup from real student data.
        $this->app->usePublicPath(sys_get_temp_dir().'/attendance-delete-test-'.uniqid());
        $db = DB::connection('attendance');
        $db->statement('CREATE TABLE students (id INTEGER PRIMARY KEY, student_id TEXT, face_image_path TEXT)');
        $db->statement('CREATE TABLE attendance (id INTEGER PRIMARY KEY, student_id TEXT)');
        $db->statement('CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, action TEXT, actor TEXT, created_at TEXT)');
        foreach (['DELETE-TEST', 'KEEP-TEST'] as $studentId) {
            $db->table('students')->insert(['student_id' => $studentId]);
            $db->table('attendance')->insert(['student_id' => $studentId]);
        }
        Auth::shouldReceive('user')->andReturn((object) ['role' => 'Administrator', 'name' => 'Test Admin']);

        try {
            $response = (new StudentController)->destroy(Request::create('/api/delete-student', 'POST', ['studentId' => 'DELETE-TEST']));
            $this->assertSame(200, $response->getStatusCode());
            $this->assertSame('Student deleted successfully.', $response->getData()->message);
            $this->assertSame(['KEEP-TEST'], $db->table('students')->pluck('student_id')->all());
            $this->assertSame(['KEEP-TEST'], $db->table('attendance')->pluck('student_id')->all());
            $this->assertSame('Deleted student DELETE-TEST', $db->table('audit_logs')->value('action'));
        } finally {
            DB::purge('attendance');
        }
    }
}
