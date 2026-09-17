"""Run locally to issue a key. Store its hash on the server; give the key to its user."""
import argparse
import hashlib
import secrets

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("admin", "operator", "viewer"))
    args = parser.parse_args()
    key = secrets.token_urlsafe(48)
    print(f"Access key (shown once): {key}")
    print(f"API_{args.role.upper()}_KEY_HASH={hashlib.sha256(key.encode()).hexdigest()}")
