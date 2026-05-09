"""Auth router — login page, login/logout/me endpoints."""

import os, hashlib, hmac, secrets
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
import users

router = APIRouter()

# ── Auth helpers ──────────────────────────────────────────────────────────────
_AUTH_SECRET = os.environ.get("AUTH_SECRET", secrets.token_hex(32))
_TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")

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

# Roles allowed to access the admin panel
_ADMIN_ROLES = ('superadmin', 'admin')


def _supervisor_blocked(path: str) -> bool:
    return any(path.startswith(p) for p in _SUPERVISOR_BLOCKED)


def _admin_allowed(role: str) -> bool:
    return role in _ADMIN_ROLES


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
<title>FleetPulse - Fleet Operations Intelligence</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32' fill='none'%3E%3Crect x='2' y='22' width='28' height='4' rx='2' fill='%23334155'/%3E%3Crect x='4' y='12' width='16' height='10' rx='2' fill='%233b82f6'/%3E%3Crect x='20' y='15' width='8' height='7' rx='1.5' fill='%232563eb'/%3E%3Ccircle cx='10' cy='22' r='3' fill='%231e293b'/%3E%3Ccircle cx='24' cy='22' r='3' fill='%231e293b'/%3E%3Cpolyline points='1,8 7,8 9,4 12,12 15,6 18,8 22,8' stroke='%2360a5fa' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' fill='none'/%3E%3C/svg%3E">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;overflow-x:hidden}

/* Animated gradient background */
.bg-anim{position:fixed;inset:0;z-index:0;overflow:hidden}
.bg-anim::before{content:'';position:absolute;width:600px;height:600px;border-radius:50%;
  background:radial-gradient(circle,rgba(59,130,246,.15),transparent 70%);
  top:-200px;right:-100px;animation:float 20s ease-in-out infinite}
.bg-anim::after{content:'';position:absolute;width:500px;height:500px;border-radius:50%;
  background:radial-gradient(circle,rgba(96,165,250,.1),transparent 70%);
  bottom:-200px;left:-100px;animation:float 25s ease-in-out infinite reverse}
@keyframes float{0%,100%{transform:translate(0,0)}50%{transform:translate(40px,30px)}}

.container{position:relative;z-index:1;max-width:1200px;margin:0 auto;padding:0 2rem}

