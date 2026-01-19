from typing import Optional
from fastapi import FastAPI, Depends
from database import sessionDep, create_db_and_tables
from models import Player, Game, Scoreboard
from sqlmodel import Session, select, func
from schemas import PlayerCreate, PlayerRead, GameCreate, GameBase, MatchResult
import random
from itertools import batched
from sqlalchemy import update


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

def gamplay_logic(rand1, rand2):
    # Placeholder for actual gameplay logic
    # For now, just return random scores
    #score1 = random.randint(0, 5)
    #score2 = random.randint(0, 5)
    return {"score1": rand1, "score2": rand2}

def matches(fixtures, session):
    # ✅ Check if there's an error from start_game
    if "error" in fixtures:
        print(f"Error in fixtures: {fixtures['error']}")
        return fixtures  # Return the error, don't try to process
    
    match_list = []
    for k,v in enumerate(fixtures["matches"], 1):
        match_number  = k
        team1, team2 = v
        print (f"Match {match_number} : {team1} vs {team2}")
        # logic for game play
        get_score = gamplay_logic(rand1, rand2)
        #generate random scores
        #rand1 = random.randint(0,6)
        #rand2 = random.randint(0,6)

        #handle ties
        #while rand1 == rand2:
         #   rand1 = random.randint(0,6)
        #rand2 = random.randint(0,6)

        match_data = {
            "match_num" : match_number,
            "team_names": [team1,team2],
            "score": [get_score["score1"], get_score["score2"]],
            "round": fixtures["round"]
        }
        match_list.append(match_data)
    print(match_list)
    save_match_results(match_list, session)
    return match_list
    
def save_match_results (match_list: list, session: sessionDep):
    """Process match results and update database
    match reuslt format: [{'match_num': 1, 'team_names': ['Peter', 'Saddam'], 
                           'score': [4, 3], 'round': 4}, ...]
                           """
    for match in match_list:
        match_num = match['match_num']
        team_names = match['team_names']
        scores = match['score']
        round_num = match['round']

        # Determine winner and loser
        if scores[0] > scores[1]:
            winner_name = team_names[0]
            loser_name = team_names[1]
        else:
            winner_name = team_names[1]
            loser_name = team_names[0]
        
        # get winner and loser ids
        winner = session.exec(select(Player).where(Player.name == winner_name)).first()
        loser = session.exec(select(Player).where(Player.name == loser_name)).first()

        if loser:
            #update eliminated players
            losersql = (
                update(Game).where(Game.player_id == loser.player_id)
                .where(Game.round == round_num)
                .values(eliminated =True)
            )
        # this ni=ot needed again since its in game_PLAY
        #if winner:
            # update winners to next round
         ##      update(Game).where(Game.player_id == winner.player_id)
           #     .where(Game.round == round_num)
            #    .values(round = round_num+1)
            #)
        
        session.exec(losersql)
        #session.exec(winnersql)

        score_record = Scoreboard(
            match_num = match_num,
            round_num=round_num,
            team1_id= winner.player_id,
            team2_id= loser.player_id,
            team1_score=max(scores),
            team2_score= min(scores),
            winner_id= winner.player_id,
            loser_id=loser.player_id
        )
        session.add(score_record)
    session.commit()
    return {"succes": True, "matches processes" : len(match_list)}

@app.get("/gamescores/")
def game_scores(rand1: int, rand2: int):
    return gamplay_logic(rand1, rand2)
    
    
        
@app.post("/tournament/start")
def start_tournament(session: sessionDep):
    """Initialize a new tournament - create Game records for all players in round 1"""
    
    # Get all players
    players = session.exec(select(Player)).all()
    
    if not players:
        return {"error": "No players in database"}
    
    # Check if tournament already started
    existing = session.exec(select(Game).where(Game.round == 1)).first()
    if existing:
        return {"error": "Tournament already started"}
    
    # Create Game records for round 1
    for player in players:
        game_record = Game(
            player_id=player.player_id,
            round=1,
            eliminated=False
        )
        session.add(game_record)
    
    session.commit()
    
    return {
        "message": "Tournament initialized",
        "players": len(players),
        "round": 1
    }

