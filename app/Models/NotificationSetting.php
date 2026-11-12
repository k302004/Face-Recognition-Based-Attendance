<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class NotificationSetting extends Model
{
    protected $connection = 'attendance';

    protected $table = 'notification_settings';

    public $timestamps = false;

    protected $primaryKey = 'setting_key';

    public $incrementing = false;

    protected $keyType = 'string';

    protected $fillable = ['setting_key', 'setting_value'];
}
