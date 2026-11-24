#!/usr/bin/env python3
"""Generate the tubewm VSCode extension (dark + light colour themes).

    python3 apps/vscode/build.py [--accent NAME|#RRGGBB] [--out DIR]

With no --out the extension is written to apps/vscode/extension/ (ignored by
git). install.sh calls this with the user's accent, packs a .vsix and hands it
to the editor.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from xml.sax.saxutils import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
import palette as P  # noqa: E402
import tokens as T  # noqa: E402

VERSION = "0.1.0"
EXT_ID = "tubewm-metro"
PUBLISHER = "tubewm"
THEMES = {"dark": "tubewm Metro Dark", "light": "tubewm Metro Light"}
CLEAR = "#00000000"


def workbench(c: dict, mode: str) -> dict:
    a, on_a = c["accent"], P.on_color(c["accent"])
    bg, sh, sf, sa = c["bg"], c["shell"], c["surface"], c["surface_alt"]
    fg, sub, dim, br = c["fg"], c["fg_subtle"], c["fg_disabled"], c["border"]
    a_text = P.readable(a, bg, 4.5)  # accent when used as text on the canvas
    sel = P.alpha(a, 0.40 if mode == "dark" else 0.25)
    sel_soft = P.alpha(a, 0.22 if mode == "dark" else 0.14)
    hover = sa
    return {
        # --- global -----------------------------------------------------
        "foreground": fg,
        "descriptionForeground": sub,
        "disabledForeground": dim,
        "errorForeground": c["error"],
        "focusBorder": a,
        "contrastBorder": CLEAR,
        "contrastActiveBorder": CLEAR,
        "selection.background": sel,
        "widget.shadow": CLEAR,
        "widget.border": br,
        "scrollbar.shadow": CLEAR,
        "sash.hoverBorder": a,
        "icon.foreground": fg,
        "textLink.foreground": a_text,
        "textLink.activeForeground": fg,
        "textPreformat.foreground": fg,
        "textBlockQuote.background": sf,
        "textBlockQuote.border": a,
        "textCodeBlock.background": sf,
        "progressBar.background": a,
        "badge.background": a,
        "badge.foreground": on_a,
        # --- window -----------------------------------------------------
        "titleBar.activeBackground": sh,
        "titleBar.activeForeground": fg,
        "titleBar.inactiveBackground": sh,
        "titleBar.inactiveForeground": sub,
        "titleBar.border": CLEAR,
        "menubar.selectionBackground": hover,
        "menubar.selectionForeground": fg,
        "menu.background": sf,
        "menu.foreground": fg,
        "menu.selectionBackground": a,
        "menu.selectionForeground": on_a,
        "menu.separatorBackground": br,
        "menu.border": CLEAR,
        "commandCenter.background": sf,
        "commandCenter.foreground": sub,
        "commandCenter.activeBackground": hover,
        "commandCenter.border": CLEAR,
        # --- activity bar: a quiet charcoal rail; the accent marks the active pivot
        "activityBar.background": sh,
        "activityBar.foreground": fg,
        "activityBar.inactiveForeground": sub,
        "activityBar.activeBorder": a,
        "activityBar.activeBackground": CLEAR,
        "activityBar.border": CLEAR,
        "activityBarBadge.background": a,
        "activityBarBadge.foreground": on_a,
        "activityBarTop.foreground": fg,
        "activityBarTop.inactiveForeground": sub,
        "activityBarTop.activeBorder": a,
        # --- side bar -----------------------------------------------------
        "sideBar.background": sh,
        "sideBar.foreground": fg,
        "sideBar.border": CLEAR,
        "sideBarTitle.foreground": fg,
        "sideBarSectionHeader.background": sh,
        "sideBarSectionHeader.foreground": fg,
        "sideBarSectionHeader.border": CLEAR,
        "list.activeSelectionBackground": a,
        "list.activeSelectionForeground": on_a,
        "list.activeSelectionIconForeground": on_a,
        "list.inactiveSelectionBackground": hover,
        "list.inactiveSelectionForeground": fg,
        "list.hoverBackground": hover,
        "list.hoverForeground": fg,
        "list.focusOutline": a,
        "list.focusBackground": CLEAR,
        "list.highlightForeground": a_text,
        "list.focusHighlightForeground": on_a,
        "list.dropBackground": sel_soft,
        "list.errorForeground": c["error"],
        "list.warningForeground": c["warning"],
        "tree.indentGuidesStroke": br,
        "tree.inactiveIndentGuidesStroke": CLEAR,
        # --- editor groups & tabs: pivot headers, no boxes ------------------
        "editorGroup.border": sh,
        "editorGroup.dropBackground": sel_soft,
        "editorGroupHeader.tabsBackground": bg,
        "editorGroupHeader.tabsBorder": CLEAR,
        "editorGroupHeader.noTabsBackground": bg,
        "tab.activeBackground": bg,
        "tab.activeForeground": fg,
        "tab.activeBorder": CLEAR,
        "tab.activeBorderTop": CLEAR,
        "tab.unfocusedActiveBorderTop": CLEAR,
        "tab.inactiveBackground": bg,
        "tab.inactiveForeground": sub,
        "tab.unfocusedActiveForeground": sub,
        "tab.unfocusedInactiveForeground": sub,
        "tab.hoverBackground": bg,
        "tab.hoverForeground": fg,
        "tab.border": CLEAR,
        "tab.lastPinnedBorder": br,
        "tab.activeModifiedBorder": a,
        "tab.inactiveModifiedBorder": sub,
        "breadcrumb.foreground": sub,
        "breadcrumb.focusForeground": fg,
        "breadcrumb.activeSelectionForeground": a_text,
        "breadcrumb.background": bg,
        "breadcrumbPicker.background": sf,
        # --- editor -----------------------------------------------------
        "editor.background": bg,
        "editor.foreground": fg,
        "editorLineNumber.foreground": dim,
        "editorLineNumber.activeForeground": fg,
        "editorCursor.foreground": a,
        "editorCursor.background": on_a,
        "editor.selectionBackground": sel,
        "editor.inactiveSelectionBackground": sel_soft,
        "editor.selectionHighlightBackground": sel_soft,
        "editor.wordHighlightBackground": P.alpha(fg, 0.10),
        "editor.wordHighlightStrongBackground": P.alpha(fg, 0.16),
        "editor.findMatchBackground": P.alpha(a, 0.65),
        "editor.findMatchBorder": a,
        "editor.findMatchHighlightBackground": sel_soft,
        "editor.lineHighlightBackground": P.alpha(fg, 0.04),
        "editor.lineHighlightBorder": CLEAR,
        "editor.rangeHighlightBackground": P.alpha(fg, 0.06),
        "editorWhitespace.foreground": P.alpha(fg, 0.15),
        "editorIndentGuide.background1": P.alpha(fg, 0.08),
        "editorIndentGuide.activeBackground1": P.alpha(fg, 0.25),
        "editorRuler.foreground": P.alpha(fg, 0.08),
        "editorBracketMatch.background": sel_soft,
        "editorBracketMatch.border": CLEAR,
        "editorBracketHighlight.foreground1": fg,
        "editorBracketHighlight.foreground2": sub,
        "editorBracketHighlight.foreground3": a_text,
        "editorBracketHighlight.unexpectedBracket.foreground": c["error"],
        "editorCodeLens.foreground": dim,
        "editorLink.activeForeground": a_text,
        "editorError.foreground": c["error"],
        "editorWarning.foreground": c["warning"],
        "editorInfo.foreground": c["info"],
        "editorGutter.background": bg,
        "editorGutter.modifiedBackground": c["info"],
        "editorGutter.addedBackground": c["success"],
        "editorGutter.deletedBackground": c["error"],
        "editorOverviewRuler.border": CLEAR,
        "editorStickyScroll.background": bg,
        "editorStickyScrollHover.background": hover,
        "editorStickyScroll.shadow": CLEAR,
        # --- widgets: flat charcoal panels, accent focus line ---------------
        "editorWidget.background": sf,
        "editorWidget.foreground": fg,
        "editorWidget.border": CLEAR,
        "editorSuggestWidget.background": sf,
        "editorSuggestWidget.border": CLEAR,
        "editorSuggestWidget.foreground": fg,
        "editorSuggestWidget.selectedBackground": a,
        "editorSuggestWidget.selectedForeground": on_a,
        "editorSuggestWidget.highlightForeground": a_text,
        "editorSuggestWidget.focusHighlightForeground": on_a,
        "editorHoverWidget.background": sf,
        "editorHoverWidget.border": CLEAR,
        "quickInput.background": sf,
        "quickInput.foreground": fg,
        "quickInputTitle.background": sf,
        "quickInputList.focusBackground": a,
        "quickInputList.focusForeground": on_a,
        "quickInputList.focusIconForeground": on_a,
        "pickerGroup.foreground": a_text,
        "pickerGroup.border": br,
        "peekView.border": a,
        "peekViewTitle.background": sf,
        "peekViewEditor.background": sh,
        "peekViewResult.background": sf,
        "peekViewResult.selectionBackground": a,
        "peekViewResult.selectionForeground": on_a,
        "notifications.background": sf,
        "notifications.foreground": fg,
        "notifications.border": CLEAR,
        "notificationCenterHeader.background": sf,
        "notificationToast.border": a,
        "notificationsInfoIcon.foreground": c["info"],
        "notificationsWarningIcon.foreground": c["warning"],
        "notificationsErrorIcon.foreground": c["error"],
        # --- inputs & buttons: rectangles with a 2px-feeling border ---------
        "input.background": bg if mode == "dark" else "#FFFFFF",
        "input.foreground": fg,
        "input.border": sub,
        "input.placeholderForeground": dim,
        "inputOption.activeBackground": a,
        "inputOption.activeForeground": on_a,
        "inputOption.activeBorder": CLEAR,
        "inputValidation.errorBackground": sf,
        "inputValidation.errorBorder": c["error"],
        "inputValidation.warningBackground": sf,
        "inputValidation.warningBorder": c["warning"],
        "inputValidation.infoBackground": sf,
        "inputValidation.infoBorder": c["info"],
        "dropdown.background": sf,
        "dropdown.listBackground": sf,
        "dropdown.foreground": fg,
        "dropdown.border": sub,
        "button.background": a,
        "button.foreground": on_a,
        "button.hoverBackground": P.mix(a, "#FFFFFF" if mode == "dark" else "#000000", 0.15),
        "button.border": CLEAR,
        "button.separator": P.alpha(on_a, 0.4),
        "button.secondaryBackground": sa,
        "button.secondaryForeground": fg,
        "button.secondaryHoverBackground": P.mix(sa, fg, 0.12),
        "checkbox.background": bg,
        "checkbox.foreground": fg,
        "checkbox.border": fg,
        "toolbar.hoverBackground": hover,
        "keybindingLabel.background": sa,
        "keybindingLabel.foreground": fg,
        "keybindingLabel.border": CLEAR,
        "keybindingLabel.bottomBorder": CLEAR,
        "scrollbarSlider.background": P.alpha(fg, 0.15),
        "scrollbarSlider.hoverBackground": P.alpha(fg, 0.28),
        "scrollbarSlider.activeBackground": a,
        "minimap.background": bg,
        "minimapSlider.background": P.alpha(fg, 0.08),
        # --- panel (terminal, problems) -------------------------------------
        "panel.background": bg,
        "panel.border": sh,
        "panelTitle.activeForeground": fg,
        "panelTitle.inactiveForeground": sub,
        "panelTitle.activeBorder": a,
        "panelSection.border": sh,
        "panelInput.border": sub,
        "terminal.background": bg,
        "terminal.foreground": fg,
        "terminalCursor.foreground": a,
        "terminal.selectionBackground": sel,
        "terminal.border": sh,
        **terminal_ansi(c, mode),
        # --- status bar: the accent strip --------------------------------
        "statusBar.background": a,
        "statusBar.foreground": on_a,
        "statusBar.border": CLEAR,
        "statusBar.noFolderBackground": a,
        "statusBar.noFolderForeground": on_a,
        "statusBar.debuggingBackground": c["warning"],
        "statusBar.debuggingForeground": P.on_color(c["warning"]),
        "statusBar.focusBorder": on_a,
        "statusBarItem.hoverBackground": P.alpha(on_a, 0.15),
        "statusBarItem.activeBackground": P.alpha(on_a, 0.25),
        "statusBarItem.remoteBackground": sh,
        "statusBarItem.remoteForeground": fg,
        "statusBarItem.prominentBackground": P.alpha("#000000", 0.25),
        "statusBarItem.errorBackground": c["error"],
        "statusBarItem.errorForeground": P.on_color(c["error"]),
        "statusBarItem.warningBackground": c["warning"],
        "statusBarItem.warningForeground": P.on_color(c["warning"]),
        # --- source control & diffs ------------------------------------------
        "gitDecoration.modifiedResourceForeground": P.readable(c["info"], sh, 4.5),
        "gitDecoration.untrackedResourceForeground": P.readable(c["success"], sh, 4.5),
        "gitDecoration.addedResourceForeground": P.readable(c["success"], sh, 4.5),
        "gitDecoration.deletedResourceForeground": P.readable(c["error"], sh, 4.5),
        "gitDecoration.conflictingResourceForeground": P.readable(c["warning"], sh, 4.5),
        "gitDecoration.ignoredResourceForeground": dim,
        "diffEditor.insertedTextBackground": P.alpha(c["success"], 0.18),
        "diffEditor.removedTextBackground": P.alpha(c["error"], 0.18),
        "diffEditor.insertedLineBackground": P.alpha(c["success"], 0.10),
        "diffEditor.removedLineBackground": P.alpha(c["error"], 0.10),
        "diffEditor.border": sh,
        # --- misc -------------------------------------------------------
        "welcomePage.tileBackground": a,
        "welcomePage.tileHoverBackground": P.mix(a, "#FFFFFF", 0.12),
        "welcomePage.progress.foreground": a,
        "walkThrough.embeddedEditorBackground": sh,
        "settings.headerForeground": fg,
        "settings.modifiedItemIndicator": a,
        "settings.focusedRowBackground": P.alpha(fg, 0.04),
        "settings.rowHoverBackground": P.alpha(fg, 0.03),
        "settings.focusedRowBorder": CLEAR,
        "debugToolBar.background": sf,
        "debugToolBar.border": CLEAR,
        "extensionButton.prominentBackground": a,
        "extensionButton.prominentForeground": on_a,
        "chat.requestBackground": sh,
    }


def terminal_ansi(c: dict, mode: str) -> dict:
    cols = T.ansi(c, mode)
    out = {}
    for i, name in enumerate(T.ANSI_NAMES):
        cap = name.capitalize()
        out[f"terminal.ansi{cap}"] = cols[i]
        out[f"terminal.ansiBright{cap}"] = cols[i + 8]
    return out


def syntax(c: dict, mode: str) -> tuple[list, dict]:
    """TextMate and semantic token rules built from the shared syntax colours."""
    s = T.syntax(c, mode)
    sw = dict(s, accent=s["keyword"])
    def rule(name, scope, color, style=None):
        s = {"foreground": color}
        if style is not None:
            s["fontStyle"] = style
        return {"name": name, "scope": scope, "settings": s}

    tokens = [
        rule("Comments", ["comment", "punctuation.definition.comment"], sw["comment"], "italic"),
        rule("Keywords", ["keyword", "storage", "storage.type", "keyword.control",
                          "keyword.operator.new", "keyword.operator.expression",
                          "keyword.operator.logical.python", "variable.language.this",
                          "variable.language.self", "variable.language.super"], sw["accent"], ""),
        rule("Operators", ["keyword.operator", "punctuation.separator.key-value"], sw["punct"], ""),
        rule("Strings", ["string", "string.quoted", "string.template", "markup.inline.raw"], sw["string"]),
        rule("Escapes and regex", ["constant.character.escape", "string.regexp",
                                   "constant.other.placeholder"], sw["escape"]),
        rule("Numbers and constants", ["constant.numeric", "constant.language", "constant.other",
                                       "support.constant", "variable.other.constant",
                                       "variable.other.enummember"], sw["number"]),
        rule("Functions", ["entity.name.function", "support.function", "meta.function-call",
                           "variable.function"], sw["func"], "bold"),
        rule("Types and classes", ["entity.name.type", "entity.name.class", "support.type",
                                   "support.class", "entity.other.inherited-class",
                                   "storage.type.primitive", "entity.name.namespace"], sw["type"], ""),
        rule("Variables", ["variable", "variable.parameter", "meta.definition.variable"], c["fg"]),
        rule("Properties", ["variable.other.property", "variable.other.object.property",
                            "support.variable.property", "meta.object-literal.key",
                            "support.type.property-name"], sw["prop"]),
        rule("Punctuation", ["punctuation", "meta.brace", "meta.delimiter"], sw["punct"]),
        rule("Tags", ["entity.name.tag", "punctuation.definition.tag"], sw["accent"]),
        rule("Attributes", ["entity.other.attribute-name"], sw["number"]),
        rule("Decorators", ["meta.decorator", "entity.name.function.decorator",
                            "punctuation.decorator"], sw["escape"]),
        rule("Markup headings", ["markup.heading", "entity.name.section"], c["fg"], "bold"),
        rule("Markup heading marks", ["punctuation.definition.heading"], sw["accent"]),
        rule("Markup bold", ["markup.bold"], c["fg"], "bold"),
        rule("Markup italic", ["markup.italic"], c["fg"], "italic"),
        rule("Markup links", ["markup.underline.link", "string.other.link"], sw["accent"]),
        rule("Markup quote", ["markup.quote"], sw["comment"], "italic"),
        rule("Diff inserted", ["markup.inserted"], sw["string"]),
        rule("Diff deleted", ["markup.deleted"], sw["error"]),
        rule("Diff changed", ["markup.changed"], sw["number"]),
        rule("Invalid", ["invalid", "invalid.illegal"], sw["error"]),
    ]
    semantic = {
        "keyword": sw["accent"],
        "function": {"foreground": sw["func"], "bold": True},
        "method": {"foreground": sw["func"], "bold": True},
        "class": sw["type"], "interface": sw["type"], "type": sw["type"], "enum": sw["type"],
        "struct": sw["type"], "typeParameter": sw["type"], "namespace": sw["type"],
        "enumMember": sw["number"],
        "variable.readonly": sw["number"],
        "property": sw["prop"],
        "parameter": c["fg"],
        "decorator": sw["escape"],
        "macro": sw["escape"],
        "string": sw["string"],
        "number": sw["number"],
        "comment": {"foreground": sw["comment"], "italic": True},
    }
    return tokens, semantic


def theme(mode: str, pal: dict) -> dict:
    c = P.polarity(pal, mode)
    tokens, semantic = syntax(c, mode)
    return {
        "$schema": "vscode://schemas/color-theme",
        "name": THEMES[mode],
        "type": mode,
        "semanticHighlighting": True,
        "colors": workbench(c, mode),
        "tokenColors": tokens,
        "semanticTokenColors": semantic,
    }


def package_json(accent: str) -> dict:
    return {
        "name": EXT_ID,
        "displayName": "tubewm Metro",
        "description": f"Flat, black, typographic colour themes from the tubewm desktop (accent {accent}).",
        "version": VERSION,
        "publisher": PUBLISHER,
        "license": "MIT",
        "engines": {"vscode": "^1.80.0"},
        "categories": ["Themes"],
        "contributes": {
            "themes": [
                {"label": THEMES["dark"], "uiTheme": "vs-dark", "path": "./themes/tubewm-metro-dark.json"},
                {"label": THEMES["light"], "uiTheme": "vs", "path": "./themes/tubewm-metro-light.json"},
            ]
        },
    }


def build(out: Path, accent: str | None = None) -> Path:
    pal = P.load(accent=accent)
    themes = out / "themes"
    themes.mkdir(parents=True, exist_ok=True)
    dump = lambda p, d: p.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    dump(out / "package.json", package_json(pal["TUBEWM_ACCENT"]))
    for mode in ("dark", "light"):
        dump(themes / f"tubewm-metro-{mode}.json", theme(mode, pal))
    (out / "README.md").write_text(
        "# tubewm Metro for VSCode\n\nGenerated by `apps/vscode/build.py` from the shared "
        "tubewm palette. Do not edit by hand; change `palette/` or the generator and rebuild.\n",
        encoding="utf-8",
    )
    return out


VSIX_MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{id}" Version="{version}" Publisher="{publisher}" />
    <DisplayName>{name}</DisplayName>
    <Description xml:space="preserve">{description}</Description>
    <Tags>theme,color-theme,metro,tubewm</Tags>
    <Categories>Themes</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{engine}" />
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code" />
  </Installation>
  <Dependencies />
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true" />
  </Assets>
</PackageManifest>
"""

