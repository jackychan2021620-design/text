/* Observe only public profile/post/detail responses already loaded by the page. */
(() => {
  if (window.__bookWorkbenchPublic) return;
  const videos=new Map(),profiles=new Map();let batches=0,lastResponse=0,hasMore=null;
  const publicEndpoint=u=>{try{const x=new URL(u,location.href);return /(^|\.)douyin\.com$/.test(x.hostname)&&/^\/aweme\/v\d+\/web\/(aweme\/(post|detail)|user\/profile\/other)(\/|$)/.test(x.pathname);}catch(_){return false;}};
  const author=x=>x&&({uid:x.uid,sec_uid:x.sec_uid||x.secUid,nickname:x.nickname});
  function cart(x,depth=0){
    if(!x||depth>6)return null;
    if(typeof x==='string'){try{return x.length<100000?cart(JSON.parse(x),depth+1):null;}catch(_){return null;}}
    if(Array.isArray(x))return x.slice(0,30).map(v=>cart(v,depth+1));
    if(typeof x!=='object')return null;
    const y={};for(const k of ['title','product_title','product_name','promotion_title','product_id','promotion_id','sku_id'])if(x[k]!=null)y[k]=x[k];
    for(const k of ['extra','product','product_info','products','promotion','promotions','goods','items','detail','info'])if(x[k])y[k]=cart(x[k],depth+1);
    return y;
  }
  function observe(value,profileResponse=false){
    const stack=[value];let visited=0;
    while(stack.length&&++visited<30000){
      const x=stack.pop();if(!x||typeof x!=='object')continue;
      if(Array.isArray(x)){stack.push(...x.slice(0,500));continue;}
      const id=x.aweme_id||x.awemeId;const a=x.author||x.authorInfo||(x.author_user_id?{uid:x.author_user_id}:null);
      if(id&&/^\d{5,30}$/.test(String(id))&&a){
        const previous=videos.get(String(id))||{};
        const v={...previous,aweme_id:String(id),author:author(a),desc:x.desc||x.description||previous.desc||'',
          create_time:x.create_time||x.createTime||x.publish_time||previous.create_time,
          statistics:{digg_count:(x.statistics||{}).digg_count??(x.statistics||{}).diggCount??null},
          is_top:!!(x.is_top||x.is_pinned),source_kind:'public_response'};
        for(const k of ['promotions','promotion','product_info','commerce_info','cart_products','anchor_info','anchors'])if(x[k])v[k]=cart(x[k]);
        videos.set(v.aweme_id,v);
      }
      const p=x.userInfo||x.user_info||(profileResponse&&x.user);
      if(p&&typeof p==='object'){const u=author(p.user||p),key=u&&(u.sec_uid||u.uid);if(key)profiles.set(String(key),{userInfo:{user:u}});}
      for(const v of Object.values(x))if(v&&typeof v==='object')stack.push(v);
    }
    if(videos.size>600){
      const stamp=v=>{let n=Number(v.create_time);if(!Number.isFinite(n))n=(Date.parse(v.create_time)||0)/1000;return n>1e11?n/1000:n;};
      const keep=[...videos.values()].sort((a,b)=>stamp(b)-stamp(a)).slice(0,600);videos.clear();for(const v of keep)videos.set(v.aweme_id,v);
    }
  }
  const receive=(url,body)=>{if(!publicEndpoint(url))return;try{observe(body,/user\/profile\/other/.test(url));lastResponse=Date.now();if(/aweme\/post/.test(url)){batches++;if(body&&body.has_more!=null)hasMore=!!body.has_more;}}catch(_){}};
  const originalFetch=window.fetch;
  if(originalFetch)window.fetch=function(...args){
    const url=String(args[0] instanceof Request?args[0].url:args[0]);const response=originalFetch.apply(this,args);
    if(publicEndpoint(url))response.then(r=>{if(Number(r.headers.get('content-length')||0)>4000000)return;r.clone().text().then(text=>{if(text.length<=4000000)receive(url,JSON.parse(text));}).catch(()=>{});}).catch(()=>{});
    return response;
  };
  const urls=new WeakMap(),open=XMLHttpRequest.prototype.open,send=XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open=function(method,url,...rest){urls.set(this,String(url));return open.call(this,method,url,...rest);};
  XMLHttpRequest.prototype.send=function(...args){const url=urls.get(this);if(publicEndpoint(url))this.addEventListener('load',()=>{try{if(this.responseType==='json')receive(url,this.response);else if((!this.responseType||this.responseType==='text')&&this.responseText.length<=4000000)receive(url,JSON.parse(this.responseText));}catch(_){}},{once:true});return send.apply(this,args);};
  function visible(el){return !!el&&el.getClientRects().length>0&&getComputedStyle(el).visibility!=='hidden';}
  function snapshot(){
    try{if(window._ROUTER_DATA)observe(window._ROUTER_DATA);}catch(_){}
    document.querySelectorAll('script#RENDER_DATA,script[type="application/json"]').forEach(s=>{try{if(s.textContent.length<4000000)observe(JSON.parse(s.id==='RENDER_DATA'?decodeURIComponent(s.textContent):s.textContent));}catch(_){}});
    const path=location.pathname.match(/\/user\/([^/?]+)/),owner=new URLSearchParams(location.search).get('sec_uid')||(path&&path[1]);
    const postRoot=document.querySelector('[data-e2e="user-post-list"],[data-e2e="user-post-list-content"]');
    if(owner&&postRoot)postRoot.querySelectorAll('a[href*="/video/"]').forEach(a=>{
      if(!visible(a))return;const match=a.href.match(/\/video\/(\d{5,30})/);if(!match)return;
      const card=a.closest('li,[data-e2e="user-post-item"]')||a;
      const like=card.querySelector('[data-e2e="video-like-count"],[data-e2e="like-count"],[data-e2e="user-post-item-like"],[aria-label*="点赞"]');
      const count=visible(like)?(like.getAttribute('aria-label')||like.innerText||'').replace(/点赞|次数|次|赞|[,，\s]/g,''):'';
      const desc=card.querySelector('[data-e2e="user-post-item-desc"]'),date=card.querySelector('time[datetime],[data-e2e*="publish-time"],[data-e2e*="create-time"]');
      const previous=videos.get(match[1]);
      if(!previous)videos.set(match[1],{aweme_id:match[1],author:{sec_uid:owner},desc:(desc&&desc.innerText||a.getAttribute('title')||a.innerText||'').slice(0,2000),create_time:date&&(date.getAttribute('datetime')||date.getAttribute('data-create-time')),
        statistics:{digg_count:/^\d+$/.test(count)?Number(count):null,digg_count_display:count},source_kind:'visible_post_card'});
    });
    const active=location.pathname.match(/\/(?:share\/)?video\/(\d{5,30})/),modal=new URLSearchParams(location.search).get('modal_id'),activeId=(active&&active[1])||modal;
    if(activeId&&videos.has(activeId)){
      const names=[...document.querySelectorAll('[data-e2e="product-title"],[data-e2e="product-name"],[data-e2e="cart-product-title"]')].filter(visible).map(x=>(x.innerText||x.getAttribute('title')||'').trim()).filter(Boolean);
      if(names.length)videos.get(activeId).cart_products=names.slice(0,20).map(title=>({product_title:title}));
    }
    const body=(document.body&&document.body.innerText||'').slice(0,20000);let blocker='';
    if(/请完成下方验证|拖动滑块|完成安全验证|请通过验证/.test(body))blocker='verification_required';
    else{const dialogs=[...document.querySelectorAll('[role="dialog"],[data-e2e*="login-dialog"],[class*="login-mask"],[class*="login-modal"]')].filter(visible).map(x=>x.innerText).join(' ');if(/扫码登录|登录后查看|请先登录/.test(dialogs)||(!postRoot&&/登录后查看|请先登录/.test(body)))blocker='login_required';}
    return {url:location.href,title:document.title,documents:[...profiles.values(),{aweme_list:[...videos.values()]}],blocker,ready:document.readyState,batches,lastResponse,hasMore};
  }
  function more(){const root=document.querySelector('[data-e2e="user-post-list"],[data-e2e="user-post-list-content"]');let el=root;while(el&&el!==document.body){if(el.scrollHeight>el.clientHeight+100&&/auto|scroll|overlay/.test(getComputedStyle(el).overflowY)){const before=el.scrollTop;el.scrollTop+=Math.max(600,el.clientHeight*.8);if(el.scrollTop!==before)return true;}el=el.parentElement;}window.scrollBy(0,Math.max(600,innerHeight*.8));return true;}
  window.__bookWorkbenchPublic={snapshot,loadMore:more};
})();
