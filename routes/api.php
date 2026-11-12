<?php

use App\Http\Controllers\AttendanceController;
use App\Http\Controllers\CameraController;
use Illuminate\Support\Facades\Route;

Route::get('/camera-current-student', [CameraController::class, 'currentStudent']);
Route::get('/face-events', [CameraController::class, 'faceEvents']);
Route::post('/device-attendance', [AttendanceController::class, 'device']);
