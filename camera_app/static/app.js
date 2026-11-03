'use strict';
const $ = id => document.getElementById(id);
let status = null, initialized = false, selecting = false, drag = null, toastTimer, polling = false, lastReconnect = 0, wasOnline = false, previousUptime = 0, lastSourceEpoch = null, hostInfo = null, sourceFormDirty = false;
const schema = [
  ['Stream', [
    ['resolution','Resolution','select', [['640x360','640 × 360'],['1280x720','1280 × 720'],['1920x1080','1920 × 1080']]],
    ['fps','Capture FPS','select', [[10,'10'],[15,'15'],[20,'20'],[25,'25'],[30,'30']]],
    ['preview_fps','Preview FPS','select', [[5,'5'],[10,'10'],[15,'15'],[20,'20'],[30,'30']]],
    ['jpeg_quality','Preview quality','range',35,95,5],
    ['record_bitrate','Recording bitrate','select',[[1000000,'1 Mbit/s'],[1500000,'1.5 Mbit/s'],[2000000,'2 Mbit/s'],[4000000,'4 Mbit/s'],[8000000,'8 Mbit/s'],[16000000,'16 Mbit/s']]],
    ['rotation','Rotation','select',[[0,'0°'],[180,'180°']]],
    ['zoom','Digital zoom','range',1,4,.1]
  ]],
  ['Exposure', [
    ['AeEnable','Auto exposure','toggle'],
    ['ExposureValue','Exposure compensation (EV)','range',-4,4,.25],
    ['ExposureTime','Manual shutter (µs)','number',100,200000,100],
    ['AnalogueGain','Manual analog gain','range',1,16,.25],
    ['AeMeteringMode','Exposure metering','select',[[0,'Center weighted'],[1,'Spot'],[2,'Matrix']]],
    ['AeExposureMode','Exposure profile','select',[[0,'Normal'],[1,'Short exposure'],[2,'Long exposure']]],
    ['HdrMode','Pi 5 processing HDR','select',[[0,'Off'],[3,'Single-exposure HDR']]]
  ]],
  ['Color & ISP', [
    ['AwbEnable','Auto white balance','toggle'],
    ['AwbMode','White balance mode','select',[[0,'Auto'],[1,'Incandescent'],[2,'Tungsten'],[3,'Fluorescent'],[4,'Indoor'],[5,'Daylight'],[6,'Cloudy']]],
    ['red_gain','Manual red gain','range',.1,8,.1],
    ['blue_gain','Manual blue gain','range',.1,8,.1],
    ['Brightness','Brightness','range',-1,1,.05],
    ['Contrast','Contrast','range',0,4,.1],
    ['Saturation','Saturation','range',0,4,.1],
    ['Sharpness','ISP sharpness','range',0,4,.1],
    ['NoiseReductionMode','Noise reduction','select',[[0,'Off'],[1,'Fast'],[2,'High quality'],[3,'Minimal'],[4,'ZSL']]]
  ]],
  ['Focus', [
    ['AfMode','Focus mode','select',[[0,'Manual / locked'],[1,'Single shot'],[2,'Continuous']]],
    ['LensPosition','Lens position (diopters)','range',0,16,.1]
  ]]
];

