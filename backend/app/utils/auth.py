from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(password):
    """Return a Werkzeug password hash suitable for storage."""
    return generate_password_hash(password)


def verify_password(password_hash, password):
    """Check a password without exposing or returning the stored hash."""
    try:
        return check_password_hash(password_hash, password)
    except (TypeError, ValueError):
        return False
