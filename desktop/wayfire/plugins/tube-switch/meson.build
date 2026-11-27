# One copy for every Wayfire series: the switcher only uses API that 0.10
# and 0.11 share.
shared_module('tube-switch', ['tube-switch.cpp'],
  dependencies: plugin_deps,
  install: true,
  install_dir: get_option('libdir'))

install_data('tube-switch.xml', install_dir: get_option('datadir'))
