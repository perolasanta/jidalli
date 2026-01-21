from unittest import runner
from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Annotated
from database import sessionDep, create_db_and_tables
from models import Player, Game, Scoreboard, Tournament, Match, Game_Round
from sqlmodel import Session, select, func
from schemas import PlayerCreate, PlayerRead, GameCreate, GameBase, MatchResult, TournamentCreate
import random
from itertools import batched
from sqlalchemy import update
import math

app = FastAPI()

# Mount static files (CSS, JS, images)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def on_startup():
    create_db_and_tables()

def start_game(teams, present_round):
    if len(teams) % 2 == 0:
        random.shuffle(teams) 
        print (f"Teams before shuffle: {teams}")     
        draws = list(batched(teams,2))
        return {"round" : present_round,
                "matches": draws}
    else:
        return {"error" : "Teams not divisible by 2"}

def matches(fixtures):
    # ✅ Check if there's an error from start_game
    if "error" in fixtures:
        print(f"Error in fixtures: {fixtures['error']}")
        return fixtures  # Return the error, don't try to process
    
    match_list = []
    for k,v in enumerate(fixtures["matches"], 1):
        match_number  = k
        team1, team2 = v
        print (f"Match {match_number} : {team1} vs {team2}")
        match_data = {
            "team1": team1,
            "team2": team2,
            "match_num" : match_number,   
            "round": fixtures["round"]
        }
        match_list.append(match_data)
    print(match_list)
    
    #save_match_results(match_list, session)
    return match_list

# ============ TEMPLATE ROUTES ============

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: sessionDep):
    """Homepage - list all tournaments"""
    tournaments = session.exec(select(Tournament)).all()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "tournaments": tournaments}
    )
    
@app.post("/players/", response_model=PlayerRead)
def create_player(player: PlayerCreate, session: sessionDep):
    db_player = Player.model_validate(player)
    session.add(db_player)
    session.commit()
    session.refresh(db_player)
    return db_player


@app.post("/tournaments/")
def create_tournament(tournament: TournamentCreate, session: sessionDep):
    """Initialize a new tournament - create Game records for all players in round 1"""
    
    # Get all players
    players = session.exec(select(Player)).all()
    
    if not players:
        return {"error": "No players in database"}
    
    # Check that players count is a power of 2
    if (len(players) & (len(players) - 1)) != 0:
        return {"error": "Number of players must be a power of 2"}

    existing = session.exec(select(Tournament).where(Tournament.name == tournament.name)).first()
    if existing:
        return {"error": "Tournament with this name already exists"}
    
    # Create Game records for round 1
    total_rounds = int(math.log2(len(players)))
    
    tournament = Tournament(
        name = tournament.name,
        status = "ongoing",
        number_of_teams = len(players),
        current_round = 1,
        total_rounds = total_rounds
    )
    session.add(tournament)
    session.flush()  # Ensure tournament_id is generated
         
    fixtures = start_game([player.player_id for player in players], 1)     
    match_list = matches(fixtures)
    for match in match_list:
        new_match = Match(
            tournament_id = tournament.tournament_id,
            round_num = match["round"],
            team1_id = str(match["team1"]),
            team2_id = str(match["team2"]),
            team1_score = 0,
            team2_score = 0,
            winner_id = None,
            loser_id = None,
            status = "pending"
        )
        session.add(new_match)

    round_record = Game_Round(
        tournament_id = tournament.tournament_id,
        round_num = 1,
        matches_in_round = len(match_list),
        status = "ongoing"
    )
    session.add(round_record)
    
    session.commit()
    return { "tournament": tournament,
             "matches": match_list,
             "round_record": round_record
             }

@app.get("/tournaments/{tournament_id}/matches/")
def get_tournament_matches(tournament_id: int, session: sessionDep):
    """Retrieve all matches for a given tournament"""
    matches = session.exec(
        select(Match).where(Match.tournament_id == tournament_id)
    ).all()
    completed = [m for m in matches if m.status == "completed"]
    pending = [m for m in matches if m.status == "pending"]
    return {"matches": completed, "pending": len(pending)}

@app.get("/tournaments/{tournament_id}/current-matches/")
def get_current_matches(tournament_id: int, session: sessionDep):
    """Retrieve all current matches for a given tournament"""
    matches = session.exec(
        select(Match).where(Match.tournament_id == tournament_id)
    ).all()
    pending = [m for m in matches if m.status == "pending"]
    return {"pending matches": pending}

