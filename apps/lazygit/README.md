# tubewm Metro for lazygit

```sh
apps/install.sh --only lazygit              # or just apps/install.sh for every app found
apps/install.sh --only lazygit --accent cobalt --light
apps/install.sh --only lazygit --uninstall
```

lazygit has no include, so the installer adds the theme block to `~/.config/lazygit/config.yml` (a copy also goes in `tubewm.yml`). If your config already has a `gui:` section it changes nothing and tells you to copy the `theme:` block across, because two `gui:` sections would clash. `--uninstall` removes exactly the lines it added.

The focused panel has an accent border, the others a quiet grey one. The selected line is charcoal so its text stays readable, and nerd-font icons are off.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
