<?php

namespace App\Services;

use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class SmsService
{
    public function send(string $recipient, string $message): bool
    {
        $apiKey = (string) env('TEXTBEE_API_KEY', '');
        $deviceId = (string) env('TEXTBEE_DEVICE_ID', '');
        $recipient = trim($recipient);
        if ($apiKey === '' || $deviceId === '' || $recipient === '' || $message === '') {
            return false;
        }
        // normalize phone to +63... if needed
        $digits = preg_replace('/\D+/', '', $recipient);
        if (strlen($digits) === 10 && str_starts_with($digits, '9')) {
            $recipient = '+63'.$digits;
        } elseif (str_starts_with($digits, '0')) {
            $recipient = '+63'.substr($digits, 1);
        } elseif (str_starts_with($digits, '63')) {
            $recipient = '+'.$digits;
        } else {
            $recipient = '+'.$digits;
        }
        try {
            $response = Http::withHeaders(['x-api-key' => $apiKey])
                ->timeout(15)
                ->post('https://api.textbee.dev/api/v1/gateway/send-sms', [
                    'deviceId' => $deviceId,
                    'recipients' => [$recipient],
                    'message' => $message,
                ]);
            if (! $response->successful()) {
                Log::warning('TextBee SMS failed', ['status' => $response->status(), 'body' => $response->body()]);

                return false;
            }

            return true;
        } catch (\Throwable $e) {
            Log::warning('TextBee SMS exception: '.$e->getMessage());

            return false;
        }
    }

    public static function render(string $template, array $vars): string
    {
        foreach ($vars as $key => $value) {
            $template = str_replace('{{'.$key.'}}', (string) $value, $template);
            $template = str_replace('{{ '.$key.' }}', (string) $value, $template);
        }

        return $template;
    }
}
