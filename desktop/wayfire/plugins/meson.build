# tubewm's own Wayfire plugins. Built by build.sh against the installed
# Wayfire's headers; each plugin lands in ~/.local/share/wayfire/plugins with
# its metadata in ~/.local/share/wayfire/metadata, where Wayfire looks anyway.
project('tubewm-wayfire-plugins', 'cpp',
  version: '1',
  license: 'MIT',
  default_options: ['cpp_std=c++17', 'buildtype=release', 'warning_level=1'])

wayfire    = dependency('wayfire', version: '>=0.10.0')
# No wlroots here: Wayfire's own pkg-config file requires the wlroots it
# was built with (0.19 for Wayfire 0.10, 0.20 for 0.11), so it comes along.
wfconfig   = dependency('wf-config')
cairo      = dependency('cairo')
pango      = dependency('pango')
pangocairo = dependency('pangocairo')
pixman     = dependency('pixman-1')
libdrm     = dependency('libdrm')
wayland    = dependency('wayland-server')
# Wayfire's headers include glm, which distros ship as a separate -dev package.
glm        = dependency('glm', required: false)  # headers in /usr/include either way

add_project_arguments(['-DWLR_USE_UNSTABLE', '-DWAYFIRE_PLUGIN'], language: 'cpp')

plugin_deps = [wayfire, wfconfig, cairo, pango, pangocairo, pixman, libdrm, wayland, glm]

subdir('tube-decor')
subdir('tube-switch')
