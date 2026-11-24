# tubewm Metro for Neovim

```sh
apps/install.sh --only neovim              # or just apps/install.sh for every app found
apps/install.sh --only neovim --accent cobalt --light
apps/install.sh --only neovim --uninstall
```

Writes the colorscheme to `~/.config/nvim/colors/tubewm.lua`. Your `init.lua` is never edited, so turn it on once:

```lua
vim.cmd.colorscheme("tubewm")
```

It covers the built-in groups, treesitter, LSP and diagnostics, gitsigns and telescope. Code is mostly monochrome with keywords in the accent, and the status line is black with the mode in the accent (`--status-bar accent` makes it solid accent). It needs `termguicolors`, which the scheme turns on.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
