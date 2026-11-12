<?php

namespace App\Http\Controllers;

use App\Models\AuditLog;
use App\Models\User;
use Illuminate\Database\Connection;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\DB;

class AuthController extends Controller
{
    private function audit(string $action): void
    {
        AuditLog::create(['action' => $action, 'actor' => Auth::user()?->name ?? 'System', 'created_at' => now()->format('Y-m-d H:i:s')]);
    }

    private function db(): Connection
    {
        return DB::connection('attendance');
    }

    public function signup(Request $request): JsonResponse
    {
        $name = trim((string) $request->input('name', ''));
        $email = strtolower(trim((string) $request->input('email', '')));
        $password = (string) $request->input('password', '');
        if ($name === '' || ! filter_var($email, FILTER_VALIDATE_EMAIL) || strlen($password) < 6) {
            return response()->json(['message' => 'Please provide valid account details.'], 400);
        }
        $exists = $this->db()->table('users')->where('email', $email)->exists();
        if ($exists) {
            return response()->json(['message' => 'An account with this email already exists.'], 409);
        }
        $id = $this->db()->table('users')->insertGetId([
            'name' => $name,
            'email' => $email,
            'password_hash' => password_hash($password, PASSWORD_DEFAULT),
            'role' => 'Administrator',
            'profile_image' => null,
            'created_at' => now()->format('Y-m-d H:i:s'),
        ]);
        $user = User::find($id);
        Auth::login($user);
        $this->audit('Created account');

        return response()->json(['user' => $this->userPayload($user)], 201);
    }

    public function login(Request $request): JsonResponse
    {
        $email = strtolower(trim((string) $request->input('email', '')));
        $password = (string) $request->input('password', '');
        $record = $this->db()->table('users')->where('email', $email)->first();
        if (! $record) {
            return response()->json(['message' => 'Incorrect email or password.'], 401);
        }
        $attempt = $this->db()->table('login_attempts')->where('email', $email)->first();
        $now = time();
        if ($attempt && (int) $attempt->locked_until > $now) {
            return response()->json(['message' => 'Too many failed attempts. Please try again in 60 seconds.', 'retryAfter' => (int) $attempt->locked_until - $now], 429);
        }
        if (! password_verify($password, (string) $record->password_hash)) {
            $failed = $attempt ? ((int) $attempt->failed_attempts + 1) : 1;
            $lockedUntil = 0;
            if ($failed >= 3) {
                $lockedUntil = $now + 60;
                $failed = 3;
                $this->db()->table('login_attempts')->upsert(
                    [['email' => $email, 'failed_attempts' => $failed, 'locked_until' => $lockedUntil, 'updated_at' => now()->format('c')]],
                    ['email'],
                    ['failed_attempts', 'locked_until', 'updated_at']
                );

                return response()->json(['message' => 'Too many failed attempts. Please try again in 60 seconds.', 'retryAfter' => 60], 429);
            }
            $this->db()->table('login_attempts')->upsert(
                [['email' => $email, 'failed_attempts' => $failed, 'locked_until' => $lockedUntil, 'updated_at' => now()->format('c')]],
                ['email'],
                ['failed_attempts', 'locked_until', 'updated_at']
            );

            return response()->json(['message' => 'Incorrect email or password.'], 401);
        }
        $this->db()->table('login_attempts')->where('email', $email)->delete();
        $user = User::find($record->id);
        Auth::login($user);

        return response()->json(['user' => $this->userPayload($user)]);
    }

    public function me(Request $request): JsonResponse
    {
        $user = Auth::user();
        if (! $user) {
            return response()->json(['message' => 'Login required.'], 401);
        }
        $fresh = User::find($user->id);
        if ($fresh) {
            Auth::setUser($fresh);
            $user = $fresh;
        }

        return response()->json(['user' => $this->userPayload($user)]);
    }

    public function logout(Request $request): JsonResponse
    {
        Auth::logout();
        $request->session()->invalidate();
        $request->session()->regenerateToken();

        return response()->json(['message' => 'Logged out.']);
    }

    public function profile(Request $request): JsonResponse
    {
        $user = Auth::user();
        if (! $user) {
            return response()->json(['message' => 'Login required.'], 401);
        }
        $name = trim((string) $request->input('name', ''));
        $profileImage = (string) $request->input('profileImage', '');
        if ($name === '') {
            return response()->json(['message' => 'A full name is required.'], 400);
        }
        $user->name = $name;
        if ($profileImage !== '') {
            $user->profile_image = $profileImage;
        }
        $user->save();
        $this->audit('Updated profile');

        return response()->json(['user' => $this->userPayload($user)]);
    }

    public function password(Request $request): JsonResponse
    {
        $user = Auth::user();
        if (! $user) {
            return response()->json(['message' => 'Login required.'], 401);
        }
        $current = (string) $request->input('currentPassword', '');
        $new = (string) $request->input('newPassword', '');
        if (! password_verify($current, (string) $user->password_hash)) {
            return response()->json(['message' => 'The current password is incorrect.'], 400);
        }
        if (strlen($new) < 6) {
            return response()->json(['message' => 'The new password must be at least 6 characters.'], 400);
        }
        $user->password_hash = password_hash($new, PASSWORD_DEFAULT);
        $user->save();
        $this->audit('Changed administrator password');

        return response()->json(['message' => 'Password changed successfully.']);
    }

