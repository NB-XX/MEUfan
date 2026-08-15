// ===== API helpers =====
function api(method, path, body){
  if(!apiAvailable){
    return Promise.reject(Error('Management API unavailable in static mode. Run server.py locally.'));
  }
  var opts={method:method,headers:{},credentials:'include'};
  if(body instanceof FormData){opts.body=body}
  else if(body){opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(body)}
  return fetch(path,opts).then(function(r){return r.json().then(function(j){if(!r.ok){var e=Error(j.error||('HTTP '+r.status));e.status=r.status;e.details=j;throw e}return j})});
}

// ===== State =====
var mapping=null,allVideos=[],apiAvailable=true,sourceSaveTimers={};
var uploadFileData=null,uploadFileName=null,uploadDetectedLang='ko';
var glossary={terms:[]};
var langOverrides={}; // filename -> lang for batch import language adjustment

// ===== UI language =====
function detectUiLang(){
  var raw=(navigator.language||navigator.userLanguage||'en').toLowerCase();
  if(raw.indexOf('ko')===0)return'ko';
  if(raw.indexOf('ja')===0)return'ja';
  if(raw.indexOf('zh')===0)return'zh';
  return'en';
}
var UI_LANG=detectUiLang();
document.documentElement.lang=UI_LANG;
var UI_TEXT={
  en:{
    pageTitle:'MEU Subtitle Manager',openApp:'Open search app',searchVideos:'Search videos...',
    uploadSrt:'Upload SRT',batchImport:'Batch import',scan:'Scan',syncYoutube:'Sync YouTube',
    scannerTitle:'Unassigned SRT files',title:'Title',duration:'Duration',subtitles:'Subtitles',
    uploadTitle:'Upload SRT subtitles',selectSrt:'Select SRT file',dropText:'Click or drag to upload an SRT file',
    language:'Language',assignVideo:'Video to assign (optional)',none:'-- None --',cancel:'Cancel',upload:'Upload',
    batchTitle:'Batch import SRT',batchHelp:'Upload multiple SRT files at once. Language is auto-detected and videos are matched by filename similarity.',
    batchDropText:'Click or drag to select SRT files',batchDropHint:'Only .srt files are supported',
    filename:'Filename',subtitleCount:'Subtitle count',matchedVideo:'Matched video',similarity:'Similarity',
    importAll:'Import all',published:'Published',sortDefault:'Default order',sortTitle:'Title',sortDuration:'Duration',sortPublished:'Publish date',stats:'{videos} videos | {withSubs} with subtitles',loadFailed:'Failed to load data: {message}',
    noRows:'No videos found.',unassignTitle:'Unassign',uploadAssignTitle:'Upload and assign SRT',
    selectFile:'Select a file first.',srtOnly:'Only SRT files can be uploaded.',uploading:'Uploading...',uploadDone:'Uploaded: {filename}',
    uploadAssignDone:'Uploaded and assigned: {filename}',uploadFailed:'Upload failed: {message}',confirmDetach:'Unassign {lang} subtitles?\n(The file will not be deleted.)',
    detached:'Unassigned.',failed:'Failed: {message}',batchAnalyzing:'Uploading and analyzing...',batchNoFiles:'Only SRT files can be selected.',
    matchFailed:'Match failed',batchStatus:'{files} files | {matched} matched above 70%',noAssignments:'No files to assign.',
    assigning:'Assigning...',assigned:'Assigned {count} files.',allAssigned:'All SRT files are assigned.',
    suggestions:'Auto-match suggestions ({count}):',noSuggestions:'No match suggestions:',assign:'Assign',
    assignedFile:'Assigned: {filename}',scanningFailed:'Scan failed: {message}',syncing:'Syncing...',syncDone:'YouTube sync complete.',
    syncFailed:'Sync failed: {message}',standardizeNames:'Standardize names',standardized:'Standardized {renamed} files, skipped {skipped}.',glossary:'Glossary',logout:'Logout',
    staticModeNotice:'⚠️ Running on static hosting. Management features (upload, assign, sync) are disabled. Clone the repo and run server.py locally for full admin access.',
    staticUploadDisabled:'Upload disabled on static hosting.',
    staticDetachDisabled:'Unassign disabled on static hosting.',
    staticSyncDisabled:'YouTube sync disabled on static hosting.',
    cleanStale:'Clean stale',
    cleanStaleConfirm:'Remove {count} stale subtitle mappings?\nThese files no longer exist on disk:\n\n{files}',
    cleanStaleDone:'Removed {count} stale mappings.',
    cleanStaleNone:'No stale mappings found.',
    batchConflictTooltip:'Already has a subtitle for this language — will be replaced',
    batchChangeLang:'Click to change detected language'
  },
  ko:{
    pageTitle:'MEU 자막 관리자',openApp:'검색 앱 열기',searchVideos:'비디오 검색...',
    uploadSrt:'SRT 업로드',batchImport:'일괄 가져오기',scan:'스캔',syncYoutube:'YouTube 동기화',
    scannerTitle:'미할당 SRT 파일',title:'제목',duration:'재생시간',subtitles:'자막',
    uploadTitle:'SRT 자막 업로드',selectSrt:'SRT 파일 선택',dropText:'클릭 또는 드래그하여 SRT 파일 업로드',
    language:'언어',assignVideo:'연결할 비디오 (선택)',none:'-- 선택 안함 --',cancel:'취소',upload:'업로드',
    batchTitle:'일괄 SRT 가져오기',batchHelp:'여러 SRT 파일을 한 번에 업로드합니다. 언어는 자동 감지하고, 비디오는 파일명 유사도 기준으로 자동 매칭합니다.',
    batchDropText:'클릭 또는 드래그하여 여러 SRT 파일 선택',batchDropHint:'.srt 파일만 업로드 가능',
    filename:'파일명',subtitleCount:'자막수',matchedVideo:'매칭 비디오',similarity:'유사도',
    importAll:'모두 가져오기',published:'게시일',sortDefault:'기본 순서',sortTitle:'제목순',sortDuration:'재생시간순',sortPublished:'게시일순',stats:'총 {videos}개 비디오 | {withSubs}개 자막 있음',loadFailed:'데이터 로드 실패: {message}',
    noRows:'검색된 비디오가 없습니다.',unassignTitle:'할당 해제',uploadAssignTitle:'SRT 업로드 및 할당',
    selectFile:'파일을 선택해주세요.',srtOnly:'SRT 파일만 업로드 가능합니다.',uploading:'업로드 중...',uploadDone:'업로드 완료: {filename}',
    uploadAssignDone:'업로드 및 할당 완료: {filename}',uploadFailed:'업로드 실패: {message}',confirmDetach:'{lang} 자막 할당을 해제하시겠습니까?\n(파일은 삭제되지 않습니다.)',
    detached:'할당 해제됨.',failed:'실패: {message}',batchAnalyzing:'업로드 및 분석 중...',batchNoFiles:'SRT 파일만 선택 가능합니다.',
    matchFailed:'매칭 실패',batchStatus:'{files}개 파일 | {matched}개 70% 이상 매칭',noAssignments:'할당할 파일이 없습니다.',
    assigning:'할당 중...',assigned:'{count}개 파일 할당 완료.',allAssigned:'모든 SRT 파일이 할당되어 있습니다.',
    suggestions:'자동 매칭 제안 ({count}개):',noSuggestions:'매칭 제안 없음:',assign:'할당',
    assignedFile:'할당 완료: {filename}',scanningFailed:'스캔 실패: {message}',syncing:'동기화 중...',syncDone:'YouTube 동기화 완료.',
    syncFailed:'동기화 실패: {message}',standardizeNames:'파일명 정리',standardized:'{renamed}개 파일 정리, {skipped}개 건너뜀.',glossary:'용어집',logout:'로그아웃',
    staticModeNotice:'⚠️ 정적 호스팅에서 실행 중입니다. 관리 기능(업로드, 할당, 동기화)은 비활성화됩니다. 전체 관리 기능은 로컬에서 server.py를 실행해 사용하세요.',
    staticUploadDisabled:'정적 호스팅에서는 업로드가 비활성화됩니다.',
    staticDetachDisabled:'정적 호스팅에서는 할당 해제가 비활성화됩니다.',
    staticSyncDisabled:'정적 호스팅에서는 YouTube 동기화가 비활성화됩니다.',
    cleanStale:'매핑 정리',
    cleanStaleConfirm:'{count}개의 오래된 자막 매핑을 제거하시겠습니까?\n다음 파일이 더 이상 디스크에 존재하지 않습니다:\n\n{files}',
    cleanStaleDone:'{count}개의 오래된 매핑을 제거했습니다.',
    cleanStaleNone:'오래된 매핑이 없습니다.',
    batchConflictTooltip:'이미 해당 언어의 자막이 있습니다 — 대체됩니다',
    batchChangeLang:'클릭하여 감지된 언어 변경'
  },
  ja:{
    pageTitle:'MEU 字幕管理',openApp:'検索アプリを開く',searchVideos:'動画を検索...',
    uploadSrt:'SRT をアップロード',batchImport:'一括インポート',scan:'スキャン',syncYoutube:'YouTube 同期',
    scannerTitle:'未割り当て SRT ファイル',title:'タイトル',duration:'再生時間',subtitles:'字幕',
    uploadTitle:'SRT 字幕アップロード',selectSrt:'SRT ファイルを選択',dropText:'クリックまたはドラッグして SRT をアップロード',
    language:'言語',assignVideo:'割り当てる動画 (任意)',none:'-- なし --',cancel:'キャンセル',upload:'アップロード',
    batchTitle:'SRT 一括インポート',batchHelp:'複数の SRT ファイルを一括アップロードします。言語は自動検出し、動画はファイル名の類似度で照合します。',
    batchDropText:'クリックまたはドラッグして SRT ファイルを選択',batchDropHint:'.srt ファイルのみ対応',
    filename:'ファイル名',subtitleCount:'字幕数',matchedVideo:'照合動画',similarity:'類似度',
    importAll:'すべてインポート',published:'公開日',sortDefault:'デフォルト順',sortTitle:'タイトル順',sortDuration:'再生時間順',sortPublished:'公開日順',stats:'{videos} 本の動画 | 字幕あり {withSubs} 本',loadFailed:'データ読み込み失敗: {message}',
    noRows:'動画が見つかりません。',unassignTitle:'割り当て解除',uploadAssignTitle:'SRT をアップロードして割り当て',
    selectFile:'ファイルを選択してください。',srtOnly:'SRT ファイルのみアップロードできます。',uploading:'アップロード中...',uploadDone:'アップロード完了: {filename}',
    uploadAssignDone:'アップロードと割り当て完了: {filename}',uploadFailed:'アップロード失敗: {message}',confirmDetach:'{lang} 字幕の割り当てを解除しますか？\n(ファイルは削除されません。)',
    detached:'割り当てを解除しました。',failed:'失敗: {message}',batchAnalyzing:'アップロードと分析中...',batchNoFiles:'SRT ファイルのみ選択できます。',
    matchFailed:'照合失敗',batchStatus:'{files} ファイル | {matched} 件が 70% 以上で照合',noAssignments:'割り当てるファイルがありません。',
    assigning:'割り当て中...',assigned:'{count} 件を割り当てました。',allAssigned:'すべての SRT ファイルが割り当て済みです。',
    suggestions:'自動照合候補 ({count} 件):',noSuggestions:'照合候補なし:',assign:'割り当て',
    assignedFile:'割り当て完了: {filename}',scanningFailed:'スキャン失敗: {message}',syncing:'同期中...',syncDone:'YouTube 同期完了。',
    syncFailed:'同期失敗: {message}',standardizeNames:'ファイル名整理',standardized:'{renamed} 件を整理、{skipped} 件をスキップしました。',glossary:'用語集',logout:'ログアウト',
    staticModeNotice:'⚠️ 静的ホスティングで実行中です。管理機能(アップロード、割り当て、同期)は無効です。ローカルで server.py を実行すると管理できます。',
    staticUploadDisabled:'静的ホスティングではアップロードできません。',
    staticDetachDisabled:'静的ホスティングでは割り当て解除できません。',
    staticSyncDisabled:'静的ホスティングではYouTube同期はできません。',
    cleanStale:'マッピング整理',
    cleanStaleConfirm:'{count} 件の古い字幕マッピングを削除しますか？\n以下のファイルはディスク上に存在しません：\n\n{files}',
    cleanStaleDone:'{count} 件の古いマッピングを削除しました。',
    cleanStaleNone:'古いマッピングはありません。',
    batchConflictTooltip:'この言語の字幕が既に存在します — 置き換えられます',
    batchChangeLang:'クリックして検出言語を変更'
  },
  zh:{
    pageTitle:'MEU 字幕管理',openApp:'打开搜索页面',searchVideos:'搜索视频...',
    uploadSrt:'上传 SRT',batchImport:'批量导入',scan:'扫描',syncYoutube:'同步 YouTube',
    scannerTitle:'未分配的 SRT 文件',title:'标题',duration:'时长',subtitles:'字幕',
    uploadTitle:'上传 SRT 字幕',selectSrt:'选择 SRT 文件',dropText:'点击或拖拽上传 SRT 文件',
    language:'语言',assignVideo:'要绑定的视频（可选）',none:'-- 不绑定 --',cancel:'取消',upload:'上传',
    batchTitle:'批量导入 SRT',batchHelp:'一次上传多个 SRT 文件。系统会自动识别语言，并按文件名相似度匹配视频。',
    batchDropText:'点击或拖拽选择多个 SRT 文件',batchDropHint:'仅支持 .srt 文件',
    filename:'文件名',subtitleCount:'字幕数',matchedVideo:'匹配视频',similarity:'相似度',
    importAll:'全部导入',published:'发布时间',sortDefault:'默认顺序',sortTitle:'标题',sortDuration:'时长',sortPublished:'发布时间',stats:'共 {videos} 个视频 | {withSubs} 个有字幕',loadFailed:'数据加载失败：{message}',
    noRows:'没有找到视频。',unassignTitle:'解除绑定',uploadAssignTitle:'上传并绑定 SRT',
    selectFile:'请先选择文件。',srtOnly:'只能上传 SRT 文件。',uploading:'上传中...',uploadDone:'上传完成：{filename}',
    uploadAssignDone:'上传并绑定完成：{filename}',uploadFailed:'上传失败：{message}',confirmDetach:'确定解除 {lang} 字幕绑定吗？\n（文件不会被删除。）',
    detached:'已解除绑定。',failed:'失败：{message}',batchAnalyzing:'上传并分析中...',batchNoFiles:'只能选择 SRT 文件。',
    matchFailed:'匹配失败',batchStatus:'{files} 个文件 | {matched} 个达到 70% 匹配',noAssignments:'没有可绑定的文件。',
    assigning:'绑定中...',assigned:'已绑定 {count} 个文件。',allAssigned:'所有 SRT 文件都已绑定。',
    suggestions:'自动匹配建议（{count} 个）：',noSuggestions:'没有匹配建议：',assign:'绑定',
    assignedFile:'绑定完成：{filename}',scanningFailed:'扫描失败：{message}',syncing:'同步中...',syncDone:'YouTube 同步完成。',
    syncFailed:'同步失败：{message}',standardizeNames:'整理文件名',standardized:'已整理 {renamed} 个文件，跳过 {skipped} 个。',glossary:'术语库',logout:'退出登录',
    staticModeNotice:'⚠️ 当前运行在静态托管环境。管理功能（上传、绑定、同步）已禁用。请在本地运行 server.py 获取完整管理权限。',
    staticUploadDisabled:'静态托管中无法上传。',
    staticDetachDisabled:'静态托管中无法解除绑定。',
    staticSyncDisabled:'静态托管中无法同步 YouTube。',
    cleanStale:'清理失效',
    cleanStaleConfirm:'确定要移除 {count} 个失效字幕映射吗？\n这些文件已不存在于磁盘上：\n\n{files}',
    cleanStaleDone:'已移除 {count} 个失效映射。',
    cleanStaleNone:'没有失效的映射。',
    batchConflictTooltip:'该语言已有字幕 — 将被替换',
    batchChangeLang:'点击修改识别语言'
  }
};
function t(key,vars){
  var str=(UI_TEXT[UI_LANG]&&UI_TEXT[UI_LANG][key])||UI_TEXT.en[key]||key;
  vars=vars||{};
  return str.replace(/\{(\w+)\}/g,function(_,k){return vars[k]!==undefined?vars[k]:''});
}
function setText(id,key){var el=document.getElementById(id);if(el)el.textContent=t(key);}
function setPlaceholder(id,key){var el=document.getElementById(id);if(el)el.placeholder=t(key);}
function applyUiText(){
  setText('pageTitle','pageTitle');setText('openAppLink','openApp');setPlaceholder('tableSearch','searchVideos');
  setText('openUploadBtn','uploadSrt');setText('openBatchBtn','batchImport');setText('scanBtn','scan');setText('syncBtn','syncYoutube');setText('standardizeBtn','standardizeNames');setText('cleanStaleBtn','cleanStale');setText('glossaryBtn','glossary');setText('logoutBtn','logout');
  setText('scannerTitle','scannerTitle');setText('titleTh','title');setText('durationTh','duration');setText('publishedTh','published');setText('subtitlesTh','subtitles');
  setText('sortDefault','sortDefault');setText('sortTitle','sortTitle');setText('sortDuration','sortDuration');setText('sortPublished','sortPublished');
  setText('uploadTitle','uploadTitle');setText('uploadFileLabel','selectSrt');setText('dropText','dropText');
  setText('uploadLangLabel','language');setText('uploadVideoLabel','assignVideo');setText('cancelUploadBtn','cancel');setText('uploadBtn','upload');
  setText('batchTitle','batchTitle');setText('batchHelp','batchHelp');setText('batchDropText','batchDropText');setText('batchDropHint','batchDropHint');
  setText('fileNameTh','filename');setText('languageTh','language');setText('subtitleCountTh','subtitleCount');setText('matchedVideoTh','matchedVideo');setText('similarityTh','similarity');
  setText('cancelBatchBtn','cancel');setText('batchImportBtn','importAll');
}

