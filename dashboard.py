"""
A single, dependency-free HTML dashboard -- no JavaScript, no React, no build
step. Just enough to show the system's current state during a demo. Reads
directly from state_manager's in-memory snapshot store.

Everything that originates outside this file (device ids, alert codes, delivery
error text, mandi fields, dates) is HTML-escaped before it is placed in the page:
device ids arrive from the network, so they are untrusted input.
"""
from datetime import datetime
from html import escape
from urllib.parse import quote

from agronomy.paddy_profile import (
    CROP_PROFILE,
    FERTILIZER_RULES,
    HARVEST_APPROACHING_WINDOW_DAYS,
    MOISTURE_HIGH_ENTER,
    MOISTURE_LOW_ENTER,
)
from config import LOCATION_NAME, STALE_AFTER_MINUTES   # STALE_AFTER_MINUTES: see config.py
from state_manager import (
    get_dashboard_device_ids, get_last_sms_event, get_last_updated_map, get_recent_readings,
    get_recent_sms_events, get_server_start_time, get_snapshot, get_sms_language, get_uptime_seconds,
)
import demo_scenarios
from sms_i18n import SUPPORTED_LANGUAGES
from weather import RAIN_THRESHOLD_MM

REFRESH_SECONDS = 15

# code -> (severity, human-readable text). Severity: "bad" (a fault), "warn" (needs
# the farmer), "wet" (too much water), "info" (context, not an action).
ALERTS = {
    "SENSOR_FAULT_DHT22": ("bad", "DHT22 sensor not responding. Check the temperature and humidity sensor."),
    "SENSOR_FAULT_SOIL": ("bad", "The soil moisture sensor is not reporting. Check the probe and its wiring."),
    "LOW_MOISTURE": ("warn", "The soil moisture is low. Check the field and irrigate if needed."),
    "EXCESS_MOISTURE": ("wet", "The soil shows high moisture. Check for standing water and drainage."),
    "FERTILIZER_DUE_BASAL": ("warn", "The basal fertilizer dose is due."),
    "FERTILIZER_DUE_TILLERING": ("warn", "The first nitrogen top-dressing is due (tillering stage)."),
    "FERTILIZER_DUE_PANICLE": ("warn", "The second nitrogen top-dressing is due (panicle initiation)."),
    "HARVEST_APPROACHING": ("warn", "The crop is approaching its estimated harvest window."),
    "HARVEST_CHECK_DUE": ("warn", "A harvest check is due. Inspect grain colour and moisture before deciding."),
    "RAIN_WARNING": ("warn", "Rain is forecast, which may affect harvesting or field work."),
    "WEATHER_UNAVAILABLE": ("info", "The weather forecast could not be fetched."),
}
_SEVERITY_ORDER = {"bad": 0, "warn": 1, "wet": 1, "info": 2}

