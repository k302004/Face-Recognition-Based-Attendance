const REMEMBER_KEY = 'drlcefiRememberedLogin';
const SETTINGS_KEY = 'drlcefiDashboardSettings';
const THEME_KEY = 'drlcefiTheme';
let dashboardData = { students: [], schedules: [], attendance: [], audit: [], notificationSettings: {} };
let archivedYear = '';
let archivedCategory = 'students';
let editingRow = null;
let currentUser = null;
let sessionTimer = null;
let loginLockoutTimer = null;

function applyTheme(theme) {
    const isDark = theme === 'dark';
    document.body.dataset.theme = isDark ? 'dark' : 'light';
    document.querySelectorAll('.theme-toggle').forEach(function (toggle) {
        toggle.textContent = isDark ? 'Light mode' : 'Dark mode';
        toggle.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
    });
}

function initializeTheme() {
    const savedTheme = localStorage.getItem(THEME_KEY) || 'light';
    applyTheme(savedTheme);
    document.querySelectorAll('.theme-toggle').forEach(function (toggle) {
        toggle.addEventListener('click', function () {
            const nextTheme = document.body.dataset.theme === 'dark' ? 'light' : 'dark';
            localStorage.setItem(THEME_KEY, nextTheme);
            document.body.classList.add('theme-switching');
            applyTheme(nextTheme);
            window.setTimeout(function () {
                document.body.classList.remove('theme-switching');
            }, 460);
        });
    });
}

initializeTheme();

function getSurname(name) {
    const parts = String(name).trim().split(/\s+/);
    return parts.length > 1 ? parts[parts.length - 1] : parts[0];
}

function setAuthMessage(message, type) {
    const messageElement = document.getElementById('authMessage');
    if (messageElement) {
        messageElement.textContent = message;
        messageElement.className = `auth-message ${type || ''}`;
    }
}

function startLoginLockout(seconds) {
    const loginForm = document.getElementById('loginForm');
    const loginSubmit = loginForm.querySelector('.auth-submit');
    const loginInputs = loginForm.querySelectorAll('input');
    const messageElement = document.getElementById('authMessage');
    let remaining = Math.max(1, Number(seconds) || 60);
    if (loginLockoutTimer) clearInterval(loginLockoutTimer);
    loginSubmit.disabled = true;
    loginInputs.forEach(function (input) { input.disabled = true; });
    const updateLockout = function () {
        if (remaining <= 0) {
            clearInterval(loginLockoutTimer);
            loginLockoutTimer = null;
            loginSubmit.disabled = false;
            loginSubmit.textContent = 'Log in';
            loginInputs.forEach(function (input) { input.disabled = false; });
            setAuthMessage('You can try logging in again.');
            return;
        }
        loginSubmit.textContent = `Try again in ${remaining}s`;
        messageElement.className = 'auth-message error';
        messageElement.textContent = `Too many failed attempts. Try again in ${remaining} seconds.`;
        remaining -= 1;
    };
    updateLockout();
    loginLockoutTimer = setInterval(updateLockout, 1000);
}

async function showApp(user) {
    document.getElementById('authScreen').hidden = true;
    document.getElementById('appShell').hidden = false;
    const welcomeTitle = document.getElementById('dashboard-title');
    currentUser = user || {};
    const displayName = user && user.name ? user.name : 'Administrator';
    const role = currentUser.role || 'Administrator';

    if (welcomeTitle) {
        welcomeTitle.textContent = `Welcome, ${displayName}!`;
    }
    updateAdminIdentity();
    const dashboardSettings = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    document.body.classList.toggle('compact-tables', dashboardSettings.compactTables === true);
    applySystemSettings(dashboardSettings);
    resetSessionTimer();
    document.getElementById('appShell').dataset.role = role;
    applyRolePermissions(role);
    await loadDashboardData();
    await loadCameraConfig();
}

function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, function (character) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character];
    });
}

function showOperationExitModal() {
    return new Promise(function (resolve) {
        const modal = document.getElementById('operationExitModal');
        if (!modal) {
            resolve(false);
            return;
        }
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');

        const yesButton = document.getElementById('operationExitYes');
        const noButton = document.getElementById('operationExitNo');

        function cleanup(result) {
            modal.style.display = 'none';
            modal.setAttribute('aria-hidden', 'true');
            if (yesButton) yesButton.removeEventListener('click', onYes);
            if (noButton) noButton.removeEventListener('click', onNo);
            resolve(result);
        }

        function onYes() { cleanup(true); }
        function onNo() { cleanup(false); }

        if (yesButton) yesButton.addEventListener('click', onYes);
        if (noButton) noButton.addEventListener('click', onNo);
    });
}

function openCameraSelectModal(cameras) {
    const list = document.getElementById('cameraSelectList');
    const status = document.getElementById('cameraSelectStatus');
    const listToShow = Array.isArray(cameras) && cameras.length ? cameras : detectedCameras;
    if (list) {
        list.innerHTML = listToShow.map(function (camera) {
            const checked = selectedCameraId === camera.id ? 'checked' : '';
            return '<label class="camera-option"><input type="radio" name="operationCameraOption" value="' + escapeHtml(camera.id) + '" ' + checked + ' onchange="selectedCameraId = this.value"> ' + escapeHtml(camera.name) + '</label>';
        }).join('');
    }
    if (status) status.textContent = '';
    const modal = document.getElementById('cameraSelectModal');
    if (modal) {
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');
    }
}

function closeCameraSelectModal() {
    const modal = document.getElementById('cameraSelectModal');
    if (modal) {
        modal.style.display = 'none';
        modal.setAttribute('aria-hidden', 'true');
    }
}

function openCameraNoneModal() {
    const modal = document.getElementById('cameraNoneModal');
    if (modal) {
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');
    }
}

function closeCameraNoneModal() {
    const modal = document.getElementById('cameraNoneModal');
    if (modal) {
        modal.style.display = 'none';
        modal.setAttribute('aria-hidden', 'true');
    }
}

async function saveOperationCamera() {
    const status = document.getElementById('cameraSelectStatus');
    const selected = detectedCameras.find(function (camera) { return camera.id === selectedCameraId; });
    if (!selected) {
        if (status) status.textContent = 'Select a camera first.';
        return;
    }
    try {
        await requestApi('camera-save', {
            method: 'POST',
            body: JSON.stringify({ id: selected.id, name: selected.name })
        });
        if (status) status.textContent = 'Camera saved.';
        await loadCameraConfig();
        closeCameraSelectModal();
        // Retry entering operation mode now that a camera is configured.
        openOperationMode();
    } catch (error) {
        if (status) status.textContent = 'Unable to save camera.';
    }
}

async function ensureCameraConfigured() {
    // Check if a camera is already configured.
    try {
        const data = await requestApi('camera-config', { method: 'GET' });
        if (data && data.config && data.config.id) {
            selectedCameraId = data.config.id;
            return true;
        }
    } catch (error) {
        // ignore
    }
    // Detect available cameras.
    let cameras = [];
    try {
        const data = await requestApi('camera-list', { method: 'GET' });
        cameras = Array.isArray(data.cameras) ? data.cameras : [];
    } catch (error) {
        cameras = [];
    }
    detectedCameras = cameras;
    if (!cameras.length) {
        openCameraNoneModal();
        return false;
    }
    selectedCameraId = cameras[0].id;
    openCameraSelectModal(cameras);
    return false;
}

async function openOperationMode() {
    const configured = await ensureCameraConfigured();
    if (!configured) {
        return;
    }
    document.querySelectorAll('.view-section').forEach(function (section) {
        section.hidden = true;
    });
    const view = document.getElementById('operationModeView');
    if (view) view.hidden = false;
    document.querySelectorAll('.nav-link').forEach(function (item) {
        item.classList.remove('active');
    });

    document.body.classList.add('operation-mode-active');

    // Validate before stopping operation mode via Escape.
    operationEscapeHandler = async function (event) {
        if (event.key !== 'Escape') return;
        event.preventDefault();
        const shouldStop = await showOperationExitModal();
        if (shouldStop) {
            closeOperationMode();
        } else {
            const requestFs = document.documentElement.requestFullscreen || document.documentElement.webkitRequestFullscreen || document.documentElement.mozRequestFullScreen || document.documentElement.msRequestFullscreen;
            if (requestFs) {
                try { requestFs.call(document.documentElement); } catch (error) { /* ignore */ }
            }
        }
    };
    document.addEventListener('keydown', operationEscapeHandler);

    operationFullscreenHandler = async function () {
        if (!document.body.classList.contains('operation-mode-active')) return;
        const isFullscreen = !!(document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement);
        if (isFullscreen) return;
        const shouldStop = await showOperationExitModal();
        if (shouldStop) {
            closeOperationMode();
        } else {
            const requestFs = document.documentElement.requestFullscreen || document.documentElement.webkitRequestFullscreen || document.documentElement.mozRequestFullScreen || document.documentElement.msRequestFullscreen;
            if (requestFs) {
                try { requestFs.call(document.documentElement); } catch (error) { /* ignore */ }
            }
        }
    };
    document.addEventListener('fullscreenchange', operationFullscreenHandler);
    document.addEventListener('webkitfullscreenchange', operationFullscreenHandler);
    document.addEventListener('mozfullscreenchange', operationFullscreenHandler);
    document.addEventListener('MSFullscreenChange', operationFullscreenHandler);

    // Force the browser into fullscreen mode for operation mode.
    const fullscreenTarget = document.documentElement;
    const requestFs = fullscreenTarget.requestFullscreen || fullscreenTarget.webkitRequestFullscreen || fullscreenTarget.mozRequestFullScreen || fullscreenTarget.msRequestFullscreen;
    if (requestFs) {
        try { requestFs.call(fullscreenTarget); } catch (error) { /* ignore */ }
    }

    const img = document.getElementById('cameraFeedImg');
    const placeholder = document.querySelector('.camera-feed__placeholder');
    const feedContainer = document.getElementById('cameraFeed');

    // Allow the browser to lay out the newly shown view before measuring.
    await new Promise(function (resolve) { requestAnimationFrame(function () { setTimeout(resolve, 250); }); });

    await startCameraStream(img, placeholder, feedContainer, true);

    // Poll the backend for the currently detected face/student.
    var _recordedAttendance = {};
    function updateFaceInfoFromData(data) {
        const info = (data && data.student) ? data.student : null;
        const faceDetected = !!(data && data.face_detected);
        if (!dashboardData || !Array.isArray(dashboardData.students) || dashboardData.students.length === 0) {
            loadDashboardData().catch(function () { /* ignore */ });
        }
        const faceInfo = document.getElementById('faceInfo');
        if (faceInfo) {
            if (info && info.student_id && faceDetected) {
                let student = (dashboardData.students || []).find(function (item) {
                    return String(item.student_id) === String(info.student_id);
                });
                if (!student && info.name) {
                    student = (dashboardData.students || []).find(function (item) {
                        return String(item.full_name).trim().toLowerCase() === String(info.name).trim().toLowerCase();
                    });
                }
                if (info && (info.course || info.year || info.full_name || info.face_image_path)) {
                    student = Object.assign({}, student || {}, {
                        full_name: info.full_name || (student && student.full_name) || info.name,
                        course: info.course || (student && student.course),
                        year: info.year || (student && student.year),
                        age: info.age || (student && student.age),
                        school_year: info.school_year || (student && student.school_year),
                        status: info.status || (student && student.status),
                        parent_phone: info.parent_phone || (student && student.parent_phone),
                        face_image_path: info.face_image_path || (student && student.face_image_path),
                    });
                }
                const details = [];
                details.push('<div class="student-detail-row"><span class="student-detail-label">Name</span><span class="student-detail-value">' + escapeHtml((student && student.full_name) || info.name || info.student_id) + '</span></div>');
                details.push('<div class="student-detail-row"><span class="student-detail-label">Student ID</span><span class="student-detail-value">' + escapeHtml(info.student_id) + '</span></div>');
                if (student) {
                    details.push('<div class="student-detail-row"><span class="student-detail-label">Course</span><span class="student-detail-value">' + escapeHtml(student.course || '\u2014') + '</span></div>');
                    details.push('<div class="student-detail-row"><span class="student-detail-label">Year</span><span class="student-detail-value">' + escapeHtml(student.year || '\u2014') + '</span></div>');
                    if (student.age) {
                        details.push('<div class="student-detail-row"><span class="student-detail-label">Age</span><span class="student-detail-value">' + escapeHtml(student.age) + '</span></div>');
                    }
                    details.push('<div class="student-detail-row"><span class="student-detail-label">School Year</span><span class="student-detail-value">' + escapeHtml(student.school_year || '\u2014') + '</span></div>');
                    details.push('<div class="student-detail-row"><span class="student-detail-label">Status</span><span class="student-detail-value">' + escapeHtml(student.status || '\u2014') + '</span></div>');
                    if (student.parent_phone) {
                        details.push('<div class="student-detail-row"><span class="student-detail-label">Parent Phone</span><span class="student-detail-value">' + escapeHtml(student.parent_phone) + '</span></div>');
                    }
                    if (typeof info.confidence !== 'undefined') {
                        details.push('<div class="student-detail-row"><span class="student-detail-label">Confidence</span><span class="student-detail-value">' + escapeHtml(Number(info.confidence).toFixed(2)) + '</span></div>');
                    }
                } else {
                    details.push('<div class="student-detail-row"><span class="student-detail-value">Student details not found in dashboard data (detected ID: ' + escapeHtml(info.student_id) + ').</span></div>');
                }
                faceInfo.innerHTML = '<div class="student-details">' + details.join('') + '</div>';
                // Auto-record attendance when a face is detected (once per student per session).
                if (info && info.student_id && !_recordedAttendance[info.student_id]) {
                    _recordedAttendance[info.student_id] = true;
                    fetch('api.php?action=record-attendance', {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ studentId: info.student_id })
                    }).then(function (r) { return r.json(); }).then(function (result) {
                        if (result && result.action === 'time_in') {
                            // Show a brief confirmation.
                            var confirmEl = document.createElement('div');
                            confirmEl.className = 'student-detail-row';
                            confirmEl.innerHTML = '<span class="student-detail-value" style="color:#22c55e;">✓ Attendance recorded: ' + escapeHtml(result.status || 'Present') + ' at ' + escapeHtml(result.timeIn || '') + '</span>';
                            faceInfo.querySelector('.student-details').appendChild(confirmEl);
                        }
                    }).catch(function () { /* ignore */ });
                }
            } else if (faceDetected) {
                faceInfo.innerHTML = '<div class="student-details"><div class="student-detail-row"><span class="student-detail-value">Face detected. (Recognition unavailable on this machine)</span></div></div>';
            } else {
                faceInfo.innerHTML = '<div class="student-details"><div class="student-detail-row"><span class="student-detail-value">No face detected yet.</span></div></div>';
            }
        }
        const profileImage = document.getElementById('profileImage');
        if (profileImage) {
            if (info && info.student_id && faceDetected) {
                let student = (dashboardData.students || []).find(function (item) {
                    return String(item.student_id) === String(info.student_id);
                });
                if (!student && info.name) {
                    student = (dashboardData.students || []).find(function (item) {
                        return String(item.full_name).trim().toLowerCase() === String(info.name).trim().toLowerCase();
                    });
                }
                if (info && (info.course || info.year || info.full_name || info.face_image_path)) {
                    student = Object.assign({}, student || {}, {
                        full_name: info.full_name || (student && student.full_name) || info.name,
                        face_image_path: info.face_image_path || (student && student.face_image_path),
                    });
                }
                let imageMarkup = '';
                if (student && student.face_image_path) {
                    const firstPath = String(student.face_image_path).split(',')[0].trim().replace(/^\/+/, '');
                    imageMarkup = '<img src="/' + escapeHtml(firstPath) + '" alt="Student profile" style="width:100%;height:100%;object-fit:cover;border-radius:8px;" onerror="this.style.display=\'none\';">';
                }
                profileImage.innerHTML = imageMarkup + '<span class="profile-image__name">' + escapeHtml((student && student.full_name) || info.name || info.student_id) + '</span>';
            } else {
                profileImage.textContent = 'No student selected.';
            }
        }
    }

    if (operationFacePollTimer) { clearInterval(operationFacePollTimer); operationFacePollTimer = null; }
    if (window.faceWebSocket) { window.faceWebSocket.close(); }
    var _lastCameraData = null;
    var _lastFetchTime = 0;
    function fetchCameraCurrentStudent() {
        var now = Date.now();
        if (now - _lastFetchTime < 300) return; // debounce
        _lastFetchTime = now;
        fetch('/api/camera-current-student', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (data) {
            var key = JSON.stringify({ s: data && data.student && data.student.student_id, f: data && data.face_detected });
            if (key === _lastCameraData) return; // cache: skip if unchanged
            _lastCameraData = key;
            updateFaceInfoFromData(data);
        }).catch(function () { /* ignore */ });
    }
    try {
        const ws = new WebSocket('wss://' + window.location.host + '/ws');
        window.faceWebSocket = ws;
        ws.onmessage = function (e) {
            try {
                const data = JSON.parse(e.data);
                var key = JSON.stringify({ s: data && data.student && data.student.student_id, f: data && data.face_detected });
                if (key === _lastCameraData) return;
                _lastCameraData = key;
                updateFaceInfoFromData(data);
            } catch (err) { /* ignore */ }
        };
        ws.onerror = function () {
            if (!operationFacePollTimer) {
                operationFacePollTimer = setInterval(fetchCameraCurrentStudent, 500);
            }
        };
        ws.onclose = function () {
            if (!operationFacePollTimer) {
                operationFacePollTimer = setInterval(fetchCameraCurrentStudent, 500);
            }
        };
    } catch (e) {
        operationFacePollTimer = setInterval(fetchCameraCurrentStudent, 500);
    }
    fetchCameraCurrentStudent();

    // Keep the stream resolution in sync with the container if its size changes
    // (e.g. when fullscreen settles or the window is resized).
    if (!cameraResizeHandler) {
        let resizeTimer = null;
        cameraResizeHandler = function () {
            if (resizeTimer) clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () {
                const container = document.getElementById('cameraFeed');
                const image = document.getElementById('cameraFeedImg');
                const place = document.querySelector('.camera-feed__placeholder');
                startCameraStream(image, place, container, false);
            }, 300);
        };
        window.addEventListener('resize', cameraResizeHandler);
        document.addEventListener('fullscreenchange', cameraResizeHandler);
        document.addEventListener('webkitfullscreenchange', cameraResizeHandler);
        document.addEventListener('mozfullscreenchange', cameraResizeHandler);
        document.addEventListener('MSFullscreenChange', cameraResizeHandler);
    }
}

