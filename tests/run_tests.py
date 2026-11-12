"""Fantasy Game Tracker tests: scoring table (real CBS numbers), ESPN box-score parsing, the Prediction Engine, and the UI at phone sizes.
Run: python3 tests/run_tests.py [--shots]   (serves the app + projections.json from 127.0.0.1, fakes the Worker and ESPN)"""
import json, sys, threading, http.server, functools, os, time
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fixtures as F

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.environ.get('FGT_SHOTS', '/home/claude/fgt-tests/shots')
os.makedirs(SHOTS, exist_ok=True)
PORT = 8765

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), functools.partial(Quiet, directory=APP_DIR))
threading.Thread(target=srv.serve_forever, daemon=True).start()

state = {'rz': 'MIA', 'lp': 'p1', 'gordon_td': False, 'gordon_rush': 46, 'gordon_fl': 0, 'det_mia': (13, 10), 'summary_calls': 0, 'sb_calls': 0}
fails = []
def check(name, cond, extra=''):
    print(('PASS ' if cond else 'FAIL ') + name + ((' :: ' + str(extra)) if extra and not cond else ''))
    if not cond: fails.append(name)

import zlib as _zl, struct as _st
def _png(w=8, h=8):
    raw = b''.join(b'\x00' + b'\x20\x60\xf0\xff' * w for _ in range(h))
    ch = lambda t, d: _st.pack('>I', len(d)) + t + d + _st.pack('>I', _zl.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + ch(b'IHDR', _st.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + ch(b'IDAT', _zl.compress(raw)) + ch(b'IEND', b'')
TINY_PNG = _png()
LEAGUE_WEEKS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'league-weeks-2026.json')))
def route(r):
    u = r.request.url
    if state.get('net') == 'off' and not u.startswith(f'http://127.0.0.1:{PORT}/index.html'):   # v1.7.0 tests: phone offline
        return r.abort()
    if 'espncdn.com/combiner' in u:                                                                  # v1.7.2 tests: small NFL logos
        state['logo_calls'] = state.get('logo_calls', 0) + 1
        return r.fulfill(body=TINY_PNG, content_type='image/png', headers={'Access-Control-Allow-Origin': '*'})
    if 'cbssports.com/team-logo/' in u:                                                              # v1.7.2 tests: CBS logo (no CORS, like the real one)
        state['cbs_logo_calls'] = state.get('cbs_logo_calls', 0) + 1
        return r.fulfill(body=TINY_PNG, content_type='image/png')
    if state.get('fb') == 'ok' and 'firebaseio.com/fgt/presence/' in u and r.request.method == 'PUT':  # v1.7.2 tests: presence works
        return r.fulfill(json={"name": json.loads(r.request.post_data or '{}').get('name'), "t": int(time.time() * 1000)}, headers={'Access-Control-Allow-Origin': '*'})
    if state.get('worker') == 'dead' and 'workers.dev' in u:                                         # v1.7.0 tests: CBS key expired
        return r.fulfill(status=502, json={"ok": False, "error": "cbs_key", "status": 401})
    if 'workers.dev/live' in u:
        if 'week=' in u:
            wk = int(u.split('week=')[1].split('&')[0])
            if wk < 9 and str(wk) in LEAGUE_WEEKS:   # past weeks: the league's real official CBS team scores (Nov 10 pull)
                return r.fulfill(json={"ok": True, "source": "cbs", "at": int(time.time() * 1000), "data": {"live_scoring": {"period": wk, "teams": [
                    {"id": t[0], "pts": t[1], "opp_team_id": t[2], "players": [{"id": "b" + t[0], "status": "Reserve", "fpts": t[3]}]} for t in LEAGUE_WEEKS[str(wk)]]}}})
            return r.fulfill(json={"ok": True, "source": "cbs", "at": int(time.time() * 1000), "data": F.build_future(wk)})
        return r.fulfill(json={"ok": True, "source": "cbs", "feed": "league/scoring/live", "at": int(time.time() * 1000) - 20000, "data": F.build_live()})
    if 'workers.dev/rosters' in u:   # v1.5.2: rosters feed mirrors the live feed's lineup (lineup-change cases: scratchpad test_ros.py)
        wk = int(u.split('week=')[1].split('&')[0]) if 'week=' in u else 9
        src = F.build_live() if wk == 9 else F.build_future(wk)
        rs = {'Active': 'A', 'Reserve': 'RS', 'Injured': 'I'}
        teams = [{'id': t['id'], 'players': [{**p, 'roster_status': rs.get(p.get('status'), 'RS')} for p in t.get('players', [])]} for t in src['live_scoring']['teams']]
        return r.fulfill(json={"ok": True, "source": "cbs", "at": int(time.time() * 1000), "data": {"rosters": {"period": str(wk), "teams": teams}}})
    if 'workers.dev/standings' in u:
        return r.fulfill(json={"ok": True, "source": "cbs", "at": int(time.time() * 1000), "data": F.build_standings()})
    if '/scoreboard' in u:
        state['sb_calls'] += 1
        return r.fulfill(json=F.build_scoreboard(state['lp'], state['det_mia'], rz=state.get('rz')))
    if '/summary' in u:
        state['summary_calls'] += 1
        ev = u.split('event=')[1].split('&')[0]
        data = {'1': F.sum_cin_atl, '2': lambda: F.sum_det_mia(state['gordon_rush'], state['gordon_td'], state['gordon_fl']), '3': F.sum_nyj_kc}.get(ev)
        return r.fulfill(json=data() if data else {"boxscore": {}, "scoringPlays": []})
    if u.startswith('http://127.0.0.1') and '/projections.json' in u:     # pinned Week 9 projections (the live file moves on each week)
        return r.fulfill(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), os.environ.get('FGT_PROJ', 'projections-week9.json')), content_type='application/json')
    if u.startswith('http://127.0.0.1'):
        return r.continue_()
    return r.abort()   # fonts, logos: offline in tests

def wait_engine(page, ms=15000):
    t0 = time.time()
    while time.time() - t0 < ms / 1000:
        if page.evaluate("!!(window.__fgt.ENG.res && window.__fgt.ENG.res.po)"): return True
        page.wait_for_timeout(250)
    return False

def wait_fresh(page, ms=15000):   # v1.7.0: a fresh engine run (not the copy saved on the phone)
    t0 = time.time()
    while time.time() - t0 < ms / 1000:
        if page.evaluate("!!(window.__fgt.ENG.res && window.__fgt.ENG.res.po && !window.__fgt.ENG.res.snap)"): return True
        page.wait_for_timeout(250)
    return False

