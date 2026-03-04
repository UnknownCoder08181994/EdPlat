(function(){
var videos=document.querySelectorAll('video[data-lazy-video]');
if(!videos.length)return;
var loadQueue=[];
var loading=false;
function loadNext(){
if(loadQueue.length===0){loading=false;return;}
loading=true;
var v=loadQueue.shift();
var sources=v.querySelectorAll('source[data-src]');
sources.forEach(function(s){s.setAttribute('src',s.getAttribute('data-src'));s.removeAttribute('data-src');});
v.load();v.dataset.loaded='1';
v.addEventListener('canplay',function(){v.play().catch(function(){});loadNext();},{once:true});
setTimeout(loadNext,3000);
}
var observer=new IntersectionObserver(function(entries){
entries.forEach(function(entry){
var v=entry.target;
if(entry.isIntersecting){
if(!v.dataset.loaded){
loadQueue.push(v);
if(!loading)loadNext();
}else{
v.play().catch(function(){});
}
}else{
v.pause();
}
});
},{rootMargin:'200px',threshold:0});
videos.forEach(function(v){observer.observe(v);});
})();