function toast(message, error=false) {
  clearTimeout(toastTimer); $('toast').textContent=message; $('toast').classList.toggle('error',error); $('toast').hidden=false;
  toastTimer=setTimeout(()=>{$('toast').hidden=true;},error?8000:3500);
}
async function api(path, body) {
  const response=await fetch('/api/'+path, {method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-Camera-Client':'1'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
  const data=await response.json();
  if(!response.ok) throw new Error(data.error||'Request failed');
  return data;
}
function run(fn) { return Promise.resolve().then(fn).catch(e=>toast(e.message,true)); }
function makeControls() {
  const root=$('camera-controls');
  for(const [heading, fields] of schema){
    const section=document.createElement('section');section.className='control-group';
    const h=document.createElement('h3');h.textContent=heading;section.append(h);
    if(heading==='Focus'){const live=document.createElement('p');live.id='focus-summary';live.className='muted';section.append(live);}
    for(const [key,label,type,...args] of fields){
      const group=document.createElement('div');group.className='control'+(type==='toggle'?' toggle':'');group.id='group-'+key;
      const l=document.createElement('label');l.htmlFor='control-'+key;l.textContent=label;
      const input=document.createElement(type==='select'?'select':'input');input.id='control-'+key;input.dataset.key=key;
      if(type==='select')for(const [value,text] of args[0]){const option=document.createElement('option');option.value=value;option.textContent=text;input.append(option);}
      else { input.type=type==='toggle'?'checkbox':type; if(type!=='toggle'){[input.min,input.max,input.step]=args;}}
      if(type==='range'){const output=document.createElement('output');output.id='value-'+key;l.append(output);input.addEventListener('input',()=>{output.textContent=input.value;});}
      if(type==='toggle'){l.append(input);group.append(l);}else group.append(l,input);
      input.addEventListener('change',()=>run(async()=>{
        let values;
        if(key==='resolution'){const [width,height]=input.value.split('x').map(Number);values={width,height};}
        else if(key==='red_gain'||key==='blue_gain')values={ColourGains:[Number($('control-red_gain').value),Number($('control-blue_gain').value)]};
        else values={[key]:type==='toggle'?input.checked:Number(input.value)};
        if(key==='AeEnable'&&!input.checked&&status){values.ExposureTime=status.metadata.ExposureTime;values.AnalogueGain=status.metadata.AnalogueGain;}
        if(key==='AwbEnable'&&!input.checked&&status?.metadata.ColourGains)values.ColourGains=status.metadata.ColourGains;
        if(key==='AfMode'&&Number(input.value)===0&&status?.metadata.LensPosition!==undefined)values.LensPosition=status.metadata.LensPosition;
        try { const settings=await api('settings',values); status.settings=settings; syncControls(settings); }
        catch(e){if(status)syncControls(status.settings);throw e;}
      }));
      section.append(group);
    }
    root.append(section);
  }
}
function syncControls(s){
  for(const [,fields] of schema)for(const [key,,type] of fields){
    const input=$('control-'+key);input.disabled=false;$('group-'+key).classList.remove('disabled');if(document.activeElement===input)continue;
    const value=key==='resolution'?s.width+'x'+s.height:key==='red_gain'?s.ColourGains[0]:key==='blue_gain'?s.ColourGains[1]:s[key];
    if(type==='toggle')input.checked=Boolean(value);else input.value=value;
    if(type==='range')$('value-'+key).textContent=value;
  }
  for(const key of ['ExposureTime','AnalogueGain']){$('group-'+key).classList.toggle('disabled',s.AeEnable);$('control-'+key).disabled=s.AeEnable;}
  for(const key of ['red_gain','blue_gain']){$('group-'+key).classList.toggle('disabled',s.AwbEnable);$('control-'+key).disabled=s.AwbEnable;}
  $('group-LensPosition').classList.toggle('disabled',s.AfMode!==0);
  $('control-LensPosition').disabled=s.AfMode!==0;
  if(status)applySourceStatus(status);
}
function text(id,value){$(id).textContent=value;}
function update(s){
  status=s;
  const online=s.status==='running'&&s.frame_age_ms!==null&&s.frame_age_ms<3000;
  if(lastSourceEpoch!==s.source_epoch){
    initialized=false;
    if(hostInfo&&!sourceFormDirty)run(loadHost);
  }
  if(online&&(!wasOnline||s.uptime_s<previousUptime||lastSourceEpoch!==s.source_epoch))reconnect();
  lastSourceEpoch=s.source_epoch;
  wasOnline=online;previousUptime=s.uptime_s;
  $('connection-dot').className='dot '+(online?'online':'offline');text('connection',online?(s.hardware?'Camera connected':'Offline source ready'):'Recovering source');
  $('video-message').hidden=online;text('video-message',s.error||'Waiting for frames…');
  text('video-format',`${s.settings.width} × ${s.settings.height} / ${s.settings.fps} FPS`);
  text('capture-fps',s.capture_fps);text('preview-fps',s.preview_fps);
  text('exposure',s.metadata.ExposureTime?`${(s.metadata.ExposureTime/1000).toFixed(1)} ms`:'—');
  text('gain',s.hardware?`gain ${Number(s.metadata.AnalogueGain||0).toFixed(2)} · ${s.metadata.ColourTemperature||'—'} K`:'Hardware controls unavailable');
  text('focus-summary',`${['Idle','Scanning','Focused','Focus failed'][s.metadata.AfState]||'Unknown focus state'} · actual lens ${Number(s.metadata.LensPosition||0).toFixed(1)} diopters`);
  text('temperature',s.temperature_c===null?'N/A':s.temperature_c+'°');
  const thermal=s.thermal||{mode:'normal',current_flags:0};
  text('thermal-status',!s.hardware?'Ubuntu software source':thermal.current_flags?'Temperature / power limit active':thermal.mode==='normal'?'Normal workload':`Reduced workload: ${thermal.mode}`);
  text('temperature-label',s.hardware?'PI TEMPERATURE':'HARDWARE STATUS');
  text('disk',`${(s.disk_free_mb/1024).toFixed(1)} GB free · ${s.memory_available_mb} MB RAM available`);
  text('frame-age',`Frame age on ${s.hardware?'Pi':'host'}: ${s.frame_age_ms??'—'} ms`);
  text('api-time',`API round-trip ${s.host.api_roundtrip_ms} ms · not video latency`);
  const a=s.analysis||{};text('brightness',a.brightness??'—');text('sharpness',a.sharpness??'—');text('dark-pct',(a.dark_pct??'—')+'%');text('clipped-pct',(a.clipped_pct??'—')+'%');
  text('quality-label',a.error?'Analysis error':a.dark_pct>65?'Many dark pixels':a.clipped_pct>15?'Bright areas present':'Luminance histogram');
  text('analysis-time',a.inference_ms!==undefined?`${a.inference_ms} ms / age ${s.analysis_age_ms} ms`:'—');
  const ctx=$('histogram').getContext('2d');ctx.clearRect(0,0,320,70);
  if(a.histogram){const max=Math.max(...a.histogram,1);ctx.fillStyle='#bfe996';a.histogram.forEach((n,i)=>ctx.fillRect(i*10,70-n/max*65,7,n/max*65));}
  if(!initialized){syncControls(s.settings);initialized=true;}
  const rec=Boolean(s.recording);$('record-badge').hidden=!rec; text('record-label',rec?'Stop recording':'Record video');$('record').classList.toggle('selected',rec);
  if(rec)text('record-seconds',Math.floor(s.recording.seconds/60)+':'+String(Math.floor(s.recording.seconds%60)).padStart(2,'0'));
  for(const k of ['resolution','fps','rotation','HdrMode','record_bitrate'])$('control-'+k).disabled=rec;
  $('snapshot-full').disabled=rec||s.hardware===false;
  $('restart-camera').disabled=rec;
  const track=a.tracking||{};$('clear-track').hidden=!track.active;text('track-status',!track.active?'Inactive':track.lost?'Target lost':`Tracking · ${Math.round(track.confidence*100)}%`);
  $('detections').replaceChildren();
  const stale=s.analysis_age_ms>Math.max(2000,s.ai_options.interval_ms*3);
  for(const detection of stale?[]:(a.boxes||[])){
    const span=document.createElement('span');span.className='detection';span.textContent=detection.label;
    const score=document.createElement('small');score.textContent=Math.round(detection.confidence*100)+'%';span.append(score);$('detections').append(span);
  }
  if(!$('detections').children.length){const span=document.createElement('span');span.className='muted';span.textContent=a.error||'No detections in the current frame.';$('detections').append(span);}
  $('qr-results').replaceChildren();for(const value of a.qr||[]){const p=document.createElement('p');p.textContent=value;$('qr-results').append(p);}
  $('events').replaceChildren();for(const e of s.events.slice(0,8)){const row=document.createElement('div');row.className='event';const time=document.createElement('time');time.textContent=new Date(e.time).toLocaleTimeString('en-GB');row.append(time,document.createTextNode(e.message));$('events').append(row);}
  for(const input of document.querySelectorAll('[data-ai]')){input.checked=Boolean(s.ai_options[input.dataset.ai]);input.disabled=!s.capabilities[input.dataset.ai];}
  if(document.activeElement!==$('confidence')){$('confidence').value=s.ai_options.confidence*100;text('confidence-value',Math.round(s.ai_options.confidence*100)+'%');}
  if(document.activeElement!==$('interval'))$('interval').value=s.ai_options.interval_ms;
  applySourceStatus(s);
  $('autofocus').disabled=!s.controls.AfMode;
  if(!s.controls.AfMode){$('control-AfMode').disabled=true;$('control-LensPosition').disabled=true;}
}
async function poll(){
  if(polling)return;polling=true;
  try{update(await api('status'));}
  catch(e){$('connection-dot').className='dot offline';text('connection','Source unavailable');text('video-message','Selected source disconnected. Choose Simulator to work offline.');$('video-message').hidden=false;initialized=false;wasOnline=false;}
  finally{polling=false;}
}
function reconnect(){lastReconnect=Date.now();$('preview').src='/stream.mjpg?t='+lastReconnect;}
async function media(){
  const {files}=await api('media');$('media-list').replaceChildren();
  if(!files.length){text('media-list','No photos or recordings yet.');return;}
  for(const f of files){
    const item=document.createElement('div');item.className='media-item'+(f.recording?' pending':'');
    const url='/api/media/'+encodeURIComponent(f.name);
    if(f.name.endsWith('.jpg')){const image=document.createElement('img');image.src=url;image.loading='lazy';image.alt=f.name;item.append(image);}
    if(f.name.endsWith('.mp4')&&!f.recording){const video=document.createElement('video');video.src='/api/media/view/'+encodeURIComponent(f.name);video.controls=true;video.preload='metadata';item.append(video);}
    const link=document.createElement(f.recording?'span':'a');link.textContent=f.name;if(!f.recording){link.href=url;link.download=f.name;}item.append(link);
    const detail=document.createElement('small');detail.textContent=`${(f.bytes/1024/1024).toFixed(2)} MB · ${f.recording?'recording in progress':new Date(f.modified*1000).toLocaleString('en-GB')}`;item.append(detail);$('media-list').append(item);
  }
}
async function action(name){const result=await api('action/'+name,{});await poll();return result;}
makeControls();
$('snapshot').onclick=()=>run(async()=>{const result=await action('snapshot');toast('Snapshot saved. Download it from Media.');if(!$('tab-media').hidden)await media();});
$('snapshot-full').onclick=()=>run(async()=>{$('snapshot-full').disabled=true;try{await action('snapshot_full');toast('12 MP photo saved. Download it from Media.');if(!$('tab-media').hidden)await media();}finally{$('snapshot-full').disabled=Boolean(status?.recording);}});
$('record').onclick=()=>run(async()=>{await action(status?.recording?'record_stop':'record_start');toast(status?.recording?'Recording started':'Video saved');if(!$('tab-media').hidden)await media();});
$('autofocus').onclick=()=>run(async()=>{await action('autofocus');syncControls(status.settings);toast('Single autofocus started');});
$('restart-camera').onclick=()=>run(async()=>{await action('restart');reconnect();toast('Camera restarted');});
$('reset-camera').onclick=()=>run(async()=>{if(!confirm('Reset camera settings to defaults?'))return;await api('settings',presets.default);await poll();syncControls(status.settings);toast('Default settings restored');});
$('fullscreen').onclick=()=>run(()=>document.fullscreenElement?document.exitFullscreen():$('video-shell').requestFullscreen());
$('reconnect').onclick=reconnect;$('refresh-media').onclick=()=>run(media);
$('preview').onerror=()=>{if(Date.now()-lastReconnect>2000)setTimeout(reconnect,2000);};
for(const tab of document.querySelectorAll('[data-tab]'))tab.onclick=()=>{for(const t of document.querySelectorAll('[data-tab]'))t.classList.toggle('active',t===tab);for(const section of document.querySelectorAll('.tab-content'))section.hidden=section.id!=='tab-'+tab.dataset.tab;if(tab.dataset.tab==='media')run(media);if(tab.dataset.tab==='lab')run(reports);};
for(const input of document.querySelectorAll('[data-ai]'))input.onchange=()=>run(async()=>{await api('ai',{[input.dataset.ai]:input.checked});await poll();});
$('confidence').oninput=()=>text('confidence-value',$('confidence').value+'%');
$('confidence').onchange=()=>run(()=>api('ai',{confidence:Number($('confidence').value)/100}));
$('interval').onchange=()=>run(()=>api('ai',{interval_ms:Number($('interval').value)}));
const presets={
  default:{width:1280,height:720,fps:30,preview_fps:15,jpeg_quality:80,record_bitrate:4000000,rotation:0,zoom:1,AeEnable:true,ExposureTime:10000,AnalogueGain:1,ExposureValue:0,AwbEnable:true,AwbMode:0,ColourGains:[1.5,1.5],Brightness:0,Contrast:1,Saturation:1,Sharpness:1,NoiseReductionMode:1,AeMeteringMode:0,AeExposureMode:0,AfMode:0,LensPosition:0,HdrMode:0},
  motion:{AeEnable:true,AeExposureMode:1,NoiseReductionMode:1,ExposureValue:0},
  lowlight:{AeEnable:true,AeExposureMode:2,NoiseReductionMode:2,Sharpness:.7}
};
for(const button of document.querySelectorAll('[data-preset]'))button.onclick=()=>run(async()=>{await api('settings',presets[button.dataset.preset]);await poll();syncControls(status.settings);toast('Preset applied');});
function position(event){const r=$('overlay').getBoundingClientRect();return{x:Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(event.clientY-r.top)/r.height))};}
function setSelecting(value){selecting=value;drag=null;$('video-stage').classList.toggle('selecting',value);$('select-track').classList.toggle('selected',value);text('video-hint',value?'Drag a region to track · Esc to cancel':'Clean video · analysis overlays are displayed separately');}
$('select-track').onclick=()=>setSelecting(!selecting);
$('clear-track').onclick=()=>run(async()=>{await api('track',{roi:null});await poll();});
$('overlay').onpointerdown=event=>{if(!selecting)return;$('overlay').setPointerCapture(event.pointerId);drag={start:position(event),end:position(event)};};
$('overlay').onpointermove=event=>{if(drag)drag.end=position(event);};
$('overlay').onpointerup=event=>{if(!drag)return;drag.end=position(event);const roi={x:Math.min(drag.start.x,drag.end.x),y:Math.min(drag.start.y,drag.end.y),w:Math.abs(drag.start.x-drag.end.x),h:Math.abs(drag.start.y-drag.end.y)};setSelecting(false);run(async()=>{await api('track',{roi});toast('Region tracking enabled');await poll();});};
$('overlay').onpointercancel=()=>{drag=null;};
function draw(){
  const canvas=$('overlay');const width=canvas.clientWidth,height=canvas.clientHeight;
  if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
  const ctx=canvas.getContext('2d');ctx.clearRect(0,0,width,height);ctx.lineWidth=2;ctx.font='12px system-ui';
  if(status&&status.analysis_age_ms<Math.max(2000,status.ai_options.interval_ms*3))for(const b of status.analysis.boxes||[]){
    const color={object:'#c6ee9e',face:'#7fd1ff',qr:'#f7c877',motion:'#c7a0ff',track:'#ffb078'}[b.kind]||'#c6ee9e';ctx.strokeStyle=color;ctx.fillStyle=color;
    ctx.strokeRect(b.x*width,b.y*height,b.w*width,b.h*height);const label=b.label+' '+Math.round(b.confidence*100)+'%';const tw=ctx.measureText(label).width+10;ctx.fillRect(b.x*width,Math.max(0,b.y*height-22),tw,22);ctx.fillStyle='#101710';ctx.fillText(label,b.x*width+5,Math.max(15,b.y*height-7));
  }
  if(drag){ctx.strokeStyle='#fff';ctx.setLineDash([6,4]);ctx.strokeRect(drag.start.x*width,drag.start.y*height,(drag.end.x-drag.start.x)*width,(drag.end.y-drag.start.y)*height);ctx.setLineDash([]);}
  requestAnimationFrame(draw);
}
document.addEventListener('keydown',event=>{if(['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)||event.ctrlKey||event.metaKey||event.altKey||event.repeat)return;if(event.key.toLowerCase()==='s')$('snapshot').click();if(event.key.toLowerCase()==='r')$('record').click();if(event.key==='Escape')setSelecting(false);});
run(loadHost);reconnect();poll();setInterval(poll,1000);setInterval(()=>{if(!$("tab-lab").hidden)run(reports);},3000);requestAnimationFrame(draw);

function optionList(select, items, selected){
  const old=selected??select.value;select.replaceChildren();
  for(const item of items){const option=document.createElement('option');option.value=item.id;option.textContent=item.name;select.append(option);}
  if(items.some(item=>item.id===old))select.value=old;
}
function sourceForm(){
  $('source-input-group').hidden=$('source-mode').value!=='replay';
  $('source-url-group').hidden=$('source-mode').value!=='pi';
}
async function loadHost(){
  hostInfo=await api('host');
  if(!sourceFormDirty){$('source-mode').value=hostInfo.mode;$('source-url').value=hostInfo.camera_url;}
  optionList($('source-input'),hostInfo.inputs);
  optionList($('benchmark-input'),hostInfo.inputs);
  optionList($('performance-profile'),hostInfo.profiles);
  profileDescription();sourceForm();
  const data=await api('presets');optionList($('saved-preset'),data.presets);
}
function profileDescription(){
  const profile=hostInfo?.profiles.find(x=>x.id===$('performance-profile').value);
  text('profile-description',profile?.description||'');
}
function applySourceStatus(s){
  const source=s.source||{kind:'pi',name:'Raspberry Pi camera'};
  $('video-shell').classList.toggle('source-offline',!s.hardware);
  document.title='Camera Studio · '+(s.hardware?'Camera':source.kind==='replay'?'Replay':'Simulator');
  text('view-eyebrow',s.hardware?'CAMERA VIEW':'SOFTWARE VIEW');
  text('source-tag',source.kind==='simulator'?'SIMULATOR':source.kind==='replay'?'REPLAY':'LIVE');
  text('model-chip',s.hardware?(s.properties.Model||'CAMERA'):'OFFLINE');
  text('source-description',source.name);
  if(!s.hardware)text('focus-summary','Requires camera hardware');
  text('camera-note',s.hardware?'Resolution, FPS, HDR and rotation changes briefly pause capture. Photos and videos are stored on the Pi without overlays. Thermal workload caps are automatic.':'Software adjustments are approximate and do not reproduce the Pi ISP. Snapshots and H.264 recordings are saved locally on Ubuntu without overlays. Exposure, autofocus, noise reduction and HDR require real hardware.');
  text('source-notice',s.hardware?'Real camera hardware':'Software source. Sensor exposure, autofocus and HDR are not simulated.');
  text('footer-source',s.hardware?'Ubuntu host ↔ Raspberry Pi':'Ubuntu host · '+source.kind+' · no Raspberry Pi required');
  text('analysis-heading',s.hardware?'Analysis on Raspberry Pi':'Analysis on Ubuntu');
  text('analysis-location',s.hardware?'Inference runs on the Pi CPU. IMX708 has no AI accelerator. Stale boxes are hidden.':'Inference runs on this Ubuntu host. Its timing does not predict Raspberry Pi performance. Stale boxes are hidden.');
  text('media-description',s.hardware?'Files are stored on the Pi microSD. Download them to Ubuntu.':'These files are stored locally on Ubuntu. They are not uploaded to the Pi.');
  if(s.supported_settings){
    for(const [,fields] of schema)for(const [key] of fields){
      const actual=key==='resolution'?'width':['red_gain','blue_gain'].includes(key)?'ColourGains':key;
      if(!s.supported_settings.includes(actual)){$('control-'+key).disabled=true;$('group-'+key).classList.add('disabled');}
    }
  }
  for(const button of document.querySelectorAll('[data-preset]'))if(button.dataset.preset!=='default')button.disabled=!s.hardware;
  $('apply-source').disabled=Boolean(s.recording);
  $('playback-controls').hidden=source.kind!=='replay';
  if(source.kind==='replay'&&s.playback){
    const p=s.playback;const duration=p.duration_s||0;
    text('playback-pause',p.paused?'Resume':'Pause');
    $('playback-seek').disabled=!duration;
    $('playback-seek').max=Math.max(0,duration-.01);
    if(document.activeElement!==$('playback-seek'))$('playback-seek').value=p.position_s;
    text('playback-time',`${p.position_s.toFixed(1)} / ${duration.toFixed(1)} s`);
  }
}
$('source-mode').onchange=()=>{sourceFormDirty=true;sourceForm();};
$('source-input').onchange=()=>{sourceFormDirty=true;};
$('source-url').oninput=()=>{sourceFormDirty=true;};
$('apply-source').onclick=()=>run(async()=>{
  const mode=$('source-mode').value;
  await api('source',{mode,input_id:$('source-input').value,camera_url:$('source-url').value||hostInfo.camera_url});
  initialized=false;wasOnline=false;sourceFormDirty=false;
  await loadHost();await poll();reconnect();
  if(!$('tab-media').hidden)await media();
  toast('Source changed');
});
$('upload-input').onclick=()=>$('input-upload').click();
$('input-upload').onchange=()=>run(async()=>{
  const file=$('input-upload').files[0];if(!file)return;
  $('upload-input').disabled=true;
  try{
    const form=new FormData();form.append('file',file);
    const response=await fetch('/api/inputs',{method:'POST',headers:{'X-Camera-Client':'1'},body:form});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'Import failed');
    await loadHost();sourceFormDirty=true;$('source-mode').value='replay';$('source-input').value=result.id;sourceForm();
    toast('Input imported. Click Apply source to play it.');
  }finally{$('upload-input').disabled=false;$('input-upload').value='';}
});
$('playback-pause').onclick=()=>run(async()=>{await api('playback',{paused:!status.playback.paused});await poll();});
$('playback-seek').onchange=()=>run(async()=>{await api('playback',{seek_s:Number($('playback-seek').value)});await poll();});
$('performance-profile').onchange=profileDescription;
$('apply-profile').onclick=()=>run(async()=>{
  const r=await api('profiles/'+$('performance-profile').value+'/apply',{});await poll();syncControls(status.settings);
  toast(r.skipped_hardware_settings.length?'Profile applied; hardware-only controls skipped.':'Profile applied');
});
$('save-preset').onclick=()=>run(async()=>{
  const name=$('preset-name').value.trim();if(!name)throw new Error('Enter a preset name');
  const p=await api('presets',{name});await loadHost();$('saved-preset').value=p.id;toast('Preset saved on Ubuntu');
});
$('apply-saved-preset').onclick=()=>run(async()=>{
  const id=$('saved-preset').value;if(!id)throw new Error('Choose a preset');
  const result=await api('presets/'+id+'/apply',{});await poll();syncControls(status.settings);
  toast(result.skipped_hardware_settings.length?'Preset applied; hardware-only controls skipped.':'Preset applied');
});
$('export-preset').onclick=()=>{
  const id=$('saved-preset').value;if(!id){toast('Choose a preset',true);return;}
  const a=document.createElement('a');a.href='/api/presets/'+id;a.download='camera-preset.json';a.click();
};
$('import-preset').onclick=()=>$('preset-upload').click();
$('preset-upload').onchange=()=>run(async()=>{
  const file=$('preset-upload').files[0];if(!file)return;
  if(file.size>16000)throw new Error('Preset exceeds 16 KB');
  const preset=JSON.parse(await file.text());const result=await api('presets',{preset});await loadHost();$('saved-preset').value=result.id;
  $('preset-upload').value='';toast('Preset imported. Click Apply to use it.');
});
$('start-benchmark').onclick=()=>run(async()=>{
  const input_id=$('benchmark-input').value;if(!input_id)throw new Error('Add a video or image first');
  const analysis={...(status?.ai_options||{} )};
  if(!['objects','faces','qr','motion'].some(k=>analysis[k]))throw new Error('Enable an analysis mode in AI & CV first');
  await api('benchmarks',{input_id,analysis,stride:Number($('benchmark-stride').value),max_frames:Number($('benchmark-maximum').value)});
  toast('Host analysis started');await reports();
});
async function reports(){
  const data=await api('benchmarks');const job=data.job;
  $('start-benchmark').disabled=job?.status==='running';
  text('benchmark-status',!job?'No analysis job yet.':job.status==='running'?`Running · ${job.analyzed_frames} frames analyzed`:job.status==='error'?`Analysis failed: ${job.error}`:`Complete · ${job.analyzed_frames} frames analyzed`);
  $('benchmark-reports').replaceChildren();
  for(const report of data.reports){
    const card=document.createElement('div');card.className='report-card';const title=document.createElement('h3');title.textContent=report.name;
    const p=document.createElement('p');p.textContent=`${report.summary.analyzed_frames} frames · ${report.summary.detections} detections · p50 ${report.summary.inference_p50_ms} ms · p95 ${report.summary.inference_p95_ms} ms`;
    const processor=document.createElement('p');processor.textContent=report.processor;
    card.append(title,p,processor);
    for(const extension of ['json','csv']){const a=document.createElement('a');a.href='/api/reports/'+report.id+'.'+extension;a.textContent=extension.toUpperCase();a.download='';card.append(a);}
    $('benchmark-reports').append(card);
  }
}
