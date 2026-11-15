# Week 10 — Jacksonville (Mike Burse) vs Miami (Donald Burse): lineup + trade timeline

Collected Sun Nov 15, 2026, ~6:15–6:35 PM ET, read-only. All times Eastern.

## Primary source: CBS transaction log (league site → Transactions → Team: Jacksonville → Type: Lineup)
URL: franleag.football.cbssports.com/transactions/7/lineup/
Neither Week 10 row is marked red ("RED = transaction performed by commissioner"), so both were made by the Jacksonville owner.

| CBS timestamp | Move (Week 10) |
|---|---|
| **Sat Nov 14, 6:40 PM** | George Pickens (WR, DAL) **Activated** · Ja'Kobi Lane (WR, BAL) Benched |
| **Sun Nov 15, 3:46 PM** | Ja'Kobi Lane **Activated** · George Pickens **Benched** |

Miami (team 6) made no lineup changes after Nov 12, 11:40 AM.

## Full timeline
| Time | Event | Source |
|---|---|---|
| Sep 27, 10:55 AM | Trade: Jacksonville gets Pickens from Miami; Miami gets Jameson Williams | CBS trades report |
| Nov 12, 3:16 AM | Jacksonville: Lane activated, Jonathan Taylor benched | CBS lineup log |
| Nov 12, 11:36 AM | Trade: **Miami gets Jonathan Taylor + Ja'Kobi Lane** from Jacksonville; **Jacksonville gets Jordan Mason + Ty Simpson** | CBS trades report |
| Nov 12, 11:37 AM | Miami activates Taylor + Bryce Young, benches Chicago players (CHI on bye Week 10: C. Williams, Swift, Monangai, Odunze, Loveland, Santos) | CBS lineup log (Miami) |
| Nov 12, 11:39 AM | Miami drops Lane (3 min after the trade), adds K Brandon McManus | CBS add/drop report |
| Nov 12, 4:21 PM | Jacksonville re-adds Lane (drops Deshaun Watson) | CBS add/drop report |
| Nov 12, 5:06 PM | Jacksonville: Lane activated, Jordan Mason benched | CBS lineup log |
| Nov 13, 5:17 PM | RotoWire/ESPN: Pickens (hamstring) **has no designation** for Sunday; practiced fully Friday. Same note on CBS's Pickens page ("Clear for return in Week 10") | ESPN news feed timestamp; CBS player page |
| Nov 14, 6:40 PM | Jacksonville: **Pickens activated**, Lane benched | CBS lineup log |
| Nov 15, 9:33 AM | Our capture: Pickens starting (flex), Lane on bench | `history/h2h-w10.json` (CBS feed via our app) |
| Nov 15, 12:12–12:14 PM | Same lineup, confirmed by CBS (our app) **and** FantasyPros' synced copy | `history/snap-w10-1212.json` |
| Nov 15, **2:54:35 PM** | Pickens **officially ACTIVE** (Joe Hoyt, Dallas Morning News, on X; time decoded from post ID 2122055685370191912) | X post ID timestamp |
| Nov 15, 3:19 PM | FantasyPros news alert: Pickens active for Week 10 | FantasyPros news page |
| Nov 15, **3:46 PM** | Jacksonville: **Lane activated, Pickens benched** — 52 min after Pickens was announced active | CBS lineup log |
| Nov 15, 4:25 PM | DAL–SF kickoff; Pickens locks on Jacksonville's bench | ESPN schedule |
| Nov 15, 1st half | Pickens: TD 35 yds (Q1 1:15), TD 39 yds (Q2 4:19); **18 CBS points by 6:20 PM, on the bench** | ESPN play-by-play; CBS points via our app |

## Matchup state at 3:46 PM (rebuilt from ESPN play-by-play wall-clock times)
All four relevant 1 PM games were in the 4th quarter (IND–MIA Q4 9:49, HOU–CLE Q4 5:19, CAR–NO Q4 3:49, KC–ATL Q4 5:54).
- **Miami 23:** Young 3 (137 pass yds at 3:46; 200 final), Taylor 6, Jameson Williams 6, McMillan 3, Pitts 5. Still to play: Bernard (SNF), McManus (4:05), 49ers D/ST (4:25) ≈ 17.5 projected.
- **Jacksonville 4:** Warren 0, Browns D/ST 4 (one sack came after 3:46). Still to play: Brissett, Corum, Pickens, Higgins, Flowers, Myers ≈ 56.2 projected.
- **Projected finals at 3:46:** Jacksonville ≈ 60 with Pickens / ≈ 56 after swapping in Lane; Miami ≈ 40.5. Miami led on the scoreboard; Jacksonville was the clear projected winner.
- Pregame projections: Pickens 7.1 (ours) / 8.6 (FantasyPros); Lane 2.7 / 4.0.

## Score at 6:20 PM (our app, CBS points)
Miami 38 (3 left: Bernard, McManus, 49ers) · Jacksonville 24 (left: Brissett, Flowers, Lane — Monday night; Higgins — Sunday night). Our win %: Jacksonville 90%. Higgins, Brissett, Flowers and Lane can still be moved until their games start.

## Context
- Only 3 trades in the league this season; 2 are Jacksonville–Miami. 2024: one Jacksonville–Miami trade (Nov 7, 2024: Miami got Odunze + Tillman; Jacksonville got Flowers + Higgins). 2025: no trades.
- Jacksonville (4-5, NFC) and Miami (5-4, AFC) are in different divisions; Week 10 is their first meeting this season (Weeks 1–9 opponents from `tests/league-weeks-2026.json`).

## What this does and doesn't show
- **Proven:** the exact times of both lineup moves; that the owner (not the commissioner) made them; that Pickens had no injury designation (Fri 5:17 PM) and was announced active at 2:54 PM, 52 min before he was benched for a lower-projected player; the Nov 12 trade timing and Miami's bye-week roster hole it filled.
- **Not shown by data:** why. CBS records when, not intent.
