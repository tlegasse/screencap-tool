#!/bin/bash
# Usage: ./setup.sh [--yes]
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
yes=0
for arg in "$@"; do
	case $arg in
	--yes | -y) yes=1 ;;
	-h | --help)
		sed -n '2p' "$0"
		exit 0
		;;
	*)
		echo "setup.sh: unknown option $arg" >&2
		exit 2
		;;
	esac
done

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

ask() {
	[ "$yes" = 1 ] && return 0
	local reply
	read -r -p "$1 [Y/n] " reply </dev/tty || return 1
	case $reply in [nN]*) return 1 ;; *) return 0 ;; esac
}

find_brew() {
	for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
		[ -x "$b" ] && echo "$b" && return
	done
}

setup_mac() {
	local brew
	brew=$(find_brew)
	if [ -z "$brew" ]; then
		say "Clip needs Homebrew (https://brew.sh), the usual way to install tools on a Mac."
		ask "Install Homebrew now? It asks for your Mac password." || {
			echo "Install Homebrew from https://brew.sh, then run this again."
			exit 1
		}
		/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
		brew=$(find_brew)
		[ -n "$brew" ] || {
			echo "Homebrew didn't install; see https://brew.sh" >&2
			exit 1
		}
	fi
	eval "$("$brew" shellenv)"
	say "Installing ffmpeg and GTK with Homebrew (the first time takes a few minutes)..."
	brew install ffmpeg gtk+3 pygobject3 adwaita-icon-theme
	say "Installing the Fira Sans font (optional; Helvetica Neue is used without it)..."
	brew install --cask font-fira-sans || echo "(skipped: Clip falls back to Helvetica Neue)"
	xattr -dr com.apple.quarantine "$here" 2>/dev/null || true
}

check_linux() {
	local missing=""
	command -v ffmpeg >/dev/null || missing="$missing ffmpeg"
	python3 -c 'import gi, cairo; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' \
		>/dev/null 2>&1 || missing="$missing PyGObject/GTK3/pycairo"
	if [ -n "$missing" ]; then
		echo "Missing:$missing. Install them with your package manager, e.g." >&2
		echo "  Debian/Ubuntu: sudo apt install ffmpeg python3-gi python3-gi-cairo gir1.2-gtk-3.0" >&2
		echo "  Fedora:        sudo dnf install ffmpeg python3-gobject gtk3" >&2
		echo "  Arch:          sudo pacman -S ffmpeg python-gobject python-cairo gtk3" >&2
		exit 1
	fi
}

if [ "$(uname)" = Darwin ]; then
	setup_mac
else
	check_linux
fi
chmod +x "$here/bin/clip" "$here"/*.command 2>/dev/null || true

config="${CLIP_CONFIG:-$HOME/.config/clip/config.toml}"
if [ -e "$config" ]; then
	say "Keeping your settings in $config"
else
	mkdir -p "$(dirname "$config")"
	cp "$here/clip/config.example.toml" "$config"
	say "Wrote the settings file $config (colours, fonts, export folder)"
fi

say "Checking..."
"$here/bin/clip" --check

say "Ready. Run Clip from this folder:"
echo "  $here/bin/clip [VIDEO]      (or double-click 'Open Clip.command')"
echo "  Colours and fonts: edit $config (or: $here/bin/clip --edit-config)"
