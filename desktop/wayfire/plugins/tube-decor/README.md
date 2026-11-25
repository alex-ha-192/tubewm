# tube-decor

Wayfire's own `decoration` plugin (MIT) with Metro title bars: a flat bar,
the title on the left at 15px, and square buttons the full height of the
bar. The close X fills red on hover. Options live in `[tube-decor]` and
match `[decoration]`'s.

Wayfire's plugin API changes with each release, so there is one copy per
Wayfire series, each with the same changes; `meson.build` picks the copy for
the installed Wayfire, and the newest copy for anything newer:

- `wf0.10/`: Wayfire 0.10 (wlroots 0.19)
- `wf0.11/`: Wayfire 0.11 (wlroots 0.20)

Changed from upstream in each copy: `deco-theme.cpp` (title and button
drawing), `deco-layout.cpp` and `deco-button.*` (button size), the option
section name, and `tube-decor.xml`. See `LICENSE` for the upstream notice.
For a new Wayfire series, copy its `plugins/decor` and
`metadata/decoration.xml` into `wfX.Y/` and make the same changes.
