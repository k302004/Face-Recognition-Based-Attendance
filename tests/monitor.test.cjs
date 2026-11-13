const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function monitor(initial){
    const elements=new Map(), tasks=new Map(), requests=[]; let id=0,state=initial;
    const get=id=>{if(!elements.has(id))elements.set(id,{hidden:false,textContent:'',className:'',addEventListener(){},removeAttribute(name){delete this[name];}});return elements.get(id);};
    const context=vm.createContext({window:{location:{protocol:"http:",hostname:"10.81.122.220"}},document:{getElementById:get,body:{classList:{toggle(){}}}},Date,Set,AbortSignal,
        URL:{createObjectURL:()=> 'blob:test-frame',revokeObjectURL(){}},
        fetch:async(url,options)=>{requests.push({url,method:options.method||'GET'});if(state instanceof Error)throw state;return {ok:true,json:async()=>state,blob:async()=>({})};},
        setTimeout:(fn,delay)=>{tasks.set(++id,{fn,delay});return id;},clearTimeout:id=>tasks.delete(id),setInterval(){},
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname,'../public/js/monitor.js'),'utf8'),context);
    async function settle(){await new Promise(resolve=>setImmediate(resolve));}
    async function advance(delay){const task=[...tasks].find(([,task])=>task.delay===delay);assert.ok(task,`No timer for ${delay}`);tasks.delete(task[0]);await task[1].fn();await settle();}
    return {get,tasks,requests,settle,advance,state:value=>state=value};
}
const student={name:'Test Student',studentId:'TEST-001',course:'BSIT',year:'2',age:19,schoolYear:'2026-2027',status:'Active',photo:null};
const event={id:'event1',name:'Test Student',studentId:'TEST-001',action:'time_in',time:'8:00 AM',photo:null};
test('active monitor shows camera, profile and face data without recording attendance',async()=>{
    const m=monitor({active:true,mode:'time_in',run:'run1',events:[event],student,cameraAvailable:true,faceDetected:true});await m.settle();
    assert.equal(m.get('operation').hidden,false);
    assert.equal(m.get('student-name').textContent,'Test Student');
    assert.equal(m.get('student-course').textContent,'BSIT');
    assert.equal(m.get('profile-name').textContent,'Test Student');
    assert.match(m.get('camera-feed').src,/^http:\/\/10\.81\.122\.220:8090\/monitor_feed/);
    assert.equal(m.get('confirmation').hidden,false);
    await m.advance(1000);await m.advance(4000);
    assert.equal(m.get('confirmation').hidden,true);
    assert.equal(m.get('operation').hidden,false);
    assert.ok(m.requests.every(r=>r.method==='GET'));
    m.state({active:false,mode:null,run:null,events:[]});await m.advance(1000);
    assert.equal(m.get('operation').hidden,true);
    assert.equal(m.get('camera-feed').src,undefined);
    assert.equal(m.get('student-name').textContent,'');
    assert.ok(![...m.tasks.values()].some(task=>task.delay===80));
});
test('network failure clears camera and student information',async()=>{
    const m=monitor({active:true,mode:'time_out',run:'run1',events:[{...event,action:'time_out'}],student,cameraAvailable:true});await m.settle();
    assert.equal(m.get('action').textContent,'Time Out recorded');
    m.state(new Error('offline'));await m.advance(1000);
    assert.equal(m.get('operation').hidden,false);
    await m.advance(1000);await m.advance(1000);
    assert.equal(m.get('operation').hidden,true);
    assert.equal(m.get('student-name').textContent,'');
    assert.equal(m.get('camera-feed').src,undefined);
    assert.equal(m.get('waiting-title').textContent,'Connection interrupted');
});
test('unknown faces clear the previous profile without claiming recorded attendance',async()=>{
    const m=monitor({active:true,mode:'time_in',run:'run1',events:[],student,cameraAvailable:true,faceDetected:true});await m.settle();
    m.state({active:true,mode:'time_in',run:'run1',events:[],student:null,cameraAvailable:true,faceDetected:true});await m.advance(1000);
    assert.equal(m.get('face-details').hidden,true);
    assert.equal(m.get('student-name').textContent,'');
    assert.equal(m.get('face-message').textContent,'Student not found/not registered');
    assert.equal(m.get('confirmation').hidden,true);
});
