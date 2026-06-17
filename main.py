import sys
import os
import threading
import asyncio
import math
import gi
import logging

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk
import cairo

from ble_backend import OpoBleController

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("NordBudsApp")


class BatteryCircle(Gtk.DrawingArea):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.percentage = 0
        self.set_draw_func(self.draw)
        self.set_size_request(64, 64)

    def set_percentage(self, percent):
        self.percentage = max(0, min(100, percent))
        self.queue_draw()

    def draw(self, area, cr, width, height):
        cx, cy = width / 2.0, height / 2.0
        radius = min(width, height) / 2.0 - 4.0

        # Background ring
        cr.set_source_rgba(0.3, 0.3, 0.3, 0.5)
        cr.set_line_width(4.0)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()

        if self.percentage > 0:
            # Foreground ring (green)
            cr.set_source_rgba(0.2, 0.8, 0.3, 1.0)
            angle = (self.percentage / 100.0) * 2 * math.pi
            start = -math.pi / 2
            cr.arc(cx, cy, radius, start, start + angle)
            cr.stroke()


class BatteryWidget(Gtk.Box):
    def __init__(self, letter):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_halign(Gtk.Align.CENTER)

        overlay = Gtk.Overlay()
        self.circle = BatteryCircle()
        overlay.set_child(self.circle)

        letter_label = Gtk.Label(label=letter)
        letter_label.set_valign(Gtk.Align.CENTER)
        letter_label.set_halign(Gtk.Align.CENTER)
        letter_label.add_css_class("heading")
        overlay.add_overlay(letter_label)

        self.append(overlay)

        self.percent_label = Gtk.Label(label="--%")
        self.percent_label.add_css_class("caption")
        self.percent_label.add_css_class("dim-label")
        self.append(self.percent_label)

    def update(self, percent):
        if percent == 0:
            self.circle.set_percentage(0)
            self.percent_label.set_label("--%")
        else:
            self.circle.set_percentage(percent)
            self.percent_label.set_label(f"{percent}%")