shots = '--shots' in sys.argv
with sync_playwright() as pw:
    br = pw.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    for (W, H, tag) in [(393, 852, 'iphone'), (360, 780, 'android')]:
        ctx = br.new_context(viewport={'width': W, 'height': H}, device_scale_factor=2, is_mobile=True, has_touch=True,
                             user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1' if tag == 'iphone' else 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Mobile Safari/537.36')
        ctx.route('**/*', route)
        page = ctx.new_page()
        errs = []
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('console', lambda m: errs.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        page.goto(f'http://127.0.0.1:{PORT}/index.html')
        page.wait_for_timeout(600)

        if tag == 'iphone':
            table = [
                ('QB', '271 PaYd, 3 PaTD (47,4,8), 7 RuYd, RuTD (1)', 33), ('WR', '155 ReYd, ReTD (47)', 20),
                ('QB', '162 PaYd, PaTD (1), PaInt, 50 RuYd', 16), ('DST', '12 PA, DFR', 7), ('DST', '3 PA, 2.0 SACK, 2 DFR', 13),
                ('DST', '10 PA, SACK, 2 Int, DFR', 10), ('DST', '17 PA, Int', 7), ('DST', '3 PA', 9), ('DST', '14 PA, DFR', 7),
                ('K', '4 FG (36,45,47,33), 3 XP', 17), ('K', '2 FG (57,43), 4 XP', 13), ('K', 'FG (45), XP', 5), ('K', '2 FG (28,40)', 7), ('K', '2 XP', 2),
                ('QB', '115 PaYd, PaTD (7), 8 RuYd, FL', 8), ('WR', '9 ReYd, FL', -1), ('RB', '-3 PaYd, 57 RuYd', 6), ('RB', '29 RuYd, RuTD (1)', 9),
                ('RB', '21 RuYd, 38 ReYd, 2 ReTD (7,25)', 15), ('WR', '32 ReYd, 2 ReTD (4,8)', 15), ('QB', '242 PaYd, PaTD (50), -1 RuYd', 17),
                ('RB', '100 RuYd, RuTD (1), 47 ReYd', 19), ('QB', '67 PaYd, PaInt, 6 RuYd', -1), ('QB', '108 PaYd, 2 PaTD (7,25)', 15),
                ('RB', '15 RuYd, RuTD (3)', 6), ('QB', '73 PaYd, PaTD (10), 2 RuYd, FL', 5), ('WR', '71 ReYd, FL', 5), ('QB', '95 PaYd, PaTD (3), PaInt, RuYd', 8),
                ('RB', '30 RuYd, 19 ReYd, FL', 2), ('RB', '47 RuYd, -1 ReYd', 3), ('QB', '135 PaYd, 11 RuYd', 3), ('WR', '61 ReYd, ReTD (50)', 16),
                ('WR', '68 ReYd', 6), ('TE', '48 ReYd', 3), ('QB', '77 PaYd, RuYd', 3), ('RB', '57 RuYd, 18 ReYd', 6), ('WR', '-3 RuYd, 6 ReYd', 0),
            ]
            res = page.evaluate("""(t) => t.map(([pos, s, want]) => { const st = window.__fgt.parseCbsStats(s, pos, true); return [pos, s, want, window.__fgt.scoreStats(pos, st).pts]; })""", table)
            bad = [r for r in res if r[2] != r[3]]
            check(f'scoring table: {len(res) - len(bad)}/{len(res)} real CBS lines match CBS points', not bad, bad)
            check('DST shutout with empty CBS line = 15', page.evaluate("window.__fgt.scoreStats('DST', window.__fgt.parseCbsStats('', 'DST', true)).pts") == 15)
            wk7 = page.evaluate("""() => { const S = window.__fgt.scoreStats; return {
              burrow: S('QB', {py:292, ptd:[12,5,20,33], pint:0, ry:0}).pts, reichard: S('K', {fg:[28,47,52], xp:1}).pts,
              marks: S('RB', {ry:66, rcar:19, cy:0}).pts, fannin: S('TE', {cy:91, fl:1}).pts,
              mason: S('RB', {ry:68, rcar:15}).pts, jones: S('RB', {ry:26, rcar:8}).pts, tate: S('WR', {cy:69}).pts,
              tier49: S('RB', {ry:49}).pts, tier50: S('RB', {ry:50}).pts, p225: S('QB', {py:225}).pts, p226: S('QB', {py:226}).pts,
              td39: S('WR', {cy:0, ctd:[39]}).pts, td40: S('WR', {cy:0, ctd:[40]}).pts, td60: S('WR', {cy:0, ctd:[60]}).pts,
              fg39: S('K', {fg:[39]}).pts, fg50: S('K', {fg:[50]}).pts, pa30: S('DST', {dst:{pa:30}}).pts, pa7: S('DST', {dst:{pa:7}}).pts, two: S('WR', {cy:0, two:1}).pts,
              ret: S('WR', {cy:20, ktd:1}).pts, cbsret: S('WR', window.__fgt.parseCbsStats('20 ReYd, KRTD', 'WR', true)).pts } }""")
            want = {'burrow': 31, 'reichard': 13, 'marks': 6, 'fannin': 5, 'mason': 6, 'jones': 3, 'tate': 6, 'tier49': 3, 'tier50': 6, 'p225': 5, 'p226': 7,
                    'td39': 6, 'td40': 8, 'td60': 12, 'fg39': 3, 'fg50': 5, 'pa30': -3, 'pa7': 9, 'two': 2, 'ret': 6, 'cbsret': 6}
            bad = {k: (wk7[k], v) for k, v in want.items() if wk7[k] != v}
            check('Week 7 acceptance + tier edges + return TD = 6', not bad, bad)
            espn = page.evaluate("""(sm) => { const f = window.__fgt; const P = f.parseSummary(sm);
              const one = (name, pos, ab, opp, os) => f.scoreStats(pos, f.espnStats(P, {name, pos}, ab, opp, os)).pts;
              return { final: P.final, burrow: one('Joe Burrow','QB','CIN','ATL',17), chase: one("Ja'Marr Chase",'WR','CIN','ATL',17), higgins: one('Tee Higgins','WR','CIN','ATL',17),
                       mcp: one('Evan McPherson','K','CIN','ATL',17), bengals: one('Bengals','DST','CIN','ATL',17), penix: one('Michael Penix Jr.','QB','ATL','CIN',34),
                       brown: one('Chase Brown','RB','CIN','ATL',17) } }""", F.sum_cin_atl())
            want = {'final': True, 'burrow': 33, 'chase': 20, 'higgins': 15, 'mcp': 13, 'bengals': 7, 'penix': 16, 'brown': 6}
            bad = {k: (espn[k], v) for k, v in want.items() if espn[k] != v}
            check('ESPN box score -> league points match CBS (CIN-ATL)', not bad, bad)
            ret = page.evaluate("""(sm) => { const f = window.__fgt; const P = f.parseSummary(sm);
              return { burden: f.scoreStats('WR', f.espnStats(P, {name:'Luther Burden III', pos:'WR'}, 'CHI', 'X', 0)).pts,
                       swift: f.scoreStats('RB', f.espnStats(P, {name:"D'Andre Swift", pos:'RB'}, 'CHI', 'X', 0)).pts, dsttd: P.teams.CHI.dstTd } }""", F.sum_return_td())
            check('ESPN return TD 6 to the player, own fumble recovery TD 6, D/ST gets the return only', ret == {'burden': 6, 'swift': 6, 'dsttd': 1}, ret)

        check(f'[{tag}] gate shows on first open', page.is_visible('#gate'))
        page.click('[data-g="browser"]')
        page.wait_for_timeout(500)
        check(f'[{tag}] team sheet opens locked', page.is_visible('#teamOverlay.show') and page.get_attribute('#teamOverlay', 'data-locked') == '1')
        page.mouse.click(W / 2, 40)
        page.wait_for_timeout(300)
        check(f'[{tag}] team sheet ignores backdrop taps', page.is_visible('#teamOverlay.show'))
        page.click('[data-team="11"]')
        page.wait_for_timeout(250)
        check(f'[{tag}] confirm step', page.is_visible('[data-tc="yes"]'))
        page.click('[data-tc="yes"]')
        page.wait_for_timeout(1500)
        check(f'[{tag}] team saved', page.evaluate("JSON.parse(localStorage.getItem('fgt-team'))") == '11')
        check(f'[{tag}] my card on top', page.inner_text('.mc.mine').find('Dallas') >= 0)
        check(f'[{tag}] five other games', page.locator('#cards .mc').count() == 5)
        page.wait_for_timeout(1500)
        check(f'[{tag}] Dallas live total from ESPN (33+3+20+7=63)', '63' in page.inner_text('.mc.mine'), page.inner_text('.mc.mine'))
        # ---------- Prediction Engine ----------
        ok = wait_engine(page)
        check(f'[{tag}] engine ran (win % + playoff odds)', ok, page.evaluate("window.__fgt.ENG.err"))
        page.wait_for_timeout(600)
        eng = page.evaluate("""() => { const E = window.__fgt.ENG.res, m = Object.keys(E.m).map(k => E.m[k]); const S = window.__fgt.S;
          return { n: m.length, wa: m.map(x => x.wa), po: E.po['11'], po0: E.po0['11'], burrowFinal: (E.p['1'] || [])[0], marks: (E.p['3'] || [])[0], gordon: (E.p['2'] || [])[0], matched: window.__fgt.projFor({name:'Woody Marks', pos:'RB', nfl:'HOU'}) ? 1 : 0 } }""")
        check(f'[{tag}] six matchups, win % between 0 and 1', eng['n'] == 6 and all(0 <= w <= 1 for w in eng['wa']), eng)
        check(f'[{tag}] final player = his actual points (Burrow 33)', abs((eng['burrowFinal'] or 0) - 33) < 1e-6, eng)
        check(f'[{tag}] not-started player projected from the model (Marks)', eng['matched'] and 5 < (eng['marks'] or 0) < 15, eng)
        check(f'[{tag}] live player projected above current points (Gordon > 3)', (eng['gordon'] or 0) > 3, eng)
        check(f'[{tag}] playoff odds 0-1, live and pregame', 0 <= eng['po'] <= 1 and 0 <= eng['po0'] <= 1, eng)
        mine = page.inner_text('.mc.mine')
        check(f'[{tag}] your card shows Win Probability', 'Win Probability' in mine and '%' in mine, mine)
        la = page.inner_text('.la')
        check(f'[{tag}] League Analysis: 4th AFC, league rank, playoff odds %', '4th' in la.replace('\n', '') and 'AFC' in la and '%' in la, la)
        check(f'[{tag}] Divisional Week badge (every Week 9 fixture game is in-division)', page.locator('.la .divwk').count() == 1)
        check(f'[{tag}] compact cards have a win % chip per team', page.locator('#cards .mc .chip2').count() == 10)
        check(f'[{tag}] no page errors', not errs, errs)
        ov = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
        check(f'[{tag}] no sideways scroll on scoreboard', ov <= 0, ov)
        if shots: page.screenshot(path=f'{SHOTS}/{tag}-04-scoreboard.png', full_page=True)

        last_key = page.eval_on_selector_all('#cards .mc', 'els => els[els.length-1].dataset.key')
        page.click(f'#cards .mc[data-key="{last_key}"] [data-pin]')
        page.wait_for_timeout(800)
        first_key = page.eval_on_selector_all('#cards .mc', 'els => els[0].dataset.key')
        check(f'[{tag}] pinned game moves to the top', first_key == last_key, (first_key, last_key))
        check(f'[{tag}] pinned card glows', page.locator('#cards .mc.pinned').count() == 1)
        check(f'[{tag}] pins saved by team', len(page.evaluate("JSON.parse(localStorage.getItem('fgt-pins'))")) == 2)

        # v1.9.0: the scoreboard card gets the same "My matchup" diamond (the old word tag is gone); scores show once the matchup has begun
        check(f'[{tag}] scoreboard: My matchup diamond on your card, no old tag', page.evaluate("document.querySelector('.mc.mine .ymx') && document.querySelector('.mc.mine .ymx').textContent") == 'My matchup' and page.evaluate("[...document.querySelectorAll('.mc.mine .tag')].some(t => t.textContent === 'My matchup')") is False)
        check(f'[{tag}] scoreboard: begun matchups show numbers, not dashes', page.evaluate("[...document.querySelectorAll('.mc.mine .sc b')].map(b => b.textContent)") == ['63', '22'], page.evaluate("[...document.querySelectorAll('.mc.mine .sc b')].map(b => b.textContent)"))
        page.click('.mc.mine')
        page.wait_for_timeout(700)
        check(f'[{tag}] matchup screen opens', page.is_visible('#hero'))
        rows = page.locator('.plist').first.locator('.prow').count()
        check(f'[{tag}] 8 starter rows', rows == 8, rows)
        txt = page.inner_text('#mrows')
        check(f'[{tag}] FLEX row is Woody Marks', 'W. Marks' in page.inner_text('.prow[data-row="4"]'))
        # v1.6.0: IR has its own section under the bench (CBS IR slot); bench rows are always BN; empty IR slot says Empty
        check(f'[{tag}] Tate shows once, in the IR section', txt.count('C. Tate') == 1 and 'C. Tate' in page.inner_text('.irlist') and page.inner_text('.irlist .chip').strip() == 'IR', txt)
        check(f'[{tag}] bench rows are all BN, IR section has the empty NE slot', all(c.strip() == 'BN' for c in page.locator('.benchlist:not(.irlist) .chip').all_inner_texts()) and 'Empty' in page.inner_text('.irlist'))
        check(f'[{tag}] every player has a position pill', page.locator('#mrows .ppos').count() == page.locator('#mrows .pside .nfl').count() > 0)
        check(f'[{tag}] matchup header has week selector + settings', page.locator('.mhead #weekBtn').count() == 1 and page.locator('.mhead #gearBtn').count() == 1)
        hero = page.inner_text('#hero')
        check(f'[{tag}] header: Win Probability, projections, record + division rank, VS', 'Win Probability' in hero and '3-5 · 4th AFC' in hero and page.locator('#hero .pj span').count() == 2 and page.locator('#hero .vsw svg').count() == 1, hero)
        check(f'[{tag}] header Divisional Week badge', page.locator('#hero .divwk').count() == 1)
        # v1.8.1: "My matchup" diamond on your game only, star = first dot, Online-strip border (no glow), badge and diamond don't touch
        check(f'[{tag}] My matchup diamond on your game', page.locator('#hero .ymx').count() == 1 and page.evaluate("document.querySelector('#hero .ymx').textContent") == 'My matchup')
        check(f'[{tag}] first dot is a lit star', page.evaluate("(() => { const d = document.querySelectorAll('.dots i'); return d[0].classList.contains('star') && d[0].classList.contains('on') && !!d[0].querySelector('svg') && document.querySelectorAll('.dots i.star').length === 1; })()"))
        bd = page.evaluate("(() => { const a = getComputedStyle(document.getElementById('hero')), b = getComputedStyle(document.querySelector('.plist')); return [a.borderTopColor, a.boxShadow, b.borderTopColor]; })()")
        check(f'[{tag}] matchup + player cards have the blue border, no glow', bd[0] == bd[2] == 'rgba(79, 141, 255, 0.28)' and bd[1] == 'none', bd)
        gap = page.evaluate("(() => { const a = document.querySelector('#hero .divwk').getBoundingClientRect(), b = document.querySelector('#hero .ymx').getBoundingClientRect(), h = document.getElementById('hero').getBoundingClientRect(); return [b.left - a.right, b.left - h.left, h.right - b.right]; })()")
        check(f'[{tag}] diamond centered, clear of the Division Week badge', gap[0] >= 4 and abs(gap[1] - gap[2]) <= 1.5, gap)
        cen = page.evaluate("""() => [...document.querySelectorAll('.plist .prow')].slice(0, 8).map(r => { const c = r.querySelector('.chip').getBoundingClientRect(), cc = c.top + c.height / 2;
          return [...r.querySelectorAll('.ppt b')].map(b => { const q = b.getBoundingClientRect(); return Math.abs(q.top + q.height / 2 - cc); }); }).flat()""")
        check(f'[{tag}] every score centered on its position square (within 3 px)', max(cen) <= 3, cen)
        check(f'[{tag}] projection under a not-started player (Marks)', page.locator('.prow[data-row="4"] .ppt small.pj').count() >= 1)
        page.click('.prow[data-row="0"]')
        page.wait_for_timeout(300)
        det = page.inner_text('.detail')
        check(f'[{tag}] Burrow drop-down: PASS bar, TD lengths, total 33', 'PASS' in det and '47' in det and '33' in det, det)
        page.click('.prow[data-row="0"]'); page.wait_for_timeout(200)
        page.click('.prow[data-row="4"]'); page.wait_for_timeout(300)
        det = page.inner_text('.detail')
        check(f'[{tag}] not-started drop-down: PROJECTED, floor, ceiling', 'PROJECTED' in det and 'Floor' in det and 'Ceiling' in det, det)
        page.click('.prow[data-row="4"]'); page.wait_for_timeout(200)
        ov = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
        check(f'[{tag}] no sideways scroll on matchup', ov <= 0, ov)
        if shots: page.screenshot(path=f'{SHOTS}/{tag}-05-matchup.png', full_page=True)
        check(f'[{tag}] live tier bar on Gordon', '4 more rush yds' in page.inner_text('.prow[data-row="1"]'), page.inner_text('.prow[data-row="1"]'))
        # v1.9.0: clock pill (no game score), RED ZONE pill on the inside, dot stays green, everything fits
        pr = page.evaluate("""(() => { const g = document.querySelector('.prow[data-row="1"] .pside:not(.r)'), w = document.querySelector('.prow[data-row="1"] .pside.r'), b = document.querySelector('.prow[data-row="0"] .pside:not(.r)');
          return { ck: g.querySelector('.ck.live').textContent, rz: g.querySelectorAll('.stp.rz').length, wrz: w.querySelectorAll('.stp').length, wck: w.querySelector('.ck.live').textContent,
                   dot: getComputedStyle(g.querySelector('.ck .dot')).backgroundColor, fin: b.querySelector('.ck.fin').textContent, txt: g.innerText + b.innerText,
                   inside: g.querySelector('.stp.rz').getBoundingClientRect().left > g.querySelector('.ck').getBoundingClientRect().left,
                   over: [...document.querySelectorAll('#view .pills')].filter(e => e.scrollWidth > e.clientWidth + 1).length,
                   pre: [...document.querySelectorAll('#view .ck.pre')].map(e => e.textContent).slice(0, 2) }; })()""")
        check(f'[{tag}] clock pill Q3 8:14, no game score', pr['ck'] == 'Q3 8:14' and '10-13' not in pr['txt'] and '34-17' not in pr['txt'], pr)
        check(f'[{tag}] RED ZONE pill on Gordon (Miami ball inside the 20), inside of the clock, not on Walker', pr['rz'] == 1 and pr['inside'] and pr['wrz'] == 0 and pr['wck'] == 'Q3 2:00', pr)
        check(f'[{tag}] clock dot stays green in the red zone', pr['dot'] == 'rgb(61, 220, 132)', pr['dot'])
        check(f'[{tag}] Final pill, kickoff pill with opponent, no pill runs over', pr['fin'] == 'Final' and pr['over'] == 0 and all(' @ ' in x or ' vs ' in x for x in pr['pre']) and len(pr['pre']) > 0, pr)
        bn = page.evaluate("""(() => ({ st: document.querySelector('.bnr.st h3').textContent, bn: document.querySelector('.bnr.bn small').textContent, ir: document.querySelector('.bnr.ir small').textContent,
          tot: [...document.querySelectorAll('.bnr.bn .sd em')].map(e => e.textContent), old: document.querySelectorAll('#mrows .plabel').length,
          pjb: document.querySelectorAll('#mrows .pj.pjb').length, hero: [...document.querySelectorAll('#hero .scs b')].map(b => b.textContent) }))()""")
        check(f'[{tag}] banners: Starters / Bench "Tiebreaker only" with both bench totals / IR "Doesn\u2019t count"', bn['st'] == 'Starters' and bn['bn'] == 'Tiebreaker only' and bn['ir'] == 'Doesn\u2019t count' and len(bn['tot']) == 2 and all(t.replace('.', '').isdigit() for t in bn['tot']) and bn['old'] == 0, bn)
        check(f'[{tag}] matchup underway: hero shows scores, projections back to gray', bn['hero'] == ['63', '22'] and bn['pjb'] == 0, bn)
        mb = page.evaluate("""(() => { const t = { lineup: [{ name: 'Test Guy', nfl: 'GB', pos: 'WR' }] };
          const mBegun = window.__fgt.mBegun; return [mBegun(t, { rows: [{ state: 'pre' }] }, t, { rows: [{ state: 'pre' }] }), mBegun(t, { rows: [{ state: 'pre' }] }, t, { rows: [{ state: 'in' }] }),
                  mBegun(t, { rows: [{ state: 'bye' }] }, null, null), mBegun(t, { rows: [null] }, t, { rows: [{ state: 'post' }] })]; })()""")
        check(f'[{tag}] matchup begins when either team has a starter kick off (not before, not for a bye)', mb == [False, True, False, True], mb)

        wa0 = page.evaluate("window.__fgt.ENG.res.m[Object.keys(window.__fgt.ENG.res.m).find(k => k.indexOf('5-11') >= 0)].wa")
        state.update({'lp': 'p2', 'gordon_td': True, 'gordon_rush': 90, 'det_mia': (13, 17), 'rz': None})
        page.wait_for_timeout(12500)
        r1 = page.inner_text('.prow[data-row="1"]')
        tdp = page.evaluate("""(() => { const g = document.querySelector('.prow[data-row="1"] .pside:not(.r)'); const t = g.querySelector('.stp.td');
          return { n: g.querySelectorAll('.stp').length, vis: t ? t.innerText.trim() : '', old: g.querySelectorAll('.evt.td').length }; })()""")
        check(f'[{tag}] TOUCHDOWN pill after a live TD (replaces RED ZONE, no old TD tag)', tdp['n'] == 1 and tdp['vis'] in ('TOUCHDOWN', 'TD') and tdp['old'] == 0, tdp)
        check(f'[{tag}] score glow after the jump', page.locator('.prow[data-row="1"] b.glow').count() == 1)
        check(f'[{tag}] Gordon now 6 + 8 = 14', '14' in r1, r1)
        wa1 = page.evaluate("window.__fgt.ENG.res.m[Object.keys(window.__fgt.ENG.res.m).find(k => k.indexOf('5-11') >= 0)].wa")
        check(f'[{tag}] win % updates live after the TD (home side = Dallas)', wa1 != wa0, (wa0, wa1))
        if shots: page.screenshot(path=f'{SHOTS}/{tag}-06-td.png')
        state.update({'lp': 'p3', 'gordon_fl': 1, 'det_mia': (13, 17)})
        page.wait_for_timeout(11000)
        r1 = page.inner_text('.prow[data-row="1"]')
        check(f'[{tag}] FUMBLE LOST badge', 'FUMBLE LOST' in r1, r1)
        state.update({'lp': 'p1', 'gordon_td': False, 'gordon_rush': 46, 'gordon_fl': 0, 'det_mia': (13, 10), 'rz': 'MIA'})

        before = page.inner_text('.fp2 .nm.r b')
        box = page.locator('#hero').bounding_box()
        y = box['y'] + 40
        page.evaluate("""([x0, y]) => { const h = document.getElementById('hero');
          const ev = (t, x) => h.dispatchEvent(new PointerEvent(t, {pointerId: 7, clientX: x, clientY: y, bubbles: true, pointerType: 'touch'}));
          ev('pointerdown', x0); for (let i = 1; i <= 8; i++) window.dispatchEvent(new PointerEvent('pointermove', {pointerId: 7, clientX: x0 - i * 25, clientY: y, bubbles: true}));
          window.dispatchEvent(new PointerEvent('pointerup', {pointerId: 7, clientX: x0 - 200, clientY: y, bubbles: true})); }""", [box['x'] + box['width'] - 20, y])
        page.wait_for_timeout(800)
        after = page.inner_text('.fp2 .nm.r b')
        check(f'[{tag}] swipe moves to the next game', before != after, (before, after))
        check(f'[{tag}] dots follow', page.locator('.dots i.on').count() == 1)
        check(f'[{tag}] no diamond on someone else\'s game, star dims', page.locator('#hero .ymx').count() == 0 and page.locator('.dots i.star').count() == 1 and page.locator('.dots i.star.on').count() == 0)

        page.click('.tabbtn[data-tab="standings"]')
        page.wait_for_timeout(600)
        st = page.inner_text('#view')
        check(f'[{tag}] standings: AFC and NFC cards', 'AFC' in st and 'NFC' in st and page.locator('.strow').count() == 12)
        check(f'[{tag}] your row highlighted', page.locator('.strow.me').count() == 1 and 'Dallas' in page.inner_text('.strow.me'))
        page.click('.strow.me')
        page.wait_for_timeout(250)
        det = page.inner_text('.stdet').lower() if page.locator('.stdet').count() else ''
        check(f'[{tag}] tap a team: Scored / Against / Differential', 'scored' in det and 'against' in det and 'differential' in det, det)
        check(f'[{tag}] every team has an arrow', page.locator('.strow .stchev').count() == 12)
        check(f'[{tag}] PLAYOFF % for every team', page.locator('.strow .stpo').count() == 12 and page.locator('.strow .stpo.na').count() == 0)
        check(f'[{tag}] MOVE column for every team (GB gone)', page.locator('.strow .stmv').count() == 12 and 'MOVE' in page.inner_text('.sthead') and 'GB' not in page.inner_text('.sthead'))
        # live: CBS 611 + Dallas's 63 so far this week (fixture), records unchanged until the week is final
        check(f'[{tag}] Avg., no +this week', '83.0 avg.' in det and 'this week' not in det, det)
        check(f'[{tag}] record unchanged while games are on', '3-5' in page.inner_text('.strow.me'))
        page.locator('.strow').nth(0).click(); page.wait_for_timeout(200)
        check(f'[{tag}] open several teams at once', page.locator('.stdet').count() == 2)
        page.click('.strow.me'); page.wait_for_timeout(200)
        check(f'[{tag}] tap again closes', page.locator('.stdet').count() == 1)
        page.click('.tabbtn[data-tab="home"]'); page.wait_for_timeout(300)
        page.click('.tabbtn[data-tab="standings"]'); page.wait_for_timeout(300)
        check(f'[{tag}] all closed when you come back to Standings', page.locator('.stdet').count() == 0)
        check(f'[{tag}] finished game reads 100%', page.evaluate("[window.__fgt.fmtPct(1, true), window.__fgt.fmtPct(0, true), window.__fgt.fmtPct(0.9996)].join(' ')") == '100% 0% >99.9%')
        # whole week final: Dallas beats its opponent -> 4-5, badge on Standings, banner once
        page.click('.tabbtn[data-tab="home"]'); page.wait_for_timeout(300)
        page.evaluate("() => { window.__fgt.S._freeze = 1; }")
        page.evaluate("""() => { const F = window.__fgt, c = F.curW(); const t = JSON.parse(JSON.stringify(c.teams));
          Object.keys(t).forEach(id => { t[id].left = 0; t[id].bleft = 0; t[id].pts = 50; });
          t['11'].pts = 150; F._setCurW({ week: c.week, teams: t, final: true, at: 'test' });
          }""")
        page.click('.tabbtn[data-tab="home"]'); page.wait_for_timeout(400)
        check(f'[{tag}] week final -> Dallas record 4-5', page.evaluate("(() => { const A = window.__fgt.stAdjust(true); const d = A.byId['11']; return d.wins + '-' + d.losses + ' ' + d.streak; })()") == '4-5 W1')
        check(f'[{tag}] badge on Standings tab', page.locator('.tabbtn[data-tab="standings"] .cbadge').count() == 1)
        page.click('.tabbtn[data-tab="standings"]'); page.wait_for_timeout(400)
        old_wl = page.inner_text('.strow.me .stwl')
        check(f'[{tag}] shuffle starts on last week (Dallas 3-5, banner waits)', old_wl == '3-5' and page.locator('.recban.later').count() == 1, old_wl)
        if os.environ.get('FGT_SHOTS_ON'):
            page.screenshot(path=f'{SHOTS}/{tag}-shuffle-1.png'); page.wait_for_timeout(1600)
            page.screenshot(path=f'{SHOTS}/{tag}-shuffle-2.png'); page.wait_for_timeout(1000)
            page.screenshot(path=f'{SHOTS}/{tag}-shuffle-3.png')
        page.wait_for_timeout(4600)
        check(f'[{tag}] after shuffle: Dallas 4-5, banner shows', page.inner_text('.strow.me .stwl') == '4-5' and page.locator('.recban.later').count() == 0)
        check(f'[{tag}] records updated banner', 'Records updated' in page.inner_text('#view'))
        check(f'[{tag}] badge cleared', page.locator('.tabbtn[data-tab="standings"] .cbadge').count() == 0)
        if os.environ.get('FGT_SHOTS_ON'):
            page.click('.strow.me'); page.locator('.strow').nth(0).click(); page.wait_for_timeout(300)
            page.screenshot(path=f'{SHOTS}/{tag}-standings-open.png', full_page=False)
        page.evaluate("() => { window.__fgt.S._freeze = 0; try{ localStorage.removeItem('fgt-rec-seen'); }catch(e){} }")
        # reopen to the last tab
        page.reload(); page.wait_for_timeout(1500)
        check(f'[{tag}] reopens on the last tab (Standings)', page.locator('.tabbtn.on[data-tab="standings"]').count() == 1)
        page.click('.tabbtn[data-tab="chat"]')
        page.wait_for_timeout(300)
        check(f'[{tag}] chat pane opens with a message box', page.is_visible('#chatPane') and page.locator('#chatInput').count() == 1)
        page.click('.tabbtn[data-tab="match"]')
        page.wait_for_timeout(400)
        check(f'[{tag}] Matchup tab opens your game', 'Dallas' in page.inner_text('#hero'))
        page.click('.tabbtn[data-tab="home"]')
        wait_engine(page); page.wait_for_timeout(800)

        keys0 = page.eval_on_selector_all('#cards .mc[data-grp="rest"]', 'els => els.map(e => e.dataset.key)')
        b0 = page.locator(f'#cards .mc[data-key="{keys0[0]}"]').bounding_box()
        b2 = page.locator(f'#cards .mc[data-key="{keys0[2]}"]').bounding_box()
        page.evaluate("""([k, x, y0, y1]) => { const el = document.querySelector('#cards .mc[data-key="' + k + '"]');
          const t = (y) => new Touch({identifier: 1, target: el, clientX: x, clientY: y});
          el.dispatchEvent(new TouchEvent('touchstart', {touches: [t(y0)], changedTouches: [t(y0)], bubbles: true, cancelable: true}));
          return new Promise(res => setTimeout(() => { for (let i = 1; i <= 10; i++) el.dispatchEvent(new TouchEvent('touchmove', {touches: [t(y0 + (y1 - y0) * i / 10)], changedTouches: [t(y0 + (y1 - y0) * i / 10)], bubbles: true, cancelable: true}));
            el.dispatchEvent(new TouchEvent('touchend', {touches: [], changedTouches: [t(y1)], bubbles: true, cancelable: true})); res(); }, 450)); }""",
            [keys0[0], b0['x'] + 60, b0['y'] + b0['height'] / 2, b2['y'] + b2['height'] / 2 + 6])
        page.wait_for_timeout(900)
        keys1 = page.eval_on_selector_all('#cards .mc[data-grp="rest"]', 'els => els.map(e => e.dataset.key)')
        check(f'[{tag}] press-and-hold drag reorders', keys1[2] == keys0[0] and keys1[0] == keys0[1], (keys0, keys1))
        check(f'[{tag}] order saved', len(page.evaluate("JSON.parse(localStorage.getItem('fgt-order'))") or []) >= 8)
        check(f'[{tag}] drag did not open the matchup', page.is_visible('#cards'))
        page.reload(); page.wait_for_timeout(1500)
        keys2 = page.eval_on_selector_all('#cards .mc[data-grp="rest"]', 'els => els.map(e => e.dataset.key)')
        check(f'[{tag}] order survives a reload', keys2 == keys1, (keys1, keys2))
        check(f'[{tag}] no gate after setup', not page.is_visible('#gate') and not page.is_visible('#teamOverlay.show'))
        # a past week only holds 10 minutes
        page.add_init_script("localStorage.setItem('fgt-view', JSON.stringify({v:'home', w:8, k:null, t:Date.now() - 11*60000}))")
        page.reload(); page.wait_for_timeout(1000)
        check(f'[{tag}] snaps back to the current week after 10 min', 'Week 9' in page.inner_text('#weekBtn') and 'Back to Current Week' in page.inner_text('#toast'), page.inner_text('#toast'))
        page.click('#gearBtn'); page.wait_for_timeout(450)
        check(f'[{tag}] settings sheet', page.is_visible('#setOverlay.show'))
        page.click('#setOverlay [data-close]'); page.wait_for_timeout(450)
        page.click('#weekBtn'); page.wait_for_timeout(450)
        check(f'[{tag}] week sheet', page.is_visible('#weekOverlay.show') and page.locator('.wbtn:not([disabled])').count() == 9)
        page.click('#weekOverlay [data-close]'); page.wait_for_timeout(400)
        check(f'[{tag}] no page errors at the end', not errs, errs)
        print(f'[{tag}] scoreboard fetches: {state["sb_calls"]}, box-score fetches: {state["summary_calls"]}')
        ctx.close()
    # ---------- v1.7.0: instant open from saved data, expired CBS key, Matchup back to your game ----------
    tag = 'v1.7'
    ctx = br.new_context(viewport={'width': 393, 'height': 852}, device_scale_factor=2, is_mobile=True, has_touch=True,
                         user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
    ctx.route('**/*', route)
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append('pageerror: ' + str(e) + ' ' + str(getattr(e, 'stack', '') or '')[:400]))
    page.on('console', lambda m: errs.append(m.text + ' @ ' + str(m.location.get('url', ''))[:120] + ':' + str(m.location.get('lineNumber', ''))) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    state.update({'net': 'ok', 'worker': 'ok', 'lp': 'p1', 'gordon_td': False, 'gordon_rush': 46, 'gordon_fl': 0, 'det_mia': (13, 10)})
    page.goto(f'http://127.0.0.1:{PORT}/index.html'); page.wait_for_timeout(300)
    page.evaluate("() => { localStorage.setItem('fgt-team', JSON.stringify('11')); localStorage.setItem('fgt-gate', '1'); }")
    page.reload(); page.wait_for_timeout(800)
    wait_fresh(page); page.wait_for_timeout(2500)
    keys = page.evaluate("() => ['ros-w9', 'cbs-w9', 'proj', 'eng', 'fut-w10', 'fut-w11', 'fut-w12'].filter(k => localStorage.getItem('fgt-' + k) == null)")
    check(f'[{tag}] lineups, projections, win %, schedule saved on the phone', not keys, keys)
    po_ok = page.evaluate("window.__fgt.ENG.res.po['11']")
    import datetime as _dt
    _ms = lambda *a: int(_dt.datetime(*a, tzinfo=_dt.timezone.utc).timestamp() * 1000)
    cases = [(_ms(2026, 11, 11, 17), _ms(2026, 11, 10, 11)),   # Wed noon ET -> Tue 6 AM ET
             (_ms(2026, 11, 10, 5), _ms(2026, 11, 3, 11)),     # Tue midnight ET (before 6 AM) -> last Tuesday
             (_ms(2026, 11, 17, 2), _ms(2026, 11, 10, 11)),    # Mon 9 PM ET -> same week
             (_ms(2026, 11, 10, 12), _ms(2026, 11, 10, 11))]   # Tue 7 AM ET -> today 6 AM
    got = page.evaluate("(c) => c.map(x => window.__fgt.weekStartET(x[0]))", cases)
    check(f'[{tag}] league week starts Tuesday 6 AM ET', got == [c[1] for c in cases], (got, [c[1] for c in cases]))
    # 1) open with no network at all: everything shows from the phone copy
    state['net'] = 'off'
    page.reload(); page.wait_for_timeout(700)
    mine = page.inner_text('.mc.mine') if page.locator('.mc.mine').count() else ''
    la = page.inner_text('.la') if page.locator('.la').count() else ''
    check(f'[{tag}] offline open: your matchup, win %, playoff odds right away', 'Dallas' in mine and 'Win Probability' in mine and '%' in la.split('Playoff Odds')[-1] and page.locator('#cards .mc').count() == 5, (mine, la))
    page.click('.mc.mine'); page.wait_for_timeout(500)
    check(f'[{tag}] offline open: matchup rows + projections', page.locator('.plist').first.locator('.prow').count() == 8 and page.locator('.prow[data-row="4"] .ppt small.pj').count() >= 1)
    page.click('#back'); page.wait_for_timeout(300)
    # 2) CBS key expired, schedule saved on the phone: same playoff odds as with a working key
    state.update({'net': 'ok', 'worker': 'dead'})
    page.reload(); page.wait_for_timeout(800)
    ok = wait_fresh(page); page.wait_for_timeout(500)
    po_dead = page.evaluate("window.__fgt.ENG.res && !window.__fgt.ENG.res.snap && window.__fgt.ENG.res.po ? window.__fgt.ENG.res.po['11'] : null")
    check(f'[{tag}] expired key: banner says so', 'CBS key expired' in page.inner_text('#view'), page.inner_text('#view')[:300])
    # v1.7.1: the warning is on every tab, right under the Online row
    seen = {}
    for tb in ['match', 'standings', 'chat', 'home']:
        page.click(f'.tabbtn[data-tab="{tb}"]'); page.wait_for_timeout(400)
        seen[tb] = page.locator('#view .status').count() >= 1 and 'CBS key expired' in page.inner_text('#view .status')
        if tb != 'home': seen[tb] = seen[tb] and page.evaluate("(() => { const s = document.querySelector('#view .keyst'), o = document.querySelector('#view .onstrip'); return !!s && (!o || (o.compareDocumentPosition(s) & 4) > 0); })()")
        if shots: page.screenshot(path=f'{SHOTS}/v17-key-{tb}.png')
    check(f'[{tag}] expired key: warning on all four tabs, under the Online row', all(seen.values()), seen)
    ov = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
    check(f'[{tag}] expired key: no sideways scroll', ov <= 0, ov)
    check(f'[{tag}] expired key + saved schedule: playoff odds unchanged', ok and po_dead is not None and abs(po_dead - po_ok) < 0.002, (po_ok, po_dead))
    # 3) expired key on a phone that never saved the schedule: built-in schedule
    page.evaluate("() => ['fgt-fut-w10', 'fgt-fut-w11', 'fgt-fut-w12'].forEach(k => localStorage.removeItem(k))")
    page.reload(); page.wait_for_timeout(800)
    ok = wait_fresh(page); page.wait_for_timeout(500)
    fut = page.evaluate("(() => { const s = window.__fgt.season(); return s ? s.future.map(f => [f.w, f.pairs === 'rank' ? 'rank' : (f.pairs || []).map(p => p.slice().sort((a, b) => a - b).join('-')).sort()]) : null; })()")
    want_f = [[10, sorted(['10-11', '3-9', '1-4', '8-12', '6-7', '2-5'])], [11, sorted(['6-11', '3-4', '2-7', '5-12', '1-10', '8-9'])], [12, 'rank']]
    check(f'[{tag}] expired key, nothing saved: built-in Weeks 10-11 + Week 12 by standings', fut == want_f, fut)
    po_b = page.evaluate("window.__fgt.ENG.res && window.__fgt.ENG.res.po ? window.__fgt.ENG.res.po['11'] : null")
    check(f'[{tag}] expired key, nothing saved: playoff odds still show', ok and po_b is not None and 0 <= po_b <= 1 and '%' in page.inner_text('.la').split('Playoff Odds')[-1], po_b)
    # 4) a copy from last league week (before Tuesday 6 AM ET) is never shown
    state.update({'net': 'off', 'worker': 'ok'})
    page.evaluate("""() => { const t = window.__fgt.weekStartET(Date.now()) - 3600000;
      ['fgt-cbs-w9', 'fgt-ros-w9', 'fgt-eng'].forEach(k => { const v = JSON.parse(localStorage.getItem(k)); v.at = t; localStorage.setItem(k, JSON.stringify(v)); }); }""")
    page.reload(); page.wait_for_timeout(700)
    check(f'[{tag}] last week\'s saved lineups are not shown', page.locator('.mc.mine').count() == 0 and page.locator('#cards .mc').count() == 0)
    state['net'] = 'ok'
    page.reload(); page.wait_for_timeout(800); wait_fresh(page); page.wait_for_timeout(2500)
    page.click('.tabbtn[data-tab="match"]'); page.wait_for_timeout(400)
    check(f'[{tag}] working key: no warning row on Matchup', page.locator('#view .keyst').count() == 0)
    page.click('.tabbtn[data-tab="home"]'); page.wait_for_timeout(300)
    check(f'[{tag}] fresh lineups saved again', page.evaluate("JSON.parse(localStorage.getItem('fgt-ros-w9')).at") >= page.evaluate("window.__fgt.weekStartET(Date.now())"))
    # 5) a TD that happened while the app was closed is not replayed as a new TD badge
    page.click('.mc.mine'); page.wait_for_timeout(600)
    state.update({'gordon_td': True, 'gordon_rush': 90, 'det_mia': (13, 17), 'lp': 'p2'})
    page.reload(); page.wait_for_timeout(4000)
    r1 = page.inner_text('.prow[data-row="1"]')
    check(f'[{tag}] reopen: Gordon updated to 14, no replayed TD badge or glow', '14' in r1 and page.locator('.prow[data-row="1"] .evt').count() == 0 and page.locator('.prow[data-row="1"] b.glow').count() == 0, r1)
    state.update({'lp': 'p1', 'gordon_td': False, 'gordon_rush': 46, 'gordon_fl': 0, 'det_mia': (13, 10)})
    # 6) Matchup tab: back after 10+ min -> your game at the top; a quick switch keeps your place
    page.click('#back'); page.wait_for_timeout(400)
    page.locator('#cards .mc').first.click(); page.wait_for_timeout(600)
    other = page.inner_text('.fp2')
    check(f'[{tag}] opened another game', 'Dallas' not in other, other)
    page.evaluate("window.scrollTo(0, 400)")
    away = """(ms) => { Object.defineProperty(document, 'hidden', {configurable: true, get: () => true}); document.dispatchEvent(new Event('visibilitychange'));
      const real = Date.now; Date.now = () => real() + ms;
      Object.defineProperty(document, 'hidden', {configurable: true, get: () => false}); document.dispatchEvent(new Event('visibilitychange'));
      Date.now = real; delete document.hidden; }"""
    page.evaluate(away, 2 * 60000); page.wait_for_timeout(500)
    check(f'[{tag}] back after 2 min: same game', page.inner_text('.fp2') == other)
    page.evaluate(away, 11 * 60000); page.wait_for_timeout(500)
    check(f'[{tag}] back after 11 min: your game, at the top', 'Dallas' in page.inner_text('.fp2') and page.evaluate('window.scrollY') == 0, (page.inner_text('.fp2'), page.evaluate('window.scrollY')))
    page.locator('.tabbtn[data-tab="home"]').click(); page.wait_for_timeout(300)
    page.locator('#cards .mc').first.click(); page.wait_for_timeout(600)
    k_other = page.evaluate("window.__fgt.S.curKey")
    # (closing the page saves the view, so the test view is set before the app starts)
    page.add_init_script("localStorage.setItem('fgt-view', JSON.stringify({v: 'match', w: 9, k: '%s', t: Date.now() - 2 * 60000}))" % k_other)
    page.reload(); page.wait_for_timeout(1200)
    check(f'[{tag}] reopen after 2 min: same game', 'Dallas' not in page.inner_text('.fp2'), page.inner_text('.fp2'))
    page.add_init_script("localStorage.setItem('fgt-view', JSON.stringify({v: 'match', w: 9, k: '%s', t: Date.now() - 11 * 60000}))" % k_other)
    page.reload(); page.wait_for_timeout(1200)
    check(f'[{tag}] reopen after 11 min: Matchup tab, your game', page.locator('.tabbtn.on[data-tab="match"]').count() == 1 and 'Dallas' in page.inner_text('.fp2'), page.inner_text('.fp2'))
    check(f'[{tag}] no page errors', not errs, errs)
    ctx.close()
    # ---------- v1.7.2: logos kept on the phone (no blink), Online bar always there (no jump) ----------
    tag = 'v1.7.2'
    ctx = br.new_context(viewport={'width': 393, 'height': 852}, device_scale_factor=2, is_mobile=True, has_touch=True,
                         user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
    ctx.route('**/*', route)
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append('pageerror: ' + str(e) + ' ' + str(getattr(e, 'stack', '') or '')[:400]))
    page.on('console', lambda m: errs.append(m.text + ' @ ' + str(m.location.get('url', ''))[:120] + ':' + str(m.location.get('lineNumber', ''))) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    state.update({'net': 'ok', 'worker': 'ok', 'fb': 'ok', 'logo_calls': 0, 'lp': 'p1', 'gordon_td': False, 'gordon_rush': 46, 'gordon_fl': 0, 'det_mia': (13, 10)})
    page.goto(f'http://127.0.0.1:{PORT}/index.html'); page.wait_for_timeout(300)
    page.evaluate("() => { localStorage.clear(); localStorage.setItem('fgt-team', JSON.stringify('11')); localStorage.setItem('fgt-gate', '1'); }")
    page.reload(); page.wait_for_timeout(800); wait_fresh(page)
    page.click('.mc.mine'); page.wait_for_timeout(500)
    nfl_srcs = lambda: page.evaluate("[...document.querySelectorAll('.prow .nfl img')].map(i => i.getAttribute('src'))")
    first = nfl_srcs()
    page.wait_for_timeout(3500)   # scoreboard + box scores in, logos saved in the background
    later = nfl_srcs()
    check(f'[{tag}] NFL logo links never change mid-visit (no reload when the scoreboard arrives)', first and first == later[:len(first)], (first[:3], later[:3]))
    saved = page.evaluate("Object.keys(JSON.parse(localStorage.getItem('fgt-logos') || '{}'))")
    want = page.evaluate("[...new Set([...document.querySelectorAll('.prow .nfl img')].map(i => i.getAttribute('data-src') || i.getAttribute('src')))]")
    check(f'[{tag}] logos saved on the phone', want and all(u in saved for u in want), (len(want), len(saved)))
    # reopen with no network: logos come from the phone, already loaded on the first paint
    state['net'] = 'off'; calls0 = state['logo_calls']
    page.add_init_script("window.__fgtT0 = performance.now();")
    page.reload(); page.wait_for_timeout(400)
    info = page.evaluate("(() => { const im = [...document.querySelectorAll('.prow .nfl img')]; return { n: im.length, blob: im.filter(i => i.src.startsWith('blob:')).length, done: im.filter(i => i.complete && i.naturalWidth > 0).length }; })()")
    check(f'[{tag}] offline reopen: every NFL logo shows from the phone', info['n'] >= 8 and info['blob'] == info['n'] and info['done'] == info['n'], info)
    check(f'[{tag}] offline reopen: no logo downloads', state['logo_calls'] == calls0, state['logo_calls'] - calls0)
    # Online bar: on every tab from the first paint, with your team; others joining never move anything
    state['net'] = 'ok'
    page.reload(); page.wait_for_timeout(150)
    first_bar = page.evaluate("(() => { const o = document.querySelector('#view .onstrip'); return o ? o.innerText : null; })()")
    check(f'[{tag}] Online bar there on open, with Dallas', first_bar is not None and 'Dallas' in first_bar, first_bar)
    page.wait_for_timeout(1500)
    geo = "(() => { const o = document.querySelector('#view .onstrip'), n = o && o.nextElementSibling; return o ? [Math.round(o.getBoundingClientRect().height * 10), n ? Math.round(n.getBoundingClientRect().top * 10) : -1] : null; })()"
    join = "(id) => { window.__fgt.CH.pres = Object.assign({}, window.__fgt.CH.pres, { ['t' + id]: { name: id, t: window.__fgt.srvNow() } }); window.__fgt.changed('pres'); }"
    res = {}
    for tb in ['home', 'match', 'standings', 'chat']:
        page.evaluate("() => { const p = {}; Object.keys(window.__fgt.CH.pres).forEach(k => { if(!/^t/.test(k)) p[k] = window.__fgt.CH.pres[k]; }); window.__fgt.CH.pres = p; window.__fgt.changed('pres'); }")
        page.click(f'.tabbtn[data-tab="{tb}"]'); page.wait_for_timeout(400)
        g0 = page.evaluate(geo); dot0 = page.locator('#view .onstrip span').count()
        page.evaluate(join, '4'); page.wait_for_timeout(200)
        g1 = page.evaluate(geo); dot1 = page.locator('#view .onstrip span').count()
        res[tb] = (g0, g1, dot0, dot1)
    check(f'[{tag}] someone coming online never moves anything (all four tabs)', all(v[0] and v[0] == v[1] and v[3] == v[2] + 1 for v in res.values()), res)
    blue = page.evaluate("(() => { const s = [...document.querySelectorAll('#view .onstrip span')].find(x => x.innerText.includes('Dallas')); return s ? !s.querySelector('.odot.off') && !!s.querySelector('.odot') : null; })()")
    check(f'[{tag}] your dot is blue when online', blue is True, blue)
    page.evaluate("() => { Object.defineProperty(navigator, 'onLine', {configurable: true, get: () => false}); window.dispatchEvent(new Event('offline')); }")
    page.wait_for_timeout(300)
    g_off = page.evaluate(geo)
    gray = page.evaluate("(() => { const s = [...document.querySelectorAll('#view .onstrip span')].find(x => x.innerText.includes('Dallas')); return s ? !!s.querySelector('.odot.off') : null; })()")
    check(f'[{tag}] offline: your team stays in the bar with a gray dot, nothing moves', gray is True and g_off == res['chat'][1], (gray, g_off, res['chat'][1]))
    page.evaluate("() => { delete navigator.onLine; window.dispatchEvent(new Event('online')); }"); page.wait_for_timeout(300)
    # empty bar (team not picked yet) is the same height as a bar with names
    h_empty = page.evaluate("(() => { const d = document.createElement('div'); d.className = 'onstrip'; d.innerHTML = '<small>ONLINE</small>'; document.querySelector('#view').prepend(d); const h = d.getBoundingClientRect().height; d.remove(); return Math.round(h * 10); })()")
    check(f'[{tag}] empty bar is the same height', h_empty == res['home'][1][0], (h_empty, res['home'][1][0]))
    ov = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
    check(f'[{tag}] no sideways scroll', ov <= 0, ov)
    if shots:
        page.click('.tabbtn[data-tab="match"]'); page.wait_for_timeout(400); page.screenshot(path=f'{SHOTS}/v172-match.png')
    check(f'[{tag}] no page errors', not errs, errs)
    state['fb'] = 'off'
    ctx.close()
    # logo cache helper (sw.js): a CBS logo that can't be copied is still there offline, from the phone's cache
    ctx = br.new_context(viewport={'width': 393, 'height': 852}, service_workers='allow')
    ctx.route('**/*', route)
    ctx.add_init_script("window.__fgtSW = 1;")
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
    state.update({'net': 'ok', 'cbs_logo_calls': 0})
    page.goto(f'http://127.0.0.1:{PORT}/index.html'); page.wait_for_timeout(300)
    page.evaluate("() => { localStorage.setItem('fgt-team', JSON.stringify('11')); localStorage.setItem('fgt-gate', '1'); }")
    page.reload(); page.wait_for_timeout(1500)
    ctl = page.evaluate("navigator.serviceWorker.ready.then(() => !!navigator.serviceWorker.controller)")
    if not ctl: page.reload(); page.wait_for_timeout(1000); ctl = page.evaluate("!!navigator.serviceWorker.controller")
    check(f'[{tag}] logo cache helper running', ctl)
    add = "(u) => new Promise(res => { const i = new Image(); i.referrerPolicy = 'no-referrer'; i.onload = () => res(i.naturalWidth); i.onerror = () => res(-1); i.src = u; })"
    lu = 'https://franleag.football.cbssports.com/team-logo/11?width=96&height=96'
    w1 = page.evaluate(add, lu); page.wait_for_timeout(500)
    inc = page.evaluate("(u) => caches.open('fgt-logos-v1').then(c => c.match(u, {ignoreVary: true})).then(r => !!r)", lu)
    check(f'[{tag}] CBS logo kept in the cache', w1 > 0 and inc, (w1, inc))
    state['net'] = 'off'
    page.reload(); page.wait_for_timeout(800)
    w2 = page.evaluate(add, lu)
    check(f'[{tag}] offline: CBS logo still shows', w2 > 0, w2)
    v = page.evaluate("fetch('version.txt?t=' + Date.now()).then(r => r.status).catch(() => 'blocked')")
    check(f'[{tag}] cache helper never touches the app or update check (offline = really offline)', v == 'blocked', v)
    check(f'[{tag}] cache helper: no page errors', not errs, errs)
    state['net'] = 'ok'
    ctx.close()
    br.close()
srv.shutdown()
# version.txt drives auto-update (v1.4.3): it must match APP_VERSION or phones never update
import re as _re2
_app = _re2.search(r"const APP_VERSION = '([0-9.]+)'", open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'index.html')).read()).group(1)
_vt = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'version.txt')).read().strip()
check('version.txt matches APP_VERSION', _vt == _app, (_vt, _app))
print('\nFAILED: ' + ', '.join(fails) if fails else '\nALL PASSED')
sys.exit(1 if fails else 0)