async function closeOperationMode() {
    document.body.classList.remove('operation-mode-active');
    if (operationEscapeHandler) {
        document.removeEventListener('keydown', operationEscapeHandler);
        operationEscapeHandler = null;
    }
    if (operationFullscreenHandler) {
        document.removeEventListener('fullscreenchange', operationFullscreenHandler);
        document.removeEventListener('webkitfullscreenchange', operationFullscreenHandler);
        document.removeEventListener('mozfullscreenchange', operationFullscreenHandler);
        document.removeEventListener('MSFullscreenChange', operationFullscreenHandler);
        operationFullscreenHandler = null;
    }
    const exitFs = document.exitFullscreen || document.webkitExitFullscreen || document.mozCancelFullScreen || document.msExitFullscreen;
    if (exitFs && (document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement)) {
        try { exitFs.call(document); } catch (error) { /* ignore */ }
    }
    const view = document.getElementById('operationModeView');
    if (view) view.hidden = true;
    if (operationFacePollTimer) {
        clearInterval(operationFacePollTimer);
        operationFacePollTimer = null;
    }
    if (window.faceWebSocket) {
        window.faceWebSocket.close();
        window.faceWebSocket = null;
    }
    const img = document.getElementById('cameraFeedImg');
    if (img) {
        img.src = '';
        img.style.display = 'none';
    }
    const placeholder = document.querySelector('.camera-feed__placeholder');
    if (placeholder) placeholder.style.display = 'flex';
    if (cameraResizeHandler) {
        window.removeEventListener('resize', cameraResizeHandler);
        document.removeEventListener('fullscreenchange', cameraResizeHandler);
        document.removeEventListener('webkitfullscreenchange', cameraResizeHandler);
        document.removeEventListener('mozfullscreenchange', cameraResizeHandler);
        document.removeEventListener('MSFullscreenChange', cameraResizeHandler);
        cameraResizeHandler = null;
    }
    cameraStreamWidth = 0;
    cameraStreamHeight = 0;
    hideCameraInitOverlay();
    try {
        await requestApi('camera-stream-stop', { method: 'POST' });
    } catch (error) {
        // ignore
    }
    const home = document.getElementById('homeView');
    if (home) home.hidden = false;
    const homeLink = document.querySelector('[data-view="home"]');
    if (homeLink) homeLink.classList.add('active');
}

function statusClass(value) {
    const status = String(value).toLowerCase();
    if (status.includes('absent') || status.includes('risk') || status.includes('danger')) return 'danger';
    if (status.includes('late') || status.includes('warning')) return 'warning';
    return 'good';
}

function statusBadge(value) {
    return `<span class="status-indicator ${statusClass(value)}">${escapeHtml(value)}</span>`;
}

function updateAdminIdentity() {
    const icon = document.querySelector('.admin-icon');
    if (!icon) return;
    if (currentUser && currentUser.profileImage) {
        icon.textContent = '';
        icon.style.backgroundImage = `url("${currentUser.profileImage}")`;
        icon.classList.add('has-profile-image');
    } else {
        icon.textContent = '👤';
        icon.style.backgroundImage = '';
        icon.classList.remove('has-profile-image');
    }
}

async function loadDashboardData() {
    dashboardData = await requestApi('dashboard');
    const studentsBody = document.querySelector('#studentTable tbody');
    if (studentsBody) {
        const sortedStudents = dashboardData.students.slice().sort(function (firstStudent, secondStudent) {
            const surnameOrder = getSurname(firstStudent.full_name).localeCompare(getSurname(secondStudent.full_name), undefined, { sensitivity: 'base' });
            return surnameOrder || String(firstStudent.full_name).localeCompare(String(secondStudent.full_name), undefined, { sensitivity: 'base' });
        });
        studentsBody.innerHTML = sortedStudents.map(function (student) {
            const archived = Number(student.is_archived) === 1;
            return `<tr data-student-id="${escapeHtml(student.student_id)}" data-student-row-id="${escapeHtml(String(student.id))}" data-student-status="${archived ? 'archived' : 'active'}" data-student-face-image-path="${escapeHtml(student.face_image_path || '')}">
                <td>${escapeHtml(student.student_id)}</td><td>${escapeHtml(student.full_name)}</td>
                <td>${escapeHtml(student.course)}</td><td>${escapeHtml(student.year)}</td><td>${escapeHtml(student.school_year || 'Unassigned')}</td>
                <td>${statusBadge(student.status)}</td><td><details class="row-menu"><summary aria-label="Student actions">•••</summary><div class="row-menu__content"><button class="menu-item" type="button" onclick="openStudentProfile(this)">Profile</button><button class="menu-item edit-btn" type="button" onclick="openStudentModal(this.closest('tr'))">Edit</button><button class="menu-item delete-btn" type="button" onclick="deleteStudent(this.closest('tr'))">Delete</button></div></details></td></tr>`;
        }).join('');
        filterStudents();
        renderArchivedStudents();
    }
    const attendanceBody = document.getElementById('attendanceTableBody');
    if (attendanceBody) {
        attendanceBody.innerHTML = dashboardData.attendance.map(function (record) {
            return `<tr data-course="${escapeHtml(record.course)}" data-attendance-date="${attendanceDateKey(record.attendance_date)}" data-attendance-archived="${Number(record.is_archived) === 1}"><td>${escapeHtml(record.student_id)}</td><td>${escapeHtml(record.student_name)}</td><td>${escapeHtml(record.attendance_date)}</td><td>${escapeHtml(record.subject)}</td><td>${escapeHtml(record.time_in)}</td><td>${escapeHtml(record.time_out)}</td><td>${statusBadge(record.status)}</td><td><details class="row-menu"><summary aria-label="Attendance actions">•••</summary><div class="row-menu__content"><button class="menu-item" type="button">View</button></div></details></td></tr>`;
        }).join('');
        getAttendanceRows().forEach(function (row) { row.dataset.matchesFilter = 'true'; });
        renderAttendanceDateControls();
        applyAttendanceFilters();
    }
    const scheduleBody = document.getElementById('scheduleTableBody');
    if (scheduleBody) {
        scheduleBody.innerHTML = dashboardData.schedules.map(function (schedule) {
            return `<tr data-schedule-id="${escapeHtml(schedule.id)}" data-school-year="${escapeHtml(schedule.school_year || '2026-2027')}"><td>${escapeHtml(schedule.school_year || '2026-2027')}</td><td>${escapeHtml(schedule.subject)}</td><td>${escapeHtml(schedule.instructor)}</td><td>${escapeHtml(schedule.room)}</td><td>${escapeHtml(schedule.day)}</td><td>${escapeHtml(schedule.start_time)} - ${escapeHtml(schedule.end_time)}</td><td><details class="row-menu"><summary aria-label="Schedule actions">•••</summary><div class="row-menu__content"><button class="menu-item edit-btn" type="button" onclick="editRow(this)">Edit</button><button class="menu-item delete-btn" type="button" onclick="openDeleteModal(this)">Delete</button></div></details></td></tr>`;
        }).join('');
        applyScheduleFilters();
    }
    renderAuditLog();
    renderAttendanceHistory();
    updateOverviewStats();
    if (archivedYear) renderArchivedCategory();
    loadNotificationSettingsFromData();
    applyRolePermissions(document.getElementById('appShell').dataset.role || 'Administrator');
    applySavedDashboardView();
}

function showAuth() {
    document.getElementById('authScreen').hidden = false;
    document.getElementById('appShell').hidden = true;
}

function switchAuthMode(mode) {
    const isLogin = mode === 'login';
    const resetForm = document.getElementById('resetForm');
    const verificationFields = document.getElementById('resetVerificationFields');

    resetForm.hidden = true;
    verificationFields.hidden = true;
    resetForm.reset();
    document.getElementById('resetCode').required = false;
    document.getElementById('resetNewPassword').required = false;
    document.getElementById('resetConfirmPassword').required = false;
    document.querySelector('.auth-tabs').hidden = false;
    document.getElementById('forgotPasswordLink').hidden = false;
    document.getElementById('loginTab').classList.toggle('active', isLogin);
    document.getElementById('signupTab').classList.toggle('active', !isLogin);
    document.getElementById('loginTab').setAttribute('aria-selected', String(isLogin));
    document.getElementById('signupTab').setAttribute('aria-selected', String(!isLogin));
    document.getElementById('loginForm').hidden = !isLogin;
    document.getElementById('signupForm').hidden = isLogin;
    document.getElementById('authTitle').textContent = isLogin ? 'Welcome back' : 'Create your account';
    document.getElementById('authSubtitle').textContent = isLogin
        ? 'Sign in to manage your attendance dashboard.'
        : 'Create an account to access your attendance dashboard.';
    setAuthMessage('');
}

