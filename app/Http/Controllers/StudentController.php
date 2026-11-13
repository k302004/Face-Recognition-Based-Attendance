<?php

namespace App\Http\Controllers;

use App\Models\Attendance;
use App\Models\AuditLog;
use App\Models\Student;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\DB;

class StudentController extends Controller
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
        $studentId = trim((string) $request->input('studentId', ''));
        $fullName = trim((string) $request->input('fullName', ''));
        $course = trim((string) $request->input('course', ''));
        $year = trim((string) $request->input('year', ''));
        $age = (int) $request->input('age', 0);
        if ($age <= 0) {
            $age = null;
        }
        $status = trim((string) $request->input('status', ''));
        $existingId = trim((string) $request->input('id', ''));

        if ($studentId === '') {
            return response()->json(['message' => 'Student ID is required.'], 400);
        }
        if ($fullName === '') {
            return response()->json(['message' => 'Full name is required.'], 400);
        }
        if ($course === '') {
            return response()->json(['message' => 'Course is required.'], 400);
        }
        if ($year === '') {
            return response()->json(['message' => 'Year is required.'], 400);
        }
        if ($status === '') {
            return response()->json(['message' => 'Status is required.'], 400);
        }
        $schoolYear = trim((string) $request->input('schoolYear', ''));
        if (! preg_match('/^\d{4}-\d{4}$/', $schoolYear) || (int) substr($schoolYear, 5) !== (int) substr($schoolYear, 0, 4) + 1) {
            return response()->json(['message' => 'Please provide a valid school year, such as 2026-2027.'], 400);
        }
        $parentPhone = trim((string) $request->input('parentPhone', ''));
        $phoneDigits = preg_replace('/\D+/', '', $parentPhone);
        if (strlen($phoneDigits) < 7 || strlen($phoneDigits) > 15) {
            return response()->json(['message' => 'Please provide a valid parent phone number.'], 400);
        }
        if (str_starts_with($phoneDigits, '63')) {
            $parentPhone = '+'.$phoneDigits;
        } elseif (str_starts_with($phoneDigits, '0')) {
            $parentPhone = '+63'.substr($phoneDigits, 1);
        } else {
            $parentPhone = '+'.$phoneDigits;
        }

        $imageDirectory = public_path('face_images');
        if (! is_dir($imageDirectory) && ! mkdir($imageDirectory, 0755, true)) {
            return response()->json(['message' => 'Unable to create the face photo folder.'], 500);
        }
        $relativeImagePaths = [];
        $facePhotos = [];
        if (is_array($request->input('facePhotos'))) {
            $facePhotos = $request->input('facePhotos');
        } elseif ((string) $request->input('facePhoto', '') !== '') {
            $facePhotos = [(string) $request->input('facePhoto')];
        }
        $photoIndex = 0;
        foreach ($facePhotos as $facePhoto) {
            $facePhoto = (string) $facePhoto;
            if ($facePhoto === '') {
                continue;
            }
            if (! preg_match('/^data:image\/(jpeg|png|webp);base64,([A-Za-z0-9+\/=]+)$/', $facePhoto, $matches)) {
                return response()->json(['message' => 'Please provide a valid face photo (JPG, PNG, or WebP).'], 400);
            }
            $imageData = base64_decode($matches[2], true);
            if ($imageData === false || strlen($imageData) > 5 * 1024 * 1024) {
                return response()->json(['message' => 'The face photo must be 5 MB or smaller.'], 400);
            }
            $imageInfo = @getimagesizefromstring($imageData);
            if (! $imageInfo || ! in_array($imageInfo['mime'], ['image/jpeg', 'image/png', 'image/webp'], true)) {
                return response()->json(['message' => 'The face photo is not a supported image.'], 400);
            }
            $extension = $matches[1] === 'jpeg' ? 'jpg' : $matches[1];
            $imageName = hash('sha256', $studentId.'_'.$photoIndex).'.'.$extension;
            $imagePath = $imageDirectory.DIRECTORY_SEPARATOR.$imageName;
            if (file_put_contents($imagePath, $imageData) === false) {
                return response()->json(['message' => 'Unable to save the face photo.'], 500);
            }
            $relativeImagePaths[] = 'face_images/'.$imageName;
            $photoIndex++;
        }
        $relativeImagePath = $relativeImagePaths ? implode(',', $relativeImagePaths) : null;

        if ($existingId !== '') {
            $existingRecord = DB::connection('attendance')->table('students')->where('id', $existingId)->first();
            if (! $existingRecord) {
                return response()->json(['message' => 'Student not found.'], 404);
            }
            $newStudentId = $studentId !== '' ? $studentId : (string) $existingRecord->student_id;
            $update = ['student_id' => $newStudentId, 'full_name' => $fullName, 'course' => $course, 'year' => $year, 'age' => $age, 'school_year' => $schoolYear, 'status' => $status, 'parent_phone' => $parentPhone];
            if ($relativeImagePath !== null) {
                $update['face_image_path'] = $relativeImagePath;
            }
            Student::where('id', $existingId)->update($update);
            $this->audit('Updated student '.$newStudentId);

            return response()->json(['message' => 'Student updated.']);
        }

        $student = new Student;
        $student->student_id = $studentId;
        $student->full_name = $fullName;
        $student->course = $course;
        $student->year = $year;
        $student->age = $age;
        $student->school_year = $schoolYear;
        $student->status = $status;
        $student->parent_phone = $parentPhone;
        $student->face_image_path = $relativeImagePath ?? '';
        try {
            $student->save();
        } catch (\Exception $e) {
            if ($relativeImagePath !== null) {
                @unlink($imageDirectory.DIRECTORY_SEPARATOR.basename($relativeImagePath));
            }
            if (str_contains($e->getMessage(), 'UNIQUE')) {
                return response()->json(['message' => 'A student with this ID already exists.'], 409);
            }

            return response()->json(['message' => 'Unable to add the student: '.$e->getMessage()], 500);
        }
        $this->audit('Added student '.$studentId);

        return response()->json(['message' => 'Student added.']);
    }

    public function archive(Request $request): JsonResponse
    {
        if ($deny = $this->requireAdmin()) {
            return $deny;
        }
        $value = (int) $request->input('archived', 0);
        $sid = (string) $request->input('studentId', '');
        Student::where('student_id', $sid)->update(['is_archived' => $value]);
        $this->audit(($value ? 'Archived ' : 'Restored ').'student '.$sid);

        return response()->json(['message' => 'Student updated.']);
    }

    public function destroy(Request $request): JsonResponse
    {
        if ($deny = $this->requireAdmin()) {
            return $deny;
        }
        $studentId = trim((string) $request->input('studentId', ''));
        if ($studentId === '') {
            return response()->json(['message' => 'Student ID is required.'], 400);
        }
        $student = DB::connection('attendance')->table('students')->where('student_id', $studentId)->first();
        if ($student && ! empty($student->face_image_path)) {
            foreach (explode(',', (string) $student->face_image_path) as $path) {
                $path = trim($path);
                $path = ltrim($path, '/\\');
                if ($path === '') {
                    continue;
                }
                $imagePath = public_path($path);
                if (is_file($imagePath)) {
                    @unlink($imagePath);
                }
            }
        }
        $imageDirectory = public_path('face_images');
        if (is_dir($imageDirectory)) {
            foreach (glob($imageDirectory.DIRECTORY_SEPARATOR.'*') as $file) {
                $basename = pathinfo($file, PATHINFO_FILENAME);
                for ($i = 0; $i < 10; $i++) {
                    if (hash('sha256', $studentId.'_'.$i) === $basename) {
                        @unlink($file);
                        break;
                    }
                }
            }
        }
        Student::where('student_id', $studentId)->delete();
        Attendance::where('student_id', $studentId)->delete();
        $this->audit('Deleted student '.$studentId);

        return response()->json(['message' => 'Student deleted successfully.']);
    }
}
