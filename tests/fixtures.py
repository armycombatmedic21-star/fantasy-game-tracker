"""Fake Worker + ESPN payloads for the Fantasy Game Tracker tests (shapes copied from the real feeds, Nov 8 2026)."""
import json, time

NOW = int(time.time())

def gi(status, opp, home, ts, q='1', tr='15:00', hs='0', as_='0'):
    return {"week": "9", "quarter": q, "game_status": status, "home_game": home, "game_start_timestamp": str(ts),
            "game_start_date_time": "11/8 1:00", "game_start_time": "1:00 pm", "home_score": hs, "away_score": as_,
            "minutes_remaining": "60", "time_remaining": tr, "opponent": opp, "game_abbr": "NFL_X"}

LIVE_TS = NOW - 3600
LATE_TS = NOW + 3 * 3600
FINAL_TS = NOW - 6 * 3600

def P(pid, name, pos, status, team, fpts, stats, g, rpos=None):
    return {"id": str(pid), "fullname": name, "firstname": name.split()[0], "lastname": name.split()[-1], "position": pos,
            "roster_pos": rpos or pos, "status": status, "pro_team": team, "pro_status": "A", "fpts": fpts,
            "fpts_period": fpts, "fpts_today": fpts, "stats_period": stats, "stats_today": stats,
            "game_info": g, "game_abbr": "NFL_X", "eligible_positions_display": pos}

G_FINAL_CIN = gi('F', 'ATL', 0, FINAL_TS, '4', '0:00', '17', '34')
G_LIVE_MIA = gi('P', 'DET', 1, LIVE_TS, '3', '8:14', '10', '13')
G_LIVE_DET = gi('P', 'MIA', 0, LIVE_TS, '3', '8:14', '10', '13')
G_LIVE_KC = gi('P', 'NYJ', 1, LIVE_TS, '3', '2:00', '14', '12')
G_LATE = lambda opp, home: gi('S', opp, home, LATE_TS)

def team(tid, name, home, opp, players, division, order, record):
    return {"id": str(tid), "name": name, "abbr": name[:3], "long_abbr": name, "short_name": name[:6], "logo": "",
            "division": division, "order": order, "pts": 0, "opp_team_id": str(opp), "record": record,
            "home_away": "home" if home else "away", "players": players, "w": record.split('-')[0], "l": record.split('-')[1], "t": 0}

def lineup(prefix, qb, rb1, rb2_or_wr3, wr1, wr2, te, k, dst, flex_is_rb=True, bench=None):
    pl = [qb, rb1]
    pl += [rb2_or_wr3, wr1, wr2] if flex_is_rb else [wr1, wr2, rb2_or_wr3]
    pl += [te, k, dst]
    return pl + (bench or [])

