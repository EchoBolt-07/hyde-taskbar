# HyDE Custom Taskbar

A premium, custom-designed glassmorphic taskbar and start menu launcher built specifically for **HyDE (Hyprland Community Edition)**. It features smooth auto-hiding animations, application pinning, standard window state tracking, and a built-in Customizer GUI.

---

## ✨ Features

- **Self-Daemonizing**: Automatically forks and detaches from the terminal on startup. Closing the terminal will not close the taskbar. (To run in the foreground for debugging, use the `--foreground` flag).
- **Start on Boot Toggle**: Enable or disable taskbar autostart on system boot directly from the Settings GUI (automatically updates your Hyprland `userprefs.conf`).
- **Smooth Auto-Hide**: Fully retractable bar that slides out of sight and reveals on hover, with a customizable, dialable delay.
- **Start Menu Pinning**: Right-click any application in the Start Menu to launch it, or pin/unpin it directly from the taskbar without running it first.
- **Visual Corner-Clipping**: Correctly handles transparent window visuals so that rounded corners render cleanly with no rectangular gray outlines.
- **Wallbash Integration**: Automatically tracks and compiles Wallbash theme color schemas in real time.
- **Custom Start Menu Icon**: Automatically scales and displays a custom Arch Linux start icon (supports PNG and SVG).
- **Settings Customizer GUI**: A dedicated settings panel styled with a premium dark glassmorphic theme to adjust:
  - Start on Boot (Autostart toggle)
  - Edge position (Top/Bottom)
  - Edge offsets and padding (px)
  - Alignment (Start/Center/End)
  - Border radius & Icon size (px)
  - Auto-hide delay (ms)
  - Theme styles (Glassmorphic, Neon Glow, Solid Color, Cyberpunk Outline, Standard GTK)

---

## 📦 System Dependencies

Before running the installer, ensure the following packages are installed on your Linux distribution:

### Arch Linux
```bash
sudo pacman -S gtk3 gtk-layer-shell python-gobject
```

### Fedora
```bash
sudo dnf install gtk3 gtk-layer-shell pygobject3
```

### Debian / Ubuntu
```bash
sudo apt install libgtk-3-dev libgtk-layer-shell-dev python3-gi
```

---

## 🚀 Installation

### 1. Clone the Repository
Clone this repository to your local machine:
```bash
git clone https://github.com/EchoBolt-07/hyde-taskbar.git
cd hyde-taskbar
```

### 2. Run the Installer
Make the installer executable and run it:
```bash
chmod +x install.sh
./install.sh
```

The installer will:
1. Validate that all system dependencies are installed.
2. Copy the taskbar script, default config files, and the Arch logo to `~/.config/hyde/taskbar/`.
3. Copy the Wallbash config files to `~/.config/hyde/wallbash/always/`.
4. Append the startup and blur rules to your `~/.config/hypr/userprefs.conf`.
5. Kill any active taskbar process and start the new taskbar.

---

## 🗑️ Uninstallation

If you wish to remove the custom taskbar and clean up all configuration adjustments, run the uninstaller script:

```bash
chmod +x uninstall.sh
./uninstall.sh
```

The uninstaller will:
1. Stop the running taskbar background process.
2. Delete the configuration files, Arch logo, and template assets located under `~/.config/hyde/taskbar/`.
3. Remove the Wallbash configuration from `~/.config/hyde/wallbash/always/`.
4. Safely clean up all startup triggers and window layerrules from `~/.config/hypr/userprefs.conf`.

---

## 🎨 Customizing the Start Menu Logo
If you want to use a custom image (e.g. a custom Arch logo or any other distro brand) for the start menu button:
1. Place a `.png` file named `arch_logo.png` into `~/.config/hyde/taskbar/`.
2. The taskbar will detect it on the next launch and scale it automatically based on your active `icon_size`.
3. If no PNG is found, it will automatically fall back to the vector Arch Linux SVG.
