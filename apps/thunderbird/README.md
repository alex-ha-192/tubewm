# Thunderbird

`apps/install.sh --only thunderbird` writes `chrome/tubewm-metro.css` into each
Thunderbird profile it finds (`~/.thunderbird` and the Flatpak's
`~/.var/app/org.mozilla.Thunderbird/.thunderbird`). It then puts an `@import` line at
the top of `chrome/userChrome.css` and turns on
`toolkit.legacyUserProfileCustomizations.stylesheets` in `user.js`.

What it does:

- black panes and white text, with grey for the open-but-unfocused things;
- the open tab is white with an accent underline, and its close button is always visible;
- the selected folder and message keep readable text and get an accent bar on the left;
- unread counts are in the accent colour, and the Write button is solid accent;
- square corners everywhere, no shadows.

Restart Thunderbird after installing. `apps/install.sh --uninstall --only thunderbird`
removes the import line, the pref line and the stylesheet.

Thunderbird renames its internals now and then. Every rule here is cosmetic, so a
rename only means that rule stops applying.
