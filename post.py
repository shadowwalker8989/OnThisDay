import argparse
import os
import sys
import time
from datetime import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import tweepy
from basketball_reference_web_scraper import client as bref


TODAY = datetime.now()
MONTH = TODAY.month
DAY = TODAY.day
FIRST_CAL_YEAR = 1946  # basketball-reference covers from the 1946-47 BAA/NBA season

_TEAM_ABBR = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
    "Seattle SuperSonics": "SEA", "New Jersey Nets": "NJN", "New Orleans Hornets": "NOH",
    "Vancouver Grizzlies": "VAN", "Philadelphia Warriors": "PHW", "San Francisco Warriors": "SFW",
    "St. Louis Hawks": "STL", "Baltimore Bullets": "BAL", "Washington Bullets": "WSB",
    "Capital Bullets": "CAP", "Kansas City Kings": "KCK", "Buffalo Braves": "BUF",
    "Cincinnati Royals": "CIN", "Minneapolis Lakers": "MNL", "San Diego Rockets": "SDR",
    "San Diego Clippers": "SDC", "Chicago Zephyrs": "CHZ", "Chicago Packers": "CHP",
    "New Orleans Jazz": "NOJ", "New York Nets": "NYN", "Milwaukee Hawks": "MLH",
    "Tri-Cities Blackhawks": "TCB", "Rochester Royals": "ROC", "Syracuse Nationals": "SYR",
    "Fort Wayne Pistons": "FTW", "Anderson Packers": "AND", "Chicago Stags": "CHS",
    "Cleveland Rebels": "CRB", "Pittsburgh Ironmen": "PIT", "Toronto Huskies": "TRH",
    "Washington Capitols": "WAC", "Providence Steamrollers": "PRO", "Sheboygan Redskins": "SHE",
    "Waterloo Hawks": "WAT", "Indianapolis Olympians": "INO",
}


def _team_to_abbr(team) -> str:
    name = team.value
    if name in _TEAM_ABBR:
        return _TEAM_ABBR[name]
    words = name.split()
    return "".join(w[0] for w in words)[:3].upper()


def fetch_games_on_this_day() -> list[dict]:
    all_games = []
    for cal_year in range(FIRST_CAL_YEAR, TODAY.year + 1):
        try:
            rows = bref.player_box_scores(day=DAY, month=MONTH, year=cal_year)
            for row in rows:
                if not row.get("seconds_played"):
                    continue
                reb = int(row.get("offensive_rebounds", 0)) + int(row.get("defensive_rebounds", 0))
                team = row["team"]
                opp = row["opponent"]
                all_games.append({
                    "player_name": row["name"],
                    "team": _team_to_abbr(team),
                    "pts": int(row.get("points", 0)),
                    "reb": reb,
                    "ast": int(row.get("assists", 0)),
                    "stl": int(row.get("steals", 0)),
                    "blk": int(row.get("blocks", 0)),
                    "matchup": f"{team.value} vs. {opp.value}",
                    "season_year": cal_year,
                    "game_date": f"{MONTH:02d}/{DAY:02d}/{cal_year}",
                })
            time.sleep(1.5)
        except Exception as exc:
            print(f"  Warning: {cal_year} failed — {exc}", file=sys.stderr)
            time.sleep(3.0)
    return all_games


def score_performance(g: dict) -> tuple[int, str]:
    pts, reb, ast, stl, blk = g["pts"], g["reb"], g["ast"], g["stl"], g["blk"]

    if pts >= 5 and reb >= 5 and ast >= 5 and stl >= 5 and blk >= 5:
        return (1000 + pts, "5x5")
    if pts >= 60:
        return (950 + pts, "60-point game")
    if pts >= 50:
        return (900 + pts, "50-point game")
    double_digit = sum(1 for v in (pts, reb, ast, stl, blk) if v >= 10)
    if double_digit >= 4:
        return (850 + pts, "quadruple-double")
    if double_digit >= 3:
        return (800 + pts, "triple-double")
    if pts >= 40:
        return (750 + pts, "40-point game")
    if reb >= 30:
        return (730 + reb, "30-rebound game")
    if blk >= 10:
        return (720 + blk, "10-block game")
    if stl >= 6:
        return (710 + stl, "6-steal game")
    if reb >= 20:
        return (700 + reb, "20-rebound game")
    if ast >= 20:
        return (670 + ast, "20-assist game")
    if ast >= 15:
        return (650 + ast, "15-assist game")
    return (pts, "strong performance")


def pick_best(games: list[dict]) -> tuple[dict, str] | None:
    if not games:
        return None
    scored = [(score_performance(g), g) for g in games]
    (priority, label), best = max(scored, key=lambda x: x[0][0])
    return best, label


def build_tweet(g: dict, label: str) -> str:
    name = g["player_name"]
    pts, reb, ast = g["pts"], g["reb"], g["ast"]
    stl, blk = g["stl"], g["blk"]
    team = g["team"]
    matchup = g["matchup"]
    year = g["season_year"]

    stats = f"{pts} PTS / {reb} REB / {ast} AST"
    if stl or blk:
        stats += f" / {stl} STL / {blk} BLK"

    if label == "5x5":
        emoji = "🔥💎"
    elif "60" in label:
        emoji = "🔥👑🐐"
    elif "50" in label:
        emoji = "🔥🏀"
    elif "quadruple" in label:
        emoji = "🔥💎👑"
    elif "triple" in label:
        emoji = "🔥📊"
    elif "40" in label:
        emoji = "🏀🔥"
    elif "30-rebound" in label:
        emoji = "💪😤"
    elif "10-block" in label:
        emoji = "🛡️🏀"
    elif "steal" in label:
        emoji = "🤚🏀"
    elif "rebound" in label:
        emoji = "💪🏀"
    elif "20-assist" in label:
        emoji = "🎯👁️"
    elif "assist" in label:
        emoji = "🎯🏀"
    else:
        emoji = "🏀"

    body = f"{emoji} On this day in {year}, {name} ({team}) had {stats} ({matchup})!"
    body += f" #NBA #OnThisDay #{team}"

    if len(body) > 280:
        body = body[:277] + "..."

    return body


def post_tweet(text: str):
    client = tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_SECRET"],
    )
    return client.create_tweet(text=text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Post an NBA 'On This Day' tweet.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    date_label = TODAY.strftime("%B %-d") if sys.platform != "win32" else TODAY.strftime("%B %#d")
    print(f"Searching NBA history for games on {date_label}…")

    games = fetch_games_on_this_day()
    print(f"Found {len(games)} player-game records across all seasons.")

    result = pick_best(games)
    if result is None:
        print("No games found for today's date in NBA history. Nothing to tweet.")
        return

    best, label = result
    print(f"\nSelected : {best['player_name']} ({best['team']}) — {label}")
    print(f"Stats    : {best['pts']} PTS / {best['reb']} REB / {best['ast']} AST / {best['stl']} STL / {best['blk']} BLK")
    print(f"Matchup  : {best['matchup']}  |  Date: {best['game_date']}")

    tweet = build_tweet(best, label)
    print(f"\nTweet ({len(tweet)} chars):\n  {tweet}\n")

    if args.dry_run:
        print("DRY RUN — tweet not posted.")
        return

    try:
        response = post_tweet(tweet)
        print(f"SUCCESS — tweet posted (id: {response.data['id']})")
    except Exception as exc:
        print(f"FAILED — could not post tweet: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
