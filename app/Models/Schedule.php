<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Schedule extends Model
{
    protected $connection = 'attendance';

    protected $table = 'schedules';

    public $timestamps = false;

    protected $fillable = [
        'subject', 'instructor', 'room', 'day', 'start_time',
        'end_time', 'school_year', 'is_archived', 'archived_school_year',
        'created_at',
    ];

    protected $casts = [
        'is_archived' => 'integer',
    ];
}
