(() => {
    const $ = id => document.getElementById(id);
    let failures = 0;
    let run = null, active = false, timer = null, queue = [], seen = new Set();
    let frameTimer = null, frameEpoch = 0, frameRunning = false, frameUrl = null, photo = null;
    function stopFrames() {
        ++frameEpoch; frameRunning = false; clearTimeout(frameTimer); frameTimer = null;
        $('camera-feed').removeAttribute('src'); $('camera-feed').hidden = true;
        if (frameUrl) URL.revokeObjectURL(frameUrl);
        frameUrl = null;
        $('camera-placeholder').hidden = false;
    }
    async function frame(epoch) {
        if (!active || epoch !== frameEpoch) return;
        let delay = 250;
        try {
            const response = await fetch('/api/monitor/frame', {cache: 'no-store', signal: AbortSignal.timeout(8000)});
            if (!response.ok) throw new Error('Camera unavailable');
            const blob = await response.blob();
            if (!active || epoch !== frameEpoch) return;
            const previous = frameUrl;
            frameUrl = URL.createObjectURL(blob);
            $('camera-feed').src = frameUrl;
            $('camera-feed').hidden = false; $('camera-placeholder').hidden = true;
            if (previous) URL.revokeObjectURL(previous);
        } catch (error) {
            delay = 1000;
            if (epoch === frameEpoch) {
                $('camera-feed').hidden = true; $('camera-placeholder').hidden = false;
                $('camera-placeholder').textContent = 'Camera unavailable. Reconnecting…';
            }
        } finally {
            if (active && epoch === frameEpoch) frameTimer = setTimeout(() => frame(epoch), delay);
        }
    }
    function streamFrames(epoch) {
        if (!active || epoch !== frameEpoch) return;
        const image = $('camera-feed');
        image.onload = () => {
            if (active && epoch === frameEpoch) { image.hidden = false; $('camera-placeholder').hidden = true; }
        };
        image.onerror = () => {
            if (!active || epoch !== frameEpoch) return;
            image.hidden = true; $('camera-placeholder').hidden = false;
            $('camera-placeholder').textContent = 'Connecting to live camera…';
            frameTimer = setTimeout(() => streamFrames(epoch), 500);
        };
        image.src = 'http://' + window.location.hostname + ':8090/monitor_feed?view=' + Date.now();
    }
    function startFrames() {
        if (frameRunning) return;
        frameRunning = true;
        $('camera-placeholder').textContent = 'Connecting to camera…';
        if (window.location.protocol === "http:") streamFrames(frameEpoch);
        else frame(frameEpoch);
    }
    function clearStudent(message = 'No face detected yet.') {
        $('portrait').onload = null; $('portrait').onerror = null;
        $('portrait').removeAttribute('src'); $('portrait').hidden = true;
        $('initials').hidden = false; $('initials').textContent = '◎'; photo = null;
        $('profile-name').textContent = 'No student selected';
        $('face-details').hidden = true; $('face-message').hidden = false;
        $('face-message').textContent = message;
        for (const field of ['student-name','student-id','student-course','student-year','student-age','student-school-year','student-status']) $(field).textContent = '';
    }
    function student(data) {
        const info = data.student;
        if (!info) {
            clearStudent(!data.cameraAvailable ? 'Waiting for camera connection…' : data.faceDetected ? 'Student not found/not registered' : 'No face detected yet.');
            return;
        }
        $('face-details').hidden = false; $('face-message').hidden = true;
        $('profile-name').textContent = info.name;
        const values = {'student-name':info.name,'student-id':info.studentId,'student-course':info.course,'student-year':info.year,'student-age':info.age,'student-school-year':info.schoolYear,'student-status':info.status};
        for (const [id, value] of Object.entries(values)) $(id).textContent = value == null || value === '' ? '—' : String(value);
        $('initials').textContent = info.name.trim().split(/\s+/).slice(0,2).map(word => word[0]).join('').toUpperCase();
        if (photo !== info.photo) {
            photo = info.photo; $('portrait').hidden = true; $('initials').hidden = false;
            $('portrait').onload = () => { $('portrait').hidden = false; $('initials').hidden = true; };
            $('portrait').onerror = () => { $('portrait').hidden = true; $('initials').hidden = false; };
            $('portrait').removeAttribute('src');
            if (photo) $('portrait').src = photo;
        }
    }
    function clear() {
        clearTimeout(timer); timer = null; queue = []; seen.clear();
        $('confirmation').hidden = true; clearStudent(); stopFrames();
    }
    function waiting(connected = true) {
        $('operation').hidden = true; $('waiting').hidden = false;
        $('waiting-title').textContent = connected ? 'Waiting for Operation Mode' : 'Connection interrupted';
        $('waiting-description').textContent = connected ? 'The attendance monitor will activate when Operation Mode starts on the main computer.' : 'Reconnecting to the main computer…';
    }
    function next() {
        if (!active || !queue.length) { timer = null; $('confirmation').hidden = true; return; }
        const event = queue.shift();
        $('confirmation').hidden = false;
        $('confirmation-name').textContent = event.name;
        $('recorded-time').textContent = event.time;
        $('action').textContent = event.action === 'time_in' ? 'Time In recorded' : 'Time Out recorded';
        timer = setTimeout(next, 4000);
    }
    async function poll() {
        try {
            const response = await fetch('/api/monitor/status', {cache:'no-store',signal:AbortSignal.timeout(8000)});
            if (!response.ok) throw new Error('Monitor unavailable');
            const data = await response.json();
            failures = 0;
            $('connection').textContent = 'Connected'; $('connection').className = 'connection online';
            if (run !== data.run) { clear(); run = data.run; }
            active = data.active;
            document.body.classList.toggle('time-out', active && data.mode === 'time_out');
            $('mode').textContent = active ? data.mode === 'time_in' ? 'TIME IN · LIVE' : 'TIME OUT · LIVE' : 'STANDBY';
            if (!active) { clear(); waiting(); }
            else {
                $('waiting').hidden = true; $('operation').hidden = false;
                $('operation-title').textContent = data.mode === 'time_in' ? 'Operation Mode — Time In' : 'Operation Mode — Time Out';
                student(data); startFrames();
                for (const event of data.events) if (!seen.has(event.id)) { seen.add(event.id); queue.push(event); }
                if (seen.size > 200) seen = new Set([...seen].slice(-100));
                if (!timer) next();
            }
        } catch (error) {
            if (++failures < 3) { $("connection").textContent = "Reconnecting"; return; }
            clear(); active = false; run = null;
            $('connection').textContent = 'Reconnecting'; $('connection').className = 'connection';
            $('mode').textContent = 'OFFLINE'; waiting(false);
        } finally { setTimeout(poll, 1000); }
    }
    function clock() {
        const now = new Date();
        $('clock').textContent = now.toLocaleTimeString('en-PH', {timeZone:'Asia/Manila',hour:'numeric',minute:'2-digit',second:'2-digit'});
        $('date').textContent = now.toLocaleDateString('en-PH', {timeZone:'Asia/Manila',weekday:'long',month:'long',day:'numeric',year:'numeric'});
    }
    $('fullscreen').addEventListener('click', () => {
        const action = document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
        action.catch(() => { $('fullscreen').textContent = 'Press F11'; });
    });
    clock(); setInterval(clock,1000); poll();
})();