function showResetForm() {
    document.getElementById('loginForm').hidden = true;
    document.getElementById('signupForm').hidden = true;
    document.getElementById('resetForm').hidden = false;
    document.querySelector('.auth-tabs').hidden = true;
    document.getElementById('forgotPasswordLink').hidden = true;
    document.getElementById('authTitle').textContent = 'Reset your password';
    document.getElementById('authSubtitle').textContent = 'We will send a verification code to your email.';
    document.getElementById('resetEmail').value = document.getElementById('loginEmail').value;
    document.getElementById('resetEmail').readOnly = false;
    document.getElementById('resetEmail').required = true;
    document.getElementById('resetVerificationFields').hidden = true;
    document.getElementById('resetCode').required = false;
    document.getElementById('resetNewPassword').required = false;
    document.getElementById('resetConfirmPassword').required = false;
    document.getElementById('resetSubmit').textContent = 'Send verification code';
    document.getElementById('resetSubmit').disabled = false;
    setAuthMessage('');
}

async function requestApi(action, options) {
    const response = await fetch(`api.php?action=${action}`, {
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        ...options
    });
    const rawText = await response.text();
    let data = {};
    if (rawText) {
        try {
            data = JSON.parse(rawText);
        } catch (error) {
            const contentType = String(response.headers.get('content-type') || '');
            const message = contentType.includes('text/html')
                ? 'The server returned an HTML error page. Check the PHP logs and try again.'
                : 'The server returned an invalid JSON response.';
            const invalidResponse = new Error(message);
            invalidResponse.rawText = rawText;
            throw invalidResponse;
        }
    }
    if (!response.ok) {
        const error = new Error(data.message || 'Request failed.');
        error.retryAfter = data.retryAfter;
        error.details = data.details;
        throw error;
    }
    return data;
}

async function initializeAuth() {
    const rememberedLogin = JSON.parse(localStorage.getItem(REMEMBER_KEY) || 'null');

    if (rememberedLogin) {
        document.getElementById('loginEmail').value = rememberedLogin.email || '';
        document.getElementById('loginPassword').value = rememberedLogin.password || '';
        document.getElementById('rememberPassword').checked = true;
    }

    showAuth();
    try {
        const data = await requestApi('me');
        await showApp(data.user);
    } catch (error) {
        // No active session keeps the login form visible.
    }

    document.getElementById('loginTab').addEventListener('click', function () { switchAuthMode('login'); });
    document.getElementById('signupTab').addEventListener('click', function () { switchAuthMode('signup'); });
    document.getElementById('forgotPasswordLink').addEventListener('click', showResetForm);
    document.getElementById('resetBack').addEventListener('click', function () { switchAuthMode('login'); });

    document.getElementById('loginForm').addEventListener('submit', async function (event) {
        event.preventDefault();
        const email = document.getElementById('loginEmail').value.trim().toLowerCase();
        const password = document.getElementById('loginPassword').value;
        if (document.getElementById('rememberPassword').checked) {
            localStorage.setItem(REMEMBER_KEY, JSON.stringify({ email: email, password: password }));
        } else {
            localStorage.removeItem(REMEMBER_KEY);
        }

        try {
            const data = await requestApi('login', { method: 'POST', body: JSON.stringify({ email, password }) });
            await showApp(data.user);
        } catch (error) {
            setAuthMessage(error.message, 'error');
            if (error.retryAfter) startLoginLockout(error.retryAfter);
        }
    });

    document.getElementById('signupForm').addEventListener('submit', async function (event) {
        event.preventDefault();
        const name = document.getElementById('signupFullName').value.trim();
        const email = document.getElementById('signupEmail').value.trim().toLowerCase();
        const password = document.getElementById('signupPassword').value;
        try {
            const data = await requestApi('signup', { method: 'POST', body: JSON.stringify({ name, email, password }) });
            localStorage.setItem(REMEMBER_KEY, JSON.stringify({ email: email, password: password }));
            await showApp(data.user);
        } catch (error) {
            setAuthMessage(error.message, 'error');
        }


    });

    document.getElementById('resetForm').addEventListener('submit', async function (event) {
        event.preventDefault();
        const email = document.getElementById('resetEmail').value.trim().toLowerCase();
        const verificationFields = document.getElementById('resetVerificationFields');
        const submitButton = document.getElementById('resetSubmit');
        const defaultSubmitLabel = verificationFields.hidden ? 'Send verification code' : 'Change password';
        submitButton.disabled = true;
        submitButton.textContent = verificationFields.hidden ? 'Sending...' : 'Updating...';
        try {
            if (verificationFields.hidden) {
                await requestApi('request-password-reset', { method: 'POST', body: JSON.stringify({ email }) });
                verificationFields.hidden = false;
                document.getElementById('resetCode').required = true;
                document.getElementById('resetNewPassword').required = true;
                document.getElementById('resetConfirmPassword').required = true;
                submitButton.textContent = 'Change password';
                setAuthMessage('Check your email for the 6-digit verification code.');
                return;
            }
            const newPassword = document.getElementById('resetNewPassword').value;
            if (newPassword !== document.getElementById('resetConfirmPassword').value) throw new Error('The passwords do not match.');
            const code = document.getElementById('resetCode').value.trim();
            const data = await requestApi('reset-password', { method: 'POST', body: JSON.stringify({ email, code, newPassword }) });
            document.getElementById('resetForm').reset();
            switchAuthMode('login');
            setAuthMessage(data.message);
        } catch (error) {
            setAuthMessage(error.message, 'error');
        } finally {
            submitButton.disabled = false;
            if (!submitButton.textContent || submitButton.textContent.endsWith('...')) submitButton.textContent = defaultSubmitLabel;
        }
    });

    document.getElementById('logoutLink').addEventListener('click', function (event) {
        event.preventDefault();
        requestApi('logout', { method: 'POST' }).finally(function () {
            showAuth();
            switchAuthMode('login');
            document.getElementById('loginForm').reset();
        });
    });

    document.getElementById('profileLink').addEventListener('click', function (event) {
        event.preventDefault();
        closeAccountMenu();
        openAdminProfile();
    });
    document.getElementById('settingsLink').addEventListener('click', function (event) {
        event.preventDefault();
        closeAccountMenu();
        openSettings();
    });

}

initializeAuth().catch(function () {
    setAuthMessage('The SQLite service is unavailable. Start the PHP server and try again.', 'error');
});

function toggleMenu() {
    const menu = document.getElementById('menu');
    const button = document.querySelector('.admin-btn');

    if (menu) {
        menu.classList.toggle('show');
    }

    if (button) {
        const isExpanded = button.getAttribute('aria-expanded') === 'true';
        button.setAttribute('aria-expanded', String(!isExpanded));
    }
}

function closeAccountMenu() {
    const menu = document.getElementById('menu');
    const button = document.querySelector('.admin-btn');
    if (menu) menu.classList.remove('show');
    if (button) button.setAttribute('aria-expanded', 'false');
}

function openAdminProfile() {
    document.getElementById('profileName').value = currentUser.name || '';
    document.getElementById('profileEmail').value = currentUser.email || '';
    document.getElementById('profileRole').value = currentUser.role || 'Administrator';
    renderProfilePreview(currentUser.profileImage);
    document.getElementById('profileMessage').textContent = '';
    const modal = document.getElementById('adminProfileModal');
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
}

function closeAdminProfile() {
    const modal = document.getElementById('adminProfileModal');
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');
}

function renderProfilePreview(image) {
    const preview = document.getElementById('adminProfilePhotoPreview');
    if (!preview) return;
    preview.textContent = image ? '' : '👤';
    preview.style.backgroundImage = image ? `url("${image}")` : '';
    preview.classList.toggle('has-profile-image', Boolean(image));
}

function openSettings() {
    document.getElementById('settingsCurrentPassword').value = '';
    document.getElementById('settingsNewPassword').value = '';
    document.getElementById('settingsConfirmPassword').value = '';
    document.getElementById('settingsMessage').textContent = '';
    const modal = document.getElementById('settingsModal');
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
}

function closeSettings() {
    const modal = document.getElementById('settingsModal');
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');
}

function toggleToolMenu(menuId, button) {
    const menu = document.getElementById(menuId);
    if (!menu) return;
    const isOpen = menu.classList.toggle('show');
    button.setAttribute('aria-expanded', String(isOpen));
}

function closeToolMenus() {
    document.querySelectorAll('.tool-popover.show').forEach(function (menu) { menu.classList.remove('show'); });
    document.querySelectorAll('.toolbar-menu.search-menu[open]').forEach(function (menu) { menu.removeAttribute('open'); });
    document.querySelectorAll('.tool-btn[aria-expanded="true"]').forEach(function (button) { button.setAttribute('aria-expanded', 'false'); });
}

window.addEventListener('click', function (event) {
    if (!event.target.closest('.search-menu')) closeToolMenus();
    if (!event.target.closest('.admin')) {
        const menu = document.getElementById('menu');
        const button = document.querySelector('.admin-btn');

        if (menu) {
            menu.classList.remove('show');
        }

        if (button) {
            button.setAttribute('aria-expanded', 'false');
        }
    }
});

document.querySelectorAll('.nav-link').forEach(function (link) {
    link.addEventListener('click', function (event) {
        event.preventDefault();

        document.querySelectorAll('.nav-link').forEach(function (item) {
            item.classList.remove('active');
        });

        this.classList.add('active');

        const target = this.dataset.view;
        const dashboardSettings = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
        if (dashboardSettings.rememberView !== false) {
            dashboardSettings.lastView = target;
            localStorage.setItem(SETTINGS_KEY, JSON.stringify(dashboardSettings));
        }
        document.getElementById('homeView').hidden = target !== 'home';
        document.getElementById('scheduleView').hidden = target !== 'schedule';
        document.getElementById('attendanceView').hidden = target !== 'attendance';
        document.getElementById('reportView').hidden = target !== 'report';
        document.getElementById('overviewView').hidden = target !== 'overview';
        document.getElementById('historyView').hidden = target !== 'history';
        document.getElementById('archiveView').hidden = target !== 'archives';
        document.getElementById('archiveDetailView').hidden = true;
        document.getElementById('setupsView').hidden = target !== 'setups';
        document.getElementById('studentRegistrationView').hidden = target !== 'student-registration';
        document.getElementById('operationModeView').hidden = true;
        document.body.classList.remove('operation-mode-active');
        if (operationEscapeHandler) {
            document.removeEventListener('keydown', operationEscapeHandler);
            operationEscapeHandler = null;
        }
        if (operationFullscreenHandler) {
            document.removeEventListener('fullscreenchange', operationFullscreenHandler);
            document.removeEventListener('webkitfullscreenchange', operationFullscreenHandler);
            document.removeEventListener('mozfullscreenchange', operationFullscreenHandler);
            document.removeEventListener('MSFullscreenChange', operationFullscreenHandler);
            operationFullscreenHandler = null;
        }
        const _exitFs = document.exitFullscreen || document.webkitExitFullscreen || document.mozCancelFullScreen || document.msExitFullscreen;
        if (_exitFs && (document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement)) {
            try { _exitFs.call(document); } catch (error) { /* ignore */ }
        }
        const _opImg = document.getElementById('cameraFeedImg');
        if (_opImg) { _opImg.src = ''; _opImg.style.display = 'none'; }
    });
});