class NordBudsApp(Adw.Application):
    def __init__(self, **kwargs):
        super().__init__(application_id='com.github.aasheesh.NordBudsControl', **kwargs)
        self.ble = OpoBleController()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()

        self.ble.on_state_changed = self._on_ble_state_changed
        self.ble.on_battery_updated = self._on_ble_battery_updated
        self.updating_ui = False

    def _run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def do_activate(self):
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)

        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
        .budslink-pill button {
            background-color: #D3D3D3;
            color: #000000;
        }
        .budslink-pill button:checked {
            background-color: #3584e4;
            color: #ffffff;
        }
        .budslink-pill button image {
            color: inherit;
        }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        win = self.props.active_window
        if not win:
            win = Adw.ApplicationWindow(application=self)
            win.set_title("Buds")
            win.set_default_size(400, 500)
            win.set_resizable(True)

            # Toolbar view
            toolbar_view = Adw.ToolbarView()
            win.set_content(toolbar_view)

            # Header bar with window controls
            header_bar = Adw.HeaderBar()
            header_bar.set_decoration_layout(":minimize,maximize,close")
            toolbar_view.add_top_bar(header_bar)

            # Main content box (no scroll needed — content is compact)
            main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
            main_box.set_margin_top(24)
            main_box.set_margin_bottom(24)
            main_box.set_margin_start(24)
            main_box.set_margin_end(24)
            main_box.set_valign(Gtk.Align.START)
            toolbar_view.set_content(main_box)

            # Title
            title_label = Gtk.Label(label="OnePlus Nord Buds 3 Pro")
            title_label.add_css_class("title-1")
            title_label.set_halign(Gtk.Align.CENTER)
            title_label.set_margin_bottom(8)
            main_box.append(title_label)

            # Battery row
            battery_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=32)
            battery_row.set_halign(Gtk.Align.CENTER)

            self.batt_l = BatteryWidget("L")
            self.batt_r = BatteryWidget("R")
            self.batt_c = BatteryWidget("C")

            battery_row.append(self.batt_l)
            battery_row.append(self.batt_c)
            battery_row.append(self.batt_r)

            main_box.append(battery_row)

            # Connection card
            self.conn_group = Adw.PreferencesGroup()
            main_box.append(self.conn_group)

            self.conn_row = Adw.ActionRow(title="Disconnected")
            self.conn_row.set_subtitle("Not connected to earbuds")
            self.conn_button = Gtk.Button(label="Connect")
            self.conn_button.set_valign(Gtk.Align.CENTER)
            self.conn_button.add_css_class("suggested-action")
            self.conn_button.connect("clicked", self._on_connect_clicked)
            self.conn_row.add_suffix(self.conn_button)
            self.conn_group.add(self.conn_row)

            # Noise control
            nc_title = Gtk.Label(label="Noise control")
            nc_title.set_halign(Gtk.Align.START)
            nc_title.add_css_class("heading")
            nc_title.set_margin_bottom(12)
            main_box.append(nc_title)

            # Register icon search path
            base_dir = os.path.dirname(os.path.abspath(__file__))
            icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
            icon_theme.add_search_path(os.path.join(base_dir, "icons"))

            nc_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            nc_box.add_css_class("linked")
            nc_box.add_css_class("budslink-pill")
            nc_box.set_homogeneous(True)

            def make_nc_button(icon_name, tooltip, group=None):
                btn = Gtk.ToggleButton()
                if group:
                    btn.set_group(group)
                icon = Gtk.Image.new_from_icon_name(icon_name)
                icon.set_pixel_size(24)
                btn.set_child(icon)
                btn.set_tooltip_text(tooltip)
                btn.set_size_request(-1, 48)
                return btn

            self.btn_anc_on = make_nc_button("anc-on-symbolic", "Noise cancellation")
            self.btn_anc_off = make_nc_button("anc-off-symbolic", "Off", self.btn_anc_on)
            self.btn_anc_trans = make_nc_button("anc-trans-symbolic", "Transparency", self.btn_anc_on)

            nc_box.append(self.btn_anc_on)
            nc_box.append(self.btn_anc_off)
            nc_box.append(self.btn_anc_trans)

            self.btn_anc_on.connect("toggled", self._on_anc_toggled, 0x02)
            self.btn_anc_off.connect("toggled", self._on_anc_toggled, 0x01)
            self.btn_anc_trans.connect("toggled", self._on_anc_toggled, 0x04)
            main_box.append(nc_box)

            self._update_ui_state(False)

            # Auto-connect on launch
            self._on_connect_clicked(self.conn_button)

        win.present()

    def _update_ui_state(self, connected):
        if connected:
            self.conn_row.set_title("Connected")
            self.conn_row.set_subtitle(self.ble.device.name if self.ble.device else "Ready")
            self.conn_button.set_label("Disconnect")
            self.conn_button.remove_css_class("suggested-action")
            self.conn_button.add_css_class("destructive-action")
            self.btn_anc_on.set_sensitive(True)
            self.btn_anc_off.set_sensitive(True)
            self.btn_anc_trans.set_sensitive(True)
        else:
            self.conn_row.set_title("Disconnected")
            self.conn_row.set_subtitle("Not connected to earbuds")
            self.conn_button.set_label("Connect")
            self.conn_button.remove_css_class("destructive-action")
            self.conn_button.add_css_class("suggested-action")
            self.btn_anc_on.set_sensitive(False)
            self.btn_anc_off.set_sensitive(False)
            self.btn_anc_trans.set_sensitive(False)
            self.batt_l.update(0)
            self.batt_r.update(0)
            self.batt_c.update(0)

    def _on_connect_clicked(self, button):
        if self.ble.is_connected:
            asyncio.run_coroutine_threadsafe(self.ble.disconnect(), self.loop)
            self.conn_button.set_sensitive(False)
        else:
            self.conn_button.set_sensitive(False)
            self.conn_row.set_subtitle("Scanning and connecting...")
            asyncio.run_coroutine_threadsafe(self.ble.scan_and_connect(), self.loop)

    def _on_ble_state_changed(self, state):
        def update():
            if str(state).startswith("anc:"):
                try:
                    mode_hex = int(str(state).split(":")[1])
                    self.updating_ui = True
                    if mode_hex == 0x01:
                        self.btn_anc_off.set_active(True)
                    elif mode_hex == 0x02:
                        self.btn_anc_on.set_active(True)
                    elif mode_hex == 0x04:
                        self.btn_anc_trans.set_active(True)
                    self.updating_ui = False
                except Exception:
                    pass
            else:
                self.conn_button.set_sensitive(True)
                self._update_ui_state(state == "connected")
        GLib.idle_add(update)

    def _on_ble_battery_updated(self, l, r, c):
        def update():
            self.batt_l.update(l)
            self.batt_r.update(r)
            self.batt_c.update(c)
        GLib.idle_add(update)

    def _on_anc_toggled(self, button, mode_hex):
        if self.updating_ui:
            return
        if button.get_active() and self.ble.authenticated:
            asyncio.run_coroutine_threadsafe(self.ble.set_anc_mode(mode_hex), self.loop)


if __name__ == '__main__':
    app = NordBudsApp()
    sys.exit(app.run(sys.argv))