def build_live():
    dal = lineup('d',
        P(1, 'Joe Burrow', 'QB', 'Active', 'CIN', '33', '271 PaYd, 3 PaTD (47,4,8), 7 RuYd, RuTD (1)', G_FINAL_CIN),
        P(2, 'Ollie Gordon II', 'RB', 'Active', 'MIA', '3', '46 RuYd', G_LIVE_MIA),
        P(3, 'Woody Marks', 'RB', 'Active', 'HOU', 0, '', G_LATE('LAC', 0)),
        P(4, "Ja'Marr Chase", 'WR', 'Active', 'CIN', '20', '155 ReYd, ReTD (47)', G_FINAL_CIN),
        P(5, 'Matthew Golden', 'WR', 'Active', 'GB', 0, '', G_LATE('NE', 0)),
        P(6, 'Harold Fannin Jr.', 'TE', 'Active', 'CLE', 0, '', G_LATE('NO', 0)),
        P(7, 'Will Reichard', 'K', 'Active', 'MIN', 0, '', G_LATE('BUF', 1)),
        P(8, 'Chiefs', 'DST', 'Active', 'KC', '7', '12 PA, DFR', G_LIVE_KC),
        bench=[P(9, 'Michael Penix Jr.', 'QB', 'Reserve', 'ATL', '16', '162 PaYd, PaTD (1), PaInt, 50 RuYd', gi('F', 'CIN', 1, FINAL_TS, '4', '0:00', '17', '34')),
               P(10, 'Carnell Tate', 'WR', 'Reserve', 'TEN', 0, '', {}), P(10, 'Carnell Tate', 'WR', 'Injured', 'TEN', '', '', {})])
    ne = lineup('n',
        P(21, 'Jordan Love', 'QB', 'Active', 'GB', 0, '', G_LATE('NE', 0)),
        P(22, 'Kenneth Walker III', 'RB', 'Active', 'KC', '15', '21 RuYd, 38 ReYd, 2 ReTD (7,25)', G_LIVE_KC),
        P(23, 'Saquon Barkley', 'RB', 'Active', 'PHI', 0, '', G_LATE('NYG', 1)),
        P(24, 'Nico Collins', 'WR', 'Active', 'HOU', 0, '', G_LATE('LAC', 0)),
        P(25, 'Ryan Flournoy', 'WR', 'Active', 'DAL', 0, '', G_LATE('IND', 0)),
        P(26, 'Sam LaPorta', 'TE', 'Active', 'DET', 0, '11 ReYd', G_LIVE_DET),
        P(27, 'Trey Smack', 'K', 'Active', 'GB', 0, '', G_LATE('NE', 0)),
        P(28, 'Bengals', 'DST', 'Active', 'CIN', '7', '17 PA, Int', G_FINAL_CIN))
    teams = [team(11, 'Dallas', True, 5, dal, 'AFC', 4, '3-5'), team(5, 'New England', False, 11, ne, 'AFC', 5, '3-5')]
    names = [(4, 'Detroit', 6, 'Miami'), (9, 'Baltimore', 7, 'Jacksonville '), (3, 'Buffalo ', 12, 'Pittsburgh'), (2, 'Green Bay', 1, 'Oakland'), (8, 'Indianapolis', 10, 'New York')]
    pid = 100
    for a, an, b, bn in names:
        for tid, tn, opp, home in ((a, an, b, False), (b, bn, a, True)):
            pl = []
            for pos in ['QB', 'RB', 'WR', 'WR', 'WR', 'TE', 'K', 'DST']:
                pid += 1
                live = pid % 3 == 0
                g = G_LIVE_KC if live else G_LATE('XX', 0)
                stats = {'QB': '180 PaYd, PaTD (12)', 'RB': '55 RuYd', 'WR': '41 ReYd', 'TE': '12 ReYd', 'K': 'XP', 'DST': '7 PA'}[pos] if live else ''
                pts = {'QB': '11', 'RB': '6', 'WR': '3', 'TE': '0', 'K': '1', 'DST': '9'}[pos] if live else 0
                pl.append(P(pid, ('Player %d' % pid) if pos != 'DST' else 'Defense%d' % pid, pos, 'Active', 'KC' if live else 'SEA', pts, stats, g))
            teams.append(team(tid, tn, home, opp, pl, 'NFC' if tid in (9, 7, 8, 10, 1, 2) else 'AFC', 1, '4-4'))
    return {"live_scoring": {"period": "9", "teams": teams, "name": "New Franchise League"}}

def build_future(week):
    """/live?week=N: Week 10 pairings (real), Week 11 divisional, Week 12 TBA (no opp ids)."""
    pairs = {10: [(11, 10), (3, 9), (4, 1), (2, 5), (8, 12), (7, 6)], 11: [(11, 6), (3, 4), (5, 12), (9, 8), (7, 10), (2, 1)]}.get(week, [])
    opp = {}
    for a, b in pairs:
        opp[a], opp[b] = b, a
    return {"live_scoring": {"teams": [{"id": str(t), "name": "T%d" % t, "opp_team_id": str(opp[t]) if t in opp else ""} for t in range(1, 13)]}}

def build_standings():
    afc = [(3, 'Buffalo ', 6, 2, 'W1', 0), (12, 'Pittsburgh', 5, 3, 'W2', 1), (6, 'Miami', 5, 3, 'W3', 1), (11, 'Dallas', 3, 5, 'L1', 3), (5, 'New England', 3, 5, 'L2', 3), (4, 'Detroit', 2, 6, 'L2', 4)]
    nfc = [(8, 'Indianapolis', 7, 1, 'W2', 0), (9, 'Baltimore', 5, 3, 'W2', 2), (7, 'Jacksonville ', 4, 4, 'L4', 3), (10, 'New York', 3, 5, 'L3', 4), (1, 'Oakland', 3, 5, 'W1', 4), (2, 'Green Bay', 2, 6, 'L1', 5)]
    def t(row, div, order):
        tid, n, w, l, s, gb = row
        return {"id": str(tid), "name": n, "abbr": "XX", "division": div, "order": order, "wins": w, "losses": l, "ties": 0, "streak": s, "games_back": gb,
                "points_scored": 600 + tid, "points_against": 580 + tid, "division_wins": 2, "division_losses": 1, "division_ties": 0, "logo": ""}
    return {"overall_standings": {"period": "9", "divisions": [
        {"id": "AFC", "teams": [t(r, 'AFC', i + 1) for i, r in enumerate(afc)]},
        {"id": "NFC", "teams": [t(r, 'NFC', i + 1) for i, r in enumerate(nfc)]}]}}