// ===== Load =====
function loadData(){
  Promise.all([api('GET','/api/mapping'),api('GET','/api/glossary'),api('GET','/api/admin/session')]).then(function(res){
    mapping=res[0];allVideos=mapping.videos;glossary=res[1]||{terms:[]};
    var session=res[2]||{};
    document.getElementById('adminAlias').textContent=session.localAuth?'Local admin':(session.alias?('Admin: '+session.alias):'');
    if(session.localAuth)document.getElementById('logoutBtn').style.display='none';
    renderGlossary();
    finishLoadData();
  }).catch(function(){
    // API unavailable — try static JSON (Cloudflare Pages fallback)
    fetch('mapping.json?t='+Date.now()).then(function(r){
      if(!r.ok)throw Error('HTTP '+r.status);
      return r.json();
    }).then(function(d){
      mapping=d;allVideos=d.videos;
      apiAvailable=false;
      applyStaticMode();
      finishLoadData();
    }).catch(function(e){toast(t('loadFailed',{message:e.message}),'error')});
  });
}
function finishLoadData(){
  renderTable();
  document.getElementById('statsBar').textContent=t('stats',{
    videos:allVideos.length,
    withSubs:allVideos.filter(function(v){return Object.keys(v.subtitles||{}).length>0}).length
  });
}

