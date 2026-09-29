BOOTSTRAP_ADMIN_EMAIL = "solavolantes@gmail.com"
ROLES = ("user", "admin")
STATUSES = ("active", "suspended")


def initial_role_for(email: str) -> str:
    return "admin" if email.strip().lower() == BOOTSTRAP_ADMIN_EMAIL else "user"


def is_admin(user: dict | None) -> bool:
    return bool(user) and user.get("role") == "admin" and user.get("status") == "active"
