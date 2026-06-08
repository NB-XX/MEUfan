// ===== SRT Parser (client-side) =====
function parseSRT(text){
  var blocks=text.trim().split(/\n\s*\n/),subs=[];
  for(var i=0;i<blocks.length;i++){
    var lines=blocks[i].trim().split('\n');
    if(lines.length<2)continue;
    var m=lines[1].match(/(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})/);
    if(!m)continue;
    var start=parseInt(m[1])*3600+parseInt(m[2])*60+parseInt(m[3])+parseInt(m[4])/1000;
    var end=parseInt(m[5])*3600+parseInt(m[6])*60+parseInt(m[7])+parseInt(m[8])/1000;
    subs.push({start:Math.round(start*1000)/1000,end:Math.round(end*1000)/1000,text:lines.slice(2).join('\n').trim()});
  }
  return subs;
}

// ===== Global State =====
var videos=[];       // [{videoId,title,duration,subtitles:{"ko":[...],"en":[...]}}]
var searchIndex=[];  // [{v,s,lang,start,text}]
var glossary={terms:[]},glossaryAliasGroups=[];
var dataReady=false;
var currentQuery='',localSubtitleQuery='',currentVideoIdx=-1,currentSubIdx=-1,currentResults=[];
var currentLang='ko',bilingualMode=false,bilingualLang='en',currentSource='youtube';
var currentMode='search';
var adminSession={admin:false,alias:null},editingCue=null;
var player=null,playerReady=false,syncInterval=null,pendingPlay=null,floatingSubtitlesEnabled=true;
var bilibiliStartTime=0,bilibiliStartedAt=0,bilibiliPlaying=false;

// ===== DOM Ref =====
var searchInput=document.getElementById('searchInput');
var clearBtn=document.getElementById('clearBtn');
var resultCount=document.getElementById('resultCount');
var resultsList=document.getElementById('resultsList');
var emptyState=document.getElementById('emptyState');
var browseView=document.getElementById('browseView');
var searchWrap=document.getElementById('searchWrap');
var mainEl=document.querySelector('.main');
var sidebarToggle=document.getElementById('sidebarToggle');
var mobileResultsToggle=document.getElementById('mobileResultsToggle');
var playerContainer=document.getElementById('playerContainer');
var playerPlaceholder=document.getElementById('playerPlaceholder');
var youtubePlayerEl=document.getElementById('youtubePlayer');
var bilibiliPlayer=document.getElementById('bilibiliPlayer');
var floatingSubtitle=document.getElementById('floatingSubtitle');
var floatingSubtitleBtn=document.getElementById('floatingSubtitleBtn');
var playerFullscreenBtn=document.getElementById('playerFullscreenBtn');
var downloadSubBtn=document.getElementById('downloadSubBtn');
var editSubtitleBtn=document.getElementById('editSubtitleBtn');
var editModal=document.getElementById('editModal');
var editStart=document.getElementById('editStart');
var editEnd=document.getElementById('editEnd');
var editText=document.getElementById('editText');
var subtitleOverlay=document.getElementById('subtitleOverlay');
var loadingOverlay=document.getElementById('loadingOverlay');
var progressFill=document.getElementById('progressFill');
var loadingDetail=document.getElementById('loadingDetail');
var langSelect=document.getElementById('langSelect');
var bilingualToggle=document.getElementById('bilingualToggle');
var bilingualCheck=document.getElementById('bilingualCheck');
var bilingualLangSelect=document.getElementById('bilingualLangSelect');
var localSubtitleSearch=document.getElementById('localSubtitleSearch');
var sourceYoutubeBtn=document.getElementById('sourceYoutubeBtn');
var sourceBilibiliBtn=document.getElementById('sourceBilibiliBtn');

// ===== Language Config =====
var SUPPORTED_UI_LANGS=['ko','ja','zh','en'];
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
    app:'MEU SubSearch',search:'Search',browse:'Browse',searchPlaceholder:'Search subtitles...',
    reload:'Reload',bilingual:'Bilingual',empty:'Enter a keyword to search all subtitles.',
    playerEmpty:'Click a subtitle result to play the video here.',
    subsEmpty:'Subtitles will appear here.',noVideoSubs:'This video has no subtitle data.',
    noResults:'No results for "{query}"',results:'{count} results',newest:'Newest',title:'Title',
    withSubsOnly:'With subtitles only',allLanguages:'All languages',noVideos:'No videos match the filters.',
    loadingMapping:'Loading mapping.json...',loadingSubs:'Loading subtitles...',localSearch:'Search in this subtitle',
    noLocalResults:'No matching lines in this subtitle.',
    floatingSub:'CC',fullscreen:'Fullscreen',download:'Download',exitFullscreen:'Exit fullscreen'
  },
  ko:{
    app:'MEU 자막 검색',search:'검색',browse:'둘러보기',searchPlaceholder:'자막 검색...',
    reload:'새로고침',bilingual:'이중 자막',empty:'검색어를 입력하면 전체 자막에서 찾아드립니다.',
    playerEmpty:'검색 결과에서 자막을 클릭하면 영상이 여기에 재생됩니다.',
    subsEmpty:'자막이 여기에 표시됩니다.',noVideoSubs:'이 영상은 자막 데이터가 없습니다.',
    noResults:'"{query}"에 대한 검색 결과가 없습니다',results:'{count}개 결과',newest:'최신순',title:'제목순',
    withSubsOnly:'자막 있는 영상만',allLanguages:'모든 언어',noVideos:'조건에 맞는 영상이 없습니다.',
    loadingMapping:'mapping.json 로딩 중...',loadingSubs:'자막 로딩 중...',localSearch:'현재 자막에서 검색',
    noLocalResults:'현재 자막에서 일치하는 줄이 없습니다.',
    floatingSub:'자막',fullscreen:'전체화면',download:'다운로드',exitFullscreen:'전체화면 종료'
  },
  ja:{
    app:'MEU 字幕検索',search:'検索',browse:'一覧',searchPlaceholder:'字幕を検索...',
    reload:'再読み込み',bilingual:'二言語字幕',empty:'キーワードを入力すると、全字幕から検索します。',
    playerEmpty:'検索結果の字幕をクリックすると、ここで動画を再生します。',
    subsEmpty:'字幕はここに表示されます。',noVideoSubs:'この動画には字幕データがありません。',
    noResults:'「{query}」の検索結果はありません',results:'{count} 件',newest:'新しい順',title:'タイトル順',
    withSubsOnly:'字幕ありのみ',allLanguages:'すべての言語',noVideos:'条件に一致する動画がありません。',
    loadingMapping:'mapping.json を読み込み中...',loadingSubs:'字幕を読み込み中...',localSearch:'この字幕内を検索',
    noLocalResults:'この字幕内に一致する行がありません。',
    floatingSub:'字幕',fullscreen:'全画面',download:'ダウンロード',exitFullscreen:'全画面終了'
  },
  zh:{
    app:'MEU 字幕搜索',search:'搜索',browse:'浏览',searchPlaceholder:'搜索字幕...',
    reload:'刷新',bilingual:'双语字幕',empty:'输入关键词后，会在全部字幕中搜索。',
    playerEmpty:'点击搜索结果中的字幕后，视频会在这里播放。',
    subsEmpty:'字幕会显示在这里。',noVideoSubs:'这个视频没有字幕数据。',
    noResults:'没有找到"{query}"的结果',results:'{count} 条结果',newest:'最新',title:'标题',
    withSubsOnly:'仅显示有字幕的视频',allLanguages:'所有语言',noVideos:'没有符合条件的视频。',
    loadingMapping:'正在加载 mapping.json...',loadingSubs:'正在加载字幕...',localSearch:'在当前字幕中搜索',
    noLocalResults:'当前字幕里没有匹配的行。',
    floatingSub:'字幕',fullscreen:'全屏',download:'下载',exitFullscreen:'退出全屏'
  }
};
function t(key,vars){
  var str=(UI_TEXT[UI_LANG]&&UI_TEXT[UI_LANG][key])||UI_TEXT.en[key]||key;
  vars=vars||{};
  return str.replace(/\{(\w+)\}/g,function(_,k){return vars[k]!==undefined?vars[k]:''});
}
function setText(id,text){var el=document.getElementById(id);if(el)el.textContent=text;}
function setPlaceholder(id,text){var el=document.getElementById(id);if(el)el.placeholder=text;}
function applyUiText(){
  var logo=document.querySelector('.logo');if(logo)logo.textContent=t('app');
  setText('modeSearchBtn',t('search'));setText('modeBrowseBtn',t('browse'));
  setPlaceholder('searchInput',t('searchPlaceholder'));
  var reload=document.getElementById('btnReload');if(reload){reload.textContent=t('reload');reload.title=t('reload');}
  var bil=document.getElementById('bilingualToggle');if(bil){bil.childNodes[1].nodeValue=' '+t('bilingual');}
  var emptyP=emptyState&&emptyState.querySelector('p');if(emptyP)emptyP.textContent=t('empty');
  var playerP=playerPlaceholder&&playerPlaceholder.querySelector('p');if(playerP)playerP.textContent=t('playerEmpty');
  subtitleOverlay.innerHTML='<div class="no-subs-hint">🐾 '+t('subsEmpty')+'</div>';
  setPlaceholder('localSubtitleSearch',t('localSearch'));
  floatingSubtitleBtn.textContent=t('floatingSub');floatingSubtitleBtn.title=t('floatingSub');
  playerFullscreenBtn.textContent=t('fullscreen');playerFullscreenBtn.title=t('fullscreen');
  downloadSubBtn.textContent=t('download');downloadSubBtn.title=t('download');
  var browseSort=document.getElementById('browseSort');
  if(browseSort){browseSort.options[0].textContent=t('newest');browseSort.options[1].textContent=t('title');}
  setText('filterHasSubsLabel',t('withSubsOnly'));
  var filterLang=document.getElementById('filterLang');if(filterLang)filterLang.options[0].textContent=t('allLanguages');
}
var LANG_LABELS={ko:'한국어',en:'English',ja:'日本語',zh:'中文'};
var LANG_COLORS={ko:'var(--accent)',en:'var(--accent2)',ja:'var(--accent3)',zh:'#2ecc71'};
currentLang=SUPPORTED_UI_LANGS.indexOf(UI_LANG)>=0?UI_LANG:'en';
bilingualLang=currentLang==='en'?'ko':'en';