function attendanceDateKey(value) {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function attendanceDateLabel(dateKey) {
    const parts = dateKey.split('-').map(Number);
    return new Date(parts[0], parts[1] - 1, parts[2]).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' });
}

const attendanceState = {
    selectedDate: attendanceDateKey(new Date()),
    sortKey: '',
    sortDirection: 1,
    page: 1,
    pageSize: 10
};

function renderAttendanceDateControls() {
    const todayKey = attendanceDateKey(new Date());
    const label = document.getElementById('attendanceDateLabel');
    const nextButton = document.querySelector('.attendance-date-nav .date-nav-button:nth-of-type(2)');
    if (label) label.textContent = attendanceState.selectedDate === todayKey ? 'Today' : attendanceDateLabel(attendanceState.selectedDate);
    if (nextButton) nextButton.disabled = attendanceState.selectedDate >= todayKey;
}

function selectAttendanceDate(dateKey) {
    const todayKey = attendanceDateKey(new Date());
    attendanceState.selectedDate = dateKey > todayKey ? todayKey : dateKey;
    renderAttendanceDateControls();
    applyAttendanceFilters();
}

function changeAttendanceDate(change) {
    const parts = attendanceState.selectedDate.split('-').map(Number);
    const date = new Date(parts[0], parts[1] - 1, parts[2]);
    date.setDate(date.getDate() + change);
    selectAttendanceDate(attendanceDateKey(date));
}

function goToAttendanceToday() {
    selectAttendanceDate(attendanceDateKey(new Date()));
}

function renderAttendanceHistory() {
    const list = document.getElementById('attendanceHistoryList');
    const empty = document.getElementById('attendanceHistoryEmpty');
    if (!list) return;
    const todayKey = attendanceDateKey(new Date());
    const grouped = {};
    dashboardData.attendance.forEach(function (record) {
        const dateKey = attendanceDateKey(record.attendance_date);
        if (!dateKey || dateKey >= todayKey) return;
        if (!grouped[dateKey]) grouped[dateKey] = { total: 0, Present: 0, Late: 0, Absent: 0 };
        grouped[dateKey].total += 1;
        grouped[dateKey][record.status] = (grouped[dateKey][record.status] || 0) + 1;
    });
    const dates = Object.keys(grouped).sort().reverse();
    list.innerHTML = dates.map(function (dateKey) {
        const summary = grouped[dateKey];
        return `<div class="attendance-history-row"><div><strong>${attendanceDateLabel(dateKey)}</strong><span>${summary.total} records • ${summary.Present} present • ${summary.Absent} absent</span></div><button class="menu-item" type="button" onclick="selectAttendanceDate('${dateKey}'); document.querySelector('[data-view=attendance]').click()">View</button></div>`;
    }).join('');
    if (empty) empty.hidden = dates.length > 0;
}

function getAttendanceRows() {
    const tableBody = document.getElementById('attendanceTableBody');
    return tableBody ? Array.from(tableBody.querySelectorAll('tr')) : [];
}

function getAttendanceValue(row, key) {
    const cellMap = { id: 0, name: 1, date: 2, subject: 3, timeIn: 4, timeOut: 5, status: 6 };
    return (row.cells[cellMap[key]]?.textContent || '').trim().toLowerCase();
}

function applyAttendanceFilters() {
    const search = document.getElementById('attendanceSearch').value.trim().toLowerCase();
    const subject = document.getElementById('attendanceSubjectFilter').value;
    const status = document.getElementById('attendanceStatusFilter').value;
    const course = document.getElementById('attendanceCourseFilter').value;

    getAttendanceRows().forEach(function (row) {
        const matches = (!search || getAttendanceValue(row, 'name').includes(search))
            && row.dataset.attendanceDate === attendanceState.selectedDate
            && row.dataset.attendanceArchived !== 'true'
            && (!subject || row.cells[3].textContent.trim() === subject)
            && (!status || row.cells[6].textContent.trim() === status)
            && (!course || row.dataset.course === course);
        row.dataset.matchesFilter = String(matches);
    });

    attendanceState.page = 1;
    renderAttendancePage();
}

function openAttendanceArchiveModal() {
    const modal = document.getElementById('attendanceArchiveModal');
    const dateLabel = document.getElementById('attendanceArchiveDateLabel');
    if (!modal) return;
    if (dateLabel) dateLabel.textContent = attendanceState.selectedDate === attendanceDateKey(new Date()) ? 'today' : attendanceDateLabel(attendanceState.selectedDate);
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
}

function closeAttendanceArchiveModal() {
    const modal = document.getElementById('attendanceArchiveModal');
    if (!modal) return;
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');
}

async function confirmAttendanceArchive() {
    const startYear = document.getElementById('attendanceArchiveStartYear').value;
    const endYear = document.getElementById('attendanceArchiveEndYear').value;
    if (Number(endYear) !== Number(startYear) + 1) {
        alert('Choose the following year in the To box, such as 2027 for 2026 - 2027.');
        return;
    }
    if (!shouldConfirmArchive()) return;
    try {
        await requestApi('archive-attendance-date', { method: 'POST', body: JSON.stringify({ date: attendanceState.selectedDate, schoolYear: `${startYear}-${endYear}` }) });
        closeAttendanceArchiveModal();
        await loadDashboardData();
    } catch (error) {
        alert(error.message);
    }
}

function resetAttendanceFilters() {
    document.getElementById('attendanceSearch').value = '';
    document.getElementById('attendanceSubjectFilter').value = '';
    document.getElementById('attendanceStatusFilter').value = '';
    document.getElementById('attendanceCourseFilter').value = '';
    getAttendanceRows().forEach(function (row) {
        row.dataset.attendanceDate = row.dataset.attendanceDate || attendanceDateKey(row.cells[2].textContent.trim());
        row.dataset.matchesFilter = 'true';
    });
    attendanceState.sortKey = '';
    attendanceState.sortDirection = 1;
    attendanceState.page = 1;
    renderAttendanceDateControls();
    renderAttendanceDateControls();
    applyAttendanceFilters();
}

function sortAttendance(sortKey) {
    if (attendanceState.sortKey === sortKey) {
        attendanceState.sortDirection *= -1;
    } else {
        attendanceState.sortKey = sortKey;
        attendanceState.sortDirection = 1;
    }

    const tableBody = document.getElementById('attendanceTableBody');
    const rows = getAttendanceRows().sort(function (firstRow, secondRow) {
        return getAttendanceValue(firstRow, sortKey).localeCompare(getAttendanceValue(secondRow, sortKey), undefined, { numeric: true }) * attendanceState.sortDirection;
    });
    rows.forEach(function (row) { tableBody.appendChild(row); });
    renderAttendancePage();
}

function sortAttendanceFromMenu() {
    const select = document.getElementById('attendanceSortSelect');
    if (select) sortAttendance(select.value);
}

function renderAttendancePage() {
    const rows = getAttendanceRows();
    const filteredRows = rows.filter(function (row) { return row.dataset.matchesFilter !== 'false'; });
    const totalPages = Math.max(1, Math.ceil(filteredRows.length / attendanceState.pageSize));
    attendanceState.page = Math.min(attendanceState.page, totalPages);
    const firstIndex = (attendanceState.page - 1) * attendanceState.pageSize;

    rows.forEach(function (row) { row.hidden = true; });
    filteredRows.slice(firstIndex, firstIndex + attendanceState.pageSize).forEach(function (row) { row.hidden = false; });

    const pagination = document.getElementById('attendancePagination');
    if (!pagination) {
        return;
    }
    pagination.innerHTML = `
        <span>Showing ${filteredRows.length ? firstIndex + 1 : 0}-${Math.min(firstIndex + attendanceState.pageSize, filteredRows.length)} of ${filteredRows.length} records</span>
        <button type="button" ${attendanceState.page === 1 ? 'disabled' : ''} onclick="changeAttendancePage(-1)">Previous</button>
        <strong>Page ${attendanceState.page} of ${totalPages}</strong>
        <button type="button" ${attendanceState.page === totalPages ? 'disabled' : ''} onclick="changeAttendancePage(1)">Next</button>
    `;
}

function changeAttendancePage(change) {
    attendanceState.page += change;
    renderAttendancePage();
}

function initializeAttendanceTools() {
    if (!document.getElementById('attendanceTable')) {
        return;
    }
    getAttendanceRows().forEach(function (row) { row.dataset.matchesFilter = 'true'; });
    const search = document.getElementById('attendanceSearch');
    if (search) {
        search.addEventListener('input', applyAttendanceFilters);
        search.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                applyAttendanceFilters();
            }
        });
    }
    document.querySelectorAll('.sort-button').forEach(function (button) {
        button.addEventListener('click', function () { sortAttendance(button.dataset.sortKey); });
    });
    renderAttendancePage();
}

initializeAttendanceTools();

const studentState = { sortKey: '', sortDirection: 1, page: 1, pageSize: 10 };

function getStudentRows() {
    const table = document.getElementById('studentTable');
    return table ? Array.from(table.querySelectorAll('tbody tr')) : [];
}

function filterStudents() {
    const search = document.getElementById('studentSearch').value.trim().toLowerCase();
    getStudentRows().forEach(function (row) {
        const rowText = row.textContent.toLowerCase();
        row.dataset.matchesFilter = String(row.dataset.studentStatus !== 'archived' && (!search || rowText.includes(search)));
    });
    studentState.page = 1;
    renderStudentPage();
}

function sortStudents(sortKey) {
    if (studentState.sortKey === sortKey) {
        studentState.sortDirection *= -1;
    } else {
        studentState.sortKey = sortKey;
        studentState.sortDirection = 1;
    }
    const columnMap = { id: 0, name: 1, course: 2, year: 3, schoolYear: 4, status: 5 };
    const body = document.querySelector('#studentTable tbody');
    getStudentRows().sort(function (firstRow, secondRow) {
        const first = firstRow.cells[columnMap[sortKey]].textContent.trim();
        const second = secondRow.cells[columnMap[sortKey]].textContent.trim();
        if (sortKey === 'name') {
            const surnameOrder = getSurname(first).localeCompare(getSurname(second), undefined, { sensitivity: 'base' });
            if (surnameOrder) return surnameOrder * studentState.sortDirection;
        }
        return first.localeCompare(second, undefined, { numeric: true }) * studentState.sortDirection;
    }).forEach(function (row) { body.appendChild(row); });
    filterStudents();
}

function renderStudentPage() {
    const rows = getStudentRows();
    const filteredRows = rows.filter(function (row) { return row.dataset.matchesFilter !== 'false'; });
    const totalPages = Math.max(1, Math.ceil(filteredRows.length / studentState.pageSize));
    studentState.page = Math.min(studentState.page, totalPages);
    const firstIndex = (studentState.page - 1) * studentState.pageSize;

    rows.forEach(function (row) { row.hidden = true; });
    filteredRows.slice(firstIndex, firstIndex + studentState.pageSize).forEach(function (row) { row.hidden = false; });

    const pagination = document.getElementById('studentPagination');
    if (!pagination) return;
    pagination.innerHTML = `
        <span>Showing ${filteredRows.length ? firstIndex + 1 : 0}-${Math.min(firstIndex + studentState.pageSize, filteredRows.length)} of ${filteredRows.length} students</span>
        <button type="button" ${studentState.page === 1 ? 'disabled' : ''} onclick="changeStudentPage(-1)">Previous</button>
        <strong>Page ${studentState.page} of ${totalPages}</strong>
        <button type="button" ${studentState.page === totalPages ? 'disabled' : ''} onclick="changeStudentPage(1)">Next</button>
    `;
}

function changeStudentPage(change) {
    studentState.page += change;
    renderStudentPage();
}

