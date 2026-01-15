from typing import Optional
from fastapi import FastAPI, Depends
from database import sessionDep, create_db_and_tables
from models import Player, Game
from sqlmodel import Session, select, func
from schemas import PlayerCreate, PlayerRead, GameCreate, GameBase
import random
from itertools import batched
from sqlalchemy import update


app = FastAPI()
@app.on_event("startup")
def on_startup():
    create_db_and_tables()


def start_game(teams, present_round):
    if len(teams) % 4 == 0:
        random.shuffle(teams) 
        print (f"Teams before shuffle: {teams}")     
        draws = list(batched(teams,2))
        return {"round" : present_round,
                "matches": draws}
    else:
        return {"error" : "Teams not divisible by 4"}



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
        rand1 = random.randint(0,6)
        rand2 = random.randint(0,6)

        #handle ties
        while rand1 == rand2:
            rand1 = random.randint(0,6)
        rand2 = random.randint(0,6)

        match_data = {
            "match_num" : match_number,
            "team_names": [team1,team2],
            "score": [rand1, rand2],
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
        
        if winner:
            # update winners to next round
            winnersql = (
                update(Game).where(Game.player_id == winner.player_id)
                .where(Game.round == round_num)
                .values(round = round_num+1)
            )

        session.exec(losersql)
        session.exec(winnersql)
    session.commit()



        


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
    fixtures = start_game(teams, present_round)
     #Debug: Print what fixtures contains
    print("Fixtures:", fixtures)
    print("Type:", type(fixtures))
    # also pass session so that it can be passed to save_result()
    display = matches(fixtures, session) 
    return {"result" : display}
    



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
    if len(teams) % 4 == 0:
        random.shuffle(teams)      
        draws = list(batched(teams,2))
        return {"round" : present_round,
                "matches": draws}
    else:
        return {"error" : "Teams not divisible by 4"}
    

#@app.get("/players/", response_model=list[PlayerRead])
#def read_players(session: sessionDep):
  #  return session.exec(select(Player)).)

#@app.post ("/games")
#def add_testgame()