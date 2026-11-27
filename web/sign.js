/* gotoquill sealed-link signing page. No build step, no external scripts. */
/* ---- vendored @noble/ciphers 2.0.1 AES-GCM (only `gcm`), https://github.com/paulmillr/noble-ciphers
   Bundled with esbuild (--bundle --minify --format=iife), see web/vendor/README.md. Fallback when crypto.subtle is missing.
   @license MIT
   The MIT License (MIT)

   Copyright (c) 2022 Paul Miller (https://paulmillr.com)
   Copyright (c) 2016 Thomas Pornin <pornin@bolet.org>

   Permission is hereby granted, free of charge, to any person obtaining a copy
   of this software and associated documentation files (the “Software”), to deal
   in the Software without restriction, including without limitation the rights
   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
   copies of the Software, and to permit persons to whom the Software is
   furnished to do so, subject to the following conditions:

   The above copyright notice and this permission notice shall be included in
   all copies or substantial portions of the Software.

   THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
   THE SOFTWARE.
   ---- */
(()=>{var P=(t,n,e)=>()=>{if(e)throw e[0];try{return t&&(n=t(t=0)),n}catch(o){throw e=[o],o}};var ft=(t,n)=>()=>{try{return n||t((n={exports:{}}).exports,n),n.exports}catch(e){throw n=0,e}};function lt(t){return t instanceof Uint8Array||ArrayBuffer.isView(t)&&t.constructor.name==="Uint8Array"}function ut(t){if(typeof t!="boolean")throw new Error(`boolean expected, not ${t}`)}function d(t,n,e=""){let o=lt(t),r=t?.length,c=n!==void 0;if(!o||c&&r!==n){let f=e&&`"${e}" `,i=c?` of length ${n}`:"",s=o?`length=${r}`:`type=${typeof t}`;throw new Error(f+"expected Uint8Array"+i+", got "+s)}return t}function C(t,n=!0){if(t.destroyed)throw new Error("Hash instance has been destroyed");if(n&&t.finished)throw new Error("Hash#digest() has already been called")}function V(t,n){d(t,void 0,"output");let e=n.outputLen;if(t.length<e)throw new Error("digestInto() expects output buffer of length at least "+e)}function Y(t){return new Uint8Array(t.buffer,t.byteOffset,t.byteLength)}function A(t){return new Uint32Array(t.buffer,t.byteOffset,Math.floor(t.byteLength/4))}function L(...t){for(let n=0;n<t.length;n++)t[n].fill(0)}function v(t){return new DataView(t.buffer,t.byteOffset,t.byteLength)}function q(t,n){if(t.length!==n.length)return!1;let e=0;for(let o=0;o<t.length;o++)e|=t[o]^n[o];return e===0}function G(t,n,e=!0){if(n===void 0)return new Uint8Array(t);if(n.length!==t)throw new Error('"output" expected Uint8Array of length '+t+", got: "+n.length);if(e&&!K(n))throw new Error("invalid output, must be aligned");return n}function J(t,n,e){ut(e);let o=new Uint8Array(16),r=v(o);return r.setBigUint64(0,BigInt(n),e),r.setBigUint64(8,BigInt(t),e),o}function K(t){return t.byteOffset%4===0}function B(t){return Uint8Array.from(t)}var ht,F,W=P(()=>{/*! noble-ciphers - MIT License (c) 2023 Paul Miller (paulmillr.com) */ht=new Uint8Array(new Uint32Array([287454020]).buffer)[0]===68;F=(t,n)=>{function e(o,...r){if(d(o,void 0,"key"),!ht)throw new Error("Non little-endian hardware is not yet supported");if(t.nonceLength!==void 0){let u=r[0];d(u,t.varSizeNonce?void 0:t.nonceLength,"nonce")}let c=t.tagLength;c&&r[1]!==void 0&&d(r[1],void 0,"AAD");let f=n(o,...r),i=(u,h)=>{if(h!==void 0){if(u!==2)throw new Error("cipher output not supported");d(h,void 0,"output")}},s=!1;return{encrypt(u,h){if(s)throw new Error("cannot encrypt() twice with same key + nonce");return s=!0,d(u),i(f.encrypt.length,h),f.encrypt(u,h)},decrypt(u,h){if(d(u),c&&u.length<c)throw new Error('"ciphertext" expected length bigger than tagLength='+c);return i(f.decrypt.length,h),f.decrypt(u,h)}}}return Object.assign(e,t),e}});function pt(t){t.reverse();let n=t[15]&1,e=0;for(let o=0;o<t.length;o++){let r=t[o];t[o]=r>>>1|e,e=(r&1)<<7}return t[0]^=-n&225,t}function Q(t){let n=(o,r)=>t(r,o.length).update(o).digest(),e=t(new Uint8Array(16),0);return n.outputLen=e.outputLen,n.blockLen=e.blockLen,n.create=(o,r)=>t(o,r),n}var S,H,U,at,gt,x,yt,I,j,D,wt,X=P(()=>{W();S=16,H=new Uint8Array(16),U=A(H),at=225,gt=(t,n,e,o)=>{let r=o&1;return{s3:e<<31|o>>>1,s2:n<<31|e>>>1,s1:t<<31|n>>>1,s0:t>>>1^at<<24&-(r&1)}},x=t=>(t>>>0&255)<<24|(t>>>8&255)<<16|(t>>>16&255)<<8|t>>>24&255|0;yt=t=>t>64*1024?8:t>1024?4:2,I=class{blockLen=S;outputLen=S;s0=0;s1=0;s2=0;s3=0;finished=!1;t;W;windowSize;constructor(n,e){d(n,16,"key"),n=B(n);let o=v(n),r=o.getUint32(0,!1),c=o.getUint32(4,!1),f=o.getUint32(8,!1),i=o.getUint32(12,!1),s=[];for(let p=0;p<128;p++)s.push({s0:x(r),s1:x(c),s2:x(f),s3:x(i)}),{s0:r,s1:c,s2:f,s3:i}=gt(r,c,f,i);let l=yt(e||1024);if(![1,2,4,8].includes(l))throw new Error("ghash: invalid window size, expected 2, 4 or 8");this.W=l;let h=128/l,g=this.windowSize=2**l,a=[];for(let p=0;p<h;p++)for(let w=0;w<g;w++){let b=0,m=0,y=0,T=0;for(let E=0;E<l;E++){if(!(w>>>l-E-1&1))continue;let{s0:M,s1:st,s2:ct,s3:it}=s[l*p+E];b^=M,m^=st,y^=ct,T^=it}a.push({s0:b,s1:m,s2:y,s3:T})}this.t=a}_updateBlock(n,e,o,r){n^=this.s0,e^=this.s1,o^=this.s2,r^=this.s3;let{W:c,t:f,windowSize:i}=this,s=0,l=0,u=0,h=0,g=(1<<c)-1,a=0;for(let p of[n,e,o,r])for(let w=0;w<4;w++){let b=p>>>8*w&255;for(let m=8/c-1;m>=0;m--){let y=b>>>c*m&g,{s0:T,s1:E,s2:_,s3:M}=f[a*i+y];s^=T,l^=E,u^=_,h^=M,a+=1}}this.s0=s,this.s1=l,this.s2=u,this.s3=h}update(n){C(this),d(n),n=B(n);let e=A(n),o=Math.floor(n.length/S),r=n.length%S;for(let c=0;c<o;c++)this._updateBlock(e[c*4+0],e[c*4+1],e[c*4+2],e[c*4+3]);return r&&(H.set(n.subarray(o*S)),this._updateBlock(U[0],U[1],U[2],U[3]),L(U)),this}destroy(){let{t:n}=this;for(let e of n)e.s0=0,e.s1=0,e.s2=0,e.s3=0}digestInto(n){C(this),V(n,this),this.finished=!0;let{s0:e,s1:o,s2:r,s3:c}=this,f=A(n);return f[0]=e,f[1]=o,f[2]=r,f[3]=c,n}digest(){let n=new Uint8Array(S);return this.digestInto(n),this.destroy(),n}},j=class extends I{constructor(n,e){d(n);let o=pt(B(n));super(o,e),L(o)}update(n){C(this),d(n),n=B(n);let e=A(n),o=n.length%S,r=Math.floor(n.length/S);for(let c=0;c<r;c++)this._updateBlock(x(e[c*4+3]),x(e[c*4+2]),x(e[c*4+1]),x(e[c*4+0]));return o&&(H.set(n.subarray(r*S)),this._updateBlock(x(U[3]),x(U[2]),x(U[1]),x(U[0])),L(U)),this}digestInto(n){C(this),V(n,this),this.finished=!0;let{s0:e,s1:o,s2:r,s3:c}=this,f=A(n);return f[0]=e,f[1]=o,f[2]=r,f[3]=c,n.reverse()}};D=Q((t,n)=>new I(t,n)),wt=Q((t,n)=>new j(t,n))});function xt(t){if(![16,24,32].includes(t.length))throw new Error('"aes key" expected Uint8Array of length 16/24/32, got length='+t.length)}function $(t){return t<<1^bt&-(t>>7)}function tt(t,n){let e=0;for(;n>0;n>>=1)e^=t&-(n&1),t=$(t);return e}function At(t,n){if(t.length!==256)throw new Error("Wrong sbox length");let e=new Uint32Array(256).map((l,u)=>n(t[u])),o=e.map(R),r=o.map(R),c=r.map(R),f=new Uint32Array(256*256),i=new Uint32Array(256*256),s=new Uint16Array(256*256);for(let l=0;l<256;l++)for(let u=0;u<256;u++){let h=l*256+u;f[h]=e[l]^o[u],i[h]=r[l]^c[u],s[h]=t[l]<<8|t[u]}return{sbox:t,sbox2:s,T0:e,T1:o,T2:r,T3:c,T01:f,T23:i}}function Ut(t){d(t);let n=t.length;xt(t);let{sbox2:e}=et,o=[];K(t)||o.push(t=B(t));let r=A(t),c=r.length,f=s=>O(e,s,s,s,s),i=new Uint32Array(n+28);i.set(r);for(let s=c;s<i.length;s++){let l=i[s-1];s%c===0?l=f(Et(l))^Lt[s/c-1]:c>6&&s%c===4&&(l=f(l)),i[s]=i[s-c]^l}return L(...o),i}function z(t,n,e,o,r,c){return t[e<<8&65280|o>>>8&255]^n[r>>>8&65280|c>>>24&255]}function O(t,n,e,o,r){return t[n&255|e&65280]|t[o>>>16&255|r>>>16&65280]<<16}function nt(t,n,e,o,r){let{sbox2:c,T01:f,T23:i}=et,s=0;n^=t[s++],e^=t[s++],o^=t[s++],r^=t[s++];let l=t.length/4-2;for(let p=0;p<l;p++){let w=t[s++]^z(f,i,n,e,o,r),b=t[s++]^z(f,i,e,o,r,n),m=t[s++]^z(f,i,o,r,n,e),y=t[s++]^z(f,i,r,n,e,o);n=w,e=b,o=m,r=y}let u=t[s++]^O(c,n,e,o,r),h=t[s++]^O(c,e,o,r,n),g=t[s++]^O(c,o,r,n,e),a=t[s++]^O(c,r,n,e,o);return{s0:u,s1:h,s2:g,s3:a}}function N(t,n,e,o,r){d(e,Z,"nonce"),d(o),r=G(o.length,r);let c=e,f=A(c),i=v(c),s=A(o),l=A(r),u=n?0:12,h=o.length,g=i.getUint32(u,n),{s0:a,s1:p,s2:w,s3:b}=nt(t,f[0],f[1],f[2],f[3]);for(let y=0;y+4<=s.length;y+=4)l[y+0]=s[y+0]^a,l[y+1]=s[y+1]^p,l[y+2]=s[y+2]^w,l[y+3]=s[y+3]^b,g=g+1>>>0,i.setUint32(u,g,n),{s0:a,s1:p,s2:w,s3:b}=nt(t,f[0],f[1],f[2],f[3]);let m=Z*Math.floor(s.length/dt);if(m<h){let y=new Uint32Array([a,p,w,b]),T=Y(y);for(let E=m,_=0;E<h;E++,_++)r[E]=o[E]^T[_];L(y)}return r}function Bt(t,n,e,o,r){let c=r?r.length:0,f=t.create(e,o.length+c);r&&f.update(r);let i=J(8*o.length,8*c,n);f.update(o),f.update(i);let s=f.digest();return L(i),s}var Z,dt,k,bt,mt,Et,R,et,Lt,ot,rt=P(()=>{X();W();Z=16,dt=4,k=new Uint8Array(Z),bt=283;mt=(()=>{let t=new Uint8Array(256);for(let e=0,o=1;e<256;e++,o^=$(o))t[e]=o;let n=new Uint8Array(256);n[0]=99;for(let e=0;e<255;e++){let o=t[255-e];o|=o<<8,n[t[e]]=(o^o>>4^o>>5^o>>6^o>>7^99)&255}return L(t),n})(),Et=t=>t<<24|t>>>8,R=t=>t<<8|t>>>24;et=At(mt,t=>tt(t,3)<<24|t<<16|t<<8|tt(t,2)),Lt=(()=>{let t=new Uint8Array(16);for(let n=0,e=1;n<16;n++,e=$(e))t[n]=e;return t})();ot=F({blockSize:16,nonceLength:12,tagLength:16,varSizeNonce:!0},function(n,e,o){if(e.length<8)throw new Error("aes/gcm: invalid nonce length");let r=16;function c(i,s,l){let u=Bt(D,!1,i,l,o);for(let h=0;h<s.length;h++)u[h]^=s[h];return u}function f(){let i=Ut(n),s=k.slice(),l=k.slice();if(N(i,!1,l,l,s),e.length===12)l.set(e);else{let h=k.slice();v(h).setBigUint64(8,BigInt(e.length*8),!1);let a=D.create(s).update(e).update(h);a.digestInto(l),a.destroy()}let u=N(i,!1,l,k);return{xk:i,authKey:s,counter:l,tagMask:u}}return{encrypt(i){let{xk:s,authKey:l,counter:u,tagMask:h}=f(),g=new Uint8Array(i.length+r),a=[s,l,u,h];K(i)||a.push(i=B(i)),N(s,!1,u,i,g.subarray(0,i.length));let p=c(l,h,g.subarray(0,g.length-r));return a.push(p),g.set(p,i.length),L(...a),g},decrypt(i){let{xk:s,authKey:l,counter:u,tagMask:h}=f(),g=[s,l,h,u];K(i)||g.push(i=B(i));let a=i.subarray(0,-r),p=i.subarray(-r),w=c(l,h,a);if(g.push(w),!q(w,p))throw new Error("aes/gcm: invalid ghash tag");let b=N(s,!1,u,a);return L(...g),b}}})});var St=ft(()=>{rt();window.nobleGcm=ot});St();})();
/* ---- end vendored ---- */
(function(){
'use strict';
let D = null, PAGES = [];
const $ = id => document.getElementById(id);
let mode = 'draw', drawn = false;

function closed(t, x){ $('loading').classList.add('hidden'); $('app').classList.add('hidden'); $('done').classList.add('hidden'); $('closed').classList.remove('hidden');
  $('closedTitle').textContent = t; $('closedText').textContent = x || ''; }

/* back-to-chat:start (same block in web/sign.js, static/sign.html, static/offline.html; tests check they match) */
// Pages cannot close the chat app's viewer, so the signed screen only says so. A subtle "Return to chat"
// text link appears only when the request set a return_to deep link. See docs/back-to-chat.md.
const BTC_SCHEMES = ['https','whatsapp','tg','sms','slack','discord','sgnl','fb-messenger','msteams','viber','line','mailto','imessage'];
const BTC_DONE = 'You can close this window and go back to the chat. Your signed document will be waiting for you there.';
function btcUrl(rt, text){ if (typeof rt !== 'string' || !rt || rt.length > 600 || /[\u0000-\u001f<>"'`\\ ]/.test(rt)) return null;
  const m = /^([a-z][a-z0-9+.-]*):/i.exec(rt); if (!m || BTC_SCHEMES.indexOf(m[1].toLowerCase()) < 0) return null;
  return rt.split('{text}').join(encodeURIComponent(text)); }
function backToChat(box, rt, docName, opts){ opts = opts || {};
  const text = opts.text || ('I signed ' + (docName || 'the document') + ' \u2705 Please send me the signed file.');
  const url = btcUrl(rt, text);
  const wrap = document.createElement('div'); wrap.id = 'backToChat'; wrap.style.cssText = 'margin-top:10px;text-align:center';
  const hint = document.createElement('p'); hint.id = 'doneLine'; hint.style.cssText = 'margin:0;font-size:1.05rem;color:#3b414d';
  hint.textContent = BTC_DONE; wrap.appendChild(hint);
  if (url) { const a = document.createElement('a'); a.id = 'returnLink'; a.textContent = 'Return to chat';
    a.href = url; a.rel = 'noopener noreferrer'; a.target = opts.target || '_top';
    a.style.cssText = 'display:inline-block;margin-top:14px;font-size:.9rem;color:#5b6170;text-decoration:underline;text-underline-offset:3px';
    if (opts.openLink) a.onclick = ev => { ev.preventDefault(); Promise.resolve(opts.openLink(url)).catch(() => { location.href = url; }); };
    wrap.appendChild(a); }
  const foot = document.createElement('a'); foot.className = 'heroFoot'; foot.textContent = 'Signed with gotoquill \u2197';
  foot.setAttribute('href', 'https://github.com/gotoquill/gotoquill'); foot.target = '_blank'; foot.rel = 'noopener noreferrer'; wrap.appendChild(foot);
  const old = document.getElementById('backToChat'); if (old) old.remove();
  if (typeof heroReceipt === 'function') heroReceipt(box);
  box.appendChild(wrap); return {url, text}; }
/* back-to-chat:end */
/* hero:start (same block in web/sign.js, static/sign.html, static/offline.html; tests check they match) */
// Document-first layout: full-width pages, top bar with progress, sticky "Review & sign", signing in a bottom sheet
// (<dialog showModal> top-layer). Also runs inside sandboxed iframes (Muse / in-app WebViews).
const HERO = {on: false, t0: Date.now(), t1: 0, spots: 0, done: 0, go: false, arm: false,
  reduce: !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches)};
function heroEl(tag, cls, txt){ const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; }
const heroId = id => document.getElementById(id);
function heroInit(){ const app = heroId('app'), card = heroId('signCard'), pages = heroId('pages');
  if (!app || !card || !pages) return;
  HERO.on = true; document.body.classList.add('hero');
  const docCard = pages.closest('.card'); if (docCard) docCard.classList.add('heroDoc');
  const bar = heroEl('header'); bar.id = 'heroBar'; const t = heroEl('div'); t.id = 'heroTitle'; const pr = heroEl('div'); pr.id = 'heroProg';
  pr.setAttribute('aria-live', 'polite'); bar.append(t, pr);
  const cta = heroEl('div'); cta.id = 'heroCta'; const b = heroEl('button', 'heroBtn', 'Review & sign'); b.type = 'button'; b.id = 'heroOpen';
  b.onclick = () => heroOpen(); cta.appendChild(b);
  const back = heroEl('div'); back.id = 'heroBack'; back.setAttribute('aria-hidden', 'true');
  back.addEventListener('click', () => { if (HERO.arm) heroClose(); });
  const sh = heroEl('dialog'); sh.id = 'heroSheet'; sh.setAttribute('aria-label', 'Sign the document');
  const h = heroEl('div', 'heroHandle'); h.setAttribute('aria-hidden', 'true'); sh.appendChild(h);
  const note = heroId('note'); if (note) sh.appendChild(note);
  sh.appendChild(card); app.append(bar, cta, back, sh);
  const sub = heroId('submit'); if (sub) { sub.textContent = 'Adopt & sign'; sub.parentNode.classList.add('heroActions'); }
  if (window.ResizeObserver) new ResizeObserver(() => heroFitChips()).observe(pages); else window.addEventListener('resize', heroFitChips);
  const clr = heroId('clear'); if (clr) { const u = heroEl('button', '', 'Undo'); u.type = 'button'; u.id = 'undo';
    u.onclick = () => { strokes.pop(); if (!strokes.length) drawn = false; redraw(); upd(); }; clr.parentNode.insertBefore(u, clr); }
  let y0 = null; h.addEventListener('pointerdown', e => { y0 = e.clientY; try { h.setPointerCapture(e.pointerId); } catch (_) {} });
  h.addEventListener('pointermove', e => { if (y0 === null) return; sh.style.transition = 'none'; sh.style.transform = 'translateY(' + Math.max(0, e.clientY - y0) + 'px)'; });
  const up = e => { if (y0 === null) return; const dy = e.clientY - y0; y0 = null; sh.style.transition = ''; sh.style.transform = ''; if (dy > 80) heroClose(); };
  h.addEventListener('pointerup', up); h.addEventListener('pointercancel', up);
  // Only dismiss when the gesture started on the dialog/backdrop itself (not a Sign-here tap that opens then retargets).
  let bdPtr = false;
  sh.addEventListener('pointerdown', e => { bdPtr = (e.target === sh); }, true);
  sh.addEventListener('click', e => { if (e.target === sh && HERO.arm && bdPtr) heroClose(); bdPtr = false; });
  sh.addEventListener('cancel', e => { e.preventDefault(); if (HERO.arm) heroClose(); });
  sh.addEventListener('close', () => { heroSheetClearPin(sh); heroBackOn(false); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && document.body.classList.contains('sheetOpen')) heroClose(); });
  document.addEventListener('click', heroIntercept, true);
  const msg = heroId('msg'); if (msg && window.MutationObserver) new MutationObserver(() => {
    if (heroId('done') && !heroId('done').classList.contains('hidden')) return; // signing finished
    if (/\berr\b/.test(msg.className) && msg.textContent) {
      b.textContent = 'Review & sign'; if (!document.body.classList.contains('sheetOpen')) heroOpen();
      else { try { if (sh && typeof sh.showModal === 'function' && !sh.open) sh.showModal(); } catch (_) {} } } }).observe(msg, {attributes: true, childList: true, characterData: true, subtree: true});
  heroSpots(0); }
// sbdate:start -- mirrors pdf.default_date_format / to_strftime / strftime so the label shows exactly what gets stamped
const SB_TOK = [['YYYY','%Y'],['MMMM','%B'],['MMM','%b'],['MM','%m'],['DD','%d'],['YY','%y'],['HH','%H'],['mm','%M']];
const SB_ISO = ['sv','ja','zh','ko','lt','hu','fr-ca','en-ca'];
const SB_MON = ['January','February','March','April','May','June','July','August','September','October','November','December'];
var SB_BOXES = null;  // set by pages whose data is not in D
const SB_DAY = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
function sbLocale(){ try { return (navigator.languages&&navigator.languages[0])||navigator.language||''; } catch (_) { return ''; } }
function sbDefFmt(locale){ const l = String(locale || '').toLowerCase().replace(/_/g, '-');
  if (!l) return '%d %b %Y';
  if (l === 'en-us' || l === 'en-ph' || l === 'en' || l.startsWith('en-us')) return '%m/%d/%Y';
  if (SB_ISO.some(x => l === x || l.startsWith(x + '-'))) return '%Y-%m-%d';
  if (['de','ru','pl','fi','cs','tr','uk','nb','da'].some(x => l.startsWith(x))) return '%d.%m.%Y';
  return '%d/%m/%Y'; }
function sbStrf(fmt, locale){ if (!fmt || fmt === 'auto' || fmt === 'locale') return sbDefFmt(locale);
  fmt = String(fmt); if (fmt.indexOf('%') >= 0) return fmt;
  let out = '', i = 0;
  while (i < fmt.length) { const t = SB_TOK.find(([k]) => fmt.startsWith(k, i));
    if (t) { out += t[1]; i += t[0].length; } else { out += fmt[i]; i += 1; } }
  return out; }
function sbDate(d, strf, zoneName){
  const pad=(n,w=2,ch='0')=>String(n).padStart(w,ch), year=d.getFullYear(), month=d.getMonth(), day=d.getDay();
  const midnight=Date.UTC(year,month,d.getDate()), jan1=Date.UTC(year,0,1), doy=Math.round((midnight-jan1)/86400000)+1;
  const thu=new Date(midnight);thu.setUTCDate(thu.getUTCDate()+3-(day+6)%7);
  const isoYear=thu.getUTCFullYear(), isoWeek=1+Math.round((thu-Date.UTC(isoYear,0,4)+(new Date(Date.UTC(isoYear,0,4)).getUTCDay()+6)%7*86400000)/604800000);
  const off=-d.getTimezoneOffset(), z=(off>=0?'+':'-')+pad(Math.floor(Math.abs(off)/60))+pad(Math.abs(off)%60);
  if(!zoneName){try{zoneName=new Intl.DateTimeFormat('en-US',{timeZoneName:'short'}).formatToParts(d).find(x=>x.type==='timeZoneName').value;}catch(_){zoneName='UTC';}}
  const values={Y:pad(year,4),y:pad(year%100),C:pad(Math.floor(year/100)),m:pad(month+1),d:pad(d.getDate()),e:pad(d.getDate(),2,' '),
    H:pad(d.getHours()),I:pad(d.getHours()%12||12),M:pad(d.getMinutes()),S:pad(d.getSeconds()),f:pad(d.getMilliseconds()*1000,6),p:d.getHours()<12?'AM':'PM',
    b:SB_MON[month].slice(0,3),h:SB_MON[month].slice(0,3),B:SB_MON[month],a:SB_DAY[day].slice(0,3),A:SB_DAY[day],
    w:String(day),u:String((day+6)%7+1),j:pad(doy,3),U:pad(Math.floor((doy+6-day)/7)),W:pad(Math.floor((doy+6-(day+6)%7)/7)),
    G:pad(isoYear,4),g:pad(isoYear%100),V:pad(isoWeek),z,Z:zoneName,n:'\n',t:'\t','%':'%'};
  const composite={c:'%a %b %e %H:%M:%S %Y',x:'%m/%d/%y',X:'%H:%M:%S',D:'%m/%d/%y',F:'%Y-%m-%d',R:'%H:%M',T:'%H:%M:%S',r:'%I:%M:%S %p'};
  return strf.replace(/%([-_0]?)([a-zA-Z%])/g,(m,flag,c)=>{
    let value=composite[c]?sbDate(d,composite[c],zoneName):values[c]; if(value===undefined)return m;
    if(flag==='-')value=value.replace(/^0+(?=\d)/,'');
    if(flag==='_')value=value.replace(/^0+/g,x=>' '.repeat(x.length));
    return value;
  });
}
function sbFmt(){ let f = null; try { const b = (typeof D !== 'undefined' && D && D.boxes) || SB_BOXES || [];
    const s = b.find(x => x.kind !== 'date' && x.date_format); if (s) f = s.date_format; } catch (_) {}
  return sbStrf(f, sbLocale()); }
// sbdate:end
{ const n = document.getElementById('name'); if (n) n.addEventListener('input', sbText); sbText(); }
function sbText(){ const s = document.getElementById('signedByText'); if (!s) return; const n = document.getElementById('name');
  const dt = sbDate(new Date(), sbFmt());
  const nm = (n && n.value.trim()) || 'your name';
  s.textContent = 'Add \u201cSigned by ' + nm + ' \u00b7 ' + dt + '\u201d under my signature'; }
function sbChecked(){ const c = document.getElementById('signedBy'); return !!(c && c.checked); }
function heroProg(){ const p = heroId('heroProg'); if (!p) return;
  p.textContent = HERO.spots ? HERO.done + ' of ' + HERO.spots + (HERO.spots === 1 ? ' spot' : ' spots') : '';
  if (!HERO.reduce && HERO.done) { p.classList.add('bump'); setTimeout(() => p.classList.remove('bump'), 220); } }
function heroFitChips(){ document.querySelectorAll('#pages button.box').forEach(b => {
    if (!b.classList.contains('heroChip')) { const t = heroEl('span', 'heroChipT', b.textContent.trim() || 'Sign here');
      b.setAttribute('aria-label', t.textContent); b.textContent = ''; b.appendChild(t); b.classList.add('heroChip'); }
    if (b.classList.contains('done')) return;
    const w = b.clientWidth, h = b.clientHeight; if (!w || !h) return;
    const fs = Math.max(8, Math.min(13, Math.floor(h * 0.62), Math.floor(w / 5.2)));
    b.style.setProperty('--chipFs', fs + 'px');
    const t = b.querySelector('.heroChipT'), full = b.getAttribute('aria-label'); b.classList.remove('icon');
    const room = w - 10, wid = () => { t.style.maxWidth = 'none'; const x = t.getBoundingClientRect().width; t.style.maxWidth = ''; return x; };
    let fits = false; for (const lbl of [full, '\u270e Sign', 'Sign']) { t.textContent = lbl; if (wid() <= room) { fits = true; break; } }
    b.classList.toggle('icon', h < 11 || !fits); }); }
function heroSpots(n){ HERO.spots = n; const t = heroId('heroTitle'), d = heroId('docName'); if (t && d) t.textContent = d.textContent; heroProg(); if (HERO.on) { heroFitChips(); requestAnimationFrame(heroFitChips); setTimeout(heroFitChips, 400); } }
function heroBackOn(on){ const b = heroId('heroBack'); if (!b) return; b.classList.toggle('heroBackOn', !!on); }
function heroSheetClearPin(sh){ if (!sh) return;
  ['inset','top','right','bottom','left','margin','width','max-width','height','min-height','max-height','display','visibility','opacity','transform','position'].forEach(k => sh.style.removeProperty(k)); }
function heroSheetPin(sh, hard){ if (!sh) return;
  const set = (k, v) => sh.style.setProperty(k, v, 'important');
  set('inset', 'auto 0 0 0'); set('top', 'auto'); set('right', '0'); set('bottom', '0'); set('left', '0');
  set('margin', '0 auto'); set('width', '100%'); set('max-width', '640px');
  const vh = window.innerHeight || 800;
  const mobile = Math.min(window.innerWidth || 800, vh) <= 640;
  if (mobile) { set('height', Math.round(vh * 0.9) + 'px'); set('min-height', Math.round(vh * 0.85) + 'px'); set('max-height', '92vh'); }
  else { set('height', 'auto'); set('min-height', '240px'); set('max-height', '90vh'); }
  set('position', 'fixed');
  if (hard) { set('display', 'flex'); set('visibility', 'visible'); set('opacity', '1'); set('transform', 'none'); } }
function heroSheetBroken(sh){ if (!sh || (!sh.open && !sh.hasAttribute('open'))) return true;
  const r = sh.getBoundingClientRect(), vh = window.innerHeight || 0;
  const cs = getComputedStyle(sh);
  return r.height < 80 || r.width < 40 || (vh && r.top > vh - 40) || cs.visibility === 'hidden' || parseFloat(cs.opacity || '1') < 0.05 || cs.display === 'none'; }
function heroSheetShow(){ const sh = heroId('heroSheet'); if (!sh) return;
  let modal = false;
  if (typeof sh.showModal === 'function') {
    try { if (!sh.open) sh.showModal(); modal = !!sh.open; } catch (_) { modal = false; } }
  if (!modal) { sh.setAttribute('open', ''); heroBackOn(true); }
  heroSheetPin(sh, false);
  const rescue = () => {
    if (!document.body.classList.contains('sheetOpen')) return;
    if (!heroSheetBroken(sh)) { try { if (typeof sizePad === 'function') sizePad(); } catch (_) {} return; }
    // Modal top-layer painted backdrop only (Android WebView): fall back to non-modal + #heroBack.
    try { if (typeof sh.close === 'function' && sh.open) sh.close(); } catch (_) {}
    sh.setAttribute('open', ''); heroBackOn(true); heroSheetPin(sh, true);
    try { if (typeof sizePad === 'function') sizePad(); } catch (_) {}
  };
  requestAnimationFrame(() => { rescue(); requestAnimationFrame(rescue); setTimeout(rescue, HERO.reduce ? 0 : 80); }); }
function heroSheetHide(){ const sh = heroId('heroSheet'); if (!sh) return;
  sh.style.transform = ''; sh.style.transition = '';
  heroSheetClearPin(sh); heroBackOn(false);
  if (typeof sh.close === 'function') { try { if (sh.open) sh.close(); } catch (_) {} }
  sh.removeAttribute('open'); }
function heroOpen(){ if (!HERO.on) return false; heroReset(); document.body.classList.add('sheetOpen');
  HERO.arm = false;
  // Defer past the current tap/click so the same gesture cannot hit ::backdrop and dismiss (Chromium touch).
  clearTimeout(HERO._showT); clearTimeout(HERO._armT); clearTimeout(HERO._padT); clearTimeout(HERO._focusT);
  HERO._showT = setTimeout(() => {
    heroSheetShow();
    HERO._armT = setTimeout(() => { HERO.arm = true; }, HERO.reduce ? 0 : 480);
    HERO._padT = setTimeout(() => { try { if (typeof sizePad === 'function') sizePad(); } catch (_) {} }, HERO.reduce ? 0 : 60);
    const dp = heroId('drawPanel'), target = dp && !dp.classList.contains('hidden') ? heroId('pad') : heroId('typed');
    HERO._focusT = setTimeout(() => { try { target && target.focus({preventScroll: true}); } catch (_) {} }, HERO.reduce ? 0 : 450);
  }, 0);
  return true; }
function heroClose(){ document.body.classList.remove('sheetOpen'); HERO.arm = false;
  clearTimeout(HERO._showT); clearTimeout(HERO._armT); clearTimeout(HERO._padT); clearTimeout(HERO._focusT);
  heroSheetHide(); }
function heroReset(){ document.querySelectorAll('#pages .box.done').forEach(b => { b.classList.remove('done'); b.querySelectorAll('.heroSig,.heroTick').forEach(x => x.remove()); });
  HERO.done = 0; HERO.go = false; heroProg(); }
function heroSigSrc(){ const sel = document.querySelector('.saved.sel img'); if (sel && sel.src) return sel.src;
  const dp = heroId('drawPanel'), pad = heroId('pad');
  if (dp && pad && !dp.classList.contains('hidden')) { try { const x = pad.getContext('2d'), W = pad.width, H = pad.height, a = x.getImageData(0, 0, W, H).data;
      let x0 = W, y0 = H, x1 = -1, y1 = -1; for (let y = 0; y < H; y += 3) for (let i = 0; i < W; i += 3) if (a[(y * W + i) * 4 + 3] > 8) { if (i < x0) x0 = i; if (i > x1) x1 = i; if (y < y0) y0 = y; if (y > y1) y1 = y; }
      if (x1 < 0) return pad.toDataURL(); const m = 10, c = document.createElement('canvas'); x0 = Math.max(0, x0 - m); y0 = Math.max(0, y0 - m);
      c.width = Math.min(W, x1 + m) - x0; c.height = Math.min(H, y1 + m) - y0; c.getContext('2d').drawImage(pad, x0, y0, c.width, c.height, 0, 0, c.width, c.height); return c.toDataURL(); }
    catch (_) { return pad.toDataURL(); } }
  const ty = heroId('typed'), v = ty ? ty.value.trim() : ''; if (!v) return '';
  const c = document.createElement('canvas'); c.width = 900; c.height = 260; const x = c.getContext('2d'); let fs = 150; x.fillStyle = '#0b1a4a';
  do { x.font = fs + 'px "Segoe Script","Brush Script MT","Snell Roundhand",cursive'; fs -= 6; } while (x.measureText(v).width > 860 && fs > 30);
  x.textBaseline = 'middle'; x.textAlign = 'center'; x.fillText(v, 450, 130); return c.toDataURL(); }
function heroPlace(box, src){ box.classList.add('done');
  if (src) { const im = heroEl('img', 'heroSig'); im.src = src; im.alt = ''; box.appendChild(im); }
  const tk = heroEl('span', 'heroTick', '\u2713'); tk.setAttribute('aria-hidden', 'true'); box.appendChild(tk); HERO.done++; heroProg(); }
const heroWait = ms => new Promise(r => setTimeout(r, HERO.reduce ? 0 : ms));
async function heroFly(){ const src = heroSigSrc(), spots = Array.from(document.querySelectorAll('#pages button.box'));
  const dp = heroId('drawPanel'), fromEl = dp && !dp.classList.contains('hidden') ? heroId('pad') : heroId('signCard'), from = fromEl.getBoundingClientRect();
  heroClose(); await heroWait(320);
  for (const box of spots) { let to = box.getBoundingClientRect();
    if (to.top < 70 || to.bottom > window.innerHeight - 100) { box.scrollIntoView({block: 'center', behavior: HERO.reduce ? 'auto' : 'smooth'}); await heroWait(380); to = box.getBoundingClientRect(); }
    if (!HERO.reduce && src && from.width) { const f = heroEl('img', 'heroFly'); f.src = src; f.alt = '';
      f.style.left = from.left + 'px'; f.style.top = from.top + 'px'; f.style.width = from.width + 'px'; f.style.height = from.height + 'px';
      document.body.appendChild(f); f.getBoundingClientRect();
      const s = Math.min(to.width / from.width, to.height / from.height), tx = to.left + (to.width - from.width * s) / 2 - from.left, ty = to.top + (to.height - from.height * s) / 2 - from.top;
      f.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + s + ')';
      await heroWait(430); f.remove(); }
    heroPlace(box, src); await heroWait(190); }
  await heroWait(300); }
async function heroIntercept(e){ const t = e.target && e.target.closest ? e.target.closest('#submit') : null;
  if (!t || !HERO.on || HERO.go || t.disabled) return;
  e.preventDefault(); e.stopImmediatePropagation(); t.disabled = true;
  if (typeof heroCaptureSignature === 'function' && !await heroCaptureSignature()) { t.disabled = false; return; }
  heroFly().catch(() => {}).then(() => { const cb = heroId('heroOpen'); if (cb) cb.textContent = 'Sending\u2026'; HERO.go = true; HERO.t1 = Date.now(); t.disabled = false; t.click(); }); }
function heroReceipt(box){ if (!box || box.querySelector('.heroCheck')) return; if (!HERO.t1) HERO.t1 = Date.now();
  box.classList.add('signed', 'heroReceipt'); const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 56 56'); svg.setAttribute('class', 'heroCheck'); svg.setAttribute('aria-hidden', 'true');
  const c = document.createElementNS(ns, 'circle'); c.setAttribute('cx', '28'); c.setAttribute('cy', '28'); c.setAttribute('r', '26');
  const p = document.createElementNS(ns, 'path'); p.setAttribute('d', 'M17 29l7 7 15-16'); svg.append(c, p); box.insertBefore(svg, box.firstChild);
  const secs = Math.max(1, Math.round((HERO.t1 - HERO.t0) / 1000)), n = Math.max(1, HERO.spots || 1);
  const meta = heroEl('p', 'heroMeta', 'Signed in ' + secs + 's \u00b7 ' + n + (n === 1 ? ' spot' : ' spots') + ' \u00b7 Stayed on your device');
  const h = box.querySelector('h1'); box.insertBefore(meta, h ? h.nextSibling : svg.nextSibling);
  const pg = document.querySelector('#pages .pg'); if (pg) { const th = heroEl('div', 'heroThumb'), cl = pg.cloneNode(true);
    const canvases = pg.querySelectorAll('canvas'); cl.querySelectorAll('canvas').forEach((c, i) => c.getContext('2d').drawImage(canvases[i], 0, 0));
    cl.querySelectorAll('[id]').forEach(x => x.removeAttribute('id')); th.setAttribute('aria-hidden', 'true'); th.appendChild(cl); box.insertBefore(th, meta.nextSibling); } }
heroInit();
/* hero:end */

// ---- SHA-256 / HMAC in plain JS (crypto.subtle is missing on file:// and content:// pages in some browsers) ----
const K = new Uint32Array([0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
function sha256(m){ const l = m.length, n = ((l + 9 + 63) >> 6) << 6, b = new Uint8Array(n); b.set(m); b[l] = 0x80;
  const dv = new DataView(b.buffer); dv.setUint32(n - 4, l * 8 >>> 0); dv.setUint32(n - 8, Math.floor(l / 0x20000000));
  const H = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]), w = new Uint32Array(64);
  const r = (x, k) => (x >>> k) | (x << (32 - k));
  for (let o = 0; o < n; o += 64) { for (let i = 0; i < 16; i++) w[i] = dv.getUint32(o + i * 4);
    for (let i = 16; i < 64; i++) { const a = w[i-15], c = w[i-2]; w[i] = (w[i-16] + (r(a,7)^r(a,18)^(a>>>3)) + w[i-7] + (r(c,17)^r(c,19)^(c>>>10))) | 0; }
    let [a,bb,c,d,e,f,g,h] = H;
    for (let i = 0; i < 64; i++) { const t1 = (h + (r(e,6)^r(e,11)^r(e,25)) + ((e&f)^(~e&g)) + K[i] + w[i]) | 0;
      const t2 = ((r(a,2)^r(a,13)^r(a,22)) + ((a&bb)^(a&c)^(bb&c))) | 0; h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = bb; bb = a; a = (t1 + t2) | 0; }
    H[0]+=a; H[1]+=bb; H[2]+=c; H[3]+=d; H[4]+=e; H[5]+=f; H[6]+=g; H[7]+=h; }
  const out = new Uint8Array(32), ov = new DataView(out.buffer); for (let i = 0; i < 8; i++) ov.setUint32(i * 4, H[i]); return out; }
const hex = u => Array.from(u, x => x.toString(16).padStart(2, '0')).join('');
const utf8 = s => new TextEncoder().encode(s);
function hmac(keyHex, msg){ let k = new Uint8Array(keyHex.match(/../g).map(h => parseInt(h, 16)));
  if (k.length > 64) k = sha256(k); const kp = new Uint8Array(64); kp.set(k);
  const ip = kp.map(x => x ^ 0x36), op = kp.map(x => x ^ 0x5c), m = utf8(msg);
  const inner = new Uint8Array(64 + m.length); inner.set(ip); inner.set(m, 64);
  const ih = sha256(inner), outer = new Uint8Array(96); outer.set(op); outer.set(ih, 64); return hex(sha256(outer)); }
function b64ToBytes(b){ const s = atob(b), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return u; }
function bytesToB64url(u){ let s = ''; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
  return btoa(s).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,''); }

// ---- signature pad (pointer events; no scrolling while drawing) ----
const pad = $('pad'), ctx = pad.getContext('2d'); let pts = [], strokes = [], activeId = null, lastD = 0;
function sizePad(){ const r = pad.getBoundingClientRect(); if (!r.width || !r.height) return; const d = Math.min(window.devicePixelRatio || 1, 3);
  const w = Math.round(r.width * d), h = Math.round(r.height * d); if (w === pad.width && h === pad.height && d === lastD) return;
  lastD = d; pad.width = w; pad.height = h; ctx.setTransform(d,0,0,d,0,0); redraw(); }
function redraw(){ CAPTURED_SIG = null; const r = pad.getBoundingClientRect(), W = r.width, Hh = r.height; ctx.save(); ctx.setTransform(1,0,0,1,0,0); ctx.clearRect(0,0,pad.width,pad.height); ctx.restore();
  $('padPh').classList.toggle('hidden', strokes.length > 0);
  ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#0b1a4a';
  for (const s of strokes) for (let i = 0; i < s.length; i++) { const a = s[Math.max(0,i-1)], p = s[i];
    ctx.beginPath(); ctx.lineWidth = 1.2 + 2.3*p.p; ctx.moveTo(a.x*W, a.y*Hh); ctx.lineTo(p.x*W + (i?0:0.1), p.y*Hh); ctx.stroke(); } }
function pos(e){ const r = pad.getBoundingClientRect(); const p = e.pointerType === 'pen' && e.pressure > 0 ? e.pressure : 0.5;
  return {x: Math.min(1, Math.max(0, (e.clientX-r.left)/r.width)), y: Math.min(1, Math.max(0, (e.clientY-r.top)/r.height)), p}; }
pad.addEventListener('pointerdown', e => { if (activeId !== null || (e.pointerType === 'mouse' && e.button !== 0)) return;
  e.preventDefault(); activeId = e.pointerId; try { pad.setPointerCapture(e.pointerId); } catch (_) {} pts = [pos(e)]; strokes.push(pts); redraw(); });
pad.addEventListener('pointermove', e => { if (e.pointerId !== activeId) return; e.preventDefault();
  const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : [e]; for (const c of (evs.length ? evs : [e])) pts.push(pos(c)); redraw(); });
const end = e => { if (e.pointerId !== activeId) return; activeId = null; try { pad.releasePointerCapture(e.pointerId); } catch (_) {} if (pts.length) { drawn = true; pts = []; upd(); } };
['pointerup','pointercancel','lostpointercapture'].forEach(t => pad.addEventListener(t, end));
['touchstart','touchmove'].forEach(t => pad.addEventListener(t, e => e.preventDefault(), {passive:false}));
pad.addEventListener('contextmenu', e => e.preventDefault());
if (window.ResizeObserver) new ResizeObserver(sizePad).observe(pad); else window.addEventListener('resize', sizePad);
window.addEventListener('orientationchange', () => setTimeout(sizePad, 200));
$('clear').onclick = () => { strokes = []; drawn = false; redraw(); upd(); };
function setMode(m){ CAPTURED_SIG = null; mode = m; $('tabDraw').setAttribute('aria-selected', m==='draw'); $('tabType').setAttribute('aria-selected', m==='type');
  $('drawPanel').classList.toggle('hidden', m!=='draw'); $('typePanel').classList.toggle('hidden', m!=='type'); if (m==='draw') sizePad(); upd(); }
$('tabDraw').onclick = () => setMode('draw'); $('tabType').onclick = () => setMode('type');
function updTyped(){ $('typedPreview').textContent = $('typed').value; }
$('typed').oninput = () => { CAPTURED_SIG = null; updTyped(); if (!$('name').dataset.touched) $('name').value = $('typed').value; upd(); };
$('name').oninput = () => { $('name').dataset.touched = 1; };
$('consent').onchange = () => upd();
$('applyAll').onchange = () => upd();
var SPOTS = 0;  // signature spots (not date fields); >1 needs the extra "apply to all" agreement
function goToPad(){ if (heroOpen()) return; const t = mode === 'draw' ? pad : $('typed'); const card = $('signCard');
  try { card.scrollIntoView({behavior: 'smooth', block: 'center'}); } catch (_) { card.scrollIntoView(); }
  setTimeout(() => { try { t.focus({preventScroll: true}); } catch (_) { t.focus(); } }, 350); }
function has(){ return mode==='draw' ? drawn : $('typed').value.trim().length > 0; }
function upd(){ sbText(); $('submit').disabled = !(has() && $('consent').checked && (SPOTS < 2 || $('applyAll').checked)); }

// signature-capture:start (shared across all three signing pages)
var CAPTURED_SIG = null;
function emptyDataUrl(u){ return typeof u !== 'string' || !/^data:image\/png;base64,[A-Za-z0-9+/]+=*$/.test(u) || u.length < 64; }
function canvasHasInk(c){
  if (![c.width, c.height].every(n => Number.isFinite(n) && n > 0) || c.width*c.height > 16000000) return false;
  const a = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  for (let i=0; i<a.length; i+=4) if ((255 - Math.min(a[i],a[i+1],a[i+2])) * a[i+3] > 127) return true;
  return false;
}
async function validSignature(u){
  if (emptyDataUrl(u)) return false;
  try { const im = new Image(); im.src = u; await im.decode();
    if (!im.naturalWidth || !im.naturalHeight || im.naturalWidth*im.naturalHeight > 16000000) return false;
    const c = document.createElement('canvas'); c.width=im.naturalWidth; c.height=im.naturalHeight;
    c.getContext('2d').drawImage(im,0,0); return canvasHasInk(c);
  } catch (_) { return false; }
}
function signatureRetry(){
  CAPTURED_SIG = null; HERO.go = false; heroOpen();
  $('msg').className = 'err'; $('msg').textContent = 'Could not capture your signature. Please try again. Your strokes are still here.';
  upd();
}
async function heroCaptureSignature(){
  try {
    const saved = typeof savedSel !== 'undefined' && savedSel && document.querySelector('.saved.sel img');
    CAPTURED_SIG = saved ? saved.src : sigPng();
  } catch (_) { CAPTURED_SIG = null; }
  if (!await validSignature(CAPTURED_SIG)) { signatureRetry(); return false; }
  return true;
}
async function capturedSignature(){
  let png = CAPTURED_SIG; CAPTURED_SIG = null;
  if (!png) { try { png = sigPng(); } catch (_) {} }
  if (!await validSignature(png)) { signatureRetry(); return null; }
  return png;
}
function sigPng(){ let src, sw, sh, sx = 0, sy = 0;
  if (mode === 'type') { const c = document.createElement('canvas'); c.width = 900; c.height = 300; const x = c.getContext('2d');
    const t = $('typed').value.trim(); let fs = 150; x.fillStyle = '#0b1a4a';
    do { x.font = fs + 'px "Segoe Script","Brush Script MT","Snell Roundhand",cursive'; fs -= 6; } while (x.measureText(t).width > 860 && fs > 30);
    x.textBaseline = 'middle'; x.fillText(t, 20, 150); src = c; sw = 900; sh = 300; }
  else { const all = strokes.flat();
    if (!pad.width || !pad.height || !all.length || !all.every(p => Number.isFinite(p.x) && Number.isFinite(p.y))) return 'data:,';
    let r = pad.getBoundingClientRect();
    let cssW = r.width, cssH = r.height;
    // After heroClose the pad is display:none → 0x0. Use DPR-backed CSS size instead.
    if (!(cssW > 1 && cssH > 1)) {
      const dpr = lastD || Math.min(window.devicePixelRatio || 1, 3) || 1;
      cssW = (pad.width / dpr) || 600;
      cssH = (pad.height / dpr) || 200;
    }
    const d = pad.width / cssW, m = 8;
    const xs = all.map(p=>p.x*cssW), ys = all.map(p=>p.y*cssH);
    const minX = Math.max(0, Math.min(...xs) - m), minY = Math.max(0, Math.min(...ys) - m);
    const maxX = Math.min(cssW, Math.max(...xs) + m), maxY = Math.min(cssH, Math.max(...ys) + m);
    src = pad; sx = minX*d; sy = minY*d; sw = Math.max(1, (maxX-minX)*d); sh = Math.max(1, (maxY-minY)*d); }
  if (!(sw > 0) || !(sh > 0) || !Number.isFinite(sw) || !Number.isFinite(sh)) return 'data:,';
  const s = Math.min(1, 600 / sw, 200 / sh), c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(sw*s)); c.height = Math.max(1, Math.round(sh*s));
  const cx = c.getContext('2d'); cx.drawImage(src, sx, sy, sw, sh, 0, 0, c.width, c.height);
  if (!canvasHasInk(c)) return 'data:,';
  // one ink colour + 4 alpha levels: looks the same, compresses ~5x better (shorter reply code)
  try { const im = cx.getImageData(0, 0, c.width, c.height), a = im.data;
    for (let i = 0; i < a.length; i += 4) { a[i] = 11; a[i+1] = 26; a[i+2] = 74; a[i+3] = Math.round(a[i+3] / 85) * 85; }
    cx.putImageData(im, 0, 0); } catch (_) {}
  const out = c.toDataURL('image/png');
  return emptyDataUrl(out) ? 'data:,' : out; }