def verify_match_belongs_to_tournament(id: int, 
                                       tournament_id: int, 
                                       session: sessionDep) -> Match:
    """Dependency: Verify match exists, is pending, and belongs to tournament"""
    match = session.get(Match, id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    # check if match is in the tournament
    if match.tournament_id != tournament_id:
        raise HTTPException(status_code=400, detail="Match does not belong to this tournament")
    
    #check if match already completed
    if match.status == "completed":
        raise HTTPException(status_code=400, detail="Match already completed")
    #get active tournament
    active_tournament = session.exec(
        select(Tournament).where(Tournament.status == 'ongoing')
        .where(Tournament.tournament_id == tournament_id) # for running multiple tournaments
    ).first()
    if not active_tournament:
        raise HTTPException(status_code=400, detail="No active tournament found")
    
    # check current round
    if match.round_num != active_tournament.current_round:
        raise HTTPException(status_code=400, 
                detail= f"Can only update matches in round {active_tournament.current_round}")
    return match


@app.post("/tournaments/{tournament_id}/matches/{id}/score/")
def update_match_score(team1_score: int, 
                       team2_score: int, 
                       session: sessionDep,
                       match: Annotated[Match, Depends(verify_match_belongs_to_tournament)]
                       ):
    """Update the score of a match and determine winner/loser"""
    
    # update scores
    match.team1_score = team1_score
    match.team2_score = team2_score
    
    if team1_score > team2_score:
        match.winner_id = int(match.team1_id)
        match.loser_id = int(match.team2_id)
    elif team2_score > team1_score:
        match.winner_id = int(match.team2_id)
        match.loser_id = int(match.team1_id)
    else:
        raise HTTPException(status_code=400, detail="Match cannot end in a tie")
    
    match.status = "completed"
    session.add(match)
    session.commit()
    session.refresh(match)
    
    # check if round is complete and advance tournament if needed
    check_round = check_round_completion(match.tournament_id, match.round_num, session)
    if check_round:
        tournament = session.get(Tournament, match.tournament_id)
        if tournament:
            # capturing this to result makes me get the return value from advance_tournament_round
            result = advance_tournament_round(tournament, session)
            
        return result
    
    

    return {"match": match}

def check_round_completion(tournament_id: int, 
                           current_round: int, 
                           session: sessionDep) -> bool:
    """Check if all matches in the current round are completed"""
    pending_matches = session.exec(
        select(Match).where(
            (Match.tournament_id == tournament_id) &
            (Match.round_num == current_round) &
         
            (Match.status == "pending")
        )
    ).all()
    return len(pending_matches) == 0

def advance_tournament_round(tournament: Tournament, session: sessionDep):
    """Advance the tournament to the next round if current round is complete"""
    print(f" Type : {type(tournament.tournament_id)} value: {tournament.tournament_id}")
    if check_round_completion(tournament.tournament_id, tournament.current_round, session):
        if tournament.current_round < tournament.total_rounds:
            # Advance to next round
            #
            this_round = session.exec(
                select(Game_Round).where(
                    (Game_Round.tournament_id == tournament.tournament_id) &
                    (Game_Round.round_num == tournament.current_round)
                )
            ).first()
            if this_round:
                this_round.status = "completed"
                session.add(this_round)
            tournament.current_round += 1
            session.add(tournament)
            session.commit()
            session.refresh(tournament)
            
            # Create new matches for next round
            winners = session.exec(
                select(Match.winner_id).where(
                    (Match.tournament_id == tournament.tournament_id) &
                    (Match.round_num == tournament.current_round - 1)
                )
            ).all()
            winner_ids = [w for w in winners]
            
            fixtures = start_game(winner_ids, tournament.current_round)
            match_list = matches(fixtures)
            for match in match_list:
                new_match = Match(
                    tournament_id = tournament.tournament_id,
                    round_num = match["round"],
                    team1_id = str(match["team1"]),
                    team2_id = str(match["team2"]),
                    team1_score = 0,
                    team2_score = 0,
                    winner_id = None,
                    loser_id = None,
                    status = "pending"
                )
                session.add(new_match)

            round_record = Game_Round(
                tournament_id = tournament.tournament_id,
                round_num = tournament.current_round,
                matches_in_round = len(match_list),
                status = "ongoing"
            )
            session.add(round_record)
            
            session.commit()
            return {"message": f"Advanced to round {tournament.current_round}", "matches": match_list}
         #  check it is the final round 
        elif tournament.current_round == tournament.total_rounds:
            # Tournament completed
            return complete_tournament(tournament, session)
    
        
        
    else:
        return {"message": "Current round not yet complete"}
    
def complete_tournament(tournament: Tournament, session: sessionDep):
    """Mark the tournament as completed"""
    final_match = session.exec(
        select(Match).where(
            (Match.tournament_id == tournament.tournament_id) &
            (Match.round_num == tournament.total_rounds) &
            (Match.status == "completed")
        )
    ).first()
    
    if not final_match:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if not final_match.winner_id:
        raise HTTPException(status_code=400, detail="Final match has no winner")
    
    # Update tournament status with winner
    tournament.winner_id = final_match.winner_id
    tournament.status = "completed"
    session.add(tournament)
    
    

    # update final round match status
    final_round = session.exec(
        select(Game_Round).where(
            (Game_Round.tournament_id == tournament.tournament_id) &
            (Game_Round.round_num == tournament.total_rounds)
        )
    ).first()
    if final_round:
        final_round.status = "completed"
        session.add(final_round)
    session.commit()
    session.refresh(tournament)

    # Get winner details
    winner = session.get(Player, final_match.winner_id)
    runner_up = session.get(Player, final_match.loser_id)
    
    # Return tournament results
    return {
        "message": "Tournament completed",
        "tournament id": tournament.tournament_id,
        "winner_id": tournament.winner_id,
        "winner_name": winner.name,
        "runner_up_id": final_match.loser_id,
        "runner_up_name": runner_up.name if runner_up else None, 
        "final_score": {"team1_score": final_match.team1_score,
                        "team2_score": final_match.team2_score}
    }


# ============ TEMPLATE ROUTES ============

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: sessionDep):
    """Homepage - list all tournaments"""
    tournaments = session.exec(select(Tournament)).all()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "tournaments": tournaments}
    )

