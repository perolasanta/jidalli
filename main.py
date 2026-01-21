# main.py
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from typing import Annotated
from database import sessionDep, create_db_and_tables
from models import Player, Game, Scoreboard, Tournament, Match, Game_Round
from schemas import TournamentCreate
from game import check_round_completion, advance_tournament_round, complete_tournament

app = FastAPI()

# Mount static files (CSS, JS, images)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Dependency
#sessionDep = Annotated[Session, Depends(get_session)]

# ============ TEMPLATE ROUTES ============

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: sessionDep):
    """Homepage - list all tournaments"""
    tournaments = session.exec(select(Tournament)).all()
    return templates.TemplateResponse(
        "index1.html",
        {"request": request, "tournaments": tournaments}
    )


@app.get("/tournaments/{tournament_id}", response_class=HTMLResponse)
async def tournament_detail(request: Request, tournament_id: int, session: sessionDep):
    """Tournament detail page"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    # Get all matches for this tournament
    matches = session.exec(
        select(Match).where(Match.tournament_id == tournament_id)
        .order_by(Match.round_num)
    ).all()
    
    # Group matches by round
    matches_by_round = {}
    for match in matches:
        if match.round_num not in matches_by_round:
            matches_by_round[match.round_num] = []
        matches_by_round[match.round_num].append(match)
    
    return templates.TemplateResponse(
        "tournament1.html",
        {
            "request": request,
            "tournament": tournament,
            "matches_by_round": matches_by_round
        }
    )


@app.get("/tournaments/create", response_class=HTMLResponse)
async def create_tournament_form(request: Request):
    """Show create tournament form"""
    return templates.TemplateResponse("create_tournament1.html", {"request": request})


@app.post("/tournaments/create")
async def create_tournament(
    request: Request,
    name: Annotated[str, Form()],
    total_rounds: Annotated[int, Form()],
    session: sessionDep
):
    """Handle tournament creation from form"""
    tournament = Tournament(
        name=name,
        total_rounds=total_rounds,
        current_round=1,
        status="ongoing"
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    
    return RedirectResponse(
        url=f"/tournaments/{tournament.tournament_id}",
        status_code=303
    )


@app.get("/matches/{match_id}", response_class=HTMLResponse)
async def match_detail(request: Request, match_id: int, session: sessionDep):
    """Match detail page"""
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    tournament = session.get(Tournament, match.tournament_id)
    team1 = session.get(Player, match.team1_id)
    team2 = session.get(Player, match.team2_id)
    
    return templates.TemplateResponse(
        "match1.html",
        {
            "request": request,
            "match": match,
            "tournament": tournament,
            "team1": team1,
            "team2": team2
        }
    )


@app.post("/matches/{match_id}/complete")
async def complete_match_form(
    request: Request,
    match_id: int,
    winner_id: Annotated[str, Form()],
    team1_score: Annotated[int, Form()],
    team2_score: Annotated[int, Form()],
    session: sessionDep
):
    """Handle match completion from form"""
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    if match.status == "completed":
        raise HTTPException(status_code=400, detail="Match already completed")
    
    # Update match
    match.team1_score = team1_score
    match.team2_score = team2_score
    match.winner_id = winner_id
    match.loser_id = match.team2_id if winner_id == match.team1_id else match.team1_id
    match.status = "completed"
    
    session.add(match)
    session.commit()
    session.refresh(match)
    
    # Check if round is complete
    check_round = check_round_completion(match.tournament_id, match.round_num, session)
    if check_round:
        tournament = session.get(Tournament, match.tournament_id)
        if tournament:
            result = advance_tournament_round(tournament, session)
            
            # If tournament completed, redirect to winner page
            if "Tournament completed" in result.get("message", ""):
                return RedirectResponse(
                    url=f"/tournaments/{match.tournament_id}/winner",
                    status_code=303
                )
    
    return RedirectResponse(
        url=f"/tournaments/{match.tournament_id}",
        status_code=303
    )


@app.get("/tournaments/{tournament_id}/winner", response_class=HTMLResponse)
async def tournament_winner(request: Request, tournament_id: int, session: sessionDep):
    """Tournament winner page"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    if tournament.status != "completed":
        raise HTTPException(status_code=400, detail="Tournament not completed yet")
    
    winner = session.get(Player, tournament.winner_id)
    
    # Get final match
    final_match = session.exec(
        select(Match).where(
            (Match.tournament_id == tournament_id) &
            (Match.round_num == tournament.total_rounds)
        )
    ).first()
    
    runner_up = session.get(Player, final_match.loser_id) if final_match else None
    
    return templates.TemplateResponse(
        "winner1.html",
        {
            "request": request,
            "tournament": tournament,
            "winner": winner,
            "runner_up": runner_up,
            "final_match": final_match
        }
    )


# ============ API ROUTES (Optional - for AJAX) ============

@app.get("/api/tournaments/{tournament_id}")
async def api_get_tournament(tournament_id: int, session: sessionDep):
    """API endpoint for AJAX calls"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return tournament