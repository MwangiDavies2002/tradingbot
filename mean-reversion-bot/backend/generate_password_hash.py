"""Hash a role password for the backend environment."""
import argparse
import getpass
import hashlib
from pathlib import Path

MIN_PASSWORD_LENGTH = 8


def update_env_file(env_path: Path, role: str, password_hash: str) -> None:
    setting = f"API_{role.upper()}_PASSWORD_HASH"
    contents = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = contents.splitlines()
    replacement = f"{setting}={password_hash}"

    for index, line in enumerate(lines):
        if line.startswith(f"{setting}="):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("admin", "operator", "viewer"))
    parser.add_argument(
        "--update-env",
        action="store_true",
        help="write the hash into the backend .env file instead of printing it",
    )
    args = parser.parse_args()

    password = getpass.getpass("Password (minimum 8 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        parser.error("passwords do not match")
    if len(password) < MIN_PASSWORD_LENGTH:
        parser.error(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if args.update_env:
        env_path = Path(__file__).resolve().with_name(".env")
        update_env_file(env_path, args.role, password_hash)
        print(f"Updated {env_path.name} for the {args.role} role.")
    else:
        print(f"API_{args.role.upper()}_PASSWORD_HASH={password_hash}")


if __name__ == "__main__":
    main()
