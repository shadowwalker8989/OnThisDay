import argparse
import os
import sys
import time
from datetime import datetime

# Ensure UTF-8 output on Windows so player names with diacritics don't crash
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import tweepy
from nba_api.library.http import NBAStatsHTTP
from nba_api.stats.endpoints import LeagueGameLog, LeagueLeaders, PlayerCareerStats
from nba_api.stats.library.parameters import SeasonTypeAllStar
from nba_api.stats.static import players as nba_players

NBAStatsHTTP.headers = {
    "Host": "stats.nba.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Connection": "keep-alive",
    "Referer": "https://stats.nba.com/",
    "Origin": "https://www.nba.com",
}


TODAY = datetime.now()
MONTH = TODAY.month
DAY = TODAY.day
CURRENT_SEASON_YEAR = TODAY.year if TODAY.month >= 10 else TODAY.year - 1

FIRST_SEASON = 1959

CAREER_POINT_MILESTONES = [10_000, 15_000, 20_000, 25_000, 30_000, 35_000, 38_388]


def season_string(year: int) -> str:
    """Convert start year to NBA season format e.g. 2023 -> '2023-24'."""
    return f"{year}-{str(year + 1)[-2:]}"


SEASON_TYPES = ["Regular Season", "Playoffs"]


def fetch_games_on_this_day() -> list[dict]:
    """Query LeagueGameLog for every season (regular + playoffs) matching today's M/D."""
    all_games = []

    for year in range(FIRST_SEASON, CURRENT_SEASON_YEAR + 1):
        season = season_string(year)
        # Calendar year for this date: Oct-Dec belongs to the season start year, Jan-Jun to start+1
        cal_year = year if MONTH >= 10 else year + 1
        date_str = f"{MONTH:02d}/{DAY:02d}/{cal_year}"

        for stype in SEASON_TYPES:
            try:
                log = LeagueGameLog(
                    season=season,
                    season_type_all_star=stype,
                    player_or_team_abbreviation="P",
                    date_from_nullable=date_str,
                    date_to_nullable=date_str,
                )
                df = log.get_data_frames()[0]
                if df.empty:
                    time.sleep(0.4)
                    continue
                for _, row in df.iterrows():
                    all_games.append({
                        "player_name": row["PLAYER_NAME"],
                        "team": row["TEAM_ABBREVIATION"],
                        "pts": int(row["PTS"]),
                        "reb": int(row["REB"]),
                        "ast": int(row["AST"]),
                        "stl": int(row["STL"]),
                        "blk": int(row["BLK"]),
                        "matchup": row["MATCHUP"],
                        "season_year": year,
                        "game_date": row["GAME_DATE"],
                        "season_type": stype,
                    })
                time.sleep(0.6)
            except Exception as exc:
                print(f"  Warning: {season} {stype} failed — {exc}", file=sys.stderr)
                time.sleep(1.5)

    return all_games


def score_performance(g: dict) -> tuple[int, str]:
    """
    Return (priority_score, label) for a performance.
    Higher score = better pick.
    """
    pts, reb, ast, stl, blk = g["pts"], g["reb"], g["ast"], g["stl"], g["blk"]

    # 5x5: 5+ in all five categories
    if pts >= 5 and reb >= 5 and ast >= 5 and stl >= 5 and blk >= 5:
        return (1000 + pts, "5x5")

    if pts >= 60:
        return (950 + pts, "60-point game")

    if pts >= 50:
        return (900 + pts, "50-point game")

    # Quadruple-double / Triple-double
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

    # Fallback: raw points
    return (pts, "strong performance")


def pick_best(games: list[dict]) -> tuple[dict, str] | None:
    if not games:
        return None
    scored = [(score_performance(g), g) for g in games]
    (priority, label), best = max(scored, key=lambda x: x[0][0])
    return best, label