CSS = """
:root { --bg:#22252b; --surface:#292d34; --surface-hi:#30343c; --text:#f4f5f8; --muted:#9ba2af;
        --ok:#17b892; --blue:#3478ff; --warn:#f2a83b; --wet:#4d87ff; --bad:#ef6670; --off:#606773;
        --shadow-dark:#191b20; --shadow-light:#333841; }
* { box-sizing:border-box; }
body { max-width:1180px; min-height:100vh; margin:0 auto; padding:32px; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; background:var(--bg); color:var(--text); }
h1 { font-size:13px; color:#dfe2e8; margin:0 0 5px; letter-spacing:.13em; font-weight:750; }
h2 { font-size:11px; margin:28px 0 12px; color:var(--muted); text-transform:uppercase; letter-spacing:.12em; }
.subtitle { color:var(--muted); margin:0 0 22px; font-size:13px; }
.devices { display:flex; gap:10px; flex-wrap:wrap; margin:0 0 20px; }
.devices a, .refresh-btn, .lang-chip { color:var(--text); text-decoration:none; border:0; background:var(--surface); box-shadow:5px 5px 10px var(--shadow-dark), -4px -4px 9px var(--shadow-light); border-radius:12px; padding:8px 14px; font-size:12px; transition:transform .15s, box-shadow .15s, color .15s; }
.devices a:hover, .refresh-btn:hover, .lang-chip:hover { color:#a9f0dd; transform:translateY(-1px); }
.devices a[aria-current="page"], .lang-chip.active { color:#fff; font-weight:700; background:linear-gradient(145deg,#17b892,#4c6fff); box-shadow:inset 2px 2px 5px #0d6d55, inset -2px -2px 5px #758cff, 0 0 16px #17b89266; }
.notice { background:#382f22; box-shadow:inset 2px 2px 5px #241e16, inset -2px -2px 5px #4b3f2d; border-radius:14px; padding:12px 15px; margin-bottom:18px; font-size:13px; color:#f6ca79; }
.status { display:flex; align-items:center; gap:11px; font-size:28px; letter-spacing:-.035em; font-weight:750; margin:4px 0; }
.status.ok { color:#b9f2e2; } .status.warn { color:#ffd17b; } .status.bad { color:#ff9ba2; } .status.off { color:var(--muted); }
.live { width:12px; height:12px; border-radius:50%; background:var(--ok); box-shadow:0 0 0 5px #17b89220, 0 0 14px var(--ok); display:inline-block; }
.live.off { background:var(--off); box-shadow:none; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(205px,1fr)); gap:18px; margin-top:18px; }
.card { min-height:142px; background:var(--surface); border:0; border-radius:18px; padding:18px; box-shadow:8px 8px 16px var(--shadow-dark), -6px -6px 14px var(--shadow-light); }
.label { font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.12em; font-weight:700; }
.value { font-size:29px; letter-spacing:-.045em; font-weight:750; margin-top:10px; }
.sub { font-size:12px; color:var(--muted); margin-top:6px; line-height:1.4; }
.na { color:var(--muted); font-weight:400; }
.tag { display:inline-block; font-size:11px; font-weight:700; letter-spacing:.03em; border-radius:999px; padding:5px 10px; margin-top:12px; background:var(--off); box-shadow:inset 1px 1px 3px #4b5059, inset -1px -1px 3px #737b88; }
.tag.ok { background:#854bd3; } .tag.warn { background:var(--warn); color:#342300; } .tag.wet { background:var(--wet); } .tag.bad { background:var(--bad); } .tag.off { background:var(--off); }
.gauge { position:relative; height:12px; border-radius:999px; margin-top:16px; box-shadow:inset 3px 3px 6px #1a1d22, inset -2px -2px 4px #363b44; }
.marker { position:absolute; top:-5px; width:5px; height:22px; background:#fff; border-radius:4px; margin-left:-2px; box-shadow:0 0 8px #fff; }
ul.alerts { list-style:none; padding:0; margin:0; display:grid; gap:10px; }
ul.alerts li { background:var(--surface); box-shadow:6px 6px 13px var(--shadow-dark), -5px -5px 11px var(--shadow-light); border:0; border-left:4px solid var(--off); border-radius:14px; padding:12px 15px; font-size:14px; }
ul.alerts li.bad { border-left-color:var(--bad); } ul.alerts li.warn { border-left-color:var(--warn); } ul.alerts li.wet { border-left-color:var(--wet); } ul.alerts li.info { border-left-color:var(--off); }
code { color:#7fe0c4; font-size:11px; margin-left:7px; }
ul.forecast { list-style:none; padding:0; margin:12px 0 0; font-size:12px; } ul.forecast li { display:flex; justify-content:space-between; padding:4px 0; } .heavy { color:#ffc85a; font-weight:700; }
.verdict { font-size:17px; font-weight:700; margin-top:10px; }.note { font-size:12px; color:var(--muted); margin:8px 0 0; line-height:1.45; }
.row { display:flex; justify-content:space-between; align-items:center; max-width:410px; padding:11px 13px; margin-bottom:8px; background:var(--surface); box-shadow:inset 2px 2px 5px var(--shadow-dark), inset -2px -2px 5px var(--shadow-light); border-radius:10px; font-size:14px; }.muted { color:#7d8490; font-size:12px; margin-top:26px; }
.demo-panel { margin-top:28px; padding:20px; background:var(--surface); border:0; border-radius:20px; box-shadow:8px 8px 16px var(--shadow-dark), -6px -6px 14px var(--shadow-light); }.demo-panel h2 { color:#d9dce2; }
.demo-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:13px; margin-top:16px; }
.demo-btn { width:100%; min-height:68px; text-align:left; background:var(--surface); color:var(--text); border:0; border-radius:14px; padding:13px 15px; font-size:13px; font-weight:700; cursor:pointer; box-shadow:6px 6px 12px var(--shadow-dark), -4px -4px 10px var(--shadow-light); transition:transform .15s, box-shadow .15s, color .15s; }.demo-btn:hover { color:#c8f5e6; transform:translateY(-2px); box-shadow:8px 8px 14px var(--shadow-dark), -5px -5px 12px var(--shadow-light), 0 0 12px #17b89233; }.demo-btn:active { transform:translateY(1px); box-shadow:inset 4px 4px 8px var(--shadow-dark), inset -3px -3px 7px var(--shadow-light); }.demo-btn small { display:block; color:var(--muted); font-size:11px; line-height:1.35; margin-top:5px; font-weight:400; }
.demo-locked { color:var(--muted); font-size:13px; line-height:1.5; }.demo-locked code { background:#20232a; padding:2px 5px; border-radius:5px; }
.unlock { display:flex; gap:12px; flex-wrap:wrap; margin-top:14px; }.unlock input { background:var(--surface); color:var(--text); border:0; box-shadow:inset 3px 3px 6px var(--shadow-dark), inset -2px -2px 5px var(--shadow-light); border-radius:12px; padding:12px 14px; font-size:13px; min-width:220px; outline:0; }.unlock input:focus { box-shadow:inset 3px 3px 6px var(--shadow-dark), inset -2px -2px 5px var(--shadow-light), 0 0 0 2px #17b89277; }.unlock .demo-btn { width:auto; min-height:0; text-align:center; }
.lang-row { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-top:16px; }.lang-row form { margin:0; }span.lang-chip { cursor:default; }.lang-chip { cursor:pointer; font-family:inherit; padding:7px 14px; }.lang-chip.active { cursor:default; }
.sms-banner { border:0; border-left:4px solid var(--off); border-radius:14px; background:var(--surface); box-shadow:6px 6px 13px var(--shadow-dark), -5px -5px 11px var(--shadow-light); padding:13px 16px; margin-bottom:18px; font-size:14px; }.sms-banner.ok { border-left-color:var(--ok); }.sms-banner.bad { border-left-color:var(--bad); }.sms-banner summary { cursor:pointer; color:var(--muted); font-size:12px; margin-top:8px; }.sms-banner pre { white-space:pre-wrap; word-break:break-word; background:#20232a; border:0; box-shadow:inset 2px 2px 5px var(--shadow-dark); border-radius:9px; padding:9px 11px; margin:8px 0 0; font-family:inherit; font-size:13px; }
.refresh-btn { display:inline-block; margin-left:10px; color:#c8f5e6; padding:6px 11px; }
@media (max-width:560px) { body { padding:20px; }.status { font-size:24px; }.grid { grid-template-columns:1fr; gap:14px; }.card { min-height:0; }.refresh-btn { margin:9px 0 0; }.subtitle { display:flex; flex-direction:column; align-items:flex-start; } }

/* App workspace: a calmer green, white and charcoal dashboard rather than a full-screen control panel. */
:root { --bg:#e9f0eb; --surface:#ffffff; --surface-soft:#f4f8f5; --text:#17231c; --muted:#718077; --ok:#197a45; --blue:#197a45; --warn:#d99625; --wet:#2f8cce; --bad:#d94c55; --off:#aebbb3; --line:#dce6df; --shadow-dark:#c9d5cd; --shadow-light:#ffffff; }
body { max-width:none; padding:0; background:var(--bg); color:var(--text); font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
.app-shell { display:flex; min-height:100vh; }
.rail { width:82px; flex:0 0 82px; background:#17231c; display:flex; flex-direction:column; align-items:center; padding:22px 12px; }
.brand { width:42px; height:42px; display:grid; place-items:center; border-radius:14px; background:#2aa260; color:#fff; box-shadow:0 7px 16px #06130b55; font-size:21px; font-weight:800; text-decoration:none; }
.rail-links { display:grid; gap:12px; margin-top:45px; }.rail-links a { width:42px; height:42px; border-radius:13px; display:grid; place-items:center; color:#b9c9bf; text-decoration:none; font-size:18px; }.rail-links a.active, .rail-links a:hover { color:#fff; background:#2aa260; box-shadow:0 7px 16px #0b442655; }
.rail-footer { margin-top:auto; color:#8ea097; font-size:11px; writing-mode:vertical-rl; transform:rotate(180deg); letter-spacing:.12em; }
.workspace { flex:1; min-width:0; padding:30px clamp(22px,4vw,64px) 42px; }.topbar { max-width:1200px; margin:0 auto 26px; display:flex; align-items:flex-start; justify-content:space-between; gap:22px; }.eyebrow { color:var(--ok); margin:0 0 9px; font-weight:750; letter-spacing:.12em; font-size:10px; text-transform:uppercase; }
h1 { color:var(--text); font-size:28px; line-height:1.1; letter-spacing:-.045em; margin:0 0 7px; }.subtitle { color:var(--muted); margin:0; font-size:13px; }.topbar-metas { display:flex; gap:10px; flex-wrap:wrap; }.topbar-meta { background:var(--surface); border:1px solid var(--line); border-radius:14px; padding:11px 14px; min-width:150px; display:flex; align-items:center; gap:9px; box-shadow:0 7px 20px #405c4910; font-size:12px; color:var(--muted); }.topbar-meta strong { display:block; color:var(--text); font-size:13px; }.topbar-meta .live { flex:0 0 auto; }
.content { max-width:1200px; margin:0 auto; }.refresh-btn { margin:0 0 0 9px; color:var(--ok); background:transparent; box-shadow:none; border:1px solid #b7d8c3; border-radius:8px; padding:5px 9px; }.refresh-btn:hover { color:#fff; background:var(--ok); transform:none; }
.devices { padding:6px; gap:5px; margin-bottom:22px; display:inline-flex; background:#dfe8e2; border-radius:11px; }.devices a { color:var(--muted); padding:7px 12px; background:transparent; box-shadow:none; border-radius:7px; }.devices a:hover { color:var(--ok); background:#fff; transform:none; }.devices a[aria-current="page"] { color:var(--ok); background:#fff; box-shadow:0 2px 7px #58706322; }
.status { color:var(--text); font-size:25px; letter-spacing:-.04em; }.status.ok { color:var(--text); }.status.warn { color:#8d6115; }.status.bad { color:#9e3038; }.live { background:var(--ok); box-shadow:0 0 0 5px #1a9b5630; }.live.off { background:var(--off); box-shadow:none; }
.grid { grid-template-columns:repeat(auto-fit,minmax(215px,1fr)); gap:16px; margin-top:17px; }.card { min-height:154px; background:var(--surface); border:1px solid var(--line); border-radius:15px; padding:18px; box-shadow:0 8px 22px #3552400d; }.card:hover { border-color:#bcd6c5; box-shadow:0 10px 25px #35524017; }.label { color:var(--muted); letter-spacing:.09em; }.value { color:var(--text); font-size:28px; }.tag { background:#e5ece8; color:#52635a; box-shadow:none; padding:5px 9px; }.tag.ok { color:#fff; background:var(--ok); }.tag.warn { background:#ffedce; color:#8b5c08; }.tag.wet { background:#dceefe; color:#1767a6; }.tag.bad { background:#fde1e3; color:#a72c36; }.tag.off { background:#e4e9e6; color:#69776f; }.gauge { box-shadow:none; }.marker { box-shadow:0 0 6px #25332b; }
h2 { color:#617168; letter-spacing:.1em; margin:29px 0 11px; }ul.alerts li, .sms-banner { background:#fff; border:1px solid var(--line); box-shadow:0 7px 20px #3552400c; border-left-width:4px; border-radius:12px; }code { color:#177443; }.row { background:#fff; box-shadow:none; border:1px solid var(--line); border-radius:10px; }.muted { color:var(--muted); }
.demo-panel { background:#f7faf8; border:1px solid var(--line); border-radius:16px; box-shadow:none; padding:20px; }.demo-panel h2 { color:var(--text); }.demo-btn { min-height:70px; background:#fff; color:var(--text); border:1px solid var(--line); border-radius:11px; box-shadow:0 5px 14px #3552400b; }.demo-btn:hover { color:#fff; background:var(--ok); border-color:var(--ok); transform:translateY(-2px); box-shadow:0 9px 17px #197a4530; }.demo-btn:hover small { color:#d6f1df; }.demo-btn:active { box-shadow:inset 2px 2px 5px #0f6136; }.unlock input { background:#fff; color:var(--text); border:1px solid var(--line); box-shadow:none; }.unlock input:focus { box-shadow:0 0 0 3px #197a4522; }.lang-chip { color:#466053; background:#fff; border:1px solid var(--line); box-shadow:none; border-radius:8px; }.lang-chip:hover { color:var(--ok); border-color:#9bc9aa; transform:none; }.lang-chip.active { color:#fff; background:var(--ok); border-color:var(--ok); box-shadow:none; }.sms-banner pre { background:#f3f7f4; box-shadow:none; }.notice { background:#fff8e9; color:#805910; box-shadow:none; border:1px solid #f0d69e; }
@media (max-width:700px) { .rail { width:60px; flex-basis:60px; padding:16px 9px; }.brand,.rail-links a { width:37px; height:37px; }.rail-links { margin-top:30px; }.workspace { padding:24px 18px 35px; }.topbar { display:block; }.topbar-meta { margin-top:18px; width:max-content; }.grid { grid-template-columns:1fr; } }

/* Polish pass (kept last so it wins): contrast, wrapping, Indic fonts, status dot, phone layout. */
:root { --muted:#5b6a61; }
body { font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","Nirmala UI","Noto Sans Devanagari","Noto Sans Kannada",sans-serif; }
button, input { font-family:inherit; }
.heavy { color:#9a5b00; }
.demo-locked code { background:#eaf1ec; color:#177443; }
.marker { background:#17231c; border:2px solid #fff; box-shadow:0 1px 4px #17231c66; }
.unlock input:focus { border-color:var(--ok); box-shadow:0 0 0 3px #197a4544; }
.sms-banner, .notice, .tag, .devices a { overflow-wrap:anywhere; }
.sms-banner pre { line-height:1.6; }
span.lang-chip:hover { color:#466053; border-color:var(--line); }
.grid.stale { opacity:.5; }
.live.warn { background:var(--warn); box-shadow:0 0 0 5px #d9962530; }
.live.bad { background:var(--bad); box-shadow:0 0 0 5px #d94c5530; }
.activity-log { margin-top:22px; }
.activity-log summary { cursor:pointer; font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.12em; font-weight:700; }
.activity-log h2 { margin:16px 0 10px; }
.unlock-link { display:inline-block; text-decoration:none; width:auto; min-height:0; text-align:center; margin-top:12px; }
@media (max-width:560px) { .card { min-height:0; }.refresh-btn { margin:9px 0 0; }.unlock input, .unlock .demo-btn { width:100%; min-width:0; } }

/* No side panel: one clean column. Control panel = a row of pill buttons at the top. */
.app-shell { display:block; }
.workspace { max-width:1240px; margin:0 auto; }
.demo-panel { margin:0 0 18px; padding:16px 18px; }
.demo-panel h2 { margin:0; }
.panel-head { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:10px; }
.hint { text-transform:none; letter-spacing:0; font-weight:500; color:var(--muted); font-size:12px; margin-left:6px; }
.panel-actions { display:flex; flex-wrap:wrap; gap:8px; }
.panel-actions form, .pill-row form { margin:0; }
.pill-row { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }
.pill { display:inline-block; font:inherit; font-size:13px; font-weight:600; color:var(--text); background:#fff; border:1px solid var(--line); border-radius:999px; padding:8px 15px; cursor:pointer; text-decoration:none; transition:background .15s, color .15s, border-color .15s; }
.pill:hover { color:#fff; background:var(--ok); border-color:var(--ok); }
.pill.primary { color:#fff; background:var(--ok); border-color:var(--ok); }
.pill.primary:hover { filter:brightness(1.12); }
.pill.quiet { color:var(--muted); background:transparent; }
.pill.quiet:hover { color:var(--text); background:#e5ece8; border-color:var(--line); }
.sim-notice { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; background:#fff8e9; color:#805910; border:1px solid #f0d69e; border-radius:12px; padding:12px 16px; margin-bottom:18px; font-size:14px; }
.sim-notice form { margin:0; }
"""