function openStudentProfile(button) {
    const row = button.closest('tr');
    const actionMenu = button.closest('details');
    if (actionMenu) actionMenu.removeAttribute('open');
    document.querySelectorAll('.row-menu[open], .view-toolbar details[open]').forEach(function (menu) {
        menu.removeAttribute('open');
    });
    const cells = row.cells;
    const faceImagePath = String(row.dataset.studentFaceImagePath || '').replace(/^\/+/, '');
    const hasFaceImage = faceImagePath !== '';
    document.getElementById('profileDetails').innerHTML = `
        <div class="student-profile-photo-wrap">
            ${hasFaceImage
                ? `<img class="student-profile-photo" src="/${faceImagePath}" alt="${escapeHtml(cells[1].textContent.trim())}'s student photo">`
                : `<div class="student-profile-photo student-profile-photo--placeholder">👤</div>`}
        </div>
        <dl class="profile-list">
            <dt>Student ID</dt><dd>${cells[0].textContent}</dd>
            <dt>Name</dt><dd>${cells[1].textContent}</dd>
            <dt>Course</dt><dd>${cells[2].textContent}</dd>
            <dt>Year</dt><dd>${cells[3].textContent}</dd>
            <dt>School Year</dt><dd>${cells[4].textContent}</dd>
            <dt>Status</dt><dd>${cells[5].textContent}</dd>
            <dt>Record</dt><dd>${row.dataset.studentStatus === 'archived' ? 'Archived' : 'Active'}</dd>
        </dl>
        <p class="profile-note">Attendance history and guardian details can be connected when the data source is added.</p>
    `;
    const profileModal = document.getElementById('profileModal');
    profileModal.hidden = false;
    profileModal.setAttribute('aria-hidden', 'false');
    profileModal.classList.add('is-open');
    profileModal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function closeProfileModal() {
    const profileModal = document.getElementById('profileModal');
    profileModal.classList.remove('is-open');
    profileModal.style.display = 'none';
    profileModal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
}

async function toggleStudentArchive(button) {
    const row = button.closest('tr');
    const archived = row.dataset.studentStatus === 'archived';
    try {
        await requestApi('archive-student', { method: 'POST', body: JSON.stringify({ studentId: row.cells[0].textContent.trim(), archived: archived ? 0 : 1 }) });
        await loadDashboardData();
    } catch (error) {
        alert(error.message);
    }
}

function openArchiveSchoolYearModal() {
    const modal = document.getElementById('archiveSchoolYearModal');
    if (!modal) return;
    const startYear = document.getElementById('archiveStartYear');
    const endYear = document.getElementById('archiveEndYear');
    if (startYear && endYear && !endYear.value) endYear.value = String(Number(startYear.value) + 1);
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
}

function initializeArchiveYearOptions() {
    const startYearSelect = document.getElementById('archiveStartYear');
    const endYearSelect = document.getElementById('archiveEndYear');
    if (!startYearSelect || !endYearSelect) return;

    const currentYear = new Date().getFullYear();
    startYearSelect.innerHTML = Array.from({ length: 13 }, function (_, index) {
        const year = currentYear - 2 + index;
        return `<option value="${year}">${year}</option>`;
    }).join('');
    endYearSelect.innerHTML = Array.from({ length: 13 }, function (_, index) {
        return `<option value="${currentYear - 1 + index}">${currentYear - 1 + index}</option>`;
    }).join('');
    startYearSelect.value = String(currentYear);
    endYearSelect.value = String(currentYear + 1);
}

initializeArchiveYearOptions();

const archiveStartYearSelect = document.getElementById('archiveStartYear');
if (archiveStartYearSelect) {
    archiveStartYearSelect.addEventListener('change', function () {
        const endYear = document.getElementById('archiveEndYear');
        if (endYear) endYear.value = String(Number(archiveStartYearSelect.value) + 1);
    });
}

function closeArchiveSchoolYearModal() {
    const modal = document.getElementById('archiveSchoolYearModal');
    if (!modal) return;
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');
}

async function confirmArchiveSchoolYear() {
    const startYear = document.getElementById('archiveStartYear').value;
    const endYear = document.getElementById('archiveEndYear').value.trim();
    if (!/^\d{4}$/.test(endYear) || Number(endYear) !== Number(startYear) + 1) {
        alert('Enter the following school year in the To box, such as 2027 for 2026 - 2027.');
        return;
    }
    const schoolYear = `${startYear}-${endYear}`;
    const course = document.getElementById('archiveCourse').value;
    if (!shouldConfirmArchive()) return;
    try {
        await requestApi('archive-year', { method: 'POST', body: JSON.stringify({ schoolYear: schoolYear, course: course }) });
        closeArchiveSchoolYearModal();
        await loadDashboardData();
    } catch (error) {
        alert(error.message);
    }
}

function shouldConfirmArchive() {
    const settings = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    return settings.confirmArchive === false || window.confirm('Archive these records? You can restore them later from Archives.');
}

function initializeStudentTools() {
    const search = document.getElementById('studentSearch');
    if (!search) {
        return;
    }
    search.addEventListener('input', filterStudents);
    filterStudents();
}

initializeStudentTools();

function renderArchivedStudents() {
    const body = document.getElementById('archiveTableBody');
    if (!body) return;
    const archivedStudents = (dashboardData.students || []).filter(function (student) { return Number(student.is_archived) === 1; });
    const groupedYears = {};
    archivedStudents.forEach(function (student) {
        const schoolYear = student.archived_school_year || 'Unassigned';
        if (!groupedYears[schoolYear]) groupedYears[schoolYear] = [];
        groupedYears[schoolYear].push(student);
    });
    const schoolYearFilter = document.getElementById('archiveSchoolYearFilter');
    if (schoolYearFilter) {
        const selectedYear = schoolYearFilter.value;
        const schoolYears = Object.keys(groupedYears).sort();
        schoolYearFilter.innerHTML = '<option value="">All school years</option>' + schoolYears.map(function (schoolYear) {
            return `<option value="${escapeHtml(schoolYear)}">${escapeHtml(schoolYear)}</option>`;
        }).join('');
        schoolYearFilter.value = schoolYears.includes(selectedYear) ? selectedYear : '';
    }
    body.innerHTML = Object.keys(groupedYears).sort().map(function (year) {
        const students = groupedYears[year];
        const courses = Array.from(new Set(students.map(function (student) { return student.course; }))).sort().join(', ');
        const names = students.map(function (student) { return student.full_name; }).join(' ');
        return `<tr data-archive-year="${escapeHtml(year)}" data-archive-search="${escapeHtml(year + ' ' + courses + ' ' + names)}">
            <td><button class="archive-year-link" type="button" onclick="openArchivedYear('${escapeHtml(year)}')">${escapeHtml(year)}</button></td><td>${students.length} students</td><td>${escapeHtml(courses)}</td>
            <td><details class="row-menu"><summary aria-label="Archived school year actions">•••</summary><div class="row-menu__content"><button class="menu-item archive-action restore-action" type="button" onclick="restoreArchivedYear(this)">Restore school year</button></div></details></td>
        </tr>`;
    }).join('');
    filterArchivedStudents();
}

function getArchivedYearData(year) {
    const students = (dashboardData.students || []).filter(function (student) {
        return Number(student.is_archived) === 1 && (student.archived_school_year || 'Unassigned') === year;
    });
    const studentIds = new Set(students.map(function (student) { return student.student_id; }));
    return {
        students: students,
        attendance: (dashboardData.attendance || []).filter(function (record) {
            return record.school_year === year || record.archived_school_year === year || studentIds.has(record.student_id);
        }),
        schedules: (dashboardData.schedules || []).filter(function (schedule) {
            return schedule.school_year === year || schedule.archived_school_year === year;
        })
    };
}

function openArchivedYear(year) {
    archivedYear = year;
    archivedCategory = 'students';
    document.getElementById('archiveView').hidden = true;
    document.getElementById('archiveDetailView').hidden = false;
    const regView = document.getElementById('studentRegistrationView');
    if (regView) regView.hidden = true;
    document.querySelectorAll('.nav-link').forEach(function (link) { link.classList.remove('active'); });
    document.querySelector('[data-view="archives"]').classList.add('active');
    document.getElementById('archiveDetailTitle').textContent = `Archived School Year ${year}`;
    renderArchivedCategory();
}

function closeArchivedYear() {
    archivedYear = '';
    document.getElementById('archiveDetailView').hidden = true;
    document.getElementById('archiveView').hidden = false;
}

function archivedTable(title, headers, rows) {
    const body = rows || `<tr><td colspan="${headers.length}">No records found for this school year.</td></tr>`;
    return `<section class="table-container archive-detail-panel"><h2>${title}</h2><table><thead><tr>${headers.map(function (header) { return `<th scope="col">${header}</th>`; }).join('')}</tr></thead><tbody>${body}</tbody></table></section>`;
}

function renderArchivedCategory() {
    const content = document.getElementById('archiveDetailContent');
    const data = getArchivedYearData(archivedYear);
    if (!content) return;
    const archivePrintButton = document.querySelector('.archive-report-print-button');
    if (archivePrintButton) archivePrintButton.hidden = archivedCategory !== 'report';
    document.querySelectorAll('.archive-category-tab').forEach(function (tab) { tab.classList.toggle('active', tab.dataset.archiveCategory === archivedCategory); });
    if (archivedCategory === 'students') {
        content.innerHTML = archivedTable('Students', ['ID', 'Student Name', 'Course', 'Year', 'Status'], data.students.map(function (student) {
            return `<tr><td>${escapeHtml(student.student_id)}</td><td>${escapeHtml(student.full_name)}</td><td>${escapeHtml(student.course)}</td><td>${escapeHtml(student.year)}</td><td>${statusBadge(student.status)}</td></tr>`;
        }).join(''));
    } else if (archivedCategory === 'attendance') {
        content.innerHTML = archivedTable('Attendance', ['Student ID', 'Student Name', 'Date', 'Subject', 'Time In', 'Time Out', 'Status'], data.attendance.map(function (record) {
            return `<tr><td>${escapeHtml(record.student_id)}</td><td>${escapeHtml(record.student_name)}</td><td>${escapeHtml(record.attendance_date)}</td><td>${escapeHtml(record.subject)}</td><td>${escapeHtml(record.time_in)}</td><td>${escapeHtml(record.time_out)}</td><td>${statusBadge(record.status)}</td></tr>`;
        }).join(''));
    } else if (archivedCategory === 'schedule') {
        content.innerHTML = archivedTable('Schedule', ['School Year', 'Subject', 'Instructor', 'Room', 'Day', 'Time'], data.schedules.map(function (schedule) {
            return `<tr><td>${escapeHtml(schedule.school_year || schedule.archived_school_year || archivedYear)}</td><td>${escapeHtml(schedule.subject)}</td><td>${escapeHtml(schedule.instructor)}</td><td>${escapeHtml(schedule.room)}</td><td>${escapeHtml(schedule.day)}</td><td>${escapeHtml(schedule.start_time)} - ${escapeHtml(schedule.end_time)}</td></tr>`;
        }).join(''));
    } else if (archivedCategory === 'report') {
        renderArchivedReport(content, data);
    } else {
        renderArchivedOverview(content, data);
    }
}

function printCurrentReport() {
    const isArchiveReport = !document.getElementById('archiveDetailView').hidden && archivedCategory === 'report';
    document.body.dataset.printView = isArchiveReport ? 'archive-report' : 'report';
    const printTitle = document.getElementById('printDocumentTitle');
    const printSubtitle = document.getElementById('printDocumentSubtitle');
    if (printTitle) printTitle.textContent = isArchiveReport ? `Archived Attendance Report: ${archivedYear}` : 'Attendance Report';
    if (printSubtitle) printSubtitle.textContent = `DRLCEFI | Generated ${new Date().toLocaleString()}`;
    window.addEventListener('afterprint', function clearPrintView() {
        delete document.body.dataset.printView;
        window.removeEventListener('afterprint', clearPrintView);
    });
    window.print();
}

function renderArchivedReport(content, data) {
    const recordsByStudent = {};
    data.attendance.forEach(function (record) {
        if (!recordsByStudent[record.student_id]) recordsByStudent[record.student_id] = { Present: 0, Late: 0, Absent: 0 };
        recordsByStudent[record.student_id][record.status] = (recordsByStudent[record.student_id][record.status] || 0) + 1;
    });
    const rows = data.students.map(function (student) {
        const counts = recordsByStudent[student.student_id] || { Present: 0, Late: 0, Absent: 0 };
        const total = counts.Present + counts.Late + counts.Absent;
        const percentage = total ? Math.round(((counts.Present + counts.Late) / total) * 100) : 0;
        const standing = percentage < 80 ? 'At Risk' : percentage < 90 ? 'Warning' : 'Good Standing';
        return `<tr><td>${escapeHtml(student.student_id)}</td><td>${escapeHtml(student.full_name)}</td><td>${counts.Present}</td><td>${counts.Late}</td><td>${counts.Absent}</td><td>${percentage}%</td><td>${statusBadge(standing)}</td></tr>`;
    }).join('');
    const warningCount = data.students.filter(function (student) {
        const counts = recordsByStudent[student.student_id] || { Present: 0, Late: 0, Absent: 0 };
        const total = counts.Present + counts.Late + counts.Absent;
        return total && ((counts.Present + counts.Late) / total) < 0.9;
    }).length;
    const riskCount = data.students.filter(function (student) {
        const counts = recordsByStudent[student.student_id] || { Present: 0, Late: 0, Absent: 0 };
        const total = counts.Present + counts.Late + counts.Absent;
        return total && ((counts.Present + counts.Late) / total) < 0.8;
    }).length;
    content.innerHTML = `<div class="summary archive-report-summary"><div class="card"><h2>Total Students</h2><p>${data.students.length}</p></div><div class="card"><h2>Students with Warning</h2><p>${warningCount}</p></div><div class="card"><h2>Students at Risk</h2><p>${riskCount}</p></div></div>${archivedTable('Attendance Report', ['Student ID', 'Name', 'Present', 'Late', 'Absent', 'Attendance %', 'Status'], rows)}`;
}

function renderArchivedOverview(content, data) {
    const timestamps = data.attendance.map(function (record) { return new Date(record.attendance_date).getTime(); }).filter(Number.isFinite);
    const latest = timestamps.length ? Math.max.apply(null, timestamps) : Date.now();
    const latestDate = new Date(latest);
    const periods = { Daily: 1, Weekly: 7, Monthly: 31 };
    const periodCards = Object.keys(periods).map(function (label) {
        const start = new Date(latestDate);
        start.setDate(start.getDate() - periods[label] + 1);
        const records = data.attendance.filter(function (record) {
            const timestamp = new Date(record.attendance_date).getTime();
            return Number.isFinite(timestamp) && timestamp >= start.getTime() && timestamp <= latest;
        });
        const present = records.filter(function (record) { return record.status === 'Present' || record.status === 'Late'; }).length;
        const rate = records.length ? Math.round((present / records.length) * 100) : 0;
        return `<div class="card"><h2>${label} Attendance</h2><p>${rate}%</p><small>${present} of ${records.length} records present or late</small></div>`;
    }).join('');
    const present = data.attendance.filter(function (record) { return record.status === 'Present'; }).length;
    const late = data.attendance.filter(function (record) { return record.status === 'Late'; }).length;
    const absent = data.attendance.filter(function (record) { return record.status === 'Absent'; }).length;
    const total = present + late + absent;
    const rate = total ? Math.round(((present + late) / total) * 100) : 0;
    content.innerHTML = `<div class="summary archive-overview-summary"><div class="card"><h2>Total Students</h2><p>${data.students.length}</p></div><div class="card"><h2>Present</h2><p>${present}</p></div><div class="card"><h2>Late</h2><p>${late}</p></div><div class="card"><h2>Absent</h2><p>${absent}</p></div><div class="card"><h2>Attendance Records</h2><p>${total}</p></div><div class="card"><h2>Schedules</h2><p>${data.schedules.length}</p></div><div class="card"><h2>Attendance Rate</h2><p>${rate}%</p></div>${periodCards}</div><p class="overview-updated">Overview calculated from all archived records for ${escapeHtml(archivedYear)}.</p>`;
}

document.querySelectorAll('.archive-category-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
        archivedCategory = tab.dataset.archiveCategory;
        renderArchivedCategory();
    });
});

async function restoreArchivedYear(button) {
    const schoolYear = button.closest('tr').dataset.archiveYear;
    try {
        await requestApi('restore-year', { method: 'POST', body: JSON.stringify({ schoolYear: schoolYear }) });
        await loadDashboardData();
    } catch (error) {
        alert(error.message);
    }
}

async function restoreSelectedSchoolYear() {
    const schoolYear = document.getElementById('archiveSchoolYearFilter')?.value || '';
    if (!schoolYear) {
        alert('Select a school year first.');
        return;
    }
    try {
        await requestApi('restore-year', { method: 'POST', body: JSON.stringify({ schoolYear: schoolYear }) });
        await loadDashboardData();
    } catch (error) {
        alert(error.message);
    }
}

function filterArchivedStudents() {
    const search = (document.getElementById('archiveSearch')?.value || '').trim().toLowerCase();
    const course = document.getElementById('archiveCourseFilter')?.value || '';
    const year = document.getElementById('archiveSchoolYearFilter')?.value || '';
    const rows = Array.from(document.querySelectorAll('#archiveTableBody tr'));
    rows.forEach(function (row) {
        const matchesSearch = !search || row.dataset.archiveSearch.toLowerCase().includes(search);
        const matchesCourse = !course || row.cells[2].textContent.split(', ').includes(course);
        const matchesYear = !year || row.dataset.archiveYear === year;
        row.hidden = !(matchesSearch && matchesCourse && matchesYear);
    });
    const emptyState = document.getElementById('archiveEmptyState');
    if (emptyState) emptyState.hidden = rows.some(function (row) { return !row.hidden; });
}

['archiveSearch', 'archiveCourseFilter', 'archiveSchoolYearFilter'].forEach(function (id) {
    const control = document.getElementById(id);
    if (control) control.addEventListener(control.tagName === 'SELECT' ? 'change' : 'input', filterArchivedStudents);
});

function searchHistory() {
    const input = document.getElementById('historySearchInput');
    const query = input ? input.value.trim().toLowerCase() : '';
    document.querySelectorAll('#timeline .history-card').forEach(function (card) {
        card.hidden = Boolean(query) && !card.textContent.toLowerCase().includes(query);
    });
    document.querySelectorAll('#attendanceHistoryList .attendance-history-row').forEach(function (row) {
        row.hidden = Boolean(query) && !row.textContent.toLowerCase().includes(query);
    });
}

