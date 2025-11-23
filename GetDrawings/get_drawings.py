# get_drawings.py — corrected to use tc_utils.worker_download exactly like the original flow.
# This fixes the "0 files downloaded" issue by ensuring we:
#   1) Resolve datasets & ImanFiles per part via DataManagement (server-side),
#   2) Try FMU cache copy first, and on any FMU failure cleanly fallback to Loose FMS (read tickets → HTTP),
#   3) Drive progress through a queue identical to the original script,
#   4) Mirror every progress line to get-tc-drawings.log so troubleshooting is easy.

import os
import sys
import threading
import queue
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from pathlib import Path
import traceback
from dotenv import load_dotenv
import logging
import importlib.resources
import json
import re
from PIL import Image, ImageTk

# Add project root to path to allow direct script execution
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

load_dotenv()
logging.basicConfig(level=logging.ERROR)  # Keep level at ERROR for better default logging

# Teamcenter client SDK wrapper
from teamcenter_get_drawings.ClientX.Session import Session  # type: ignore

# Shared Teamcenter logic
try:
    from teamcenter_get_drawings import tc_utils  # type: ignore
except ImportError:
    import tc_utils  # type: ignore


def _base_dir() -> Path:
    """Determines the base directory of the application, handling both frozen and script execution."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # Running as a PyInstaller bundle
        return Path(sys.executable).resolve().parent
    # Running as a script
    return Path(__file__).resolve().parent


LOG_PATH = _base_dir() / "get-tc-drawings.log"


class LogMirror:
    """A utility to write all GUI output to a log file for debugging."""

    def __init__(self, path: Path):
        """
        Initializes the logger and truncates the log file at the start of the session.

        Args:
            path: The path to the log file.
        """
        self.path = path
        self._lock = threading.Lock()
        try:
            # Clear the log file on startup
            self.path.write_text("", encoding="utf-8")
        except IOError as e:
            print(f"Warning: Could not clear log file {self.path}: {e}")

    def write(self, line: str):
        """
        Atomically writes a line to the log file.

        Args:
            line: The string message to write.
        """
        if not line.strip():
            return
        line = line if line.endswith("\n") else f"{line}\n"
        with self._lock:
            try:
                with self.path.open("a", encoding="utf-8", errors="ignore") as f:
                    f.write(line)
            except IOError as e:
                print(f"Warning: Could not write to log file {self.path}: {e}")


# -------- Settings Management --------
def get_settings_path() -> Path:
    """Returns the path to the settings file, ensuring the directory exists."""
    settings_dir = Path.home() / ".get_tc_drawings"
    settings_dir.mkdir(exist_ok=True)
    return settings_dir / "settings.json"


def load_settings() -> dict:
    """Loads settings from the JSON file."""
    path = get_settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading settings: {e}")
        return {}


def save_settings(settings: dict):
    """Saves settings to the JSON file."""
    path = get_settings_path()
    try:
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except IOError as e:
        print(f"Error saving settings: {e}")


# -------- GUI Application --------
class App(tk.Tk):
    """The main GUI application window for the Teamcenter Drawing Downloader."""

    def __init__(self):
        """Initializes the application window, widgets, and state."""
        super().__init__()
        self.settings = load_settings()

        # Load Azure theme for a modern look
        try:
            theme_path = importlib.resources.files("teamcenter_get_drawings").joinpath("azure.tcl")
            self.tk.call("source", str(theme_path))
        except (tk.TclError, ModuleNotFoundError, AttributeError) as e:
            print(f"Azure theme not found or failed to load, using default theme. Error: {e}")

        self.title("Get Teamcenter Drawings")
        try:
            # Check for icon in base dir (script execution) or in subdirectory (Nuitka build)
            path1 = _base_dir() / "app.ico"
            path2 = _base_dir() / "teamcenter_get_drawings" / "app.ico"

            if path1.exists():
                self.iconbitmap(path1)
            elif path2.exists():
                self.iconbitmap(path2)
        except Exception as e:
            print(f"Warning: Could not load application icon: {e}")
        self.geometry("800x600")
        self.minsize(720, 520)

        self.mirror = LogMirror(LOG_PATH)
        self.cancel_evt = threading.Event()
        self.q: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.worker: threading.Thread | None = None

        self._setup_widgets()
        self._toggle_theme()  # Apply initial theme based on settings

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _setup_widgets(self):
        """Creates and arranges all the widgets in the main window."""
        self.frm = ttk.Frame(self, padding=12)
        self.frm.pack(fill="both", expand=True)

        r = 0
        # User ID and Password fields
        ttk.Label(self.frm, text="User ID").grid(row=r, column=0, sticky="w", pady=(4, 0))
        self.user_var = tk.StringVar(value=os.getenv("TCUSER", ""))
        ttk.Entry(self.frm, textvariable=self.user_var, font=("Segoe UI", 10)).grid(
            row=r, column=1, sticky="ew", pady=(4, 0)
        )
        r += 1

        ttk.Label(self.frm, text="Password").grid(row=r, column=0, sticky="w", pady=(4, 0))
        self.pw_var = tk.StringVar(value=os.getenv("TCPASSWORD", ""))
        ttk.Entry(self.frm, textvariable=self.pw_var, show="*", font=("Segoe UI", 10)).grid(
            row=r, column=1, sticky="ew", pady=(4, 0)
        )
        r += 1

        # Item IDs input area
        ttk.Label(self.frm, text="Item IDs\n(one per line)").grid(row=r, column=0, sticky="nw", pady=(8, 0))
        self.ids_txt = tk.Text(self.frm, height=8, font=("Segoe UI", 10))
        self.ids_txt.grid(row=r, column=1, sticky="nsew", pady=(8, 0))
        r += 1

        # Download folder selection
        ttk.Label(self.frm, text="Download folder").grid(row=r, column=0, sticky="w", pady=(8, 0))
        default_folder = self.settings.get("download_folder", str(_base_dir() / "Downloads"))
        self.out_var = tk.StringVar(value=default_folder)
        self.row2 = ttk.Frame(self.frm)
        ttk.Entry(self.row2, textvariable=self.out_var, font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True)
        ttk.Button(self.row2, text="Browse…", command=self._pick_dir).pack(side="left", padx=(8, 0))
        self.row2.grid(row=r, column=1, sticky="ew", pady=(8, 0))
        r += 1

        # Options checkboxes
        self.check_frm = ttk.Frame(self.frm)
        self.latest_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.check_frm, text="Only latest revisions", variable=self.latest_var).pack(
            side="left", padx=(0, 10)
        )

        self.dark_mode_var = tk.BooleanVar(value=self.settings.get("dark_mode", False))
        ttk.Checkbutton(self.check_frm, text="Dark Mode", variable=self.dark_mode_var, command=self._toggle_theme).pack(
            side="left"
        )
        self.check_frm.grid(row=r, column=1, sticky="w")
        r += 1

        ttk.Separator(self.frm).grid(row=r, column=0, columnspan=2, sticky="ew", pady=(8, 8))
        r += 1

        # Progress bar and output console
        ttk.Label(self.frm, text="Downloading…").grid(row=r, column=0, sticky="w")
        self.pbar = ttk.Progressbar(self.frm, mode="indeterminate")
        self.pbar.grid(row=r, column=1, sticky="ew")
        r += 1

        self.out_txt = tk.Text(self.frm, height=14, state="disabled", wrap="word", font=("Segoe UI", 10))
        self.out_txt.grid(row=r, column=0, columnspan=2, sticky="nsew")
        r += 1

        # Action buttons
        self.btns = ttk.Frame(self.frm)
        ttk.Button(self.btns, text="Start", command=self._start).pack(side="left", padx=(0, 4))
        ttk.Button(self.btns, text="Cancel", command=self._cancel).pack(side="left", padx=4)
        ttk.Button(self.btns, text="Help", command=self._show_help).pack(side="left", padx=4)
        ttk.Button(self.btns, text="Quit", command=self._on_closing).pack(side="left", padx=(4, 0))
        self.btns.grid(row=r, column=1, sticky="e", pady=(8, 0))
        r += 1

        # Configure resizing behavior
        self.frm.columnconfigure(1, weight=1)
        self.frm.rowconfigure(2, weight=1)  # Item IDs text area
        self.frm.rowconfigure(7, weight=1)  # Output text area

    def _on_closing(self):
        """Saves settings and gracefully exits the application."""
        self.settings["download_folder"] = self.out_var.get()
        self.settings["dark_mode"] = self.dark_mode_var.get()
        save_settings(self.settings)
        if self.worker and self.worker.is_alive():
            self.cancel_evt.set()
            self.worker.join(timeout=2.0)
        self.destroy()

    def _pick_dir(self):
        """Opens a dialog to choose the download directory."""
        d = filedialog.askdirectory(initialdir=self.out_var.get() or os.getcwd())
        if d:
            self.out_var.set(d)

    def _toggle_theme(self):
        """Switches the GUI theme between light and dark mode."""
        try:
            theme = "selenized" if self.dark_mode_var.get() else "light"
            self.tk.call("set_theme", theme)
        except tk.TclError as e:
            print(f"Azure theme could not be changed: {e}")

    def _show_help(self):
        """Displays the README.md content in a new window."""
        try:
            content = (
                importlib.resources.files("teamcenter_get_drawings").joinpath("README.md").read_text(encoding="utf-8")
            )
        except Exception as e:
            messagebox.showerror(
                "Help Not Found", f"The help file (README.md) could not be loaded from the package.\n\nError: {e}"
            )
            return

        help_win = tk.Toplevel(self)
        help_win.title("Help")
        help_win.geometry("700x500")
        help_win.images = []  # type: ignore[attr-defined]  Persist image references

        # Configure colors based on the current theme
        is_dark = self.dark_mode_var.get()
        if is_dark:
            bg_color = "#0e4956"  # selenized-bg
            fg_color = "#adbcbc"  # selenized-fg
            code_bg = "#275b69"   # selenized-bg_2
            code_fg = "#fef3da"   # selenized-fg_2
        else:
            bg_color = "white"
            fg_color = "black"
            code_bg = "#f0f0f0"
            code_fg = "black"

        help_win.configure(background=bg_color)

        txt = ScrolledText(help_win, wrap="word", padx=10, pady=10, background=bg_color, foreground=fg_color)
        txt.pack(expand=True, fill="both")

        # --- Basic Markdown Renderer ---
        h1_font = tkfont.Font(family="Segoe UI", size=16, weight="bold")
        h2_font = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        bold_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        italic_font = tkfont.Font(family="Segoe UI", size=10, slant="italic")
        code_font = tkfont.Font(family="Consolas", size=10)

        txt.tag_configure("h1", font=h1_font, spacing1=5, spacing3=10)
        txt.tag_configure("h2", font=h2_font, spacing1=5, spacing3=8)
        txt.tag_configure("bold", font=bold_font)
        txt.tag_configure("italic", font=italic_font)

        txt.tag_configure(
            "code",
            font=code_font,
            background=code_bg,
            foreground=code_fg,
            lmargin1=10,
            lmargin2=10,
            spacing1=10,
            spacing3=10,
        )

        in_code_block = False
        code_block_lines = []

        def flush_code_block():
            if not code_block_lines:
                return
            block_text = "\n".join(code_block_lines).replace("<br>", "\n")
            lines = [l.rstrip() if l.endswith("  ") else l for l in block_text.split("\n")]
            txt.insert("end", "\n".join(lines) + "\n", "code")
            code_block_lines.clear()

        # Process content line by line for markdown rendering
        for line in content.splitlines():
            if line.strip() == "```":
                in_code_block = not in_code_block
                if not in_code_block:
                    flush_code_block()
                continue

            if in_code_block:
                code_block_lines.append(line)
            else:
                img_match = re.match(r"!\s*\[.*?\]\s*\((.*?)\)", line.strip())
                if img_match:
                    image_path_str = img_match.group(1)
                    try:
                        image_path = importlib.resources.files("teamcenter_get_drawings").joinpath(
                            image_path_str.strip("./")
                        )

                        # Use Pillow to open and resize the image
                        img = Image.open(image_path) # type: ignore[attr-defined]

                        if img.width > 600:
                            ratio = 600 / img.width
                            new_height = int(img.height * ratio)
                            img = img.resize((600, new_height), Image.Resampling.LANCZOS)

                        photo = ImageTk.PhotoImage(img)
                        help_win.images.append(photo) # type: ignore[attr-defined]
                        txt.image_create("end", image=photo)
                        txt.insert("end", "\n")
                    except Exception as img_e:
                        txt.insert("end", line + "\n")
                        print(f"Failed to load image {image_path_str}: {img_e}")
                elif line.startswith("## "):
                    txt.insert("end", line[3:] + "\n", "h2")
                elif line.startswith("# "):
                    txt.insert("end", line[2:] + "\n", "h1")
                else:
                    processed_line = line.replace("<br>", "\n")
                    if line.endswith("  "):
                        processed_line = processed_line.rstrip()

                    parts = re.split(r"(\*\*.*?\*\*|\*.*?\*)", processed_line)
                    for part in parts:
                        if part.startswith("**") and part.endswith("**"):
                            txt.insert("end", part[2:-2], "bold")
                        elif part.startswith("*") and part.endswith("*"):
                            txt.insert("end", part[1:-1], "italic")
                        else:
                            txt.insert("end", part)
                    txt.insert("end", "\n")

        flush_code_block()

        txt.configure(state="disabled")
        # --- End Renderer ---

        close_button = ttk.Button(help_win, text="Close", command=help_win.destroy)
        close_button.pack(pady=10)

    def _println(self, msg: str):
        """Prints a message to the GUI's output console and the log file."""
        self.out_txt.configure(state="normal")
        self.out_txt.insert("end", msg + "\n")
        self.out_txt.see("end")
        self.out_txt.configure(state="disabled")
        self.mirror.write(msg)

    def _start(self):
        """Validates inputs and starts the background download worker thread."""
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "A download is already in progress.")
            return

        host = os.getenv("TC_SERVER_HOST") or os.getenv("TC_URL") or "http://GVWTCUPRODAPP.gvwholdings.com:8001/tc"
        user = self.user_var.get().strip()
        pw = self.pw_var.get()
        item_ids = [s.strip() for s in self.ids_txt.get("1.0", "end").splitlines() if s.strip()]
        dest = Path(self.out_var.get().strip()).resolve()

        if not all([host, user, pw, item_ids]):
            messagebox.showerror("Missing Information", "Please provide User ID, Password, and at least one Item ID.")
            return

        self.cancel_evt.clear()
        dest.mkdir(parents=True, exist_ok=True)

        self.pbar.start(15)
        self._println(f"Preparing {len(item_ids)} item id(s)…")
        self.worker = threading.Thread(
            target=self._run, args=(host, user, pw, item_ids, dest, self.latest_var.get()), daemon=True
        )
        self.worker.start()
        self.after(100, self._pump)

    def _cancel(self):
        """Signals the worker thread to cancel the current operation."""
        if self.worker and self.worker.is_alive():
            self.cancel_evt.set()
            self._println("Cancel requested…")

    def _pump(self):
        """Periodically checks the queue for messages from the worker and updates the GUI."""
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "msg":
                    self._println(str(payload))
                elif kind == "error":
                    self._println(f"ERROR: {payload}")
                    messagebox.showerror("Error", str(payload))
                elif kind == "done":
                    total_saved = sum(len(v or []) for v in (payload or {}).values()) # type: ignore[attr-defined]
                    self._println(f"Done. Saved {total_saved} file(s).")
                else:
                    self._println(f"[{kind}] {payload}")
        except queue.Empty:
            pass

        if self.worker and self.worker.is_alive():
            self.after(120, self._pump)
        else:
            self.pbar.stop()
            self.pbar.configure(mode="determinate", value=100)

    def _run(self, host: str, user: str, pw: str, item_ids: list[str], dest: Path, latest_only: bool):
        """The target function for the worker thread; handles the entire TC operation."""
        sess = None
        try:
            self._println(f"Connecting to {host}…")
            sess = Session(host)

            # Manually set credentials on the manager before login
            cred = Session.credentialManager
            cred.name = user
            cred.password = pw
            group = os.getenv("TC_GROUP") or os.getenv("TCGROUP") or ""
            role = os.getenv("TC_ROLE") or os.getenv("TCROLE") or ""
            if group or role:
                cred.SetGroupRole(group or "", role or "")

            user_obj = sess.login()
            if not user_obj:
                self.q.put(("error", "Login failed. Check credentials or Teamcenter connection."))
                return

            self._println(f"Login OK for {user_obj.User_id}")

            # Execute the download logic
            tc_utils.worker_download(
                sess.getConnection(),
                item_ids,
                str(dest),
                self.q,
                self.cancel_evt,
                latest_only,
            )

        except Exception as ex:
            tb = traceback.format_exc()
            self.q.put(("error", f"{ex}\n{tb}"))
        finally:
            if sess and sess.is_logged_in():
                self._println("Logging out…")
                sess.logout()
                self._println("Logout OK.")


def main():
    """Creates and runs the main application loop."""
    App().mainloop()


if __name__ == "__main__":
    main()
