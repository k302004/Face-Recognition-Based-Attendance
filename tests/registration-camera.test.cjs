const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function registration(protocol = 'http:') {
    const preview = { naturalWidth: 720, naturalHeight: 1280,
        removeAttribute(name) { delete this[name]; } };
    const status = {};
    let drawn = false;
    const canvas = { getContext: () => ({ drawImage: () => { drawn = true; } }),
        toDataURL: () => 'data:image/jpeg;base64,test' };
    const elements = { registrationVideo: preview, registrationPoseStatus: status,
        registrationCanvas: canvas };
    const alerts = [];
    const context = vm.createContext({
        document: { getElementById: id => elements[id] || null },
        window: { location: { protocol } },
        alert: message => alerts.push(message),
    });
    const source = fs.readFileSync(path.join(__dirname, '../public/js/script.js'), 'utf8');
    vm.runInContext(source.slice(source.indexOf('let registrationCaptures = {}'),
        source.indexOf('async function submitStudentRegistration()')), context);
    return { context, preview, status, canvas, alerts, drawn: () => drawn };
}

test('registration shares stream, captures a frame and disconnects on stop', () => {
    const r = registration();
    r.context.startRegistrationCamera();
    assert.match(r.preview.src, /^http:\/\/127\.0\.0\.1:8090\/video_feed/);
    r.preview.onload();
    assert.match(r.status.textContent, /Camera ready/);
    r.context.captureRegistrationFrame('front');
    assert.equal(r.drawn(), true);
    assert.equal(r.canvas.width, 720);
    r.context.stopRegistrationCamera();
    assert.equal(r.preview.src, undefined);
    r.context.captureRegistrationFrame('front');
    assert.equal(r.alerts.length, 1);
});

test('HTTPS uses proxy and a failed stream can be retried', () => {
    const r = registration('https:');
    r.context.startRegistrationCamera();
    assert.match(r.preview.src, /^api\.php\?action=camera-feed/);
    r.preview.onerror();
    assert.match(r.status.textContent, /Camera unavailable/);
    assert.equal(r.preview.src, undefined);
    r.context.startRegistrationCamera();
    assert.ok(r.preview.src);
});