@app.post("/game_play/")
def game_play (session : sessionDep, round_num: int | None = None):
    """
    Play a round of the game
    If round_num is None, start a new tournament at round 1
    Otherwise, play the specified round
    """
    # check if its a new tournament
    if round_num is not None:
        present_round = round_num
    else:
        stmt  = select(func.max(Game.round))
        present_round =  session.exec(stmt).one()
    statement = select (Player.name).join(Game, Player.player_id ==
                                          Game.player_id).where(
                                              Game.round == present_round 
                                          ).where(
                                              Game.eliminated == False
                                          )
    teams = session.exec(statement).all()

    if not teams:
        return {"error": f"No active teams in round {present_round}"}

    print(f"Active teams in round {present_round}:", teams)

    fixtures = start_game(teams, present_round)
     #Debug: Print what fixtures contains
    print("Fixtures:", fixtures)
    print("Type:", type(fixtures))
    if "error" in fixtures:
        return fixtures
    # also pass session so that it can be passed to save_result()
    display = matches(fixtures, session) 

    # Advance winners to next round
    winners = [
        match['team_names'][0] if match['score'][0] > match['score'][1] 
        else match['team_names'][1]
        for match in display
    ]

    # Create Game records for next round
    for winner_name in winners:
        player = session.exec(
            select(Player).where(Player.name == winner_name)
        ).first()
        
        game_record = Game(
            player_id=player.player_id,
            round=present_round + 1,
            eliminated=False
        )
        session.add(game_record)
    
    session.commit()
    
    return {
        "round": present_round,
        "matches_played": len(display),
        "results": display,
        "winners_advancing": len(winners)
    }

def display_match_results(match_results: list):
    """Format and display match results"""
    print(f"\n{'='*50}")
    print(f"Round {match_results[0]['round']} Results")
    print(f"{'='*50}\n")
    
    for match in match_results:
        print (match['team_names'])
        team1, team2 = match['team_names']
        score1, score2 = match['score']
        winner = team1 if score1 > score2 else team2
        
        print(f"Match {match['match_num']}:")
        print(f"  {team1} {score1} - {score2} {team2}")
        print(f"  Winner: {winner} ✓")
        print()   
    
@app.post("/round/{round}/complete")
def complete_round(round: int, results: list[MatchResult], session: sessionDep):
    """Complete a round by processing all match results"""
    
    # Convert to dict format
    match_data = [result.model_dump() for result in results]
    
    # Display results (optional, or return to frontend)
    display_match_results(match_data)
    
    # Save to database and eliminate losers
    response = save_match_results(match_data, session)
    
    # Check if tournament is complete
    remaining = session.exec(
        select(func.count(Player.player_id))
        .join(Game, Player.player_id == Game.player_id)
        .where(Game.round == round)
        .where(Game.eliminated == False)
    ).one()
    
    if remaining == 1:
        # Tournament complete!
        winner = session.exec(
            select(Player.name)
            .join(Game, Player.player_id == Game.player_id)
            .where(Game.round == round)
            .where(Game.eliminated == False)
        ).first()
        return {
            "tournament_complete": True,
            "winner": winner,
            **response
        }
    
    return {
        "tournament_complete": False,
        "remaining_players": remaining,
        **response
    }


@app.post("/players/", response_model=PlayerRead)
def create_player(player: PlayerCreate, session: sessionDep):
    db_player = Player.model_validate(player)
    session.add(db_player)
    session.commit()
    session.refresh(db_player)
    return db_player

@app.get("/round/{round}")
def read_round(round: int, session: sessionDep):
    if round != 1:
        stmt  = select(func.max(Game.round))
        present_round =  session.exec(stmt).one()
    #present_round = round    

    statement = select (Player.name).join(Game, Player.player_id ==
                                          Game.player_id).where(
                                              Game.round == present_round 
                                          ).where(
                                              Game.eliminated == False
                                          )
    teams = session.exec(statement).all()
    if len(teams) % 2 == 0:
        random.shuffle(teams)      
        draws = list(batched(teams,2))
        return {"round" : present_round,
                "matches": draws}
    else:
        return {"error" : "Teams not divisible by 2"}
    

#@app.get("/players/", response_model=list[PlayerRead])
#def read_players(session: sessionDep):
  #  return session.exec(select(Player)).)

#@app.post ("/games")
#def add_testgame()