function applyStaticMode(){
  // Show banner
  document.getElementById('staticBanner').style.display='flex';
  document.getElementById('staticBannerText').textContent=t('staticModeNotice');
  // Hide management buttons
  document.getElementById('openUploadBtn').style.display='none';
  document.getElementById('openBatchBtn').style.display='none';
  document.getElementById('scanBtn').style.display='none';
  document.getElementById('syncBtn').style.display='none';
  document.getElementById('standardizeBtn').style.display='none';
  document.getElementById('cleanStaleBtn').style.display='none';
  // Re-render table without +/- controls
  renderTable();
}

// ===== Render Table =====
var langLabels={ko:'한국어',en:'English',ja:'日本語',zh:'中文'};
var langOrder=['ko','en','ja','zh'];
var currentSort='default',sortAsc=true;

function formatDate(ts){
  if(!ts)return'-';
  var d=new Date(ts);
  if(isNaN(d.getTime()))return'-';
  return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
}

function sortVideos(videos){
  if(currentSort==='default')return videos;
  var sorted=videos.slice();
  if(currentSort==='title'){
    sorted.sort(function(a,b){return a.title.localeCompare(b.title,'ko')});
  }else if(currentSort==='duration'){
    sorted.sort(function(a,b){return(a.duration||0)-(b.duration||0)});
  }else if(currentSort==='published'){
    sorted.sort(function(a,b){return(a.publishedAt||'').localeCompare(b.publishedAt||'')});
  }
  if(!sortAsc)sorted.reverse();
  return sorted;
}