function subtitleFileUrl(filename){
  return './'+filename.split('/').map(encodeURIComponent).join('/');
}

function youtubeVideoId(video){
  return video&&(video.youtubeVideoId||video.videoId)||'';
}

function youtubeUrl(video){
  if(!video)return'';
  if(video.youtubeUrl)return video.youtubeUrl;
  if(video.videoUrl)return video.videoUrl;
  var id=youtubeVideoId(video);
  return id?'https://www.youtube.com/watch?v='+encodeURIComponent(id):'';
}

function bilibiliUrl(video){
  if(!video)return'';
  if(video.bilibiliUrl)return video.bilibiliUrl;
  if(video.bvid)return 'https://www.bilibili.com/video/'+video.bvid;
  if(video.sources&&video.sources.bilibili)return video.sources.bilibili.url||video.sources.bilibili.videoUrl||'';
  return '';
}

function bilibiliSubtitleOffset(video){
  if(!video)return 0;
  var value=video.bilibiliSubtitleOffset;
  if(value===undefined&&video.sources&&video.sources.bilibili)value=video.sources.bilibili.subtitleOffset;
  value=parseFloat(value);
  return isFinite(value)?value:0;
}

function currentSubtitleOffset(){
  var video=currentVideoIdx>=0?videos[currentVideoIdx]:null;
  return currentSource==='bilibili'?bilibiliSubtitleOffset(video):0;
}

function subtitleClockTime(playerTime){
  if(playerTime===undefined||playerTime===null)return playerTime;
  return playerTime-currentSubtitleOffset();
}

function displaySubtitleTime(srtTime){
  return srtTime+currentSubtitleOffset();
}

function getVideoSourceUrl(video,source){
  return source==='bilibili'?bilibiliUrl(video):youtubeUrl(video);
}

function hasVideoSource(video,source){
  return !!getVideoSourceUrl(video,source);
}

function parseBilibiliRef(url){
  url=(url||'').trim();
  var result={bvid:'',aid:'',page:1};
  if(!url)return result;
  var b=url.match(/(?:BV|bv)([0-9A-Za-z]+)/);
  if(b)result.bvid='BV'+b[1];
  var a=url.match(/(?:av|aid=)(\d+)/i);
  if(a)result.aid=a[1];
  var p=url.match(/[?&]p=(\d+)/);
  if(p)result.page=Math.max(1,parseInt(p[1])||1);
  return result;
}

function bilibiliEmbedUrl(video,startTime){
  var ref=parseBilibiliRef(bilibiliUrl(video));
  var params=['autoplay=1','high_quality=1','danmaku=0','page='+encodeURIComponent(ref.page||1)];
  if(ref.bvid)params.push('bvid='+encodeURIComponent(ref.bvid));
  else if(ref.aid)params.push('aid='+encodeURIComponent(ref.aid));
  else return '';
  if(startTime)params.push('t='+Math.floor(startTime));
  return 'https://player.bilibili.com/player.html?'+params.join('&');
}

function checkAdminSession(){
  return fetch('/api/admin/session',{credentials:'include'}).then(function(r){return r.ok?r.json():{admin:false}}).then(function(s){
    adminSession=s||{admin:false};
    if(editSubtitleBtn)editSubtitleBtn.classList.toggle('hidden',!adminSession.admin);
  }).catch(function(){adminSession={admin:false};if(editSubtitleBtn)editSubtitleBtn.classList.add('hidden')});
}

function fetchJson(url){
  return fetch(url).then(function(r){
    if(!r.ok)throw Error('HTTP '+r.status);
    return r.json();
  });
}

function loadPublicData(){
  var stamp='?t='+Date.now();
  return fetchJson('data/manifest.json'+stamp).then(function(manifest){
    return {
      mapping:{videos:manifest.videos||[]},
      glossary:manifest.glossary||{terms:[]}
    };
  }).catch(function(){
    return Promise.all([
      fetchJson('mapping.json'+stamp),
      fetch('/api/glossary'+stamp).then(function(r){return r.ok?r.json():{terms:[]}}).catch(function(){return{terms:[]}})
    ]).then(function(payload){
      return {mapping:payload[0],glossary:payload[1]||{terms:[]}};
    });
  });
}