function initializeExpandableSearches() {
    document.querySelectorAll('.toolbar-search input[type="search"]').forEach(function (input) {
        input.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            if (input.id === 'studentSearch') filterStudents();
            if (input.id === 'historySearchInput') searchHistory();
        });
    });
}

initializeExpandableSearches();

function initializeExclusiveToolbarMenus() {
    document.querySelectorAll('.view-toolbar details').forEach(function (menu) {
        menu.addEventListener('toggle', function () {
            if (!menu.open) return;
            const toolbar = menu.closest('.view-toolbar');
            if (!toolbar) return;
            toolbar.querySelectorAll('details[open]').forEach(function (otherMenu) {
                if (otherMenu !== menu) otherMenu.removeAttribute('open');
            });
        });
    });
}

initializeExclusiveToolbarMenus();

function sortStudentsFromMenu() {
    const select = document.getElementById('studentSortSelect');
    if (select) sortStudents(select.value);
}

function setStudentStatus(value) {
    const status = document.getElementById('studentStatusFilter');
    if (status) {
        status.value = value;
        filterStudents();
    }
}

function refreshDashboard() {
    loadDashboardData().catch(function (error) { alert(error.message); });
}

function applyRolePermissions(role) {
    const adminOnly = document.querySelectorAll('[data-admin-only="true"], .archive-action, .edit-btn, .delete-btn');
    adminOnly.forEach(function (element) {
        element.hidden = role !== 'Administrator';
    });
}

function renderAuditLog() {
    const log = document.getElementById('auditLog');
    if (!log) return;
    const entries = dashboardData.audit || [];
    log.innerHTML = entries.length ? entries.map(function (entry) {
        return `<p><strong>${entry.created_at}</strong> ${escapeHtml(entry.actor)}: ${escapeHtml(entry.action)}</p>`;
    }).join('') : '<p>No audit activity yet.</p>';
}

async function saveNotificationSettings() {
    const settings = {
        absent: document.getElementById('notifyAbsent').checked,
        late: document.getElementById('notifyLate').checked,
        checkIn: document.getElementById('notifyCheckIn').checked
    };
    try {
        await requestApi('settings', { method: 'POST', body: JSON.stringify(settings) });
        await loadDashboardData();
    } catch (error) {
        alert(error.message);
    }
}

function loadNotificationSettings() {
    const settings = dashboardData.notificationSettings;
    if (!settings) return;
    if (document.getElementById('notifyAbsent')) document.getElementById('notifyAbsent').checked = settings.absent !== false;
    if (document.getElementById('notifyLate')) document.getElementById('notifyLate').checked = settings.late !== false;
    if (document.getElementById('notifyCheckIn')) document.getElementById('notifyCheckIn').checked = settings.checkIn !== false;
}

function loadNotificationSettingsFromData() { loadNotificationSettings(); }

document.getElementById('adminProfilePhoto')?.addEventListener('change', async function () {
    const file = this.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
        this.value = '';
        document.getElementById('profileMessage').textContent = 'The profile photo must be 2 MB or smaller.';
        return;
    }
    try {
        renderProfilePreview(await readFacePhoto(file));
        document.getElementById('profileMessage').textContent = '';
    } catch (error) {
        document.getElementById('profileMessage').textContent = error.message;
    }
});

async function saveAdminProfile() {
    const name = document.getElementById('profileName').value.trim();
    const file = document.getElementById('adminProfilePhoto').files[0];
    if (!name) {
        document.getElementById('profileMessage').textContent = 'Enter your full name.';
        return;
    }
    try {
        const profileImage = file ? await readFacePhoto(file) : currentUser.profileImage || '';
        const data = await requestApi('profile', { method: 'POST', body: JSON.stringify({ name, profileImage }) });
        currentUser = data.user;
        updateAdminIdentity();
        document.getElementById('profileMessage').textContent = 'Profile saved successfully.';
        document.querySelector('.welcome h1, #dashboard-title').textContent = `Welcome, ${name}!`;
        setTimeout(closeAdminProfile, 500);
    } catch (error) {
        document.getElementById('profileMessage').textContent = error.message;
    }
}

async function saveAdminSettings() {
    const currentPassword = document.getElementById('settingsCurrentPassword').value;
    const newPassword = document.getElementById('settingsNewPassword').value;
    const confirmPassword = document.getElementById('settingsConfirmPassword').value;
    if (!currentPassword || newPassword.length < 6 || newPassword !== confirmPassword) {
        document.getElementById('settingsMessage').textContent = 'Enter the current password and matching new password (6+ characters).';
        return;
    }
    try {
        await requestApi('password', { method: 'POST', body: JSON.stringify({ currentPassword, newPassword }) });
        document.getElementById('settingsMessage').textContent = 'Settings saved successfully.';
        setTimeout(closeSettings, 500);
    } catch (error) {
        document.getElementById('settingsMessage').textContent = error.message;
    }
}

function applySystemSettings(settings) {
    const logo = document.querySelector('.logo');
    if (logo) {
        const logoLabel = logo.querySelector('span');
        if (logoLabel) {
            logoLabel.textContent = settings.schoolName || 'DRLCEFI';
        } else {
            logo.textContent = settings.schoolName || 'DRLCEFI';
        }
        logo.style.backgroundImage = '';
        logo.classList.remove('has-school-logo');
    }
}

function resetSessionTimer() {
    const settings = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    if (sessionTimer) clearTimeout(sessionTimer);
    if (!settings.sessionTimeout || !currentUser) return;
    sessionTimer = setTimeout(function () {
        requestApi('logout', { method: 'POST' }).finally(function () { currentUser = null; showAuth(); });
    }, settings.sessionTimeout * 60 * 1000);
}

['click', 'keydown', 'mousemove'].forEach(function (eventName) {
    document.addEventListener(eventName, function () {
        if (!document.getElementById('appShell').hidden) resetSessionTimer();
    });
});

function applySavedDashboardView() {
    const settings = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    if (!settings.rememberView || archivedYear) return;
    const view = settings.lastView || settings.defaultView;
    if (!view) return;
    const link = document.querySelector(`[data-view="${view}"]`);
    if (link && !link.classList.contains('active')) link.click();
}

function updateOverviewStats() {
    const rows = Array.from(document.querySelectorAll('#attendanceTableBody tr'));
    const present = rows.filter(function (row) { return row.cells[6].textContent.trim() === 'Present'; }).length;
    const late = rows.filter(function (row) { return row.cells[6].textContent.trim() === 'Late'; }).length;
    const absent = rows.filter(function (row) { return row.cells[6].textContent.trim() === 'Absent'; }).length;
    const total = present + late + absent;
    const cards = document.querySelectorAll('#overviewView .summary-card p');
    if (cards.length >= 4) {
        cards[0].textContent = document.querySelectorAll('#studentTable tbody tr').length;
        cards[1].textContent = present;
        cards[2].textContent = absent;
        cards[3].textContent = total ? `${Math.round(((present + late) / total) * 100)}%` : '0%';
    }
}

function initializeGlobalSearch() {
    const input = document.getElementById('globalSearch');
    const results = document.getElementById('globalSearchResults');
    if (!input || !results) return;
    input.addEventListener('input', function () {
        const query = input.value.trim().toLowerCase();
        if (!query) {
            results.innerHTML = '';
            return;
        }
        const matches = Array.from(document.querySelectorAll('.view-section tbody tr, .history-card')).filter(function (item) {
            return item.textContent.toLowerCase().includes(query);
        }).slice(0, 8);
        results.innerHTML = matches.length ? matches.map(function (item) {
            return `<button type="button">${item.textContent.trim().slice(0, 70)}</button>`;
        }).join('') : '<span>No matches</span>';
    });
}

let registrationCaptures = {};
let registrationPoseTimer = null;
let registrationCurrentPose = 'none';
let registrationAutoCaptureEnabled = true;
const REGISTRATION_ANGLES = ['front', 'down', 'right', 'left', 'up'];

let registrationStream = null;
function startRegistrationCamera() {
    const video = document.getElementById('registrationVideo');
    if (!video) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert('Browser camera is not supported in this browser.');
        return;
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 720 }, height: { ideal: 960 } } })
        .then(function (stream) {
            registrationStream = stream;
            video.srcObject = stream;
            video.play();
            const statusEl = document.getElementById('registrationPoseStatus');
            if (statusEl) statusEl.textContent = 'Camera ready — capture each angle manually';
        })
        .catch(function (error) {
            alert('Unable to access the camera: ' + (error.message || error));
        });
}

function stopRegistrationCamera() {
    const video = document.getElementById('registrationVideo');
    if (registrationStream) {
        registrationStream.getTracks().forEach(function (track) { track.stop(); });
        registrationStream = null;
    }
    if (video) video.srcObject = null;
    registrationCurrentPose = 'none';
    const statusEl = document.getElementById('registrationPoseStatus');
    if (statusEl) statusEl.textContent = 'Pose: none';
}

function pollRegistrationPose() {
    // Browser camera has no pose detection; just keep status updated.
    const statusEl = document.getElementById('registrationPoseStatus');
    if (statusEl) statusEl.textContent = 'Camera ready — capture each angle manually';
}

function captureRegistrationFrame(angle) {
    const video = document.getElementById('registrationVideo');
    const canvas = document.getElementById('registrationCanvas');
    if (!video || !canvas) return;
    if (!video.videoWidth || !video.videoHeight) {
        // Retry shortly after the frame loads.
        setTimeout(function () { captureRegistrationFrame(angle); }, 200);
        return;
    }
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    try {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    } catch (e) {
        alert('Unable to capture frame: ' + (e.message || e));
        return;
    }
    const dataUrl = canvas.toDataURL('image/jpeg', 0.9);
    registrationCaptures[angle] = dataUrl;

    const container = document.getElementById('registrationCaptures');
    if (container) {
        let thumb = container.querySelector('[data-angle="' + angle + '"]');
        if (!thumb) {
            thumb = document.createElement('div');
            thumb.className = 'registration-capture-item';
            thumb.dataset.angle = angle;
            container.appendChild(thumb);
        }
        thumb.innerHTML = '<strong>' + angle + '</strong><img src="' + dataUrl + '" alt="' + angle + '">';
    }
}

function captureRegistrationAngle(angle) {
    // Manual capture fallback.
    captureRegistrationFrame(angle);
}

async function submitStudentRegistration() {
    const studentId = document.getElementById('regStudentId').value.trim();
    const firstName = document.getElementById('regFirstName').value.trim();
    const middleName = document.getElementById('regMiddleName').value.trim();
    const lastName = document.getElementById('regLastName').value.trim();
    const fullName = [firstName, middleName, lastName].filter(Boolean).join(' ');
    const course = document.getElementById('regCourse').value.trim();
    const schoolYearStart = document.getElementById('regSchoolYearStart').value.trim();
    const schoolYearEnd = document.getElementById('regSchoolYearEnd').value.trim();
    const schoolYear = schoolYearStart + '-' + schoolYearEnd;
    const parentPhone = document.getElementById('regParentPhone').value.trim();
    const year = document.getElementById('regYear').value.trim();
    const status = document.getElementById('regStatus').value.trim();

    if (!studentId || !firstName || !lastName || !course || !schoolYearStart || !schoolYearEnd || !parentPhone || !year || !status) {
        alert('Please complete all required fields.');
        return;
    }
    const requiredAngles = ['front', 'down', 'right', 'left', 'up'];
    if (!registrationCaptures.front) {
        alert('Please capture at least the Front angle before registering.');
        return;
    }
    const facePhotos = requiredAngles
        .map(function (a) { return registrationCaptures[a]; })
        .filter(Boolean);

    const loadingEl = document.getElementById('registrationLoading');
    if (loadingEl) loadingEl.hidden = false;
    try {
        const payload = { studentId, fullName, course, schoolYear, parentPhone, year, status, facePhotos: facePhotos };
        await requestApi('student', { method: 'POST', body: JSON.stringify(payload) });
        alert('Student registered successfully.');
        registrationCaptures = {};
        const container = document.getElementById('registrationCaptures');
        if (container) container.innerHTML = '';
        document.getElementById('studentRegistrationForm').reset();
    } catch (error) {
        alert(error.message || 'Registration failed.');
    } finally {
        if (loadingEl) loadingEl.hidden = true;
    }
}

let detectedCameras = [];
let selectedCameraId = null;
let operationEscapeHandler = null;
let operationFullscreenHandler = null;
let cameraResizeHandler = null;
let cameraStreamWidth = 0;
let cameraStreamHeight = 0;
let cameraStreamStarting = false;
let operationFacePollTimer = null;

function showCameraInitOverlay(message) {
    const overlay = document.getElementById('cameraInitOverlay');
    const text = document.getElementById('cameraInitOverlayText');
    if (text && message) text.textContent = message;
    if (overlay) overlay.hidden = false;
}

function hideCameraInitOverlay() {
    const overlay = document.getElementById('cameraInitOverlay');
    if (overlay) overlay.hidden = true;
}

