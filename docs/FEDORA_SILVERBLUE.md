# Fedora Atomic / Silverblue notes

The reference host is an immutable Fedora-family desktop.

## Development dependencies

Install GTK4, libadwaita, and Python bindings through the host or a development container. The project itself is installed in a Python virtual environment.

## Bottles

The supported Bottles installation is the Flatpak application. The GUI checks the preserved shared-backend contract and does not download missing runners.

## Filesystem considerations

Use a POSIX filesystem for materializations that contain Wine prefixes, symbolic links, executable bits, or names such as `dosdevices/c:` and `dosdevices/z:`. Do not deploy those trees directly on NTFS, FAT, or exFAT.
