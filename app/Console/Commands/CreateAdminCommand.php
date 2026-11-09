<?php

namespace App\Console\Commands;

use Illuminate\Console\Command;
use PDO;

class CreateAdminCommand extends Command
{
    protected $signature = 'admin:create
        {email : Administrator email address}
        {--name= : Administrator full name}
        {--password= : Administrator password}';

    protected $description = 'Create an administrator account, or reset the password if the email already exists.';

    public function handle(): int
    {
        $email = strtolower(trim((string) $this->argument('email')));
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
            $this->error('A valid email address is required.');
            return self::FAILURE;
        }

        $name = trim((string) ($this->option('name') ?: ''));
        if ($name === '') {
            $name = $this->ask('Full name');
        }
        if ($name === '') {
            $this->error('A full name is required.');
            return self::FAILURE;
        }

        $password = (string) ($this->option('password') ?: '');
        if ($password === '') {
            $password = $this->secret('Password');
        }
        if (strlen($password) < 6) {
            $this->error('The password must be at least 6 characters.');
            return self::FAILURE;
        }

        $databasePath = public_path('attendance.sqlite');
        if (!is_file($databasePath)) {
            $this->error('Attendance database not found at ' . $databasePath);
            return self::FAILURE;
        }

        $pdo = new PDO('sqlite:' . $databasePath);
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->exec('PRAGMA foreign_keys = ON');

        $statement = $pdo->prepare('SELECT id FROM users WHERE email = ? LIMIT 1');
        $statement->execute([$email]);
        $existing = $statement->fetch(PDO::FETCH_ASSOC);

        $passwordHash = password_hash($password, PASSWORD_DEFAULT);

        if ($existing) {
            $update = $pdo->prepare('UPDATE users SET name = ?, password_hash = ? WHERE email = ?');
            $update->execute([$name, $passwordHash, $email]);
            $this->info('Password reset for existing administrator: ' . $email);
            return self::SUCCESS;
        }

        $insert = $pdo->prepare('INSERT INTO users (name, email, password_hash, role, profile_image, created_at) VALUES (?, ?, ?, ?, ?, ?)');
        $insert->execute([$name, $email, $passwordHash, 'Administrator', null, date('c')]);
        $this->info('Administrator account created: ' . $email);
        return self::SUCCESS;
    }
}
