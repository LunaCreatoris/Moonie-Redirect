"""Settings > Security: the password (set here, else the file's), the sessions, the login brake, `reset-password`."""

# The fixtures of test_app.py are imported, and every test names them as its arguments
# ruff: noqa: F811

import sqlite3

import pytest
from test_app import AUTH, PASSWORD, client, clock, csrf_of, env, flask_app, login, store  # noqa: F401

import app

NEW = "a much longer new password"


def admin(client):
    """A signed-in client and a function that sends a change through it, as the pages do."""
    csrf = login(client)

    def send(method, path, **kwargs):
        headers = {"X-CSRF-Token": csrf, "Sec-Fetch-Site": "same-origin"}
        return client.open(path, method=method, headers=headers, **kwargs)

    return send


def sign_in(client, password):
    return client.post("/login", data={"password": password, "csrf": csrf_of(client)})


def test_security_says_where_the_password_comes_from(client, store):
    send = admin(client)
    answer = send("GET", "/api/settings/security").get_json()
    assert answer == {"password": {"origin": "file"}, "sessions": {"active": 1, "hours": 12}, "login_brake_seconds": 1}
    store.set_setting(app.ADMIN_PASSWORD_SETTING, app.hash_password(NEW))
    assert send("GET", "/api/settings/security").get_json()["password"] == {"origin": "stored"}


def test_with_no_password_anywhere_the_origin_is_missing(env, clock):
    env.pop("MOONIE_REDIRECT_PASSWORD_FILE")
    flask_app = app.create_app(env)
    client = flask_app.test_client()
    page = sign_in(client, "anything at all").get_data(as_text=True)
    assert "No password is configured" in page
    flask_app.extensions["store"].set_setting(app.ADMIN_PASSWORD_SETTING, app.hash_password(NEW))
    clock[0] += 2
    assert sign_in(client, NEW).status_code == 302  # the password set here, with no file at all


def test_a_changed_password_wins_over_the_file_and_ends_the_other_sessions(flask_app, store, clock):
    mine, other = flask_app.test_client(), flask_app.test_client()
    send = admin(mine)
    login(other)
    answer = send("POST", "/api/settings/password", json={"password": PASSWORD, "new_password": NEW})
    assert answer.status_code == 204
    stored = store.setting(app.ADMIN_PASSWORD_SETTING)
    assert stored.startswith("scrypt$16384$8$1$") and NEW not in stored
    assert other.get("/api/status").status_code == 401
    assert send("GET", "/api/status").status_code == 200  # this one stays open
    assert send("GET", "/api/settings/security").get_json()["sessions"]["active"] == 1
    fresh = flask_app.test_client()
    assert sign_in(fresh, PASSWORD).status_code == 401  # the file's no longer counts
    clock[0] += 2
    assert sign_in(fresh, NEW).status_code == 302


def test_a_wrong_current_password_is_refused_and_brakes_the_next_try(client, store, clock):
    send = admin(client)
    wrong = send("POST", "/api/settings/password", json={"password": "not it", "new_password": NEW})
    assert wrong.status_code == 400
    assert wrong.get_json() == {"error": "login_failed", "fields": {"password": "wrong password"}}
    braked = send("POST", "/api/settings/password", json={"password": PASSWORD, "new_password": NEW})
    assert braked.status_code == 429 and braked.get_json() == {"error": "too_many_attempts"}
    # The login shares the brake
    assert sign_in(client.application.test_client(), PASSWORD).status_code == 429
    clock[0] += 1.5
    assert send("POST", "/api/settings/password", json={"password": PASSWORD, "new_password": NEW}).status_code == 204
    clock[0] += 0.1
    # A success gave the brake back: the next check goes at once
    assert send("POST", "/api/settings/password", json={"password": NEW, "new_password": PASSWORD}).status_code == 204


