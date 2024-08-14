#!/usr/bin/python3
import pathlib
import tkinter as tk
import pygubu

PROJECT_PATH = pathlib.Path(__file__).parent
PROJECT_UI = PROJECT_PATH / "power_monitor.ui"
RESOURCE_PATHS = [PROJECT_PATH]


class auto_generateUI:
    def __init__(self, master=None, on_first_object_cb=None):
        self.builder = pygubu.Builder(
            on_first_object=on_first_object_cb)
        self.builder.add_resource_paths(RESOURCE_PATHS)
        self.builder.add_from_file(PROJECT_UI)
        # Main widget
        self.mainwindow: tk.Toplevel = self.builder.get_object(
            "toplevel", master)
        self.builder.connect_callbacks(self)

        # Link scrollbars
        self.text_status = self.builder.get_object('text_status', master)
        self.vscroll = self.builder.get_object('scrollbar_vertical', master)
        self.hscroll = self.builder.get_object('scrollbar_horizontal', master)

        self.text_status.config(yscrollcommand=self.vscroll.set, xscrollcommand=self.hscroll.set)
        self.vscroll.config(command=self.text_status.yview)
        self.hscroll.config(command=self.text_status.xview)

    def run(self):
        self.mainwindow.mainloop()


if __name__ == "__main__":
    app = auto_generateUI()
    app.run()
