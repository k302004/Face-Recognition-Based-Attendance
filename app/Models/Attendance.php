<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Attendance extends Model
{
    protected $connection = 'attendance';

    protected $table = 'attendance';

    public $timestamps = false;

    protected $fillable = [
        'student_id', 'student_name', 'course', 'attendance_date',
        'subject', 'time_in', 'time_out', 'status', 'school_year',
        'is_archived', 'archived_school_year', 'created_at',
    ];

    protected $casts = [
        'is_archived' => 'integer',
    ];
}
