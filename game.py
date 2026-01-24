from email.mime import base
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from json import load
import smtplib
from unittest import runner
from webbrowser import get
from fastapi import BackgroundTasks, FastAPI, Depends, HTTPException, Request, Form, Response, requests, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Annotated
from database import sessionDep, create_db_and_tables
from models import Player, Game, RefreshToken, Scoreboard, Tournament, Match, Game_Round, User, VerificationToken
from sqlmodel import Session, select, func
from schemas import PlayerCreate, PlayerRead, TournamentCreate, UserCreate, UserResponse, Token, TokenData, EmailVerificationRequest
import random
from itertools import batched
from sqlalchemy import update
import math
import os
from jose import JWTError, jwt
from datetime import datetime, timedelta
import secrets
from passlib.context import CryptContext
from dotenv import load_dotenv
#import mailtrap as mt
import resend
load_dotenv()


# ============ ENVIRONMENT VARIABLES ============
SECRET_KEY = os.getenv("SECRET_KEY", "your_default_secret_key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))
VERIFICATION_TOKEN_EXPIRE_HOURS = int(os.getenv("VERIFICATION_TOKEN_EXPIRE_HOURS", 24))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./jidalli.db")
base_url = os.getenv("BASE_URL", "http://localhost:8000")

#Email settings
#EMAILS_ENABLED=True
#SMTP_SERVER="smtp.gmail.com"
#SMTP_HOST=smtp.example.com
#SMTP_PORT=587
#SMTP_USERNAME="peterenesibello@gmail.com"
#SMTP_PASSWORD="qwrrelrcykeqffnv"
#FROM_EMAIL="noreply@jidalli.com"
#MAIL_STARTTLS=True

#MAIL_SSL_TLS=False


#Email settings
EMAILS_ENABLED=True
SMTP_SERVER=os.getenv("SMTP_SERVER")
SMTP_PORT=int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME=os.getenv("SMTP_USERNAME")
SMTP_PASSWORD=os.getenv("SMTP_PASSWORD") 
FROM_EMAIL=os.getenv("FROM_EMAIL", "jidalli@example.com")
MAIL_STARTTLS=os.getenv("MAIL_STARTTLS", "True").lower() in ("true", "1", "t")
MAIL_SSL_TLS=os.getenv("MAIL_SSL_TLS", "False").lower() in ("true", "1", "t")
MAILTRAP_API=os.getenv("MAILTRAP_API")
MAILTRAP_USE_SANDBOX=os.getenv("MAILTRAP_USE_SANDBOX", "True").lower() in ("true", "1", "t")
MAILTRAP_INBOX_ID=int(os.getenv("MAILTRAP_INBOX_ID"))
RESEND_API=os.getenv("RESEND_API","re_hBLd9qzs_4hJjRJSnSZD5J39EFfv31WPW")


app = FastAPI()


# Mount static files (CSS, JS, images)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="templates")

#================= Helper functions ==================
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme=OAuth2PasswordBearer(tokenUrl="login")

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

async def get_token(request: Request) -> str:
    """Dependency: Get JWT token from request headers"""
    auth_header = request.headers.get("Authorization")
    if auth_header: 
        # Split "Bearer <token>" and return only <token>
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        
    """Dependency: Get JWT token from request cookies"""
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        if cookie_token.startswith("Bearer "):
            return cookie_token.replace("Bearer ", "")
        return cookie_token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    return token

async def get_current_user(token: Annotated[str , Depends(get_token)], session: sessionDep) -> User:
    """Dependency: Get current user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        token_type: str = payload.get("type")
        if username is None or token_type != "access":
            raise credentials_exception
        token_data = TokenData(username=username) # this isnt necessary
        # could just use username directly in the query below
    except JWTError:
        raise credentials_exception
    
    user = session.exec(select(User).where(User.username == token_data.username)).first()
    if user is None:
        raise credentials_exception
    return user

# current user dependency
CurrentUserDep = Annotated[User, Depends(get_current_user)]



async def get_current_active_user(current_user: CurrentUserDep) -> User:
    """Dependency: Get current active user"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

# get current active user dependency
CurrentActiveUserDep = Annotated[User, Depends(get_current_active_user)]

async def get_admin_user(current_user: CurrentUserDep) -> User:
    """Dependency: Get current admin user"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user


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

def advance_tournament_round(request: Request, tournament: Tournament, session: sessionDep):
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
            new_round = templates.TemplateResponse(
                "round_advance.html", {"request": request, "matches": match_list,
                                       "message": f"Advanced to round {tournament.current_round}"}
            )
            return new_round
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




def create_verification_token() -> str:
    """Create a JWT token for email verification"""
    return secrets.token_urlsafe(32)

def hash_password(password: str) -> str:
    """Hash the password (placeholder function)"""
    # In production, use a proper hashing algorithm like bcrypt
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)

#client = mt.MailtrapClient(token=MAILTRAP_API, sandbox=True, inbox_id=4328972)
def send_verification_email_task(email: str, token: str, name: str):
    verification_link = f"{base_url}/verify-email?token={token}"
    
    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #27ae60;">Welcome to Jidalli Tournament Manager</h2>
            <p>Hello {name},</p>
            <p>Please verify your email by clicking the button below:</p>
            <p style="margin: 30px 0;">
                <a href="{verification_link}" 
                   style="background-color: #27ae60; color: white; padding: 12px 30px; 
                          text-decoration: none; border-radius: 5px; display: inline-block;">
                    Verify Email
                </a>
            </p>
            <p>Or copy this link: {verification_link}</p>
        </body>
    </html>
    """
    
    resend.api_key=RESEND_API   # Must save it to resend.api_key   
    
    try:
        print(f"Sending message to {email}....")
        resend.Emails.send({
            "from": "Jidalli <onboarding@resend.dev>",  # Free tier uses resend.dev
            "to": [email],
            "subject": "Verify your email - Jidalli Tournament Manager",
            "html": html_body
        })
        
        print(f"✓ Email sent to {email}: Status: OK")
    except Exception as e:
        print(f"✗ Failed to send email to {email}: {e}")

def send_verification_email(email: str, token: str, name: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(send_verification_email_task,email,token, name)


def send_email(to_email: str, subject: str, body: str, background_tasks:BackgroundTasks):
    """Send an email (placeholder function)"""
    if not EMAILS_ENABLED:
        print("Email sending is disabled.")
    
    """ Send mail in the background    """
    def _send():
        try:
            # Here you would integrate with an actual email sending service
            msg= MIMEMultipart()
            msg['From']= FROM_EMAIL
            msg['To']= to_email
            msg['Subject']= subject
            msg.attach(MIMEText(body, 'html'))

            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.set_debuglevel(1)
                server.ehlo()
                if MAIL_STARTTLS:
                    server.starttls()
                    server.ehlo()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
            print(f"Email sent to {to_email}")
        except Exception as e:
            print(f"Failed to send email to {to_email}: {e}")
    background_tasks.add_task(_send)
    #_send()  # For testing purposes, send immediately
    # Here you would integrate with an actual email sending service
    print(f"Sending email to {to_email}:\nSubject: {subject}\n\n{body}")

# Disable this to use email api above cos render.com blocks smtp ports
#def send_verification_email(to_email: str, token: str, full_name: str, background_tasks:BackgroundTasks):
 #   """Send verification email to user (placeholder function)"""
  #  if not EMAILS_ENABLED:
   #     print("Email sending is disabled.")
    #    return
    
    #verification_link = f"{base_url}/verify-email?token={token}"
    #subject = "Verify your email address"
    #body = f"""
    #<html>
    #<body>
    #<H2> Welcome to Jidalli Tournament Manager</H2>
    #<p>Hello {full_name},</p>
    #<p>Please verify your email by clicking the link below:</p>
    #<strong><a href="{verification_link}">Verify Email</a></strong>
    #<p>Thank you!</p>
    #</body>
    #</html>
    #"""

    #send_email(to_email, subject, body, background_tasks)
    #print(f"Sending email to {to_email}:\nSubject: {subject}\n\n{body}")

def create_access_token(data: dict, expires_delta:timedelta | None = None):
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict, expires_delta:timedelta | None = None):
    """Create a JWT refresh token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# ============ ENDPOINT ROUTES ============

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: sessionDep):
    """Homepage - list all tournaments"""
    tournaments = session.exec(select(Tournament)).all()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "tournaments": tournaments}
    )
    
@app.post("/players/", response_model=PlayerRead)
def create_player(player: PlayerCreate, session: sessionDep, current_user: CurrentActiveUserDep):
    db_player = Player.model_validate(player)
    session.add(db_player)
    session.commit()
    session.refresh(db_player)
    return {"player": db_player, "user": current_user}


@app.post("/tournaments/")
def create_tournament(tournament: TournamentCreate, session: sessionDep, current_user: CurrentActiveUserDep):
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
             "round_record": round_record,
             "user": current_user
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



@app.post("/tournaments/{tournament_id}/matches/{id}/score/")
def update_match_score(request:Request,
                       team1_score: Annotated[int, Form()], 
                       team2_score: Annotated[int, Form()], 
                       session: sessionDep,
                       match: Annotated[Match, Depends(verify_match_belongs_to_tournament)],
                       current_user: CurrentActiveUserDep
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
            result = advance_tournament_round(request, tournament, session)
            
        return result
    
    
    return RedirectResponse(
        url=f"/tournaments/{match.tournament_id}",
        status_code=303
    )



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
# Add current user dependency to restrict access to admins/users only
async def create_player_form(request: Request, current_user: CurrentActiveUserDep):
    """Show create player form"""
    return templates.TemplateResponse(
        "create_player.html", 
        {"request": request, "user": current_user}
    )

@app.post("/players/create", response_class=HTMLResponse)
async def create_player_from_form(
    request: Request,
    name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    session: sessionDep,
    current_user: CurrentActiveUserDep
):
    """Handle player creation from HTML form"""
    player_data = PlayerCreate(name=name, email=email)
    db_player = create_player(player_data, session, current_user)

    return RedirectResponse(
        url="/players/",
        status_code=303
    )

@app.get("/tournaments/create", response_class=HTMLResponse)
async def create_tournament_form(request: Request, current_user: CurrentActiveUserDep):
    """Show create tournament form"""
    return templates.TemplateResponse(
        "create_tournament.html", 
        {"request": request,
         "user": current_user}
    )


@app.post("/tournaments/create", response_class=HTMLResponse)
async def create_tournament_from_form(
    request: Request,
    name: Annotated[str, Form()],
    session: sessionDep,
    current_user: CurrentActiveUserDep
):
    """Handle tournament creation from HTML form"""
    tournament_data = TournamentCreate(name=name)
    result = create_tournament(tournament_data, session, current_user)

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
    session: sessionDep,
    current_user: CurrentUserDep
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
            "team2": team2,
            "user": current_user
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
    session: sessionDep,
    current_user: CurrentUserDep
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



#================= JWT AUTHENTICATION ROUTES ================

@app.post("/register_user", response_model=UserResponse, status_code=201)
#def register_user(user: UserCreate, session: sessionDep):
async def register_user_from_form(
    request: Request,
    username: Annotated[str, Form()],
    email: Annotated[str, Form()],
    full_name: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    session: sessionDep,
    background_tasks: BackgroundTasks
):
    """Handle user registration from HTML form"""
    
    # Validate passwords match
    if password != confirm_password:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "error": "Passwords do not match"
            }
        )

    """Register a new user"""
    existing_user = session.exec(
        select(User).where(User.username == username.lower())
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    existing_email = session.exec(
        select(User).where(User.email == email)
    ).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    
    db_user = User(
        username=username.lower(),
        email=email,
        full_name=full_name,
        password=hash_password(password),
        is_active = False,
        is_verified = False
    )
    session.add(db_user)
    session.flush()
    session.refresh(db_user)
    print(f"Created user: {db_user.username} with ID {db_user.user_id}")
    
    # Here you would send a verification email with the token
    verification_token = create_verification_token()
    print(f"Verification token for {db_user.email}: {verification_token}")
    verification = VerificationToken(
        user_id = db_user.user_id,
        token = verification_token,
        token_type = "email_verification",
        expires_at = datetime.utcnow() + timedelta(hours=int(VERIFICATION_TOKEN_EXPIRE_HOURS))
    )
    session.add(verification)
    session.commit()
    print(f" created verification token record for user ID {verification.user_id}")


    send_verification_email(db_user.email, verification_token, db_user.full_name, background_tasks)
    # Show success page
    return templates.TemplateResponse(
        "register_success.html",
        {
            "request": request,
            "email": db_user.email
        }
    )


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Show registration form"""
    return templates.TemplateResponse(
        "register.html",
        {"request": request}
    )


   

@app.get("/verify-email", response_class=HTMLResponse)
def verify_email(request: Request, token: str, session: sessionDep):
    """Verify user's email address using token"""
    print(f"Verifying email with token: {token}")
    session.expire_all()  # Clear session cache to ensure fresh data

    # Used the chained .where clauses for clarity instead of &
    # this also avoids potential operator precedence issues with SQLModel bitwiswe &
    verification = session.exec(select(VerificationToken)
                                .where(VerificationToken.token == token)
                                .where(VerificationToken.token_type == "email_verification")
                                .where(VerificationToken.used == False)
                                ).first()
    print (f"Verification lookup for token {token}: {verification}")
    if not verification:
        return templates.TemplateResponse(
            "email_verification.html",
            {"request": request, "error": "Invalid or expired verification token."}
        )
    
    if verification.expires_at < datetime.utcnow():
        return templates.TemplateResponse(
            "email_verification.html",
            {"request": request, "error": "Verification token has expired."}
        )
    
    user = session.get(User, verification.user_id)
    print(f"Found user: {user.username if user else 'None'} (ID: {verification.user_id})")  # Debug print

    if not user:
        return templates.TemplateResponse(
            "email_verification.html",
            {"request": request, "error": "User not found."}
        )
    
    user.is_verified = True
    user.is_active = True
    user.updated_at = datetime.utcnow()
    #session.delete(verification)  # Remove used token
    verification.used = True
    session.add(user)
    
    session.add(verification)
    session.commit()
    
    session.refresh(user)

    print(f"Verified user: {user.username} (ID: {user.user_id})")  # Debug print

    return templates.TemplateResponse(
        "email_verification.html",
        {"request": request, "username": user.username, "message": "Email verified successfully! You can now log in."}
    )

@app.get("/resend-verification", response_class=HTMLResponse)
async def resend_verification_page(request: Request, session: sessionDep, background_tasks: BackgroundTasks):
    """Show form to resend verification email"""
    if request.method == "POST":
        form = await request.form()
        email = form.get("email")

        
        # Logic to resend verification email goes here
        # ...
        db_user = session.exec(
            select(User).where(User.email == email)
        ).first()
        if not db_user:
            return templates.TemplateResponse(
                "resend_verification.html",
                {"request": request, "message": "Verification email resent if the email exists in our system."}
            )
        if db_user.is_verified:
            return templates.TemplateResponse(
                "resend_verification.html",
                {"request": request, "message": "Email is already verified."}
            )
        if db_user.created_at > datetime.utcnow() - timedelta(minutes=1):
            return templates.TemplateResponse(
                "resend_verification.html",
                {"request": request, "message": "Please wait before requesting another verification email."}
            )
         # Here you would send a verification email with the token
        verification_token = create_verification_token()
        print(f"Verification token for {email}: {verification_token}")
        verification = VerificationToken(
            user_id = db_user.id,
            token = verification_token,
            token_type = "email_verification",
            expires_at = datetime.utcnow() + timedelta(hours=int(VERIFICATION_TOKEN_EXPIRE_HOURS))
        )
        session.add(verification)
        session.commit()
        session.refresh(db_user)
        

        send_verification_email(db_user.email, verification_token, db_user.full_name, background_tasks)
        # Show success page
        return templates.TemplateResponse(
            "register_success.html",
            {
                "request": request,
                "email": db_user.email
            }
        )
        return templates.TemplateResponse(
            "resend_verification.html",
            {"request": request, "message": "Verification email resent if the email exists in our system."}
        )
    return templates.TemplateResponse(
        "resend_verification.html",
        {"request": request}
    )


@app.post("/login", response_model=Token)
def login_for_access_token(session: sessionDep,
                           response: Response,
                           form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticate user and return JWT token"""
    user = session.exec(
        select(User).where(User.username == form_data.username.lower())
    ).first()
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    if not verify_password(form_data.password, user.password):
        raise HTTPException(status_code=400, detail="Incorrect username or password", 
                            headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires
    )
    refresh_token_str = create_refresh_token(
        data={"sub": user.username}
    )

    # Store refresh token in database
    refresh_token = RefreshToken(
        user_id = user.user_id,
        token = refresh_token_str,
        expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    session.add(refresh_token)
    session.commit()
    session.refresh(refresh_token)

    # Save token in cookie and redirect to home
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax"
    )
    return response
    #return Token(access_token=access_token, token_type="bearer", refresh_token=refresh_token_str)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show login form"""
    return templates.TemplateResponse(
        "login.html",
        {"request": request}
    )

@app.get("/logout", response_class=HTMLResponse)
async def logout(request: Request, response: Response):
    """Logout user by clearing the access token cookie"""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="access_token")
    return response