function updateSortHeaders(){
  var headers=document.querySelectorAll('.video-table th.sortable');
  for(var i=0;i<headers.length;i++){
    var th=headers[i],key=th.dataset.sort;
    th.classList.toggle('sorted',key===currentSort);
    var arrow=th.querySelector('.sort-arrow');
    if(arrow)arrow.textContent=key===currentSort?(sortAsc?' ▲':' ▼'):'';
  }
}

function renderTable(filter){
  var tbody=document.getElementById('videoTableBody');
  var videos=allVideos;
  if(filter){
    var q=filter.toLowerCase();
    videos=videos.filter(function(v){return v.title.toLowerCase().indexOf(q)>=0||v.videoId.toLowerCase().indexOf(q)>=0});
  }
  videos=sortVideos(videos);
  updateSortHeaders();
  var html='';
  for(var i=0;i<videos.length;i++){
    var v=videos[i],subs=v.subtitles||{};
    html+='<tr>';
    html+='<td>'+(i+1)+'</td>';
    html+='<td class="vid">'+esc(v.videoId)+'</td>';
    html+='<td class="title-cell" title="'+esc(v.title)+'">'+esc(v.title)+'</td>';
    html+='<td class="dur">'+(v.duration?formatDuration(v.duration):'-')+'</td>';
    html+='<td class="pub">'+formatDate(v.publishedAt)+'</td>';
    html+='<td class="source-cell">'+renderSourceInputs(v)+'</td>';
    html+='<td><div class="lang-slots">';
    for(var j=0;j<langOrder.length;j++){
      var lang=langOrder[j],fn=subs[lang];
      html+='<div class="lang-slot '+lang+(fn?' assigned':'')+'" data-vid="'+v.videoId+'" data-lang="'+lang+'">';
      html+='<span style="font-weight:600;font-size:10px">'+lang.toUpperCase()+'</span>';
      if(fn){
        html+='<span class="fn" title="'+esc(fn)+'">'+esc(fn)+'</span>';
        if(apiAvailable){
          html+='<button class="detach" title="'+t('unassignTitle')+'" onclick="detachSrt(\''+v.videoId+'\',\''+lang+'\')">x</button>';
        }
      }else{
        if(apiAvailable){
          html+='<button class="upload-btn" title="'+t('uploadAssignTitle')+'" onclick="openUploadFor(\''+v.videoId+'\',\''+lang+'\')">+</button>';
        }
      }
      html+='</div>';
    }
    html+='</div></td>';
    html+='</tr>';
  }
  tbody.innerHTML=html||'<tr><td colspan="7" style="text-align:center;color:var(--text-dim);padding:40px">'+t('noRows')+'</td></tr>';
}