// signature-capture:end

// ---- sealed link: fragment, relay, AES-GCM ----
// sealed file: the params are embedded in the page (window.GOTOQUILL_SEALED) instead of the URL fragment
const EMB = typeof window.GOTOQUILL_SEALED === 'string' ? window.GOTOQUILL_SEALED
  : (typeof window.AGENT_SIGN_SEALED === 'string' ? window.AGENT_SIGN_SEALED : '');
const F = new URLSearchParams(EMB || location.hash.slice(1));
const RELAY = (F.get('r') || 'https://ntfy.sh').replace(/\/+$/, ''), QT = F.get('q'), AT = F.get('a'), KEY = F.get('k');
const _rtRaw = (F.get('rt') || ((RELAY.indexOf('gotoquill-relay') >= 0 || RELAY.indexOf('gotoquill-cloud') >= 0 || RELAY.indexOf('agent-sign-relay') >= 0 || RELAY.indexOf('agentsign-relay') >= 0 || /workers\.dev/i.test(RELAY) || /\/v1(\/|$)/.test(RELAY)) ? 'gotoquill' : 'ntfy'));
const RT = (_rtRaw === 'agentsign' || _rtRaw === 'agent-sign') ? 'gotoquill' : _rtRaw;
const TOPIC_RE = /^[A-Za-z0-9_-]{20,64}$/;
const boxUrl = (t) => RELAY + '/v1/box/' + t;
function b64uToBytes(s){ s = s.replace(/-/g,'+').replace(/_/g,'/'); while (s.length % 4) s += '='; return b64ToBytes(s); }
const aadOf = (kind, topic) => utf8('gotoquill/sealed/v1|' + kind + '|' + topic);
let cryptoKey = null;
// AES-256-GCM: WebCrypto when available (secure contexts), else the vendored audited pure-JS @noble/ciphers gcm.
// Same wire format either way: ciphertext || 16-byte tag.
const SUBTLE = !!(window.crypto && crypto.subtle && crypto.subtle.importKey);
async function aesKey(raw){ if (raw.length !== 32) throw new Error('bad key');
  return SUBTLE ? {w: await crypto.subtle.importKey('raw', raw, {name: 'AES-GCM'}, false, ['encrypt', 'decrypt'])} : {raw}; }
