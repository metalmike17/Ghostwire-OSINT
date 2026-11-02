#!/usr/bin/env python3
"""GHOSTWIRE - an OSINT toolkit front-end built with Gooey.

Each sidebar module either wraps a well-known CLI tool (Maigret, Sherlock,
Holehe, PhoneInfoga, Instaloader) or queries a public data source directly.
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import requests
from gooey import Gooey, GooeyParser

# Gooey's per-field label/help text colors are NOT controlled by the @Gooey()
# theme kwargs below - they're a separate hardcoded default meant for a light
# background (#000000 labels, #363636 help text), so on our dark theme they
# were nearly invisible. Patch the real default here instead of passing
# gooey_options={'label_color': ..., 'help_color': ...} to every single field.
import gooey.python_bindings.argparse_to_json as _gooey_json
_gooey_json.item_default["label_color"] = "#F2F4F8"
_gooey_json.item_default["help_color"] = "#A9B4C2"

APP_NAME = "GHOSTWIRE"
VENV_BIN = Path(sys.executable).parent
TOOLS_DIR = Path.home() / ".local/share/ghostwire-tools"
HARVESTER_DIR = TOOLS_DIR / "theHarvester"
PHOTON_DIR = TOOLS_DIR / "Photon"
DOCS = os.path.expanduser("~/Documents")
HTTP_TIMEOUT = 20
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Ghostwire/0.1"}

DISCLAIMER = (
    "Use only on people, accounts and systems you are authorized to investigate, "
    "and follow the law and each service's terms. Results come from public sources "
    "and may be wrong or out of date."
)


def out(*a):
    print(*a, flush=True)


def head(title):
    out(f"\n=== {title} ===")


def find_tool(name):
    for cand in (VENV_BIN / name, Path.home() / ".local/bin" / name):
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if found:
        return found
    out(f"ERROR: '{name}' is not installed.")
    sys.exit(1)


def run(cmd, skip=None):
    out("$", shlex.join(cmd))
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
    )
    for line in proc.stdout:
        if skip and re.search(skip, line):
            continue
        out(line.rstrip())
    return proc.wait()


def get(url, **kw):
    kw.setdefault("timeout", HTTP_TIMEOUT)
    kw.setdefault("headers", UA)
    return requests.get(url, **kw)


def targets(text):
    return shlex.split(text or "")


# --------------------------------------------------------------------------
# Username
# --------------------------------------------------------------------------
def do_username(a):
    names = targets(a.usernames)
    if a.engine in ("Maigret", "Both"):
        head("Maigret")
        cmd = [find_tool("maigret"), *names, "--timeout", str(a.timeout),
               "--no-progressbar", "--no-color"]
        cmd += ["-a"] if a.all_sites else ["--top-sites", str(a.top_sites)]
        if a.permute and len(names) >= 2:
            cmd.append("--permute")
        if a.no_recursion:
            cmd.append("--no-recursion")
        if a.proxy:
            cmd += ["--proxy", a.proxy]
        for flag, on in (("-H", a.html), ("-P", a.pdf), ("-C", a.csv), ("-T", a.txt)):
            if on:
                cmd.append(flag)
        if a.folder:
            cmd += ["--folderoutput", a.folder]
        run(cmd)
    if a.engine in ("Sherlock", "Both"):
        head("Sherlock")
        cmd = [find_tool("sherlock"), "--no-color", "--print-found", "--timeout", str(a.timeout)]
        if a.proxy:
            cmd += ["--proxy", a.proxy]
        if a.folder and (a.csv or a.txt):
            cmd += ["--folderoutput", a.folder]
            cmd += [f for f, on in (("--csv", a.csv), ("--txt", a.txt)) if on]
        run(cmd + names)


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]+)$")


def check_mx(domain):
    import dns.resolver

    try:
        recs = dns.resolver.resolve(domain, "MX", lifetime=8)
        return sorted(str(r.exchange).rstrip(".") for r in recs)
    except Exception as e:
        return f"no MX records ({type(e).__name__})"


def gravatar(email):
    h = hashlib.md5(email.strip().lower().encode()).hexdigest()
    r = get(f"https://gravatar.com/{h}.json")
    if r.status_code != 200:
        return None
    return r.json().get("entry", [{}])[0]


def do_email(a):
    for email in targets(a.emails):
        head(email)
        m = EMAIL_RE.match(email)
        if not m:
            out("Not a valid email address, skipping.")
            continue
        out("Mail servers:", check_mx(m.group(1)))
        try:
            g = gravatar(email)
        except requests.RequestException as e:
            g = None
            out("Gravatar lookup failed:", e)
        if g:
            out("Gravatar profile found:")
            for k in ("displayName", "preferredUsername", "aboutMe", "currentLocation", "profileUrl"):
                if g.get(k):
                    out(f"  {k}: {g[k]}")
            for acct in g.get("accounts", []):
                out(f"  linked: {acct.get('name')} -> {acct.get('url')}")
        else:
            out("No public Gravatar profile.")
        if a.holehe:
            head("Holehe - sites where this email is registered")
            cmd = [find_tool("holehe"), "--no-color", "--no-clear", "-T", str(a.timeout)]
            if a.only_used:
                cmd.append("--only-used")
            if not a.password_recovery:
                cmd.append("-NP")
            run(cmd + [email], skip=r"it/s\]|^Twitter : |^Github : |BTC Donations|^\s*$")


# --------------------------------------------------------------------------
# Phone
# --------------------------------------------------------------------------
def do_phone(a):
    for number in targets(a.numbers):
        head(number)
        if not number.startswith("+"):
            out("Use international format, e.g. +14155552671. Skipping.")
            continue
        run([find_tool("phoneinfoga"), "scan", "-n", number])


# --------------------------------------------------------------------------
# Instagram (public data via Instaloader)
# --------------------------------------------------------------------------
def do_instagram(a):
    import instaloader

    for user in targets(a.usernames):
        user = user.lstrip("@")
        head(f"Instagram: {user}")
        L = instaloader.Instaloader(
            quiet=True, download_pictures=False, save_metadata=False,
            sleep=False, max_connection_attempts=1, request_timeout=30,
        )
        if a.login_user:
            try:
                L.load_session_from_file(a.login_user)
                out(f"Using saved session for {a.login_user}")
            except FileNotFoundError:
                out(f"No saved session for {a.login_user}. Create one once in a terminal with:")
                out(f"  {find_tool('instaloader')} --login {a.login_user}")
                return
        try:
            p = instaloader.Profile.from_username(L.context, user)
        except instaloader.exceptions.ProfileNotExistsException:
            out("Profile does not exist.")
            continue
        except Exception as e:
            out(f"Lookup failed: {e}")
            out("Instagram often blocks anonymous requests. Try a saved login session.")
            continue
        try:
            out(f"Name:       {p.full_name}")
            out(f"User ID:    {p.userid}")
            out(f"Private:    {p.is_private}   Verified: {p.is_verified}")
            out(f"Followers:  {p.followers}   Following: {p.followees}   Posts: {p.mediacount}")
            out(f"Bio:        {p.biography}")
            out(f"External:   {p.external_url}")
            out(f"Profile pic: {p.profile_pic_url}")
        except Exception as e:
            out(f"Instagram stopped the lookup part-way ({type(e).__name__}). "
                "You are probably rate-limited - wait a while or use a saved login session.")
            continue
        if a.download:
            if p.is_private and not a.login_user:
                out("Profile is private - cannot download posts without following it.")
                continue
            folder = a.folder or DOCS
            run(
                [find_tool("instaloader"), "--quiet", "--count", str(a.count),
                 "--dirname-pattern", os.path.join(folder, "instagram", "{target}"),
                 *(["--login", a.login_user] if a.login_user else []), "--", user]
            )
            out(f"Saved to {os.path.join(folder, 'instagram', user)}")


# --------------------------------------------------------------------------
# Domain
# --------------------------------------------------------------------------
def do_domain(a):
    import dns.resolver

    for domain in targets(a.domains):
        domain = re.sub(r"^https?://", "", domain).split("/")[0].lower()
        head(domain)
        if a.whois:
            out("--- WHOIS ---")
            run(["whois", domain])
        if a.dns:
            out("--- DNS records ---")
            for rtype in ("A", "AAAA", "MX", "NS", "TXT", "SOA", "CNAME"):
                try:
                    for r in dns.resolver.resolve(domain, rtype, lifetime=8):
                        out(f"{rtype:6} {r.to_text()}")
                except Exception:
                    pass
        if a.headers:
            out("--- HTTP headers ---")
            try:
                r = requests.get(f"https://{domain}", headers=UA, timeout=HTTP_TIMEOUT)
                out(f"{r.url} -> {r.status_code}")
                for k, v in r.headers.items():
                    out(f"{k}: {v}")
            except requests.RequestException as e:
                out("Request failed:", e)
            for path in ("robots.txt", ".well-known/security.txt"):
                try:
                    r = get(f"https://{domain}/{path}")
                    if r.status_code == 200:
                        out(f"\n--- /{path} ---\n{r.text[:1500]}")
                except requests.RequestException:
                    pass
        subs = set()
        if a.subdomains:
            subfinder = shutil.which("subfinder") or str(Path.home() / ".local/bin/subfinder")
            if Path(subfinder).exists():
                out("--- Subdomains (subfinder) ---")
                try:
                    # subfinder's own -timeout is per-request, not an overall cap, so we
                    # enforce a hard wall-clock budget here too and fall back on crt.sh.
                    proc = subprocess.run(
                        [subfinder, "-d", domain, "-silent", "-timeout", str(a.timeout)],
                        capture_output=True, text=True, timeout=max(a.timeout * 3, 45),
                    )
                    for line in proc.stdout.splitlines():
                        line = line.strip().lower()
                        if line:
                            subs.add(line)
                            out(line)
                    out(f"{len(subs)} unique names")
                except subprocess.TimeoutExpired:
                    out("subfinder took too long and was stopped - falling back to crt.sh.")
                    subfinder = None
            if not subfinder or not Path(subfinder).exists():
                out("--- Subdomains (certificate transparency via crt.sh) ---")
                out("(install subfinder for faster, more thorough results)")
                try:
                    r = get(f"https://crt.sh/?q=%25.{domain}&output=json", timeout=45)
                    for row in r.json():
                        for n in row["name_value"].splitlines():
                            subs.add(n.lstrip("*.").lower())
                    for n in sorted(subs):
                        out(n)
                    out(f"{len(subs)} unique names")
                except Exception as e:
                    out("crt.sh lookup failed (it is often slow or rate-limited):", e)

            if a.probe_live and subs:
                httpx_bin = shutil.which("httpx") or str(Path.home() / ".local/bin/httpx")
                if Path(httpx_bin).exists():
                    out("\n--- Live hosts (httpx) ---")
                    try:
                        proc = subprocess.run(
                            [httpx_bin, "-silent", "-status-code", "-title", "-tech-detect",
                             "-timeout", str(min(a.timeout, 15))],
                            input="\n".join(sorted(subs)), capture_output=True, text=True,
                            timeout=max(len(subs) * 3, 60),
                        )
                        for line in proc.stdout.splitlines():
                            out(line)
                    except subprocess.TimeoutExpired:
                        out("httpx took too long and was stopped.")
                else:
                    out("httpx is not installed - skipping live-host probing.")

        if a.harvester:
            out("\n--- theHarvester (emails, hosts, IPs from search engines) ---")
            bin_path = HARVESTER_DIR / "bin" / "theHarvester"
            if not bin_path.exists():
                out(f"theHarvester not found at {HARVESTER_DIR}. See the README for setup.")
            else:
                env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONPATH=str(HARVESTER_DIR))
                proc = subprocess.Popen(
                    [sys.executable, str(bin_path), "-d", domain, "-b", a.harvester_sources,
                     "-l", str(a.harvester_limit)],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                )
                for line in proc.stdout:
                    out(line.rstrip())
                proc.wait()


# --------------------------------------------------------------------------
# IP
# --------------------------------------------------------------------------
def do_ip(a):
    for host in targets(a.hosts):
        head(host)
        try:
            ip = socket.gethostbyname(host)
        except OSError as e:
            out("Cannot resolve:", e)
            continue
        out("IP:", ip)
        try:
            out("Reverse DNS:", socket.gethostbyaddr(ip)[0])
        except OSError:
            out("Reverse DNS: none")
        try:
            d = get(f"https://ipinfo.io/{ip}/json").json()
            for k in ("city", "region", "country", "loc", "org", "postal", "timezone"):
                if d.get(k):
                    out(f"{k}: {d[k]}")
            if d.get("loc"):
                out(f"map: https://www.openstreetmap.org/?mlat={d['loc'].replace(',', '&mlon=')}&zoom=10")
        except Exception as e:
            out("ipinfo lookup failed:", e)


# --------------------------------------------------------------------------
# Wayback Machine
# --------------------------------------------------------------------------
def do_wayback(a):
    for url in targets(a.urls):
        head(url)
        try:
            for label, limit in (("Earliest", 1), ("Latest", -a.count)):
                r = get(
                    "https://web.archive.org/cdx/search/cdx",
                    params={"url": url, "output": "json", "limit": limit,
                            "fl": "timestamp,statuscode,original", "collapse": "digest"},
                    timeout=40,
                )
                rows = r.json()[1:]
                out(f"{label}:")
                if not rows:
                    out("  no snapshots")
                for ts, status, orig in rows:
                    out(f"  {ts[:4]}-{ts[4:6]}-{ts[6:8]} [{status}] https://web.archive.org/web/{ts}/{orig}")
        except Exception as e:
            out("Wayback lookup failed:", e)


# --------------------------------------------------------------------------
# File metadata
# --------------------------------------------------------------------------
def _deg(vals, ref):
    d, m, s = (float(x) for x in vals)
    v = d + m / 60 + s / 3600
    return -v if ref in ("S", "W") else v


def pillow_metadata(path):
    from PIL import ExifTags, Image

    exif = Image.open(path).getexif()
    data = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
    data.update({ExifTags.TAGS.get(k, k): v for k, v in exif.get_ifd(0x8769).items()})
    for k, v in data.items():
        out(f"{k}: {str(v)[:150]}")
    gps = exif.get_ifd(0x8825)
    if 2 in gps and 4 in gps:
        lat, lon = _deg(gps[2], gps.get(1)), _deg(gps[4], gps.get(3))
        out(f"\nGPS: {lat:.6f}, {lon:.6f}")
        out(f"map: https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=15")
    elif not data:
        out("No EXIF data found.")


def do_metadata(a):
    exiftool = shutil.which("exiftool")
    if not exiftool:
        out("(exiftool not installed - using the built-in image reader. "
            "Install 'perl-Image-ExifTool' for PDFs, Office files and video.)")
    for path in a.files.split(os.pathsep) if a.files else []:
        head(path)
        if exiftool:
            run([exiftool, "-a", "-u", "-g1", path])
        else:
            try:
                pillow_metadata(path)
            except Exception as e:
                out("Cannot read metadata:", e)


# --------------------------------------------------------------------------
# GitHub
# --------------------------------------------------------------------------
def do_github(a):
    hdr = dict(UA)
    if os.environ.get("GITHUB_TOKEN"):
        hdr["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    api = "https://api.github.com"
    for user in targets(a.usernames):
        head(f"GitHub: {user}")
        r = get(f"{api}/users/{user}", headers=hdr)
        if r.status_code == 404:
            out("User not found.")
            continue
        if r.status_code != 200:
            out(f"GitHub API error {r.status_code}: {r.json().get('message')}")
            continue
        u = r.json()
        for k in ("name", "company", "location", "email", "blog", "twitter_username",
                  "bio", "public_repos", "followers", "following", "created_at"):
            if u.get(k):
                out(f"{k}: {u[k]}")
        orgs = get(f"{api}/users/{user}/orgs", headers=hdr).json()
        if orgs:
            out("orgs:", ", ".join(o["login"] for o in orgs))
        out("\nRecently pushed repos:")
        repos = get(f"{api}/users/{user}/repos?per_page=100&sort=pushed", headers=hdr).json()
        for repo in repos[: a.repos]:
            out(f"  {repo['name']} ({repo.get('language')}) - {repo['html_url']}")
        if a.emails:
            out("\nEmails seen in recent public commits:")
            events = get(f"{api}/users/{user}/events/public?per_page=100", headers=hdr).json()
            seen = {}
            for ev in events if isinstance(events, list) else []:
                for c in ev.get("payload", {}).get("commits", []):
                    em = c["author"]["email"]
                    if not em.endswith("noreply.github.com"):
                        seen[em] = c["author"]["name"]
            for em, name in seen.items():
                out(f"  {em} ({name})")
            if not seen:
                out("  none (commit emails are often hidden)")


# --------------------------------------------------------------------------
# Breach check
# --------------------------------------------------------------------------
def xon_check(email):
    r = get(f"https://api.xposedornot.com/v1/check-email/{email}", timeout=30)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    data = r.json()
    return data.get("breaches", [[]])[0] if data.get("breaches") else []


def xon_risk(email):
    try:
        r = get(f"https://api.xposedornot.com/v1/breach-analytics?email={email}", timeout=30)
        if r.status_code != 200:
            return None
        risk = r.json().get("BreachMetrics", {}).get("risk", [{}])
        return risk[0] if risk else None
    except Exception:
        return None


def hibp_check(email, api_key):
    r = requests.get(
        f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
        headers={**UA, "hibp-api-key": api_key},
        params={"truncateResponse": "false"},
        timeout=30,
    )
    if r.status_code == 404:
        return []
    if r.status_code == 401:
        out("HaveIBeenPwned rejected the API key (401 Unauthorized).")
        return None
    r.raise_for_status()
    return r.json()


def pwned_password_count(password):
    """k-anonymity check: only the first 5 hex chars of the SHA-1 hash leave
    this machine. The full password and full hash are never sent anywhere."""
    sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]
    r = get(f"https://api.pwnedpasswords.com/range/{prefix}", timeout=20)
    r.raise_for_status()
    for line in r.text.splitlines():
        h, count = line.split(":")
        if h == suffix:
            return int(count)
    return 0


def do_breach(a):
    for email in targets(a.emails):
        head(email)
        m = EMAIL_RE.match(email)
        if not m:
            out("Not a valid email address, skipping.")
            continue

        if a.engine in ("XposedOrNot (free, no key)", "Both"):
            out("--- XposedOrNot ---")
            try:
                breaches = xon_check(email)
            except requests.RequestException as e:
                out("Lookup failed:", e)
                breaches = None
            if breaches is not None:
                if breaches:
                    out(f"Found in {len(breaches)} breach(es):")
                    out(", ".join(breaches))
                    risk = xon_risk(email)
                    if risk:
                        out(f"Risk: {risk.get('risk_label')} ({risk.get('risk_score')}/100)")
                else:
                    out("No breaches found.")

        if a.engine in ("HaveIBeenPwned (needs API key)", "Both"):
            out("--- HaveIBeenPwned ---")
            key = a.hibp_key or os.environ.get("HIBP_API_KEY")
            if not key:
                out("No API key given. Get one at https://haveibeenpwned.com/API/Key "
                    "and paste it in the field above, or set HIBP_API_KEY.")
            else:
                try:
                    breaches = hibp_check(email, key)
                except requests.RequestException as e:
                    out("Lookup failed:", e)
                    breaches = None
                if breaches:
                    out(f"Found in {len(breaches)} breach(es):")
                    for b in breaches:
                        out(f"  {b['Name']} ({b.get('BreachDate')}) - {b.get('DataClasses') and ', '.join(b['DataClasses'])}")
                elif breaches == []:
                    out("No breaches found.")

    if a.password:
        head("Password check (Pwned Passwords)")
        out("Only the first 5 characters of the password's SHA-1 hash are sent - "
            "the password itself never leaves this machine.")
        try:
            n = pwned_password_count(a.password)
        except requests.RequestException as e:
            out("Lookup failed:", e)
        else:
            if n:
                out(f"This password has appeared in {n:,} previously breached password(s). Do not use it.")
            else:
                out("Not found in known breach dumps. That alone doesn't make it a strong password.")


# --------------------------------------------------------------------------
# Network (Nmap)
# --------------------------------------------------------------------------
NMAP_PROFILES = {
    "Quick (top 100 ports)": ["-T4", "-F"],
    "Default (top 1000 ports, service/version)": ["-T4", "-sV"],
    "Thorough (all ports, service/version, OS guess)": ["-T4", "-p-", "-sV", "-O"],
    "Ping sweep only (host discovery, no port scan)": ["-sn"],
}


def do_network(a):
    nmap = shutil.which("nmap")
    if not nmap:
        out("nmap is not installed. Install it with:")
        out("  sudo dnf install nmap")
        return
    out("Only scan hosts and networks you own or are explicitly authorized to test.")
    for target in targets(a.targets):
        head(target)
        cmd = [nmap, *NMAP_PROFILES[a.profile]]
        if a.profile != "Ping sweep only (host discovery, no port scan)" and a.ports:
            cmd += ["-p", a.ports]
        if a.script:
            cmd += ["--script", a.script]
        if a.no_ping:
            cmd.append("-Pn")
        if a.folder and a.save:
            safe = re.sub(r"[^\w.-]", "_", target)
            cmd += ["-oN", os.path.join(a.folder, f"nmap_{safe}.txt")]
        cmd.append(target)
        rc = run(cmd)
        if rc != 0:
            out(f"nmap exited with code {rc}. It may need elevated privileges for this scan type "
                "(OS detection, SYN scan) - try running the app with sudo, or switch profiles.")


# --------------------------------------------------------------------------
# Crawl (Photon)
# --------------------------------------------------------------------------
def do_crawl(a):
    script = PHOTON_DIR / "photon.py"
    if not script.exists():
        out(f"Photon not found at {PHOTON_DIR}. See the README for setup.")
        return
    for url in targets(a.urls):
        head(url)
        out("Crawling a site repeatedly or aggressively can look like abuse to its owner. "
            "Keep the crawl depth reasonable and only target sites you're authorized to probe.")
        outdir = os.path.join(a.folder or DOCS, "photon", re.sub(r"[^\w.-]", "_", url))
        cmd = [sys.executable, str(script), "-u", url, "-l", str(a.level),
               "-t", str(a.threads), "--timeout", str(a.timeout), "-o", outdir]
        if a.only_urls:
            cmd.append("--only-urls")
        if a.dns:
            cmd.append("--dns")
        if a.keys:
            cmd.append("--keys")
        if a.wayback:
            cmd.append("--wayback")
        rc = run(cmd)
        if rc == 0 and os.path.isdir(outdir):
            out(f"\nSaved to {outdir}:")
            for name in sorted(os.listdir(outdir)):
                out(f"  {name}")


# --------------------------------------------------------------------------
# GUI definition
# --------------------------------------------------------------------------
def add_proxy_timeout(g, timeout=30):
    g.add_argument("--timeout", metavar="Timeout (seconds)", type=int, default=timeout,
                   widget="IntegerField", gooey_options={"min": 1, "max": 600})


# Cyberpunk palette. The Gooey/wx header strip keeps its native light text color
# (not themeable), so it stays a light "glass" bar; everything we DO control -
# body, sidebar, footer and the terminal/output pane - goes dark with neon accents.
NEON_CYAN = "#00C8D6"
NEON_MAGENTA = "#FF2BD6"
INK = "#0D0F14"
PANEL = "#15181F"
TERMINAL = "#0A0C10"


GOOEY_OPTS = dict(
    program_name=APP_NAME,
    program_description="OSINT toolkit - " + DISCLAIMER,
    navigation="SIDEBAR",
    sidebar_title="Modules",
    default_size=(1100, 780),
    richtext_controls=True,
    show_success_modal=False,
    image_dir=str(Path(__file__).parent / "theme" / "images"),
    language_dir=str(Path(__file__).parent / "theme" / "lang"),
    header_bg_color=INK,
    body_bg_color=INK,
    sidebar_bg_color=PANEL,
    footer_bg_color=PANEL,
    terminal_panel_color=TERMINAL,
    terminal_font_color=NEON_CYAN,
    terminal_font_family="monospace",
    error_color=NEON_MAGENTA,
    menu=[{"name": "Help", "items": [{
        "type": "AboutDialog", "menuTitle": "About", "name": APP_NAME,
        "description": "OSINT toolkit built with Gooey", "version": "0.1",
        "copyright": "", "website": "", "developer": "", "license": DISCLAIMER}]}],
)


def register_modules(sub):
    """Add every free module as a sub-parser. GHOSTWIRE PRO calls this too."""

    # Username
    p = sub.add_parser("Username", help="Find accounts by username (Maigret, Sherlock)")
    g = p.add_argument_group("Search")
    g.add_argument("usernames", metavar="Usernames", help="One or more, separated by spaces")
    g.add_argument("--engine", metavar="Engine", widget="Dropdown", default="Maigret",
                   choices=["Maigret", "Sherlock", "Both"],
                   help="Maigret checks more sites and extracts profile details")
    g.add_argument("--top-sites", metavar="Top N sites (Maigret)", type=int, default=500,
                   widget="IntegerField", gooey_options={"min": 1, "max": 5000})
    g.add_argument("--all-sites", metavar="All sites (Maigret, slow)", action="store_true")
    g.add_argument("--permute", metavar="Try name combinations (2+ names)", action="store_true")
    g.add_argument("--no-recursion", metavar="Don't follow discovered IDs", action="store_true")
    add_proxy_timeout(g, 30)
    g.add_argument("--proxy", metavar="Proxy", help="Optional, e.g. socks5://127.0.0.1:1080")
    o = p.add_argument_group("Reports")
    o.add_argument("--folder", metavar="Save to folder", widget="DirChooser", default=DOCS)
    o.add_argument("--html", metavar="HTML report (Maigret)", action="store_true")
    o.add_argument("--pdf", metavar="PDF report (Maigret)", action="store_true")
    o.add_argument("--csv", metavar="CSV", action="store_true")
    o.add_argument("--txt", metavar="Text", action="store_true")

    # Email
    p = sub.add_parser("Email", help="Email footprint (Holehe, Gravatar, MX)")
    g = p.add_argument_group("Search")
    g.add_argument("emails", metavar="Emails", help="One or more, separated by spaces")
    g.add_argument("--holehe", metavar="Check site registrations (Holehe)",
                   action="store_true",
                   gooey_options={"initial_value": True})
    g.add_argument("--only-used", metavar="Only show sites where registered",
                   action="store_true",
                   gooey_options={"initial_value": True})
    g.add_argument("--password-recovery", metavar="Include password-recovery checks",
                   action="store_true",
                   help="Off by default: these can trigger 'reset your password' emails to the target")
    add_proxy_timeout(g, 10)

    # Phone
    p = sub.add_parser("Phone", help="Phone number info (PhoneInfoga)")
    p.add_argument("numbers", metavar="Phone numbers",
                   help="International format, e.g. +14155552671, separated by spaces")

    # Instagram
    p = sub.add_parser("Instagram", help="Public Instagram profile info (Instaloader)")
    g = p.add_argument_group("Profile")
    g.add_argument("usernames", metavar="Usernames", help="Separated by spaces")
    g.add_argument("--login-user", metavar="Saved login session (optional)",
                   help="Instagram often blocks anonymous lookups. Run "
                        "'instaloader --login YOURUSER' once in a terminal first")
    d = p.add_argument_group("Download")
    d.add_argument("--download", metavar="Download recent posts", action="store_true")
    d.add_argument("--count", metavar="Number of posts", type=int, default=10, widget="IntegerField")
    d.add_argument("--folder", metavar="Save to folder", widget="DirChooser", default=DOCS)

    # Domain
    p = sub.add_parser("Domain", help="WHOIS, DNS, subdomains, recon (subfinder, httpx, theHarvester)")
    g = p.add_argument_group("Basics")
    g.add_argument("domains", metavar="Domains", help="e.g. example.com, separated by spaces")
    for flag, label in (("whois", "WHOIS"), ("dns", "DNS records"),
                        ("headers", "HTTP headers, robots.txt, security.txt")):
        g.add_argument(f"--{flag}", metavar=label, action="store_true",
                       gooey_options={"initial_value": True})
    add_proxy_timeout(g, 20)

    s = p.add_argument_group("Subdomains")
    s.add_argument("--subdomains", metavar="Enumerate subdomains (subfinder, falls back to crt.sh)",
                   action="store_true", gooey_options={"initial_value": True})
    s.add_argument("--probe-live", metavar="Probe which subdomains are live (httpx)",
                   action="store_true", gooey_options={"initial_value": True})

    h = p.add_argument_group("theHarvester",
                             "Emails, hosts and IPs gathered from search engines and public sources")
    h.add_argument("--harvester", metavar="Run theHarvester", action="store_true")
    h.add_argument("--harvester-sources", metavar="Sources", default="crtsh,otx,hackertarget",
                   help="Comma-separated, e.g. crtsh,otx,hackertarget,bing,duckduckgo")
    h.add_argument("--harvester-limit", metavar="Result limit per source", type=int, default=100,
                   widget="IntegerField", gooey_options={"min": 0, "max": 5000})

    # IP
    p = sub.add_parser("IP", help="IP / host geolocation and reverse DNS")
    p.add_argument("hosts", metavar="IPs or hostnames", help="Separated by spaces")

    # Wayback
    p = sub.add_parser("Wayback", help="Internet Archive snapshots")
    p.add_argument("urls", metavar="URLs", help="Separated by spaces")
    p.add_argument("--count", metavar="Latest snapshots to show", type=int, default=10,
                   widget="IntegerField", gooey_options={"min": 1, "max": 100})

    # Metadata
    p = sub.add_parser("Metadata", help="EXIF / GPS metadata from files")
    p.add_argument("files", metavar="Files", widget="MultiFileChooser",
                   help="Photos work out of the box; install exiftool for PDFs, Office files and video")

    # GitHub
    p = sub.add_parser("GitHub", help="GitHub user recon")
    g = p.add_argument_group("User")
    g.add_argument("usernames", metavar="Usernames", help="Separated by spaces")
    g.add_argument("--repos", metavar="Repos to list", type=int, default=15, widget="IntegerField")
    g.add_argument("--emails", metavar="Find emails in public commits", action="store_true",
                   gooey_options={"initial_value": True})

    # Network
    p = sub.add_parser("Network", help="Port / service scanning (Nmap)")
    g = p.add_argument_group("Scan")
    g.add_argument("targets", metavar="Targets", help="IPs, hostnames or CIDR ranges, separated by spaces")
    g.add_argument("--profile", metavar="Scan profile", widget="Dropdown",
                   default="Default (top 1000 ports, service/version)",
                   choices=list(NMAP_PROFILES.keys()))
    g.add_argument("--ports", metavar="Specific ports (optional)",
                   help="e.g. 22,80,443 or 1-1024. Overrides the profile's port range")
    g.add_argument("--script", metavar="NSE scripts (optional)",
                   help="e.g. default,vuln - advanced, see 'man nmap-scripts'")
    g.add_argument("--no-ping", metavar="Skip host discovery (-Pn)", action="store_true",
                   help="Scan even if the target doesn't answer pings")
    o = p.add_argument_group("Output")
    o.add_argument("--save", metavar="Save results to a file", action="store_true")
    o.add_argument("--folder", metavar="Save to folder", widget="DirChooser", default=DOCS)

    # Breach check
    p = sub.add_parser("Breach", help="Check emails / a password against known breaches")
    g = p.add_argument_group("Email")
    g.add_argument("emails", metavar="Emails", help="One or more, separated by spaces")
    g.add_argument("--engine", metavar="Source", widget="Dropdown",
                   default="XposedOrNot (free, no key)",
                   choices=["XposedOrNot (free, no key)", "HaveIBeenPwned (needs API key)", "Both"])
    g.add_argument("--hibp-key", metavar="HaveIBeenPwned API key (optional)", widget="PasswordField",
                   help="Get one at https://haveibeenpwned.com/API/Key - only needed for that source")
    g2 = p.add_argument_group("Password (optional)",
                              "Checked locally with k-anonymity - only a 5-character hash "
                              "prefix is sent, never the password itself")
    g2.add_argument("--password", metavar="Check a password", widget="PasswordField")

    # Crawl
    p = sub.add_parser("Crawl", help="Crawl a site for emails, links, JS files and secrets (Photon)")
    g = p.add_argument_group("Crawl")
    g.add_argument("urls", metavar="URLs", help="e.g. https://example.com, separated by spaces")
    g.add_argument("--level", metavar="Crawl depth", type=int, default=2, widget="IntegerField",
                   gooey_options={"min": 1, "max": 10})
    g.add_argument("--threads", metavar="Threads", type=int, default=10, widget="IntegerField",
                   gooey_options={"min": 1, "max": 50})
    add_proxy_timeout(g, 15)
    e = p.add_argument_group("Extras")
    e.add_argument("--only-urls", metavar="Only extract URLs (faster)", action="store_true")
    e.add_argument("--dns", metavar="Enumerate subdomains and DNS data", action="store_true")
    e.add_argument("--keys", metavar="Look for exposed API keys / secrets", action="store_true")
    e.add_argument("--wayback", metavar="Also seed crawl from Wayback Machine URLs", action="store_true")
    o = p.add_argument_group("Output")
    o.add_argument("--folder", metavar="Save to folder", widget="DirChooser", default=DOCS)


HANDLERS = {
    "Username": do_username, "Email": do_email, "Phone": do_phone,
    "Instagram": do_instagram, "Domain": do_domain, "IP": do_ip,
    "Wayback": do_wayback, "Metadata": do_metadata, "GitHub": do_github,
    "Network": do_network, "Breach": do_breach, "Crawl": do_crawl,
}


@Gooey(**GOOEY_OPTS)
def main():
    parser = GooeyParser(description=DISCLAIMER)
    sub = parser.add_subparsers(dest="command")
    register_modules(sub)
    args = parser.parse_args()
    HANDLERS[args.command](args)


if __name__ == "__main__":
    main()