function renderSourceInputs(video){
  var yt=video.youtubeUrl||video.videoUrl||'';
  var bili=video.bilibiliUrl||(video.sources&&video.sources.bilibili&&(video.sources.bilibili.url||video.sources.bilibili.videoUrl))||'';
  var offset=video.bilibiliSubtitleOffset;
  if(offset===undefined&&video.sources&&video.sources.bilibili)offset=video.sources.bilibili.subtitleOffset;
  offset=offset===undefined||offset===null?'':offset;
  var disabled=apiAvailable?'':' disabled';
  return '<div class="source-inputs">'+
    '<label><span>YT</span><input type="url" value="'+esc(yt)+'"'+disabled+' data-vid="'+esc(video.videoId)+'" data-source="youtube" onchange="saveVideoSource(this)" onkeydown="sourceInputKey(event,this)" placeholder="YouTube URL"></label>'+
    '<label><span>BI</span><input type="url" value="'+esc(bili)+'"'+disabled+' data-vid="'+esc(video.videoId)+'" data-source="bilibili" onchange="saveVideoSource(this)" onkeydown="sourceInputKey(event,this)" placeholder="Bilibili URL"></label>'+
    '<label><span>OFF</span><input type="number" step="0.1" value="'+esc(String(offset))+'"'+disabled+' data-vid="'+esc(video.videoId)+'" data-source="bilibiliOffset" onchange="saveVideoSource(this)" onkeydown="sourceInputKey(event,this)" placeholder="+/- seconds"></label>'+
  '</div>';
}

function sourceInputKey(event,input){
  if(event.key==='Enter'){event.preventDefault();saveVideoSource(input)}
}

function saveVideoSource(input){
  if(!apiAvailable)return;
  var videoId=input.dataset.vid,source=input.dataset.source,value=input.value.trim();
  var video=allVideos.find(function(v){return v.videoId===videoId});
  if(!video)return;
  if(source==='youtube'){
    video.videoUrl=value;
    video.youtubeUrl=value;
  }else if(source==='bilibili'){
    video.bilibiliUrl=value;
    video.sources=video.sources||{};
    video.sources.bilibili=video.sources.bilibili||{};
    video.sources.bilibili.url=value;
  }else if(source==='bilibiliOffset'){
    var offset=value===''?0:parseFloat(value);
    if(!isFinite(offset)){toast(t('failed',{message:'Invalid offset'}),'error');return;}
    video.bilibiliSubtitleOffset=offset;
    video.sources=video.sources||{};
    video.sources.bilibili=video.sources.bilibili||{};
    video.sources.bilibili.subtitleOffset=offset;
  }
  clearTimeout(sourceSaveTimers[videoId+source]);
  sourceSaveTimers[videoId+source]=setTimeout(function(){
    api('POST','/api/mapping',mapping).then(function(){toast('Source saved','success')})
      .catch(function(e){toast(t('failed',{message:e.message}),'error')});
  },250);
}

// ===== Upload =====
function openUploadModal(){openUploadFor('','');}
function openUploadFor(videoId,lang){
  document.getElementById('uploadModal').classList.add('show');
  document.getElementById('uploadLang').value=lang||'ko';
  uploadFileData=null;uploadFileName=null;
  document.getElementById('fileInfo').textContent='';
  document.getElementById('uploadBtn').disabled=true;
  document.getElementById('uploadFile').value='';
  // Populate video select
  var sel=document.getElementById('uploadVideo');
  sel.innerHTML='<option value="">'+t('none')+'</option>';
  for(var i=0;i<allVideos.length;i++){
    var v=allVideos[i],selAttr=v.videoId===videoId?' selected':'';
    sel.innerHTML+='<option value="'+v.videoId+'"'+selAttr+'>'+esc(v.title.substring(0,80))+'</option>';
  }
}
function closeUploadModal(){document.getElementById('uploadModal').classList.remove('show')}

function onFileSelected(input){
  var file=input.files[0];
  if(!file)return;
  uploadFileData=file;uploadFileName=file.name;
  // Detect language
  var name=file.name.toLowerCase();
  uploadDetectedLang='ko';
  if(detectLangFromName(name,'en'))uploadDetectedLang='en';
  else if(detectLangFromName(name,'ja'))uploadDetectedLang='ja';
  else if(detectLangFromName(name,'zh'))uploadDetectedLang='zh';
  document.getElementById('uploadLang').value=uploadDetectedLang;
  document.getElementById('fileInfo').textContent=file.name+' ('+formatSize(file.size)+')';
  document.getElementById('uploadBtn').disabled=false;
}

function detectLangFromName(name,lang){
  var aliases={
    en:['en','eng','english'],
    ja:['ja','jp','jpn','japanese'],
    zh:['zh','zh-cn','zh-tw','zh-hans','zh-hant','cn','chinese']
  }[lang]||[lang];
  var stem=name.replace(/\.srt$/,'').replace(/\.srt[._-]/,'.');
  var tokens=stem.split(/[^a-z0-9]+/).filter(function(t){return t});
  for(var i=0;i<aliases.length;i++){
    var alias=aliases[i],parts=alias.split(/[^a-z0-9]+/).filter(function(t){return t});
    if(tokens.indexOf(alias)>=0)return true;
    for(var j=0;j<=tokens.length-parts.length;j++){
      if(tokens.slice(j,j+parts.length).join('-')===parts.join('-'))return true;
    }
  }
  return false;
}

