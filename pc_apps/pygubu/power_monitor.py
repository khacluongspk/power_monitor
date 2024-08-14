#!/usr/bin/python3
import time
import serial
import binascii
import pathlib
import tkinter as tk
from tkinter import messagebox
import pygubu
import threading
import struct
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

PROJECT_PATH = pathlib.Path(__file__).parent
PROJECT_UI = PROJECT_PATH / "power_monitor.ui"
RESOURCE_PATHS = [PROJECT_PATH]

# Constants
SIGNATURE = 0x87654321
DATA_RPT_SAMPLE_SIZE = 63  # The size of the current and voltage arrays
MAX_DATA_SIZE = 100000     # Maximum number of samples for zoom-out

conversion_times = {
    "280uS": 0x3,
    "540uS": 0x4,
    "1052uS": 0x5,
    "2074uS": 0x6,
    "4120uS": 0x7
}

average_num = {
    "AVG_NUM_1"    : 0x00,
    "AVG_NUM_4"    : 0x01,
    "AVG_NUM_16"   : 0x02,
    "AVG_NUM_64"   : 0x03,
    "AVG_NUM_128"  : 0x04,
    "AVG_NUM_256"  : 0x05,
    "AVG_NUM_512"  : 0x06,
    "AVG_NUM_1024" : 0x07
}

adc_range = {
    "RANGE_0"  : 0x00,
    "RANGE_1"  : 0x01
}

