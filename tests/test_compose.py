"""compose.yml deploys with plain Docker Compose, or as a Portainer stack, with no just, in either mode.

The guide offers two ways to deploy: plain `docker compose` (or Portainer) and the just recipes. These tests pin what
the first one needs from compose.yml: compose builds the image from the repository itself, every variable it reads
has a default except the one the app cannot start without, and the secret files can live in any folder of the host,
as a Portainer stack cannot reach the repository's relative paths.

Two modes (D35): compose.yml alone is LAN mode, which publishes the port on the host and needs no network made
beforehand; compose.proxy.yml, laid over it, is reverse-proxy mode, which drops the published port and joins the
proxy's external network, with Traefik labels as the example. `just compose-check` runs `docker compose config` on
both, with no variable but the public address (and the proxy's host for the overlay), in the pinned Docker CLI image.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = (ROOT / "compose.yml").read_text(encoding="utf-8")
PROXY = (ROOT / "compose.proxy.yml").read_text(encoding="utf-8")


def live(text: str) -> str:
    """A compose file with its comments dropped: what Docker Compose reads."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


class ComposeLoader(yaml.SafeLoader):
    """PyYAML's safe loader, reading Docker Compose's `!reset` tag as the value it carries."""


ComposeLoader.add_constructor("!reset", lambda loader, node: loader.construct_sequence(node))


def load(text: str) -> dict:
    return yaml.load(text, Loader=ComposeLoader)


LIVE = live(COMPOSE)
PROXY_LIVE = live(PROXY)
REQUIRED = "MOONIE_REDIRECT_PUBLIC_BASE_URL"
SECRETS = ("store_key", "password", "api_token")


def recipe(name: str) -> list[str]:
    """A justfile recipe: its header line, then its body's lines, stripped."""
    lines = (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(rf"{re.escape(name)}( [^:=]*)?:(?!=)", line))
    body = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.startswith("    "):
            break
        body.append(line.strip())
    return body


def test_compose_builds_the_image_from_the_repository():
    assert "    build: .\n    image: ${MOONIE_REDIRECT_IMAGE:-moonie-redirect:local}\n" in LIVE + "\n"
    assert (ROOT / "Dockerfile").is_file()


def test_every_variable_has_a_default_but_the_public_address():
    references = re.findall(r"\$\{([A-Z0-9_]+)(:-|:\?|-|\?)?[^}]*\}", LIVE)
    assert references
    for name, operator in references:
        if name == REQUIRED:
            assert operator == ":?", name
        else:
            assert operator == ":-", f"{name} has no default: plain docker compose would need just to set it"


def test_no_variable_is_one_only_just_sets():
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")
    exported = set(re.findall(r"^export\s+([A-Za-z_][A-Za-z0-9_]*)", justfile, re.MULTILINE))
    assert "set export" not in justfile
    for name in re.findall(r"\$\{([A-Z0-9_]+)", LIVE):
        assert name not in exported


def test_the_secret_files_live_in_a_folder_the_host_can_choose():
    for name in SECRETS:
        assert f"  {name}:\n    file: ${{MOONIE_REDIRECT_SECRETS_DIR:-./secrets}}/{name}\n" in LIVE + "\n"
    assert "MOONIE_REDIRECT_SECRETS_DIR" in (ROOT / ".env.example").read_text(encoding="utf-8")


def test_lan_mode_publishes_the_port_and_needs_no_network():
    data = load(LIVE)
    service = data["services"]["moonie"]
    assert service["ports"] == ["${MOONIE_REDIRECT_BIND:-0.0.0.0}:${MOONIE_REDIRECT_PORT:-8080}:8080"]
    # The stack's default network only: nothing to create before `docker compose up`
    assert "networks" not in service
    assert "networks" not in data
    assert "labels" not in service
    assert "external" not in LIVE


def test_the_proxy_overlay_drops_the_port_and_joins_the_external_network():
    data = load(PROXY_LIVE)
    service = data["services"]["moonie"]
    # `!reset` drops the base file's ports when the files are merged, not just adds to them
    assert re.search(r"^    ports: !reset \[\]$", PROXY_LIVE, re.MULTILINE)
    assert service["networks"] == {"proxy": {"aliases": ["moonie-redirect"]}}
    assert data["networks"] == {"proxy": {"external": True, "name": "${MOONIE_REDIRECT_PROXY_NETWORK:-proxy}"}}
    labels = service["labels"]
    assert labels["traefik.enable"] == "true"
    assert labels["traefik.docker.network"] == "${MOONIE_REDIRECT_PROXY_NETWORK:-proxy}"
    assert labels["traefik.http.routers.moonie-redirect.rule"].startswith("Host(`${MOONIE_REDIRECT_HOST:?")
    assert labels["traefik.http.routers.moonie-redirect.entrypoints"] == "${MOONIE_REDIRECT_ENTRYPOINT:-websecure}"
    assert labels["traefik.http.services.moonie-redirect.loadbalancer.server.port"] == "8080"
    # An overlay only: the image, the secrets and the hardening stay in compose.yml
    assert set(service) == {"ports", "networks", "labels"}
    assert set(data) == {"services", "networks"}


def test_the_proxy_overlay_needs_only_the_proxys_host():
    for name, operator in re.findall(r"\$\{([A-Z0-9_]+)(:-|:\?|-|\?)?[^}]*\}", PROXY_LIVE):
        assert operator == (":?" if name == "MOONIE_REDIRECT_HOST" else ":-"), name


def test_the_env_example_names_every_variable_compose_reads():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in set(re.findall(r"\$\{([A-Z0-9_]+)", COMPOSE + PROXY)):
        assert re.search(rf"^#? ?{name}=", example, re.MULTILINE), name


def test_the_run_recipes_are_plain_docker_compose():
    assert recipe("run")[1:] == ["docker compose up -d --build"]
    assert recipe("run-proxy")[1:] == ["docker compose -f compose.yml -f compose.proxy.yml up -d --build"]


def test_the_compose_check_runs_in_ci_on_both_modes():
    assert "compose-check" in recipe("ci")[0].split(":", 1)[1].split()
    body = " ".join(recipe("compose-check")[1:])
    assert "docker compose --env-file .env.example config --quiet" in body
    assert "docker compose --env-file .env.example -f compose.yml -f compose.proxy.yml config --quiet" in body
    assert f"-e {REQUIRED}=http://192.0.2.10:8080" in body
    assert "-e MOONIE_REDIRECT_HOST=redirect.example.test" in body
    assert re.search(
        r'compose_image := "docker:[0-9.]+-cli@sha256:[0-9a-f]{64}"', (ROOT / "justfile").read_text(encoding="utf-8")
    )
