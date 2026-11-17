#!/usr/bin/env bash
# Install Grimoire with one line (macOS and Linux):
#
#   curl -fsSL https://raw.githubusercontent.com/Windynik/grimoire/main/install.sh | bash
#
# The script puts the app in ~/grimoire, sets it up (./grimoire --setup), and
# adds a "grimoire" command in ~/.local/bin. Run the same line again to update:
# the update keeps your card data, collections and decks (.scryfall_cache).
#
# Options (after "bash -s --" when you pipe the script):
#   --with-mcp   also install the MCP server for AI assistants
#   --start      start Grimoire when the install is done
#   --no-setup   fetch the app and add the command only (no Python setup)
#
# GRIMOIRE_HOME sets the app folder, GRIMOIRE_BIN the command folder.
set -euo pipefail

REPO_URL="${GRIMOIRE_REPO:-https://github.com/Windynik/grimoire.git}"
BRANCH="${GRIMOIRE_BRANCH:-main}"
TARBALL_URL="${GRIMOIRE_TARBALL:-https://github.com/Windynik/grimoire/archive/refs/heads/${BRANCH}.tar.gz}"
APP_DIR="${GRIMOIRE_HOME:-$HOME/grimoire}"
BIN_DIR="${GRIMOIRE_BIN:-$HOME/.local/bin}"
USE_GIT="${GRIMOIRE_USE_GIT:-1}"
MARKER=".grimoire-install"

SETUP=1
START=0
SETUP_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --with-mcp) SETUP_ARGS+=("--with-mcp") ;;
    --start) START=1 ;;
    --no-setup) SETUP=0 ;;
    -h|--help) sed -n '2,17p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (options: --with-mcp, --start, --no-setup)" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1;33m›\033[0m %s\n' "$*"; }
fail() { printf 'Grimoire install: %s\n' "$*" >&2; exit 1; }

# A folder this script may write into: missing, empty, or an earlier install.
check_target() {
  [ -e "$APP_DIR" ] || return 0
  [ -d "$APP_DIR" ] || fail "$APP_DIR is a file, not a folder."
  [ -z "$(ls -A "$APP_DIR")" ] && return 0
  [ -d "$APP_DIR/.git" ] || [ -f "$APP_DIR/$MARKER" ] && return 0
  fail "$APP_DIR is not a Grimoire install and is not empty. Set GRIMOIRE_HOME to another folder."
}

fetch_with_git() {
  if [ -d "$APP_DIR/.git" ]; then
    say "Updating Grimoire in $APP_DIR…"
    git -C "$APP_DIR" pull --ff-only --quiet origin "$BRANCH"
  else
    say "Downloading Grimoire into $APP_DIR…"
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --quiet --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  fi
}

# Without git: unpack the tarball, then copy it over the app folder. The copy
# replaces the app's files and leaves everything else (the data, .venv) alone.
fetch_with_tarball() {
  if [ -f "$APP_DIR/$MARKER" ]; then say "Updating Grimoire in $APP_DIR…"
  else say "Downloading Grimoire into $APP_DIR…"
  fi
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT
  curl -fsSL "$TARBALL_URL" -o "$TMP_DIR/grimoire.tar.gz"
  mkdir -p "$TMP_DIR/src"
  tar -xzf "$TMP_DIR/grimoire.tar.gz" -C "$TMP_DIR/src" --strip-components 1
  mkdir -p "$APP_DIR"
  cp -R "$TMP_DIR/src/." "$APP_DIR/"
  touch "$APP_DIR/$MARKER"
}

check_target
if [ "$USE_GIT" = 1 ] && command -v git >/dev/null 2>&1; then
  fetch_with_git
else
  command -v curl >/dev/null 2>&1 || fail "the install needs git or curl."
  fetch_with_tarball
fi
chmod +x "$APP_DIR/grimoire"

if [ "$SETUP" = 1 ]; then
  "$APP_DIR/grimoire" --setup "${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"}"
fi

# The "grimoire" command: a small script that runs the app's launcher.
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/grimoire" <<EOF
#!/usr/bin/env bash
# Made by the Grimoire installer. It runs the app in $APP_DIR.
exec "$APP_DIR/grimoire" "\$@"
EOF
chmod +x "$BIN_DIR/grimoire"

say "Grimoire is installed in $APP_DIR."
case ":$PATH:" in
  *":$BIN_DIR:"*) say "Start it with: grimoire" ;;
  *)
    say "Start it with: $BIN_DIR/grimoire"
    say "To type just \"grimoire\", add this line to your ~/.zshrc (or ~/.bashrc):"
    echo "    export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac
say "To update later, run the install line again. Your collections and decks stay."

if [ "$START" = 1 ]; then
  exec "$APP_DIR/grimoire"
fi