CONTENT_TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension=".json" ContentType="application/json" /><Default Extension=".md" ContentType="text/markdown" /><Default Extension=".vsixmanifest" ContentType="text/xml" /></Types>
"""


def vsix(ext_dir: Path, dest: Path) -> Path:
    """Pack a built extension folder into a .vsix the editors' CLIs accept."""
    pkg = json.loads((ext_dir / "package.json").read_text(encoding="utf-8"))
    manifest = VSIX_MANIFEST.format(
        id=escape(pkg["name"]), version=escape(pkg["version"]), publisher=escape(pkg["publisher"]),
        name=escape(pkg["displayName"]), description=escape(pkg["description"]),
        engine=escape(pkg["engines"]["vscode"]),
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("extension.vsixmanifest", manifest)
        for f in sorted(ext_dir.rglob("*")):
            if f.is_file():
                z.write(f, "extension/" + f.relative_to(ext_dir).as_posix())
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--accent", help="accent name from palette/accents, or #RRGGBB")
    ap.add_argument("--out", type=Path, default=HERE / "extension")
    ap.add_argument("--vsix", type=Path, help="also pack the result into this .vsix file")
    args = ap.parse_args(argv)
    try:
        out = build(args.out, args.accent)
    except ValueError as e:
        print(f"build.py: {e}", file=sys.stderr)
        return 2
    print(vsix(out, args.vsix) if args.vsix else out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
