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

state = {'lp': 'p1', 'gordon_td': False, 'gordon_rush': 46, 'gordon_fl': 0, 'det_mia': (13, 10), 'summary_calls': 0, 'sb_calls': 0}
fails = []
def check(name, cond, extra=''):
    print(('PASS ' if cond else 'FAIL ') + name + ((' :: ' + str(extra)) if extra and not cond else ''))
    if not cond: fails.append(name)

def route(r):
    u = r.request.url
    if 'workers.dev/live' in u:
        if 'week=' in u:
            return r.fulfill(json={"ok": True, "source": "cbs", "at": int(time.time() * 1000), "data": F.build_future(int(u.split('week=')[1].split('&')[0]))})
        return r.fulfill(json={"ok": True, "source": "cbs", "feed": "league/scoring/live", "at": int(time.time() * 1000) - 20000, "data": F.build_live()})
    if 'workers.dev/standings' in u:
        return r.fulfill(json={"ok": True, "source": "cbs", "at": int(time.time() * 1000), "data": F.build_standings()})
    if '/scoreboard' in u:
        state['sb_calls'] += 1
        return r.fulfill(json=F.build_scoreboard(state['lp'], state['det_mia']))
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

        page.click('.mc.mine')
        page.wait_for_timeout(700)
        check(f'[{tag}] matchup screen opens', page.is_visible('#hero'))
        rows = page.locator('.plist').first.locator('.prow').count()
        check(f'[{tag}] 8 starter rows', rows == 8, rows)
        txt = page.inner_text('#mrows')
        check(f'[{tag}] FLEX row is Woody Marks', 'W. Marks' in page.inner_text('.prow[data-row="4"]'))
        check(f'[{tag}] Tate shows once on the bench (IR)', txt.count('C. Tate') == 1 and 'IR' in page.inner_text('.plist:nth-of-type(2)'), txt)
        hero = page.inner_text('#hero')
        check(f'[{tag}] header: Win Probability, projections, record + division rank, VS', 'Win Probability' in hero and '3-5 · 4th AFC' in hero and page.locator('#hero .pj span').count() == 2 and page.locator('#hero .vsw svg').count() == 1, hero)
        check(f'[{tag}] header Divisional Week badge', page.locator('#hero .divwk').count() == 1)
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

        wa0 = page.evaluate("window.__fgt.ENG.res.m[Object.keys(window.__fgt.ENG.res.m).find(k => k.indexOf('5-11') >= 0)].wa")
        state.update({'lp': 'p2', 'gordon_td': True, 'gordon_rush': 90, 'det_mia': (13, 17)})
        page.wait_for_timeout(12500)
        r1 = page.inner_text('.prow[data-row="1"]')
        check(f'[{tag}] TD badge with length after a live TD', 'TD' in r1 and '44 yd run' in r1, r1)
        check(f'[{tag}] score glow after the jump', page.locator('.prow[data-row="1"] b.glow').count() == 1)
        check(f'[{tag}] Gordon now 6 + 8 = 14', '14' in r1, r1)
        wa1 = page.evaluate("window.__fgt.ENG.res.m[Object.keys(window.__fgt.ENG.res.m).find(k => k.indexOf('5-11') >= 0)].wa")
        check(f'[{tag}] win % updates live after the TD (home side = Dallas)', wa1 != wa0, (wa0, wa1))
        if shots: page.screenshot(path=f'{SHOTS}/{tag}-06-td.png')
        state.update({'lp': 'p3', 'gordon_fl': 1, 'det_mia': (13, 17)})
        page.wait_for_timeout(11000)
        r1 = page.inner_text('.prow[data-row="1"]')
        check(f'[{tag}] FUMBLE LOST badge', 'FUMBLE LOST' in r1, r1)
        state.update({'lp': 'p1', 'gordon_td': False, 'gordon_rush': 46, 'gordon_fl': 0, 'det_mia': (13, 10)})

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
        check(f'[{tag}] Avg., no +this week', '76.4 avg.' in det and 'this week' not in det, det)
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
    br.close()
srv.shutdown()
# version.txt drives auto-update (v1.4.3): it must match APP_VERSION or phones never update
import re as _re2
_app = _re2.search(r"const APP_VERSION = '([0-9.]+)'", open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'index.html')).read()).group(1)
_vt = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'version.txt')).read().strip()
check('version.txt matches APP_VERSION', _vt == _app, (_vt, _app))
print('\nFAILED: ' + ', '.join(fails) if fails else '\nALL PASSED')
sys.exit(1 if fails else 0)
