from sqlmodel import Column, Integer, String, ForeignKey
from sqlmodel import SQLModel, Relationship, Field


class Player(SQLModel, table=True):
    player_id: int = Field(default=None, primary_key=True)
    name: str
    email: str



    games: list["Game"] = Relationship(back_populates="player")

class Game(SQLModel, table=True):
    game_id: int = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.player_id")
    round: int
    eliminated: bool

    player: Player = Relationship(back_populates="games")

class Scoreboard (SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    match_num: int
    round_num: int
    team1_id: str
    team2_id : str
    team1_score : int
    team2_score : int
    winner_id: int
    loser_id : int

class Tournament (SQLModel, table=True):
    tournament_id: int = Field(default=None, primary_key=True)
    name: str
    status: str
    number_of_teams: int
    current_round: int
    total_rounds: int
    winner_id: int | None = None

class Match (SQLModel, table=True):
    match_id: int = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.tournament_id")
    round_num: int
    team1_id: str
    team2_id : str
    team1_score : int | None = None
    team2_score : int | None = None
    winner_id: int | None = None
    loser_id : int | None = None
    status: str

class Game_Round (SQLModel, table=True):
    round_id: int = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.tournament_id")
    round_num: int
    matches_in_round: int
    status: str