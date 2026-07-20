import os
import tempfile
import threading

import requests
from flask import Response
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import (
    Flask,
    after_this_request,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from file import save_to_csv
from scrapper import (
    TEAM_SUGGESTIONS,
    collect_all_games,
    normalize_text,
    request_get,
    resolve_team_name,
    search_games,
    search_news,
    search_player_photo,
    search_team_logo,
    search_team_squad,
)


app = Flask(__name__)

# Render의 한 프로세스 안에서 재사용하는 임시 캐시입니다.
db = {
    "all_games": [],
    "status": {},
    "news_cache": {},
    "squad_cache": {},
    "logo_cache": {},
    "photo_cache": {},
    "result_cache": {},
}

schedule_lock = threading.Lock()


def squad_can_cache(squad):
    """정상 선수단 또는 리그 검색 결과만 캐시에 저장합니다."""

    if squad.get("players"):
        return True

    message = squad.get("message", "")
    return "리그명 검색" in message


@app.route("/")
def home():
    return render_template(
        "index.html",
        team_suggestions=TEAM_SUGGESTIONS,
    )


@app.route("/search")
def search():
    keyword = request.args.get("keyword", "").strip()

    if keyword == "":
        return redirect("/")

    # 여러 사용자가 동시에 첫 검색을 하더라도 일정 수집은 한 번만 실행합니다.
    if len(db["all_games"]) == 0:
        with schedule_lock:
            if len(db["all_games"]) == 0:
                try:
                    all_games, status = collect_all_games()
                    db["all_games"] = all_games
                    db["status"] = status
                except Exception as error:
                    print("경기 일정 전체 수집 실패:", error)
                    db["all_games"] = []
                    db["status"] = {}

    games = search_games(db["all_games"], keyword)
    cache_key = normalize_text(keyword)

    news = db["news_cache"].get(cache_key)
    squad = db["squad_cache"].get(cache_key)
    jobs = {}

    # 뉴스와 선수단은 서로 다른 사이트이므로 동시에 수집합니다.
    with ThreadPoolExecutor(max_workers=2) as executor:
        if news is None:
            jobs["news"] = executor.submit(search_news, keyword)

        if squad is None:
            jobs["squad"] = executor.submit(search_team_squad, keyword)

        if "news" in jobs:
            try:
                news = jobs["news"].result()
                # Render에서 일시적으로 실패한 빈 결과는 저장하지 않습니다.
                if news:
                    db["news_cache"][cache_key] = news
            except Exception as error:
                print("뉴스 수집 작업 실패:", error)
                news = []

        if "squad" in jobs:
            try:
                squad = jobs["squad"].result()
                if squad_can_cache(squad):
                    db["squad_cache"][cache_key] = squad
            except Exception as error:
                print("선수단 수집 작업 실패:", error)
                squad = {
                    "team_name": "",
                    "players": [],
                    "source_url": "",
                    "logo_url": "",
                    "message": "선수단 정보를 가져오지 못했습니다.",
                }

    news = news or []
    squad = squad or {
        "team_name": "",
        "players": [],
        "source_url": "",
        "logo_url": "",
        "message": "선수단 정보가 없습니다.",
    }

    # 다운로드는 현재 사용자의 검색어를 기준으로 찾도록 검색 결과별로 저장합니다.
    db["result_cache"][cache_key] = {
        "keyword": keyword,
        "games": games,
        "news": news,
        "squad": squad,
    }

    return render_template(
        "result.html",
        keyword=keyword,
        games=games,
        news=news,
        squad=squad,
        total_count=len(db["all_games"]),
        status=db["status"],
        team_suggestions=TEAM_SUGGESTIONS,
    )


@app.route("/team-logo")
def team_logo():
    """경기 결과 화면을 먼저 띄운 뒤 팀 로고를 별도로 불러옵니다."""

    team_name = request.args.get("name", "").strip()
    if team_name == "":
        return "", 404

    logo_key = resolve_team_name(team_name)
    logo_url = db["logo_cache"].get(logo_key)

    if logo_url is None:
        try:
            logo_url = search_team_logo(team_name)
        except Exception as error:
            print(team_name, "팀 로고 수집 실패:", error)
            logo_url = ""

        # 실패 결과는 저장하지 않아 다음 요청에서 다시 시도합니다.
        if logo_url:
            db["logo_cache"][logo_key] = logo_url

    if not logo_url:
        return "", 404

    response = redirect(logo_url)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.route("/player-photo")
def player_photo():
    """선수 사진 주소를 찾은 뒤 외부 이미지 주소로 바로 이동합니다."""

    player_name = request.args.get("name", "").strip()
    team_name = request.args.get("team", "").strip()
    wiki_title = request.args.get("title", "").strip()
    alternate = request.args.get("alternate", "0") == "1"

    if player_name == "":
        return "", 404

    photo_key = "|".join([
        normalize_text(player_name),
        normalize_text(team_name),
        normalize_text(wiki_title),
        str(alternate),
    ])

    image_url = db["photo_cache"].get(photo_key)

    if image_url is None:
        try:
            image_url = search_player_photo(
                player_name,
                team_name,
                wiki_title,
                skip_primary=alternate,
            )

        except Exception as error:
            print(player_name, "선수 사진 검색 실패:", error)
            image_url = ""

        if image_url:
            db["photo_cache"][photo_key] = image_url

    if not image_url:
        return "", 404

    # Flask가 이미지를 다운로드하지 않고 이미지 주소로 바로 이동
    response = redirect(image_url)

    # 같은 사진은 브라우저에서 하루 동안 재사용
    response.headers["Cache-Control"] = "public, max-age=86400"

    return response

@app.route("/download")
def download():
    keyword = request.args.get("keyword", "").strip()
    cache_key = normalize_text(keyword)
    result = db["result_cache"].get(cache_key)

    if result is None:
        return redirect("/" if keyword == "" else url_for("search", keyword=keyword))

    temp = tempfile.NamedTemporaryFile(
        prefix="football_results_",
        suffix=".csv",
        delete=False,
    )
    temp.close()
    csv_path = Path(temp.name)

    save_to_csv(
        result["games"],
        result["news"],
        result["squad"],
        csv_path,
    )

    @after_this_request
    def remove_temp_file(response):
        try:
            csv_path.unlink(missing_ok=True)
        except OSError:
            pass
        return response

    return send_file(
        csv_path,
        as_attachment=True,
        download_name="football_results.csv",
        mimetype="text/csv",
    )


@app.route("/refresh")
def refresh():
    for key in db:
        if isinstance(db[key], dict):
            db[key].clear()
        elif isinstance(db[key], list):
            db[key].clear()
    return redirect("/")


@app.route("/health")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