async function aesDec(k, iv, aad, ct){ return k.w ? new Uint8Array(await crypto.subtle.decrypt({name: 'AES-GCM', iv, additionalData: aad}, k.w, ct))
  : window.nobleGcm(k.raw, iv, aad).decrypt(ct); }
async function aesEnc(k, iv, aad, pt){ return k.w ? new Uint8Array(await crypto.subtle.encrypt({name: 'AES-GCM', iv, additionalData: aad}, k.w, pt))
  : window.nobleGcm(k.raw, iv, aad).encrypt(pt); }
const OPEN_IN_BROWSER = 'This preview cannot open it. Tap Download, then open the file in Chrome or Safari.';
// network failures (blocked fetch in in-app previews, offline) -> friendly message instead of a raw TypeError
class NetErr extends Error {}
const isNet = e => e instanceof NetErr || (e && e.name === 'TypeError');
async function fetchRetry(url, opt, n){ let last; for (let i = 0; i < (n || 3); i++) { let r; try { r = await fetch(url, opt); } catch (e) { last = new NetErr(String(e)); r = null; }
    if (r) { if (r.ok) return r; last = new Error('HTTP ' + r.status); if (r.status < 500 && r.status !== 429) break; } await new Promise(z => setTimeout(z, 600 * (i + 1))); } throw last; }
