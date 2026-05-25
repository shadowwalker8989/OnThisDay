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
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests


TODAY = datetime.now()
MONTH = TODAY.month
DAY = TODAY.day
FIRST_CAL_YEAR = 1946


def _fetch_daily_leaders(month: int, day: int, year: int) -> str:
    url = (
        f"https://www.basketball-reference.com/friv/dailyleaders.fcgi"
        f"?month={month}&day={day}&year={year}&type=all"
    )
    resp = curl_requests.get(url, impersonate="chrome124", timeout=30)
    resp.raise_for_status()
    return resp.text


def _parse_box_scores(html: str, cal_year: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "stats"})
    if table is None:
        return []

    def td(row, stat: str) -> str:
        cell = row.find("td", {"data-stat": stat})
        return cell.get_text(strip=True) if cell else ""

    def nt(row, stat: str) -> int:
        val = td(row, stat)
        try:
            return int(val) if val else 0
        except ValueError:
            return 0

    results = []
    for row in table.select("tbody tr"):
        if "thead" in (row.get("class") or []):
            continue
        player = td(row, "player")
        if not player:
            continue
        team = td(row, "team_id")
        opp = td(row, "opp_id")
        results.append({
            "player_name": player,
            "team": team,
            "pts": nt(row, "pts"),
            "reb": nt(row, "trb"),
            "ast": nt(row, "ast"),
            "stl": nt(row, "stl"),
            "blk": nt(row, "blk"),
            "matchup": f"{team} vs. {opp}",
            "season_year": cal_year,
            "game_date": f"{MONTH:02d}/{DAY:02d}/{cal_year}",
        })
    return results


def fetch_games_on_this_day() -> list[dict]:
    all_games = []
    for cal_year in range(FIRST_CAL_YEAR, TODAY.year + 1):
        try:
            html = _fetch_daily_leaders(MONTH, DAY, cal_year)
            rows = _parse_box_scores(html, cal_year)
            all_games.extend(rows)
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