// ===== Data Loading =====
function loadData(){
  dataReady=false;searchInput.disabled=true;
  loadingOverlay.style.display='flex';progressFill.style.width='0%';
  loadingDetail.textContent=t('loadingMapping');

  loadPublicData()
    .then(function(payload){
      var mapping=payload.mapping||{videos:[]};
      glossary=payload.glossary||{terms:[]};
      buildGlossaryAliasGroups();
      var vlist=mapping.videos;
      videos=new Array(vlist.length);

      // Count total SRT files to fetch
      var toFetch=[];
      for(var i=0;i<vlist.length;i++){
        var v=vlist[i];
        // Support both new (subtitles dict) and legacy (srtFile string) formats
        var subs=v.subtitles||{};
        if(!subs.ko&&!subs.en&&!subs.ja&&v.srtFile){
          subs={ko:v.srtFile}; // Legacy fallback
        }
        videos[i]=Object.assign({},v,{duration:v.duration||0,subtitles:{}});
        var langs=Object.keys(subs);
        for(var j=0;j<langs.length;j++){
          toFetch.push({vIdx:i,lang:langs[j],file:subs[langs[j]]});
        }
      }

      var total=toFetch.length,loaded=0;
      loadingDetail.textContent='0 / '+total+' files';

      if(total===0){finishLoading();return;}

      // Fetch all SRTs in parallel
      var promises=[];
      for(var i=0;i<toFetch.length;i++){
        (function(item){
          var p=fetch(subtitleFileUrl(item.file)+'?t='+Date.now())
            .then(function(r){if(!r.ok)throw Error('HTTP '+r.status);return r.text()})
            .then(function(txt){
              videos[item.vIdx].subtitles[item.lang]=parseSRT(txt);
              loaded++;
              progressFill.style.width=Math.round(loaded/total*100)+'%';
              loadingDetail.textContent=loaded+' / '+total+' files';
            })
            .catch(function(err){
              console.warn('Failed:',item.file,err);loaded++;
              progressFill.style.width=Math.round(loaded/total*100)+'%';
              loadingDetail.textContent=loaded+' / '+total+' files';
            });
          promises.push(p);
        })(toFetch[i]);
      }
      return Promise.all(promises);
    })
    .then(function(){finishLoading()})
    .catch(function(err){loadingDetail.textContent='Error: '+err.message;setTimeout(loadData,3000)});
}

function finishLoading(){
  // Build search index across ALL languages
  searchIndex=[];
  for(var vi=0;vi<videos.length;vi++){
    var langs=Object.keys(videos[vi].subtitles);
    for(var li=0;li<langs.length;li++){
      var lang=langs[li],subs=videos[vi].subtitles[lang];
      for(var si=0;si<subs.length;si++){
        searchIndex.push({v:vi,s:si,lang:lang,start:subs[si].start,text:subs[si].text});
      }
    }
  }

  // Count stats
  var withSubs=0,langCounts={};
  for(var i=0;i<videos.length;i++){
    var ls=Object.keys(videos[i].subtitles);
    if(ls.length>0)withSubs++;
    for(var j=0;j<ls.length;j++){langCounts[ls[j]]=(langCounts[ls[j]]||0)+1;}
  }
  console.log('MEU SubSearch: '+videos.length+' videos, '+withSubs+' with subs, '+searchIndex.length+' entries');
  console.log('Languages:',JSON.stringify(langCounts));

  // Update language selector
  populateLangSelects();

  dataReady=true;searchInput.disabled=false;searchInput.focus();
  loadingOverlay.style.display='none';
  showEmptyState();
}

function populateLangSelects(){
  // Collect available languages
  var avail={};
  for(var i=0;i<videos.length;i++){
    var ls=Object.keys(videos[i].subtitles);
    for(var j=0;j<ls.length;j++)avail[ls[j]]=true;
  }
  var langs=Object.keys(avail);
  if(!avail[currentLang]&&langs.length>0)currentLang=langs[0];
  if(!avail[bilingualLang]||bilingualLang===currentLang){
    bilingualLang=langs.filter(function(l){return l!==currentLang})[0]||currentLang;
  }

  // Primary language select
  langSelect.innerHTML='';
  for(var i=0;i<langs.length;i++){
    var opt=document.createElement('option');
    opt.value=langs[i];opt.textContent=LANG_LABELS[langs[i]]||langs[i];
    if(langs[i]===currentLang)opt.selected=true;
    langSelect.appendChild(opt);
  }

  // Bilingual secondary language select
  bilingualLangSelect.innerHTML='';
  for(var i=0;i<langs.length;i++){
    if(langs[i]===currentLang)continue;
    var opt=document.createElement('option');
    opt.value=langs[i];opt.textContent=LANG_LABELS[langs[i]]||langs[i];
    if(langs[i]===bilingualLang)opt.selected=true;
    bilingualLangSelect.appendChild(opt);
  }
  if(bilingualLangSelect.options.length===0){
    // All langs are ko, no bilingual possible
    bilingualToggle.style.display='none';
  }else{
    bilingualToggle.style.display='';
  }

  langSelect.value=currentLang;
  bilingualLangSelect.value=bilingualLang;
}

function setActivePlayerElement(source){
  if(youtubePlayerEl)youtubePlayerEl.classList.toggle('hidden',source!=='youtube');
  if(bilibiliPlayer)bilibiliPlayer.classList.toggle('hidden',source!=='bilibili');
}

function stopYoutubePlayback(){
  if(player&&playerReady){
    try{player.pauseVideo();}catch(e){}
  }
}

function stopBilibiliPlayback(){
  bilibiliPlaying=false;
  bilibiliStartTime=0;
  bilibiliStartedAt=0;
  if(bilibiliPlayer)bilibiliPlayer.removeAttribute('src');
}

function updateSourceControls(video){
  var hasYoutube=hasVideoSource(video,'youtube');
  var hasBilibili=hasVideoSource(video,'bilibili');
  if(sourceYoutubeBtn)sourceYoutubeBtn.disabled=!hasYoutube;
  if(sourceBilibiliBtn)sourceBilibiliBtn.disabled=!hasBilibili;
  if(video){
    if(currentSource==='bilibili'&&!hasBilibili)currentSource=hasYoutube?'youtube':'bilibili';
    if(currentSource==='youtube'&&!hasYoutube&&hasBilibili)currentSource='bilibili';
  }
  if(sourceYoutubeBtn)sourceYoutubeBtn.classList.toggle('active',currentSource==='youtube');
  if(sourceBilibiliBtn)sourceBilibiliBtn.classList.toggle('active',currentSource==='bilibili');
  setActivePlayerElement(currentSource);
}

function switchSource(source){
  var video=currentVideoIdx>=0?videos[currentVideoIdx]:null;
  var oldSource=currentSource;
  var oldPlayerTime=currentPlayerTime();
  if(source!==currentSource){
    if(video&&!hasVideoSource(video,source))return;
    currentSource=source;
    if(source==='youtube')stopBilibiliPlayback();
    else stopYoutubePlayback();
  }
  updateSourceControls(currentVideoIdx>=0?videos[currentVideoIdx]:null);
  if(currentVideoIdx>=0){
    var oldOffset=oldSource==='bilibili'?bilibiliSubtitleOffset(videos[currentVideoIdx]):0;
    var rawTime=(oldPlayerTime||0)-oldOffset;
    var t=rawTime+currentSubtitleOffset();
    loadCurrentVideoAt(t,true);
    updateFloatingSubtitle(t);
  }
}

function playBilibiliAt(video,startTime){
  var url=bilibiliEmbedUrl(video,startTime);
  if(!url)return false;
  if(bilibiliPlayer)bilibiliPlayer.src=url;
  bilibiliStartTime=startTime||0;
  bilibiliStartedAt=Date.now();
  bilibiliPlaying=true;
  startSync();
  return true;
}