// Drag and drop
var dz=document.getElementById('dropZone');
dz.addEventListener('dragover',function(e){e.preventDefault();dz.classList.add('dragover')});
dz.addEventListener('dragleave',function(){dz.classList.remove('dragover')});
dz.addEventListener('drop',function(e){
  e.preventDefault();dz.classList.remove('dragover');
  var file=e.dataTransfer.files[0];
  if(file&&file.name.toLowerCase().endsWith('.srt')){
    var dt=new DataTransfer();dt.items.add(file);
    document.getElementById('uploadFile').files=dt.files;
    onFileSelected(document.getElementById('uploadFile'));
  }else{toast(t('srtOnly'),'error')}
});

function doUpload(overwrite){
  if(!uploadFileData){toast(t('selectFile'),'error');return}
  var lang=document.getElementById('uploadLang').value;
  var videoId=document.getElementById('uploadVideo').value;
  var form=new FormData();
  form.append('file',uploadFileData);
  form.append('lang',lang);
  if(videoId)form.append('videoId',videoId);
  if(overwrite)form.append('overwrite','1');

  document.getElementById('uploadBtn').disabled=true;
  document.getElementById('uploadBtn').textContent=t('uploading');

  api('POST','/api/upload',form).then(function(r){
    toast((r.assigned?t('uploadAssignDone',{filename:r.filename}):t('uploadDone',{filename:r.filename})),'success');
    closeUploadModal();
    loadData();
  }).catch(function(e){
    var info=e.details||{};
    if(info.requiresOverwrite&&confirm('已有 '+info.lang.toUpperCase()+' 字幕：\n'+info.existingFile+'\n\n是否覆盖？')){
      doUpload(true);
      return;
    }
    toast(t('uploadFailed',{message:e.message}),'error');
  }).finally(function(){
    document.getElementById('uploadBtn').disabled=false;
    document.getElementById('uploadBtn').textContent=t('upload');
  });
}

// ===== Detach =====
function detachSrt(videoId,lang){
  if(!confirm(t('confirmDetach',{lang:lang.toUpperCase()})))return;
  api('POST','/api/assign',{videoId:videoId,lang:lang,remove:true}).then(function(){
    toast(t('detached'),'success');loadData();
  }).catch(function(e){toast(t('failed',{message:e.message}),'error')});
}

// ===== Scanner =====
// ===== Batch Import =====
var batchFiles=[],batchResults=[];

function openBatchModal(){
  document.getElementById('batchModal').classList.add('show');
  batchFiles=[];batchResults=[];langOverrides={};
  document.getElementById('batchFiles').value='';
  document.getElementById('batchPreview').style.display='none';
  document.getElementById('batchImportBtn').disabled=true;
  document.getElementById('batchStatus').textContent='';
}
function closeBatchModal(){
  if(batchResults.length>0){
    var files=batchResults.map(function(r){return r.filename});
    api('POST','/api/srt/cleanup-batch',{files:files}).catch(function(){});
  }
  langOverrides={};
  document.getElementById('batchModal').classList.remove('show');
}

function onBatchFilesSelected(input){
  batchFiles=Array.from(input.files).filter(function(f){return f.name.toLowerCase().endsWith('.srt')});
  if(batchFiles.length===0){toast(t('batchNoFiles'),'error');return}

  document.getElementById('batchStatus').textContent=t('batchAnalyzing');
  document.getElementById('batchImportBtn').disabled=true;

  var form=new FormData();
  for(var i=0;i<batchFiles.length;i++)form.append('file_'+i,batchFiles[i]);

  api('POST','/api/upload-batch',form).then(function(r){
    batchResults=r.files;
    renderBatchPreview();
  }).catch(function(e){toast(t('uploadFailed',{message:e.message}),'error')});
}

function renderBatchPreview(){
  var tbody=document.getElementById('batchTableBody'),html='';
  var langLabels={ko:'한국어',en:'English',ja:'日本語',zh:'中文'};

  for(var i=0;i<batchResults.length;i++){
    var f=batchResults[i];
    var matchOk=f.matchScore>=0.7;
    var effectiveLang=langOverrides[f.filename]||f.detectedLang;

    // Check conflict: matched video already has this language
    var conflict=false;
    if(matchOk){
      var vid=allVideos.find(function(v){return v.videoId===f.suggestedVideoId});
      conflict=vid&&vid.subtitles&&vid.subtitles[effectiveLang];
    }

    html+='<tr style="border-bottom:1px solid var(--border)" data-fn="'+esc(f.filename)+'">';
    html+='<td style="padding:6px 8px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+esc(f.filename)+'">'+esc(f.filename)+'</td>';
    // Language dropdown
    html+='<td style="padding:4px 6px;text-align:center">';
    html+='<select class="batch-lang-select" onchange="onBatchLangChange(this)" title="'+t('batchChangeLang')+'">';
    for(var l=0;l<langOrder.length;l++){
      var sel=langOrder[l]===effectiveLang?' selected':'';
      html+='<option value="'+langOrder[l]+'"'+sel+'>'+(langLabels[langOrder[l]]||langOrder[l].toUpperCase())+'</option>';
    }
    html+='</select></td>';
    html+='<td style="padding:6px 8px;text-align:center">~'+f.subtitleCount+'</td>';
    html+='<td style="padding:6px 8px;font-size:11px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:'+(matchOk?'var(--green)':'var(--red)')+'" title="'+(f.suggestedTitle||'')+'">';
    html+=matchOk?esc((f.suggestedTitle||'').substring(0,50)):t('matchFailed');
    html+='</td>';
    html+='<td class="batch-score-cell" style="padding:6px 8px;text-align:center;font-weight:600;color:'+(matchOk?'var(--green)':'var(--red)')+'">'+Math.round(f.matchScore*100)+'%';
    if(conflict){
      html+=' <span class="batch-conflict-warn" style="font-size:9px;color:var(--orange);cursor:help" title="'+t('batchConflictTooltip')+'">⚠️</span>';
    }
    html+='</td>';
    html+='</tr>';
  }

  tbody.innerHTML=html;
  document.getElementById('batchPreview').style.display='block';

  var matched=batchResults.filter(function(f){return f.matchScore>=0.7}).length;
  document.getElementById('batchStatus').textContent=t('batchStatus',{files:batchResults.length,matched:matched});
  document.getElementById('batchImportBtn').disabled=false;
}