@app.get("/players/", response_class=HTMLResponse)
async def list_players(request: Request, session: sessionDep):
    """List all players"""
    players = session.exec(select(Player)).all()
    return templates.TemplateResponse(
        "players.html",
        {"request": request, "players": players}
    )

@app.get("/players/create", response_class=HTMLResponse)
async def create_player_form(request: Request):
    """Show create player form"""
    return templates.TemplateResponse(
        "create_player.html", 
        {"request": request}
    )

@app.post("/players/create", response_class=HTMLResponse)
async def create_player_from_form(
    request: Request,
    name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    session: sessionDep
):
    """Handle player creation from HTML form"""
    player_data = PlayerCreate(name=name, email=email)
    db_player = create_player(player_data, session)
    
    return RedirectResponse(
        url="/players/",
        status_code=303
    )

@app.get("/tournaments/create", response_class=HTMLResponse)
async def create_tournament_form(request: Request):
    """Show create tournament form"""
    return templates.TemplateResponse(
        "create_tournament.html", 
        {"request": request}
    )


@app.post("/tournaments/create", response_class=HTMLResponse)
async def create_tournament_from_form(
    request: Request,
    name: Annotated[str, Form()],
    session: sessionDep
):
    """Handle tournament creation from HTML form"""
    tournament_data = TournamentCreate(name=name)
    result = create_tournament(tournament_data, session)
    
    if "error" in result:
        return templates.TemplateResponse(
            "create_tournament.html",
            {"request": request, "error": result["error"]}
        )
    
    return RedirectResponse(
        url=f"/tournaments/{result['tournament'].tournament_id}",
        status_code=303
    )


@app.get("/tournaments/{tournament_id}", response_class=HTMLResponse)
async def tournament_bracket_view(
    request: Request, 
    tournament_id: int, 
    session: sessionDep
):
    """Tournament bracket view with all matches"""
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
    
    # Get all players
    player_ids = set()
    for match in matches:
        if match.team1_id:
            player_ids.add(int(match.team1_id))
        if match.team2_id:
            player_ids.add(int(match.team2_id))
    
    players_list = session.exec(
        select(Player).where(Player.player_id.in_(player_ids))
    ).all()
    
    players = {str(p.player_id): p for p in players_list}
    
    return templates.TemplateResponse(
        "tournament_bracket.html",
        {
            "request": request,
            "tournament": tournament,
            "matches_by_round": matches_by_round,
            "players": players
        }
    )


