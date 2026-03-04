class VisionCardReveal{constructor(){this.cards=document.querySelectorAll('.hcard');this._pendingTimers=[];if(this.cards.length===0)return;this.bindEvents();}
bindEvents(){document.addEventListener('section-revealed',(e)=>{const section=document.getElementById('vision');if(e.detail.index===1){if(section){section.classList.add('h2-grid-ready');}
this.animateContentIn();}else if(e.detail.index===2){this.animateContentIn();}else{this.resetPage2();}});}
spawnMeshBurst(card){const accent=card.dataset.accent;const colors={cyan:'rgba(140,145,160,',purple:'rgba(140,145,160,',mixed:'rgba(140,145,160,'};const base=colors[accent]||colors.cyan;const rect=card.getBoundingClientRect();const container=card.closest('.vision-content')||card.parentElement;const containerRect=container.getBoundingClientRect();const count=35;const gridSize=14;for(let n=0;n<count;n++){const sq=document.createElement('div');sq.className='mesh-burst-sq';const side=Math.random();let x,y;if(side<0.25){x=rect.left-containerRect.left-Math.random()*80;y=rect.top-containerRect.top+Math.random()*rect.height;}else if(side<0.5){x=rect.right-containerRect.left+Math.random()*80;y=rect.top-containerRect.top+Math.random()*rect.height;}else if(side<0.75){x=rect.left-containerRect.left+Math.random()*rect.width;y=rect.top-containerRect.top-Math.random()*60;}else{x=rect.left-containerRect.left+Math.random()*rect.width;y=rect.bottom-containerRect.top+Math.random()*60;}
x=Math.round(x/gridSize)*gridSize;y=Math.round(y/gridSize)*gridSize;const size=gridSize-2;const opacity=0.15+Math.random()*0.5;const delay=Math.random()*200;const duration=300+Math.random()*400;sq.style.cssText=`
                position: absolute;
                left: ${x}px;
                top: ${y}px;
                width: ${size}px;
                height: ${size}px;
                background: ${base}${opacity});
                border: 1px solid ${base}${opacity * 0.8});
                pointer-events: none;
                z-index: 3;
                opacity: 0;
                animation: mesh-sq-flash ${duration}ms ease-out ${delay}ms forwards;
            `;container.appendChild(sq);setTimeout(()=>sq.remove(),delay+duration+50);}}
_later(fn,ms){const id=setTimeout(()=>{const idx=this._pendingTimers.indexOf(id);if(idx!==-1)this._pendingTimers.splice(idx,1);fn();},ms);this._pendingTimers.push(id);}}
document.addEventListener('DOMContentLoaded',()=>{new VisionCardReveal();});
