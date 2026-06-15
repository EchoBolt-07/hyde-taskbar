#!/usr/bin/env python3
import os
import sys

# Detach from terminal (daemonize) if not run in foreground/settings mode
if "--foreground" not in sys.argv and "--settings" not in sys.argv:
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        sys.exit(1)
        
    os.setsid()
    
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        sys.exit(1)

    # Redirect standard file descriptors
    si = open(os.devnull, 'r')
    so = open(os.devnull, 'a+')
    se = open(os.devnull, 'a+')
    os.dup2(si.fileno(), sys.stdin.fileno())
    os.dup2(so.fileno(), sys.stdout.fileno())
    os.dup2(se.fileno(), sys.stderr.fileno())
import json
import socket
import threading
import subprocess
import hashlib
from collections import defaultdict

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GLib, Gio, GObject, GtkLayerShell, GdkPixbuf

# Ensure the taskbar directories exist
CONFIG_DIR = os.path.expanduser("~/.config/hyde/taskbar")
os.makedirs(CONFIG_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(CONFIG_DIR, "taskbar.json")
CACHE_DIR = os.path.expanduser("~/.cache/hyde")
WALLBASH_CSS = os.path.join(CACHE_DIR, "wallbash/hyde-taskbar.css")

ARCH_SVG_DATA = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="28" height="28">
  <defs>
    <linearGradient id="grad" x1="0%" y1="100%" x2="0%" y2="0%">
      <stop offset="0%" stop-color="#1793d1"/>
      <stop offset="100%" stop-color="#33a6de"/>
    </linearGradient>
  </defs>
  <path d="M 50,12 C 47,17 20,68 15,75 C 23,78 35,80 50,80 C 65,80 77,78 85,75 C 80,68 53,17 50,12 Z" fill="url(#grad)" />
  <path d="M 50,25 C 48,29 30,68 26,74 C 33,76 42,77 50,77 C 58,77 67,76 74,74 C 70,68 52,29 50,25 Z" fill="#ffffff" opacity="0.3" />
  <path d="M 50,42 C 49,44 40,64 36,68 C 41,70 45,71 50,71 C 55,71 59,70 64,68 C 60,64 51,44 50,42 Z" fill="#0f3d5f" opacity="0.85" />
</svg>"""

def clean_exec_cmd(cmd):
    if not cmd:
        return ""
    # Split arguments and get base executable name
    exe = cmd.split()[0]
    return os.path.basename(exe).lower()

def get_icon_pixbuf(icon_name, size):
    if not icon_name:
        return get_fallback_pixbuf(size)
    
    # Check if absolute path
    if icon_name.startswith("/"):
        if os.path.exists(icon_name):
            try:
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_name, size, size, True)
            except Exception as e:
                print(f"Error loading icon path {icon_name}: {e}")
    
    # Strip extension (e.g., Firefox.png -> Firefox)
    base_icon_name = icon_name
    if "." in icon_name:
        name_part, ext = os.path.splitext(icon_name)
        if ext.lower() in [".png", ".svg", ".xpm", ".jpg", ".jpeg", ".gif"]:
            base_icon_name = name_part

    icon_theme = Gtk.IconTheme.get_default()
    
    # Check theme for stripped icon name
    if icon_theme.has_icon(base_icon_name):
        try:
            pixbuf = icon_theme.load_icon(base_icon_name, size, Gtk.IconLookupFlags.FORCE_SIZE)
            return pixbuf
        except Exception:
            pass
            
    # Check theme for original icon name
    if icon_theme.has_icon(icon_name):
        try:
            pixbuf = icon_theme.load_icon(icon_name, size, Gtk.IconLookupFlags.FORCE_SIZE)
            return pixbuf
        except Exception:
            pass

    # Try exact match of file name in standard icon paths if not found
    pixmap_path = f"/usr/share/pixmaps/{icon_name}"
    if os.path.exists(pixmap_path):
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(pixmap_path, size, size, True)
        except Exception:
            pass
            
    if "." not in icon_name:
        for ext in [".png", ".svg", ".xpm"]:
            p = f"/usr/share/pixmaps/{icon_name}{ext}"
            if os.path.exists(p):
                try:
                    return GdkPixbuf.Pixbuf.new_from_file_at_scale(p, size, size, True)
                except Exception:
                    pass

    return get_fallback_pixbuf(size)

def get_fallback_pixbuf(size):
    icon_theme = Gtk.IconTheme.get_default()
    for fallback in ["application-x-executable", "system-run", "unknown"]:
        if icon_theme.has_icon(fallback):
            try:
                return icon_theme.load_icon(fallback, size, Gtk.IconLookupFlags.FORCE_SIZE)
            except Exception:
                pass
    try:
        return GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, size, size)
    except Exception:
        return None

class ConfigManager:
    def __init__(self):
        self.config = {
            "pinned": [
                {"name": "Terminal", "exec": "kitty", "icon": "kitty"},
                {"name": "Files", "exec": "dolphin", "icon": "system-file-manager"},
                {"name": "Web Browser", "exec": "firefox", "icon": "firefox"},
                {"name": "VS Code", "exec": "code", "icon": "code"}
            ],
            "settings": {
                "position": "bottom",
                "alignment": "center",
                "icon_size": 40,
                "spacing": 8,
                "bar_padding": 6,
                "opacity": 0.4,
                "theme": "glassmorphic",
                "blur": True,
                "offset_y": 10,
                "offset_x": 0,
                "auto_hide": False,
                "auto_hide_delay": 500,
                "show_labels": False,
                "border_radius": 20,
                "show_active_only": False
            }
        }
        self.load()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    if "pinned" in data:
                        self.config["pinned"] = data["pinned"]
                    if "settings" in data:
                        self.config["settings"].update(data["settings"])
            except Exception as e:
                print(f"Error loading config: {e}")

    def save(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")

    def get_setting(self, key, default=None):
        return self.config["settings"].get(key, default)

    def set_setting(self, key, value):
        self.config["settings"][key] = value
        self.save()

    def pin_app(self, name, exe, icon):
        cleaned_exe = clean_exec_cmd(exe)
        for app in self.config["pinned"]:
            if clean_exec_cmd(app["exec"]) == cleaned_exe:
                return
        self.config["pinned"].append({"name": name, "exec": exe, "icon": icon})
        self.save()

    def unpin_app(self, exe):
        cleaned_exe = clean_exec_cmd(exe)
        self.config["pinned"] = [app for app in self.config["pinned"] if clean_exec_cmd(app["exec"]) != cleaned_exe]
        self.save()

    def is_pinned(self, exe):
        cleaned_exe = clean_exec_cmd(exe)
        for app in self.config["pinned"]:
            if clean_exec_cmd(app["exec"]) == cleaned_exe:
                return True
        return False


class WidthAnimator:
    def __init__(self, widget, start, end, duration_ms=250, callback=None):
        self.widget = widget
        self.start = start
        self.end = end
        self.duration = duration_ms
        self.callback = callback
        self.start_time = GLib.get_monotonic_time() / 1000
        self.tag = GLib.timeout_add(12, self.tick)

    def tick(self):
        now = GLib.get_monotonic_time() / 1000
        elapsed = now - self.start_time
        if elapsed >= self.duration:
            self.widget.set_size_request(self.end, -1)
            if self.end == 0:
                self.widget.hide()
            if self.callback:
                self.callback()
            return False
        
        # Cubic Out Easing
        t = elapsed / self.duration
        t = 1 - (1 - t) ** 3
        current = int(self.start + (self.end - self.start) * t)
        self.widget.set_size_request(current, -1)
        self.widget.show_all()
        return True


class MarginAnimator:
    def __init__(self, widget, edge, start, end, duration_ms=250, callback=None):
        self.widget = widget
        self.edge = edge
        self.start = start
        self.end = end
        self.duration = duration_ms
        self.callback = callback
        self.start_time = GLib.get_monotonic_time() / 1000
        self.tag = GLib.timeout_add(12, self.tick)

    def tick(self):
        now = GLib.get_monotonic_time() / 1000
        elapsed = now - self.start_time
        if elapsed >= self.duration:
            GtkLayerShell.set_margin(self.widget, self.edge, self.end)
            if self.callback:
                self.callback()
            return False
        
        # Cubic Out Easing
        t = elapsed / self.duration
        t = 1 - (1 - t) ** 3
        current = int(self.start + (self.end - self.start) * t)
        GtkLayerShell.set_margin(self.widget, self.edge, current)
        return True


class DesktopAppDatabase:
    def __init__(self):
        self.apps = []
        self.by_class = {}
        self.by_exec = {}
        self.reload()

    def reload(self):
        self.apps = []
        self.by_class = {}
        self.by_exec = {}
        paths = ["/usr/share/applications", os.path.expanduser("~/.local/share/applications")]
        for p in paths:
            if not os.path.exists(p):
                continue
            for f in os.listdir(p):
                if f.endswith(".desktop"):
                    filepath = os.path.join(p, f)
                    try:
                        self.parse_desktop_file(filepath)
                    except Exception:
                        pass

    def parse_desktop_file(self, filepath):
        info = {}
        with open(filepath, "r", errors="ignore") as f:
            in_section = False
            for line in f:
                line = line.strip()
                if line == "[Desktop Entry]":
                    in_section = True
                    continue
                elif line.startswith("[") and line.endswith("]"):
                    in_section = False
                    continue
                if in_section and "=" in line:
                    k, v = line.split("=", 1)
                    info[k.strip()] = v.strip()

        if info.get("NoDisplay") == "true" or info.get("Type") != "Application":
            return

        name = info.get("Name", "")
        exec_cmd = info.get("Exec", "")
        icon = info.get("Icon", "")
        categories = info.get("Categories", "Other").split(";")
        categories = [c.strip() for c in categories if c.strip()]
        
        # Clean exec command (%U, %f, etc)
        exec_clean = exec_cmd
        for placeholder in ["%u", "%U", "%f", "%F", "%i", "%c", "%k"]:
            exec_clean = exec_clean.replace(placeholder, "")
        exec_clean = exec_clean.strip()

        app_entry = {
            "name": name,
            "exec": exec_clean,
            "icon": icon,
            "categories": categories,
            "wm_class": info.get("StartupWMClass", "").lower()
        }

        self.apps.append(app_entry)
        if app_entry["wm_class"]:
            self.by_class[app_entry["wm_class"]] = app_entry
        
        # Also index by executable name
        exe_name = os.path.basename(exec_clean.split()[0]).lower() if exec_clean else ""
        if exe_name:
            self.by_exec[exe_name] = app_entry

    def find_by_class(self, wm_class):
        if not wm_class:
            return None
        wm_class_lower = wm_class.lower()
        # Direct class match
        if wm_class_lower in self.by_class:
            return self.by_class[wm_class_lower]
        # Exec name match
        if wm_class_lower in self.by_exec:
            return self.by_exec[wm_class_lower]
        # Partial match
        for k, v in self.by_class.items():
            if k in wm_class_lower or wm_class_lower in k:
                return v
        for k, v in self.by_exec.items():
            if k in wm_class_lower or wm_class_lower in k:
                return v
        return None


class StartMenu(Gtk.Window):
    def __init__(self, config_manager, db_apps, taskbar_win):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config_manager = config_manager
        self.db_apps = db_apps
        self.taskbar_win = taskbar_win
        self.set_name("start-menu-window")

        self.set_app_paintable(True)

        # Configure RGBA Visual for transparency
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        # Configure Layer Shell
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        GtkLayerShell.set_namespace(self, "hyde-start-menu")

        # Style context
        self.get_style_context().add_class("start-menu")

        self.connect("focus-out-event", self.on_focus_out)
        self.connect("key-press-event", self.on_key_press)
        self.connect("enter-notify-event", self.on_enter)
        self.connect("leave-notify-event", self.on_leave)

        self.hide_timer = None
        self.mouse_inside_menu = False
        self.menu_active = False

        # Main Layout
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.main_box.set_size_request(450, 550)
        self.main_box.get_style_context().add_class("start-menu-container")
        self.add(self.main_box)

        # Search Bar
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search apps...")
        self.search_entry.connect("search-changed", self.on_search_changed)
        self.main_box.pack_start(self.search_entry, False, False, 4)

        # Content Area (Sidebar categories + Grid)
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.main_box.pack_start(self.content_box, True, True, 4)

        # Categories Sidebar
        self.sidebar_scrolled = Gtk.ScrolledWindow()
        self.sidebar_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.sidebar_scrolled.set_size_request(120, -1)
        self.category_list = Gtk.ListBox()
        self.category_list.connect("row-selected", self.on_category_selected)
        self.sidebar_scrolled.add(self.category_list)
        self.content_box.pack_start(self.sidebar_scrolled, False, False, 0)

        # Apps Grid Scrolled Area
        self.grid_scrolled = Gtk.ScrolledWindow()
        self.grid_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.apps_flowbox = Gtk.FlowBox()
        self.apps_flowbox.set_valign(Gtk.Align.START)
        self.apps_flowbox.set_max_children_per_line(4)
        self.apps_flowbox.set_min_children_per_line(4)
        self.apps_flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.apps_flowbox.connect("child-activated", self.on_app_activated)
        self.grid_scrolled.add(self.apps_flowbox)
        self.content_box.pack_start(self.grid_scrolled, True, True, 0)

        # Bottom Action Bar (Power actions)
        self.bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.bottom_bar.get_style_context().add_class("bottom-action-bar")
        self.main_box.pack_end(self.bottom_bar, False, False, 4)

        # Settings Button
        settings_btn = Gtk.Button.new_from_icon_name("preferences-system", Gtk.IconSize.LARGE_TOOLBAR)
        settings_btn.set_tooltip_text("Taskbar Settings")
        settings_btn.connect("clicked", self.on_settings_clicked)
        self.bottom_bar.pack_start(settings_btn, False, False, 4)

        # Spacer
        spacer = Gtk.Box()
        self.bottom_bar.pack_start(spacer, True, True, 0)

        # Power Buttons
        self.add_power_btn("system-lock-screen", "Lock Screen", "hyde-shell lock-session")
        self.add_power_btn("system-suspend", "Suspend", "systemctl suspend")
        self.add_power_btn("system-log-out", "Log Out", "hyprctl dispatch exit")
        self.add_power_btn("system-reboot", "Restart", "systemctl reboot")
        self.add_power_btn("system-shutdown", "Shut Down", "systemctl poweroff")

        self.current_category = "All"
        self.search_text = ""
        
        self.populate_categories()
        self.filter_apps()

    def add_power_btn(self, icon_name, tooltip, command):
        btn = Gtk.Button.new_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR)
        btn.set_tooltip_text(tooltip)
        btn.get_style_context().add_class("power-btn")
        btn.connect("clicked", lambda w: self.run_action(command))
        self.bottom_bar.pack_end(btn, False, False, 4)

    def run_action(self, cmd):
        self.hide()
        subprocess.Popen(cmd.split(), start_new_session=True)

    def on_settings_clicked(self, btn):
        self.hide()
        self.taskbar_win.open_settings()

    def populate_categories(self):
        categories = ["All", "Development", "Graphics", "Internet", "Multimedia", "Office", "System", "Utility"]
        for cat in categories:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=cat, xalign=0.0)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(6)
            label.set_margin_bottom(6)
            row.add(label)
            row.cat_name = cat
            self.category_list.add(row)
        self.category_list.select_row(self.category_list.get_row_at_index(0))

    def filter_apps(self):
        # Clear current flowbox children
        for child in self.apps_flowbox.get_children():
            self.apps_flowbox.remove(child)

        search_query = self.search_text.lower().strip()
        
        for app in sorted(self.db_apps.apps, key=lambda x: x["name"].lower()):
            # Category filter
            if self.current_category != "All":
                mapped_cats = [c.lower() for c in app["categories"]]
                if self.current_category.lower() not in mapped_cats:
                    if self.current_category == "Utility" and "accessories" in mapped_cats:
                        pass
                    elif self.current_category == "Multimedia" and ("audio" in mapped_cats or "video" in mapped_cats or "audiovideo" in mapped_cats):
                        pass
                    else:
                        continue
            
            # Search query filter
            if search_query:
                if search_query not in app["name"].lower() and search_query not in app["exec"].lower():
                    continue

            # Create Grid Item
            item_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            item_box.set_size_request(72, 80)
            item_box.set_margin_start(4)
            item_box.set_margin_end(4)
            item_box.set_margin_top(4)
            item_box.set_margin_bottom(4)

            # Icon
            img = Gtk.Image()
            icon_size = 40
            pixbuf = get_icon_pixbuf(app["icon"], icon_size)
            if pixbuf:
                img.set_from_pixbuf(pixbuf)
            
            item_box.pack_start(img, True, True, 0)

            # Label
            lbl = Gtk.Label(label=app["name"])
            lbl.set_ellipsize(3) # Pango.EllipsizeMode.END
            lbl.set_max_width_chars(10)
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.get_style_context().add_class("start-app-label")
            item_box.pack_start(lbl, False, False, 0)

            # Wrapper Row
            row = Gtk.EventBox()
            row.set_visible_window(False)
            row.add(item_box)
            row.app_data = app

            row.connect("button-press-event", self.on_app_button_press, app)

            self.apps_flowbox.add(row)
        
        self.apps_flowbox.show_all()

    def on_app_button_press(self, widget, event, app):
        if event.button == 3: # Right click
            self.on_app_right_click(event, app)
            return True
        return False

    def on_app_right_click(self, event, app):
        self.menu_active = True
        menu = Gtk.Menu()
        menu.connect("deactivate", self.on_menu_deactivate)
        
        # Launch option
        launch_item = Gtk.MenuItem(label="Launch Application")
        launch_item.connect("activate", lambda w: self.launch_app(app))
        menu.append(launch_item)
        
        # Pin/Unpin option
        is_pinned = self.config_manager.is_pinned(app["exec"])
        pin_item = Gtk.MenuItem(label="Unpin from Taskbar" if is_pinned else "Pin to Taskbar")
        pin_item.connect("activate", self.on_toggle_pin, app)
        menu.append(pin_item)
        
        menu.show_all()
        ev = Gtk.get_current_event()
        menu.popup_at_pointer(ev)

    def launch_app(self, app):
        self.hide()
        subprocess.Popen(app["exec"].split(), start_new_session=True)

    def on_toggle_pin(self, item, app):
        is_pinned = self.config_manager.is_pinned(app["exec"])
        if is_pinned:
            self.config_manager.unpin_app(app["exec"])
        else:
            self.config_manager.pin_app(app["name"], app["exec"], app["icon"])
        self.taskbar_win.refresh_layout()

    def on_menu_deactivate(self, menu):
        self.menu_active = False
        GLib.timeout_add(100, self.check_focus_on_menu_close)

    def check_focus_on_menu_close(self):
        if not self.mouse_inside_menu and not self.taskbar_win.mouse_inside:
            self.hide()
        return False


    def on_category_selected(self, listbox, row):
        if row:
            self.current_category = row.cat_name
            self.filter_apps()

    def on_search_changed(self, entry):
        self.search_text = entry.get_text()
        self.filter_apps()

    def on_app_activated(self, flowbox, child):
        # child is a FlowBoxChild wrapping our custom row Box
        row_box = child.get_child()
        app = row_box.app_data
        self.hide()
        subprocess.Popen(app["exec"].split(), start_new_session=True)

    def toggle(self, button):
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
            self.hide_timer = None
        if self.is_visible():
            self.hide()
        else:
            self.mouse_inside_menu = False
            # Position the Start Menu relative to the button
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
            
            # Read settings for margins
            pos = self.config_manager.get_setting("position", "bottom")
            align = self.config_manager.get_setting("alignment", "center")
            offset_y = self.config_manager.get_setting("offset_y", 10)
            offset_x = self.config_manager.get_setting("offset_x", 0)
            
            # Position dynamically
            alloc = button.get_allocation()
            origin_x, origin_y = button.translate_coordinates(self.taskbar_win, 0, 0)
            
            screen_w = self.taskbar_win.get_screen().get_width()
            
            if pos == "bottom":
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, False)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, 65 + offset_y)
            elif pos == "top":
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, False)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 65 + offset_y)
            
            if align == "center":
                # Position above the start of the bar
                bar_alloc = self.taskbar_win.get_allocation()
                x_offset = int((screen_w - 450) / 2)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, max(12, x_offset))
            else:
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, max(12, origin_x + offset_x))

            self.show_all()
            self.present()
            self.search_entry.set_text("")
            self.search_entry.grab_focus()

    def on_enter(self, widget, event):
        self.mouse_inside_menu = True
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
            self.hide_timer = None
        return False

    def on_leave(self, widget, event):
        self.mouse_inside_menu = False
        return False

    def on_focus_out(self, widget, event):
        # Start a 250ms delay timer before hiding
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
        self.hide_timer = GLib.timeout_add(250, self.delayed_hide)
        return False

    def delayed_hide(self):
        self.hide_timer = None
        if getattr(self, 'menu_active', False):
            return False
        # Check if mouse is inside the start menu or the taskbar before hiding
        if not self.mouse_inside_menu and not self.taskbar_win.mouse_inside:
            self.hide()
        return False

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False


class SettingsWindow(Gtk.Window):
    def __init__(self, config_manager, taskbar_win):
        super().__init__(title="Taskbar Modifier Options")
        self.config_manager = config_manager
        self.taskbar_win = taskbar_win
        
        self.set_default_size(350, 480)
        self.set_keep_above(True)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Style context
        self.get_style_context().add_class("settings-window")

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)
        main_box.set_margin_top(16)
        main_box.set_margin_bottom(16)
        self.add(main_box)

        # Title
        lbl = Gtk.Label(label="Taskbar Customizer GUI")
        lbl.get_style_context().add_class("settings-title")
        main_box.pack_start(lbl, False, False, 4)

        # Scrolled Area for Controls
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_height(True)
        main_box.pack_start(scrolled, True, True, 4)

        # Grid of controls
        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(16)
        grid.set_margin_start(8)
        grid.set_margin_end(8)
        grid.set_margin_top(8)
        grid.set_margin_bottom(8)
        scrolled.add(grid)

        row = 0

        # Position
        grid.attach(Gtk.Label(label="Edge Position:", xalign=0.0), 0, row, 1, 1)
        self.pos_combo = Gtk.ComboBoxText()
        self.pos_combo.append("bottom", "Bottom")
        self.pos_combo.append("top", "Top")
        self.pos_combo.set_active_id(config_manager.get_setting("position", "bottom"))
        self.pos_combo.connect("changed", self.on_pos_changed)
        grid.attach(self.pos_combo, 1, row, 1, 1)
        row += 1

        # Alignment
        grid.attach(Gtk.Label(label="Alignment:", xalign=0.0), 0, row, 1, 1)
        self.align_combo = Gtk.ComboBoxText()
        self.align_combo.append("center", "Center")
        self.align_combo.append("start", "Left/Start")
        self.align_combo.append("end", "Right/End")
        self.align_combo.set_active_id(config_manager.get_setting("alignment", "center"))
        self.align_combo.connect("changed", self.on_align_changed)
        grid.attach(self.align_combo, 1, row, 1, 1)
        row += 1

        # Icon Size
        grid.attach(Gtk.Label(label="Icon Size (px):", xalign=0.0), 0, row, 1, 1)
        self.size_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 24, 64, 2)
        self.size_scale.set_value(config_manager.get_setting("icon_size", 40))
        self.size_scale.connect("value-changed", self.on_icon_size_changed)
        grid.attach(self.size_scale, 1, row, 1, 1)
        row += 1

        # Spacing
        grid.attach(Gtk.Label(label="Spacing (px):", xalign=0.0), 0, row, 1, 1)
        self.spacing_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 2, 24, 1)
        self.spacing_scale.set_value(config_manager.get_setting("spacing", 8))
        self.spacing_scale.connect("value-changed", self.on_spacing_changed)
        grid.attach(self.spacing_scale, 1, row, 1, 1)
        row += 1

        # Bar Padding
        grid.attach(Gtk.Label(label="Bar Padding (px):", xalign=0.0), 0, row, 1, 1)
        self.padding_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 2, 20, 1)
        self.padding_scale.set_value(config_manager.get_setting("bar_padding", 6))
        self.padding_scale.connect("value-changed", self.on_padding_changed)
        grid.attach(self.padding_scale, 1, row, 1, 1)
        row += 1

        # Border Radius
        grid.attach(Gtk.Label(label="Corner Radius (px):", xalign=0.0), 0, row, 1, 1)
        self.radius_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 32, 1)
        self.radius_scale.set_value(config_manager.get_setting("border_radius", 20))
        self.radius_scale.connect("value-changed", self.on_radius_changed)
        grid.attach(self.radius_scale, 1, row, 1, 1)
        row += 1

        # Margins
        grid.attach(Gtk.Label(label="Edge Offset (px):", xalign=0.0), 0, row, 1, 1)
        self.offset_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.offset_scale.set_value(config_manager.get_setting("offset_y", 10))
        self.offset_scale.connect("value-changed", self.on_offset_changed)
        grid.attach(self.offset_scale, 1, row, 1, 1)
        row += 1

        # Opacity
        grid.attach(Gtk.Label(label="Opacity:", xalign=0.0), 0, row, 1, 1)
        self.opacity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.05, 1.0, 0.05)
        self.opacity_scale.set_value(config_manager.get_setting("opacity", 0.4))
        self.opacity_scale.connect("value-changed", self.on_opacity_changed)
        grid.attach(self.opacity_scale, 1, row, 1, 1)
        row += 1

        # Theme selection
        grid.attach(Gtk.Label(label="Theme Style:", xalign=0.0), 0, row, 1, 1)
        self.theme_combo = Gtk.ComboBoxText()
        self.theme_combo.append("glassmorphic", "Glassmorphic")
        self.theme_combo.append("neon-glow", "Neon Glow")
        self.theme_combo.append("solid", "Solid Color")
        self.theme_combo.append("outline", "Outline / Cyberpunk")
        self.theme_combo.append("gtk", "Standard GTK Panel")
        self.theme_combo.set_active_id(config_manager.get_setting("theme", "glassmorphic"))
        self.theme_combo.connect("changed", self.on_theme_changed)
        grid.attach(self.theme_combo, 1, row, 1, 1)
        row += 1

        # Blur
        grid.attach(Gtk.Label(label="Blur Background:", xalign=0.0), 0, row, 1, 1)
        self.blur_switch = Gtk.Switch()
        self.blur_switch.set_active(config_manager.get_setting("blur", True))
        self.blur_switch.connect("state-set", self.on_blur_changed)
        grid.attach(self.blur_switch, 1, row, 1, 1)
        row += 1

        # Auto-hide
        grid.attach(Gtk.Label(label="Auto-Hide:", xalign=0.0), 0, row, 1, 1)
        self.autohide_switch = Gtk.Switch()
        self.autohide_switch.set_active(config_manager.get_setting("auto_hide", False))
        self.autohide_switch.connect("state-set", self.on_autohide_changed)
        grid.attach(self.autohide_switch, 1, row, 1, 1)
        row += 1

        # Auto-hide Delay
        grid.attach(Gtk.Label(label="Hide Delay (ms):", xalign=0.0), 0, row, 1, 1)
        self.delay_spin = Gtk.SpinButton.new_with_range(100, 3000, 100)
        self.delay_spin.set_digits(0)
        self.delay_spin.set_value(config_manager.get_setting("auto_hide_delay", 500))
        self.delay_spin.connect("value-changed", self.on_delay_changed)
        grid.attach(self.delay_spin, 1, row, 1, 1)
        row += 1

        # Start on Boot
        grid.attach(Gtk.Label(label="Start on Boot:", xalign=0.0), 0, row, 1, 1)
        self.boot_switch = Gtk.Switch()
        self.boot_switch.set_active(self.is_autostart_enabled())
        self.boot_switch.connect("state-set", self.on_boot_changed)
        grid.attach(self.boot_switch, 1, row, 1, 1)
        row += 1

        self.show_all()

    def on_pos_changed(self, combo):
        self.config_manager.set_setting("position", combo.get_active_id())
        self.taskbar_win.refresh_layout()

    def on_align_changed(self, combo):
        self.config_manager.set_setting("alignment", combo.get_active_id())
        self.taskbar_win.refresh_layout()

    def on_icon_size_changed(self, scale):
        self.config_manager.set_setting("icon_size", int(scale.get_value()))
        self.taskbar_win.refresh_layout()

    def on_spacing_changed(self, scale):
        self.config_manager.set_setting("spacing", int(scale.get_value()))
        self.taskbar_win.refresh_layout()

    def on_padding_changed(self, scale):
        self.config_manager.set_setting("bar_padding", int(scale.get_value()))
        self.taskbar_win.refresh_layout()

    def on_radius_changed(self, scale):
        self.config_manager.set_setting("border_radius", int(scale.get_value()))
        self.taskbar_win.refresh_layout()

    def on_offset_changed(self, scale):
        self.config_manager.set_setting("offset_y", int(scale.get_value()))
        self.taskbar_win.refresh_layout()

    def on_opacity_changed(self, scale):
        self.config_manager.set_setting("opacity", scale.get_value())
        self.taskbar_win.reload_styles()

    def on_theme_changed(self, combo):
        self.config_manager.set_setting("theme", combo.get_active_id())
        self.taskbar_win.reload_styles()

    def on_blur_changed(self, switch, state):
        self.config_manager.set_setting("blur", state)
        self.taskbar_win.refresh_layout()

    def on_autohide_changed(self, switch, state):
        self.config_manager.set_setting("auto_hide", state)
        self.taskbar_win.setup_autohide()

    def on_delay_changed(self, spin):
        self.config_manager.set_setting("auto_hide_delay", spin.get_value_as_int())
        self.taskbar_win.setup_autohide()

    def is_autostart_enabled(self):
        path = os.path.expanduser("~/.config/hypr/userprefs.conf")
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r") as f:
                content = f.read()
            return "exec-once = python3 ~/.config/hyde/taskbar/hyde-taskbar.py" in content
        except Exception:
            return False

    def on_boot_changed(self, switch, state):
        path = os.path.expanduser("~/.config/hypr/userprefs.conf")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            content = ""
            if os.path.exists(path):
                with open(path, "r") as f:
                    content = f.read()
            
            if state:
                lines_to_add = []
                if "hyde-taskbar.py" not in content:
                    lines_to_add.append("\n# -----------------------------------------------------")
                    lines_to_add.append("# HyDE Custom Taskbar Integration")
                    lines_to_add.append("# -----------------------------------------------------")
                    lines_to_add.append("exec-once = python3 ~/.config/hyde/taskbar/hyde-taskbar.py")
                if "match:namespace hyde-taskbar" not in content:
                    lines_to_add.append("layerrule = blur true,match:namespace hyde-taskbar")
                    lines_to_add.append("layerrule = ignore_alpha 0.05,match:namespace hyde-taskbar")
                if "match:namespace hyde-start-menu" not in content:
                    lines_to_add.append("layerrule = blur true,match:namespace hyde-start-menu")
                    lines_to_add.append("layerrule = ignore_alpha 0.05,match:namespace hyde-start-menu")
                
                if lines_to_add:
                    with open(path, "a") as f:
                        f.write("\n".join(lines_to_add) + "\n")
            else:
                lines = content.splitlines()
                new_lines = [l for l in lines if "exec-once = python3 ~/.config/hyde/taskbar/hyde-taskbar.py" not in l]
                with open(path, "w") as f:
                    f.write("\n".join(new_lines) + "\n")
        except Exception as e:
            print(f"Error setting autostart: {e}")
        return False


class TaskbarAppButton(Gtk.EventBox):
    def __init__(self, name, exec_cmd, icon_name, config_manager, taskbar_win, is_running=False):
        super().__init__()
        self.name = name
        self.exec_cmd = exec_cmd
        self.icon_name = icon_name
        self.config_manager = config_manager
        self.taskbar_win = taskbar_win
        self.is_running = is_running
        self.is_active = False

        self.set_visible_window(False)
        self.get_style_context().add_class("app-button")

        # Layout Box
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.box.set_valign(Gtk.Align.CENTER)
        self.add(self.box)

        # Icon Gtk.Image
        self.image = Gtk.Image()
        self.box.pack_start(self.image, True, True, 0)

        # Active indicator dot
        self.indicator = Gtk.Box()
        self.indicator.get_style_context().add_class("indicator")
        self.indicator.set_halign(Gtk.Align.CENTER)
        self.box.pack_end(self.indicator, False, False, 0)

        # Setup mouse actions
        self.connect("button-press-event", self.on_button_press)
        self.connect("enter-notify-event", self.on_hover_enter)
        self.connect("leave-notify-event", self.on_hover_leave)

        self.update_icon()

    def update_icon(self):
        icon_size = self.config_manager.get_setting("icon_size", 40)
        pixbuf = get_icon_pixbuf(self.icon_name, icon_size)
        if pixbuf:
            self.image.set_from_pixbuf(pixbuf)

        self.set_tooltip_text(self.name)
        self.show_all()

    def set_running_state(self, running, active=False):
        self.is_running = running
        self.is_active = active
        
        ctx = self.get_style_context()
        if running:
            ctx.add_class("running")
        else:
            ctx.remove_class("running")

        if active:
            ctx.add_class("active")
        else:
            ctx.remove_class("active")

    def on_button_press(self, widget, event):
        if event.button == 1: # Left click
            self.launch_or_focus()
        elif event.button == 3: # Right click
            self.show_context_menu(event)
        return True

    def launch_or_focus(self):
        if self.is_running:
            # Get windows matching this class/exec
            windows = self.taskbar_win.get_windows_by_app(self.exec_cmd)
            if windows:
                if len(windows) == 1 or not self.is_active:
                    # Focus first window
                    win = windows[0]
                    subprocess.Popen(f"hyprctl dispatch focuswindow address:{win['address']}".split(), start_new_session=True)
                else:
                    # Cycle through windows of this app
                    active_addr = self.taskbar_win.get_active_window_address()
                    next_win = windows[0]
                    for idx, win in enumerate(windows):
                        if win["address"] == active_addr:
                            next_win = windows[(idx + 1) % len(windows)]
                            break
                    subprocess.Popen(f"hyprctl dispatch focuswindow address:{next_win['address']}".split(), start_new_session=True)
        else:
            subprocess.Popen(self.exec_cmd.split(), start_new_session=True)

    def show_context_menu(self, event):
        menu = Gtk.Menu()

        pinned = self.config_manager.is_pinned(self.exec_cmd)
        pin_item = Gtk.MenuItem(label="Unpin from Taskbar" if pinned else "Pin to Taskbar")
        pin_item.connect("activate", self.on_toggle_pin)
        menu.append(pin_item)

        if self.is_running:
            close_item = Gtk.MenuItem(label="Close All Windows")
            close_item.connect("activate", self.on_close_windows)
            menu.append(close_item)

        menu.show_all()
        ev = Gtk.get_current_event()
        menu.popup_at_pointer(ev)

    def on_toggle_pin(self, item):
        pinned = self.config_manager.is_pinned(self.exec_cmd)
        if pinned:
            # Animate shrink before removal if it's not running
            self.config_manager.unpin_app(self.exec_cmd)
            if not self.is_running:
                target_width = self.config_manager.get_setting("icon_size", 40) + self.config_manager.get_setting("spacing", 8)
                WidthAnimator(self, target_width, 0, duration_ms=200, callback=self.taskbar_win.refresh_layout)
                return
        else:
            self.config_manager.pin_app(self.name, self.exec_cmd, self.icon_name)
        
        self.taskbar_win.refresh_layout()

    def on_close_windows(self, item):
        windows = self.taskbar_win.get_windows_by_app(self.exec_cmd)
        for win in windows:
            subprocess.Popen(f"hyprctl dispatch closewindow address:{win['address']}".split(), start_new_session=True)

    def on_hover_enter(self, widget, event):
        self.get_style_context().add_class("hovered")
        return False

    def on_hover_leave(self, widget, event):
        self.get_style_context().remove_class("hovered")
        return False


class HydeTaskbar(Gtk.Window):
    def __init__(self, config_manager, db_apps):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config_manager = config_manager
        self.db_apps = db_apps
        self.bar_height = 50
        
        self.set_name("taskbar-window")
        self.set_title("HyDE Taskbar")
        self.set_app_paintable(True)

        # Configure RGBA Visual for transparency
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        # Configure Layer Shell
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_namespace(self, "hyde-taskbar")


        self.connect("size-allocate", self.on_size_allocate)

        # Window properties
        self.get_style_context().add_class("taskbar")

        # Main horizontal box
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.main_box.set_homogeneous(False)
        self.main_box.get_style_context().add_class("taskbar-container")
        self.add(self.main_box)

        # Arch Logo Button
        self.logo_btn = Gtk.Button()
        self.logo_btn.set_name("start-button")
        self.logo_btn.get_style_context().add_class("logo-button")
        
        self.logo_img = Gtk.Image()
        self.logo_btn.add(self.logo_img)
        self.logo_btn.connect("clicked", self.on_logo_clicked)
        self.main_box.pack_start(self.logo_btn, False, False, 0)

        # Apps Container
        self.apps_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.main_box.pack_start(self.apps_box, True, True, 0)

        # Settings window reference
        self.settings_win = None

        # Track loaded buttons
        # Maps executable command to button widget
        self.buttons = {}
        self.active_clients = []
        self.active_address = ""

        # Setup GLib File monitor for settings changes
        self.setup_config_monitor()

        # Build initial layout
        self.refresh_layout()

        # Connect window events
        self.connect("destroy", Gtk.main_quit)
        self.connect("enter-notify-event", self.on_bar_hover_enter)
        self.connect("leave-notify-event", self.on_bar_hover_leave)

        # Start IPC thread to listen to Hyprland events
        self.start_ipc_thread()

        # Setup Start Menu
        self.start_menu = StartMenu(self.config_manager, self.db_apps, self)

        # Setup Auto-hide timer & margins
        self.setup_autohide()
        self.setup_margins()

        self.show_all()

    def start_ipc_thread(self):
        t = threading.Thread(target=self.ipc_listener, daemon=True)
        t.start()

    def get_socket2_path(self):
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        if not sig:
            return None
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        path = f"{runtime_dir}/hypr/{sig}/.socket2.sock"
        if os.path.exists(path):
            return path
        path = f"/tmp/hypr/{sig}/.socket2.sock"
        if os.path.exists(path):
            return path
        return None

    def ipc_listener(self):
        sock_path = self.get_socket2_path()
        if not sock_path:
            # Fallback check
            GLib.timeout_add_seconds(2, self.poll_refresh)
            return

        while True:
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(sock_path)
                buffer = ""
                while True:
                    data = s.recv(4096)
                    if not data:
                        break
                    buffer += data.decode(errors="ignore")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if line:
                            GLib.idle_add(self.handle_hyprland_event, line)
            except Exception as e:
                print(f"Hyprland IPC connection lost: {e}. Reconnecting in 3s...")
                import time
                time.sleep(3)

    def handle_hyprland_event(self, line):
        if ">>" in line:
            ev, args = line.split(">>", 1)
            # Events that trigger a refresh of clients
            if ev in ["openwindow", "closewindow", "movewindow", "changeworkspace", "activewindow"]:
                # Debounce refresh by 80ms
                if hasattr(self, "_refresh_timer") and self._refresh_timer:
                    GLib.source_remove(self._refresh_timer)
                self._refresh_timer = GLib.timeout_add(80, self.update_running_clients)

    def poll_refresh(self):
        self.update_running_clients()
        return True

    def get_hyprland_clients(self):
        try:
            out = subprocess.check_output(["hyprctl", "clients", "-j"]).decode()
            return json.loads(out)
        except Exception:
            return []

    def get_active_window_address(self):
        try:
            out = subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True, text=True)
            if out.returncode == 0:
                data = json.loads(out.stdout)
                return data.get("address", "")
        except Exception:
            pass
        return ""

    def update_running_clients(self):
        self._refresh_timer = None
        
        clients = self.get_hyprland_clients()
        self.active_address = self.get_active_window_address()
        self.active_clients = clients

        # Gather classes of all running windows
        running_apps = defaultdict(list)
        for client in clients:
            cls = client.get("class", "")
            if cls:
                running_apps[cls.lower()].append(client)

        pinned_apps = self.config_manager.config["pinned"]
        pinned_execs = [app["exec"] for app in pinned_apps]

        # 1. Update states of existing buttons (both pinned and unpinned)
        for exe, btn in list(self.buttons.items()):
            matching_clients = self.get_windows_by_app(exe)
            if matching_clients:
                is_active = any(c["address"] == self.active_address for c in matching_clients)
                btn.set_running_state(True, is_active)
            else:
                btn.set_running_state(False, False)

        # 2. Add buttons for running apps that are not already present in self.buttons or pinned in config
        for cls, clients_list in running_apps.items():
            # Try to match to a desktop entry
            app_entry = self.db_apps.find_by_class(cls)
            if app_entry:
                exe = app_entry["exec"]
                name = app_entry["name"]
                icon = app_entry["icon"]
            else:
                # Fallback for apps with no desktop file
                exe = cls
                name = cls.capitalize()
                icon = cls.lower()

            cleaned_exe = clean_exec_cmd(exe)

            # Check if this app is already represented in our buttons
            already_has_button = False
            for btn_exe in self.buttons.keys():
                if clean_exec_cmd(btn_exe) == cleaned_exe:
                    already_has_button = True
                    break

            # Check if this app is pinned in the config
            is_pinned_in_config = False
            for pinned_exe in pinned_execs:
                if clean_exec_cmd(pinned_exe) == cleaned_exe:
                    is_pinned_in_config = True
                    break

            if not already_has_button and not is_pinned_in_config:
                # Create dynamic app button
                btn = TaskbarAppButton(name, exe, icon, self.config_manager, self, is_running=True)
                
                # Set margins/spacing
                spacing = self.config_manager.get_setting("spacing", 8)
                btn.box.set_margin_start(spacing // 2)
                btn.box.set_margin_end(spacing // 2)
                
                self.apps_box.pack_end(btn, False, False, 0)
                self.buttons[exe] = btn
                
                # Slide-in animation
                target_width = self.config_manager.get_setting("icon_size", 40) + spacing
                btn.set_size_request(0, -1)
                WidthAnimator(btn, 0, target_width)
                
                is_active = any(c["address"] == self.active_address for c in clients_list)
                btn.set_running_state(True, is_active)

        # 3. Clean up unpinned apps that are no longer running
        for exe, btn in list(self.buttons.items()):
            # Check if this exe is pinned in config
            is_pinned_in_config = False
            for pinned_exe in pinned_execs:
                if clean_exec_cmd(pinned_exe) == clean_exec_cmd(exe):
                    is_pinned_in_config = True
                    break
            
            if not is_pinned_in_config:
                matching_clients = self.get_windows_by_app(exe)
                if not matching_clients:
                    # Animate slide-out before removing
                    if exe in self.buttons:
                        del self.buttons[exe]
                    target_width = self.config_manager.get_setting("icon_size", 40) + self.config_manager.get_setting("spacing", 8)
                    WidthAnimator(btn, target_width, 0, duration_ms=200, callback=lambda b=btn: self.remove_button_callback(b))

        return False

    def remove_button_callback(self, btn):
        self.apps_box.remove(btn)
        self.refresh_layout()

    def get_windows_by_app(self, exec_cmd):
        cmd_base = clean_exec_cmd(exec_cmd)
        if not cmd_base:
            return []

        matched = []
        for client in self.active_clients:
            cls = client.get("class", "").lower()
            title = client.get("title", "").lower()
            initial_class = client.get("initialClass", "").lower()
            
            # Match base executable command with window class, initial class, or title
            if (cmd_base in cls or cls in cmd_base or 
                cmd_base in initial_class or initial_class in cmd_base or
                cmd_base in title):
                matched.append(client)
            else:
                # Fallback to desktop entry lookup
                app_entry = self.db_apps.find_by_class(cls)
                if app_entry and cmd_base in clean_exec_cmd(app_entry["exec"]):
                    matched.append(client)
        return matched

    def refresh_layout(self):
        # Update Arch Logo image
        logo_size = int(self.config_manager.get_setting("icon_size", 40) * 0.7)
        logo_size = max(24, logo_size)
        custom_logo_path = os.path.join(CONFIG_DIR, "arch_logo.png")
        loaded_custom = False
        
        if os.path.exists(custom_logo_path):
            try:
                from gi.repository import GdkPixbuf
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(custom_logo_path)
                scaled_pixbuf = pixbuf.scale_simple(logo_size, logo_size, GdkPixbuf.InterpType.BILINEAR)
                self.logo_img.set_from_pixbuf(scaled_pixbuf)
                loaded_custom = True
            except Exception as e:
                print(f"Error loading custom logo image: {e}")

        if not loaded_custom:
            try:
                from gi.repository import GdkPixbuf
                loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
                loader.write(ARCH_SVG_DATA.encode())
                loader.close()
                pixbuf = loader.get_pixbuf()
                scaled_pixbuf = pixbuf.scale_simple(logo_size, logo_size, GdkPixbuf.InterpType.BILINEAR)
                self.logo_img.set_from_pixbuf(scaled_pixbuf)
            except Exception as e:
                print(f"Error loading logo SVG: {e}")
                self.logo_img.set_from_icon_name("archlinux", Gtk.IconSize.DIALOG)

        # Re-populate the apps container
        for child in self.apps_box.get_children():
            self.apps_box.remove(child)

        spacing = self.config_manager.get_setting("spacing", 8)
        bar_padding = self.config_manager.get_setting("bar_padding", 6)
        
        # Configure layout padding/margins
        self.main_box.set_margin_start(0)
        self.main_box.set_margin_end(0)
        self.main_box.set_margin_top(0)
        self.main_box.set_margin_bottom(0)

        # Add Pinned apps
        pinned_apps = self.config_manager.config["pinned"]
        self.buttons = {}
        
        for app in pinned_apps:
            btn = TaskbarAppButton(app["name"], app["exec"], app["icon"], self.config_manager, self)
            btn.box.set_margin_start(spacing // 2)
            btn.box.set_margin_end(spacing // 2)
            self.apps_box.pack_start(btn, False, False, 0)
            self.buttons[app["exec"]] = btn

        self.apps_box.show_all()
        self.update_running_clients()

        # Update layer anchors and alignment
        self.setup_autohide()
        self.setup_margins()
        self.reload_styles()

    def setup_margins(self):
        # Configure Anchors
        pos = self.config_manager.get_setting("position", "bottom")
        align = self.config_manager.get_setting("alignment", "center")
        offset_y = self.config_manager.get_setting("offset_y", 10)
        offset_x = self.config_manager.get_setting("offset_x", 0)

        # Clear anchors
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, False)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)

        # Position Anchor
        if pos == "top":
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
            if getattr(self, 'autohide_active', False) and getattr(self, 'is_hidden', False):
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, -(self.bar_height - 2))
            else:
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, offset_y)
        else:
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
            if getattr(self, 'autohide_active', False) and getattr(self, 'is_hidden', False):
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, -(self.bar_height - 2))
            else:
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, offset_y)

        # Alignment Anchor
        if align == "start":
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, 20 + offset_x)
        elif align == "end":
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 20 + offset_x)
        else:
            # Centered: do NOT set LEFT or RIGHT anchors. GTK Layer Shell automatically centers
            # the window and scales width to fit the content! This provides the retractable behavior.
            pass

    def setup_autohide(self):
        self.autohide_active = self.config_manager.get_setting("auto_hide", False)
        self.hide_delay = self.config_manager.get_setting("auto_hide_delay", 500)
        self.mouse_inside = False
        
        # Reset hide timer
        if hasattr(self, 'hide_timer_id') and self.hide_timer_id:
            GLib.source_remove(self.hide_timer_id)
            self.hide_timer_id = None

        if self.autohide_active:
            # On-top layer so it appears above normal windows when revealed
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
            GtkLayerShell.set_exclusive_zone(self, 0)
            self.is_hidden = False
            self.queue_hide()
        else:
            # Underneath windows when open
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)
            GtkLayerShell.set_exclusive_zone(self, 0) # stay behind foreground softwares
            self.is_hidden = False
            self.reveal_bar(animate=False)

    def reveal_bar(self, animate=True):
        self.is_hidden = False
        pos = self.config_manager.get_setting("position", "bottom")
        edge = GtkLayerShell.Edge.TOP if pos == "top" else GtkLayerShell.Edge.BOTTOM
        offset_y = self.config_manager.get_setting("offset_y", 10)

        # Cancel current margin animator
        if hasattr(self, 'margin_animator') and self.margin_animator:
            GLib.source_remove(self.margin_animator.tag)
            self.margin_animator = None

        if animate:
            current_margin = GtkLayerShell.get_margin(self, edge)
            self.margin_animator = MarginAnimator(self, edge, current_margin, offset_y, duration_ms=200)
        else:
            GtkLayerShell.set_margin(self, edge, offset_y)

    def hide_bar(self, animate=True):
        self.is_hidden = True
        pos = self.config_manager.get_setting("position", "bottom")
        edge = GtkLayerShell.Edge.TOP if pos == "top" else GtkLayerShell.Edge.BOTTOM
        hidden_margin = -(self.bar_height - 2)

        # Cancel current margin animator
        if hasattr(self, 'margin_animator') and self.margin_animator:
            GLib.source_remove(self.margin_animator.tag)
            self.margin_animator = None

        if animate:
            current_margin = GtkLayerShell.get_margin(self, edge)
            self.margin_animator = MarginAnimator(self, edge, current_margin, hidden_margin, duration_ms=200)
        else:
            GtkLayerShell.set_margin(self, edge, hidden_margin)

    def queue_hide(self):
        if hasattr(self, 'hide_timer_id') and self.hide_timer_id:
            GLib.source_remove(self.hide_timer_id)
            self.hide_timer_id = None
        self.hide_timer_id = GLib.timeout_add(self.hide_delay, self._on_hide_timer)

    def _on_hide_timer(self):
        self.hide_timer_id = None
        if not self.mouse_inside:
            self.hide_bar()
        return False

    def on_bar_hover_enter(self, widget, event):
        self.mouse_inside = True
        if self.autohide_active:
            if hasattr(self, 'hide_timer_id') and self.hide_timer_id:
                GLib.source_remove(self.hide_timer_id)
                self.hide_timer_id = None
            self.reveal_bar()
        return False

    def on_bar_hover_leave(self, widget, event):
        self.mouse_inside = False
        if self.autohide_active:
            self.queue_hide()
        return False

    def on_size_allocate(self, widget, allocation):
        self.bar_height = allocation.height
        if getattr(self, 'autohide_active', False) and getattr(self, 'is_hidden', False):
            pos = self.config_manager.get_setting("position", "bottom")
            edge = GtkLayerShell.Edge.TOP if pos == "top" else GtkLayerShell.Edge.BOTTOM
            hidden_margin = -(self.bar_height - 2)
            GtkLayerShell.set_margin(self, edge, hidden_margin)

    def setup_config_monitor(self):
        # Config monitor
        gio_file = Gio.File.new_for_path(CONFIG_FILE)
        self.monitor = gio_file.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self.on_config_file_changed)

        # Wallbash CSS monitor
        if os.path.exists(WALLBASH_CSS):
            gio_css = Gio.File.new_for_path(WALLBASH_CSS)
            self.css_monitor = gio_css.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self.css_monitor.connect("changed", self.on_css_file_changed)

    def on_config_file_changed(self, monitor, file, other_file, event_type):
        if event_type == Gio.FileMonitorEvent.CHANGES_DONE_HINT:
            GLib.idle_add(self.reload_config_and_refresh)

    def on_css_file_changed(self, monitor, file, other_file, event_type):
        if event_type == Gio.FileMonitorEvent.CHANGES_DONE_HINT:
            GLib.idle_add(self.reload_styles)

    def reload_config_and_refresh(self):
        self.config_manager.load()
        self.refresh_layout()

    def get_wallbash_colors(self):
        colors = {
            "taskbar-bg": "#222233",
            "taskbar-bg-rgba": "rgba(34, 34, 51, 0.45)",
            "taskbar-border": "rgba(255, 255, 255, 0.15)",
            "taskbar-text": "#ffffff",
            "taskbar-accent": "#33a6de",
            "taskbar-accent-rgba": "rgba(51, 166, 222, 1.0)",
            "taskbar-hover-rgba": "rgba(51, 166, 222, 0.25)",
            "taskbar-indicator-active": "rgba(51, 166, 222, 0.9)",
            "taskbar-indicator-running": "rgba(255, 255, 255, 0.35)",
            "menu-bg-rgba": "rgba(20, 20, 30, 0.85)"
        }
        
        # Read from wallbash css if it exists
        if os.path.exists(WALLBASH_CSS):
            try:
                with open(WALLBASH_CSS, "r") as f:
                    for line in f:
                        if line.startswith("@define-color"):
                            parts = line.strip().split()
                            if len(parts) >= 3:
                                name = parts[1]
                                val = parts[2].rstrip(";")
                                colors[name] = val
            except Exception as e:
                print(f"Error parsing wallbash colors: {e}")
                
        # Parse opacity and replace it in the rgba string
        opacity = self.config_manager.get_setting("opacity", 0.4)
        if "@opacity@" in colors.get("taskbar-bg-rgba", ""):
            colors["taskbar-bg-rgba"] = colors["taskbar-bg-rgba"].replace("@opacity@", str(opacity))
        else:
            # Parse rgba(r,g,b,...) and set custom opacity
            rgba = colors["taskbar-bg-rgba"]
            if rgba.startswith("rgba(") and rgba.endswith(")"):
                inner = rgba[5:-1]
                vals = inner.split(",")
                if len(vals) >= 3:
                    colors["taskbar-bg-rgba"] = f"rgba({vals[0].strip()},{vals[1].strip()},{vals[2].strip()},{opacity})"
                    
        return colors

    def reload_styles(self):
        colors = self.get_wallbash_colors()
        theme = self.config_manager.get_setting("theme", "glassmorphic")
        radius = self.config_manager.get_setting("border_radius", 20)
        spacing = self.config_manager.get_setting("spacing", 8)
        bar_padding = self.config_manager.get_setting("bar_padding", 6)

        # Assemble CSS rules
        css = f"""
        @define-color bg_color {colors['taskbar-bg']};
        @define-color border_color {colors['taskbar-border']};
        @define-color text_color {colors['taskbar-text']};
        @define-color accent_color {colors['taskbar-accent']};
        @define-color accent_rgba {colors['taskbar-accent-rgba']};
        @define-color hover_bg_rgba {colors['taskbar-hover-rgba']};
        @define-color ind_active {colors['taskbar-indicator-active']};
        @define-color ind_running {colors['taskbar-indicator-running']};
        @define-color menu_bg {colors['menu-bg-rgba']};

        #taskbar-window, .taskbar {{
            background-color: transparent;
            background-image: none;
            background: transparent;
            border: none;
            box-shadow: none;
        }}
        """

        # Append style templates
        if theme == "glassmorphic":
            css += f"""
            .taskbar-container {{
                background-color: {colors['taskbar-bg-rgba']};
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: {radius}px;
                box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
                padding: {bar_padding}px {bar_padding * 2}px;
            }}
            """
        elif theme == "neon-glow":
            css += f"""
            .taskbar-container {{
                background-color: rgba(12, 12, 20, 0.65);
                border: 2px solid @accent_color;
                border-radius: {radius}px;
                box-shadow: 0 0 12px @accent_rgba;
                padding: {bar_padding}px {bar_padding * 2}px;
            }}
            """
        elif theme == "solid":
            css += f"""
            .taskbar-container {{
                background-color: @bg_color;
                border: 1px solid rgba(0, 0, 0, 0.2);
                border-radius: {radius}px;
                padding: {bar_padding}px {bar_padding * 2}px;
            }}
            """
        elif theme == "outline":
            css += f"""
            .taskbar-container {{
                background-color: rgba(0, 0, 0, 0.9);
                border: 2px solid @accent_color;
                border-radius: 0px;
                box-shadow: 4px 4px 0px @border_color;
                padding: {bar_padding}px {bar_padding * 2}px;
            }}
            """
        else: # Standard GTK
            css += f"""
            .taskbar-container {{
                background-color: @theme_bg_color;
                border: 1px solid @theme_border_color;
                border-radius: 4px;
                padding: {bar_padding}px {bar_padding * 2}px;
            }}
            """

        css += f"""
        .app-button {{
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
            border-radius: {radius - 4 if radius > 4 else 4}px;
            padding: 2px;
        }}
        .app-button.hovered {{
            background-color: @hover_bg_rgba;
            margin-bottom: 6px; /* Lift animation */
        }}
        .logo-button {{
            background: transparent;
            border: none;
            box-shadow: none;
            border-radius: 50%;
            padding: 4px;
            margin-right: {spacing}px;
            transition: all 0.2s ease;
        }}
        .logo-button:hover {{
            background-color: rgba(255, 255, 255, 0.1);
        }}
        .indicator {{
            min-height: 4px;
            min-width: 4px;
            margin-bottom: 2px;
            border-radius: 2px;
            background-color: transparent;
            transition: all 0.2s ease-in-out;
        }}
        .app-button.running .indicator {{
            background-color: @ind_running;
            min-width: 6px;
        }}
        .app-button.active .indicator {{
            background-color: @accent_color;
            min-width: 16px;
            border-radius: 2px;
        }}

        /* Start Menu styles */
        #start-menu-window, .start-menu {{
            background-color: transparent;
            background-image: none;
            background: transparent;
            border: none;
            box-shadow: none;
        }}
        .start-menu-container {{
            background-color: @menu_bg;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 16px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
            padding: 12px;
        }}
        .start-app-label {{
            font-size: 10px;
            color: @text_color;
        }}
        .power-btn {{
            background: transparent;
            border: none;
            box-shadow: none;
            color: @text_color;
            padding: 6px;
            border-radius: 8px;
            transition: all 0.2s ease;
        }}
        .power-btn:hover {{
            background-color: rgba(255, 50, 50, 0.2);
            color: #ff5555;
        }}
        .bottom-action-bar {{
            border-top: 1px solid rgba(255, 255, 255, 0.1);
            padding-top: 8px;
        }}

        /* Settings GUI styles */
        .settings-window {{
            background-color: rgba(22, 22, 33, 0.95);
            color: #ffffff;
            font-family: "Inter", "Sans-Serif";
        }}
        .settings-title {{
            font-size: 15px;
            font-weight: 700;
            color: @accent_color;
            margin-bottom: 10px;
            padding-bottom: 6px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            letter-spacing: 0.5px;
        }}
        .settings-window label {{
            color: #e2e8f0;
            font-size: 11.5px;
            font-weight: 600;
        }}
        .settings-window scrolledwindow {{
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 8px;
            background-color: rgba(10, 10, 15, 0.4);
            padding: 12px;
        }}
        /* Scrollbar decoration */
        .settings-window scrollbar {{
            background-color: transparent;
            border: none;
        }}
        .settings-window scrollbar trough {{
            background-color: rgba(255, 255, 255, 0.02);
            border-radius: 4px;
        }}
        .settings-window scrollbar slider {{
            background-color: rgba(255, 255, 255, 0.15);
            border-radius: 4px;
            min-height: 40px;
        }}
        .settings-window scrollbar slider:hover {{
            background-color: @accent_color;
        }}
        /* Combobox, SpinButton, Entry, Switch */
        .settings-window combobox button, .settings-window spinbutton entry, .settings-window spinbutton button, .settings-window switch {{
            background-color: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 6px;
            color: #ffffff;
            padding: 4px 8px;
            font-size: 11px;
            transition: all 0.2s ease;
        }}
        .settings-window combobox button:hover, .settings-window spinbutton button:hover {{
            background-color: rgba(255, 255, 255, 0.1);
            border-color: @accent_color;
        }}
        .settings-window scale slider {{
            background-color: @accent_color;
            border-radius: 50%;
            min-height: 12px;
            min-width: 12px;
            border: none;
        }}
        .settings-window scale trough {{
            background-color: rgba(255, 255, 255, 0.1);
            border-radius: 3px;
            min-height: 6px;
        }}
        .settings-window scale highlight {{
            background-color: @accent_color;
            border-radius: 3px;
        }}
        """

        # Apply CSS
        if not hasattr(self, "css_provider"):
            self.css_provider = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                self.css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        self.css_provider.load_from_data(css.encode())

    def on_logo_clicked(self, button):
        self.start_menu.toggle(button)

    def open_settings(self):
        if self.settings_win is None or not self.settings_win.is_visible():
            self.settings_win = SettingsWindow(self.config_manager, self)
        else:
            self.settings_win.present()


if __name__ == "__main__":
    # Reload desktop DB
    db_apps = DesktopAppDatabase()
    cfg_mgr = ConfigManager()

    if len(sys.argv) > 1 and sys.argv[1] == "--settings":
        # Launch settings window standalone
        win = Gtk.Window()
        win.connect("destroy", Gtk.main_quit)
        # Setup dummy taskbar just to compile styles
        class DummyTaskbar:
            def refresh_layout(self): pass
            def reload_styles(self): pass
            def setup_autohide(self): pass
        panel = SettingsWindow(cfg_mgr, DummyTaskbar())
        Gtk.main()
        sys.exit(0)

    # Launch main taskbar
    app = HydeTaskbar(cfg_mgr, db_apps)
    Gtk.main()
