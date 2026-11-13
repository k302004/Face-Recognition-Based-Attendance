<?php

namespace App\Services;

use Illuminate\Support\Facades\Cache;

class MonitorState
{
    private const KEY = 'attendance-monitor:operation';

    public function start(string $mode): array
    {
        return Cache::lock(self::KEY.':lock', 3)->block(2, function () use ($mode) {
            $state = ['session' => bin2hex(random_bytes(24)), 'mode' => $mode];
            Cache::put(self::KEY, $state, 20);

            return $state;
        });
    }

    public function control(string $session, bool $stop = false): bool
    {
        return Cache::lock(self::KEY.':lock', 3)->block(2, function () use ($session, $stop) {
            $state = Cache::get(self::KEY);
            if (! $state || ! hash_equals($state['session'], $session)) {
                return false;
            }
            if ($stop) {
                Cache::forget(self::KEY);
                Cache::forget(self::KEY.':events:'.$session);
            } else {
                Cache::put(self::KEY, $state, 20);
            }

            return true;
        });
    }

    public function publish(string $session, object $student, string $action, string $time): void
    {
        Cache::lock(self::KEY.':lock', 3)->block(2, function () use ($session, $student, $action, $time) {
            $state = Cache::get(self::KEY);
            if (! $state || ! hash_equals($state['session'], $session) || $state['mode'] !== $action) {
                return;
            }
            $photo = trim(explode(',', (string) ($student->face_image_path ?? ''))[0]);
            // Publish only the enrollment-photo path and display fields.
            $photo = preg_match('~^face_images/[a-zA-Z0-9_-]+\.(jpg|jpeg|png|webp)$~i', $photo) ? '/'.$photo : null;
            $event = [
                'id' => bin2hex(random_bytes(12)), 'name' => $student->full_name,
                'studentId' => $student->student_id, 'photo' => $photo,
                'action' => $action, 'time' => $time, 'recordedAt' => now()->getTimestampMs(),
            ];
            $key = self::KEY.':events:'.$session;
            $events = Cache::get($key, []);
            $events[] = $event;
            Cache::put($key, array_slice($events, -20), 20);
        });
    }

    public function status(): array
    {
        $state = Cache::get(self::KEY);
        if (! $state) {
            return ['active' => false, 'mode' => null, 'run' => null, 'events' => []];
        }
        $events = Cache::get(self::KEY.':events:'.$state['session'], []);
        $events = array_values(array_filter($events, fn ($event) => $event['recordedAt'] >= now()->getTimestampMs() - 15000));

        return ['active' => true, 'mode' => $state['mode'], 'run' => substr(hash('sha256', $state['session']), 0, 16), 'events' => $events];
    }
}