function onBatchLangChange(selectEl){
  var newLang=selectEl.value;
  var row=selectEl.closest('tr');
  var filename=row.getAttribute('data-fn');
  langOverrides[filename]=newLang;

  // Find matching batch result
  var f=batchResults.find(function(r){return r.filename===filename});
  if(!f||!f.suggestedVideoId||f.matchScore<0.7)return;

  // Update conflict indicator for this row only
  var vid=allVideos.find(function(v){return v.videoId===f.suggestedVideoId});
  var conflict=vid&&vid.subtitles&&vid.subtitles[newLang];
  var scoreCell=row.querySelector('.batch-score-cell');
  if(!scoreCell)return;

  // Remove existing conflict warning
  var existing=scoreCell.querySelector('.batch-conflict-warn');
  if(existing)existing.remove();

  if(conflict){
    var span=document.createElement('span');
    span.className='batch-conflict-warn';
    span.style.cssText='font-size:9px;color:var(--orange);cursor:help';
    span.title=t('batchConflictTooltip');
    span.textContent=' ⚠️';
    scoreCell.appendChild(span);
  }
}

function doBatchImport(){
  var assignments=[];
  for(var i=0;i<batchResults.length;i++){
    var f=batchResults[i];
    if(f.suggestedVideoId&&f.matchScore>=0.7){
      var assignedLang=langOverrides[f.filename]||f.detectedLang;
      assignments.push({videoId:f.suggestedVideoId,lang:assignedLang,filename:f.filename});
    }
  }

  if(assignments.length===0){toast(t('noAssignments'),'error');return}

  document.getElementById('batchImportBtn').disabled=true;
  document.getElementById('batchImportBtn').textContent=t('assigning');

  api('POST','/api/assign-batch',{assignments:assignments}).then(function(r){
    toast(t('assigned',{count:r.assigned}),'success');
    batchResults=[];closeBatchModal();loadData();
  }).catch(function(e){toast(t('failed',{message:e.message}),'error')})
  .finally(function(){
    document.getElementById('batchImportBtn').disabled=false;
    document.getElementById('batchImportBtn').textContent=t('importAll');
  });
}

// Batch drag-and-drop
var bdz=document.getElementById('batchDropZone');
bdz.addEventListener('dragover',function(e){e.preventDefault();bdz.classList.add('dragover')});
bdz.addEventListener('dragleave',function(){bdz.classList.remove('dragover')});
bdz.addEventListener('drop',function(e){
  e.preventDefault();bdz.classList.remove('dragover');
  var files=Array.from(e.dataTransfer.files).filter(function(f){return f.name.toLowerCase().endsWith('.srt')});
  if(files.length>0){
    var dt=new DataTransfer();files.forEach(function(f){dt.items.add(f)});
    document.getElementById('batchFiles').files=dt.files;
    onBatchFilesSelected(document.getElementById('batchFiles'));
  }else{toast(t('batchNoFiles'),'error')}
});

document.getElementById('batchModal').addEventListener('click',function(e){if(e.target===this)closeBatchModal()});

function scanSrts(){
  api('GET','/api/scan').then(function(r){
    var div=document.getElementById('scannerResults');
    var list=document.getElementById('unassignedList');
    if(r.unassigned.length===0&&r.suggestions.length===0){
      div.style.display='block';
      list.innerHTML='<p style="color:var(--text-dim)">'+t('allAssigned')+'</p>';
      return;
    }
    div.style.display='block';
    var html='';
    if(r.suggestions.length>0){
      html+='<p style="margin-bottom:8px;color:var(--text-dim)">'+t('suggestions',{count:r.suggestions.length})+'</p>';
      for(var i=0;i<r.suggestions.length;i++){
        var s=r.suggestions[i];
        html+='<div class="item">';
        html+='<span class="name">'+esc(s.filename)+' <span class="lang-badge" style="font-size:10px">'+s.lang.toUpperCase()+'</span></span>';
        html+='<span class="match">'+esc(s.suggestedTitle.substring(0,60))+' ('+Math.round(s.score*100)+'%)</span>';
        html+='<button class="btn btn-sm" onclick="quickAssign(\''+s.suggestedVideoId+'\',\''+s.lang+'\',\''+s.filename+'\')">'+t('assign')+'</button>';
        html+='</div>';
      }
    }
    if(r.unassigned.length>0){
      html+='<p style="margin:12px 0 8px;color:var(--text-dim)">'+t('noSuggestions')+'</p>';
      for(var i=0;i<r.unassigned.length;i++)html+='<div class="item"><span class="name">'+esc(r.unassigned[i])+'</span></div>';
    }
    list.innerHTML=html;
  }).catch(function(e){toast(t('scanningFailed',{message:e.message}),'error')});
}

function quickAssign(videoId,lang,filename){
  api('POST','/api/assign',{videoId:videoId,lang:lang,filename:filename}).then(function(){
    toast(t('assignedFile',{filename:filename}),'success');loadData();scanSrts();
  }).catch(function(e){toast(t('failed',{message:e.message}),'error')});
}

