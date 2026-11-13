<?php

namespace App\Http\Controllers;

use App\Models\Student;
use App\Services\MonitorState;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;
use Symfony\Component\HttpFoundation\Response;

class MonitorController extends Controller
{
    public function status(MonitorState $monitor): JsonResponse
    {
        $state = $monitor->status();
        $state += ['cameraAvailable' => false, 'faceDetected' => false, 'student' => null];
        if ($state['active']) {
            try {
                $reply = Http::connectTimeout(1)->timeout(1)->get('http://127.0.0.1:8090/current_student');
                $state['cameraAvailable'] = $reply->successful();
                $state['faceDetected'] = $reply->successful() && $reply->json('face_detected') === true;
                $id = $reply->json('student.student_id');
                if ($state['faceDetected'] && is_string($id)) {
                    $student = Student::where('student_id', $id)->where('is_archived', 0)->first();
                    if ($student) {
                        $photo = trim(explode(',', (string) $student->face_image_path)[0]);
                        $state['student'] = [
                            'name' => $student->full_name, 'studentId' => $student->student_id,
                            'course' => $student->course, 'year' => $student->year, 'age' => $student->age,
                            'schoolYear' => $student->school_year, 'status' => $student->status,
                            'photo' => preg_match('~^face_images/[a-zA-Z0-9_-]+\.(jpg|jpeg|png|webp)$~i', $photo) ? '/'.$photo : null,
                        ];
                    }
                }
            } catch (ConnectionException) {
                // Keep operation state available while the camera reconnects.
            }
        }

        return response()->json($state)->header('Cache-Control', 'no-store');
    }

    public function frame(MonitorState $monitor): Response
    {
        if (! $monitor->status()['active']) {
            return response('', 409)->header('Cache-Control', 'no-store');
        }
        try {
            $frame = Http::connectTimeout(1)->timeout(2)->get('http://127.0.0.1:8090/snapshot');
            if ($frame->successful() && str_starts_with($frame->body(), "\xff\xd8")) {
                return response($frame->body())->header('Content-Type', 'image/jpeg')->header('Cache-Control', 'no-store');
            }
        } catch (ConnectionException) {
        }

        return response('', 503)->header('Cache-Control', 'no-store');
    }

    public function start(Request $request, MonitorState $monitor): JsonResponse
    {
        $data = $request->validate(['mode' => 'required|in:time_in,time_out']);

        return response()->json($monitor->start($data['mode']));
    }

    public function heartbeat(Request $request, MonitorState $monitor): JsonResponse
    {
        return $this->control($request, $monitor, false);
    }

    public function stop(Request $request, MonitorState $monitor): JsonResponse
    {
        return $this->control($request, $monitor, true);
    }

    private function control(Request $request, MonitorState $monitor, bool $stop): JsonResponse
    {
        $data = $request->validate(['session' => 'required|string|max:96']);
        $ok = $monitor->control($data['session'], $stop);

        return response()->json(['ok' => $ok], $ok ? 200 : 409);
    }
}
