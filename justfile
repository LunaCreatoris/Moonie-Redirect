# moonie-redirect: every recipe runs in the pinned Python image, the same on macOS, Linux and Windows.

python_image := "python:3.13.18-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90"
image := "moonie-redirect:local"
in_python := "docker run --rm -v \"" + justfile_directory() + "\":/src -w /src -e PIP_ROOT_USER_ACTION=ignore -e PIP_DISABLE_PIP_VERSION_CHECK=1 " + python_image + " sh -c"
# The front's tests run under this Node, pinned by tag and digest (multi-platform index)
node_image := "node:22.21.1-slim@sha256:25b3eb23a00590b7499f2a2ce939322727fcce1b15fdd69754fcd09536a3ae2c"
# The goldens are captured in this Chromium, pinned by tag and digest, on one platform, linux/arm64
playwright_image := "mcr.microsoft.com/playwright/python:v1.52.0-noble@sha256:a1d2b48b65f41f34e5e1d7690f385f1376397b7208691cba359e4078edbf86cb"
platform := "linux/arm64"
in_browser := "docker run --rm --platform " + platform + " -v \"" + justfile_directory() + "\":/src -w /src -e PIP_ROOT_USER_ACTION=ignore -e PIP_DISABLE_PIP_VERSION_CHECK=1 -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/tmp/deps " + playwright_image + " sh -c"
# The app's packages and the harness's, then the harness: what every goldens recipe starts with
harness := "pip install -q --no-deps --target /tmp/deps -r requirements.txt -r tests/ui/requirements.txt && python tests/ui/screenshots.py"

# SiteLuna's guide checker, vendored byte for byte in tools/guide_check.py (D31), pins this Markdown
markdown_pin := "markdown==3.11.2"
# The words no guide may hold are private: read from the file GUIDE_CHECK_PRIVATE_WORDS_FILE names, else from the
# git-ignored .guide-check-private-words; without either the checker says that check did not run
private_words_file := env("GUIDE_CHECK_PRIVATE_WORDS_FILE", justfile_directory() / ".guide-check-private-words")
private_words_found := path_exists(private_words_file)
private_words_mount := if private_words_found == "true" { "-v \"" + absolute_path(private_words_file) + "\":/run/guide-check-private-words:ro" } else { "" }
private_words_option := if private_words_found == "true" { "--private-words /run/guide-check-private-words" } else { "" }

# List the recipes
default:
    @just --list

# Run the tests
test:
    {{in_python}} "pip install -q -r requirements-dev.txt && pytest"

# Lint and check the formatting
lint:
    {{in_python}} "pip install -q -r requirements-dev.txt && ruff check . && ruff format --check ."

# Format the code
format:
    {{in_python}} "pip install -q -r requirements-dev.txt && ruff format . && ruff check --fix ."

# Check the guide in wiki/guide against SiteLuna's format with its vendored checker, modifying nothing
guide-check:
    @docker run --rm -v "{{justfile_directory()}}":/src:ro {{private_words_mount}} -w /src -e PIP_ROOT_USER_ACTION=ignore -e PIP_DISABLE_PIP_VERSION_CHECK=1 -e PYTHONDONTWRITEBYTECODE=1 {{python_image}} sh -c "pip install -q {{markdown_pin}} && python tools/guide_check.py wiki/guide --repo Moonie-Redirect {{private_words_option}}"

# Run the tests of the front's logic (static/ui) under Node
test-js:
    docker run --rm -v "{{justfile_directory()}}":/src -w /src {{node_image}} sh -c "node --test tests/js/*.test.mjs"

# Capture the goldens into tests/goldens: every walk, or the ones named (frame links nanourls qrcodes address settings settings-cloudflare)
goldens *WALKS:
    {{in_browser}} "{{harness}} --out tests/goldens {{WALKS}}"

# Capture every golden afresh and fail if one byte differs from tests/goldens (new, missing or changed)
goldens-check:
    {{in_browser}} "{{harness}} --out /tmp/goldens && python tests/ui/compare.py tests/goldens /tmp/goldens"

# Capture every golden twice and fail if the two runs differ by one byte
goldens-stability:
    {{in_browser}} "{{harness}} --out /tmp/first && python tests/ui/screenshots.py --out /tmp/second && python tests/ui/compare.py /tmp/first /tmp/second"

# The merge gate, and the only CI (D33): lint, check the guide, test the app and the front, check the goldens
ci: lint guide-check test test-js goldens-check

# Build the image
build:
    docker build -t {{image}} .

# Run the stack from compose.yml with .env (builds the image first)
run: build
    docker compose up -d

# Re-pin requirements*.txt to the latest versions (needs uv on the host)
lock:
    uv pip compile --quiet --python-version 3.13 --no-annotate --no-header --upgrade requirements.in -o requirements.txt
    uv pip compile --quiet --python-version 3.13 --no-annotate --no-header --upgrade requirements-dev.in -o requirements-dev.txt

# Print a new store key (64 hex characters): just store-key > secrets/store_key
store-key:
    @{{in_python}} "python -c 'import secrets; print(secrets.token_hex(32))'"

# In the running stack, drop the password set in Settings and end every session: the password file counts again
reset-password:
    docker compose exec moonie python app.py reset-password

# Copy the links of a 7.0.1 database (stopped cleanly, copied out, readable by uid 10001): just import-v7 path/to/moonie.db
import-v7 db:
    docker compose run --rm --no-deps -v "{{absolute_path(db)}}:/import/moonie.db:ro" moonie python app.py import-v7 /import/moonie.db
