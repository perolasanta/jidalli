from unittest import runner
from fastapi import FastAPI, Depends, HTTPException
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