@pytest.mark.parametrize("new", [None, 12345678901234, "", "x" * 11, "x" * 1025, ["x" * 20]])
def test_a_new_password_out_of_bounds_is_refused_before_the_current_is_checked(client, store, new):
    send = admin(client)
    answer = send("POST", "/api/settings/password", json={"password": "wrong", "new_password": new})
    assert answer.status_code == 400 and answer.get_json()["error"] == "invalid"
    assert set(answer.get_json()["fields"]) == {"new_password"}
    assert store.setting(app.ADMIN_PASSWORD_SETTING) is None
    # Nothing was checked, so nothing brakes
    assert (
        send("POST", "/api/settings/password", json={"password": PASSWORD, "new_password": "x" * 12}).status_code == 204
    )


def test_the_bounds_are_12_and_1024_characters(client):
    send = admin(client)
    assert (
        send("POST", "/api/settings/password", json={"password": PASSWORD, "new_password": "é" * 1024}).status_code
        == 204
    )


def test_a_password_change_needs_the_csrf_token(client, store):
    login(client)
    answer = client.post("/api/settings/password", json={"password": PASSWORD, "new_password": NEW})
    assert answer.status_code == 403 and answer.get_json() == {"error": "csrf"}
    assert store.setting(app.ADMIN_PASSWORD_SETTING) is None


def test_end_all_sessions_ends_this_one_too(flask_app):
    mine, other = flask_app.test_client(), flask_app.test_client()
    send = admin(mine)
    login(other)
    assert send("POST", "/api/settings/sessions/end", json={}).status_code == 204
    assert mine.get("/api/status").status_code == 401
    assert other.get("/api/status").status_code == 401
    assert flask_app.extensions["store"].sessions_active(app.time.time()) == 0


# --- The password hash ---


def test_the_hash_checks_its_own_password_only():
    stored = app.hash_password(NEW)
    assert app.password_matches(stored, NEW)
    assert not app.password_matches(stored, NEW + " ")
    assert app.hash_password(NEW) != stored  # a new salt each time


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "scrypt",
        "bcrypt$16384$8$1$AAAA$AAAA",
        "scrypt$16383$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAA",  # not a power of two
        "scrypt$2097152$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAA",  # too costly to try
        "scrypt$16384$8$1$not base64!$AAAA",
        "scrypt$16384$8$1$AAAA$",
        "scrypt$x$8$1$AAAA$AAAA",
    ],
)
def test_a_damaged_hash_matches_nothing(stored):
    assert not app.password_matches(stored, NEW)


# --- reset-password ---


def test_reset_password_drops_the_hash_and_ends_every_session(flask_app, store, env, monkeypatch, capsys):
    send = admin(flask_app.test_client())
    assert send("POST", "/api/settings/password", json={"password": PASSWORD, "new_password": NEW}).status_code == 204
    monkeypatch.setenv("MOONIE_REDIRECT_DB", env["MOONIE_REDIRECT_DB"])
    assert app.main(["app.py", "reset-password"]) == 0
    assert "is removed" in capsys.readouterr().out
    assert store.setting(app.ADMIN_PASSWORD_SETTING) is None
    assert send("GET", "/api/status").status_code == 401
    assert sign_in(flask_app.test_client(), PASSWORD).status_code == 302  # the file's counts again
    assert app.main(["app.py", "reset-password"]) == 0
    assert "already in force" in capsys.readouterr().out


def test_reset_password_takes_no_argument(capsys):
    assert app.main(["app.py", "reset-password", "now"]) == 2
    assert "reset-password" in capsys.readouterr().err


def test_the_password_hash_is_the_only_trace_in_the_database(flask_app, env):
    send = admin(flask_app.test_client())
    send("POST", "/api/settings/password", json={"password": PASSWORD, "new_password": NEW})
    with sqlite3.connect(env["MOONIE_REDIRECT_DB"]) as conn:
        dump = "\n".join(conn.iterdump())
    conn.close()
    assert NEW not in dump and PASSWORD not in dump


def test_the_settings_never_answer_a_bearer_key(client):
    for path in ("/api/settings/security", "/api/settings/password", "/api/settings/sessions/end"):
        answer = client.open(path, method="GET" if path.endswith("security") else "POST", headers=AUTH, json={})
        assert answer.status_code == 403 and answer.get_json() == {"error": "needs_admin"}
