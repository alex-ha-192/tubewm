# tubewm Metro for Helix

```sh
apps/install.sh --only helix              # or just apps/install.sh for every app found
apps/install.sh --only helix --accent cobalt --light
apps/install.sh --only helix --uninstall
```

Writes `~/.config/helix/themes/tubewm.toml`. If `config.toml` sets no theme, `theme = "tubewm"` is added at the top. If you already chose another theme it is left alone and the installer tells you. You can also switch any time with `:theme tubewm`.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
