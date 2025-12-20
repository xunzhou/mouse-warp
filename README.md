# mouse-warp

Screen edge wrapping and monitor switching for X11.

## Features

- Edge wrapping with optional resistance (time/distance/velocity modes)
- Shift + mouse: jump between monitors
- Ctrl + mouse: accelerated cursor movement
- Visual feedback with colors (auto dark/light)

## Install

```bash
make install enable start
```

## Commands

```
make start|stop|restart|status
make reload-config
make uninstall
```

## Config

`~/.config/mouse-warp/config.toml`