// ===== Sync =====
function runSync(event){
  var btn=event&&event.target?event.target:document.getElementById('syncBtn');
  btn.disabled=true;btn.textContent=t('syncing');
  api('POST','/api/sync').then(function(r){
    if(r.ok){
      var summary='Videos: '+r.totalVideos+' | Published: '+r.publishedAtPopulated+' | Missing: '+r.publishedAtMissing;
      document.getElementById('syncResult').style.display='block';
      document.getElementById('syncResult').textContent=summary;
      toast(t('syncDone')+' '+summary,'success');loadData();
    }
    else{toast(t('syncFailed',{message:(r.error||r.output)}),'error')}
  }).catch(function(e){toast(t('syncFailed',{message:e.message}),'error')})
  .finally(function(){btn.disabled=false;btn.textContent=t('syncYoutube')});
}

function standardizeSubtitles(){
  var btn=document.getElementById('standardizeBtn');
  btn.disabled=true;
  api('POST','/api/subtitles/standardize',{}).then(function(r){
    toast(t('standardized',{renamed:r.renamed,skipped:r.skipped}),'success');
    loadData();
  }).catch(function(e){toast(t('failed',{message:e.message}),'error')})
  .finally(function(){btn.disabled=false});
}

function cleanStaleMappings(){
  var btn=document.getElementById('cleanStaleBtn');
  btn.disabled=true;
  api('POST','/api/mapping/cleanup',{}).then(function(r){
    if(r.cleaned===0){
      toast(t('cleanStaleNone'),'success');
    }else{
      toast(t('cleanStaleDone',{count:r.cleaned}),'success');
      loadData();
    }
  }).catch(function(e){toast(t('failed',{message:e.message}),'error')})
  .finally(function(){btn.disabled=false});
}

function toggleGlossaryPanel(){
  var p=document.getElementById('glossaryPanel');
  p.style.display=p.style.display==='none'?'block':'none';
}
function aliasesToText(values){return (values||[]).join(', ')}
function textToAliases(text){return text.split(',').map(function(s){return s.trim()}).filter(function(s){return s})}
function renderGlossary(){
  var body=document.getElementById('glossaryBody');if(!body)return;
  var terms=(glossary&&glossary.terms)||[],html='';
  for(var i=0;i<terms.length;i++){
    var a=terms[i].aliases||{};
    html+='<tr data-i="'+i+'"><td><input value="'+esc(terms[i].label||'')+'"></td><td><input value="'+esc(aliasesToText(a.ko))+'"></td><td><input value="'+esc(aliasesToText(a.en))+'"></td><td><input value="'+esc(aliasesToText(a.ja))+'"></td><td><input value="'+esc(aliasesToText(a.zh))+'"></td><td><button class="btn btn-sm btn-danger" onclick="removeGlossaryRow('+i+')">x</button></td></tr>';
  }
  body.innerHTML=html;
}
function readGlossaryFromTable(){
  var rows=document.querySelectorAll('#glossaryBody tr'),terms=[];
  rows.forEach(function(row,i){
    var inputs=row.querySelectorAll('input'),label=inputs[0].value.trim();
    terms.push({id:label.toLowerCase().replace(/[^a-z0-9_-]+/g,'-')||('term-'+(i+1)),label:label,aliases:{ko:textToAliases(inputs[1].value),en:textToAliases(inputs[2].value),ja:textToAliases(inputs[3].value),zh:textToAliases(inputs[4].value)}});
  });
  return {terms:terms};
}
function addGlossaryRow(){
  glossary=readGlossaryFromTable();
  glossary.terms.push({id:'new-term',label:'',aliases:{ko:[],en:[],ja:[],zh:[]}});
  renderGlossary();
}
function removeGlossaryRow(i){
  glossary=readGlossaryFromTable();
  glossary.terms.splice(i,1);
  renderGlossary();
}
function saveGlossary(){
  glossary=readGlossaryFromTable();
  api('POST','/api/glossary',glossary).then(function(r){glossary=r.glossary;renderGlossary();toast('Glossary saved','success')})
    .catch(function(e){toast(t('failed',{message:e.message}),'error')});
}
function logoutAdmin(){api('POST','/api/admin/logout',{}).then(function(){location.href='/admin'}).catch(function(){location.href='/admin'})}

// ===== Helpers =====
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function formatDuration(s){if(!s||s<=0)return'';var h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=Math.floor(s%60);return h>0?h+':'+pad(m)+':'+pad(sec):m+':'+pad(sec)}
function pad(n){return n<10?'0'+n:''+n}
function formatSize(b){return b<1024?b+' B':b<1048576?(b/1024).toFixed(1)+' KB':(b/1048576).toFixed(1)+' MB'}

function toast(msg,type){
  var t=document.getElementById('toast');
  t.textContent=msg;t.className='toast '+(type||'success')+' show';
  clearTimeout(t._timeout);t._timeout=setTimeout(function(){t.classList.remove('show')},2500);
}

// ===== Events =====
document.getElementById('tableSearch').addEventListener('input',function(){renderTable(this.value)});
document.getElementById('uploadModal').addEventListener('click',function(e){if(e.target===this)closeUploadModal()});
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeUploadModal()});
// Sort select
document.getElementById('sortSelect').addEventListener('change',function(){
  currentSort=this.value;sortAsc=true;renderTable(document.getElementById('tableSearch').value);
});
// Sortable column headers
document.querySelectorAll('.video-table th.sortable').forEach(function(th){
  th.addEventListener('click',function(){
    var key=this.dataset.sort;
    if(currentSort===key){sortAsc=!sortAsc}else{currentSort=key;sortAsc=true}
    document.getElementById('sortSelect').value=currentSort;
    renderTable(document.getElementById('tableSearch').value);
  });
});

// ===== Init =====
applyUiText();
loadData();
