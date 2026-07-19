import csv
from pathlib import Path


def save_to_csv(games, news, squad, csv_path):
    """현재 검색한 일정, 뉴스, 스쿼드를 하나의 CSV 파일에 저장합니다."""

    csv_path = Path(csv_path)

    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "구분", "리그", "시즌", "날짜", "시간", "홈팀", "원정팀",
            "팀", "등번호", "포지션", "국적", "선수명", "선수 사진",
            "뉴스 제목", "언론사", "게시일", "링크",
        ])

        for game in games:
            writer.writerow([
                "경기 일정",
                game.get("league", ""),
                game.get("season", ""),
                game.get("date", ""),
                game.get("time", ""),
                game.get("home_team", ""),
                game.get("away_team", ""),
                "", "", "", "", "", "", "", "", "",
                game.get("source_url", ""),
            ])

        for article in news:
            writer.writerow([
                "관련 뉴스",
                "", "", "", "", "", "", "", "", "", "", "", "",
                article.get("title", ""),
                article.get("source", ""),
                article.get("published", ""),
                article.get("link", ""),
            ])

        for player in squad.get("players", []):
            writer.writerow([
                "팀 스쿼드",
                "", "", "", "", "", "",
                squad.get("team_name", ""),
                player.get("number", ""),
                player.get("position", ""),
                player.get("nationality", ""),
                player.get("name", ""),
                player.get("image_url", ""),
                "", "", "",
                player.get("profile_url") or squad.get("source_url", ""),
            ])

    return csv_path