def iso(ts):
    return time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime(ts))

def comp(eid, away, aid, home, hid, state, name, period, clock, as_, hs, ts, lp=''):
    return {"id": eid, "date": iso(ts), "status": {"type": {"state": state, "completed": state == 'post', "name": name, "shortDetail": ""}, "period": period, "displayClock": clock},
            "competitions": [{"neutralSite": False, "competitors": [
                {"homeAway": "home", "score": str(hs), "team": {"abbreviation": home, "id": hid, "logos": []}},
                {"homeAway": "away", "score": str(as_), "team": {"abbreviation": away, "id": aid, "logos": []}}],
                "situation": {"lastPlay": {"id": lp}} if lp else {}}]}

def build_scoreboard(lp='p1', det_mia=(13, 10), kc=(12, 14)):
    ev = [comp('1', 'CIN', '4', 'ATL', '1', 'post', 'STATUS_FINAL', 4, '0:00', 34, 17, FINAL_TS),
          comp('2', 'DET', '8', 'MIA', '15', 'in', 'STATUS_IN_PROGRESS', 3, '8:14', det_mia[0], det_mia[1], LIVE_TS, lp),
          comp('3', 'NYJ', '20', 'KC', '12', 'in', 'STATUS_IN_PROGRESS', 3, '2:00', kc[0], kc[1], LIVE_TS, lp + 'k'),
          comp('4', 'GB', '9', 'NE', '17', 'pre', 'STATUS_SCHEDULED', 0, '0:00', 0, 0, LATE_TS),
          comp('5', 'BUF', '2', 'MIN', '16', 'pre', 'STATUS_SCHEDULED', 0, '0:00', 0, 0, LATE_TS),
          comp('6', 'HOU', '34', 'LAC', '24', 'pre', 'STATUS_SCHEDULED', 0, '0:00', 0, 0, LATE_TS),
          comp('7', 'CLE', '5', 'NO', '18', 'pre', 'STATUS_SCHEDULED', 0, '0:00', 0, 0, LATE_TS),
          comp('8', 'ARI', '22', 'SEA', '26', 'pre', 'STATUS_SCHEDULED', 0, '0:00', 0, 0, LATE_TS)]
    return {"week": {"number": 9}, "season": {"type": 2}, "events": ev}

def block(name, keys, athletes):
    return {"name": name, "keys": keys, "labels": keys, "totals": [], "athletes": [{"athlete": {"id": str(i), "displayName": n}, "stats": s} for i, (n, s) in enumerate(athletes)]}

PASSK = ["completions/passingAttempts", "passingYards", "yardsPerPassAttempt", "passingTouchdowns", "interceptions", "sacks-sackYardsLost", "adjQBR", "QBRating"]
RUSHK = ["rushingAttempts", "rushingYards", "yardsPerRushAttempt", "rushingTouchdowns", "longRushing"]
RECK = ["receptions", "receivingYards", "yardsPerReception", "receivingTouchdowns", "longReception", "receivingTargets"]
FUMK = ["fumbles", "fumblesLost", "fumblesRecovered"]
KICKK = ["fieldGoalsMade/fieldGoalAttempts", "fieldGoalPct", "longFieldGoalMade", "extraPointsMade/extraPointAttempts", "totalKickingPoints"]

def summary(final, teams, plays, team_stats=None):
    return {"header": {"competitions": [{"status": {"type": {"name": "STATUS_FINAL" if final else "STATUS_IN_PROGRESS"}}}]},
            "boxscore": {"players": [{"team": {"abbreviation": ab}, "statistics": blocks} for ab, blocks in teams],
                         "teams": [{"team": {"abbreviation": ab}, "statistics": [{"name": k, "displayValue": v} for k, v in st.items()]} for ab, st in (team_stats or {}).items()]},
            "scoringPlays": [{"id": str(i), "type": {"text": t, "abbreviation": a}, "scoringType": {"abbreviation": a, "name": {'TD': 'touchdown', 'FG': 'field-goal', 'SF': 'safety'}.get(a, '')}, "text": x, "team": {"abbreviation": ab}}
                             for i, (ab, t, a, x) in enumerate(plays)]}