def _ago(delta_seconds: float) -> str:
    seconds = max(int(delta_seconds), 0)
    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{seconds} s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h ago"
    return f"{hours // 24} d ago"


def _format_uptime(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m {secs}s"
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _parse_time(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _rule_name(rule: dict) -> str:
    return rule["id"].split("-", 1)[-1].capitalize()      # "FERT-TILLERING" -> "Tillering"


def _stage_summary(days: int, maturity_days: int) -> str:
    """One line on what the crop is doing / what is coming next, from days since sowing."""
    remaining = maturity_days - days
    if remaining <= 0:
        return "Estimated maturity reached."
    if remaining <= HARVEST_APPROACHING_WINDOW_DAYS:
        return f"Harvest window approaching: about {_plural(remaining, 'day')} to go."
    for rule in FERTILIZER_RULES:
        lo, hi = rule["window"]
        if lo <= days <= hi:
            return f"{_rule_name(rule)} fertilizer window is open now (until day {hi})."
    for rule in FERTILIZER_RULES:
        lo, _ = rule["window"]
        if lo > days:
            return f"Next: {_rule_name(rule).lower()} fertilizer window opens in {_plural(lo - days, 'day')} (day {lo})."
    return f"About {remaining} days until the estimated harvest check."


def _num(value, fmt: str):
    """Format a number, or None if it is missing / not a number."""
    try:
        return format(float(value), fmt)
    except (TypeError, ValueError):
        return None


def _na(sub: str = "") -> str:
    note = f'<div class="sub">{escape(sub)}</div>' if sub else ""
    return f'<div class="value"><span class="na">N/A</span></div>{note}'


# ----------------------------------------------------------------- sections

def _moisture_card(facts: dict) -> str:
    moisture = facts.get("soil_moisture_index")
    state = facts.get("moisture_state")
    tag = {
        "low": '<span class="tag warn">Low</span>',
        "normal": '<span class="tag ok">Normal</span>',
        "high": '<span class="tag wet">Too wet</span>',
    }.get(state, '<span class="tag bad">No data</span>')

    label = '<div class="label">Soil moisture index</div>'
    if moisture is None:
        return f'<div class="card">{label}{_na()}{tag}</div>'

    lo, hi = MOISTURE_LOW_ENTER, MOISTURE_HIGH_ENTER
    position = min(max(float(moisture), 0.0), 100.0)
    gradient = (
        f"linear-gradient(to right, var(--warn) 0 {lo:.1f}%, "
        f"var(--ok) {lo:.1f}% {hi:.1f}%, var(--wet) {hi:.1f}% 100%)"
    )
    return (
        f'<div class="card">{label}'
        f'<div class="value">{escape(format(float(moisture), "g"))} <span class="na">/ 100</span></div>'
        f'<div class="gauge" role="meter" aria-label="Soil moisture index" aria-valuemin="0" aria-valuemax="100" '
        f'aria-valuenow="{escape(format(float(moisture), "g"))}" style="background:{gradient}">'
        f'<span class="marker" style="left:{position:.1f}%"></span></div>'
        f"{tag}</div>"
    )


def _dht_card(label: str, formatted, fault: bool) -> str:
    if formatted is not None:
        return f'<div class="card"><div class="label">{label}</div><div class="value">{formatted}</div></div>'
    note = "DHT22 sensor not responding" if fault else "No data"
    return f'<div class="card"><div class="label">{label}</div>{_na(note)}</div>'


def _weather_card(facts: dict, codes: list) -> str:
    label = '<div class="label">Rain forecast (3 days)</div>'
    if facts.get("weather_available"):
        rain = facts.get("rain_expected_next_days")
        verdict = "Rain expected" if rain else "No significant rain expected"
        rows = ""
        for day in facts.get("weather_forecast") or []:
            try:
                name = datetime.strptime(str(day.get("date")), "%Y-%m-%d").strftime("%a %d %b")
            except ValueError:
                name = str(day.get("date"))
            mm = _num(day.get("rain_mm"), ".1f")
            if mm is None:
                amount = '<span class="na">no data</span>'
            elif float(mm) >= RAIN_THRESHOLD_MM:
                amount = f'<span class="heavy">{mm} mm</span>'
            else:
                amount = f"<span>{mm} mm</span>"
            rows += f"<li><span>{escape(name)}</span>{amount}</li>"
        listing = f'<ul class="forecast">{rows}</ul>' if rows else ""
        return f'<div class="card">{label}<div class="verdict">{verdict}</div>{listing}</div>'

    if "WEATHER_UNAVAILABLE" in codes:
        return (
            f'<div class="card">{label}<div class="verdict">Unavailable</div>'
            '<p class="note">The forecast could not be fetched. This does not mean no rain.</p></div>'
        )
    return (
        f'<div class="card">{label}<div class="verdict">Not checked</div>'
        '<p class="note">The forecast is only fetched when a new alert is being sent.</p></div>'
    )


def _mandi_card(facts: dict) -> str:
    mandi = facts.get("mandi") or {}
    if not mandi.get("available"):
        return ""
    price = _num(mandi.get("modal_price"), ",.0f")
    if price is None:
        return ""
    where = ", ".join(escape(str(x)) for x in (mandi.get("market"), mandi.get("arrival_date")) if x)
    low, high = mandi.get("min_price"), mandi.get("max_price")
    spread = f'<div class="sub">range Rs {escape(str(low))} to {escape(str(high))}</div>' if low and high else ""
    return (
        '<div class="card"><div class="label">Mandi price</div>'
        f'<div class="value">Rs {price}</div><div class="sub">per quintal &middot; {where}</div>{spread}</div>'
    )


def _alerts_section(codes: list) -> str:
    if not codes:
        return "<p>No active alerts.</p>"
    known = [(ALERTS.get(c, ("warn", c)), c) for c in codes]
    known.sort(key=lambda item: (_SEVERITY_ORDER[item[0][0]], item[1]))
    items = "".join(
        f'<li class="{severity}">{escape(text)}<code>{escape(code)}</code></li>'
        for (severity, text), code in known
    )
    return f'<ul class="alerts">{items}</ul>'


def _delivery_section(snapshot: dict, now: datetime) -> str:
    delivery = snapshot.get("delivery")
    if not delivery:
        return "<h2>Delivery</h2><p>No advisory has been sent yet.</p>"

    def row(name: str, status) -> str:
        status = str(status if status is not None else "-")
        kind = "ok" if status.startswith("sent") else "bad" if status.startswith("failed") else "off"
        return f'<div class="row"><span>{name}</span><span class="tag {kind}" style="margin:0">{escape(status)}</span></div>'

    sent_at = _parse_time(snapshot.get("delivery_at"))
    when = f" &middot; {_ago((now - sent_at).total_seconds())}" if sent_at else ""
    return (
        f"<h2>Last advisory sent{when}</h2>"
        + row("SMS", delivery.get("sms_status"))
        + row("Voice call", delivery.get("voice_status"))
    )


def _activity_log(device_id: str, now: datetime) -> str:
    """Collapsed by default (see the file docstring: no JS, so a <details> disclosure is the dropdown)."""
    readings = get_recent_readings(device_id, limit=10)
    sms_events = get_recent_sms_events(device_id, limit=10)

    def reading_row(r: dict) -> str:
        temp = _num(r["temperature"], ".1f")
        moisture = _num(r["soil_moisture"], ".0f")
        return (
            f'<div class="row"><span>{escape(_ago((now - r["received_at"]).total_seconds()))}</span>'
            f'<span>moisture {moisture if moisture is not None else "N/A"} '
            f'&middot; {temp if temp is not None else "N/A"}&deg;C</span></div>'
        )

    def sms_row(s: dict) -> str:
        kind = "ok" if s["success"] else "bad"
        label = "Sent" if s["success"] else f'Failed{": " + escape(s["error"]) if s["error"] else ""}'
        return (
            f'<div class="row"><span>{escape(_ago((now - s["attempted_at"]).total_seconds()))}</span>'
            f'<span class="tag {kind}" style="margin:0">{label}</span></div>'
        )

    reading_html = "".join(reading_row(r) for r in readings) or '<p class="note">No readings yet.</p>'
    sms_html = "".join(sms_row(s) for s in sms_events) or '<p class="note">No SMS sent yet.</p>'
    return (
        '<details class="activity-log"><summary>Activity log</summary>'
        f'<h2>Recent readings</h2>{reading_html}'
        f'<h2>Recent SMS</h2>{sms_html}'
        "</details>"
    )


def _sms_banner(event: dict, now: datetime) -> str:
    """
    The notification for the most recent SMS attempt (automatic, or from a problem introduced by hand):
    green if the gateway accepted it, red with the error if it did not, plus the exact text and the
    reading time it was built from.
    """
    if not event:
        return ""
    ok = bool(event.get("ok"))
    sent_at = _parse_time(event.get("sent_at"))
    reading_at = _parse_time(event.get("reading_at"))
    when = _ago((now - sent_at).total_seconds()) if sent_at else "time unknown"
    language = SUPPORTED_LANGUAGES.get(event.get("language"), "English")
    error = escape(str(event.get("error") or "unknown error"))

    if event.get("simulated"):
        problem = event.get("problem")
        what = f"Problem introduced: {escape(str(problem))}" if problem else "Problem introduced"
        if ok:
            head = f"&#10003; {what} &middot; SMS sent &middot; {escape(when)} &middot; {escape(language)}"
        else:
            head = f"&#10007; {what} &middot; SMS FAILED &middot; {escape(when)} &middot; {error}"
        sub = "Made-up readings for the demo, not from the field sensor"
    else:
        if ok:
            head = f"&#10003; SMS sent &middot; {escape(when)} &middot; {escape(language)}"
        else:
            head = f"&#10007; SMS FAILED &middot; {escape(when)} &middot; {error}"
        reading = f" &middot; reading taken {escape(reading_at.strftime('%H:%M:%S'))}" if reading_at else ""
        sub = f"Device {escape(str(event.get('device_id', '?')))}{reading}"

    return (
        f'<div class="sms-banner {"ok" if ok else "bad"}" role="status"><b>{head}</b>'
        f'<div class="sub">{sub}</div>'
        f'<details><summary>The SMS text</summary><pre lang="{escape(str(event.get("language", "en")))}">'
        f'{escape(str(event.get("message", "")))}</pre></details>'
        "</div>"
    )


def _language_row(unlocked: bool, device_id: str) -> str:
    """
    English / Hindi / Kannada chips. Unlocked, they are POST buttons that switch the SMS language
    (automatic SMS and introduced problems alike); locked, they are read-only.
    """
    current = get_sms_language()
    chips = ""
    for code, name in SUPPORTED_LANGUAGES.items():
        active = code == current
        cls = "lang-chip active" if active else "lang-chip"
        if not unlocked:
            chips += f'<span class="{cls}" lang="{code}">{escape(name)}</span>'
        elif active:
            chips += f'<span class="{cls}" lang="{code}" aria-current="true">{escape(name)}</span>'
        else:
            action = f"/settings/sms-language?lang={code}&back=dashboard"
            if device_id:
                action += f"&device={quote(device_id, safe='')}"
            chips += (
                f'<form method="post" action="{escape(action)}">'
                f'<button class="{cls}" type="submit" lang="{code}">{escape(name)}</button></form>'
            )
    return f'<div class="lang-row"><span class="label">SMS language</span>{chips}</div>'


def _demo_panel(
    unlocked: bool,
    device_id: str = None,
    show_key_form: bool = False,
    key_error: bool = False,
    simulating: bool = False,
) -> str:
    """
    The control panel: one button per problem that can be introduced by hand (from the decision
    table in demo_scenarios.py), a "Back to real values" button, and the SMS language chips.
    Plain HTML <form method="post"> buttons -- no JavaScript. They only work because the
    dashboard's CSP allows form posts to its own origin (form-action 'self', see main.py).

    Introducing a problem sends a real SMS, so the panel stays locked until the access key has been
    entered once (main.py then remembers it in a cookie).

    The key box is only shown on request (`show_key_form`: ?unlock=1, or after a wrong key). The
    page reloads itself every few seconds, which would wipe a key half-typed into an always-present
    box, so the pages that show the box do not reload.
    """
    if not unlocked:
        device_field = f'<input type="hidden" name="device" value="{escape(device_id)}">' if device_id else ""
        if show_key_form:
            # The message sits right above the key box (which is auto-focused, so the browser scrolls
            # to it): a notice further away would be scrolled out of sight.
            wrong = (
                '<div class="notice" role="alert" style="margin:12px 0 0"><b>Incorrect access key.</b> '
                "Nothing was sent. Enter the access key, not the device name.</div>"
                if key_error else ""
            )
            unlock = (
                f'{wrong}<form class="unlock" method="get" action="/dashboard">{device_field}'
                '<input type="password" name="key" placeholder="Access key" aria-label="Access key" '
                'autocomplete="off" required autofocus>'
                '<button class="demo-btn" type="submit">Unlock</button></form>'
            )
        else:
            href = "?unlock=1" + (f"&device={quote(device_id, safe='')}" if device_id else "") + "#demo-controls"
            unlock = f'<a class="demo-btn unlock-link" href="{escape(href)}">Enter access key</a>'
        return (
            '<div class="demo-panel" id="demo-controls"><h2 style="margin-top:0">Introduce a problem</h2>'
            '<p class="demo-locked">Enter the access key to unlock buttons that introduce a problem (and send '
            "its SMS) so you can show every alert on demand, and to change the SMS language.</p>"
            f"{unlock}</div>"
        )

    pills = ""
    for name, s in demo_scenarios.get_button_scenarios().items():
        action = f"/demo/scenario/{quote(name, safe='')}?back=dashboard"
        pills += (
            f'<form method="post" action="{escape(action)}">'
            f'<button class="pill" type="submit" title="{escape(s["why_it_matters"])}">{escape(s["title"])}</button></form>'
        )
    # Real device, not a synthetic DEMO-* one: offers a way to test the SMS pipeline (formatting,
    # delivery) against today's genuine field numbers rather than a scenario's fixed sample values.
    # Never fakes a problem -- /demo/test-real-sms only sends if the real reading already has one.
    if device_id and not device_id.startswith("DEMO"):
        action = f"/demo/test-real-sms?device={quote(device_id, safe='')}&back=dashboard"
        pills += (
            f'<form method="post" action="{escape(action)}">'
            f'<button class="pill" type="submit" title="Sends a real SMS built from {escape(device_id)}&#8217;s most '
            "recent real reading, forced past the cooldown. Only sends if that reading currently has an active "
            'alert -- nothing is faked.">Test SMS with real data</button></form>'
        )
    back = (
        f'<form method="post" action="/demo/reset?back=dashboard"><button class="pill{" primary" if simulating else ""}" '
        'type="submit">&#8634; Back to real values</button></form>'
    )
    lock = '<form method="post" action="/dashboard/lock"><button class="pill quiet" type="submit">Lock</button></form>'
    return (
        '<div class="demo-panel" id="demo-controls">'
        '<div class="panel-head"><h2>Introduce a problem <span class="hint">each button sends an SMS</span></h2>'
        f'<div class="panel-actions">{back}{lock}</div></div>'
        f'<div class="pill-row">{pills}</div>'
        f"{_language_row(unlocked, device_id)}</div>"
    )


def _simulation_notice(unlocked: bool) -> str:
    """Shown on a simulated device's page: makes clear these readings are made up, and how to get back."""
    if unlocked:
        back = (
            '<form method="post" action="/demo/reset?back=dashboard">'
            '<button class="pill primary" type="submit">&#8634; Back to real values</button></form>'
        )
    else:
        back = '<a class="pill primary" href="/dashboard">Back to real values</a>'
    return (
        '<div class="sim-notice" role="status"><span><b>Simulated problem.</b> These readings are made up '
        f"for the demo &mdash; they are not from the field sensor.</span>{back}</div>"
    )


def _device_nav(device_ids: list, selected: str) -> str:
    # Each introduced problem leaves a DEMO-* device behind. They are not real devices: keep them out of
    # the switcher, and on their own page the "Back to real values" button replaces it.
    if selected and selected.startswith("DEMO"):
        return ""
    device_ids = [d for d in device_ids if not d.startswith("DEMO")]
    if len(device_ids) < 2:
        return ""
    links = []
    for d in device_ids:
        current = ' aria-current="page"' if d == selected else ""
        links.append(f'<a href="?device={quote(d, safe="")}"{current}>{escape(d)}</a>')
    return f'<nav class="devices" aria-label="Devices">{"".join(links)}</nav>'


def _empty_body(notice: str) -> str:
    return (
        f"{notice}<h2>Waiting for the first sensor reading</h2>"
        "<p>Nothing has been received yet. Power on the field node; its first reading appears "
        "here within a few seconds.</p>"
    )


def _status(snapshot: dict, now: datetime, simulated: bool = False):
    """(css class, headline, indicator-dot classes, age in seconds, stale?) for one device snapshot."""
    codes = list(snapshot.get("alert_codes") or [])
    updated = _parse_time(snapshot.get("updated_at"))
    age_seconds = (now - updated).total_seconds() if updated else None
    # A simulated problem is static by nature (nothing keeps reporting), so it never counts as "no recent data".
    stale = age_seconds is not None and age_seconds > STALE_AFTER_MINUTES * 60 and not simulated

    severities = {ALERTS.get(c, ("warn", c))[0] for c in codes}
    if stale:
        cls, headline = "off", "No recent data"
    elif "bad" in severities:
        cls, headline = "bad", "Sensor fault"
    elif severities & {"warn", "wet"}:
        cls, headline = "warn", "Attention needed"
    else:
        cls, headline = "ok", "All clear"
    dot = {"off": "live off", "bad": "live bad", "warn": "live warn"}.get(cls, "live")
    return cls, headline, dot, age_seconds, stale


def _snapshot_body(device_id: str, snapshot: dict, now: datetime) -> str:
    facts = snapshot.get("facts") or {}
    codes = list(snapshot.get("alert_codes") or [])

    simulated = device_id.startswith("DEMO")
    cls, headline, dot, age_seconds, stale = _status(snapshot, now, simulated)
    seen = "Simulated reading" if simulated else (
        f"Last update {_ago(age_seconds)}" if age_seconds is not None else "Update time unknown"
    )

    temp, humidity = _num(facts.get("temperature_c"), ".1f"), _num(facts.get("humidity_percent"), ".0f")
    dht_fault = "SENSOR_FAULT_DHT22" in codes
    rain_now = facts.get("rain_detected_now")
    light = _num(facts.get("light_level"), ".0f")

    days = facts.get("days_since_sowing")
    if isinstance(days, int):
        maturity = (facts.get("crop_profile") or CROP_PROFILE).get("maturity_days", CROP_PROFILE["maturity_days"])
        crop = f'<div class="value">Day {days}</div><div class="sub">{escape(_stage_summary(days, maturity))}</div>'
    else:
        crop = _na()

    light_html = (
        f'<div class="value">{light} <span class="na">/ 100</span></div>'
        if light is not None else _na()
    )
    cards = (
        _moisture_card(facts)
        + _dht_card("Temperature", f"{temp} &deg;C" if temp is not None else None, dht_fault)
        + _dht_card("Humidity", f"{humidity} %" if humidity is not None else None, dht_fault)
        + f'<div class="card"><div class="label">Rain right now</div><div class="value">'
          f'{"Yes" if rain_now else "No" if rain_now is False else "Unknown"}</div></div>'
        + _weather_card(facts, codes)
        + _mandi_card(facts)
        + f'<div class="card"><div class="label">Crop age</div>{crop}</div>'
        + f'<div class="card"><div class="label">Ambient light</div>{light_html}'
          '<div class="sub">informational only</div></div>'
    )

    return (
        f'<div class="status {cls}"><span class="{dot}"></span>{headline}</div>'
        f'<p class="subtitle">{escape(seen)}</p>'
        f'<div class="grid{" stale" if stale else ""}">{cards}</div>'
        f"<h2 id=\"active-alerts\">Active alerts</h2>{_alerts_section(codes)}"
        f"{_delivery_section(snapshot, now)}"
        f'<p class="muted">Rule version: {escape(str(facts.get("rule_version", "unknown")))} '
        f"&middot; Device: {escape(device_id)}</p>"
        f"{_activity_log(device_id, now)}"
    )


def _default_device(device_ids: list) -> str:
    """
    The device to show when none is chosen: the most recently updated REAL device,
    not just whichever reported first. Otherwise a DEMO-* device that happened to
    report first (a demo button, or an early reading after a restart) would be shown
    as if it were the live field node, with old numbers.

    Uses one query (get_last_updated_map) rather than a get_snapshot() call per
    candidate device -- the full snapshot for only the winning device is fetched
    afterwards, by the caller.
    """
    real = [d for d in device_ids if not d.startswith("DEMO")]
    pool = real or device_ids
    updated = get_last_updated_map()
    return max(pool, key=lambda d: updated.get(d) or "")


def render_dashboard(
    device_id: str = None,
    now: datetime = None,
    key: str = None,
    key_error: bool = False,
    unlock: bool = False,
    unlocked: bool = False,
    error: str = None,
) -> str:
    now = now or datetime.now()
    unlocked = unlocked or bool(key)          # `key` (the older way of passing it) also means unlocked
    device_ids = get_dashboard_device_ids()

    notice = ""
    if device_id and device_id not in device_ids:
        notice += (
            f'<div class="notice">No device called <b>{escape(device_id)}</b> has reported. '
            "Showing the default device instead.</div>"
        )
        device_id = None
    if error == "no-problem":
        notice += (
            '<div class="notice">That device&#8217;s most recent real reading has no active alert right now, '
            "so there is nothing to send. Use one of the buttons below to force a specific scenario instead.</div>"
        )
    if not device_id and device_ids:
        device_id = _default_device(device_ids)

    snapshot = get_snapshot(device_id) if device_id else None
    simulating = bool(snapshot) and device_id.startswith("DEMO")
    banner = _sms_banner(get_last_sms_event(), now)

    # While the key box is showing (?unlock=1, or after a wrong key) the page must NOT reload itself:
    # a reload every 15 s would wipe whatever is being typed into it.
    show_key_form = (unlock or key_error) and not unlocked
    panel = _demo_panel(unlocked, device_id, show_key_form=show_key_form, key_error=key_error, simulating=simulating)
    auto_refresh = "" if show_key_form else f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">' + "\n"

    # controls first (what you operate), then the notification, then the readings
    if snapshot:
        body = (
            panel + banner + (_simulation_notice(unlocked) if simulating else "") + notice
            + _device_nav(device_ids, device_id) + _snapshot_body(device_id, snapshot, now)
        )
        _, status_label, status_dot, _, _ = _status(snapshot, now, simulating)
        if simulating:
            status_label = "Simulated problem"
    else:
        body = panel + banner + _empty_body(notice)
        status_label, status_dot = "Waiting for data", "live off"
    crop = str(CROP_PROFILE.get("crop", "crop")).capitalize()

    # Manual refresh keeps the device being viewed.
    refresh_href = f"?device={quote(device_id, safe='')}" if device_id else "?"

    uptime_str = _format_uptime(get_uptime_seconds())
    started_str = get_server_start_time().strftime("%H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{auto_refresh}<title>Crop Advisory v5 - Dashboard</title>
<style>{CSS}</style>
</head>
<body>
<div class="app-shell">
  <main class="workspace">
    <header class="topbar">
      <div>
        <p class="eyebrow">Field intelligence</p>
        <h1>Crop Advisory Dashboard</h1>
        <p class="subtitle">{escape(LOCATION_NAME)} &middot; {escape(crop)} &middot; updates every {REFRESH_SECONDS}s
          <a class="refresh-btn" href="{escape(refresh_href)}">Refresh</a></p>
      </div>
      <div class="topbar-metas">
        <div class="topbar-meta"><span class="{status_dot}"></span><span><strong>Field monitor</strong>{escape(status_label)}</span></div>
        <div class="topbar-meta"><span><strong>Server uptime</strong>Up {escape(uptime_str)} &middot; since {escape(started_str)}</span></div>
      </div>
    </header>
    <section class="content" id="field-status">
      {body}
    </section>
  </main>
</div>
</body>
</html>
"""
