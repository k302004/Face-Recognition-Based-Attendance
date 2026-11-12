<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class AuditLog extends Model
{
    protected $connection = 'attendance';

    protected $table = 'audit_logs';

    public $timestamps = false;

    protected $fillable = ['action', 'actor', 'created_at'];
}
