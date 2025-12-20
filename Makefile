PREFIX = $(HOME)/.local
SYSTEMD_USER_DIR = $(HOME)/.config/systemd/user
CONFIG_DIR = $(HOME)/.config/mouse-warp
VENV_DIR = $(PREFIX)/lib/mouse-warp/venv

.PHONY: install uninstall enable disable start stop restart status reload-config import-env

install:
	python3 -m venv $(VENV_DIR)
	$(VENV_DIR)/bin/pip install -r requirements.txt
	install -Dm755 mouse-warp.py $(PREFIX)/bin/mouse-warp.py
	install -Dm644 mouse-warp.service $(SYSTEMD_USER_DIR)/mouse-warp.service
	sed -i 's|@VENV_PYTHON@|$(VENV_DIR)/bin/python|' $(SYSTEMD_USER_DIR)/mouse-warp.service
	sed -i 's|@SCRIPT_PATH@|$(PREFIX)/bin/mouse-warp.py|' $(SYSTEMD_USER_DIR)/mouse-warp.service
	@mkdir -p $(CONFIG_DIR)
	@test -f $(CONFIG_DIR)/config.toml || install -Dm644 config.toml $(CONFIG_DIR)/config.toml
	systemctl --user daemon-reload
	@echo ""
	@echo "NOTE: For reliable startup at boot, add to ~/.xinitrc or ~/.xprofile:"
	@echo "  systemctl --user import-environment DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS"
	@echo "Or run 'make import-env' in your current session."

import-env:
	systemctl --user import-environment DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS
	@echo "Environment imported. You can now 'make start' or 'make enable'."

uninstall:
	-systemctl --user stop mouse-warp.service
	-systemctl --user disable mouse-warp.service
	rm -f $(PREFIX)/bin/mouse-warp.py $(SYSTEMD_USER_DIR)/mouse-warp.service
	rm -rf $(PREFIX)/lib/mouse-warp
	systemctl --user daemon-reload

enable:
	systemctl --user enable --now mouse-warp.service

disable:
	systemctl --user disable --now mouse-warp.service

start:
	systemctl --user start mouse-warp.service

stop:
	systemctl --user stop mouse-warp.service

restart:
	systemctl --user restart mouse-warp.service

status:
	systemctl --user status mouse-warp.service

reload-config:
	pkill -HUP -f mouse-warp.py