class auto_generateUI:
    def __init__(self, master=None, on_first_object_cb=None):
        # Initialize the stack to keep track of xlim history
        self.xlim_stack = []
        # Initialize other properties
        self.original_xlim = None

        self.serial_port = None
        self.is_receiving = False
        self.is_measuring = False
        self.receive_thread = None
        self.current_data = np.array([])  # Store received current data here
        self.voltage_data = np.array([])  # Store received voltage data here

        self.builder = pygubu.Builder(
            on_first_object=on_first_object_cb)
        self.builder.add_resource_paths(RESOURCE_PATHS)
        self.builder.add_from_file(PROJECT_UI)
        # Main widget
        self.mainwindow: tk.Toplevel = self.builder.get_object(
            "toplevel", master)
        self.builder.connect_callbacks(self)

        # Collect the GUI objects here
        self.output_text = self.builder.get_object('text_status', master)
        self.canvas_current = self.builder.get_object('canvas_current', master)
        self.canvas_voltage = self.builder.get_object('canvas_voltage', master)
        self.avg_current_entry = self.builder.get_object('entry_average', master)
        self.marker1_text = self.builder.get_object('entry_marker1_value', master)
        self.marker2_text = self.builder.get_object('entry_marker2_value', master)
        self.port_entry = self.builder.get_object('entry_port', master)
        self.baudrate_entry = self.builder.get_object('entry_baudrate', master)
        self.optionmenu_convtime = self.builder.get_object('optionmenu_convtime', master)
        self.optionmenu_avgnum = self.builder.get_object('optionmenu_avgnum', master)
        self.optionmenu_adcrange = self.builder.get_object('optionmenu_adcrange', master)
        self.input_entry = self.builder.get_object('entry_cmd', master)

        # Process conversion time drop-down list
        self.selected_convtime_key = tk.StringVar(master)
        self.selected_convtime_key.set(next(iter(conversion_times.keys())))  # Set default value
        self.update_optionmenu_convtime_items()
        self.optionmenu_convtime['textvariable'] = self.selected_convtime_key

        # Process average num drop-down list
        self.selected_avgnum_key = tk.StringVar(master)
        self.selected_avgnum_key.set(next(iter(average_num.keys())))  # Set default value
        self.update_optionmenu_avgnum_items()
        self.optionmenu_avgnum['textvariable'] = self.selected_avgnum_key

        # Process adc range drop-down list
        self.selected_adcrange_key = tk.StringVar(master)
        self.selected_adcrange_key.set(next(iter(adc_range.keys())))  # Set default value
        self.update_optionmenu_adcrange_items()
        self.optionmenu_adcrange['textvariable'] = self.selected_adcrange_key

        # Link scrollbars
        self.vscroll = self.builder.get_object('scrollbar_vertical', master)
        self.hscroll = self.builder.get_object('scrollbar_horizontal', master)
        self.output_text.config(yscrollcommand=self.vscroll.set, xscrollcommand=self.hscroll.set)
        self.vscroll.config(command=self.output_text.yview)
        self.hscroll.config(command=self.output_text.xview)

        # Matplotlib figure for plotting current waveform
        self.figure1 = plt.Figure(figsize=(20, 3), dpi=70)
        self.ax1 = self.figure1.add_subplot(111)
        self.ax1.set_title("Current Waveform (mA)")
        self.ax1.set_xlabel("Sample")
        self.ax1.set_ylabel("Current (mA)")
        self.canvas1 = FigureCanvasTkAgg(self.figure1, master=self.canvas_current)
        self.canvas1.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Matplotlib figure for plotting volatge waveform
        self.figure2 = plt.Figure(figsize=(20, 2), dpi=70)
        self.ax2 = self.figure2.add_subplot(111)
        self.ax2.set_title("Volatge Waveform (V)")
        self.ax2.set_xlabel("Sample")
        self.ax2.set_ylabel("Volatage (V)")
        self.canvas2 = FigureCanvasTkAgg(self.figure2, master=self.canvas_voltage)
        self.canvas2.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Initialize marker positions
        self.marker1_pos = 200
        self.marker2_pos = 400
        # Add default markers
        self.marker_line1 = self.ax1.axvline(self.marker1_pos, color='red', linestyle='--')
        self.marker_line2 = self.ax1.axvline(self.marker2_pos, color='blue', linestyle='--')
        # Initialize dragging_marker
        self.dragging_marker = None
        # Connect event handlers for dragging markers
        self.canvas1.mpl_connect('button_press_event', self.on_press)
        self.canvas1.mpl_connect('button_release_event', self.on_release)
        self.canvas1.mpl_connect('motion_notify_event', self.on_motion)
        self.canvas1.mpl_connect('scroll_event', self.on_scroll)
        # Update the waveform and markers
        self.update_current_waveform(self.current_data)

    def update_optionmenu_convtime_items(self):
        menu = self.optionmenu_convtime['menu']
        menu.delete(0, 'end')  # Clear existing items
        for key in conversion_times.keys():
            menu.add_command(label=key, command=tk._setit(self.selected_convtime_key, key))

    def update_optionmenu_avgnum_items(self):
        menu = self.optionmenu_avgnum['menu']
        menu.delete(0, 'end')  # Clear existing items
        for key in average_num.keys():
            menu.add_command(label=key, command=tk._setit(self.selected_avgnum_key, key))

    def update_optionmenu_adcrange_items(self):
        menu = self.optionmenu_adcrange['menu']
        menu.delete(0, 'end')  # Clear existing items
        for key in adc_range.keys():
            menu.add_command(label=key, command=tk._setit(self.selected_adcrange_key, key))

    def update_marker_values(self):
        # Ensure marker positions are within the bounds of current_data
        marker1_index = int(self.marker1_pos)
        marker2_index = int(self.marker2_pos)

        # Get the current values at marker positions
        marker1_value = self.current_data[marker1_index] if 0 <= marker1_index < len(self.current_data) else 'N/A'
        marker2_value = self.current_data[marker2_index] if 0 <= marker2_index < len(self.current_data) else 'N/A'

        # Update text boxes
        self.marker1_text.delete(0, tk.END)
        self.marker2_text.delete(0, tk.END)

        # Helper function to format values
        def format_value(value):
            try:
                return f"{float(value):.2f}"  # Convert to float and format
            except ValueError:
                return str(value)  # Return the value as is if it can't be converted

        self.marker1_text.insert(0, format_value(marker1_value))
        self.marker2_text.insert(0, format_value(marker2_value))

    def on_scroll(self, event):
        if self.is_measuring == True:
            return

        if event.inaxes != self.ax1:
            return

        zoom_factor = 1.1
        if event.button == 'up':
            zoom_factor = 1 / zoom_factor
            self.xlim_stack.append(self.ax1.get_xlim())
        elif event.button == 'down':
            if self.xlim_stack:
                prev_xlim = self.xlim_stack.pop()
                self.ax1.set_xlim(prev_xlim)
            else:
                self.ax1.set_xlim(self.original_xlim)

        x_center = (self.marker1_pos + self.marker2_pos) / 2
        x_range = self.ax1.get_xlim()[1] - self.ax1.get_xlim()[0]
        new_x_range = x_range * zoom_factor

        if event.button == 'up':
            self.ax1.set_xlim([x_center - new_x_range / 2, x_center + new_x_range / 2])
        elif event.button == 'down':
            new_xlim = [x_center - new_x_range / 2, x_center + new_x_range / 2]
            # Ensure limits do not exceed original limits on zoom out
            self.ax1.set_xlim([
                max(new_xlim[0], self.original_xlim[0]),
                min(new_xlim[1], self.original_xlim[1])
            ])

        self.canvas1.draw()

    def on_press(self, event):
        if self.is_measuring == True:
            return

        if event.inaxes != self.ax1:
            return

        # Check if the click is close to a marker
        x_center = (self.marker1_pos + self.marker2_pos) / 2

        if(event.xdata <= self.marker1_pos) and (abs(event.xdata - self.marker1_pos) < x_center):
            self.dragging_marker = 'marker1'
        elif (event.xdata >= self.marker2_pos) and (abs(event.xdata - self.marker2_pos) < x_center):
            self.dragging_marker = 'marker2'

    def on_release(self, event):
        if self.is_measuring == True:
            return

        self.dragging_marker = None

    def on_motion(self, event):
        if self.is_measuring == True:
            return

        if not hasattr(self, 'dragging_marker'):
            return

        if event.inaxes != self.ax1:
            return

        # Update marker position based on mouse movement
        if self.dragging_marker == 'marker1':
            self.marker1_pos = min(max(event.xdata, 0), self.marker2_pos)
            self.marker_line1.set_xdata([self.marker1_pos, self.marker1_pos])
        elif self.dragging_marker == 'marker2':
            self.marker2_pos = max(min(event.xdata, len(self.current_data)), self.marker1_pos)
            self.marker_line2.set_xdata([self.marker2_pos, self.marker2_pos])

        # Update marker values in text boxes based on current data
        self.update_marker_values()

        # Recalculate the average current and update the display
        self.calculate_and_update_average()

        # Redraw the canvas
        self.canvas1.draw()

    def update_current_waveform(self, current_data):
        # Clear the axis without removing the markers
        self.ax1.clear()

        # Plot only the last MAX_DATA_SIZE samples if the data size exceeds it
        if len(current_data) > MAX_DATA_SIZE:
            self.ax1.plot(current_data[-MAX_DATA_SIZE:])
            self.original_xlim = [0, MAX_DATA_SIZE]
        else:
            self.ax1.plot(current_data)
            self.original_xlim = [0, len(current_data)]

        # Re-add the markers after plotting the waveform
        self.marker_line1 = self.ax1.axvline(self.marker1_pos, color='red', linestyle='--')
        self.marker_line2 = self.ax1.axvline(self.marker2_pos, color='blue', linestyle='--')

        # Set axis labels and title
        self.ax1.set_title("Current Waveform (mA)")
        self.ax1.set_xlabel("Sample")
        self.ax1.set_ylabel("Current (mA)")

        # Update average current display
        self.calculate_and_update_average()

        # Check and set initial x-limits
        current_xlim = self.ax1.get_xlim()
        if current_xlim[0] == current_xlim[1]:  # Check if x-limits are identical
            # Increase the range slightly to avoid identical limits
            delta = 1
            new_xlim = [current_xlim[0] - delta, current_xlim[1] + delta]
        else:
            new_xlim = self.original_xlim

        # Ensure new_xlim is valid and has distinct bounds
        if new_xlim[0] == new_xlim[1]:
            new_xlim[0] -= 1
            new_xlim[1] += 1

        self.ax1.set_xlim(new_xlim)
        self.canvas1.draw()

    def update_volatge_waveform(self, voltage_data):
        self.ax2.clear()

        # Plot only the last MAX_DATA_SIZE samples if the data size exceeds it
        if len(voltage_data) > MAX_DATA_SIZE:
            self.ax2.plot(voltage_data[-MAX_DATA_SIZE:])
        else:
            self.ax2.plot(voltage_data)

        self.ax1.set_title("Volatge Waveform (V)")
        self.ax1.set_xlabel("Sample")
        self.ax1.set_ylabel("Voltage (mA)")
        self.canvas2.draw()

    def calculate_and_update_average(self):
        if not hasattr(self, 'avg_current_entry'):
            return  # Exit if avg_current_entry is not available

        x_min, x_max = int(self.marker1_pos), int(self.marker2_pos)

        if x_min < 0:
            x_min = 0
        if x_max > len(self.current_data):
            x_max = len(self.current_data)

        selected_data = self.current_data[x_min:x_max]

        # Remove invalid values
        selected_data = selected_data[np.isfinite(selected_data)]

        if len(selected_data) > 0:
            avg_current = np.mean(selected_data)
        else:
            avg_current = 0  # Or another appropriate value

        self.avg_current_entry.config(state=tk.NORMAL)
        self.avg_current_entry.delete(0, tk.END)
        self.avg_current_entry.insert(0, f"{avg_current:.2f}")
        self.avg_current_entry.config(state="readonly")

    def execute_stop_measuring(self):
        cmd = bytearray()

        if not self.serial_port or not self.serial_port.is_open:
            messagebox.showerror("Error", "Please connect to a UART port first.")
            return

        try:
            # Run command start measuring
            cmd = bytearray([0x08, 0x00, 0x00, 0x00])
            self.serial_port.write(cmd)
            response = self.serial_port.read(16)
            self.output_text.insert(tk.END, f"Response: {response}\n")
            # We don't expect response OK after stop measure command
            # if response[0] != cmd[0] or response[1] != 0x01:
                # messagebox.showerror("Error", "Device respone error")
                # return

        except Exception as e:
            messagebox.showerror("Error", str(e))

        self.output_text.see(tk.END)

        # Update the display to show markers even without current data
        self.is_measuring = False
        self.update_current_waveform(self.current_data)

    def execute_start_measuring(self):
        cmd = bytearray()

        if not self.serial_port or not self.serial_port.is_open:
            messagebox.showerror("Error", "Please connect to a UART port first.")
            return

        try:
            # Run command start measuring
            cmd = bytearray([0x07, 0x00, 0x00, 0x00])
            self.serial_port.write(cmd)
            response = self.serial_port.read(16)
            self.output_text.insert(tk.END, f"Response: {response}\n")
            if response[0] != cmd[0] or response[1] != 0x01:
                messagebox.showerror("Error", "Device respone error")
                return

        except Exception as e:
            messagebox.showerror("Error", str(e))

        self.is_measuring = True
        self.output_text.see(tk.END)

    def execute_adc_configuration(self):
        cmd = bytearray()
        selected_conv_time = self.selected_convtime_key.get()
        hex_value = conversion_times[selected_conv_time]
        cmd.extend([0x02, 0x00, 0x00, 0x00]) # Command write config
        cmd.append(hex_value) # added cnv_time
        self.output_text.insert(tk.END, f"Selected Conversion Time: {selected_conv_time} (0x{hex_value:X})\n")

        selected_avg_num = self.selected_avgnum_key.get()
        hex_value = average_num[selected_avg_num]
        cmd.append(hex_value) # added avg_num
        self.output_text.insert(tk.END, f"Selected Average Num: {selected_avg_num} (0x{hex_value:X})\n")

        selected_adc_range = self.selected_adcrange_key.get()
        hex_value = adc_range[selected_adc_range]
        cmd.append(hex_value) # added adc_range
        cmd.append(0x01)      # added avg_alert
        self.output_text.insert(tk.END, f"Selected Adc Range: {selected_adc_range} (0x{hex_value:X})\n")
        self.output_text.insert(tk.END, f"Command: {cmd}\n")

        if not self.serial_port or not self.serial_port.is_open:
            messagebox.showerror("Error", "Please connect to a UART port first.")
            return

        try:
            # Write adc config param command
            self.serial_port.write(cmd)
            response = self.serial_port.read(16)
            self.output_text.insert(tk.END, f"Response: {response}\n")
            if response[0] != cmd[0] or response[1] != 0x01:
                messagebox.showerror("Error", "Device respone error")
                return

            # Run command configure INA229
            cmd = bytearray([0x04, 0x00, 0x00, 0x00])
            self.serial_port.write(cmd)
            response = self.serial_port.read(16)
            self.output_text.insert(tk.END, f"Response: {response}\n")
            if response[0] != cmd[0] or response[1] != 0x01:
                messagebox.showerror("Error", "Device respone error")
                return

        except Exception as e:
            messagebox.showerror("Error", str(e))

        self.output_text.see(tk.END)

    def connect(self):
        port = self.port_entry.get()
        baudrate = self.baudrate_entry.get()
        try:
            self.serial_port = serial.Serial(port, baudrate=int(baudrate), timeout=1)
            # messagebox.showinfo("Connection", f"Connected to {port} at {baudrate} baud")
            self.is_receiving = True
            self.receive_thread = threading.Thread(target=self.receive_data)
            self.receive_thread.start()
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))

    def disconnect(self):
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            messagebox.showinfo("Disconnection", "Disconnected from the UART port")
        self.is_receiving = False
        if self.receive_thread:
            self.receive_thread.join()

    def clear_output(self):
        self.output_text.delete('1.0', tk.END)

    def close(self):
        self.disconnect()
        self.mainwindow.destroy()

    def send_data(self):
        if not self.serial_port or not self.serial_port.is_open:
            messagebox.showerror("Error", "Please connect to a UART port first.")
            return

        hex_input = self.input_entry.get().strip()

        try:
            # Convert space-separated hex input to bytes
            data = binascii.unhexlify(hex_input.replace(" ", ""))
            self.serial_port.write(data)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def receive_data(self):
        while self.is_receiving:
            try:
                if self.serial_port.in_waiting >= (4 + 4 + 4 * DATA_RPT_SAMPLE_SIZE * 2):
                    data = self.serial_port.read(4 + 4 + 4 * DATA_RPT_SAMPLE_SIZE * 2)

                    # Unpack the received data
                    sign, package_id = struct.unpack('<II', data[:8])

                    # Check the signature
                    if sign == SIGNATURE:
                        voltage_data = struct.unpack('<' + 'i' * DATA_RPT_SAMPLE_SIZE, data[8:8 + 4 * DATA_RPT_SAMPLE_SIZE])
                        current_data = struct.unpack('<' + 'i' * DATA_RPT_SAMPLE_SIZE, data[8 + 4 * DATA_RPT_SAMPLE_SIZE:])

                        # Append to existing data for a smooth waveform
                        self.current_data = np.append(self.current_data, current_data)
                        if len(self.current_data) > MAX_DATA_SIZE:  # Limit the size to MAX_DATA_SIZE samples for display
                            self.current_data = self.current_data[-MAX_DATA_SIZE:]

                        # Append to existing data for a smooth waveform
                        self.voltage_data = np.append(self.voltage_data, voltage_data)
                        if len(self.voltage_data) > MAX_DATA_SIZE:  # Limit the size to MAX_DATA_SIZE samples for display
                            self.voltage_data = self.voltage_data[-MAX_DATA_SIZE:]

                        # Update current waveform
                        self.update_current_waveform(self.current_data)

                        # Update volatge waveform
                        self.update_volatge_waveform(self.voltage_data)

                        #self.output_text.insert(tk.END, f"Package ID: {package_id}\n")
                        #self.output_text.insert(tk.END, f"Current (mA): {current_data[:5]}...\n")  # Display first 5 values as a preview
                        #self.output_text.see(tk.END)
            except Exception as e:
                self.is_receiving = False
                #messagebox.showerror("Error", str(e))
                break


    def run(self):
        self.mainwindow.mainloop()


if __name__ == "__main__":
    app = auto_generateUI()
    app.run()
