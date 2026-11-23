#!/usr/bin/env bash
set -e

VENV_DIR=".venv"

detect_os() { case "$(uname -s)" in Linux*) OS="linux";; Darwin*) OS="macos";; MINGW*|MSYS*|CYGWIN*) OS="windows";; *) OS="unknown";; esac; echo "Detected OS: $OS"; }
find_python() { for cmd in python3.12 python3.11 python3 python; do if command -v "$cmd" &>/dev/null; then PYTHON="$cmd"; echo "Using: $PYTHON"; return 0; fi; done; exit 1; }

setup_venv() {
    [ -d "$VENV_DIR" ] && echo "Venv exists — reusing." || $PYTHON -m venv "$VENV_DIR"
    if [ "$OS" = "windows" ]; then source "$VENV_DIR/Scripts/activate"; else source "$VENV_DIR/bin/activate"; fi
    pip install --upgrade pip --quiet && pip install -e ".[dev]" --quiet
    echo "Dependencies installed."

    echo "Installing Playwright browsers..."
    playwright install chromium --with-deps 2>/dev/null || playwright install chromium
    echo "Chromium installed."
}

main() {
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║            Twinlane — Setup                            ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    detect_os; find_python; setup_venv
    echo ""
    echo "Ready. Usage:"
    echo "  twinlane --input data/sample_input.csv --output results/"
    echo "  twinlane --input data.csv --output results/ --vlm --excel"
    echo "  twinlane --input data.csv --output results/ --dry-run"
}

main "$@"