async function startCameraStream(img, placeholder, feedContainer, force) {
    if (cameraStreamStarting) return;
    const container = feedContainer || document.getElementById('cameraFeed');
    const image = img || document.getElementById('cameraFeedImg');
    const place = placeholder || document.querySelector('.camera-feed__placeholder');

    let targetWidth = cameraStreamWidth || 720;
    let targetHeight = cameraStreamHeight || 1280;
    if (container) {
        const rect = container.getBoundingClientRect();
        const width = Math.round(container.clientWidth || rect.width || 0);
        const height = Math.round(container.clientHeight || rect.height || 0);
        if (width > 0 && height > 0) {
            targetWidth = width;
            targetHeight = height;
        }
    }

    // Avoid restarting the stream for sub-pixel / tiny changes.
    if (!force && cameraStreamWidth > 0 && cameraStreamHeight > 0 &&
        Math.abs(targetWidth - cameraStreamWidth) < 4 && Math.abs(targetHeight - cameraStreamHeight) < 4) {
        return;
    }

    cameraStreamStarting = true;
    showCameraInitOverlay('Initializing camera feed (' + targetWidth + '×' + targetHeight + ')…');
    try {
        await requestApi('camera-stream-start', {
            method: 'POST',
            body: JSON.stringify({ width: targetWidth, height: targetHeight })
        });
        cameraStreamWidth = targetWidth;
        cameraStreamHeight = targetHeight;
        if (image) {
            image.style.display = 'block';
            var _retryCount = 0;
            var _loadFeed = function () {
                image.src = '/camera-feed';
            };
            image.onerror = function () {
                if (_retryCount < 10) {
                    _retryCount++;
                    setTimeout(_loadFeed, 1000);
                }
            };
            _loadFeed();
        }
        if (place) place.style.display = 'none';
        showCameraInitOverlay('Camera ready. Loading stream…');
        await new Promise(function (resolve) { setTimeout(resolve, 400); });
    } catch (error) {
        if (place) {
            place.style.display = 'flex';
            place.textContent = 'Unable to start camera stream. Run scripts/camera_stream.py manually.';
        }
        showCameraInitOverlay('Camera initialization failed.');
        await new Promise(function (resolve) { setTimeout(resolve, 1200); });
    } finally {
        cameraStreamStarting = false;
        hideCameraInitOverlay();
    }
}

async function detectCameras() {
    const status = document.getElementById('cameraStatus');
    const list = document.getElementById('cameraList');
    if (status) status.textContent = 'Detecting cameras...';
    if (list) list.innerHTML = '';
    try {
        const data = await requestApi('camera-list', { method: 'GET' });
        detectedCameras = Array.isArray(data.cameras) ? data.cameras : [];
        if (!detectedCameras.length) {
            if (status) status.textContent = 'No cameras detected.';
            return;
        }
        if (status) status.textContent = detectedCameras.length + ' camera(s) found.';
        if (list) {
            list.innerHTML = detectedCameras.map(function (camera) {
                const checked = selectedCameraId === camera.id ? 'checked' : '';
                return '<label class="camera-option"><input type="radio" name="cameraOption" value="' + escapeHtml(camera.id) + '" ' + checked + ' onchange="selectedCameraId = this.value"> ' + escapeHtml(camera.name) + '</label>';
            }).join('');
        }
    } catch (error) {
        if (status) status.textContent = 'Camera detection failed.';
        if (list) list.innerHTML = '<p class="empty-state">' + escapeHtml(error.message || 'Unable to detect cameras.') + '</p>';
    }
}

async function saveSelectedCamera() {
    const status = document.getElementById('cameraStatus');
    const selected = detectedCameras.find(function (camera) { return camera.id === selectedCameraId; });
    if (!selected) {
        if (status) status.textContent = 'Select a camera first.';
        return;
    }
    try {
        const data = await requestApi('camera-save', {
            method: 'POST',
            body: JSON.stringify({
                id: selected.id,
                name: selected.name,
                modelId: selected.modelId || null,
                uniqueId: selected.uniqueId || null
            })
        });
        if (status) status.textContent = 'Camera saved.';
        await loadCameraConfig();
    } catch (error) {
        if (status) status.textContent = 'Unable to save camera.';
    }
}

async function loadCameraConfig() {
    const summary = document.getElementById('cameraConfigSummary');
    try {
        const data = await requestApi('camera-config', { method: 'GET' });
        if (data.config) {
            if (summary) summary.textContent = 'Saved camera: ' + (data.config.name || data.config.id || 'Unknown');
            selectedCameraId = data.config.id || selectedCameraId;
        } else {
            if (summary) summary.textContent = 'No camera saved yet.';
        }
    } catch (error) {
        if (summary) summary.textContent = 'Unable to load camera config.';
    }
}

renderAuditLog();
initializeGlobalSearch();
updateOverviewStats();

['scheduleDayFilter', 'scheduleInstructorFilter', 'scheduleSubjectFilter', 'scheduleRoomFilter'].forEach(function (id) {
    const control = document.getElementById(id);
    if (control) {
        control.addEventListener(control.tagName === 'SELECT' ? 'change' : 'input', applyScheduleFilters);
    }
});

function applyScheduleFilters() {
    const day = document.getElementById('scheduleDayFilter').value.toLowerCase();
    const instructor = document.getElementById('scheduleInstructorFilter').value.trim().toLowerCase();
    const subject = document.getElementById('scheduleSubjectFilter').value.trim().toLowerCase();
    const room = document.getElementById('scheduleRoomFilter').value.trim().toLowerCase();
    document.querySelectorAll('#scheduleTableBody tr').forEach(function (row) {
        row.hidden = (day && !row.cells[4].textContent.toLowerCase().includes(day))
            || (instructor && !row.cells[2].textContent.toLowerCase().includes(instructor))
            || (subject && !row.cells[1].textContent.toLowerCase().includes(subject))
            || (room && !row.cells[3].textContent.toLowerCase().includes(room));
    });
}

function resetScheduleFilters() {
    document.getElementById('scheduleDayFilter').value = '';
    document.getElementById('scheduleInstructorFilter').value = '';
    document.getElementById('scheduleSubjectFilter').value = '';
    document.getElementById('scheduleRoomFilter').value = '';
    applyScheduleFilters();
}

function timeToMinutes(value) {
    const trimmed = String(value || '').trim();
    const match = trimmed.match(/^(\d{1,2}):(\d{2})(?:\s*(AM|PM))?$/i);
    if (!match) {
        return null;
    }
    let hours = Number(match[1]);
    const minutes = Number(match[2]);
    const meridiem = (match[3] || '').toUpperCase();
    if (meridiem === 'PM' && hours !== 12) hours += 12;
    if (meridiem === 'AM' && hours === 12) hours = 0;
    return hours * 60 + minutes;
}

function hasScheduleConflict(day, room, startTime, endTime, ignoredRow) {
    const start = timeToMinutes(startTime);
    const end = timeToMinutes(endTime);
    return Array.from(document.querySelectorAll('#scheduleTableBody tr')).some(function (row) {
        if (row === ignoredRow || row.hidden) {
            return false;
        }

        const rowRoom = row.cells[3].textContent.trim().toLowerCase();
        const rowDays = String(row.cells[4].textContent).split(',').map(function (item) { return item.trim(); }).filter(Boolean);
        if (rowRoom !== room.toLowerCase() || !rowDays.includes(day)) {
            return false;
        }

        const existingTimes = row.cells[5].textContent.split(' - ');
        const existingStart = timeToMinutes(existingTimes[0]);
        const existingEnd = timeToMinutes(existingTimes[1]);
        return start !== null && end !== null && existingStart !== null && existingEnd !== null && start < existingEnd && end > existingStart;
    });
}

function generateReport() {
    const from = document.getElementById('reportFromDate').value;
    const to = document.getElementById('reportToDate').value;
    const day = document.getElementById('reportDayFilter').value;
    const course = document.getElementById('reportCourseFilter').value;
    const records = dashboardData.attendance.filter(function (record) {
        const date = new Date(record.attendance_date);
        const dateKey = attendanceDateKey(date);
        return (!from || dateKey >= from) && (!to || dateKey <= to) && (day === '' || String(date.getDay()) === day) && (!course || record.course === course);
    });
    const students = dashboardData.students.filter(function (student) { return !course || student.course === course; });
    const reportBody = document.querySelector('#reportTable tbody');
    if (reportBody) {
        reportBody.innerHTML = students.map(function (student) {
            const studentRecords = records.filter(function (record) { return record.student_id === student.student_id; });
            const present = studentRecords.filter(function (record) { return record.status === 'Present'; }).length;
            const late = studentRecords.filter(function (record) { return record.status === 'Late'; }).length;
            const absent = studentRecords.filter(function (record) { return record.status === 'Absent'; }).length;
            const total = present + late + absent;
            const rate = total ? Math.round(((present + late) / total) * 100) : 0;
            const status = absent > present + late ? 'At Risk' : late > present ? 'Warning' : 'Good Standing';
            return `<tr><td>${escapeHtml(student.student_id)}</td><td>${escapeHtml(student.full_name)}</td><td>${present}</td><td>${late}</td><td>${absent}</td><td>${rate}%</td><td class="${statusClass(status)}">${status}</td></tr>`;
        }).join('');
    }
    const message = document.getElementById('reportRangeMessage');
    if (message) {
        const dayLabel = day === '' ? '' : ` on ${document.getElementById('reportDayFilter').selectedOptions[0].textContent}`;
        message.textContent = `Report generated${from ? ` from ${from}` : ''}${to ? ` to ${to}` : ''}${dayLabel}${course ? ` for ${course}` : ''}.`;
    }
}

function setReportToday() {
    const today = attendanceDateKey(new Date());
    document.getElementById('reportFromDate').value = today;
    document.getElementById('reportToDate').value = today;
    document.getElementById('reportDayFilter').value = String(new Date().getDay());
    generateReport();
}

function downloadReportFile() {
    const pdfLibrary = window.jspdf;
    const table = document.getElementById('reportTable');
    if (!pdfLibrary || !table) {
        alert('The PDF download library is not available. Check your internet connection and try again.');
        return;
    }
    const pdf = new pdfLibrary.jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const margin = 14;
    const columns = Array.from(table.querySelectorAll('thead th')).map(function (cell) { return cell.textContent.trim(); });
    const rows = Array.from(table.querySelectorAll('tbody tr')).map(function (row) {
        return Array.from(row.cells).map(function (cell) { return cell.textContent.trim(); });
    });
    const columnWidths = [30, 64, 25, 25, 25, 31, 56];
    const rowHeight = 9;
    const drawHeader = function () {
        pdf.setFillColor(128, 0, 0);
        pdf.rect(0, 0, pageWidth, 7, 'F');
        pdf.setTextColor(128, 0, 0);
        pdf.setFont('helvetica', 'bold');
        pdf.setFontSize(11);
        pdf.text('DRLCEFI', pageWidth / 2, 18, { align: 'center' });
        pdf.setFontSize(21);
        pdf.text('Attendance Report', pageWidth / 2, 29, { align: 'center' });
        pdf.setTextColor(102, 89, 84);
        pdf.setFont('helvetica', 'normal');
        pdf.setFontSize(9);
        pdf.text(`Generated ${new Date().toLocaleString()}`, pageWidth / 2, 36, { align: 'center' });
        const message = document.getElementById('reportRangeMessage')?.textContent || '';
        pdf.text(message, pageWidth / 2, 42, { align: 'center' });
    };
    const drawTableHeader = function (y) {
        pdf.setFillColor(128, 0, 0);
        pdf.rect(margin, y, pageWidth - margin * 2, rowHeight, 'F');
        pdf.setTextColor(255, 255, 255);
        pdf.setFont('helvetica', 'bold');
        pdf.setFontSize(8);
        let x = margin;
        columns.forEach(function (column, index) { pdf.text(column, x + 2, y + 6); x += columnWidths[index]; });
        return y + rowHeight;
    };
    drawHeader();
    let y = drawTableHeader(50);
    rows.forEach(function (row, rowIndex) {
        if (y + rowHeight > pageHeight - 12) {
            pdf.addPage();
            drawHeader();
            y = drawTableHeader(50);
        }
        pdf.setFillColor(rowIndex % 2 ? 251 : 255, rowIndex % 2 ? 248 : 255, rowIndex % 2 ? 246 : 255);
        pdf.rect(margin, y, pageWidth - margin * 2, rowHeight, 'F');
        pdf.setDrawColor(228, 216, 210);
        pdf.rect(margin, y, pageWidth - margin * 2, rowHeight);
        pdf.setFont('helvetica', 'normal');
        pdf.setFontSize(8);
        let x = margin;
        row.forEach(function (value, index) {
            if (index === row.length - 1) {
                const color = value === 'Good Standing' ? [33, 107, 44] : value === 'Warning' ? [138, 87, 0] : [128, 0, 0];
                pdf.setTextColor(color[0], color[1], color[2]);
            } else pdf.setTextColor(47, 34, 34);
            pdf.text(pdf.splitTextToSize(value, columnWidths[index] - 4)[0], x + 2, y + 6);
            x += columnWidths[index];
        });
        y += rowHeight;
    });
    pdf.save(`attendance-report-${attendanceDateKey(new Date())}.pdf`);
}

function closeModal() {
    const modal = document.getElementById('modal');
    if (modal) {
        modal.style.display = 'none';
    }
    clearForm();
}

function closeStudentModal() {
    const modal = document.getElementById('studentModal');
    if (modal) {
        modal.style.display = 'none';
        modal.setAttribute('aria-hidden', 'true');
    }
    clearStudentForm();
}

function openModal() {
    const modal = document.getElementById('modal');
    editingRow = null;
    document.getElementById('modalTitle').textContent = 'Add Schedule';
    document.getElementById('saveScheduleBtn').textContent = 'Save Schedule';
    document.getElementById('scheduleSchoolYear').value = `${new Date().getFullYear()}-${new Date().getFullYear() + 1}`;
    if (modal) modal.style.display = 'flex';
}

function getSelectedScheduleDays() {
    const dayContainer = document.getElementById('day');
    if (!dayContainer) return [];

    if (dayContainer.tagName === 'SELECT') {
        const selectedValue = String(dayContainer.value || '').trim();
        return selectedValue ? [selectedValue] : [];
    }

    return Array.from(dayContainer.querySelectorAll('input[type="checkbox"]:checked')).map(function (checkbox) {
        return checkbox.value.trim();
    }).filter(Boolean);
}

