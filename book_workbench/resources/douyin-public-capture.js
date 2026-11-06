/* Observe only public profile/post/detail responses loaded by the normal page.
   No generated signatures, cookie export, private endpoints or login automation. */
(() => {
  if (window.__bookWorkbenchPublic) return;
  const videos = new Map(), profiles = new Map();
  const publicEndpoint = u => {
    try {
      const x = new URL(u, location.href);
      return /(^|\.)douyin\.com$/.test(x.hostname) && /^\/aweme\/v\d+\/web\/(aweme\/(post|detail)|user\/profile\/other)(\/|$)/.test(x.pathname);
    } catch (_) { return false; }
  };
  const author = x => x && ({uid:x.uid, sec_uid:x.sec_uid || x.secUid, nickname:x.nickname});
  const product = p => p && ({title:p.title, product_title:p.product_title, product_name:p.product_name});
  const list = x => Array.isArray(x) ? x.slice(0,30).map(product) : product(x);
  function observe(value, profileResponse=false) {
    const stack=[value];let visited=0;
    while (stack.length && ++visited < 30000) {
      const x=stack.pop();if (!x || typeof x !== 'object') continue;
      if (Array.isArray(x)) { stack.push(...x.slice(0,500));continue; }
      const id=x.aweme_id || x.awemeId;
      if (id && /^\d{5,30}$/.test(String(id)) && (x.author || x.authorInfo)) {
        const v={aweme_id:String(id),author:author(x.author || x.authorInfo),desc:x.desc || x.description || '',
          create_time:x.create_time || x.createTime,statistics:{digg_count:(x.statistics || {}).digg_count ?? (x.statistics || {}).diggCount},
          promotions:list(x.promotions),promotion:list(x.promotion),product_info:list(x.product_info)};
        videos.set(v.aweme_id,v);if (videos.size>500) videos.delete(videos.keys().next().value);
      }
      const p=x.userInfo || x.user_info || (profileResponse && x.user);
      if (p && typeof p==='object') {
        const u=author(p.user || p);const key=u && (u.sec_uid || u.uid);
        if (key) profiles.set(String(key),{userInfo:{user:u}});
      }
      for (const v of Object.values(x)) if (v && typeof v==='object') stack.push(v);
    }
  }
  const receive=(url,body) => {
    if (!publicEndpoint(url)) return;
    try { observe(body,/user\/profile\/other/.test(url)); } catch (_) {}
  };
  const originalFetch=window.fetch;
  if (originalFetch) window.fetch=function(...args) {
    const url=String(args[0] instanceof Request ? args[0].url : args[0]);
    const response=originalFetch.apply(this,args);
    if (publicEndpoint(url)) response.then(r=> {
      if (Number(r.headers.get('content-length') || 0)>4000000) return;
      r.clone().text().then(text=> { if (text.length<=4000000) receive(url,JSON.parse(text)); }).catch(()=>{});
    }).catch(()=>{});
    return response;
  };
  const urls=new WeakMap(), open=XMLHttpRequest.prototype.open, send=XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open=function(method,url,...rest) { urls.set(this,String(url));return open.call(this,method,url,...rest); };
  XMLHttpRequest.prototype.send=function(...args) {
    const url=urls.get(this);
    if (publicEndpoint(url)) this.addEventListener('load',()=> {
      try {
        if (this.responseType==='json') receive(url,this.response);
        else if ((!this.responseType || this.responseType==='text') && this.responseText.length<=4000000) receive(url,JSON.parse(this.responseText));
      } catch (_) {}
    },{once:true});
    return send.apply(this,args);
  };
  function visible(el) { return !!el && el.getClientRects().length>0 && getComputedStyle(el).visibility!=='hidden'; }
  function snapshot() {
    try { if (window._ROUTER_DATA) observe(window._ROUTER_DATA); } catch (_) {}
    document.querySelectorAll('script#RENDER_DATA,script[type="application/json"]').forEach(s=> {
      try { if (s.textContent.length<4000000) observe(JSON.parse(s.id==='RENDER_DATA' ? decodeURIComponent(s.textContent) : s.textContent)); } catch (_) {}
    });
    const path=location.pathname.match(/\/user\/([^/?]+)/);
    const owner=new URLSearchParams(location.search).get('sec_uid') || (path && path[1]);
    if (owner) document.querySelectorAll('a[href*="/video/"]').forEach(a=> {
      if (!visible(a)) return;
      const match=a.href.match(/\/video\/(\d{5,30})/);if (!match || videos.has(match[1])) return;
      const card=a.closest('li,[data-e2e="user-post-item"]') || a;
      const like=card.querySelector('[data-e2e="video-like-count"],[data-e2e="like-count"],[data-e2e="user-post-item-like"],[aria-label*="点赞"]');
      if (!visible(like)) return;
      const count=(like.getAttribute('aria-label') || like.innerText || '').replace(/点赞|次数|次|赞|[,，\s]/g,'');
      if (!/^\d+$/.test(count)) return; // Do not turn rounded/hidden counts into exact values.
      const desc=card.querySelector('[data-e2e="user-post-item-desc"]');
      videos.set(match[1],{aweme_id:match[1],author:{sec_uid:owner},desc:(desc && desc.innerText || a.getAttribute('title') || a.innerText || '').slice(0,2000),statistics:{digg_count:Number(count)}});
    });
    const body=(document.body && document.body.innerText || '').slice(0,20000);
    let blocker='';
    if (/请完成下方验证|拖动滑块|完成安全验证|请通过验证/.test(body)) blocker='verification_required';
    else {
      const dialogs=[...document.querySelectorAll('[role="dialog"],[data-e2e*="login-dialog"],[class*="login-mask"],[class*="login-modal"]')].filter(visible).map(x=>x.innerText).join(' ');
      const visibleWorks=[...document.querySelectorAll('a[href*="/video/"]')].some(visible);
      if (/扫码登录|登录后查看|请先登录/.test(dialogs) || (!visibleWorks && /登录后查看|请先登录/.test(body))) blocker='login_required';
    }
    return {url:location.href,title:document.title,documents:[...profiles.values(),{aweme_list:[...videos.values()]}],blocker,ready:document.readyState};
  }
  window.__bookWorkbenchPublic={snapshot};
})();
