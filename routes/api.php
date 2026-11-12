<?php

use Illuminate\Support\Facades\Route;
use App\Http\Controllers\CameraController;

Route::get('/camera-current-student', [CameraController::class, 'currentStudent']);
Route::get('/face-events', [CameraController::class, 'faceEvents']);