function playYoutubeAt(video,startTime){
  var id=youtubeVideoId(video);
  if(!id)return false;
  if(!player||!playerReady)return false;
  try{
    var vd=player.getVideoData?player.getVideoData():null;
    if(vd&&vd.video_id===id){player.seekTo(startTime,true);player.playVideo();}
    else player.loadVideoById({videoId:id,startSeconds:startTime,suggestedQuality:'default'});
  }catch(e){player.loadVideoById({videoId:id,startSeconds:startTime,suggestedQuality:'default'});}
  return true;
}

function loadCurrentVideoAt(startTime,autoplay){
  var video=currentVideoIdx>=0?videos[currentVideoIdx]:null;
  if(!video)return false;
  updateSourceControls(video);
  playerPlaceholder.style.display='none';
  if(currentSource==='bilibili'){
    stopYoutubePlayback();
    return playBilibiliAt(video,startTime||0);
  }
  stopBilibiliPlayback();
  if(!player||!playerReady){
    if(autoplay)pendingPlay={vIdx:currentVideoIdx,sIdx:currentSubIdx,startTime:startTime||0,lang:currentLang};
    return false;
  }
  return playYoutubeAt(video,startTime||0);
}

// ===== YouTube IFrame API =====
var tag=document.createElement('script');
tag.src='https://www.youtube.com/iframe_api';
document.getElementsByTagName('script')[0].parentNode.insertBefore(tag,document.getElementsByTagName('script')[0]);
window.onYouTubeIframeAPIReady=function(){
  player=new YT.Player('youtubePlayer',{
    height:'100%',width:'100%',videoId:'',
    playerVars:{autoplay:0,controls:1,rel:0,modestbranding:1},
    events:{onReady:onPlayerReady,onStateChange:onPlayerStateChange}
  });
};
function onPlayerReady(){
  playerReady=true;
  if(pendingPlay&&currentSource==='youtube'){var p=pendingPlay;pendingPlay=null;playAt(p.vIdx,p.sIdx,p.startTime,p.lang);}
}
function onPlayerStateChange(e){if(e.data===YT.PlayerState.PLAYING)startSync();else stopSync();}

// ===== Subtitle Sync =====
function startSync(){stopSync();syncInterval=setInterval(syncSubtitle,250);}
function stopSync(){if(syncInterval){clearInterval(syncInterval);syncInterval=null;}}

function syncSubtitle(){
  if(currentVideoIdx<0)return;
  try{
    var ct=currentPlayerTime();
    if(ct===null||ct===undefined)return;
    var st=subtitleClockTime(ct);
    var subs=videos[currentVideoIdx].subtitles[currentLang];
    if(!subs||subs.length===0){updateFloatingSubtitle(ct);return;}
    var active=activeSubtitlesAt(subs,st);
    var nextIdx=active.length?active[0].idx:-1;
    if(nextIdx!==currentSubIdx){currentSubIdx=nextIdx;highlightCurrentSubtitle();scrollToCurrentSubtitle();}
    updateFloatingSubtitle(ct);
  }catch(e){}
}

function highlightCurrentSubtitle(){
  var lines=subtitleOverlay.querySelectorAll('.sub-line');
  for(var i=0;i<lines.length;i++)lines[i].classList.toggle('current',parseInt(lines[i].dataset.idx)===currentSubIdx&&lines[i].dataset.lang===currentLang);
  var items=resultsList.querySelectorAll('.sub-item');
  for(var i=0;i<items.length;i++){
    var v=parseInt(items[i].dataset.v),s=parseInt(items[i].dataset.s);
    items[i].classList.toggle('active',v===currentVideoIdx&&s===currentSubIdx);
  }
}

function scrollResultsToCurrent(){
  if(currentVideoIdx<0||currentSubIdx<0||currentResults.length===0)return;
  var items=resultsList.querySelectorAll('.sub-item');
  for(var i=0;i<items.length;i++){
    var v=parseInt(items[i].dataset.v),s=parseInt(items[i].dataset.s);
    if(v===currentVideoIdx&&s===currentSubIdx){
      items[i].scrollIntoView({block:'center',behavior:'smooth'});
      var group=items[i].closest('.video-group');
      if(group&&!group.classList.contains('expanded'))group.classList.add('expanded');
      return;
    }
  }
  var groups=resultsList.querySelectorAll('.video-group');
  for(var j=0;j<groups.length;j++){
    if(parseInt(groups[j].dataset.v)===currentVideoIdx){
      groups[j].querySelector('.video-group-header').scrollIntoView({block:'center',behavior:'smooth'});
      return;
    }
  }
}

function scrollToCurrentSubtitle(){
  if(currentSubIdx<0)return;
  var line=subtitleOverlay.querySelector('.sub-line.current');
  if(line)line.scrollIntoView({block:'center',behavior:'smooth'});
}

function updateFloatingSubtitle(currentTime){
  if(!floatingSubtitle||!floatingSubtitlesEnabled||currentVideoIdx<0){
    hideFloatingSubtitle();return;
  }
  var video=videos[currentVideoIdx],lines=[],st=subtitleClockTime(currentTime);
  if(!video){hideFloatingSubtitle();return;}

  var primary=activeSubtitlesAt(video.subtitles[currentLang]||[],st);
  for(var i=0;i<primary.length;i++)lines.push({text:primary[i].text,secondary:false});

  if(bilingualMode&&bilingualLang!==currentLang){
    var secondary=activeSubtitlesAt(video.subtitles[bilingualLang]||[],st);
    for(var j=0;j<secondary.length;j++)lines.push({text:secondary[j].text,secondary:true});
  }

  if(lines.length===0){hideFloatingSubtitle();return;}
  floatingSubtitle.innerHTML=lines.map(function(line){
    return '<div class="float-line '+(line.secondary?'secondary':'')+'">'+escHtml(line.text)+'</div>';
  }).join('');
  floatingSubtitle.classList.remove('hidden');
}

function hideFloatingSubtitle(){
  if(floatingSubtitle){floatingSubtitle.classList.add('hidden');floatingSubtitle.innerHTML='';}
}

function activeSubtitlesAt(subs,currentTime){
  if(!subs||subs.length===0||currentTime===undefined||currentTime===null)return [];
  var active=[];
  for(var i=0;i<subs.length;i++){
    if(subs[i].start>currentTime)break;
    if(subs[i].start<=currentTime&&currentTime<=subs[i].end){
      active.push({idx:i,text:subs[i].text,start:subs[i].start,end:subs[i].end});
    }
  }
  return active;
}

function applyClickedResultLanguage(vIdx,lang){
  var video=videos[vIdx];if(!video||!lang||!video.subtitles||!video.subtitles[lang])return;
  if(!video.subtitles[currentLang]){
    currentLang=lang;
  }else if(lang!==currentLang){
    bilingualLang=lang;
    if(Object.keys(video.subtitles||{}).length>1){
      bilingualMode=true;
      bilingualCheck.checked=true;
      bilingualToggle.classList.add('active');
      bilingualLangSelect.style.display='';
    }
  }
  normalizeVideoLanguageState(vIdx);
}

function activePrimaryIndexAt(vIdx,currentTime){
  var video=videos[vIdx];if(!video)return -1;
  var active=activeSubtitlesAt(video.subtitles[currentLang]||[],currentTime);
  return active.length?active[0].idx:-1;
}

