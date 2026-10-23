window.SageTeamMode=true;
const nativeFetch=window.fetch.bind(window);let teamCsrf='';
window.teamReady=nativeFetch('/auth/me').then(async r=>{if(!r.ok){location.replace('/login');throw Error('登录已过期');}const me=await r.json();teamCsrf=me.csrf;if(!me.provider_ready){const n=document.createElement('div');n.className='provider-notice';n.textContent='已有成果可正常查看。启动新研究前，请管理员在“账号与模型设置”中配置 DeepSeek API 密钥。';document.querySelector('main').prepend(n);}return me;});
window.fetch=async (url,options={})=>{if((options.method||'GET').toUpperCase()!=='GET'){await window.teamReady;const headers=new Headers(options.headers||{});headers.set('X-CSRF-Token',teamCsrf);options={...options,headers};}return nativeFetch(url,options);};
document.getElementById('logout').onclick=async()=>{await window.teamReady;await fetch('/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});sessionStorage.clear();location.replace('/login');};