function setSelectedScheduleDays(days) {
    const dayContainer = document.getElementById('day');
    if (!dayContainer) return;

    const selectedDays = Array.isArray(days) ? days : String(days || '').split(',').map(function (day) {
        return day.trim();
    }).filter(Boolean);

    if (dayContainer.tagName === 'SELECT') {
        dayContainer.value = selectedDays[0] || '';
        return;
    }

    const checkboxes = Array.from(dayContainer.querySelectorAll('input[type="checkbox"]'));
    checkboxes.forEach(function (checkbox) {
        checkbox.checked = false;
    });

    selectedDays.forEach(function (day) {
        const checkbox = checkboxes.find(function (item) {
            return item.value.toLowerCase() === String(day).toLowerCase();
        });
        if (checkbox) checkbox.checked = true;
    });
}

function clearForm() {
    document.getElementById('subject').value = '';
    document.getElementById('teacher').value = '';
    document.getElementById('room').value = '';
    setSelectedScheduleDays([]);
    document.getElementById('startTime').value = '';
    document.getElementById('endTime').value = '';
    document.getElementById('scheduleSchoolYear').value = '';
}

let editingStudentId = null;

function clearStudentForm() {
    editingStudentId = null;
    const modalTitle = document.querySelector('#studentModal h2');
    if (modalTitle) modalTitle.textContent = 'Add Student';
    const saveButton = document.querySelector('#studentModal .save-btn');
    if (saveButton) saveButton.textContent = 'Save Student';
    document.getElementById('studentId').value = '';
    document.getElementById('studentFirstName').value = '';
    document.getElementById('studentMiddleName').value = '';
    document.getElementById('studentLastName').value = '';
    document.getElementById('course').value = '';
    document.getElementById('studentSchoolYearStart').value = String(new Date().getFullYear());
    document.getElementById('studentSchoolYearEnd').value = String(new Date().getFullYear() + 1);
    document.getElementById('year').value = '';
    document.getElementById('status').value = '';
    document.getElementById('facePhoto').value = '';
    document.getElementById('parentPhone').value = '';
}

function readFacePhoto(file) {
    return new Promise(function (resolve, reject) {
        const reader = new FileReader();
        reader.addEventListener('load', function () { resolve(reader.result); });
        reader.addEventListener('error', function () { reject(new Error('Unable to read the face photo.')); });
        reader.readAsDataURL(file);
    });
}

function formatParentPhone(value) {
    const digits = value.replace(/\D/g, '');
    let localNumber = digits;
    if (digits.startsWith('63')) {
        localNumber = digits.slice(2);
    } else if (digits.startsWith('0')) {
        localNumber = digits.slice(1);
    }
    if (!localNumber.startsWith('9')) return value.replace(/[^0-9+\s().-]/g, '');
    localNumber = localNumber.slice(0, 10);
    const groups = [localNumber.slice(0, 3), localNumber.slice(3, 6), localNumber.slice(6, 10)].filter(Boolean);
    return `+63 ${groups.join(' ')}`;
}

function initializeParentPhoneFormatter() {
    const input = document.getElementById('parentPhone');
    if (!input) return;
    input.addEventListener('input', function () {
        input.value = formatParentPhone(input.value);
    });
}

initializeParentPhoneFormatter();

function openStudentModal(row) {
    const modal = document.getElementById('studentModal');
    if (!modal) return;

    const modalTitle = document.querySelector('#studentModal h2');
    const saveButton = document.querySelector('#studentModal .save-btn');
    const fields = {
        studentId: document.getElementById('studentId'),
        firstName: document.getElementById('studentFirstName'),
        middleName: document.getElementById('studentMiddleName'),
        lastName: document.getElementById('studentLastName'),
        course: document.getElementById('course'),
        schoolYearStart: document.getElementById('studentSchoolYearStart'),
        schoolYearEnd: document.getElementById('studentSchoolYearEnd'),
        year: document.getElementById('year'),
        status: document.getElementById('status'),
        parentPhone: document.getElementById('parentPhone'),
        facePhoto: document.getElementById('facePhoto')
    };

    editingStudentId = null;
    if (modalTitle) modalTitle.textContent = 'Add Student';
    if (saveButton) saveButton.textContent = 'Save Student';
    Object.values(fields).forEach(function (field) { if (field && field.tagName === 'INPUT' && field.type === 'file') field.value = ''; else if (field) field.value = ''; });
    if (fields.schoolYearStart) fields.schoolYearStart.value = String(new Date().getFullYear());
    if (fields.schoolYearEnd) fields.schoolYearEnd.value = String(new Date().getFullYear() + 1);

    if (row) {
        editingStudentId = row.dataset.studentRowId || row.dataset.studentId || row.cells[0].textContent.trim();
        const parts = (row.cells[1]?.textContent || '').trim().split(/\s+/);
        const firstName = parts[0] || '';
        const lastName = parts.length > 1 ? parts[parts.length - 1] : '';
        const middleName = parts.length > 2 ? parts.slice(1, -1).join(' ') : '';
        const schoolYear = (row.cells[4]?.textContent || '').trim();
        const statusValue = row.cells[5]?.textContent.trim();

        if (modalTitle) modalTitle.textContent = 'Edit Student';
        if (saveButton) saveButton.textContent = 'Update Student';
        if (fields.studentId) fields.studentId.value = row.cells[0].textContent.trim();
        if (fields.firstName) fields.firstName.value = firstName;
        if (fields.middleName) fields.middleName.value = middleName;
        if (fields.lastName) fields.lastName.value = lastName;
        if (fields.course) fields.course.value = row.cells[2].textContent.trim();
        if (fields.schoolYearStart && fields.schoolYearEnd && /^\d{4}-\d{4}$/.test(schoolYear)) {
            const [startYear, endYear] = schoolYear.split('-');
            fields.schoolYearStart.value = startYear;
            fields.schoolYearEnd.value = endYear;
        }
        if (fields.year) fields.year.value = row.cells[3].textContent.trim();
        if (fields.status) fields.status.value = statusValue === 'Irregular' ? 'Irregular' : 'Regular';
    }

    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
}

async function addStudent() {
    const studentId = document.getElementById('studentId').value.trim();
    const firstName = document.getElementById('studentFirstName').value.trim();
    const middleName = document.getElementById('studentMiddleName').value.trim();
    const lastName = document.getElementById('studentLastName').value.trim();
    const fullName = [firstName, middleName, lastName].filter(Boolean).join(' ');
    const course = document.getElementById('course').value.trim();
    const schoolYearStart = document.getElementById('studentSchoolYearStart').value.trim();
    const schoolYearEnd = document.getElementById('studentSchoolYearEnd').value.trim();
    const schoolYear = `${schoolYearStart}-${schoolYearEnd}`;
    const parentPhone = document.getElementById('parentPhone').value.trim();
    const year = document.getElementById('year').value.trim();
    const status = document.getElementById('status').value.trim();
    const facePhoto = document.getElementById('facePhoto').files[0];

    if (!studentId || !firstName || !lastName || !course || !schoolYearStart || !schoolYearEnd || !parentPhone || !year || !status || (!editingStudentId && !facePhoto)) {
        alert('Please complete all required fields.');
        return;
    }
    if (!/^\d{4}$/.test(schoolYearStart) || !/^\d{4}$/.test(schoolYearEnd) || Number(schoolYearEnd) !== Number(schoolYearStart) + 1) {
        alert('Enter consecutive school years, such as 2026 and 2027.');
        return;
    }
    if (facePhoto && facePhoto.size > 5 * 1024 * 1024) {
        alert('The face photo must be 5 MB or smaller.');
        return;
    }

    try {
        const payload = { studentId, fullName, course, schoolYear, parentPhone, year, status };
        if (editingStudentId) payload.id = editingStudentId;
        if (facePhoto) payload.facePhoto = await readFacePhoto(facePhoto);
        await requestApi('student', { method: 'POST', body: JSON.stringify(payload) });
        closeStudentModal();
        clearStudentForm();
        await loadDashboardData();
    } catch (error) {
        alert(error.message);
    }
}

async function deleteStudent(row) {
    const studentId = row.dataset.studentId;
    const studentName = row.cells[1]?.textContent.trim() || studentId;
    
    if (!confirm(`Are you sure you want to delete ${studentName}? This action cannot be undone.`)) {
        return;
    }
    
    try {
        await requestApi('delete-student', {
            method: 'POST',
            body: JSON.stringify({ studentId })
        });
        alert(`Student ${studentName} has been deleted successfully.`);
        await loadDashboardData();
    } catch (error) {
        alert('Error deleting student: ' + error.message);
    }
}

async function addSchedule() {
    const subject = document.getElementById('subject').value.trim();
    const teacher = document.getElementById('teacher').value.trim();
    const room = document.getElementById('room').value.trim();
    const selectedDays = getSelectedScheduleDays();
    const startTime = document.getElementById('startTime').value.trim();
    const endTime = document.getElementById('endTime').value.trim();
    const schoolYear = document.getElementById('scheduleSchoolYear').value.trim();

    if (!subject || !teacher || !room || selectedDays.length === 0 || !startTime || !endTime || !schoolYear) {
        alert('Please complete all fields.');
        return;
    }
    if (!/^\d{4}-\d{4}$/.test(schoolYear) || Number(schoolYear.slice(5)) !== Number(schoolYear.slice(0, 4)) + 1) {
        alert('Enter consecutive school years, such as 2026-2027.');
        return;
    }

    try {
        if (editingRow) {
            const day = selectedDays.join(', ');
            for (const selectedDay of selectedDays) {
                if (hasScheduleConflict(selectedDay, room, startTime, endTime, editingRow)) {
                    alert(`Schedule conflict: ${room} is already occupied on ${selectedDay} during this time.`);
                    return;
                }
            }

            await requestApi('schedule', {
                method: 'POST',
                body: JSON.stringify({
                    id: editingRow.dataset.scheduleId,
                    subject,
                    teacher,
                    room,
                    day,
                    startTime,
                    endTime,
                    schoolYear
                })
            });
        } else {
            for (const selectedDay of selectedDays) {
                if (hasScheduleConflict(selectedDay, room, startTime, endTime, null)) {
                    alert(`Schedule conflict: ${room} is already occupied on ${selectedDay} during this time.`);
                    return;
                }
            }

            for (const selectedDay of selectedDays) {
                await requestApi('schedule', {
                    method: 'POST',
                    body: JSON.stringify({
                        subject,
                        teacher,
                        room,
                        day: selectedDay,
                        startTime,
                        endTime,
                        schoolYear
                    })
                });
            }
        }

        closeModal();
        clearForm();
        editingRow = null;
        await loadDashboardData();
    } catch (error) {
        alert(error.message);
    }
}

function toTimeInputValue(value) {
    const trimmed = String(value || '').trim();
    if (!trimmed) return '';

    const match = trimmed.match(/^(\d{1,2}):(\d{2})(?:\s*(AM|PM))?$/i);
    if (!match) return '';

    let hours = Number(match[1]);
    const minutes = match[2].padStart(2, '0');
    const meridiem = (match[3] || '').toUpperCase();

    if (meridiem === 'PM' && hours !== 12) hours += 12;
    if (meridiem === 'AM' && hours === 12) hours = 0;

    return `${String(hours).padStart(2, '0')}:${minutes}`;
}

function editRow(button) {
    const row = button.closest('tr');
    editingRow = row;

    document.getElementById('modalTitle').textContent = 'Edit Schedule';
    document.getElementById('saveScheduleBtn').textContent = 'Update Schedule';

    document.getElementById('scheduleSchoolYear').value = row.cells[0].textContent;
    document.getElementById('subject').value = row.cells[1].textContent;
    document.getElementById('teacher').value = row.cells[2].textContent;
    document.getElementById('room').value = row.cells[3].textContent;

    const selectedDays = String(row.cells[4].textContent).split(',').map(function (day) { return day.trim(); }).filter(Boolean);
    setSelectedScheduleDays(selectedDays);

    const timeText = row.cells[5].textContent;
    const [startTime, endTime] = timeText.split(' - ');
    document.getElementById('startTime').value = toTimeInputValue(startTime || '');
    document.getElementById('endTime').value = toTimeInputValue(endTime || '');
    document.getElementById('scheduleSchoolYear').value = row.dataset.schoolYear || '2026-2027';

    const modal = document.getElementById('modal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

function openDeleteModal(button) {
    rowToDelete = button.closest('tr');
    const modal = document.getElementById('deleteConfirmModal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

function closeDeleteModal() {
    rowToDelete = null;
    const modal = document.getElementById('deleteConfirmModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function confirmDelete() {
    if (rowToDelete) {
        const scheduleId = rowToDelete.dataset.scheduleId;
        if (scheduleId) {
            requestApi('delete-schedule', { method: 'POST', body: JSON.stringify({ id: scheduleId }) })
                .then(loadDashboardData)
                .catch(function (error) { alert(error.message); });
        }
    }
    closeDeleteModal();
}

function searchStudent() {
    const input = document.getElementById('searchInput').value.trim().toUpperCase();
    const table = document.getElementById('attendanceTable');
    if (!table) {
        return;
    }

    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(function (row) {
        const nameCell = row.cells[1];
        const nameText = nameCell ? nameCell.textContent.trim().toUpperCase() : '';
        row.style.display = nameText.indexOf(input) > -1 ? '' : 'none';
    });
}

function searchReport() {
    const input = document.getElementById('reportSearchInput').value.trim().toUpperCase();
    const table = document.getElementById('reportTable');
    if (!table) {
        return;
    }

    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(function (row) {
        const nameCell = row.cells[1];
        const nameText = nameCell ? nameCell.textContent.trim().toUpperCase() : '';
        row.style.display = nameText.indexOf(input) > -1 ? '' : 'none';
    });
}

function openTimePicker() {
    const picker = document.getElementById('timePicker');
    if (!picker) {
        return;
    }

    try {
        if (typeof picker.showPicker === 'function') {
            picker.showPicker();
            return;
        }
    } catch (error) {
        console.warn('Picker could not be opened:', error);
    }

    picker.focus();
    picker.click();
}

function setTimeValue(value) {
    const input = document.getElementById('time');
    if (input) {
        input.value = value;
    }
}
