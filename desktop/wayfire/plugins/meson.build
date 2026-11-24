# tubewm's own Wayfire plugins. Built by build.sh against the installed
# Wayfire's headers; each plugin lands in ~/.local/share/wayfire/plugins with
# its metadata in ~/.local/share/wayfire/metadata, where Wayfire looks anyway.
project('tubewm-wayfire-plugins', 'cpp',
  version: '1',
  license: 'MIT',
  default_options: ['cpp_std=c++17', 'buildtype=release', 'warning_level=1'])

wayfire    = dependency('wayfire', version: '>=0.10.0')
wlroots    = dependency('wlroots-0.19')
wfconfig   = dependency('wf-config')
cairo      = dependency('cairo')
pango      = dependency('pango')
pangocairo = dependency('pangocairo')
pixman     = dependency('pixman-1')
libdrm     = dependency('libdrm')
wayland    = dependency('wayland-server')
glm        = dependency('glm', required: false)

add_project_arguments(['-DWLR_USE_UNSTABLE', '-DWAYFIRE_PLUGIN'], language: 'cpp')

plugin_deps = [wayfire, wlroots, wfconfig, cairo, pango, pangocairo, pixman, libdrm, wayland, glm]

subdir('tube-decor')
