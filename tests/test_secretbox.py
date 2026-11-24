"""The secrets the app must read back (D23): AES-256-GCM rows, the store key file, and its fallback beside the data."""

import logging
import os
import pickle
import re
import subprocess
import sys

import pytest

import app

KEY = bytes(range(32))
OTHER = bytes(range(1, 33))
SECRET = "cf-secret-value-0123456789"


@pytest.fixture
def store(tmp_path):
    return app.Store(tmp_path / "data" / "redirect.db")


def test_a_sealed_value_opens_again(store):
    box = app.SecretBox(KEY)
    store.write_sealed(box, "cloudflare_token", SECRET)
    assert store.read_sealed(box, "cloudflare_token") == ("stored", SECRET)
    assert store.read_sealed(box, "webhook_secret") == ("missing", None)
    store.write_sealed(box, "cloudflare_token", "replaced")
    assert store.read_sealed(app.SecretBox(KEY), "cloudflare_token") == ("stored", "replaced")
    assert store.drop_sealed("cloudflare_token") and not store.drop_sealed("cloudflare_token")
    assert store.read_sealed(box, "cloudflare_token") == ("missing", None)


def test_every_seal_draws_its_own_nonce():
    box = app.SecretBox(KEY)
    first, second = box.seal("cloudflare_token", SECRET), box.seal("cloudflare_token", SECRET)
    assert first[0] == second[0] == box.key_id and len(first[0]) == 8
    assert first[1] != second[1] and first[2] != second[2] and len(first[1]) == 12


def test_a_value_moved_to_another_row_does_not_open():
    box = app.SecretBox(KEY)
    key_id, nonce, value = box.seal("cloudflare_token", SECRET)
    assert box.open("cloudflare_token", key_id, nonce, value) == SECRET
    assert box.open("webhook_secret", key_id, nonce, value) is None


def test_another_key_reads_unreadable_never_an_error(store):
    store.write_sealed(app.SecretBox(KEY), "webhook_secret", SECRET)
    other = app.SecretBox(OTHER)
    assert other.key_id != app.SecretBox(KEY).key_id
    assert store.read_sealed(other, "webhook_secret") == ("unreadable", None)


@pytest.mark.parametrize(
    "damage",
    [
        lambda row: (row[0], row[1], row[2][:-1] + bytes([row[2][-1] ^ 1])),  # one bit of the tag
        lambda row: (row[0], row[1][:-1] + bytes([row[1][-1] ^ 1]), row[2]),  # one bit of the nonce
        lambda row: (row[0], row[1][:8], row[2]),  # a short nonce
        lambda row: (row[0], "text", row[2]),  # a nonce of another type
        lambda row: (row[0], row[1], b""),  # nothing
    ],
)
def test_a_damaged_row_reads_unreadable(damage):
    box = app.SecretBox(KEY)
    assert box.open("cloudflare_token", *damage(box.seal("cloudflare_token", SECRET))) is None


def test_the_database_files_never_hold_the_value(store):
    store.write_sealed(app.SecretBox(KEY), "cloudflare_token", SECRET)
    folder = store.path.parent
    held = b"".join(path.read_bytes() for path in folder.iterdir() if path.is_file())
    assert SECRET.encode() not in held


def test_the_box_never_shows_its_key():
    box = app.SecretBox(KEY)
    assert KEY.hex() not in repr(box) and box.key_id in repr(box)
    with pytest.raises(TypeError):
        pickle.dumps(box)
    with pytest.raises(ValueError):
        app.SecretBox(KEY[:16])


# --- The store key ---


def test_the_key_file_is_read(tmp_path):
    (tmp_path / "store_key").write_text(KEY.hex().upper() + "\n")
    env = {"MOONIE_REDIRECT_STORE_KEY_FILE": str(tmp_path / "store_key")}
    assert app.store_key(env, tmp_path / "data") == KEY
    assert not (tmp_path / "data" / app.STORE_KEY_FILE).exists()


@pytest.mark.parametrize("content", ["", "abc", KEY.hex()[:-1], KEY.hex() + "0", "g" * 64, KEY.hex() + " x"])
def test_a_malformed_key_file_stops_the_start(tmp_path, content):
    (tmp_path / "store_key").write_text(content)
    with pytest.raises(SystemExit, match="64 hexadecimal"):
        app.store_key({"MOONIE_REDIRECT_STORE_KEY_FILE": str(tmp_path / "store_key")}, tmp_path)


def test_a_key_file_that_cannot_be_read_stops_the_start(tmp_path):
    with pytest.raises(SystemExit, match="cannot be read"):
        app.store_key({"MOONIE_REDIRECT_STORE_KEY_FILE": str(tmp_path / "absent")}, tmp_path)
    (tmp_path / "binary").write_bytes(b"\xff\xfe\xfa" * 30)
    with pytest.raises(SystemExit):
        app.store_key({"MOONIE_REDIRECT_STORE_KEY_FILE": str(tmp_path / "binary")}, tmp_path)