// ===== Search =====
function normalizeSearchText(text){return (text||'').toString().toLowerCase().replace(/[‐-―_-]+/g,' ').replace(/\s+/g,' ').trim()}
function compactSearchText(text){return normalizeSearchText(text).replace(/\s+/g,'')}
function buildGlossaryAliasGroups(){
  glossaryAliasGroups=[];
  var terms=(glossary&&glossary.terms)||[];
  for(var i=0;i<terms.length;i++){
    var aliases=[],a=terms[i].aliases||{};
    if(terms[i].label)aliases.push(terms[i].label);
    var langs=Object.keys(a);
    for(var l=0;l<langs.length;l++)for(var j=0;j<(a[langs[l]]||[]).length;j++)aliases.push(a[langs[l]][j]);
    var seen={},clean=[];
    for(var k=0;k<aliases.length;k++){var val=(aliases[k]||'').toString().trim();if(val&&!seen[val.toLowerCase()]){seen[val.toLowerCase()]=true;clean.push(val)}}
    if(clean.length)glossaryAliasGroups.push(clean);
  }
}
function expandedTermGroups(terms){return terms.map(function(term){
  var norm=normalizeSearchText(term),compact=compactSearchText(term),matches=[];
  for(var i=0;i<glossaryAliasGroups.length;i++){
    var group=glossaryAliasGroups[i];
    for(var j=0;j<group.length;j++){
      if(normalizeSearchText(group[j])===norm||compactSearchText(group[j])===compact){matches=group.slice();break;}
    }
    if(matches.length)break;
  }
  if(!matches.length)matches=[term];
  return matches;
})}
function textHasAlias(text,alias){
  var normText=normalizeSearchText(text),normAlias=normalizeSearchText(alias);
  if(!normAlias)return false;
  return normText.indexOf(normAlias)>=0||compactSearchText(text).indexOf(compactSearchText(alias))>=0;
}
function matchesExpandedGroups(text,groups){
  if(!groups||groups.length===0)return true;
  for(var i=0;i<groups.length;i++){
    var ok=false;
    for(var j=0;j<groups[i].length;j++){if(textHasAlias(text,groups[i][j])){ok=true;break}}
    if(!ok)return false;
  }
  return true;
}

function doSearch(query){
  if(!dataReady)return;
  query=query.trim();currentQuery=query;
  if(!query){showEmptyState();clearBtn.classList.remove('visible');resultCount.textContent='';return;}
  setMobileResultsCollapsed(false);
  clearBtn.classList.add('visible');
  var results=[],terms=query.split(/\s+/).filter(function(t){return t.length>0}),groups=expandedTermGroups(terms);
  for(var i=0;i<searchIndex.length;i++)if(matchesExpandedGroups(searchIndex[i].text,groups))results.push(searchIndex[i]);
  currentResults=results;
  renderResults(results,groups);
}

function renderResults(results,terms){
  if(results.length===0){
    emptyState.style.display='flex';resultsList.style.display='none';
    emptyState.querySelector('.icon').textContent='🐾';
    emptyState.querySelector('p').textContent=t('noResults',{query:currentQuery});
    resultCount.textContent=t('results',{count:'0'});return;
  }
  emptyState.style.display='none';resultsList.style.display='block';
  resultCount.textContent=t('results',{count:results.length.toLocaleString()});

  var groups={};
  for(var i=0;i<results.length;i++){
    var v=results[i].v;if(!groups[v])groups[v]=[];groups[v].push(results[i]);
  }
  var sorted=Object.entries(groups).sort(function(a,b){return b[1].length-a[1].length});
  var html='';
  for(var gi=0;gi<sorted.length;gi++){
    var vIdx=parseInt(sorted[gi][0]),entries=sorted[gi][1],video=videos[vIdx];
    var thumb='https://i.ytimg.com/vi/'+video.videoId+'/hqdefault.jpg';
    var show=Math.min(entries.length,30),more=entries.length>30;
    html+='<div class="video-group expanded" data-v="'+vIdx+'">';
    html+='<div class="video-group-header" onclick="event.stopPropagation();toggleGroup(this.parentElement)">';
    html+='<img class="thumb" src="'+thumb+'" loading="lazy" onerror="this.style.display=\'none\'" onclick="event.stopPropagation();loadVideoSubtitles('+vIdx+')" title="Load subtitles">';
    html+='<span class="vtitle" onclick="event.stopPropagation();loadVideoSubtitles('+vIdx+')" title="Load subtitles">'+escHtml(video.title)+'</span>';
    html+='<span class="vcount">'+entries.length+'</span>';
    html+='<span class="expand-icon">▼</span></div><div class="sub-items">';
    for(var i=0;i<show;i++)html+=renderSubItem(entries[i],terms);
    if(more)html+='<div class="sub-item" style="color:var(--text-dim);cursor:default">... and '+(entries.length-show)+' more</div>';
    html+='</div></div>';
  }
  resultsList.innerHTML=html;
}

function renderSubItem(entry,terms){
  return '<div class="sub-item" data-v="'+entry.v+'" data-s="'+entry.s+'" data-lang="'+entry.lang+'" onclick="playAt('+entry.v+','+entry.s+','+entry.start+',\''+entry.lang+'\')">'+
    '<span class="sub-time">'+formatTime(entry.start)+'</span>'+
    '<span class="lang-badge '+entry.lang+'">'+entry.lang.toUpperCase()+'</span>'+
    '<span class="sub-text">'+highlightTerms(entry.text,terms)+'</span></div>';
}

// ===== Video Playback =====
function playAt(vIdx,sIdx,startTime,lang){
  var video=videos[vIdx];if(!video)return;
  applyClickedResultLanguage(vIdx,lang);
  currentVideoIdx=vIdx;
  var playerStartTime=displaySubtitleTime(startTime);
  currentSubIdx=activePrimaryIndexAt(vIdx,startTime);
  localSubtitleSearch.value=localSubtitleQuery;

  if(currentSource==='youtube'&&(!player||!playerReady)){
    pendingPlay={vIdx:vIdx,sIdx:sIdx,startTime:startTime,lang:lang};
  }
  loadCurrentVideoAt(playerStartTime,true);
  playerPlaceholder.style.display='none';
  renderSubtitles(vIdx);
  setMobileResultsCollapsed(true);
  setTimeout(function(){highlightCurrentSubtitle();scrollToCurrentSubtitle();scrollResultsToCurrent();updateFloatingSubtitle(playerStartTime);},400);
  updateVideoInfo(video);
}

function loadVideoSubtitles(vIdx,lang){
  var video=videos[vIdx];if(!video)return;
  if(lang)currentLang=lang;
  currentVideoIdx=vIdx;currentSubIdx=-1;
  localSubtitleQuery='';
  localSubtitleSearch.value='';
  loadCurrentVideoAt(0,true);
  playerPlaceholder.style.display='none';
  renderSubtitles(vIdx);
  hideFloatingSubtitle();
  setMobileResultsCollapsed(true);
  updateVideoInfo(video);
}

