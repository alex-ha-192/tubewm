# tubewm Metro for bat

```sh
apps/install.sh --only bat              # or just apps/install.sh for every app found
apps/install.sh --only bat --accent cobalt --light
apps/install.sh --only bat --uninstall
```

Writes `themes/tubewm.tmTheme` into bat's config folder (`bat --config-dir`, `batcat` on Debian and Ubuntu), runs `bat cache --build`, and adds `--theme="tubewm"` to bat's `config` if it sets no theme.

The colours match the Neovim, Helix and VSCode themes: mostly white code, keywords in the accent, strings and comments in calm greys and greens. `delta` uses bat themes too, so `delta --syntax-theme tubewm` works.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
