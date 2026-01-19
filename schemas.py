from sqlmodel import SQLModel


class PlayerBase(SQLModel):
    name: str
    email: str

class PlayerCreate(PlayerBase):
    pass

class PlayerRead(PlayerBase):
    player_id: int

    class Config:
        orm_mode = True

class GameBase(SQLModel):
    player_id: int
    round: int
    eliminated: bool

class GameCreate(GameBase):
    pass

class MatchResult(SQLModel):
    match_num: int
    team_names: list[str]
    score: list[int]
    round: int

class TournamentCreate(SQLModel):
    name: str
    