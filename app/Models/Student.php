<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Student extends Model
{
    protected $connection = 'attendance';

    protected $table = 'students';

    public $timestamps = false;

    protected $fillable = [
        'student_id', 'full_name', 'course', 'year', 'age',
        'school_year', 'status', 'parent_phone', 'is_archived',
        'archived_school_year', 'face_image_path', 'created_at',
    ];

    protected $casts = [
        'is_archived' => 'integer',
        'age' => 'integer',
    ];
}
