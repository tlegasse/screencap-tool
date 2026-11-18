#!/bin/bash
# Usage: ./install.sh [--uninstall] [--yes]
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
yes=0
uninstall=0
for arg in "$@"; do
	case $arg in
	--yes | -y) yes=1 ;;
	--uninstall) uninstall=1 ;;
	-h | --help)
		sed -n '2p' "$0"
		exit 0
		;;
	*)
		echo "install.sh: unknown option $arg" >&2
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

if [ "$(uname)" = Darwin ]; then
	app_dir="$HOME/Library/Application Support/Clip/app"
	bundle="$HOME/Applications/Clip.app"
	log="$HOME/Library/Logs/Clip.log"
else
	app_dir="${XDG_DATA_HOME:-$HOME/.local/share}/clip/app"
	bundle=""
	desktop_file="${XDG_DATA_HOME:-$HOME/.local/share}/applications/clip.desktop"
fi
cli="$HOME/.local/bin/clip"

if [ "$uninstall" = 1 ]; then
	rm -rf "$app_dir"
	[ -n "$bundle" ] && rm -rf "$bundle"
	[ -n "${desktop_file:-}" ] && rm -f "$desktop_file"
	[ -L "$cli" ] && rm -f "$cli"
	echo "Removed Clip. Your settings (~/.config/clip) and exported clips are untouched."
	exit 0
fi

install_mac_deps() {
	local brew=""
	for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
		[ -x "$b" ] && brew=$b && break
	done
	if [ -z "$brew" ]; then
		say "Clip needs Homebrew (https://brew.sh), the usual way to install tools on a Mac."
		ask "Install Homebrew now? It asks for your Mac password." || {
			echo "Install Homebrew from https://brew.sh, then run this again."
			exit 1
		}
		/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
		for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
			[ -x "$b" ] && brew=$b && break
		done
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
}

check_linux_deps() {
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

copy_app() {
	say "Copying Clip to $app_dir"
	rm -rf "$app_dir"
	mkdir -p "$app_dir"
	cp -R "$here/clip" "$here/bin" "$app_dir/"
	find "$app_dir" -name __pycache__ -type d -prune -exec rm -rf {} +
	chmod +x "$app_dir/bin/clip"
	if [ "$(uname)" = Darwin ]; then
		xattr -dr com.apple.quarantine "$app_dir" 2>/dev/null || true
	fi
	mkdir -p "$(dirname "$cli")"
	ln -sf "$app_dir/bin/clip" "$cli"
}

applescript_string() {
	local s=${1//\\/\\\\}
	printf '"%s"' "${s//\"/\\\"}"
}

make_mac_app() {
	say "Making $bundle (double-click it, or drop videos on it)"
	local launcher logfile src
	launcher=$(applescript_string "$app_dir/bin/clip")
	logfile=$(applescript_string "$log")
	src="$(mktemp -d)/clip.applescript"
	cat >"$src" <<EOF
property launcher : $launcher
property logfile : $logfile

on run
	do shell script quoted form of launcher & " >> " & quoted form of logfile & " 2>&1 &"
end run

on open theFiles
	repeat with f in theFiles
		do shell script quoted form of launcher & " " & quoted form of (POSIX path of f) & " >> " & quoted form of logfile & " 2>&1 &"
	end repeat
end open
EOF
	mkdir -p "$(dirname "$bundle")" "$(dirname "$log")"
	rm -rf "$bundle"
	osacompile -o "$bundle" "$src"
	rm -rf "$(dirname "$src")"
}

make_linux_entry() {
	mkdir -p "$(dirname "$desktop_file")"
	cat >"$desktop_file" <<EOF
[Desktop Entry]
Type=Application
Name=Clip
Comment=Annotate a screen recording
Exec="$app_dir/bin/clip" %f
Icon=video-x-generic
MimeType=video/mp4;video/quicktime;video/webm;video/x-matroska;
Categories=AudioVideo;Video;
EOF
}

if [ "$(uname)" = Darwin ]; then
	install_mac_deps
	copy_app
	make_mac_app
else
	check_linux_deps
	copy_app
	make_linux_entry
fi

say "Checking..."
"$app_dir/bin/clip" --check

say "Done."
if [ -n "$bundle" ]; then
	echo "  Open Clip from ~/Applications (or drag it to the Dock and drop recordings on it)."
	echo "  Problems get logged to $log"
fi
case ":$PATH:" in
*":$HOME/.local/bin:"*) echo "  In a terminal: clip [VIDEO], clip --help" ;;
*) echo "  In a terminal: ~/.local/bin/clip [VIDEO] (add ~/.local/bin to your PATH to type just 'clip')" ;;
esac
echo "  Colours and fonts: clip --edit-config"
