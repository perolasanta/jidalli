from fastapi import FastAPI, Depends
from typing import Annotated
from sqlmodel import SQLModel, Session, create_engine

DATABASE_URL = "sqlite:///./jidalli.db"
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

sessionDep = Annotated[Session, Depends(get_session)]


