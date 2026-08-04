# Fedora Silverblue

Install the host GUI dependencies:

```text
sudo rpm-ostree install python3-gobject gtk4 libadwaita
```

Reboot after layering packages.

Bottles is expected as the Flatpak application
`com.usebottles.bottles`. The managed Bottles directory is discovered through
the core and displayed read-only. The GUI does not replace it with an arbitrary
path.

For source development, set `OGV_SOURCE_ROOT` to the core checkout containing
the `refactor/state-free-components` work until that branch is merged.