function renderSubtitles(vIdx){
  normalizeVideoLanguageState(vIdx);
  var subs=videos[vIdx].subtitles[currentLang];
  if(!subs||subs.length===0){
    // Try to find any available language
    var avail=Object.keys(videos[vIdx].subtitles);
    if(avail.length>0){currentLang=avail[0];normalizeVideoLanguageState(vIdx);subs=videos[vIdx].subtitles[currentLang];}
    else{subtitleOverlay.innerHTML='<div class="no-subs-hint">'+t('noVideoSubs')+'</div>';return;}
  }

  if(bilingualMode){
    renderBilingualSubtitles(vIdx);return;
  }

  var globalTerms=currentQuery?expandedTermGroups(currentQuery.split(/\s+/).filter(function(t){return t.length>0})):[];
  var localTerms=localSubtitleTerms();
  var terms=globalTerms.concat(localTerms);
  var html='';
  var shown=0;
  for(var i=0;i<subs.length;i++){
    if(!matchesTerms(subs[i].text,localTerms))continue;
    var txt=terms.length>0?highlightTerms(subs[i].text,terms):escHtml(subs[i].text);
    html+='<div class="sub-line '+currentLang+'" data-idx="'+i+'" data-lang="'+currentLang+'" onclick="seekSubtitle('+i+')"><span class="stime">'+formatTime(displaySubtitleTime(subs[i].start))+'</span>'+txt+'</div>';
    shown++;
  }
  subtitleOverlay.innerHTML=shown?html:'<div class="no-subs-hint">'+t('noLocalResults')+'</div>';
  subtitleOverlay.scrollTop=0;
}

function renderBilingualSubtitles(vIdx){
  normalizeVideoLanguageState(vIdx);
  var primary=videos[vIdx].subtitles[currentLang]||[];
  var secondary=videos[vIdx].subtitles[bilingualLang]||[];
  if(secondary.length===0){
    var old=bilingualMode;bilingualMode=false;renderSubtitles(vIdx);bilingualMode=old;return;
  }

  // Merge and interleave by start time
  var merged=[];
  for(var i=0;i<primary.length;i++)merged.push({lang:currentLang,idx:i,start:primary[i].start,text:primary[i].text});
  for(var i=0;i<secondary.length;i++)merged.push({lang:bilingualLang,idx:i,start:secondary[i].start,text:secondary[i].text});
  merged.sort(function(a,b){return a.start-b.start});

  var globalTerms=currentQuery?expandedTermGroups(currentQuery.split(/\s+/).filter(function(t){return t.length>0})):[];
  var localTerms=localSubtitleTerms();
  var terms=globalTerms.concat(localTerms);
  var html='';
  var shown=0;
  for(var i=0;i<merged.length;i++){
    var e=merged[i],txt=terms.length>0?highlightTerms(e.text,terms):escHtml(e.text);
    if(!matchesTerms(e.text,localTerms))continue;
    html+='<div class="sub-line '+e.lang+'" data-idx="'+e.idx+'" data-lang="'+e.lang+'" data-start="'+e.start+'" onclick="seekSubtitleInLang(\''+e.lang+'\','+e.idx+')">'+
      '<span class="stime">'+formatTime(displaySubtitleTime(e.start))+'</span>'+
      '<span class="lang-badge '+e.lang+'">'+e.lang.toUpperCase()+'</span>'+txt+'</div>';
    shown++;
  }
  subtitleOverlay.innerHTML=shown?html:'<div class="no-subs-hint">'+t('noLocalResults')+'</div>';
  subtitleOverlay.scrollTop=0;
}

function normalizeVideoLanguageState(vIdx){
  var video=videos[vIdx];if(!video)return;
  var avail=Object.keys(video.subtitles||{});
  if(avail.length===0)return;
  if(avail.indexOf(currentLang)<0)currentLang=avail[0];
  if(avail.length>1&&(avail.indexOf(bilingualLang)<0||bilingualLang===currentLang)){
    bilingualLang=avail.filter(function(l){return l!==currentLang})[0]||bilingualLang;
  }
  if(avail.length<2){
    bilingualMode=false;
    bilingualCheck.checked=false;
    bilingualToggle.classList.remove('active');
    bilingualLangSelect.style.display='none';
  }
  rebuildPrimaryLangOptions(avail);
  langSelect.value=currentLang;
  rebuildBilingualLangOptions(avail);
}

function rebuildPrimaryLangOptions(avail){
  langSelect.innerHTML='';
  for(var i=0;i<avail.length;i++){
    var opt=document.createElement('option');
    opt.value=avail[i];opt.textContent=LANG_LABELS[avail[i]]||avail[i];
    if(avail[i]===currentLang)opt.selected=true;
    langSelect.appendChild(opt);
  }
}

function rebuildBilingualLangOptions(avail){
  bilingualLangSelect.innerHTML='';
  for(var i=0;i<avail.length;i++){
    if(avail[i]===currentLang)continue;
    var opt=document.createElement('option');
    opt.value=avail[i];opt.textContent=LANG_LABELS[avail[i]]||avail[i];
    if(avail[i]===bilingualLang)opt.selected=true;
    bilingualLangSelect.appendChild(opt);
  }
  bilingualToggle.style.display=avail.length>1?'':'none';
  bilingualLangSelect.value=bilingualLang;
}

function seekSubtitle(idx){
  if(currentVideoIdx<0)return;
  var subs=videos[currentVideoIdx].subtitles[currentLang];
  if(idx>=0&&idx<subs.length){currentSubIdx=idx;var t=displaySubtitleTime(subs[idx].start);loadCurrentVideoAt(t,true);highlightCurrentSubtitle();updateFloatingSubtitle(t);}
}

function seekSubtitleInLang(lang,idx){
  if(currentVideoIdx<0)return;
  var subs=videos[currentVideoIdx].subtitles[lang];
  if(idx>=0&&subs&&idx<subs.length){
    applyClickedResultLanguage(currentVideoIdx,lang);
    var t=displaySubtitleTime(subs[idx].start);
    currentSubIdx=activePrimaryIndexAt(currentVideoIdx,subtitleClockTime(t));
    loadCurrentVideoAt(t,true);
    highlightCurrentSubtitle();
    updateFloatingSubtitle(t);
  }
}

function openSubtitleEditor(){
  if(!adminSession.admin||currentVideoIdx<0)return;
  var subs=videos[currentVideoIdx].subtitles[currentLang]||[];
  var idx=currentSubIdx;
  if((idx<0||idx>=subs.length)&&player&&playerReady)idx=activePrimaryIndexAt(currentVideoIdx,currentPlayerTime()||0);
  if(idx<0||idx>=subs.length){alert('No current subtitle cue to edit.');return;}
  editingCue={videoId:videos[currentVideoIdx].videoId,lang:currentLang,index:idx};
  editStart.value=subs[idx].start;editEnd.value=subs[idx].end;editText.value=subs[idx].text;
  editModal.classList.add('visible');editText.focus();
}
function closeSubtitleEditor(){editingCue=null;editModal.classList.remove('visible')}
function saveSubtitleEdit(){
  if(!editingCue)return;
  var body={videoId:editingCue.videoId,lang:editingCue.lang,index:editingCue.index,start:parseFloat(editStart.value),end:parseFloat(editEnd.value),text:editText.value};
  fetch('/api/subtitle/save',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json().then(function(j){if(!r.ok||!j.ok)throw new Error(j.error||'Save failed');return j})})
    .then(function(j){
      videos[currentVideoIdx].subtitles[editingCue.lang]=j.subtitles;
      currentSubIdx=editingCue.index;
      closeSubtitleEditor();renderSubtitles(currentVideoIdx);highlightCurrentSubtitle();updateFloatingSubtitle(currentPlayerTime());
    })
    .catch(function(e){alert(e.message)});
}

