# CI checks

These scripts run in GitHub Actions on a fresh `archlinux:latest` container
(see `.github/workflows/ci.yml`), so they use the same current packages a
CachyOS or Arch user gets. They also run weekly, so an upstream release that
starts rejecting one of our configs fails here before it fails on a laptop.

| Script | What it checks |
|---|---|
| `lint.sh` | shellcheck on every shell script, pyflakes on every Python file, every JSON / JSONC / TOML file parses |
| `check-desktop.sh` | runs `desktop/install.sh` into a throwaway home, then asks the real tools about every config it wrote: `foot --check-config`, `sway -C`, `fuzzel --check-config`, swaylock keys against `swaylock --help`, GTK 3 / GTK 4's own CSS parser for waybar, GTK, gtklock and the shell. Repeats after `tube-accent lime`, then uninstalls. |
| `check-apps.sh` | runs `apps/install.sh` into a throwaway home, parses every JSON / TOML it wrote, and loads the themes in tmux, Neovim, mpv, kitty and Helix |
| `check-plugins.sh` | builds `desktop/wayfire/plugins` with `build.sh` against the installed Wayfire (its own CI job installs Arch's current `wayfire`), checks each plugin is installed and exports `newInstance`, that a second run is a no-op, and tries to load it in a headless Wayfire (only a warning when there's no GPU to start one) |
| `smoke-session.sh` | starts headless sway the way a display manager does (clean environment, `PATH` without `~/.local/bin`), checks waybar, mako and swayidle stay up, that every program the sway and waybar configs run is findable from inside the session, that start, charms and foot open, that changing the accent from the session works, and that the session log has no config errors or tracebacks |
| `run-all.sh` | all of the above plus `pytest apps/tests` |

## Running them yourself

In a container with the same packages as CI (needs docker or podman):

```sh
tests/ci/in-arch.sh                     # everything
tests/ci/in-arch.sh smoke-session.sh    # one check
```

Or directly on an Arch machine, after `sudo tests/ci/arch-deps.sh`. Nothing
touches your own home: every check works in a temporary one and removes it.
When run as root, the checks create and use a `tubewm-ci` user, because sway
doesn't run as root.

`TUBEWM_CI_PATH` overrides the minimal session `PATH`
(`/usr/local/sbin:/usr/local/bin:/usr/bin`), and `SMOKE_SETTLE` how many
seconds the session gets to settle before it is checked.
