<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Attendance Monitor</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Bodoni+Moda:opsz,wght@6..96,500;6..96,600;6..96,700&family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="{{ asset('css/theme.css') }}?v={{ filemtime(public_path('css/theme.css')) }}">
    <link rel="stylesheet" href="{{ asset('css/monitor.css') }}?v={{ filemtime(public_path('css/monitor.css')) }}">
    <script src="{{ asset('js/monitor.js') }}?v={{ filemtime(public_path('js/monitor.js')) }}" defer></script>
</head>
<body>
    <header><a class="brand" href="/monitor"><span class="brand-icon">✓</span> Attendance Monitor</a><div class="header-right"><span id="connection" class="connection">Connecting</span><button id="fullscreen" type="button">Fullscreen</button></div></header>
    <main>
        <div class="topline"><span id="mode" class="pill">STANDBY</span><time id="clock"></time></div>
        <section id="waiting" class="waiting" aria-live="polite">
            <div class="waiting-icon" aria-hidden="true">◎</div>
            <p class="eyebrow">FACE RECOGNITION ATTENDANCE</p>
            <h1 id="waiting-title">Waiting for Operation Mode</h1>
            <p id="waiting-description">The attendance monitor will activate when Operation Mode starts on the main computer.</p>
        </section>
        <section id="operation" class="operation" hidden aria-label="Live operation monitor">
            <div class="operation-heading"><div><p class="eyebrow">LIVE ATTENDANCE</p><h1 id="operation-title">Operation Mode</h1></div><span class="read-only">Student display</span></div>
            <div class="operation-grid">
                <section class="panel camera-panel"><h2><span class="live-dot"></span> Camera Feed</h2><div class="camera-frame"><img id="camera-feed" alt="Live camera feed from the main computer" hidden><p id="camera-placeholder">Connecting to camera…</p></div></section>
                <section class="panel profile-panel"><h2>Student Profile Image</h2><div class="profile-frame"><img id="portrait" alt="Registered student profile" hidden><div id="initials" class="initials">◎</div></div><p id="profile-name" class="profile-name">No student selected</p></section>
                <section class="panel info-panel"><h2>Face Information</h2><p id="face-message">No face detected yet.</p><dl id="face-details" hidden>
                    <div><dt>Name</dt><dd id="student-name"></dd></div>
                    <div><dt>Student ID</dt><dd id="student-id"></dd></div>
                    <div><dt>Course</dt><dd id="student-course"></dd></div>
                    <div><dt>Year</dt><dd id="student-year"></dd></div>
                    <div><dt>Age</dt><dd id="student-age"></dd></div>
                    <div><dt>School Year</dt><dd id="student-school-year"></dd></div>
                    <div><dt>Status</dt><dd id="student-status"></dd></div>
                </dl></section>
            </div>
            <div id="confirmation" class="attendance-confirmation" hidden role="status"><span class="confirmation-check">✓</span><div><strong id="action"></strong><p id="confirmation-name"></p></div><strong id="recorded-time"></strong></div>
        </section>
    </main>
    <footer><span>Face Recognition-Based Attendance System</span><span id="date"></span></footer>
</body>
</html>
