"""Auth router — login page, login/logout/me endpoints."""

import os, hashlib, hmac, secrets, time, threading
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
import users
from permissions import get_user_features

router = APIRouter()

# ── Login rate limiter ────────────────────────────────────────────────────────
_rate_lock = threading.Lock()
_rate_attempts: dict[str, list[float]] = {}  # ip -> [timestamps]
_RATE_WINDOW = 60    # seconds
_RATE_MAX    = 15    # max attempts per window per IP


def _rate_check(ip: str) -> bool:
    """Return True if the IP is within the allowed rate. False = block."""
    now = time.time()
    with _rate_lock:
        ts = _rate_attempts.get(ip, [])
        ts = [t for t in ts if now - t < _RATE_WINDOW]
        if len(ts) >= _RATE_MAX:
            _rate_attempts[ip] = ts
            return False
        ts.append(now)
        _rate_attempts[ip] = ts
        return True


def _get_ip(request: Request) -> str:
    forwarded = request.headers.get('x-forwarded-for', '')
    return forwarded.split(',')[0].strip() or request.client.host


# ── Auth helpers ──────────────────────────────────────────────────────────────
_AUTH_SECRET = os.environ.get("AUTH_SECRET", secrets.token_hex(32))
_TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")
_DEV_AUTO_LOGIN = os.environ.get("DEV_AUTO_LOGIN", "false").lower() == "true"

_PUBLIC_PATHS = {"/login", "/forgot-password", "/reset-password", "/api/auth/login", "/api/auth/forgot-password", "/api/auth/verify-reset-pin", "/api/auth/reset-password", "/api/health", "/api/features", "/favicon.ico"}

# Paths finance-department users may call (everything else → 403)
_FINANCE_ALLOWED = ('/api/auth/', '/api/accounting/', '/api/health', '/api/features')


def _finance_ok(path: str) -> bool:
    return any(path.startswith(p) for p in _FINANCE_ALLOWED)


def _get_department(username: str) -> str:
    """Return the user's department string, '' if not set or not found."""
    u = users.get_user(username)
    return (u or {}).get('department', '') or ''


def _get_role(username: str) -> str:
    """Return the user's role string, '' if not set or not found."""
    u = users.get_user(username)
    return (u or {}).get('role', '') or ''


# Paths that ers-supervisor role is blocked from
_SUPERVISOR_BLOCKED = ('/api/accounting/', '/api/admin/')

# Roles allowed to access the full admin panel
_ADMIN_ROLES = ('superadmin', 'admin')

# Roles allowed read/write access to reference data only (no PIN required)
_REFERENCE_ROLES = ('executive', 'ers-director')


def _supervisor_blocked(path: str) -> bool:
    return any(path.startswith(p) for p in _SUPERVISOR_BLOCKED)


def _admin_allowed(role: str) -> bool:
    return role in _ADMIN_ROLES


def _reference_allowed(role: str, path: str) -> bool:
    return role in _REFERENCE_ROLES and path.startswith('/api/admin/reference/')


def _sign_cookie(payload: str) -> str:
    sig = hmac.new(_AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_cookie(cookie: str) -> str | None:
    if not cookie or "." not in cookie:
        return None
    payload, sig = cookie.rsplit(".", 1)
    expected = hmac.new(_AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return payload
    return None


_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FleetPulse — Sign In</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%}
body{
  font-family:-apple-system,BlinkMacSystemFont,'Inter','Segoe UI',system-ui,sans-serif;
  background:#060c18;color:#e2e8f0;min-height:100dvh;
  display:flex;align-items:center;justify-content:center;overflow:hidden;
}

/* ── Animated background ── */
.bg{position:fixed;inset:0;z-index:0;overflow:hidden}
.orb{position:absolute;border-radius:50%;filter:blur(90px);pointer-events:none}
.orb-1{
  width:560px;height:560px;
  background:radial-gradient(circle,rgba(37,99,235,.38) 0%,transparent 70%);
  top:-180px;right:-120px;
  animation:drift1 20s ease-in-out infinite;
}
.orb-2{
  width:480px;height:480px;
  background:radial-gradient(circle,rgba(245,158,11,.22) 0%,transparent 70%);
  bottom:-140px;left:-100px;
  animation:drift2 26s ease-in-out infinite;
}
.orb-3{
  width:320px;height:320px;
  background:radial-gradient(circle,rgba(6,182,212,.18) 0%,transparent 70%);
  top:45%;left:25%;
  animation:drift3 32s ease-in-out infinite;
}
@keyframes drift1{0%,100%{transform:translate(0,0) scale(1)}40%{transform:translate(28px,-22px) scale(1.06)}70%{transform:translate(-18px,18px) scale(.97)}}
@keyframes drift2{0%,100%{transform:translate(0,0) scale(1)}35%{transform:translate(-24px,20px) scale(1.04)}65%{transform:translate(18px,-14px) scale(.96)}}
@keyframes drift3{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(36px,28px) scale(1.08)}}

