"""Password verification and short-lived access tokens."""

from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from models import User


class AuthService:
    def __init__(self, sessions: sessionmaker[Session], secret: str) -> None:
        self._sessions = sessions
        self._secret = secret
        self._passwords = PasswordHash.recommended()

    def register(self, username: str, password: str) -> dict | None:
        password_hash = self._passwords.hash(password)
        try:
            with self._sessions.begin() as session:
                user = User(username=username, password_hash=password_hash)
                session.add(user)
                session.flush()
                return {"id": user.id, "username": user.username}
        except IntegrityError:
            return None

    def login(self, username: str, password: str) -> str | None:
        with self._sessions() as session:
            user = session.scalar(select(User).where(User.username == username))
            if user is None or not self._passwords.verify(password, user.password_hash):
                return None
            user_id = user.id
        expires = datetime.now(timezone.utc) + timedelta(minutes=30)
        return jwt.encode(
            {"sub": str(user_id), "exp": expires},
            self._secret,
            algorithm="HS256",
        )

    def user_id_for_token(self, token: str) -> int | None:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                options={"require": ["sub", "exp"]},
            )
            user_id = int(payload["sub"])
            if user_id < 1:
                return None
        except (InvalidTokenError, ValueError, TypeError):
            return None
        with self._sessions() as session:
            return user_id if session.get(User, user_id) is not None else None