function updateVideoInfo(video){
  var bar=document.getElementById('videoInfoBar'),thumb=document.getElementById('videoInfoThumb'),title=document.getElementById('videoInfoTitle');
  if(video){
    bar.classList.add('visible');
    localSubtitleSearch.classList.remove('hidden');
    editSubtitleBtn.classList.toggle('hidden',!adminSession.admin);
    var ytId=youtubeVideoId(video);
    thumb.src=video.thumbnailUrl||(ytId?('https://i.ytimg.com/vi/'+ytId+'/hqdefault.jpg'):'');
    title.textContent=video.title;
    updateSourceControls(video);
  }
  else{
    bar.classList.remove('visible');
    localSubtitleSearch.classList.add('hidden');
    editSubtitleBtn.classList.add('hidden');
    updateSourceControls(null);
  }
}

// ===== Browse Mode =====
function renderBrowseView(){
  var sortBy=document.getElementById('browseSort').value;
  var filterSubs=document.getElementById('filterHasSubs').checked;
  var filterLang=document.getElementById('filterLang').value;

  var filtered=[];
  for(var i=0;i<videos.length;i++){
    var v=videos[i],hasSubs=Object.keys(v.subtitles).length>0;
    if(filterSubs&&!hasSubs)continue;
    if(filterLang&&!v.subtitles[filterLang])continue;
    filtered.push({idx:i,video:v});
  }

  if(sortBy==='newest')filtered.reverse(); // playlist is newest-first, reverse for oldest-first... wait, playlist is newest first
  else if(sortBy==='title')filtered.sort(function(a,b){return a.video.title.localeCompare(b.video.title,'ko')});

  var grid=document.getElementById('videoGrid'),html='';
  for(var i=0;i<filtered.length;i++){
    var item=filtered[i],v=item.video;
    var ytId=youtubeVideoId(v);
    var thumb=v.thumbnailUrl||(ytId?('https://i.ytimg.com/vi/'+ytId+'/hqdefault.jpg'):'');
    var durStr=formatDuration(v.duration);
    var badges='',langs=Object.keys(v.subtitles);
    for(var j=0;j<langs.length;j++)badges+='<span class="lang-badge '+langs[j]+'">'+langs[j].toUpperCase()+'</span>';

    html+='<div class="video-card" onclick="loadVideoSubtitles('+item.idx+')">'+
      '<img class="card-thumb" src="'+thumb+'" loading="lazy" onerror="this.style.background=\'var(--surface2)\'">'+
      '<div class="card-body">'+
        '<div class="card-title">'+escHtml(v.title)+'</div>'+
        '<div class="card-meta">'+(durStr?'<span>⏱ '+durStr+'</span>':'')+'<span>'+badges+'</span></div>'+
      '</div></div>';
  }
  grid.innerHTML=html||'<div class="empty-state" style="grid-column:1/-1"><p>'+t('noVideos')+'</p></div>';
}

function switchMode(mode){
  currentMode=mode;
  document.getElementById('modeSearchBtn').classList.toggle('active',mode==='search');
  document.getElementById('modeBrowseBtn').classList.toggle('active',mode==='browse');
  if(mode==='search'){
    setMobileResultsCollapsed(false);
    searchWrap.classList.remove('inactive');resultsList.style.display=currentQuery?'block':'none';
    emptyState.style.display=currentQuery?'none':'flex';browseView.style.display='none';
  }else{
    setMobileResultsCollapsed(false);
    searchWrap.classList.add('inactive');resultsList.style.display='none';emptyState.style.display='none';
    browseView.style.display='flex';renderBrowseView();
  }
}

// ===== Helpers =====
function toggleGroup(el){el.classList.toggle('expanded')}
function escHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

function highlightTerms(text,terms){
  if(!terms||terms.length===0)return escHtml(text);
  var aliases=[];
  for(var i=0;i<terms.length;i++){
    if(Array.isArray(terms[i]))aliases=aliases.concat(terms[i]);
    else aliases.push(terms[i]);
  }
  aliases=aliases.filter(function(t){return t&&String(t).trim()}).sort(function(a,b){return String(b).length-String(a).length});
  if(!aliases.length)return escHtml(text);
  var e=[];for(var j=0;j<aliases.length;j++)e.push(String(aliases[j]).replace(/[.*+?^${}()|[\]\\]/g,'\\$&'));
  var re=new RegExp('('+e.join('|')+')','gi'),r='',li=0,m;
  while((m=re.exec(text))!==null){r+=escHtml(text.slice(li,m.index))+'<mark>'+escHtml(m[0])+'</mark>';li=re.lastIndex}
  return r+escHtml(text.slice(li));
}

function localSubtitleTerms(){
  var raw=localSubtitleQuery.trim().split(/\s+/).filter(function(t){return t.length>0});
  return expandedTermGroups(raw);
}

function matchesTerms(text,terms){
  return matchesExpandedGroups(text,terms);
}

function formatTime(s){
  var h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=Math.floor(s%60);
  return h>0?h+':'+pad(m)+':'+pad(sec):m+':'+pad(sec);
}
function formatDuration(s){if(!s||s<=0)return'';return formatTime(s)}
function pad(n){return n<10?'0'+n:''+n}

function showEmptyState(){
  currentResults=[];emptyState.style.display='flex';resultsList.style.display='none';
  emptyState.querySelector('.icon').textContent='这里是一片荒芜';
  emptyState.querySelector('p').textContent=t('empty');
  resultCount.textContent='';
}

function isMobileViewport(){
  return window.matchMedia('(max-width: 768px), (max-width: 900px) and (orientation: landscape) and (max-height: 520px)').matches;
}

function setMobileResultsCollapsed(collapsed){
  if(!mainEl)return;
  if(!isMobileViewport())collapsed=false;
  mainEl.classList.toggle('results-collapsed',!!collapsed);
  updateMobileResultsToggle();
}

function setSidebarCollapsed(collapsed){
  if(!mainEl||isMobileViewport())collapsed=false;
  mainEl.classList.toggle('sidebar-collapsed',!!collapsed);
  if(sidebarToggle)sidebarToggle.textContent=collapsed?'›':'‹';
  try{localStorage.setItem('meufanSidebarCollapsed',collapsed?'1':'0')}catch(e){}
}

function initSidebarCollapse(){
  var collapsed=false;
  try{collapsed=localStorage.getItem('meufanSidebarCollapsed')==='1'}catch(e){}
  setSidebarCollapsed(collapsed);
}

function updateMobileResultsToggle(){
  if(!mainEl||!mobileResultsToggle)return;
  mobileResultsToggle.textContent=mainEl.classList.contains('results-collapsed')?'Show results':'Hide results';
}

function currentPlayerTime(){
  if(currentSource==='bilibili'){
    if(!bilibiliPlaying)return null;
    return bilibiliStartTime+(Date.now()-bilibiliStartedAt)/1000;
  }
  if(!player||!playerReady)return null;
  try{return player.getCurrentTime();}catch(e){return null;}
}

function toggleFloatingSubtitles(){
  floatingSubtitlesEnabled=!floatingSubtitlesEnabled;
  floatingSubtitleBtn.classList.toggle('active',floatingSubtitlesEnabled);
  floatingSubtitleBtn.textContent=t('floatingSub');
  if(floatingSubtitlesEnabled)updateFloatingSubtitle(currentPlayerTime());
  else hideFloatingSubtitle();
}

function togglePlayerFullscreen(){
  if(!playerContainer)return;
  var fullscreenElement=document.fullscreenElement||document.webkitFullscreenElement;
  if(fullscreenElement){
    if(document.exitFullscreen)document.exitFullscreen();
    else if(document.webkitExitFullscreen)document.webkitExitFullscreen();
  }else if(playerContainer.requestFullscreen){
    playerContainer.requestFullscreen();
  }else if(playerContainer.webkitRequestFullscreen){
    playerContainer.webkitRequestFullscreen();
  }
}