def sum_cin_atl():
    return summary(True, [
        ('CIN', [block('passing', PASSK, [('Joe Burrow', ["24/29", "271", "9.3", "3", "0", "2-6", "92", "140"])]),
                 block('rushing', RUSHK, [('Joe Burrow', ["2", "7", "3.5", "1", "6"]), ('Chase Brown', ["9", "57", "6.3", "0", "19"])]),
                 block('receiving', RECK, [("Ja'Marr Chase", ["10", "155", "15.5", "1", "47", "12"]), ('Tee Higgins', ["3", "32", "10", "2", "12", "4"])]),
                 block('fumbles', FUMK, []),
                 block('kicking', KICKK, [('Evan McPherson', ["2/2", "100", "57", "4/4", "10"])])]),
        ('ATL', [block('passing', PASSK, [('Michael Penix Jr.', ["15/30", "162", "5", "1", "1", "0-0", "", ""])]),
                 block('rushing', RUSHK, [('Michael Penix Jr.', ["5", "50", "10", "0", "20"])]),
                 block('fumbles', FUMK, [])])],
        [('ATL', 'Passing Touchdown', 'TD', 'Charlie Woerner 1 Yd pass from Michael Penix Jr. (Nick Folk Kick)'),
         ('CIN', 'Passing Touchdown', 'TD', "Ja'Marr Chase 47 Yd pass from Joe Burrow (Evan McPherson Kick)"),
         ('ATL', 'Field Goal Good', 'FG', 'Nick Folk 31 Yd Field Goal'),
         ('CIN', 'Rushing Touchdown', 'TD', 'Joe Burrow 1 Yd Rush (Evan McPherson Kick)'),
         ('CIN', 'Passing Touchdown', 'TD', 'Tee Higgins 4 Yd pass from Joe Burrow (Evan McPherson Kick)'),
         ('CIN', 'Field Goal Good', 'FG', 'Evan McPherson 57 Yd Field Goal '),
         ('CIN', 'Passing Touchdown', 'TD', 'Tee Higgins 8 Yd pass from Joe Burrow (Evan McPherson Kick)'),
         ('CIN', 'Field Goal Good', 'FG', 'Evan McPherson 43 Yd Field Goal ')],
        {'CIN': {'fumblesLost': '0', 'interceptions': '0', 'sacksYardsLost': '2-6'}, 'ATL': {'fumblesLost': '0', 'interceptions': '1', 'sacksYardsLost': '0-0'}})

def sum_det_mia(gordon_rush=46, gordon_td=False, gordon_fl=0):
    plays = []
    if gordon_td:
        plays.append(('MIA', 'Rushing Touchdown', 'TD', 'Ollie Gordon II 44 Yd Run (Jason Sanders Kick)'))
    return summary(False, [
        ('MIA', [block('rushing', RUSHK, [('Ollie Gordon II', ["9", str(gordon_rush), "5", "1" if gordon_td else "0", "44"])]),
                 block('fumbles', FUMK, [('Ollie Gordon II', [str(gordon_fl), str(gordon_fl), "0"])] if gordon_fl else [])]),
        ('DET', [block('receiving', RECK, [('Sam LaPorta', ["2", "11", "5.5", "0", "8", "3"])])])], plays)

def sum_nyj_kc():
    return summary(False, [
        ('KC', [block('rushing', RUSHK, [('Kenneth Walker III', ["7", "21", "3", "0", "9"])]),
                block('receiving', RECK, [('Kenneth Walker III', ["4", "38", "9", "2", "25", "5"])])]),
        ('NYJ', [block('passing', PASSK, [('Justin Fields', ["10/18", "90", "5", "0", "0", "0-0", "", ""])]),
                 block('fumbles', FUMK, [('Breece Hall', ["1", "1", "0"])])])],
        [('KC', 'Passing Touchdown', 'TD', 'Kenneth Walker III 7 Yd pass from Patrick Mahomes (Harrison Butker Kick)'),
         ('KC', 'Passing Touchdown', 'TD', 'Kenneth Walker III 25 Yd pass from Patrick Mahomes (Harrison Butker Kick)')],
        {'NYJ': {'fumblesLost': '1', 'interceptions': '0', 'sacksYardsLost': '0-0'}})

def sum_return_td():
    """Kickoff return TD by a WR + own-fumble recovery TD by a RB (both 6 to the player; D/ST only for the return)."""
    return summary(False, [('CHI', [block('receiving', RECK, [('Luther Burden III', ["2", "20", "10", "0", "12", "3"])])])],
        [('CHI', 'Kickoff Return Touchdown', 'TD', 'Luther Burden III 98 Yd Kickoff Return (Cairo Santos Kick)'),
         ('CHI', 'Fumble Recovery (Own)', 'TD', "D'Andre Swift 0 Yd Fumble Recovery (Cairo Santos Kick)")])
