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