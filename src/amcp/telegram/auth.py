from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AuthMiddleware:
    allowed_users: set[int] = field(default_factory=set)
    admin_users: set[int] = field(default_factory=set)

    def is_authorized(self, user_id: int) -> bool:
        return user_id in self.allowed_users

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_users

    def update_allowed_users(self, users: set[int]) -> None:
        self.allowed_users = set(users)

    def update_admin_users(self, users: set[int]) -> None:
        self.admin_users = set(users)
