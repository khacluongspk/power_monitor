import serial
import binascii
import tkinter as tk
from tkinter import ttk, messagebox
import threading

class UARTApp:
    def __init__(self, root):
        self.root = root
        self.root.title("UART Hex Communication")
        self.root.geometry("600x400")
        self.root.resizable(True, True)  # Allow the window to be maximized

        self.serial_port = None
        self.is_receiving = False
        self.receive_thread = None

        # UART Settings
        self.port_label = tk.Label(root, text="COM Port:")
        self.port_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.port_entry = tk.Entry(root)
        self.port_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        self.baudrate_label = tk.Label(root, text="Baud Rate:")
        self.baudrate_label.grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.baudrate_entry = tk.Entry(root)
        self.baudrate_entry.insert(0, "2000000")  # Default baud rate set to 2000000
        self.baudrate_entry.grid(row=1, column=1, padx=10, pady=10, sticky="ew")

        # Frame for connect/disconnect buttons
        self.button_frame = tk.Frame(root)
        self.button_frame.grid(row=2, column=0, columnspan=2, pady=10, sticky="ew")
        self.button_frame.grid_columnconfigure(0, weight=1)
        self.button_frame.grid_columnconfigure(1, weight=1)

        self.connect_button = tk.Button(self.button_frame, text="Connect", command=self.connect)
        self.connect_button.grid(row=0, column=0, padx=(10, 5), sticky="ew")

        self.disconnect_button = tk.Button(self.button_frame, text="Disconnect", command=self.disconnect)
        self.disconnect_button.grid(row=0, column=1, padx=(5, 10), sticky="ew")

        # Data input/output
        self.input_label = tk.Label(root, text="Input (Hex):")
        self.input_label.grid(row=3, column=0, padx=10, pady=10, sticky="w")
        self.input_entry = tk.Entry(root)
        self.input_entry.grid(row=3, column=1, padx=10, pady=10, sticky="ew")

        self.send_button = tk.Button(root, text="Send", command=self.send_data)
        self.send_button.grid(row=4, column=0, columnspan=2, pady=10)

        self.clear_button = tk.Button(root, text="Clear Output", command=self.clear_output)
        self.clear_button.grid(row=5, column=0, columnspan=2, pady=10)

        self.quit_button = tk.Button(root, text="Quit", command=self.close)
        self.quit_button.grid(row=6, column=0, columnspan=2, pady=10)

        self.output_label = tk.Label(root, text="Output (Hex):")
        self.output_label.grid(row=7, column=0, padx=10, pady=10, sticky="w")

        # Adding a scroll bar to the text output
        self.output_frame = tk.Frame(root)
        self.output_frame.grid(row=8, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.output_text = tk.Text(self.output_frame, height=10, width=50, wrap=tk.NONE)
        self.output_scrollbar_y = tk.Scrollbar(self.output_frame, orient=tk.VERTICAL, command=self.output_text.yview)
        self.output_scrollbar_x = tk.Scrollbar(self.output_frame, orient=tk.HORIZONTAL, command=self.output_text.xview)
        self.output_text.configure(yscrollcommand=self.output_scrollbar_y.set, xscrollcommand=self.output_scrollbar_x.set)
        self.output_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configure grid layout for resizing
        self.root.grid_rowconfigure(8, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

    def connect(self):
        port = self.port_entry.get()
        baudrate = self.baudrate_entry.get()
        try:
            self.serial_port = serial.Serial(port, baudrate=int(baudrate), timeout=1)
            messagebox.showinfo("Connection", f"Connected to {port} at {baudrate} baud")
            self.is_receiving = True
            self.receive_thread = threading.Thread(target=self.receive_data)
            self.receive_thread.start()
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))

    def disconnect(self):
        self.is_receiving = False
        if self.receive_thread:
            self.receive_thread.join()
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            messagebox.showinfo("Disconnection", "Disconnected from the UART port")
        else:
            messagebox.showerror("Error", "No UART port is currently connected")

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
                if self.serial_port.in_waiting > 0:
                    response = self.serial_port.read(self.serial_port.in_waiting)
                    hex_output = ' '.join([f'{byte:02x}' for byte in response])
                    self.output_text.insert(tk.END, f"Received: {hex_output}\n")
                    self.output_text.see(tk.END)
            except Exception as e:
                self.is_receiving = False
                messagebox.showerror("Error", str(e))
                break

    def clear_output(self):
        self.output_text.delete('1.0', tk.END)

    def close(self):
        self.is_receiving = False
        if self.receive_thread:
            self.receive_thread.join()
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = UARTApp(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()
