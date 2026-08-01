# Fedora Silverblue

Install GTK4/libadwaita Python bindings and Bubblewrap through the host. Keep
the core and GUI source checkouts outside Flatpak sandboxes unless explicitly
testing a packaged application.

For a source checkout, set `OGV_SOURCE_ROOT` when the core is not installed as
`ogv`. Configure `OGV_COLLECTION_ROOT` only when collection auto-discovery is
not appropriate.

Bottles remains a separate Flatpak integration and requires
the directory reported by `bottles-cli info bottles-path`.
