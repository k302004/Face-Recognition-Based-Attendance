<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\StreamedResponse;

class CameraController extends Controller
{
    private function streamUrl(string $path): string
    {
        return 'http://127.0.0.1:8090' . $path;
    }

    public function currentStudent(Request $request): JsonResponse
    {
        $url = $this->streamUrl('/current_student');
        $context = stream_context_create(['http' => ['timeout' => 2]]);
        $response = @file_get_contents($url, false, $context);
        if ($response === false) {
            return response()->json([
                'student' => null,
                'face_detected' => false,
                'message' => 'Camera stream is not running.',
            ], 502);
        }
        $decoded = json_decode($response, true);
        return response()->json(is_array($decoded) ? $decoded : ['student' => null]);
    }

    public function faceEvents(Request $request): StreamedResponse
    {
        return new StreamedResponse(function () {
            set_time_limit(0);
            $url = $this->streamUrl('/events');
            $context = stream_context_create(['http' => ['timeout' => 300]]);
            $stream = @fopen($url, 'r', false, $context);
            if (!$stream) {
                echo "data: " . json_encode(['student' => null, 'face_detected' => false, 'message' => 'Camera stream is not running.']) . "\n\n";
                flush();
                return;
            }
            while (!feof($stream)) {
                $line = fgets($stream);
                if ($line !== false) {
                    echo $line;
                    flush();
                }
            }
            fclose($stream);
        }, 200, [
            'Content-Type' => 'text/event-stream',
            'Cache-Control' => 'no-cache',
            'X-Accel-Buffering' => 'no',
        ]);
    }
}