// Render locally from sealed bytes first. The preview capability is only a fallback
// for Cloud documents exceeding the relay box limit; never send fragment keys.
async function renderDocumentPages(payload){
  const token = F.get('pv');
  // OSS/offline requests already carry real raster previews and need no PDF.js assets.
  if (!payload.render_pdf && !token) return null;
  let bytes = payload.pdf_base64 ? b64ToBytes(payload.pdf_base64) : null;
  if (!bytes && RT === 'gotoquill' && token && /^pv_[A-Za-z0-9_-]+$/.test(token)) {
    const response = await fetchRetry(RELAY + '/v1/preview/' + encodeURIComponent(token),
      {cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer'});
    bytes = new Uint8Array(await response.arrayBuffer());
  }
  if (!bytes) return null; // Legacy sealed links already contain rendered PNGs.
  if (D.original_sha256 && hex(sha256(bytes)) !== D.original_sha256)
    throw new Error('Document preview does not match this signing request.');
  const pdfjs = await import('./vendor/pdf.min.mjs');
  const parser = await import('./vendor/pdf.worker.min.mjs');
  // CSP blocks workers: install the same main-thread handler used by the widget.
  globalThis.pdfjsWorker = {WorkerMessageHandler: parser.WorkerMessageHandler};
  const task = pdfjs.getDocument({data: bytes, useSystemFonts: true, isEvalSupported: false});
  try {
    const pdf = await task.promise, pages = [];
    for (let n = 1; n <= pdf.numPages; n++) {
      const page = await pdf.getPage(n), natural = page.getViewport({scale: 1});
      const viewport = page.getViewport({scale: Math.min(2, 1600 / Math.max(natural.width, natural.height))});
      const canvas = document.createElement('canvas');
      canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
      await page.render({canvasContext: canvas.getContext('2d'), viewport}).promise;
      pages.push(canvas.toDataURL('image/png'));
      canvas.width = canvas.height = 0;
      page.cleanup();
    }
    return pages;
  } finally { await task.destroy(); }
}
async function load(){
  if (!QT || !AT || !KEY || !TOPIC_RE.test(QT) || !TOPIC_RE.test(AT)) return closed('This link is incomplete', 'Open the full link your assistant sent (it is long; copy all of it).');
  if (!window.crypto || !crypto.getRandomValues) return closed('Open this in your browser', OPEN_IN_BROWSER);
  // forget the secret part of the address (history / screenshots of the address bar)
  if (!EMB) try { history.replaceState(null, '', location.pathname + location.search); } catch (_) {}
  cryptoKey = await aesKey(b64uToBytes(KEY));
  let blob = null;
  if (RT === 'gotoquill') {
    // single-use GET: retry briefly in case publish is still propagating
    for (let i = 0; i < 5 && !blob; i++) { if (i) await new Promise(z => setTimeout(z, 1000 * i));
      try { const r = await fetchRetry(boxUrl(QT), {cache: 'no-store', referrerPolicy: 'no-referrer'});
        blob = new Uint8Array(await r.arrayBuffer()); } catch (e) { if (!(e && String(e).indexOf('HTTP 404') >= 0)) throw e; } }
  } else {
    let m = null;  // a just-published message can take a moment to show up in the relay's poll: retry briefly
    for (let i = 0; i < 5 && !m; i++) { if (i) await new Promise(z => setTimeout(z, 1000 * i));
      const list = await (await fetchRetry(RELAY + '/' + QT + '/json?poll=1&since=all', {cache: 'no-store', referrerPolicy: 'no-referrer'})).text();
      const msgs = list.split('\n').filter(Boolean).map(l => { try { return JSON.parse(l); } catch (_) { return null; } }).filter(m => m && m.event === 'message');
      m = msgs.reverse().find(x => x.attachment && x.attachment.url) || null; }
    if (!m) return closed('This link has expired', 'The document is no longer on the relay. Ask your assistant for a new link.');
    blob = new Uint8Array(await (await fetchRetry(m.attachment.url, {cache: 'no-store', referrerPolicy: 'no-referrer'})).arrayBuffer());
  }
  if (!blob) return closed('This link has expired', 'The document is no longer on the relay. Ask your assistant for a new link.');
  let plain;
  try { plain = await aesDec(cryptoKey, blob.slice(0, 12), aadOf('request', QT), blob.slice(12)); }
  catch (_) { return closed('Cannot open this document', 'The link key does not match. Use the exact link your assistant sent.'); }
  const P = JSON.parse(new TextDecoder().decode(plain));
  if (!P || (P.type !== 'gotoquill-sealed-request' && P.type !== 'agent-sign-sealed-request')) return closed('Cannot open this document', 'Unknown format.');
  D = P.data; PAGES = (P.pages || []).map(b => 'data:image/png;base64,' + b);
  // already answered? (HEAD for gotoquill so we do not consume the reply the agent is polling for)
  try {
    if (RT === 'gotoquill') {
      const hr = await fetch(boxUrl(AT), {method: 'HEAD', cache: 'no-store', referrerPolicy: 'no-referrer'});
      if (hr.ok) return closed('Already answered', 'This request was already signed or declined. You can close this page.');
    } else {
      const rl = await (await fetch(RELAY + '/' + AT + '/json?poll=1&since=all', {cache: 'no-store'})).text();
      if (rl.split('\n').some(l => l.indexOf('"event":"message"') >= 0)) return closed('Already answered', 'This request was already signed or declined. You can close this page.');
    }
  } catch (_) {}
  try {
    const rendered = await renderDocumentPages(P);
    if (rendered) PAGES = rendered;
  } catch (_) {
    return closed('Cannot preview this document', 'The PDF could not be loaded. Reopen the link or ask your assistant for a new signing request.');
  }
  $('loading').classList.add('hidden'); $('app').classList.remove('hidden');
  start(); }
function start(){
// ---- page ----
  $('docName').textContent = D.document_name;
  const exp = new Date(D.expires_at);
  $('sub').textContent = (D.signer_name ? 'For ' + D.signer_name + ' · ' : '') + D.page_count + ' page(s) · request ' + D.request_id + ' · valid until ' + exp.toLocaleString();
  if (D.message) { $('note').textContent = D.message; $('note').classList.remove('hidden'); }
  if (D.signer_name) { $('name').value = D.signer_name; $('typed').value = D.signer_name; }
  $('consentText').textContent = D.consent_text;
  PAGES.forEach((src, i) => { const wrap = document.createElement('div'); wrap.className = 'pg';
    const im = new Image(); im.alt = 'Page ' + (i + 1) + ' of ' + PAGES.length; im.src = src; wrap.appendChild(im);
    (D.boxes || []).filter(b => b.page === i + 1).forEach(b => { const x = document.createElement(b.kind === 'date' ? 'div' : 'button'); x.className = 'box';
      if (b.kind !== 'date') { x.type = 'button'; x.setAttribute('aria-label', 'Sign here: go to the signature pad'); x.onclick = goToPad; }
      x.style.left = (b.left*100)+'%'; x.style.top = (b.top*100)+'%'; x.style.width = (b.width*100)+'%'; x.style.height = (b.height*100)+'%';
      x.textContent = b.kind === 'date' ? 'Date' : b.kind === 'initials' ? 'Initials' : 'Sign here'; wrap.appendChild(x); });
    $('pages').appendChild(wrap); });
  SPOTS = (D.boxes || []).filter(b => b.kind !== 'date').length; heroSpots(SPOTS);
  if (SPOTS > 1) { $('multi').classList.remove('hidden');
    $('multiNote').textContent = 'This document has ' + SPOTS + ' signature spots. Your one signature will be placed on each of them.';
    $('applyAllText').textContent = 'I agree this signature will be applied to all ' + SPOTS + ' signature spots in this document'; }
  if (exp < new Date()) closed('This request has expired', 'Ask the assistant for a new signing link.');
  
  
  sizePad(); updTyped(); upd(); }

async function finish(resp){ resp.type = 'gotoquill-response'; resp.version = 1; resp.request_id = D.request_id; resp.original_sha256 = D.original_sha256;
  resp.client_timestamp = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'); resp.user_agent = navigator.userAgent;
  if (resp.decision === 'sign') { const png = b64ToBytes(resp.signature_png.split(',')[1]);
    resp.proof = hmac(D.key, ['gotoquill/v1', D.request_id, D.original_sha256, hex(sha256(png)), resp.method, resp.typed_name || '', resp.signer_name || '', resp.client_timestamp].join('|')); }
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await aesEnc(cryptoKey, iv, aadOf('reply', AT), utf8(JSON.stringify(resp)));
  const body = new Uint8Array(12 + ct.length); body.set(iv); body.set(ct, 12);
  $('msg').className = 'mut'; $('msg').textContent = 'Sending (encrypted)…';
  if (RT === 'gotoquill') {
    await fetchRetry(boxUrl(AT), {method: 'PUT', body: new Blob([body]), headers: {'Content-Type': 'application/octet-stream'}, referrerPolicy: 'no-referrer'}, 4);
  } else {
    await fetchRetry(RELAY + '/' + AT + '?filename=reply.bin', {method: 'POST', body: new Blob([body]), referrerPolicy: 'no-referrer'}, 4);
  }
  try { if (typeof heroClose === 'function') heroClose(); } catch (_) {}
  $('app').classList.add('hidden'); $('done').classList.remove('hidden');
  if (resp.decision === 'decline') { $('doneTitle').textContent = 'Declined. you can close this page'; $('doneText').textContent = 'Your assistant was told.'; }
  else { $('done').classList.add('signed'); $('doneTitle').textContent = 'Signed ✓'; $('doneText').classList.add('hidden'); backToChat($('done'), D.return_to, D.document_name); }
  window.scrollTo(0, 0); }
$('submit').onclick = async () => { if (!has() || !$('consent').checked || (SPOTS > 1 && !$('applyAll').checked)) return; $('submit').disabled = true;
  const typed = mode === 'type' ? $('typed').value.trim() : '';
  const png = await capturedSignature(); if (!png) return;
  finish({decision:'sign', signer_timezone: (()=>{try{return Intl.DateTimeFormat().resolvedOptions().timeZone||''}catch(_){return ''}})(), signer_utc_offset: -new Date().getTimezoneOffset(), signer_locale: (navigator.languages&&navigator.languages[0])||navigator.language||'', signature_png: png, method: mode==='draw' ? 'drawn' : 'typed', typed_name: typed,
          signer_name: $('name').value.trim(), consent: true, signed_by_line: sbChecked(), consent_text: D.consent_text})
    .catch(e => { signatureRetry(); $('msg').className = 'err'; $('msg').textContent = isNet(e) ? 'Could not send. Check your connection and tap Sign again. If this is a chat preview, open this file in your browser: tap Download, then open it in Chrome/Safari.' : 'Could not send. Check your connection and tap Sign again. (' + e + ')'; upd(); }); };
$('decline').onclick = () => { let r = ''; try { r = prompt('Decline this request? Optional reason:', ''); } catch (_) {} if (r === null) return;
  finish({decision:'decline', decline_reason: r || ''}).catch(e => { $('msg').className = 'err'; $('msg').textContent = 'Could not send: ' + e; }); };

load().catch(e => isNet(e) ? closed('Open this file in your browser', 'Open this file in your browser: tap Download, then open it in Chrome/Safari. (If you are already in a browser, check your connection and reload.)')
  : closed('Could not open the document', 'Check your connection and try again. (' + e + ')'));
})();
