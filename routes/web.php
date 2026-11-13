<?php

use App\Http\Controllers\ArchiveController;
use App\Http\Controllers\AttendanceController;
use App\Http\Controllers\AuthController;
use App\Http\Controllers\DashboardController;
use App\Http\Controllers\MonitorController;
use App\Http\Controllers\ScheduleController;
use App\Http\Controllers\SettingsController;
use App\Http\Controllers\StudentController;
use App\Services\MonitorState;
use Illuminate\Support\Facades\Route;

Route::get('/', function () {
    return view('attendance-app');
});
Route::view('/monitor', 'attendance-monitor');
Route::get('/api/monitor/status', [MonitorController::class, 'status']);
Route::get('/api/monitor/active', fn (MonitorState $monitor) => response()->json(['active' => $monitor->status()['active']])->header('Cache-Control', 'no-store'));
Route::get('/api/monitor/frame', [MonitorController::class, 'frame']);

Route::prefix('api')->group(function () {
    Route::post('signup', [AuthController::class, 'signup']);
    Route::post('login', [AuthController::class, 'login']);
    Route::post('request-password-reset', [AuthController::class, 'requestPasswordReset']);
    Route::post('reset-password', [AuthController::class, 'resetPassword']);

    Route::middleware('auth')->group(function () {
        Route::post('monitor/start', [MonitorController::class, 'start']);
        Route::post('monitor/heartbeat', [MonitorController::class, 'heartbeat']);
        Route::post('monitor/stop', [MonitorController::class, 'stop']);
        Route::get('me', [AuthController::class, 'me']);
        Route::get('dashboard', [DashboardController::class, 'dashboard']);
        Route::post('student', [StudentController::class, 'store']);
        Route::post('archive-student', [StudentController::class, 'archive']);
        Route::post('delete-student', [StudentController::class, 'destroy']);
        Route::post('schedule', [ScheduleController::class, 'store']);
        Route::post('delete-schedule', [ScheduleController::class, 'destroy']);
        Route::post('settings', [SettingsController::class, 'store']);
        Route::post('record-attendance', [AttendanceController::class, 'record']);
        Route::post('archive-year', [ArchiveController::class, 'archiveYear']);
        Route::post('archive-attendance-date', [ArchiveController::class, 'archiveAttendanceDate']);
        Route::post('restore-year', [ArchiveController::class, 'restoreYear']);
        Route::post('logout', [AuthController::class, 'logout']);
        Route::post('profile', [AuthController::class, 'profile']);
        Route::post('password', [AuthController::class, 'password']);
    });
});
