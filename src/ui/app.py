import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import pystray
from PIL import Image
from watchdog.observers import Observer

from assets import get_asset
from ui.quick_chat import QuickChatDialog
from ui.utils import create_warning_label
from utils import *


class App:
    def __init__(self, setting_file, config, gui_config):
        self.setting_file = setting_file
        self.config = config
        self.ui_config = gui_config
        self.locale_dict = {value: key for key, value in LOCALE_CODES.items()}
        self.game_client = config.get("GameClient", "")
        self.observer: Observer | None = None
        self.watching = False
        self.watch_thread = None

        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{VERSION}")
        self.window_width = 300
        self.window_height = 330
        self.control_padding = 8
        self.layout_padding = 10

        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        self.position_top = int(self.screen_height / 2 - self.window_height / 2)
        self.position_right = int(self.screen_width / 2 - self.window_width / 2)
        self.root.geometry(f"{self.window_width}x{self.window_height}+{self.position_right}+{self.position_top}")
        self.root.iconbitmap(get_asset('icon.ico'))
        self.root.minsize(self.window_width, self.window_height)
        self.root.maxsize(self.window_width + 50, self.window_height + 50)
        # self.root.resizable(False, False)

        self.create_menu_bar()
        self.selected_locale = config.get("Locale", "zh_CN")
        self.create_locale_groupbox()
        self.create_quick_chat_groupbox()

        self.create_status_bar()
        self.create_launch_button()
        self.tray_app = self.create_tray_app()
        self.tray_thread = threading.Thread(target=self.tray_app.run)

        self.root.pack_propagate(True)

        self.root.protocol("WM_DELETE_WINDOW", self.on_window_minimizing)

    def create_tray_app(self):
        return pystray.Icon(
            APP_NAME,
            Image.open(get_asset("tray_icon.png")),
            f"{APP_NAME} v{VERSION}",
            menu=self.create_tray_menu()
        )

    def create_tray_menu(self):
        return pystray.Menu(
            pystray.MenuItem("显示主窗口", self.on_window_restoring, default=True),
            pystray.MenuItem("帮助", self.show_about),
            pystray.MenuItem("退出", self.on_window_closing)
        )

    def create_menu_bar(self):
        self.menu_bar = tk.Menu(self.root)
        self.setting_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.setting_menu.add_command(label="自动检测游戏配置文件", command=self.detect_metadata_file)
        self.setting_menu.add_command(label="手动选择游戏配置文件", command=self.choose_metadata_file)
        # self.setting_menu.add_command(label="恢复默认", command=self.reset_settings)
        self.minimize_on_closing = tk.BooleanVar(value=self.config.get("MinimizeOnClosing", True))
        self.setting_menu.add_checkbutton(label="关闭时最小化到托盘", variable=self.minimize_on_closing)
        self.menu_bar.add_cascade(label="设置", menu=self.setting_menu)
        self.help_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.help_menu.add_command(label="关于", command=self.show_about)
        self.help_menu.add_command(label="检查更新", command=lambda: check_for_updates(self.no_new_version_fn))
        self.menu_bar.add_cascade(label="帮助", menu=self.help_menu)
        self.root.config(menu=self.menu_bar)

    def create_locale_groupbox(self):
        self.locale_groupbox = tk.LabelFrame(self.root, text="语言设置")
        self.locale_var = tk.StringVar(value=LOCALE_CODES[self.selected_locale])
        self.locale_dropdown = ttk.Combobox(self.locale_groupbox, textvariable=self.locale_var, state="readonly", exportselection=True)
        self.locale_dropdown['values'] = list(self.locale_dict.keys())
        self.locale_dropdown.current(list(self.locale_dict.values()).index(self.selected_locale))
        self.locale_dropdown.pack(padx=self.control_padding, pady=self.control_padding, fill=tk.BOTH)
        self.locale_dropdown.bind("<<ComboboxSelected>>", self.on_locale_changed)
        self.locale_groupbox.pack(fill=tk.BOTH, padx=self.layout_padding, pady=self.layout_padding)

    def on_quick_chat_enable_change(self, *args):
        if not self.config.get("QuickChatNoteNotAsk", False) and self.quick_chat_enabled.get():
            decision = easygui.buttonbox('您是否已根据《注意事项》设置好"无边框"模式？',
                                         "启用前的准备", ["已设置好", "还没有", "已设置好，不要再提醒"])
            if decision == "还没有":
                self.quick_chat_enabled.set(False)
                return
            elif decision == "已设置好，不要再提醒":
                self.config["QuickChatNoteNotAsk"] = True

        state = tk.NORMAL if self.quick_chat_enabled.get() else tk.DISABLED
        self.shortcut_dropdown.config(state=state)
        self.set_chat_button.config(state=state)
        if self.quick_chat_enabled.get():
            self.update_status("一键喊话已启用")
            create_quick_chat_file(CONFIG_FILENAME)
            self.quick_chat_dialog.set_hotkey(self.shortcut_var.get())
        else:
            self.update_status("一键喊话已禁用")
            self.quick_chat_dialog.disable_hotkey()

    def create_quick_chat_groupbox(self):
        self.quick_chat_groupbox = tk.LabelFrame(self.root, text="一键喊话设置")
        self.quick_chat_warning_label = create_warning_label(self.quick_chat_groupbox, "\u26A1 使用前请仔细阅读", "注意事项", "notes.pdf")
        self.quick_chat_warning_label.pack(padx=self.control_padding, pady=self.control_padding, fill=tk.BOTH)
        self.quick_chat_enabled_setting = self.config.get("QuickChatEnabled", False)
        self.quick_chat_enabled = tk.BooleanVar(value=self.quick_chat_enabled_setting)
        self.quick_chat_enabled.trace("w", self.on_quick_chat_enable_change)
        state = tk.NORMAL if self.quick_chat_enabled.get() else tk.DISABLED
        self.quick_chat_checkbox = tk.Checkbutton(self.quick_chat_groupbox, text="一键喊话", variable=self.quick_chat_enabled)
        self.quick_chat_checkbox.pack()

        self.shortcut_frame = tk.Frame(self.quick_chat_groupbox)

        self.shortcut_label = tk.Label(self.shortcut_frame, text="快捷键")
        self.shortcut_label.pack(side=tk.LEFT)
        self.shortcut_var = tk.StringVar(value=self.config.get("QuickChatShortcut", "`"))

        self.shortcut_dropdown = ttk.Combobox(self.shortcut_frame, state=state, textvariable=self.shortcut_var, exportselection=True)
        available_shortcuts = ["`", "Alt", "Ctrl", "Shift", "Tab"]
        self.shortcut_dropdown['values'] = available_shortcuts
        self.shortcut_dropdown.current(available_shortcuts.index(self.shortcut_var.get()))
        self.shortcut_dropdown.bind("<<ComboboxSelected>>", self.on_shortcut_changed)
        self.shortcut_dropdown.pack(side=tk.RIGHT)

        self.shortcut_frame.pack(padx=self.layout_padding)

        self.set_chat_button = tk.Button(self.quick_chat_groupbox, text="设置喊话内容", state=state, command=self.open_quick_chat_file)
        self.set_chat_button.pack(padx=self.control_padding, pady=self.control_padding, fill=tk.BOTH)

        self.quick_chat_groupbox.pack(fill=tk.BOTH, padx=self.layout_padding, pady=self.layout_padding)

        self.quick_chat_dialog = QuickChatDialog(self.root, self.config, self.ui_config)
        if self.quick_chat_enabled_setting:
            self.quick_chat_dialog.set_hotkey(self.config.get('QuickChatShortcut', '`'))
        else:
            self.quick_chat_dialog.disable_hotkey()

    def open_quick_chat_file(self):
        print("Opening quick chat file...")
        if not os.path.exists(QUICK_CHAT_FILENAME):
            create_quick_chat_file(CONFIG_FILENAME)
        subprocess.run(['notepad.exe', QUICK_CHAT_FILENAME], check=False)

    def create_launch_button(self):
        self.image = tk.PhotoImage(file=get_asset("button_icon.png"))
        self.launch_button = tk.Button(self.root, text="英雄联盟，启动！", image=self.image, compound=tk.LEFT,
                                       command=self.start)
        self.launch_button.pack(side=tk.BOTTOM, pady=self.layout_padding)

    def create_status_bar(self):
        self.status_var = tk.StringVar(value="准备就绪")
        self.status_bar = tk.Label(self.root, textvariable=self.status_var, bd=1, relief=tk.RIDGE, anchor=tk.W, foreground="gray")
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def update_status(self, message):
        self.status_var.set(message)

    def show_about(self, icon=None, item=None):
        pady = self.layout_padding // 2
        self.about_window = tk.Toplevel(self.root)
        self.about_window.title("关于")
        self.about_window.iconbitmap(get_asset("icon.ico"))
        self.about_window.geometry(f"+{self.position_right}+{self.position_top}")
        self.about_window.protocol("WM_DELETE_WINDOW", lambda: self.on_about_window_closing(create_tray=icon is not None))
        self.app_name_label = tk.Label(self.about_window, text=f"{APP_NAME} v{VERSION}")
        self.app_name_label.pack(padx=self.control_padding, pady=pady)

        self.author_label = tk.Label(self.about_window, text="作者：Chenglong Ma", fg="blue", cursor="hand2")
        self.author_label.pack(padx=self.control_padding, pady=pady)
        self.author_label.bind("<Button-1>", lambda event: open_my_homepage())

        self.homepage_label = tk.Label(self.about_window, text=f"GitHub：{REPO_NAME}", fg="blue", cursor="hand2")
        self.homepage_label.pack(padx=self.control_padding, pady=pady)
        self.homepage_label.bind("<Button-1>", lambda event: open_repo_page())

        self.copyright_label = tk.Label(self.about_window, text="Copyright © 2024 Chenglong Ma. All rights reserved.")
        self.copyright_label.pack(padx=self.control_padding, pady=pady)

    def on_about_window_closing(self, create_tray=False):
        self.about_window.destroy()
        # if create_tray:
        #     self.run_tray_app()

    def no_new_version_fn(self):
        messagebox.showinfo("检查更新", "当前已是最新版本")
        self.update_status("当前已是最新版本")

    def start_game(self, settings):
        self.update_status("正在启动游戏...")
        product_install_root = settings['product_install_root']

        product_install_root = product_install_root if os.path.exists(product_install_root) else "C:/"

        game_clients_in_settings = [os.path.join(product_install_root, "Riot Client/RiotClientServices.exe")]

        game_clients = filter_existing_files(to_list(self.game_client) + game_clients_in_settings)
        if not game_clients or len(game_clients) == 0:
            self.update_status("未找到 RiotClientServices.exe，请手动启动游戏。")
            return

        self.update_status("英雄联盟，启动！")
        self.game_client = os.path.normpath(game_clients[0])
        subprocess.run(['explorer.exe', self.game_client], check=False)

    def start(self):
        self.update_status("正在更新配置文件...")
        settings = update_settings(self.setting_file, self.selected_locale, msg_callback_fn=self.update_status)
        if not settings:
            messagebox.showerror("错误", "配置文件更新失败，无法启动游戏。")
            return

        self.start_game(settings)
        self.on_window_minimizing(True)

    def wait_for_observer_stopping(self):
        print("Stopping observer...")
        self.watching = False
        if self.observer is not None and self.observer.is_alive():
            self.observer.stop()
            # self.observer.join()
            print("Observer stopped")
        self.observer = None

    def start_watch_thread(self):
        self.wait_for_observer_stopping()
        self.watch_thread = threading.Thread(target=self.watch_file)
        self.watch_thread.start()

    def watch_file(self):
        self.wait_for_observer_stopping()
        event_handler = FileWatcher(self.setting_file, self.selected_locale)
        self.observer = Observer()
        self.observer.schedule(event_handler, path=os.path.dirname(self.setting_file), recursive=False)
        self.watching = True
        self.observer.start()
        print(f"Watching {self.setting_file}...")

        try:
            while self.watching:
                time.sleep(1)
        except KeyboardInterrupt:
            self.observer.stop()
        except Exception as e:
            self.update_status(f"Error: {e}")
            self.observer.stop()

    def detect_metadata_file(self):
        is_yes = tk.messagebox.askyesno("提示", "您确定要重新检测以修改已有配置？")
        if is_yes:
            setting_files = detect_metadata_file()
            if setting_files:
                self.setting_file = setting_files[0]  # TODO: multiple files support
                self.sync_config()
                msg = "游戏配置文件已更新"
            else:
                msg = "未找到有效配置，将继续使用之前的配置"
            self.update_status(msg)
            tk.messagebox.showinfo("提示", msg)

    def choose_metadata_file(self):
        is_yes = tk.messagebox.askyesno("提示", "已自动检测到游戏配置文件，您确定要手动选择吗？")
        if is_yes:
            selected_file = open_metadata_file_dialog(title="请选择 league_of_legends.live.product_settings.yaml 文件",
                                                      file_types=[('Riot 配置文件', '*.yaml'), ('所有文件', '*.*')],
                                                      initial_dir=DEFAULT_METADATA_DIR, initial_file=DEFAULT_METADATA_FILE)
            if selected_file:
                self.setting_file = selected_file
                self.sync_config()
                msg = "游戏配置文件已更新"
            else:
                msg = "未找到有效配置，将继续使用之前的配置"
            self.update_status(msg)
            tk.messagebox.showinfo("提示", msg)

    def on_locale_changed(self, event):
        current_value = self.locale_var.get()
        self.selected_locale = self.locale_dict[current_value]
        self.update_status(f"语言将被设置为：{current_value}")

    def on_shortcut_changed(self, event):
        current_value = self.shortcut_var.get()
        self.update_status(f"快捷键将被设置为：{current_value}")
        self.quick_chat_dialog.set_hotkey(current_value)

    def on_window_restoring(self, icon: pystray.Icon = None, item=None):
        self.root.after(0, self.root.deiconify)

    def on_window_showing(self, event=None):
        if self.root.winfo_viewable():
            print("Window is already visible")
            return
        print("Window is now visible", event)

    def on_window_minimizing(self, force_minimize=False):
        print("Window is now minimized")
        if force_minimize or self.minimize_on_closing.get():
            self.sync_config()
            self.root.after(0, self.root.withdraw)
        else:
            self.on_window_closing(self.tray_app)

    def run(self):
        self.start_watch_thread()
        self.tray_thread.start()
        self.root.mainloop()
        self.tray_thread.join()

    def sync_config(self):
        default_config = {
            "@注意": r"请使用\或/做为路径分隔符，如 C:\ProgramData 或 C:/ProgramData",
            "@SettingFile": "请在下方填写 league_of_legends.live.product_settings.yaml 文件路径",
            "SettingFile": self.setting_file,
            "@GameClient": "请在下方填写 RiotClientServices.exe 文件路径",
            "GameClient": self.game_client,
            "Locale": self.selected_locale,
            "QuickChatEnabled": self.quick_chat_enabled.get(),
            "QuickChatShortcut": self.shortcut_var.get(),
            "MinimizeOnClosing": self.minimize_on_closing.get(),
            "Process Name": "League of Legends.exe"
        }
        self.config.update(default_config)
        self.config.update(self.quick_chat_dialog.user_config)
        write_json(CONFIG_FILENAME, self.config)
        self.ui_config.update(self.quick_chat_dialog.ui_config)
        write_json(GUI_CONFIG_FILENAME, self.ui_config)
        print("Configuration file updated")

    def on_window_closing(self, icon: pystray.Icon = None, item=None):

        close = messagebox.askyesno("退出", "退出后再启动游戏时文本和语音将恢复为默认设置\n您确定要退出吗？")
        if close:
            self.wait_for_observer_stopping()
            if icon:
                icon.stop()
            self.sync_config()
            self.root.after(0, self.root.destroy)
