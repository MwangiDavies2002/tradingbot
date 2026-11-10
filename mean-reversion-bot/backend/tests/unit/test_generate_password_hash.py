from generate_password_hash import update_env_file


def test_update_env_file_replaces_password_hash_and_preserves_settings(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_NAME=Mean Reversion Bot\nAPI_ADMIN_PASSWORD_HASH=old\n",
        encoding="utf-8",
    )

    update_env_file(env_file, "admin", "new-hash")

    assert env_file.read_text(encoding="utf-8") == (
        "APP_NAME=Mean Reversion Bot\nAPI_ADMIN_PASSWORD_HASH=new-hash\n"
    )


def test_update_env_file_adds_missing_role_hash(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_NAME=Mean Reversion Bot\n", encoding="utf-8")

    update_env_file(env_file, "operator", "new-hash")

    assert env_file.read_text(encoding="utf-8").endswith(
        "API_OPERATOR_PASSWORD_HASH=new-hash\n"
    )