def check_scoring_champion(player_name: str, season_year: int) -> float | None:
    """Return player's PPG if they led the NBA in scoring that regular season."""
    season = season_string(season_year)
    try:
        leaders = LeagueLeaders(
            season=season,
            season_type_all_star="Regular Season",
            per_mode_simple="PerGame",
            stat_category_abbreviation="PTS",
        )
        df = leaders.get_data_frames()[0]
        if df.empty:
            return None
        max_gp = int(df["GP"].max())
        qualified = df[df["GP"] >= max(int(max_gp * 0.7), 30)]
        if qualified.empty:
            return None
        top = qualified.loc[qualified["PTS"].idxmax()]
        if top["PLAYER"].strip().lower() == player_name.strip().lower():
            return round(float(top["PTS"]), 1)
    except Exception:
        pass
    return None


def check_career_milestone(player_name: str, season_year: int) -> str | None:
    """Return milestone string if player crossed a career points threshold this season."""
    matches = nba_players.find_players_by_full_name(player_name)
    if not matches:
        return None
    player_id = matches[0]["id"]
    try:
        career = PlayerCareerStats(player_id=player_id)
        df = career.get_data_frames()[0]
        if df.empty:
            return None
        total_before = 0
        total_through = 0
        for _, row in df.iterrows():
            yr_str = str(row.get("SEASON_ID", ""))
            if len(yr_str) < 4:
                continue
            yr = int(yr_str[:4])
            try:
                pts = int(row["PTS"])
            except (ValueError, TypeError):
                pts = 0
            if yr < season_year:
                total_before += pts
            if yr <= season_year:
                total_through += pts
        for milestone in CAREER_POINT_MILESTONES:
            if total_before < milestone <= total_through:
                return f"{milestone:,} career points"
    except Exception:
        pass
    return None


def build_tweet(g: dict, label: str, milestone_note: str | None = None) -> str:
    name = g["player_name"]
    pts, reb, ast = g["pts"], g["reb"], g["ast"]
    stl, blk = g["stl"], g["blk"]
    team = g["team"]
    matchup = g["matchup"]
    year = g["season_year"]

    # Stat line
    stats = f"{pts} PTS / {reb} REB / {ast} AST"
    if stl or blk:
        stats += f" / {stl} STL / {blk} BLK"

    # Emoji selection
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

    playoff_tag = " (Playoffs)" if g.get("season_type") == "Playoffs" else ""
    body = (
        f"{emoji} On this day in {year}{playoff_tag}, {name} ({team}) had "
        f"{stats} ({matchup})!"
    )
    if milestone_note:
        body += f" {milestone_note}."
    body += f" #NBA #OnThisDay #{team}"

    # Trim to 280 if necessary (shouldn't happen often)
    if len(body) > 280:
        body = body[:277] + "..."

    return body


def post_tweet(text: str) -> None:
    api_key = os.environ["TWITTER_API_KEY"]
    api_secret = os.environ["TWITTER_API_SECRET"]
    access_token = os.environ["TWITTER_ACCESS_TOKEN"]
    access_secret = os.environ["TWITTER_ACCESS_SECRET"]

    client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_secret,
    )
    response = client.create_tweet(text=text)
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description="Post an NBA 'On This Day' tweet.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and score performances, print the tweet, but do not post.",
    )
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

    print(f"\nSelected performance : {best['player_name']} ({best['team']}) — {label}")
    print(f"Stats               : {best['pts']} PTS / {best['reb']} REB / {best['ast']} AST / {best['stl']} STL / {best['blk']} BLK")
    print(f"Matchup             : {best['matchup']}  |  Date: {best['game_date']}")

    print("Checking scoring title and career milestones…")
    title_ppg = check_scoring_champion(best["player_name"], best["season_year"])
    time.sleep(0.6)
    milestone = check_career_milestone(best["player_name"], best["season_year"])
    time.sleep(0.6)

    notes = []
    if title_ppg:
        notes.append(f"🏆 Scoring champ that season ({title_ppg} PPG)")
    if milestone:
        notes.append(f"📈 Crossed {milestone} this season")
    milestone_note = " · ".join(notes) if notes else None
    if milestone_note:
        print(f"Milestone           : {milestone_note}")

    tweet = build_tweet(best, label, milestone_note)
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
