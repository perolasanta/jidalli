from datetime import datetime
from sqlmodel import SQLModel
from pydantic import EmailStr


class PlayerBase(SQLModel):
    name: str
    email: EmailStr

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
    

    #======== JWT Token Schemas ========

class UserCreate(SQLModel):
    username: str
    email: str 
    full_name: str
    password: str 
    is_active: bool = False
    is_verified: bool = False

class UserResponse(SQLModel):
    user_id: int
    username: str
    email: str 
    full_name: str
    is_admin: bool
    is_active: bool
    created_at: datetime 

class Token(SQLModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
class TokenData(SQLModel):
    username: str | None = None

class EmailVerificationRequest(SQLModel):
    token: str