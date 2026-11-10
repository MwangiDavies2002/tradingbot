"""Hash a role password for the backend environment."""
import argparse
import getpass
import hashlib

MIN_PASSWORD_LENGTH = 8


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("admin", "operator", "viewer"))
    args = parser.parse_args()

    password = getpass.getpass("Password (minimum 8 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        parser.error("passwords do not match")
    if len(password) < MIN_PASSWORD_LENGTH:
        parser.error(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    print(f"API_{args.role.upper()}_PASSWORD_HASH={password_hash}")


if __name__ == "__main__":
    main()