/* Header */
header{padding:1.5rem 0;display:flex;align-items:center;justify-content:space-between}
.logo{display:flex;align-items:center;gap:.5rem;text-decoration:none;color:#fff;font-size:1.3rem;font-weight:700}
.logo svg{width:28px;height:28px}
.logo span{color:#60a5fa}

/* Hero */
.hero{display:grid;grid-template-columns:1fr 400px;gap:4rem;align-items:center;padding:4rem 0 3rem;min-height:70vh}
.hero-text h1{font-size:3rem;font-weight:800;line-height:1.1;margin-bottom:1.5rem;
  background:linear-gradient(135deg,#fff 0%,#60a5fa 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero-text p{font-size:1.1rem;color:#94a3b8;line-height:1.7;margin-bottom:2rem;max-width:520px}

/* Feature pills */
.pills{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:2rem}
.pill{display:flex;align-items:center;gap:.4rem;background:rgba(59,130,246,.1);border:1px solid rgba(59,130,246,.2);
  border-radius:999px;padding:.35rem .8rem;font-size:.75rem;color:#93c5fd;font-weight:500}
.pill svg{width:14px;height:14px;opacity:.7}

/* Login card */
.login-card{background:rgba(15,23,42,.8);backdrop-filter:blur(20px);border:1px solid rgba(51,65,85,.5);
  border-radius:16px;padding:2.5rem;box-shadow:0 25px 50px rgba(0,0,0,.3)}
.login-card h2{font-size:1.2rem;font-weight:700;color:#fff;text-align:center;margin-bottom:.3rem}
.login-card .sub{text-align:center;color:#64748b;font-size:.85rem;margin-bottom:1.8rem}
.login-card input{width:100%;padding:.75rem 1rem;margin-bottom:.75rem;background:#1e293b;border:1px solid #334155;
  border-radius:8px;color:#e2e8f0;font-size:.9rem;outline:none;transition:border-color .2s}
.login-card input:focus{border-color:#3b82f6}
.login-card input::placeholder{color:#475569}
.login-btn{width:100%;padding:.8rem;background:linear-gradient(135deg,#2563eb,#3b82f6);color:#fff;border:none;
  border-radius:8px;font-size:.95rem;font-weight:600;cursor:pointer;transition:all .2s;margin-top:.5rem}
.login-btn:hover{background:linear-gradient(135deg,#1d4ed8,#2563eb);transform:translateY(-1px);
  box-shadow:0 8px 20px rgba(37,99,235,.3)}
.err{color:#f87171;text-align:center;margin-bottom:.8rem;font-size:.85rem;min-height:1.2rem}

/* Features grid */
.features{padding:2rem 0 4rem}
.features h2{text-align:center;font-size:1.5rem;font-weight:700;margin-bottom:.5rem}
.features .sub{text-align:center;color:#64748b;font-size:.9rem;margin-bottom:2.5rem}
.feat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1.2rem}
.feat{background:rgba(30,41,59,.5);border:1px solid rgba(51,65,85,.4);border-radius:12px;padding:1.5rem;
  transition:all .3s}
.feat:hover{border-color:rgba(59,130,246,.3);transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.2)}
.feat-icon{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;
  margin-bottom:1rem;font-size:1.2rem}
.feat h3{font-size:.9rem;font-weight:600;margin-bottom:.4rem;color:#f1f5f9}
.feat p{font-size:.78rem;color:#64748b;line-height:1.5}

.feat-icon.blue{background:rgba(59,130,246,.15)}
.feat-icon.green{background:rgba(16,185,129,.15)}
.feat-icon.amber{background:rgba(245,158,11,.15)}
.feat-icon.purple{background:rgba(139,92,246,.15)}
.feat-icon.rose{background:rgba(244,63,94,.15)}
.feat-icon.cyan{background:rgba(6,182,212,.15)}

/* Footer */
footer{text-align:center;padding:2rem 0;color:#334155;font-size:.75rem;border-top:1px solid rgba(51,65,85,.3)}

/* Responsive */
@media(max-width:900px){
  .hero{grid-template-columns:1fr;gap:2rem;padding:2rem 0;min-height:auto}
  .feat-grid{grid-template-columns:1fr 1fr}
}
@media(max-width:600px){.feat-grid{grid-template-columns:1fr}}
</style></head>
<body>
<div class="bg-anim"></div>
<div class="container">

<header>
  <a href="/login" class="logo">
    <svg viewBox="0 0 32 32" fill="none"><rect x="2" y="22" width="28" height="4" rx="2" fill="#334155"/>
    <rect x="4" y="12" width="16" height="10" rx="2" fill="#3b82f6"/><rect x="20" y="15" width="8" height="7" rx="1.5" fill="#2563eb"/>
    <circle cx="10" cy="22" r="3" fill="#1e293b"/><circle cx="24" cy="22" r="3" fill="#1e293b"/>
    <polyline points="1,8 7,8 9,4 12,12 15,6 18,8 22,8" stroke="#60a5fa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>
    Fleet<span>Pulse</span>
  </a>
</header>

<section class="hero">
  <div class="hero-text">
    <h1>Real-time fleet intelligence at your fingertips</h1>
    <p>FleetPulse transforms raw Salesforce Field Service data into actionable insights. Monitor garages, optimize dispatch, track driver performance, and hit your SLA targets -- all from one unified dashboard.</p>
    <div class="pills">
      <div class="pill"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> Real-Time Monitoring</div>
      <div class="pill"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20V10M18 20V4M6 20v-4"/></svg> Performance Scoring</div>
      <div class="pill"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg> AI Assistant</div>
      <div class="pill"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg> Dispatch Insights</div>
    </div>
  </div>
  <div class="login-card">
    <h2>Welcome Back</h2>
    <div class="sub">Sign in to your FleetPulse dashboard</div>
    <div class="err" id="err"></div>
    <form onsubmit="return doLogin(event)">
      <input name="username" placeholder="Username" required autocomplete="username">
      <input name="password" type="password" placeholder="Password" required autocomplete="current-password">
      <button type="submit" class="login-btn">Sign In</button>
    </form>
    <a href="/forgot-password" style="display:block;text-align:center;margin-top:1rem;color:#60a5fa;font-size:.85rem;text-decoration:none">Forgot password?</a>
  </div>
</section>

<section class="features">
  <h2>Everything you need to run a world-class fleet</h2>
  <div class="sub">Built for AAA roadside operations. Powered by Salesforce Field Service data.</div>
  <div class="feat-grid">
    <div class="feat">
      <div class="feat-icon blue">&#128225;</div>
      <h3>Command Center</h3>
      <p>Bird's-eye view of all territories. Open calls, SLA status, over-capacity alerts, and dispatch metrics -- updated in real time.</p>
    </div>
    <div class="feat">
      <div class="feat-icon green">&#9733;</div>
      <h3>Garage Scorecards</h3>
      <p>A-to-F composite grading for every garage based on response time, utilization, on-time arrival, and customer satisfaction.</p>
    </div>
    <div class="feat">
      <div class="feat-icon amber">&#128336;</div>
      <h3>PTA Advisor</h3>
      <p>Predicted Time of Arrival accuracy tracking. See where estimates miss and by how much, broken down by work type.</p>
    </div>
    <div class="feat">
      <div class="feat-icon purple">&#127793;</div>
      <h3>Territory Matrix</h3>
      <p>Cross-territory health comparison. Identify imbalances, workload distribution issues, and cascade opportunities.</p>
    </div>
    <div class="feat">
      <div class="feat-icon rose">&#128202;</div>
      <h3>Dispatch Insights</h3>
      <p>System vs dispatcher assignment rates, closest-driver analysis for fleet and Towbook, and over-capacity detection.</p>
    </div>
    <div class="feat">
      <div class="feat-icon cyan">&#129302;</div>
      <h3>AI Assistant</h3>
      <p>Ask questions about metrics, calculations, and data in plain English. Powered by AI with full context of your fleet data.</p>
    </div>
  </div>
</section>

<footer>FleetPulse -- Fleet Operations Intelligence Platform</footer>

</div>
<script>
async function doLogin(e){e.preventDefault();
const f=new FormData(e.target);
const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({username:f.get('username'),password:f.get('password')})});
if(r.ok){window.location.href='/'}
else{document.getElementById('err').textContent='Invalid credentials'}}
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
        return {"user": principal, "method": "sso", "role": "admin", "name": principal}
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
        return {"user": username, "name": name, "role": role, "email": email, "department": department, "method": "admin"}
    return {"user": "dev", "name": "Developer", "role": "admin", "email": "", "department": "", "method": "local"}


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