    public function requestPasswordReset(Request $request): JsonResponse
    {
        $email = strtolower(trim((string) $request->input('email', '')));
        if (! filter_var($email, FILTER_VALIDATE_EMAIL)) {
            return response()->json(['message' => 'Please provide a valid email address.'], 400);
        }
        $user = $this->db()->table('users')->where('email', $email)->first();
        if ($user) {
            $this->db()->table('password_reset_tokens')->where('email', $email)->delete();
            $code = str_pad((string) random_int(0, 999999), 6, '0', STR_PAD_LEFT);
            $this->db()->table('password_reset_tokens')->insert([
                'user_id' => (int) $user->id,
                'email' => $email,
                'token_hash' => password_hash($code, PASSWORD_DEFAULT),
                'expires_at' => time() + 900,
                'created_at' => now()->format('Y-m-d H:i:s'),
            ]);
            if (! $this->sendVerificationEmail($email, $code)) {
                $this->audit('Password reset email delivery failed for '.$email);

                return response()->json(['message' => 'Unable to send the verification code right now. Please check the email configuration and try again.'], 500);
            }
        }

        return response()->json(['message' => 'If that account exists, a 6-digit verification code has been sent to your email.']);
    }

    public function resetPassword(Request $request): JsonResponse
    {
        $email = strtolower(trim((string) $request->input('email', '')));
        $code = trim((string) $request->input('code', ''));
        $newPassword = (string) $request->input('newPassword', '');
        if (! filter_var($email, FILTER_VALIDATE_EMAIL)) {
            return response()->json(['message' => 'A valid email address is required.'], 400);
        }
        if (! preg_match('/^[0-9]{6}$/', $code)) {
            return response()->json(['message' => 'Please enter the 6-digit verification code.'], 400);
        }
        if (strlen($newPassword) < 6) {
            return response()->json(['message' => 'The new password must be at least 6 characters.'], 400);
        }
        $token = $this->db()->table('password_reset_tokens')->where('email', $email)->orderBy('expires_at', 'desc')->first();
        if (! $token || ! password_verify($code, (string) $token->token_hash) || (int) $token->expires_at < time()) {
            return response()->json(['message' => 'The verification code is invalid or has expired. Please request a new one.'], 400);
        }
        $this->db()->table('users')->where('email', $email)->update(['password_hash' => password_hash($newPassword, PASSWORD_DEFAULT)]);
        $this->db()->table('password_reset_tokens')->where('email', $email)->delete();
        $this->audit('Reset password for '.$email);

        return response()->json(['message' => 'Your password has been updated successfully.']);
    }

    private function userPayload(?User $user): array
    {
        if (! $user) {
            return [];
        }

        return [
            'id' => (int) $user->id,
            'name' => $user->name,
            'email' => $user->email,
            'role' => $user->role,
            'profileImage' => $user->profile_image,
        ];
    }

    private function sendVerificationEmail(string $recipient, string $code): bool
    {
        $configPath = public_path('mail-config.php');
        $config = is_file($configPath) ? require $configPath : [];
        if (! is_array($config) || empty($config['host']) || empty($config['username']) || empty($config['password'])) {
            return false;
        }
        $host = (string) $config['host'];
        $port = (int) ($config['port'] ?? 587);
        $encryption = strtolower((string) ($config['encryption'] ?? 'tls'));
        $from = (string) ($config['from'] ?? $config['username']);
        $fromName = (string) ($config['from_name'] ?? 'DRLCEFI Attendance');
        $remote = ($encryption === 'ssl' ? 'ssl://' : '').$host.':'.$port;
        $context = stream_context_create(['ssl' => ['verify_peer' => true, 'verify_peer_name' => true]]);
        $socket = @stream_socket_client($remote, $errorNumber, $errorMessage, 15, STREAM_CLIENT_CONNECT, $context);
        if (! $socket) {
            return false;
        }
        stream_set_timeout($socket, 15);
        $read = static function () use ($socket): string {
            $response = '';
            while (($line = fgets($socket, 515)) !== false) {
                $response .= $line;
                if (strlen($line) < 4 || $line[3] === ' ') {
                    break;
                }
            }

            return $response;
        };
        $write = static function (string $command) use ($socket, $read): bool {
            fwrite($socket, $command."\r\n");

            return (int) substr($read(), 0, 3) < 400;
        };
        $ready = (int) substr($read(), 0, 3) < 400;
        $ready = $ready && $write('EHLO localhost');
        if ($ready && $encryption === 'tls') {
            $ready = $write('STARTTLS') && @stream_socket_enable_crypto($socket, true, STREAM_CRYPTO_METHOD_TLS_CLIENT);
            $ready = $ready && $write('EHLO localhost');
        }
        $ready = $ready && $write('AUTH LOGIN');
        $ready = $ready && $write(base64_encode((string) $config['username']));
        $ready = $ready && $write(base64_encode((string) $config['password']));
        $ready = $ready && $write('MAIL FROM:<'.$from.'>');
        $ready = $ready && $write('RCPT TO:<'.$recipient.'>');
        $ready = $ready && $write('DATA');
        if ($ready) {
            $subject = 'DRLCEFI password reset verification code';
            $body = "Your DRLCEFI verification code is: {$code}\r\n\r\nThis code expires in 15 minutes. If you did not request a password reset, you can ignore this email.";
            $message = 'From: '.$fromName.' <'.$from.">\r\n"
                .'To: <'.$recipient.">\r\n"
                .'Subject: '.$subject."\r\n"
                ."MIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n"
                .$body;
            $message = preg_replace('/^\./m', '..', $message)."\r\n.";
            fwrite($socket, $message."\r\n");
            $ready = (int) substr($read(), 0, 3) < 400;
        }
        $write('QUIT');
        fclose($socket);

        return $ready;
    }
}