function updateFullscreenButton(){
  var fullscreenElement=document.fullscreenElement||document.webkitFullscreenElement;
  var active=fullscreenElement===playerContainer;
  if(playerFullscreenBtn)playerFullscreenBtn.classList.toggle('active',active);
  if(playerFullscreenBtn)playerFullscreenBtn.textContent=active?t('exitFullscreen'):t('fullscreen');
}

// ===== Download Subtitle =====
function sanitizeFilename(name){
  return name.replace(/[\/\\:*?"<>|]/g,'_').replace(/[\x00-\x1f]/g,'').replace(/\s+/g,' ').trim();
}
function downloadSubtitle(){
  if(currentVideoIdx<0)return;
  var video=videos[currentVideoIdx];
  var subs=video.subtitles[currentLang];
  if(!subs||subs.length===0){
    var avail=Object.keys(video.subtitles);
    if(avail.length===0){alert('No subtitle data available.');return;}
  }
  if(!subs||subs.length===0)subs=video.subtitles[Object.keys(video.subtitles)[0]];
  if(!subs||subs.length===0)return;

  var srt='';
  for(var i=0;i<subs.length;i++){
    var s=subs[i];
    srt+=(i+1)+'\n';
    srt+=secondsToSRTTime(s.start)+' --> '+secondsToSRTTime(s.end)+'\n';
    srt+=s.text+'\n\n';
  }

  var lang=currentLang;
  if(!video.subtitles[lang]||video.subtitles[lang].length===0){
    lang=Object.keys(video.subtitles)[0];
  }
  var safeTitle=sanitizeFilename(video.title);
  if(safeTitle.length>120)safeTitle=safeTitle.substring(0,120);
  var filename='['+lang+'/'+video.videoId+']'+safeTitle+'.srt';

  var blob=new Blob([srt],{type:'text/plain;charset=utf-8'});
  var url=URL.createObjectURL(blob);
  var a=document.createElement('a');
  a.href=url;a.download=filename;document.body.appendChild(a);
  a.click();document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
function secondsToSRTTime(sec){
  var h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=Math.floor(sec%60),ms=Math.round((sec%1)*1000);
  return pad2(h)+':'+pad2(m)+':'+pad2(s)+','+pad3(ms);
}
function pad2(n){return n<10?'0'+n:''+n}
function pad3(n){return n<100?'0'+pad2(n):''+n}

// ===== Events =====
var debounce=null;
searchInput.addEventListener('input',function(){clearTimeout(debounce);debounce=setTimeout(function(){doSearch(searchInput.value)},200)});
searchInput.addEventListener('keydown',function(e){if(e.key==='Escape'){searchInput.value='';doSearch('');searchInput.blur()}});
clearBtn.addEventListener('click',function(){searchInput.value='';doSearch('');searchInput.focus()});
document.addEventListener('keydown',function(e){if((e.ctrlKey||e.metaKey)&&e.key==='k'){e.preventDefault();searchInput.focus();searchInput.select()}});
if(sidebarToggle)sidebarToggle.addEventListener('click',function(){setSidebarCollapsed(!mainEl.classList.contains('sidebar-collapsed'))});
mobileResultsToggle.addEventListener('click',function(){
  if(!mainEl)return;
  setMobileResultsCollapsed(!mainEl.classList.contains('results-collapsed'));
});
window.addEventListener('resize',function(){setMobileResultsCollapsed(mainEl&&mainEl.classList.contains('results-collapsed'));setSidebarCollapsed(mainEl&&mainEl.classList.contains('sidebar-collapsed'))});
floatingSubtitleBtn.addEventListener('click',toggleFloatingSubtitles);
playerFullscreenBtn.addEventListener('click',togglePlayerFullscreen);
downloadSubBtn.addEventListener('click',downloadSubtitle);
editSubtitleBtn.addEventListener('click',openSubtitleEditor);
if(sourceYoutubeBtn)sourceYoutubeBtn.addEventListener('click',function(){switchSource('youtube')});
if(sourceBilibiliBtn)sourceBilibiliBtn.addEventListener('click',function(){switchSource('bilibili')});
document.getElementById('editCancelBtn').addEventListener('click',closeSubtitleEditor);
document.getElementById('editSaveBtn').addEventListener('click',saveSubtitleEdit);
editModal.addEventListener('click',function(e){if(e.target===editModal)closeSubtitleEditor()});
document.addEventListener('fullscreenchange',function(){updateFullscreenButton();updateFloatingSubtitle(currentPlayerTime());});
document.addEventListener('webkitfullscreenchange',function(){updateFullscreenButton();updateFloatingSubtitle(currentPlayerTime());});
localSubtitleSearch.addEventListener('input',function(){
  localSubtitleQuery=this.value;
  if(currentVideoIdx>=0)renderSubtitles(currentVideoIdx);
});

// Language events
langSelect.addEventListener('change',function(){
  currentLang=this.value;
  if(currentVideoIdx>=0)normalizeVideoLanguageState(currentVideoIdx);
  if(currentVideoIdx>=0)renderSubtitles(currentVideoIdx);
  updateFloatingSubtitle(currentPlayerTime());
});
bilingualToggle.addEventListener('click',function(e){
  e.preventDefault();
  if(currentVideoIdx>=0){
    normalizeVideoLanguageState(currentVideoIdx);
    if(bilingualLangSelect.options.length===0)return;
  }
  bilingualMode=!bilingualMode;bilingualCheck.checked=bilingualMode;
  bilingualToggle.classList.toggle('active',bilingualMode);
  bilingualLangSelect.style.display=bilingualMode?'':'none';
  if(currentVideoIdx>=0)renderSubtitles(currentVideoIdx);
  updateFloatingSubtitle(currentPlayerTime());
});
bilingualLangSelect.addEventListener('change',function(){bilingualLang=this.value;if(bilingualMode&&currentVideoIdx>=0)renderSubtitles(currentVideoIdx);updateFloatingSubtitle(currentPlayerTime())});

// Mode events
document.getElementById('modeSearchBtn').addEventListener('click',function(){switchMode('search')});
document.getElementById('modeBrowseBtn').addEventListener('click',function(){switchMode('browse')});

// Browse events
document.getElementById('browseSort').addEventListener('change',renderBrowseView);
document.getElementById('filterHasSubs').addEventListener('change',renderBrowseView);
document.getElementById('filterLang').addEventListener('change',renderBrowseView);

// Reload
document.getElementById('btnReload').addEventListener('click',function(){
  currentQuery='';currentVideoIdx=-1;currentSubIdx=-1;currentResults=[];
  localSubtitleQuery='';localSubtitleSearch.value='';localSubtitleSearch.classList.add('hidden');
  stopBilibiliPlayback();
  stopSync();
  hideFloatingSubtitle();
  searchInput.value='';resultCount.textContent='';
  emptyState.style.display='flex';resultsList.style.display='none';browseView.style.display='none';
  setMobileResultsCollapsed(false);
  subtitleOverlay.innerHTML='<div class="no-subs-hint">🐾 '+t('subsEmpty')+'</div>';
  document.getElementById('videoInfoBar').classList.remove('visible');
  playerPlaceholder.style.display='flex';clearBtn.classList.remove('visible');
  loadData();
});

// ===== Init =====
applyUiText();
updateSourceControls(null);
checkAdminSession();
initSidebarCollapse();
loadData();