def test_without_a_key_file_one_is_drawn_once_beside_the_database(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    first = app.store_key({}, tmp_path)
    assert len(first) == 32 and app.store_key({}, tmp_path) == first
    text = (tmp_path / app.STORE_KEY_FILE).read_text()
    assert bytes.fromhex(text.strip()) == first
    assert sum("drew a new store key" in record.message for record in caplog.records) == 1
    assert any("MOONIE_REDIRECT_STORE_KEY_FILE" in record.message for record in caplog.records)
    assert not [path for path in tmp_path.iterdir() if path.name.endswith(".tmp")]


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX only; Windows keeps its own ACLs")
def test_the_drawn_key_is_readable_by_its_owner_only(tmp_path):
    app.store_key({}, tmp_path)
    assert (tmp_path / app.STORE_KEY_FILE).stat().st_mode & 0o777 == 0o600


def test_a_drawn_key_that_is_a_directory_stops_the_start_cleanly(tmp_path):
    (tmp_path / app.STORE_KEY_FILE).mkdir()
    with pytest.raises(SystemExit, match="cannot be read"):
        app.store_key({}, tmp_path)


def test_a_drawn_key_that_cannot_be_read_stops_the_start_cleanly(tmp_path, monkeypatch):
    app.store_key({}, tmp_path)
    real = app.Path.read_text

    def refuse(self, *args, **kwargs):
        if self.name == app.STORE_KEY_FILE:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    # A mode change does not stop root in the test container, so the refusal is the one the OS would give
    monkeypatch.setattr(app.Path, "read_text", refuse)
    with pytest.raises(SystemExit, match="cannot be read"):
        app.store_key({}, tmp_path)


def test_a_damaged_drawn_key_stops_the_start(tmp_path):
    (tmp_path / app.STORE_KEY_FILE).write_text("short")
    with pytest.raises(SystemExit, match="damaged"):
        app.store_key({}, tmp_path)


def test_the_app_seals_with_the_key_it_was_given(tmp_path):
    (tmp_path / "store_key").write_text(KEY.hex())
    env = {
        "MOONIE_REDIRECT_DB": str(tmp_path / "data" / "redirect.db"),
        "MOONIE_REDIRECT_PUBLIC_BASE_URL": "https://go.example.test",
        "MOONIE_REDIRECT_STORE_KEY_FILE": str(tmp_path / "store_key"),
    }
    assert app.create_app(env).extensions["box"].key_id == app.SecretBox(KEY).key_id
    (tmp_path / "store_key").write_text("not a key")
    with pytest.raises(SystemExit):
        app.create_app(env)


def test_the_sealed_secrets_adapter_names_rows_by_name(store):
    secrets = app.SealedSecrets(store, app.SecretBox(KEY))
    assert secrets.state("webhook_secret") == "missing" and secrets.read("webhook_secret") is None
    secrets.write("webhook_secret", SECRET)
    assert secrets.state("webhook_secret") == "stored" and secrets.read("webhook_secret") == SECRET
    assert app.SealedSecrets(store, app.SecretBox(OTHER)).state("webhook_secret") == "unreadable"
    assert secrets.delete("webhook_secret") and secrets.state("webhook_secret") == "missing"


# --- The deployment: the recipe that draws the key, and the compose secret that brings it ---

ROOT = app.Path(__file__).resolve().parents[1]


def recipe(name: str) -> str:
    """The body of a justfile recipe, its lines joined."""
    lines = (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{name}:") + 1
    body = []
    for line in lines[start:]:
        if not line.startswith("    "):
            break
        body.append(line.strip())
    return "\n".join(body)


def test_the_store_key_recipe_draws_a_key_the_app_reads(tmp_path):
    code = re.search(r"python -c '([^']+)'", recipe("store-key")).group(1)
    drawn = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    (tmp_path / "store_key").write_text(drawn)
    key = app.store_key({"MOONIE_REDIRECT_STORE_KEY_FILE": str(tmp_path / "store_key")}, tmp_path / "data")
    assert len(key) == 32
    again = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert again != drawn


def test_compose_brings_the_store_key_as_a_secret_outside_the_volume():
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
    assert "MOONIE_REDIRECT_STORE_KEY_FILE: /run/secrets/store_key" in compose
    assert "      - store_key\n" in compose
    assert "  store_key:\n    file: ./secrets/store_key\n" in compose


def test_the_reset_password_recipe_runs_the_command_in_the_stack():
    assert recipe("reset-password") == "docker compose exec moonie python app.py reset-password"