/* Subtle dot grid */
.grid{
  position:fixed;inset:0;z-index:0;pointer-events:none;
  background-image:radial-gradient(rgba(59,130,246,.08) 1px,transparent 1px);
  background-size:28px 28px;
}

/* ── Card ── */
.wrap{
  position:relative;z-index:1;
  width:100%;max-width:400px;
  padding:0 20px;
  animation:rise .75s cubic-bezier(.22,1,.36,1) both;
}
@keyframes rise{from{opacity:0;transform:translateY(28px)}to{opacity:1;transform:translateY(0)}}

.card{
  background:rgba(9,16,30,.88);
  border:1px solid rgba(255,255,255,.07);
  border-radius:22px;
  padding:40px 36px 36px;
  backdrop-filter:blur(28px);
  box-shadow:
    0 0 0 1px rgba(59,130,246,.07),
    0 40px 80px rgba(0,0,0,.55),
    0 0 80px rgba(37,99,235,.06);
}

/* ── Logo ── */
.logo{
  display:flex;align-items:center;justify-content:center;gap:10px;
  margin-bottom:30px;text-decoration:none;
  animation:rise .75s .1s cubic-bezier(.22,1,.36,1) both;
}
.logo-text{font-size:1.3rem;font-weight:800;color:#fff;letter-spacing:-.03em}
.logo-text span{color:#3b82f6}

/* ── Headings ── */
.title{
  font-size:1.6rem;font-weight:700;color:#fff;
  letter-spacing:-.025em;text-align:center;
  margin-bottom:6px;
  animation:rise .75s .15s cubic-bezier(.22,1,.36,1) both;
}
.subtitle{
  font-size:.83rem;color:#475569;text-align:center;
  line-height:1.5;margin-bottom:30px;
  animation:rise .75s .2s cubic-bezier(.22,1,.36,1) both;
}

/* ── Form fields ── */
.field{margin-bottom:14px;animation:rise .75s .25s cubic-bezier(.22,1,.36,1) both}
.field+.field{animation-delay:.3s}
.field label{
  display:block;font-size:.72rem;font-weight:600;
  color:#64748b;letter-spacing:.06em;text-transform:uppercase;margin-bottom:7px;
}
.field input{
  width:100%;padding:13px 16px;
  background:rgba(15,23,42,.75);
  border:1px solid rgba(255,255,255,.07);
  border-radius:11px;color:#e2e8f0;font-size:.93rem;
  outline:none;transition:border-color .2s,box-shadow .2s,background .2s;
}
.field input:focus{
  border-color:rgba(59,130,246,.5);
  box-shadow:0 0 0 3px rgba(59,130,246,.12),0 0 24px rgba(59,130,246,.05);
  background:rgba(20,32,58,.85);
}
.field input::placeholder{color:#2d3f5a}

/* ── Password toggle ── */
.pw-wrap{position:relative}
.pw-wrap input{padding-right:46px}
.pw-btn{
  position:absolute;right:13px;top:50%;transform:translateY(-50%);
  background:none;border:none;cursor:pointer;color:#334155;
  display:flex;align-items:center;padding:4px;
  transition:color .2s;
}
.pw-btn:hover{color:#64748b}

/* ── Error ── */
.err{
  font-size:.8rem;color:#f87171;text-align:center;
  min-height:20px;margin-bottom:14px;display:flex;
  align-items:center;justify-content:center;gap:6px;
  animation:rise .75s .35s cubic-bezier(.22,1,.36,1) both;
}

/* ── Submit button ── */
.btn{
  width:100%;padding:14px;margin-top:4px;
  background:#2563eb;color:#fff;border:none;
  border-radius:11px;font-size:.95rem;font-weight:600;
  cursor:pointer;letter-spacing:-.01em;
  transition:background .2s,transform .15s,box-shadow .2s;
  position:relative;overflow:hidden;
  animation:rise .75s .4s cubic-bezier(.22,1,.36,1) both;
}
.btn::after{
  content:'';position:absolute;inset:0;
  background:linear-gradient(135deg,rgba(255,255,255,.1) 0%,transparent 55%);
  opacity:0;transition:opacity .2s;pointer-events:none;
}
.btn:hover{
  background:#1d4ed8;transform:translateY(-2px);
  box-shadow:0 10px 30px rgba(37,99,235,.45),0 0 50px rgba(37,99,235,.15);
}
.btn:hover::after{opacity:1}
.btn:active{transform:translateY(0) scale(.99);box-shadow:none}
.btn:disabled{opacity:.55;cursor:not-allowed;transform:none;box-shadow:none}

/* ── Spinner ── */
.sp{
  display:inline-block;width:15px;height:15px;
  border:2px solid rgba(255,255,255,.3);border-top-color:#fff;
  border-radius:50%;animation:spin .65s linear infinite;
  vertical-align:middle;margin-right:8px;
}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── Forgot link ── */
.fp{
  display:block;text-align:center;margin-top:18px;
  color:#3b82f6;font-size:.8rem;text-decoration:none;opacity:.7;
  transition:opacity .2s;
  animation:rise .75s .45s cubic-bezier(.22,1,.36,1) both;
}
.fp:hover{opacity:1}

/* ── Footer tag ── */
.tag{
  text-align:center;margin-top:22px;
  font-size:.7rem;color:rgba(255,255,255,.18);letter-spacing:.04em;
}

@media(max-width:420px){
  .card{padding:32px 24px 28px;border-radius:18px}
}
</style></head>
<body>

<div class="bg">
  <div class="orb orb-1"></div>
  <div class="orb orb-2"></div>
  <div class="orb orb-3"></div>
</div>
<div class="grid"></div>

<div class="wrap">
  <div class="card">

    <a href="/login" class="logo">
      <svg viewBox="0 0 36 36" width="30" height="30" fill="none">
        <circle cx="18" cy="18" r="15.5" stroke="#2563eb" stroke-width="1.4" opacity="0.45"/>
        <circle cx="18" cy="18" r="15.5" stroke="#3b82f6" stroke-width="6" opacity="0.04"/>
        <polyline points="2.5,18 7,18 10,10 13.5,26 18,12 21.5,21 24.5,18 33.5,18"
          stroke="#f59e0b" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
        <circle cx="33.5" cy="18" r="2.2" fill="#3b82f6">
          <animate attributeName="opacity" values="1;0.25;1" dur="1.6s" repeatCount="indefinite"/>
        </circle>
        <circle cx="33.5" cy="18" r="4.5" fill="#3b82f6" opacity="0.12">
          <animate attributeName="r" values="3;6;3" dur="1.6s" repeatCount="indefinite"/>
          <animate attributeName="opacity" values="0.12;0;0.12" dur="1.6s" repeatCount="indefinite"/>
        </circle>
      </svg>
      <span class="logo-text">Fleet<span>Pulse</span></span>
    </a>

    <h1 class="title">Welcome back</h1>
    <p class="subtitle">Sign in to your FleetPulse account</p>

    <div class="err" id="err" role="alert" aria-live="polite"></div>

    <form onsubmit="return doLogin(event)" novalidate>
      <div class="field">
        <label for="u">Username</label>
        <input id="u" name="username" type="text"
          placeholder="Enter your username"
          required autocomplete="username" autofocus>
      </div>

      <div class="field">
        <label for="p">Password</label>
        <div class="pw-wrap">
          <input id="p" name="password" type="password"
            placeholder="Enter your password"
            required autocomplete="current-password">
          <button type="button" class="pw-btn" id="pwtoggle"
            aria-label="Show password" onclick="togglePw()">
            <svg id="eye-icon" viewBox="0 0 24 24" width="18" height="18"
              fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
          </button>
        </div>
      </div>

      <button type="submit" class="btn" id="btn">Sign in</button>
    </form>

    <a href="/forgot-password" class="fp">Forgot password?</a>

  </div>
  <p class="tag">AAA Emergency Road Service &bull; Internal tool</p>
</div>

<script>
var eyeOpen='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
var eyeOff='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
function togglePw(){
  var inp=document.getElementById('p');
  var btn=document.getElementById('pwtoggle');
  var hidden=inp.type==='password';
  inp.type=hidden?'text':'password';
  btn.innerHTML=hidden?eyeOff:eyeOpen;
  btn.setAttribute('aria-label',hidden?'Hide password':'Show password');
}
async function doLogin(e){
  e.preventDefault();
  var err=document.getElementById('err');
  var btn=document.getElementById('btn');
  err.textContent='';
  btn.disabled=true;
  btn.innerHTML='<span class="sp"></span>Signing in…';
  try{
    var f=new FormData(e.target);
    var r=await fetch('/api/auth/login',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({username:f.get('username'),password:f.get('password')})
    });
    if(r.ok){
      btn.innerHTML='Signed in ✔';
      window.location.href='/';
    } else {
      err.textContent='Invalid username or password';
      btn.disabled=false;
      btn.textContent='Sign in';
      document.getElementById('p').focus();
    }
  } catch(ex){
    err.textContent='Connection error. Try again.';
    btn.disabled=false;
    btn.textContent='Sign in';
  }
}
</script>
</body></html>"""


_FORGOT_PASSWORD_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FleetPulse - Forgot Password</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32' fill='none'%3E%3Crect x='2' y='22' width='28' height='4' rx='2' fill='%23334155'/%3E%3Crect x='4' y='12' width='16' height='10' rx='2' fill='%233b82f6'/%3E%3Crect x='20' y='15' width='8' height='7' rx='1.5' fill='%232563eb'/%3E%3Ccircle cx='10' cy='22' r='3' fill='%231e293b'/%3E%3Ccircle cx='24' cy='22' r='3' fill='%231e293b'/%3E%3Cpolyline points='1,8 7,8 9,4 12,12 15,6 18,8 22,8' stroke='%2360a5fa' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' fill='none'/%3E%3C/svg%3E">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center}
.bg-anim{position:fixed;inset:0;z-index:0;overflow:hidden}
.bg-anim::before{content:'';position:absolute;width:600px;height:600px;border-radius:50%;
  background:radial-gradient(circle,rgba(59,130,246,.15),transparent 70%);
  top:-200px;right:-100px;animation:float 20s ease-in-out infinite}
.bg-anim::after{content:'';position:absolute;width:500px;height:500px;border-radius:50%;
  background:radial-gradient(circle,rgba(96,165,250,.1),transparent 70%);
  bottom:-200px;left:-100px;animation:float 25s ease-in-out infinite reverse}
@keyframes float{0%,100%{transform:translate(0,0)}50%{transform:translate(40px,30px)}}
.card{position:relative;z-index:1;background:rgba(15,23,42,.8);backdrop-filter:blur(20px);border:1px solid rgba(51,65,85,.5);
  border-radius:16px;padding:2.5rem;box-shadow:0 25px 50px rgba(0,0,0,.3);width:100%;max-width:420px;margin:1rem}
.logo{display:flex;align-items:center;justify-content:center;gap:.5rem;text-decoration:none;color:#fff;font-size:1.3rem;font-weight:700;margin-bottom:1.5rem}
.logo svg{width:28px;height:28px}
.logo span{color:#60a5fa}
h2{font-size:1.2rem;font-weight:700;color:#fff;text-align:center;margin-bottom:.3rem}
.sub{text-align:center;color:#64748b;font-size:.85rem;margin-bottom:1.8rem}
input{width:100%;padding:.75rem 1rem;margin-bottom:.75rem;background:#1e293b;border:1px solid #334155;
  border-radius:8px;color:#e2e8f0;font-size:.9rem;outline:none;transition:border-color .2s}
input:focus{border-color:#3b82f6}
input::placeholder{color:#475569}
.btn{width:100%;padding:.8rem;background:linear-gradient(135deg,#2563eb,#3b82f6);color:#fff;border:none;
  border-radius:8px;font-size:.95rem;font-weight:600;cursor:pointer;transition:all .2s;margin-top:.5rem}
.btn:hover{background:linear-gradient(135deg,#1d4ed8,#2563eb);transform:translateY(-1px);box-shadow:0 8px 20px rgba(37,99,235,.3)}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none;box-shadow:none}
.msg{text-align:center;margin-bottom:.8rem;font-size:.85rem;min-height:1.2rem}
.msg.error{color:#f87171}
.msg.success{color:#34d399}
.back{display:block;text-align:center;margin-top:1rem;color:#60a5fa;font-size:.85rem;text-decoration:none}
.back:hover{text-decoration:underline}
.hp{display:none!important;visibility:hidden!important}
.cf-turnstile{margin:0 0 .75rem}
</style>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
</head><body>
<div class="bg-anim"></div>
<div class="card">
  <a href="/login" class="logo">
    <svg viewBox="0 0 32 32" fill="none"><rect x="2" y="22" width="28" height="4" rx="2" fill="#334155"/>
    <rect x="4" y="12" width="16" height="10" rx="2" fill="#3b82f6"/><rect x="20" y="15" width="8" height="7" rx="1.5" fill="#2563eb"/>
    <circle cx="10" cy="22" r="3" fill="#1e293b"/><circle cx="24" cy="22" r="3" fill="#1e293b"/>
    <polyline points="1,8 7,8 9,4 12,12 15,6 18,8 22,8" stroke="#60a5fa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>
    Fleet<span>Pulse</span>
  </a>
  <h2>Reset Your Password</h2>
  <div class="sub">Enter your email and we'll send you a reset link + PIN</div>
  <div class="msg" id="msg"></div>
  <form id="frm" onsubmit="return doForgot(event)">
    <input name="email" type="email" placeholder="your.email@nyaaa.com" required autocomplete="email">
      <input name="website" type="text" class="hp" tabindex="-1" autocomplete="off">
    <div class="cf-turnstile" data-sitekey="" data-callback="turnstileReady" data-expired-callback="turnstileExpired"></div>
    <button type="submit" class="btn" id="btn" disabled>Send Reset Link</button>
  </form>
  <a href="/login" class="back">&larr; Back to login</a>
</div>
<script>
let turnstileToken='';
function turnstileReady(token){turnstileToken=token;document.getElementById('btn').disabled=false;}
function turnstileExpired(){turnstileToken='';document.getElementById('btn').disabled=true;}

async function doForgot(e){e.preventDefault();
const btn=document.getElementById('btn');const msg=document.getElementById('msg');
btn.disabled=true;btn.textContent='Sending...';msg.textContent='';msg.className='msg';
const fd=new FormData(e.target);
const email=fd.get('email');
const website=fd.get('website');
try{const r=await fetch('/api/auth/forgot-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,website,turnstile:turnstileToken})});
const d=await r.json();
if(r.ok){msg.textContent=d.message||'Check your email for a reset link and PIN.';msg.className='msg success';document.getElementById('frm').style.display='none'}
else{msg.textContent=d.detail||'Something went wrong';msg.className='msg error';btn.disabled=false;btn.textContent='Send Reset Link'}}
catch(err){msg.textContent='Network error. Please try again.';msg.className='msg error';btn.disabled=false;btn.textContent='Send Reset Link'}}
</script>
</body></html>"""


_RESET_PASSWORD_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FleetPulse - Reset Password</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32' fill='none'%3E%3Crect x='2' y='22' width='28' height='4' rx='2' fill='%23334155'/%3E%3Crect x='4' y='12' width='16' height='10' rx='2' fill='%233b82f6'/%3E%3Crect x='20' y='15' width='8' height='7' rx='1.5' fill='%232563eb'/%3E%3Ccircle cx='10' cy='22' r='3' fill='%231e293b'/%3E%3Ccircle cx='24' cy='22' r='3' fill='%231e293b'/%3E%3Cpolyline points='1,8 7,8 9,4 12,12 15,6 18,8 22,8' stroke='%2360a5fa' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' fill='none'/%3E%3C/svg%3E">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center}
.bg-anim{position:fixed;inset:0;z-index:0;overflow:hidden}
.bg-anim::before{content:'';position:absolute;width:600px;height:600px;border-radius:50%;
  background:radial-gradient(circle,rgba(59,130,246,.15),transparent 70%);
  top:-200px;right:-100px;animation:float 20s ease-in-out infinite}
.bg-anim::after{content:'';position:absolute;width:500px;height:500px;border-radius:50%;
  background:radial-gradient(circle,rgba(96,165,250,.1),transparent 70%);
  bottom:-200px;left:-100px;animation:float 25s ease-in-out infinite reverse}
@keyframes float{0%,100%{transform:translate(0,0)}50%{transform:translate(40px,30px)}}
.card{position:relative;z-index:1;background:rgba(15,23,42,.8);backdrop-filter:blur(20px);border:1px solid rgba(51,65,85,.5);
  border-radius:16px;padding:2.5rem;box-shadow:0 25px 50px rgba(0,0,0,.3);width:100%;max-width:420px;margin:1rem}
.logo{display:flex;align-items:center;justify-content:center;gap:.5rem;text-decoration:none;color:#fff;font-size:1.3rem;font-weight:700;margin-bottom:1.5rem}
.logo svg{width:28px;height:28px}
.logo span{color:#60a5fa}
h2{font-size:1.2rem;font-weight:700;color:#fff;text-align:center;margin-bottom:.3rem}
.sub{text-align:center;color:#64748b;font-size:.85rem;margin-bottom:1.8rem}
input{width:100%;padding:.75rem 1rem;margin-bottom:.75rem;background:#1e293b;border:1px solid #334155;
  border-radius:8px;color:#e2e8f0;font-size:.9rem;outline:none;transition:border-color .2s}
input:focus{border-color:#3b82f6}
input::placeholder{color:#475569}
.btn{width:100%;padding:.8rem;background:linear-gradient(135deg,#2563eb,#3b82f6);color:#fff;border:none;
  border-radius:8px;font-size:.95rem;font-weight:600;cursor:pointer;transition:all .2s;margin-top:.5rem}
.btn:hover:not(:disabled){background:linear-gradient(135deg,#1d4ed8,#2563eb);transform:translateY(-1px);box-shadow:0 8px 20px rgba(37,99,235,.3)}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none;box-shadow:none}
.msg{text-align:center;margin-bottom:.8rem;font-size:.85rem;min-height:1.2rem}
.msg.error{color:#f87171}
.msg.success{color:#34d399}
.back{display:block;text-align:center;margin-top:1rem;color:#60a5fa;font-size:.85rem;text-decoration:none}
.back:hover{text-decoration:underline}
.reqs{list-style:none;margin:0 0 1rem;padding:0;font-size:.8rem}
.reqs li{padding:.2rem 0;display:flex;align-items:center;gap:.4rem}
.reqs li .icon{width:16px;text-align:center;font-weight:700}
.reqs li.pass{color:#34d399}
.reqs li.fail{color:#64748b}
.step{display:none}
.step.active{display:block}
</style></head><body>
<div class="bg-anim"></div>
<div class="card">
  <a href="/login" class="logo">
    <svg viewBox="0 0 32 32" fill="none"><rect x="2" y="22" width='28' height='4' rx='2' fill='#334155'/>
    <rect x="4" y="12" width='16' height='10' rx='2' fill='#3b82f6'/><rect x="20" y="15" width='8' height='7' rx='1.5' fill='#2563eb'/>
    <circle cx="10" cy="22" r='3' fill='#1e293b'/><circle cx="24" cy="22" r='3' fill='#1e293b'/>
    <polyline points='1,8 7,8 9,4 12,12 15,6 18,8 22,8' stroke='#60a5fa' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' fill='none'/></svg>
    Fleet<span>Pulse</span>
  </a>

  <!-- Step 1: PIN Verification -->
  <div id="step-pin" class="step active">
    <h2>Verify Your Identity</h2>
    <div class="sub">Enter the 6-digit PIN from your email</div>
    <div class="msg" id="msg-pin"></div>
    <form id="frm-pin" onsubmit="return doVerifyPin(event)">
      <input name="pin" type="text" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" placeholder="6-digit PIN" required autocomplete="one-time-code" id="pin-input">
      <button type="submit" class="btn" id="btn-pin">Verify PIN</button>
    </form>
    <a href="/forgot-password" class="back">Request a new reset link</a>
  </div>

  <!-- Step 2: New Password -->
  <div id="step-pw" class="step">
    <h2>Set New Password</h2>
    <div class="sub">Choose a strong password for your account</div>
    <div class="msg" id="msg-pw"></div>
    <form id="frm-pw" onsubmit="return doReset(event)">
      <input name="password" type="password" placeholder="New password" required autocomplete="new-password" id="pw1" oninput="validate()">
      <input name="password_confirm" type="password" placeholder="Confirm password" required autocomplete="new-password" id="pw2" oninput="validate()">
      <ul class="reqs">
        <li id="r-len" class="fail"><span class="icon">&#10005;</span> At least 12 characters</li>
        <li id="r-upper" class="fail"><span class="icon">&#10005;</span> Contains uppercase letter</li>
        <li id="r-lower" class="fail"><span class="icon">&#10005;</span> Contains lowercase letter</li>
        <li id="r-num" class="fail"><span class="icon">&#10005;</span> Contains number</li>
        <li id="r-spec" class="fail"><span class="icon">&#10005;</span> Contains special character</li>
        <li id="r-match" class="fail"><span class="icon">&#10005;</span> Passwords match</li>
      </ul>
      <button type="submit" class="btn" id="btn-pw" disabled>Update Password</button>
    </form>
    <a href="/forgot-password" class="back">Request a new reset link</a>
  </div>
</div>
<script>
const token=new URLSearchParams(location.search).get('token');
let validationToken='';

if(!token){
  document.getElementById('msg-pin').textContent='Invalid reset link. Please request a new one.';
  document.getElementById('msg-pin').className='msg error';
  document.getElementById('frm-pin').style.display='none';
}

function showStep(id){
  document.querySelectorAll('.step').forEach(s=>s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

async function doVerifyPin(e){e.preventDefault();
const btn=document.getElementById('btn-pin');const msg=document.getElementById('msg-pin');
btn.disabled=true;btn.textContent='Verifying...';msg.textContent='';msg.className='msg';
const pin=document.getElementById('pin-input').value.trim();
try{
  const r=await fetch('/api/auth/verify-reset-pin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:token,pin:pin})});
  const d=await r.json();
  if(r.ok){validationToken=d.validation_token;showStep('step-pw');}
  else{msg.textContent=d.detail||'Something went wrong';msg.className='msg error';btn.disabled=false;btn.textContent='Verify PIN';}
}
catch(err){msg.textContent='Network error. Please try again.';msg.className='msg error';btn.disabled=false;btn.textContent='Verify PIN';}}

function validate(){
const pw=document.getElementById('pw1').value;
const pw2=document.getElementById('pw2').value;
const checks=[
{id:'r-len',ok:pw.length>=12},
{id:'r-upper',ok:/[A-Z]/.test(pw)},
{id:'r-lower',ok:/[a-z]/.test(pw)},
{id:'r-num',ok:/[0-9]/.test(pw)},
{id:'r-spec',ok:/[!@#$%^&*()_+\-=\[\]{}|;:',.<>?\/`~]/.test(pw)},
{id:'r-match',ok:pw.length>0&&pw===pw2}
];
let allGood=true;
checks.forEach(c=>{const el=document.getElementById(c.id);
el.className=c.ok?'pass':'fail';
el.querySelector('.icon').innerHTML=c.ok?'&#10003;':'&#10005;';
if(!c.ok)allGood=false});
document.getElementById('btn-pw').disabled=!allGood}

async function doReset(e){e.preventDefault();
const btn=document.getElementById('btn-pw');const msg=document.getElementById('msg-pw');
btn.disabled=true;btn.textContent='Updating...';msg.textContent='';msg.className='msg';
const pw=document.getElementById('pw1').value;
const pw2=document.getElementById('pw2').value;
try{const r=await fetch('/api/auth/reset-password',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({validation_token:validationToken,password:pw,password_confirm:pw2})});
const d=await r.json();
if(r.ok){msg.textContent='Password updated successfully! Redirecting to login...';msg.className='msg success';
document.getElementById('frm-pw').style.display='none';setTimeout(()=>location.href='/login',3000)}
else{msg.textContent=d.detail||'Something went wrong';msg.className='msg error';btn.disabled=false;btn.textContent='Update Password';validate()}}
catch(err){msg.textContent='Network error. Please try again.';msg.className='msg error';btn.disabled=false;btn.textContent='Update Password';validate()}}
</script>
</body></html>"""


@router.get("/login", response_class=HTMLResponse)
def login_page():
    return _LOGIN_HTML


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page():
    html = _FORGOT_PASSWORD_HTML
    if _TURNSTILE_SITE_KEY:
        html = html.replace('data-sitekey=""', f'data-sitekey="{_TURNSTILE_SITE_KEY}"')
    else:
        # If no site key configured, hide the widget container
        html = html.replace('<div class="cf-turnstile"', '<div class="cf-turnstile" style="display:none"')
    return html


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page():
    return _RESET_PASSWORD_HTML


@router.post("/api/auth/login")
def admin_login(request: Request, creds: dict, response: Response):
    if not _rate_check(_get_ip(request)):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a minute.")
    user = users.authenticate(creds.get("username", ""), creds.get("password", ""))
    if user:
        dept = user.get("department", "")
        token = users.create_session(user["username"], user["role"], user["name"], dept)
        payload = f"{user['username']}:{user['role']}:{token}"
        response.set_cookie("fslapp_auth", _sign_cookie(payload), httponly=True, samesite="lax", max_age=86400)
        return {"ok": True, "user": user["username"], "name": user["name"], "role": user["role"], "department": dept}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/api/auth/me")
def auth_me(request: Request):
    # Azure Easy Auth
    principal = request.headers.get("x-ms-client-principal-name")
    if principal:
        return {"user": principal, "method": "sso", "role": "admin", "name": principal, "features": get_user_features("admin")}
    # Admin cookie
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if payload:
        parts = payload.split(":")
        username = parts[0]
        role = parts[1] if len(parts) > 1 else "admin"
        name = username
        email = ""
        department = ""
        # Try to get session info for richer data
        if len(parts) > 2:
            sess = users.get_session(parts[2])
            if sess:
                name = sess.get("name", username)
                role = sess.get("role", role)
                department = sess.get("department", "")
        # Get email + department from user record (authoritative; also handles old sessions without dept)
        user_record = users.get_user(username)
        if user_record:
            email = user_record.get("email", "")
            if not department:
                department = user_record.get("department", "")
        return {"user": username, "name": name, "role": role, "email": email, "department": department, "method": "admin", "features": get_user_features(role)}
    if _DEV_AUTO_LOGIN:
        return {"user": "dev", "name": "Developer", "role": "admin", "email": "", "department": "", "method": "local", "features": get_user_features("admin")}
    raise HTTPException(status_code=401, detail="Not authenticated")


@router.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if payload:
        parts = payload.split(":")
        if len(parts) > 2:
            users.destroy_session(parts[2])
    response.delete_cookie("fslapp_auth")
    return {"ok": True}