@app.get("/tournaments/{tournament_id}/standings", response_class=HTMLResponse)
async def tournament_standings_view(
    request: Request, 
    tournament_id: int, 
    session: sessionDep
):
    """Tournament standings page"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    result = get_tournament_standings(tournament_id, session)
    
    return templates.TemplateResponse(
        "standings.html",
        {
            "request": request,
            "tournament": tournament,
            "standings": result.get("standings", [])
        }
    )


@app.get("/tournaments/{tournament_id}/matches/{id}/score", response_class=HTMLResponse)
async def match_score_form(
    request: Request,
    tournament_id: int,
    id: int,
    session: sessionDep
):
    """Show form to enter match score"""
    match = verify_match_belongs_to_tournament(id, tournament_id, session)
    
    tournament = session.get(Tournament, match.tournament_id)
    team1 = session.get(Player, int(match.team1_id)) if match.team1_id else None
    team2 = session.get(Player, int(match.team2_id)) if match.team2_id else None
    
    return templates.TemplateResponse(
        "complete_match.html",
        {
            "request": request,
            "match": match,
            "tournament": tournament,
            "team1": team1,
            "team2": team2
        }
    )


@app.post("/tournaments/{tournament_id}/matches/{id}/score/", response_class=HTMLResponse)
async def submit_match_score_from_form(
    request: Request,
    tournament_id: int,
    id: int,
    team1_score: Annotated[int, Form()],
    team2_score: Annotated[int, Form()],
    winner: Annotated[str, Form()],
    session: sessionDep
):
    """Handle match score submission from HTML form"""
    match = verify_match_belongs_to_tournament(id, tournament_id, session)
    
    # Update the match using existing function
    result = update_match_score(team1_score, team2_score, session, match)
    
    # Check if tournament completed
    if result and "Tournament completed" in result.get("message", ""):
        return RedirectResponse(
            url=f"/tournaments/{tournament_id}/winner",
            status_code=303
        )
    
    return RedirectResponse(
        url=f"/tournaments/{tournament_id}",
        status_code=303
    )


@app.get("/tournaments/{tournament_id}/winner", response_class=HTMLResponse)
async def tournament_winner_view(
    request: Request,
    tournament_id: int,
    session: sessionDep
):
    """Tournament winner celebration page"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    if tournament.status != "completed":
        return RedirectResponse(
            url=f"/tournaments/{tournament_id}",
            status_code=303
        )
    
    winner = session.get(Player, tournament.winner_id) if tournament.winner_id else None
    
    # Get final match
    final_match = session.exec(
        select(Match).where(
            (Match.tournament_id == tournament_id) &
            (Match.round_num == tournament.total_rounds)
        )
    ).first()
    
    runner_up = session.get(Player, final_match.loser_id) if (final_match and final_match.loser_id) else None
    
    # Get tournament stats
    all_matches = session.exec(
        select(Match).where(
            (Match.tournament_id == tournament_id) &
            (Match.status == "completed")
        )
    ).all()
    
    total_matches = len(all_matches)
    total_points = sum(m.team1_score + m.team2_score for m in all_matches)
    
    return templates.TemplateResponse(
        "winner.html",
        {
            "request": request,
            "tournament": tournament,
            "winner": winner,
            "runner_up": runner_up,
            "final_match": final_match,
            "total_matches": total_matches,
            "total_points": total_points
        }
    )


def get_tournament_standings(tournament_id: int, session: sessionDep):
    """Get complete standings for a tournament"""
    tournament = session.exec(
        select(Tournament).where(Tournament.tournament_id == tournament_id)
    ).first()
    
    if not tournament:
        return {"error": "Tournament not found"}
    
    # Get all completed matches
    matches = session.exec(
        select(Match).where(
            (Match.tournament_id == tournament_id) &
            (Match.status == "completed")
        ).order_by(Match.round_num.desc())
    ).all()
    
    # Track team performance
    team_stats = {}
    
    for match in matches:
        # Winner stats
        if match.winner_id:
            winner_str = str(match.winner_id)
            if winner_str not in team_stats:
                team_stats[winner_str] = {
                    "wins": 0,
                    "losses": 0,
                    "rounds_reached": match.round_num
                }
            team_stats[winner_str]["wins"] += 1
            team_stats[winner_str]["rounds_reached"] = max(
                team_stats[winner_str]["rounds_reached"], 
                match.round_num
            )
        
        # Loser stats
        if match.loser_id:
            loser_str = str(match.loser_id)
            if loser_str not in team_stats:
                team_stats[loser_str] = {
                    "wins": 0,
                    "losses": 0,
                    "rounds_reached": match.round_num
                }
            team_stats[loser_str]["losses"] += 1
    
    # Sort by performance (rounds reached, then wins)
    sorted_teams = sorted(
        team_stats.items(),
        key=lambda x: (x[1]["rounds_reached"], x[1]["wins"]),
        reverse=True
    )
    
    standings = []
    for rank, (team_id, stats) in enumerate(sorted_teams, 1):
        try:
            player = session.get(Player, int(team_id))
            team_name = player.name if player else f"Player {team_id}"
        except:
            team_name = f"Player {team_id}"
            
        standings.append({
            "rank": rank,
            "team_id": team_id,
            "team_name": team_name,
            "wins": stats["wins"],
            "losses": stats["losses"],
            "rounds_reached": stats["rounds_reached"],
            "is_champion": str(team_id) == str(tournament.winner_id) if tournament.winner_id else False
        })
    
    return {
        "tournament_id": tournament_id,
        "status": tournament.status,
        "current_round": tournament.current_round,
        "total_rounds": tournament.total_rounds,
        "standings": standings
    }
