#!/usr/bin/env python3
"""
速率限制配置签名工具 - 增强版
支持文件夹选择和文件完整性哈希计算
"""

import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import configparser
import secrets
from gmssl import sm2, sm3, func
import sys
import os
import traceback
import re
import base64
import hashlib
import subprocess
from typing import Union, Dict

# SM2补丁（与原版保持一致）
original_sm3_z = sm2.CryptSM2._sm3_z
def fixed_sm3_z(self, uid: Union[str, bytes]):
    if isinstance(uid, str):
        uid_bytes = uid.encode('utf-8')
    else:
        uid_bytes = uid
    return original_sm3_z(self, uid_bytes)

sm2.CryptSM2._sm3_z = fixed_sm3_z

original_verify = sm2.CryptSM2.verify
def fixed_verify(self, sign: str, data: bytes, uid: Union[str, bytes]) -> bool:
    z_hex = self._sm3_z(uid=uid)
    message_bytes = z_hex.encode('utf-8') + data
    hash_to_verify = sm3.sm3_hash(func.bytes_to_list(message_bytes))
    return original_verify(self, sign, bytes.fromhex(hash_to_verify))

sm2.CryptSM2.verify = fixed_verify

def _encode_der_length(length: int) -> bytes:
    """辅助函数：编码 ASN.1 DER 长度。"""
    if length < 128:
        return bytes([length])
    else:
        length_bytes = length.to_bytes((length.bit_length() + 7) // 8, 'big')
        return bytes([0x80 | len(length_bytes)]) + length_bytes

def _generate_pem_from_hex(public_key_hex: str) -> str:
    """从十六进制公钥字符串生成PEM格式内容。"""
    public_key_bytes = bytes.fromhex(public_key_hex)
    oid_ec_pubkey = b'\x06\x07\x2a\x86\x48\xce\x3d\x02\x01'
    oid_sm2p256v1 = b'\x06\x08\x2a\x81\x1c\xcf\x55\x01\x82\x2d'
    algorithm_der = b'\x30' + _encode_der_length(len(oid_ec_pubkey) + len(oid_sm2p256v1)) + oid_ec_pubkey + oid_sm2p256v1
    bit_string_content = b'\x00' + public_key_bytes
    public_key_der_part = b'\x03' + _encode_der_length(len(bit_string_content)) + bit_string_content
    sequence_content = algorithm_der + public_key_der_part
    der_data = b'\x30' + _encode_der_length(len(sequence_content)) + sequence_content
    b64_data = base64.b64encode(der_data).decode('utf-8')
    pem_lines = [b64_data[i:i+64] for i in range(0, len(b64_data), 64)]
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(pem_lines) + "\n-----END PUBLIC KEY-----\n"

def _extract_hex_from_pem(pem_content: str) -> str:
    """从PEM格式的公钥字符串中稳健地提取十六进制公钥。"""
    try:
        pem_lines = pem_content.strip().split('\n')
        base64_str = "".join(line for line in pem_lines if not line.startswith("-----"))
        der_data = base64.b64decode(base64_str)
        public_key_bytes = der_data[-65:]
        if public_key_bytes[0] != 0x04:
            raise ValueError("PEM公钥内容无效，未找到 0x04 (非压缩) 标识。")
        return public_key_bytes.hex()
    except Exception as e:
        raise ValueError(f"无法解析PEM公钥: {e}") from e

# 默认关键文件列表
DEFAULT_CRITICAL_FILES = [
    "src/scrapers/dandanplay.py",
    "src/scrapers/bilibili.py",
    "src/crud.py",
    "src/api/ui_api.py",
    "src/rate_limiter.so",
    "src/security_core.so"
]

def calculate_file_hashes(folder_path: Path, critical_files: list = None) -> Dict[str, str]:
    """计算指定文件夹中关键文件的哈希值"""
    if critical_files is None:
        critical_files = DEFAULT_CRITICAL_FILES

    file_hashes = {}
    for file_path in critical_files:
        full_path = folder_path / file_path
        if full_path.exists():
            try:
                with open(full_path, 'rb') as f:
                    content = f.read()
                    file_hash = hashlib.sha256(content).hexdigest()
                    file_hashes[file_path] = file_hash
                    print(f"✅ {file_path}: {file_hash[:16]}...")
            except Exception as e:
                print(f"❌ 计算 {file_path} 哈希失败: {e}")
        else:
            print(f"⚠️ 文件不存在: {file_path}")
    
    return file_hashes

def generate_and_sign_config(enabled: bool, limit: int, period_minutes: int, private_key_hex: str, public_key_hex: str, xor_key: bytes, uid_str: str, output_dir: Path, file_hashes: Dict[str, str] = None) -> str:
    """根据提供的参数生成一个经过XOR混淆的二进制配置，并使用SM2私钥对其进行签名。"""
    config_data = {
        "enabled": enabled, 
        "global_limit": limit,
        "global_period_seconds": period_minutes * 60, 
        "xorKey": xor_key.decode('utf-8'),
        "file_hashes": file_hashes or {}  # 添加文件哈希
    }
    
    try:
        json_bytes = json.dumps(config_data).encode('utf-8')
        obfuscated_bytes = bytearray()
        for i, byte in enumerate(json_bytes):
            obfuscated_bytes.append(byte ^ xor_key[i % len(xor_key)])

        sm2_crypt = sm2.CryptSM2(public_key=public_key_hex, private_key=private_key_hex)
        z_hex = sm2_crypt._sm3_z(uid=uid_str)
        message_bytes = z_hex.encode('utf-8') + bytes(obfuscated_bytes)
        hash_to_sign = sm3.sm3_hash(func.bytes_to_list(message_bytes))
        random_hex_str = func.random_hex(sm2_crypt.para_len)
        signature = sm2_crypt.sign(bytes.fromhex(hash_to_sign), random_hex_str)
        
        bin_path = output_dir / "rate_limit.bin"
        sig_path = output_dir / "rate_limit.bin.sig"
        pem_path = output_dir / "public_key.pem"
        uid_path = output_dir / "rate_limit.uid"

        with open(bin_path, 'wb') as f:
            f.write(obfuscated_bytes)
        with open(sig_path, 'wb') as f:
            f.write(signature.encode('utf-8'))
        with open(uid_path, 'w', encoding='utf-8') as f:
            f.write(uid_str)
        
        public_key_pem_content = _generate_pem_from_hex(public_key_hex)
        with open(pem_path, 'w', encoding='utf-8') as f:
            f.write(public_key_pem_content)

        hash_count = len(file_hashes) if file_hashes else 0
        return f"成功生成以下文件:\n- {bin_path}\n- {sig_path}\n- {pem_path}\n- {uid_path}\n\n包含 {hash_count} 个文件的完整性哈希值"
    except (ValueError, TypeError, base64.binascii.Error) as e:
        return f"签名时出错: 无效的私钥或公钥格式。\n请确保密钥是正确的十六进制字符串。\n\n详细错误: {e}"
    except IOError as e:
        return f"写入文件时出错:\n{e}"
    except Exception as e:
        return f"发生未知错误: {e}\n\n{traceback.format_exc()}"

class ConfigGeneratorApp:
    def __init__(self, root):
        self.root = root
        root.title("速率限制配置签名工具 - 增强版")
        root.geometry("600x800")  # 增大窗口尺寸以显示所有按钮

        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            self.app_path = Path(sys.executable).parent
        else:
            self.app_path = Path(__file__).parent
        self.config_file = self.app_path / "generator_config.ini"
        self.config = configparser.ConfigParser()

        # 控件变量
        self.enabled_var = tk.BooleanVar(value=True)
        self.limit_var = tk.StringVar(value="50")
        self.period_minutes_var = tk.StringVar(value="60")
        self.uid_var = tk.StringVar()
        # 分离两个功能的路径变量
        self.compile_folder_var = tk.StringVar()  # 编译功能的目录路径
        self.integrity_folder_var = tk.StringVar()  # 哈希计算功能的目录路径
        self.file_hashes = {}
        self.critical_files = DEFAULT_CRITICAL_FILES.copy()  # 可配置的关键文件列表

        # 编译状态
        self._compiling = False

        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 配置部分
        ttk.Checkbutton(main_frame, text="启用全局速率限制", variable=self.enabled_var).pack(anchor='w', pady=5)

        limit_frame = ttk.Frame(main_frame)
        limit_frame.pack(fill=tk.X, pady=5)
        ttk.Label(limit_frame, text="请求次数:").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Entry(limit_frame, textvariable=self.limit_var, width=10).pack(side=tk.LEFT)
        
        period_frame = ttk.Frame(main_frame)
        period_frame.pack(fill=tk.X, pady=5)
        ttk.Label(period_frame, text="时间周期 (分钟):").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Entry(period_frame, textvariable=self.period_minutes_var, width=10).pack(side=tk.LEFT)
        
        period_shortcuts = {'1小时': 60, '3小时': 180, '6小时': 360, '12小时': 720, '24小时': 1440}
        shortcut_combobox = ttk.Combobox(period_frame, values=list(period_shortcuts.keys()), state="readonly", width=10)
        shortcut_combobox.pack(side=tk.LEFT, padx=5)
        shortcut_combobox.bind("<<ComboboxSelected>>", lambda e: self.period_minutes_var.set(str(period_shortcuts[shortcut_combobox.get()])))

        # 文件完整性验证部分
        folder_frame = ttk.LabelFrame(main_frame, text="文件完整性验证", padding="10")
        folder_frame.pack(fill=tk.X, pady=10)

        # 文件选择和哈希计算按钮
        file_config_frame = ttk.Frame(folder_frame)
        file_config_frame.pack(fill=tk.X, pady=5)
        ttk.Button(file_config_frame, text="选择验证文件", command=self.select_integrity_files_inline).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(file_config_frame, text="计算哈希", command=self.calculate_hashes_for_current_files).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(file_config_frame, text="配置关键文件", command=self.configure_critical_files).pack(side=tk.LEFT)

        self.hash_display = scrolledtext.ScrolledText(folder_frame, height=4, wrap=tk.WORD, state="disabled")
        self.hash_display.pack(fill=tk.BOTH, expand=True, pady=5)

        # 密钥配置部分
        key_frame = ttk.LabelFrame(main_frame, text="密钥配置", padding="10")
        key_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        # UID 输入与生成
        uid_frame = ttk.Frame(key_frame)
        uid_frame.pack(fill=tk.X, pady=(5, 5))
        ttk.Label(uid_frame, text="用户ID (UID):").pack(side=tk.LEFT)
        ttk.Entry(uid_frame, textvariable=self.uid_var).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        ttk.Button(uid_frame, text="随机生成", command=self.randomize_uid).pack(side=tk.LEFT)

        # 混淆密钥输入
        ttk.Label(key_frame, text="混淆密钥 (XOR Key):").pack(anchor='w', pady=(10, 0))
        self.xor_key_text = scrolledtext.ScrolledText(key_frame, height=2, wrap=tk.WORD)
        self.xor_key_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # 私钥输入
        ttk.Label(key_frame, text="私钥 (Hex 格式):").pack(anchor='w', pady=(5, 0))
        self.private_key_text = scrolledtext.ScrolledText(key_frame, height=3, wrap=tk.WORD)
        self.private_key_text.pack(fill=tk.BOTH, expand=True)

        # 公钥输入
        ttk.Label(key_frame, text="公钥 (Hex 格式, 04开头):").pack(anchor='w', pady=(10, 0))
        self.public_key_text = scrolledtext.ScrolledText(key_frame, height=3, wrap=tk.WORD)
        self.public_key_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # 按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=5, side=tk.BOTTOM)

        # 第一行按钮
        button_row1 = ttk.Frame(button_frame)
        button_row1.pack(fill=tk.X, pady=(0, 2))
        ttk.Button(button_row1, text="编译为.so文件", command=self.start_nuitka_compile).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 1))
        ttk.Button(button_row1, text="生成文件", command=self.on_generate, style="Accent.TButton").pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(1, 0))

        # 第二行按钮
        button_row2 = ttk.Frame(button_frame)
        button_row2.pack(fill=tk.X)
        ttk.Button(button_row2, text="验证签名文件", command=self.on_verify).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        ttk.Button(button_row2, text="保存当前密钥", command=self.save_app_config).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

        self.load_app_config()

    def select_integrity_files_inline(self):
        """内联选择完整性验证文件（不弹窗）"""
        # 获取当前保存的哈希计算目录，如果没有则使用当前工作目录
        folder_path = self.integrity_folder_var.get()
        if not folder_path:
            folder_path = str(Path.cwd())

        # 使用文件选择界面
        selected_files = self.select_integrity_files_dialog(folder_path)
        if selected_files:
            self.critical_files = selected_files
            # 更新显示但不自动计算哈希
            self.update_hash_display_with_files()
            messagebox.showinfo("成功", f"已选择 {len(selected_files)} 个文件，点击'计算哈希'按钮开始计算")

    def calculate_hashes_for_current_files(self):
        """为当前选中的文件计算哈希值"""
        if not self.critical_files:
            messagebox.showwarning("警告", "请先选择要验证的文件")
            return

        # 使用哈希计算专用的路径变量
        folder_path = self.integrity_folder_var.get()
        if not folder_path:
            messagebox.showerror("错误", "请先选择验证文件以确定基础目录")
            return

        self.calculate_hashes_for_selected_files(folder_path)

    def select_integrity_files_dialog(self, folder_path):
        """文件完整性验证文件选择对话框"""
        # 创建文件选择窗口
        select_window = tk.Toplevel(self.root)
        select_window.title("选择文件完整性验证文件")
        select_window.geometry("800x600")
        select_window.transient(self.root)
        select_window.grab_set()

        main_frame = ttk.Frame(select_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="选择需要进行完整性验证的文件：", font=("Arial", 12, "bold")).pack(anchor='w', pady=(0, 10))

        # 创建左右分栏布局
        paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 左侧：目录树
        left_frame = ttk.LabelFrame(paned_window, text="目录浏览", padding="5")
        paned_window.add(left_frame, weight=1)

        # 目录选择
        dir_frame = ttk.Frame(left_frame)
        dir_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(dir_frame, text="当前目录:").pack(side=tk.LEFT)
        self.integrity_dir_var = tk.StringVar(value=folder_path)
        dir_entry = ttk.Entry(dir_frame, textvariable=self.integrity_dir_var, state="readonly")
        dir_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        ttk.Button(dir_frame, text="浏览", command=self.browse_integrity_directory).pack(side=tk.LEFT)

        # 目录树
        tree_frame = ttk.Frame(left_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.integrity_tree = ttk.Treeview(tree_frame, selectmode="extended")
        tree_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.integrity_tree.yview)
        self.integrity_tree.config(yscrollcommand=tree_scrollbar.set)

        self.integrity_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 右侧：选中的文件列表
        right_frame = ttk.LabelFrame(paned_window, text="选中的文件", padding="5")
        paned_window.add(right_frame, weight=1)

        # 选中文件列表
        selected_frame = ttk.Frame(right_frame)
        selected_frame.pack(fill=tk.BOTH, expand=True)

        self.integrity_selected_listbox = tk.Listbox(selected_frame, selectmode=tk.SINGLE)
        selected_scrollbar = ttk.Scrollbar(selected_frame, orient=tk.VERTICAL, command=self.integrity_selected_listbox.yview)
        self.integrity_selected_listbox.config(yscrollcommand=selected_scrollbar.set)

        self.integrity_selected_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        selected_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 右侧操作按钮
        right_button_frame = ttk.Frame(right_frame)
        right_button_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Button(right_button_frame, text="移除选中", command=self.remove_integrity_file).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(right_button_frame, text="清空列表", command=self.clear_integrity_files).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(right_button_frame, text="添加默认", command=self.add_default_integrity_files).pack(side=tk.LEFT)

        # 操作按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(button_frame, text="添加选中文件", command=self.add_integrity_files_from_tree).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="刷新目录", command=self.refresh_integrity_tree).pack(side=tk.LEFT, padx=(0, 5))

        # 底部按钮
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(10, 0))

        self.integrity_files_result = []

        def confirm_integrity_selection():
            if self.integrity_selected_listbox.size() == 0:
                messagebox.showwarning("警告", "请至少选择一个文件进行完整性验证")
                return

            self.integrity_files_result = list(self.integrity_selected_listbox.get(0, tk.END))
            # 保存选择的目录到哈希计算专用的配置
            self.integrity_folder_var.set(self.integrity_dir_var.get())
            select_window.destroy()

        ttk.Button(bottom_frame, text="确认选择", command=confirm_integrity_selection).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(bottom_frame, text="取消", command=select_window.destroy).pack(side=tk.RIGHT)

        # 初始化目录树和默认文件
        self.refresh_integrity_tree()
        self.load_current_integrity_files()

        # 等待窗口关闭
        select_window.wait_window()
        return self.integrity_files_result

    def calculate_hashes_for_selected_files(self, base_folder):
        """为选中的文件计算哈希值"""
        if not self.critical_files:
            messagebox.showerror("错误", "没有选择任何文件")
            return

        try:
            self.file_hashes = {}
            base_path = Path(base_folder)

            for file_path in self.critical_files:
                full_path = base_path / file_path
                if full_path.exists():
                    try:
                        with open(full_path, 'rb') as f:
                            content = f.read()
                            file_hash = hashlib.sha256(content).hexdigest()
                            self.file_hashes[file_path] = file_hash
                            print(f"✅ {file_path}: {file_hash[:16]}...")
                    except Exception as e:
                        print(f"❌ 计算 {file_path} 哈希失败: {e}")
                else:
                    print(f"⚠️ 文件不存在: {file_path}")

            self.update_hash_display()
            messagebox.showinfo("成功", f"成功计算了 {len(self.file_hashes)} 个文件的哈希值")
        except Exception as e:
            messagebox.showerror("错误", f"计算文件哈希失败: {e}")

    def calculate_hashes(self):
        """计算文件哈希值（兼容旧方法）"""
        folder_path = self.integrity_folder_var.get()
        if not folder_path:
            messagebox.showerror("错误", "请先选择项目文件夹")
            return

        self.calculate_hashes_for_selected_files(folder_path)

    def update_hash_display(self):
        """更新哈希值显示"""
        self.hash_display.config(state="normal")
        self.hash_display.delete("1.0", tk.END)
        
        if self.file_hashes:
            for file_path, file_hash in self.file_hashes.items():
                self.hash_display.insert(tk.END, f"{file_path}: {file_hash[:16]}...\n")
        else:
            self.hash_display.insert(tk.END, "尚未计算文件哈希值")
        
        self.hash_display.config(state="disabled")

    def update_hash_display_with_files(self):
        """更新哈希值显示区域，显示选中的文件（不显示哈希值）"""
        self.hash_display.config(state="normal")
        self.hash_display.delete("1.0", tk.END)

        if self.critical_files:
            self.hash_display.insert(tk.END, f"已选择 {len(self.critical_files)} 个文件进行完整性验证：\n\n")
            for file_path in self.critical_files:
                self.hash_display.insert(tk.END, f"📄 {file_path}\n")
            self.hash_display.insert(tk.END, f"\n点击'计算哈希'按钮开始计算文件哈希值")
        else:
            self.hash_display.insert(tk.END, "尚未选择任何文件")

        self.hash_display.config(state="disabled")

    def browse_integrity_directory(self):
        """浏览选择完整性验证目录"""
        new_dir = filedialog.askdirectory(title="选择完整性验证根目录", initialdir=self.integrity_dir_var.get())
        if new_dir:
            self.integrity_dir_var.set(new_dir)
            self.refresh_integrity_tree()

    def refresh_integrity_tree(self):
        """刷新完整性验证目录树"""
        # 清空树
        for item in self.integrity_tree.get_children():
            self.integrity_tree.delete(item)

        current_dir = Path(self.integrity_dir_var.get())
        if not current_dir.exists():
            return

        # 添加所有文件到树中（不仅仅是Python文件）
        try:
            self._add_integrity_directory_to_tree("", current_dir, current_dir)
        except Exception as e:
            messagebox.showerror("错误", f"刷新目录失败: {e}")

    def _add_integrity_directory_to_tree(self, parent, dir_path, root_path, max_depth=3, current_depth=0):
        """递归添加目录到完整性验证树中（限制深度以提高性能）"""
        if current_depth >= max_depth:
            return

        try:
            items = []
            # 限制每个目录最多显示的项目数量
            max_items_per_dir = 100
            item_count = 0

            # 先添加目录（限制数量）
            for item in sorted(dir_path.iterdir()):
                if item_count >= max_items_per_dir:
                    break
                if item.is_dir() and not item.name.startswith('.') and not item.name.startswith('__'):
                    # 跳过一些常见的大目录
                    if item.name in ['node_modules', '.git', '__pycache__', 'venv', '.venv', 'env']:
                        continue
                    items.append(item)
                    item_count += 1

            # 再添加文件（限制数量）
            for item in sorted(dir_path.iterdir()):
                if item_count >= max_items_per_dir:
                    break
                if item.is_file() and not item.name.startswith('.') and not item.name.startswith('__'):
                    # 只显示常见的文件类型
                    if item.suffix in ['.py', '.so', '.txt', '.md', '.yml', '.yaml', '.json', '.js', '.ts', '.html', '.css']:
                        items.append(item)
                        item_count += 1

            for item in items:
                rel_path = item.relative_to(root_path)
                display_name = item.name

                if item.is_dir():
                    # 目录节点
                    node = self.integrity_tree.insert(parent, tk.END, text=f"📁 {display_name}",
                                                     values=[str(rel_path)], tags=["directory"])
                    # 递归添加子目录（增加深度）
                    self._add_integrity_directory_to_tree(node, item, root_path, max_depth, current_depth + 1)
                else:
                    # 文件节点，根据扩展名显示不同图标
                    if item.suffix == '.py':
                        icon = "🐍"
                    elif item.suffix == '.so':
                        icon = "⚙️"
                    elif item.suffix in ['.txt', '.md', '.yml', '.yaml', '.json']:
                        icon = "📄"
                    elif item.suffix in ['.js', '.ts']:
                        icon = "📜"
                    elif item.suffix in ['.html', '.css']:
                        icon = "🌐"
                    else:
                        icon = "📄"

                    self.integrity_tree.insert(parent, tk.END, text=f"{icon} {display_name}",
                                              values=[str(rel_path).replace("\\", "/")], tags=["file"])

            # 如果项目太多，添加提示
            if item_count >= max_items_per_dir:
                self.integrity_tree.insert(parent, tk.END, text="... (更多项目)",
                                          values=[""], tags=["info"])

        except PermissionError:
            pass  # 跳过无权限的目录

    def add_integrity_files_from_tree(self):
        """从树中添加选中的文件到完整性验证列表（无弹窗）"""
        selected_items = self.integrity_tree.selection()
        if not selected_items:
            # 不弹窗，只在状态栏或其他地方显示提示
            return

        added_count = 0
        for item in selected_items:
            tags = self.integrity_tree.item(item, "tags")
            if "file" in tags:
                file_path = self.integrity_tree.item(item, "values")[0]
                # 检查是否已存在
                existing_files = list(self.integrity_selected_listbox.get(0, tk.END))
                if file_path not in existing_files:
                    self.integrity_selected_listbox.insert(tk.END, file_path)
                    added_count += 1

        # 不弹出消息框，静默添加

    def remove_integrity_file(self):
        """移除选中的完整性验证文件"""
        selection = self.integrity_selected_listbox.curselection()
        if selection:
            self.integrity_selected_listbox.delete(selection[0])

    def clear_integrity_files(self):
        """清空完整性验证文件列表"""
        self.integrity_selected_listbox.delete(0, tk.END)

    def add_default_integrity_files(self):
        """添加默认的完整性验证文件"""
        default_files = DEFAULT_CRITICAL_FILES
        current_dir = Path(self.integrity_dir_var.get())

        added_count = 0
        existing_files = list(self.integrity_selected_listbox.get(0, tk.END))

        for file_path in default_files:
            full_path = current_dir / file_path
            if full_path.exists() and file_path not in existing_files:
                self.integrity_selected_listbox.insert(tk.END, file_path)
                added_count += 1

        if added_count > 0:
            messagebox.showinfo("成功", f"已添加 {added_count} 个默认文件")
        else:
            messagebox.showinfo("提示", "默认文件不存在或已在列表中")

    def load_current_integrity_files(self):
        """加载当前的完整性验证文件列表"""
        for file_path in self.critical_files:
            self.integrity_selected_listbox.insert(tk.END, file_path)

    def load_current_compile_files(self):
        """加载当前的编译文件列表（如果有的话）"""
        # 这里可以加载之前保存的编译文件列表
        # 目前先加载常用的编译文件
        pass

    def load_app_config(self):
        if not self.config_file.exists(): return
        try:
            self.config.read(self.config_file, encoding='utf-8')
            if 'Keys' in self.config:
                if xor_key := self.config['Keys'].get('XorKey'):
                    self.xor_key_text.delete("1.0", tk.END)
                    self.xor_key_text.insert(tk.INSERT, xor_key)
                if private_key := self.config['Keys'].get('PrivateKeyHex'):
                    self.private_key_text.delete("1.0", tk.END)
                    self.private_key_text.insert(tk.INSERT, private_key)
                if public_key := self.config['Keys'].get('PublicKeyHex', ''):
                    self.public_key_text.delete("1.0", tk.END)
                    self.public_key_text.insert(tk.INSERT, public_key)
                if uid := self.config['Keys'].get('UID'):
                    self.uid_var.set(uid)
                # 加载编译功能的目录路径
                if compile_folder := self.config['Keys'].get('CompileFolder'):
                    self.compile_folder_var.set(compile_folder)
                # 加载哈希计算功能的目录路径
                if integrity_folder := self.config['Keys'].get('IntegrityFolder'):
                    self.integrity_folder_var.set(integrity_folder)
                # 兼容旧配置：如果有FolderPath但没有分离的配置，则同时设置两个
                if folder_path := self.config['Keys'].get('FolderPath'):
                    if not self.compile_folder_var.get():
                        self.compile_folder_var.set(folder_path)
                    if not self.integrity_folder_var.get():
                        self.integrity_folder_var.set(folder_path)
                # 加载关键文件列表
                if critical_files_str := self.config['Keys'].get('CriticalFiles'):
                    try:
                        import json
                        self.critical_files = json.loads(critical_files_str)
                    except:
                        self.critical_files = DEFAULT_CRITICAL_FILES.copy()
                else:
                    self.critical_files = DEFAULT_CRITICAL_FILES.copy()
        except Exception as e:
            messagebox.showwarning("加载配置警告", f"加载 generator_config.ini 文件时出错，部分配置可能未加载。\n\n错误: {e}")

    def save_app_config(self):
        xor_key_value = self.xor_key_text.get("1.0", tk.END).strip()
        if not xor_key_value:
            messagebox.showerror("输入错误", "混淆密钥 (XOR Key) 不能为空。")
            return
        # 保存关键文件列表为JSON字符串
        import json
        critical_files_json = json.dumps(self.critical_files, ensure_ascii=False)

        self.config['Keys'] = {
            'PrivateKeyHex': self.private_key_text.get("1.0", tk.END).strip(),
            'PublicKeyHex': self.public_key_text.get("1.0", tk.END).strip(),
            'XorKey': xor_key_value.replace('%', '%%'),
            'UID': self.uid_var.get(),
            'CompileFolder': self.compile_folder_var.get(),  # 编译功能的目录路径
            'IntegrityFolder': self.integrity_folder_var.get(),  # 哈希计算功能的目录路径
            'CriticalFiles': critical_files_json,
            # 保留旧的FolderPath以兼容旧版本（使用编译路径）
            'FolderPath': self.compile_folder_var.get()
        }
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f: self.config.write(f)
            messagebox.showinfo("成功", f"配置已成功保存到 {self.config_file.name}")
        except IOError as e:
            messagebox.showerror("错误", f"保存配置文件失败: {e}")

    def randomize_uid(self):
        """生成一个16字节的随机十六进制字符串作为UID。"""
        self.uid_var.set(secrets.token_hex(16))

    def configure_critical_files(self):
        """配置关键文件列表"""
        # 创建配置窗口
        config_window = tk.Toplevel(self.root)
        config_window.title("配置关键文件")
        config_window.geometry("600x500")
        config_window.transient(self.root)
        config_window.grab_set()

        main_frame = ttk.Frame(config_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="关键文件列表配置", font=("Arial", 12, "bold")).pack(anchor='w', pady=(0, 10))

        # 说明文本
        info_text = "配置需要进行完整性验证的关键文件路径（相对于项目根目录）："
        ttk.Label(main_frame, text=info_text, wraplength=550).pack(anchor='w', pady=(0, 10))

        # 文件列表框架
        list_frame = ttk.LabelFrame(main_frame, text="当前关键文件", padding="5")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 创建列表框和滚动条
        list_container = ttk.Frame(list_frame)
        list_container.pack(fill=tk.BOTH, expand=True)

        self.files_listbox = tk.Listbox(list_container, selectmode=tk.SINGLE)
        scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL, command=self.files_listbox.yview)
        self.files_listbox.config(yscrollcommand=scrollbar.set)

        self.files_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 填充当前文件列表
        for file_path in self.critical_files:
            self.files_listbox.insert(tk.END, file_path)

        # 操作按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(button_frame, text="添加文件", command=self.add_critical_file).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="删除选中", command=self.remove_critical_file).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="重置为默认", command=self.reset_critical_files).pack(side=tk.LEFT, padx=(0, 5))

        # 底部按钮
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X)

        ttk.Button(bottom_frame, text="保存配置", command=lambda: self.save_critical_files_config(config_window)).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(bottom_frame, text="取消", command=config_window.destroy).pack(side=tk.RIGHT)

        # 保存窗口引用
        self.config_window = config_window

    def add_critical_file(self):
        """添加关键文件"""
        # 创建输入对话框
        input_window = tk.Toplevel(self.config_window)
        input_window.title("添加关键文件")
        input_window.geometry("400x150")
        input_window.transient(self.config_window)
        input_window.grab_set()

        frame = ttk.Frame(input_window, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="文件路径（相对于项目根目录）：").pack(anchor='w', pady=(0, 5))

        path_var = tk.StringVar()
        path_entry = ttk.Entry(frame, textvariable=path_var, width=50)
        path_entry.pack(fill=tk.X, pady=(0, 10))
        path_entry.focus()

        def add_file():
            file_path = path_var.get().strip()
            if file_path:
                if file_path not in self.critical_files:
                    self.critical_files.append(file_path)
                    self.files_listbox.insert(tk.END, file_path)
                    input_window.destroy()
                else:
                    messagebox.showwarning("警告", "该文件已存在于列表中")
            else:
                messagebox.showerror("错误", "请输入文件路径")

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X)

        ttk.Button(button_frame, text="添加", command=add_file).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="取消", command=input_window.destroy).pack(side=tk.RIGHT)

        # 绑定回车键
        path_entry.bind('<Return>', lambda e: add_file())

    def remove_critical_file(self):
        """删除选中的关键文件"""
        selection = self.files_listbox.curselection()
        if selection:
            index = selection[0]
            file_path = self.files_listbox.get(index)
            self.critical_files.remove(file_path)
            self.files_listbox.delete(index)
        else:
            messagebox.showwarning("警告", "请先选择要删除的文件")

    def reset_critical_files(self):
        """重置为默认关键文件列表"""
        if messagebox.askyesno("确认", "确定要重置为默认文件列表吗？"):
            self.critical_files = DEFAULT_CRITICAL_FILES.copy()
            self.files_listbox.delete(0, tk.END)
            for file_path in self.critical_files:
                self.files_listbox.insert(tk.END, file_path)

    def save_critical_files_config(self, config_window):
        """保存关键文件配置"""
        try:
            # 保存到配置文件
            self.save_app_config()
            messagebox.showinfo("成功", "关键文件配置已保存")
            config_window.destroy()
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")



    def start_nuitka_compile(self):
        """启动Nuitka编译过程 - 新版本支持文件选择和进度显示"""
        # 防止重复执行
        if hasattr(self, '_compiling') and self._compiling:
            return

        try:
            # 使用编译专用的路径变量
            folder_path = self.compile_folder_var.get()
            if not folder_path:
                folder_path = filedialog.askdirectory(title="选择编译项目根目录")
                if not folder_path:
                    return
                self.compile_folder_var.set(folder_path)

            # 让用户选择要编译的Python文件
            selected_files = self.select_files_to_compile(folder_path)
            if not selected_files:
                return

            # 使用用户最终选择的目录（可能在文件选择器中已更改）
            final_folder_path = self.compile_folder_var.get()
            # 创建新的编译进度窗口
            self.create_compile_progress_window(final_folder_path, selected_files)

        except Exception as e:
            messagebox.showerror("编译错误", f"编译过程发生错误：\n{e}")

    def select_files_to_compile(self, folder_path):
        """内嵌式文件选择器"""
        # 创建文件选择窗口
        select_window = tk.Toplevel(self.root)
        select_window.title("选择要编译的Python文件")
        select_window.geometry("800x600")
        select_window.transient(self.root)
        select_window.grab_set()

        main_frame = ttk.Frame(select_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="选择要编译为.so文件的Python文件：", font=("Arial", 12, "bold")).pack(anchor='w', pady=(0, 10))

        # 创建左右分栏布局
        paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 左侧：目录树
        left_frame = ttk.LabelFrame(paned_window, text="目录浏览", padding="5")
        paned_window.add(left_frame, weight=1)

        # 目录选择
        dir_frame = ttk.Frame(left_frame)
        dir_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(dir_frame, text="当前目录:").pack(side=tk.LEFT)
        self.current_dir_var = tk.StringVar(value=folder_path)
        dir_entry = ttk.Entry(dir_frame, textvariable=self.current_dir_var, state="readonly")
        dir_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        ttk.Button(dir_frame, text="浏览", command=self.browse_compile_directory).pack(side=tk.LEFT)

        # 目录树
        tree_frame = ttk.Frame(left_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.dir_tree = ttk.Treeview(tree_frame, selectmode="extended")
        tree_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.dir_tree.yview)
        self.dir_tree.config(yscrollcommand=tree_scrollbar.set)

        self.dir_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 绑定双击事件
        self.dir_tree.bind("<Double-1>", self.on_compile_tree_double_click)

        # 右侧：选中的文件列表
        right_frame = ttk.LabelFrame(paned_window, text="选中的文件", padding="5")
        paned_window.add(right_frame, weight=1)

        # 选中文件列表
        selected_frame = ttk.Frame(right_frame)
        selected_frame.pack(fill=tk.BOTH, expand=True)

        self.selected_listbox = tk.Listbox(selected_frame, selectmode=tk.SINGLE)
        selected_scrollbar = ttk.Scrollbar(selected_frame, orient=tk.VERTICAL, command=self.selected_listbox.yview)
        self.selected_listbox.config(yscrollcommand=selected_scrollbar.set)

        self.selected_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        selected_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 右侧操作按钮
        right_button_frame = ttk.Frame(right_frame)
        right_button_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Button(right_button_frame, text="移除选中", command=self.remove_selected_file).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(right_button_frame, text="清空列表", command=self.clear_selected_files).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(right_button_frame, text="添加常用", command=self.add_common_files).pack(side=tk.LEFT)

        # 操作按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(button_frame, text="添加选中文件", command=self.add_selected_files_from_tree).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="刷新目录", command=self.refresh_directory_tree).pack(side=tk.LEFT, padx=(0, 5))

        # 底部按钮
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(10, 0))

        self.selected_files_result = []

        def confirm_selection():
            if self.selected_listbox.size() == 0:
                messagebox.showwarning("警告", "请至少选择一个文件进行编译")
                return

            self.selected_files_result = list(self.selected_listbox.get(0, tk.END))
            # 保存选择的目录到编译专用的配置
            self.compile_folder_var.set(self.current_dir_var.get())
            select_window.destroy()

        ttk.Button(bottom_frame, text="开始编译", command=confirm_selection).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(bottom_frame, text="取消", command=select_window.destroy).pack(side=tk.RIGHT)

        # 初始化目录树和加载之前选择的文件
        self.refresh_directory_tree()
        self.load_current_compile_files()

        # 等待窗口关闭
        select_window.wait_window()
        return self.selected_files_result

    def browse_compile_directory(self):
        """浏览选择编译目录"""
        new_dir = filedialog.askdirectory(title="选择编译根目录", initialdir=self.current_dir_var.get())
        if new_dir:
            self.current_dir_var.set(new_dir)
            self.refresh_directory_tree()

    def refresh_directory_tree(self):
        """刷新目录树"""
        # 清空树
        for item in self.dir_tree.get_children():
            self.dir_tree.delete(item)

        current_dir = Path(self.current_dir_var.get())
        if not current_dir.exists():
            return

        # 添加Python文件到树中
        try:
            self._add_directory_to_tree("", current_dir, current_dir)
        except Exception as e:
            messagebox.showerror("错误", f"刷新目录失败: {e}")

    def _add_directory_to_tree(self, parent, dir_path, root_path, max_depth=3, current_depth=0):
        """递归添加目录到树中（限制深度以提高性能）"""
        if current_depth >= max_depth:
            return

        try:
            items = []
            max_items_per_dir = 50  # 编译文件选择限制更少的项目
            item_count = 0

            # 先添加目录（限制数量）
            for item in sorted(dir_path.iterdir()):
                if item_count >= max_items_per_dir:
                    break
                if item.is_dir() and not item.name.startswith('.') and not item.name.startswith('__'):
                    # 跳过一些常见的大目录
                    if item.name in ['node_modules', '.git', '__pycache__', 'venv', '.venv', 'env', 'dist', 'build']:
                        continue
                    items.append(item)
                    item_count += 1

            # 再添加Python文件
            for item in sorted(dir_path.iterdir()):
                if item_count >= max_items_per_dir:
                    break
                if item.is_file() and item.suffix == '.py' and not item.name.startswith('__'):
                    items.append(item)
                    item_count += 1

            for item in items:
                rel_path = item.relative_to(root_path)
                display_name = item.name

                if item.is_dir():
                    # 目录节点
                    node = self.dir_tree.insert(parent, tk.END, text=f"📁 {display_name}",
                                               values=[str(rel_path)], tags=["directory"])
                    # 递归添加子目录（增加深度）
                    self._add_directory_to_tree(node, item, root_path, max_depth, current_depth + 1)
                else:
                    # 文件节点，根据扩展名显示不同图标
                    if item.suffix == '.py':
                        icon = "🐍"
                        tag = "python_file"
                    elif item.suffix == '.so':
                        icon = "⚙️"
                        tag = "so_file"
                    elif item.suffix in ['.txt', '.md', '.yml', '.yaml', '.json']:
                        icon = "📄"
                        tag = "text_file"
                    elif item.suffix in ['.js', '.ts']:
                        icon = "📜"
                        tag = "script_file"
                    elif item.suffix in ['.html', '.css']:
                        icon = "🌐"
                        tag = "web_file"
                    else:
                        icon = "📄"
                        tag = "other_file"

                    self.dir_tree.insert(parent, tk.END, text=f"{icon} {display_name}",
                                        values=[str(rel_path).replace("\\", "/")], tags=[tag])

            # 如果项目太多，添加提示
            if item_count >= max_items_per_dir:
                self.dir_tree.insert(parent, tk.END, text="... (更多项目)",
                                    values=[""], tags=["info"])

        except PermissionError:
            pass  # 跳过无权限的目录

    def on_compile_tree_double_click(self, event):
        """处理编译目录树的双击事件"""
        item = self.dir_tree.selection()[0] if self.dir_tree.selection() else None
        if not item:
            return

        # 获取项目标签
        tags = self.dir_tree.item(item, "tags")

        if "directory" in tags:
            # 双击文件夹：展开/折叠
            if self.dir_tree.item(item, "open"):
                self.dir_tree.item(item, open=False)
            else:
                self.dir_tree.item(item, open=True)
        elif "python_file" in tags:
            # 双击Python文件：添加到选择列表
            self.add_selected_files_from_tree()
        elif any(tag in tags for tag in ["so_file", "text_file", "script_file", "web_file", "other_file"]):
            # 双击其他文件类型：也可以添加到选择列表（如果需要的话）
            if "so_file" in tags:
                messagebox.showinfo("提示", "这是一个已编译的.so文件，无需重新编译")
            else:
                # 对于非Python文件，询问是否要添加
                if messagebox.askyesno("确认", "这不是Python文件，确定要添加到编译列表吗？"):
                    self.add_selected_files_from_tree()

    def add_selected_files_from_tree(self):
        """从树中添加选中的文件"""
        selected_items = self.dir_tree.selection()
        if not selected_items:
            messagebox.showwarning("警告", "请先在左侧目录树中选择Python文件")
            return

        added_count = 0
        for item in selected_items:
            tags = self.dir_tree.item(item, "tags")
            if "python_file" in tags:
                file_path = self.dir_tree.item(item, "values")[0]
                # 检查是否已存在
                existing_files = list(self.selected_listbox.get(0, tk.END))
                if file_path not in existing_files:
                    self.selected_listbox.insert(tk.END, file_path)
                    added_count += 1

        if added_count > 0:
            messagebox.showinfo("成功", f"已添加 {added_count} 个文件")
        else:
            messagebox.showinfo("提示", "没有新文件被添加（可能已存在或选择的不是Python文件）")

    def remove_selected_file(self):
        """移除选中的文件"""
        selection = self.selected_listbox.curselection()
        if selection:
            self.selected_listbox.delete(selection[0])

    def clear_selected_files(self):
        """清空选中的文件列表"""
        self.selected_listbox.delete(0, tk.END)

    def add_common_files(self):
        """添加常用文件"""
        common_files = ["src/rate_limiter.py", "src/security_core.py"]
        current_dir = Path(self.current_dir_var.get())

        added_count = 0
        existing_files = list(self.selected_listbox.get(0, tk.END))

        for file_path in common_files:
            full_path = current_dir / file_path
            if full_path.exists() and file_path not in existing_files:
                self.selected_listbox.insert(tk.END, file_path)
                added_count += 1

        if added_count > 0:
            messagebox.showinfo("成功", f"已添加 {added_count} 个常用文件")
        else:
            messagebox.showinfo("提示", "常用文件不存在或已在列表中")

    def get_python_executable(self):
        """获取Python可执行文件路径"""
        import shutil
        # 尝试查找系统Python
        python_exe = shutil.which("python")
        if not python_exe:
            python_exe = shutil.which("python3")
        if not python_exe:
            # 如果找不到，使用当前Python（但避免exe文件）
            if not sys.executable.endswith('.exe') or 'python' in sys.executable.lower():
                python_exe = sys.executable
            else:
                python_exe = "python"  # 最后的备选
        return python_exe

    def create_compile_batch(self, folder_path, files_to_compile):
        """创建编译批处理文件（在程序目录下的临时文件夹编译）"""
        batch_content = "@echo off\n"
        batch_content += "chcp 65001 >nul\n"  # 设置UTF-8编码
        batch_content += "setlocal enabledelayedexpansion\n"
        batch_content += "echo 开始编译...\n"
        batch_content += f'cd /d "{self.app_path}"\n'  # 切换到程序目录
        batch_content += "echo 当前工作目录: %cd%\n"
        batch_content += "if exist temp_compile rmdir /s /q temp_compile\n"
        batch_content += "mkdir temp_compile\n"
        batch_content += "cd temp_compile\n"
        batch_content += "echo 临时编译目录: %cd%\n"
        batch_content += "echo.\n"

        for file_path in files_to_compile:
            file_name = Path(file_path).name
            stem_name = Path(file_path).stem

            # 处理文件路径 - 确保路径正确
            if Path(file_path).is_absolute():
                # 绝对路径直接使用
                source_path = str(Path(file_path))
            else:
                # 相对路径需要基于folder_path解析
                source_path = str(Path(folder_path) / file_path)

            # 确保路径存在
            if not Path(source_path).exists():
                self.log_compile_message(f"警告: 源文件不存在: {source_path}")
                continue

            batch_content += f"echo.\n"
            batch_content += f"echo ========== 处理文件: {file_name} ==========\n"
            batch_content += f"echo 源文件路径: {source_path}\n"
            batch_content += f"echo 复制 {file_name}...\n"
            batch_content += f'copy "{source_path}" "{file_name}" >nul\n'
            batch_content += f"if not exist {file_name} (\n"
            batch_content += f"    echo 错误: 文件复制失败 {file_name}\n"
            batch_content += f"    goto :cleanup\n"
            batch_content += f")\n"
            batch_content += f"echo 复制成功: {file_name}\n"
            batch_content += f"echo 编译 {file_name}...\n"
            # 生成完整的一行编译命令，添加更多输出选项
            compile_command = f'python -m nuitka --module "{file_name}" --output-dir=. --no-pyi-file --show-progress --assume-yes-for-downloads --verbose'
            batch_content += f"echo 执行命令: {compile_command}\n"
            batch_content += f'{compile_command} 2>&1\n'  # 重定向错误输出
            batch_content += f"if !errorlevel! neq 0 (\n"
            batch_content += f"    echo 错误: 编译失败 {file_name} (错误码: !errorlevel!)\n"
            batch_content += f"    goto :cleanup\n"
            batch_content += f")\n"
            batch_content += f"echo 查找编译输出...\n"
            batch_content += f'dir {stem_name}.* /b\n'
            batch_content += f"echo 处理编译输出...\n"
            batch_content += f'for %%f in ({stem_name}.*.pyd {stem_name}.*.so) do (\n'
            batch_content += f'    if exist "%%f" (\n'
            batch_content += f'        echo 找到编译文件: %%f\n'
            batch_content += f'        ren "%%f" "{stem_name}.so"\n'
            batch_content += f'        if exist "{stem_name}.so" (\n'
            batch_content += f'            copy "{stem_name}.so" "..\\" >nul\n'
            batch_content += f'            echo 成功生成: {stem_name}.so\n'
            batch_content += f'        ) else (\n'
            batch_content += f'            echo 错误: 重命名失败 {stem_name}.so\n'
            batch_content += f'        )\n'
            batch_content += f'    )\n'
            batch_content += f')\n'

        batch_content += "\n:cleanup\n"
        batch_content += "echo.\n"
        batch_content += "echo ========== 清理临时文件 ==========\n"
        batch_content += "cd ..\n"
        batch_content += "echo 返回项目根目录: %cd%\n"
        batch_content += "echo 删除临时编译目录...\n"
        batch_content += "if exist temp_compile (\n"
        batch_content += "    rmdir /s /q temp_compile\n"
        batch_content += "    if exist temp_compile (\n"
        batch_content += "        echo 警告: 临时目录删除失败，请手动删除 temp_compile\n"
        batch_content += "    ) else (\n"
        batch_content += "        echo 临时目录已成功删除\n"
        batch_content += "    )\n"
        batch_content += ") else (\n"
        batch_content += "    echo 临时目录不存在，无需删除\n"
        batch_content += ")\n"
        batch_content += "echo.\n"
        batch_content += "echo ========== 编译结果 ==========\n"
        batch_content += "echo 查看生成的.so文件：\n"
        batch_content += "dir *.so /b 2>nul\n"
        batch_content += "if !errorlevel! equ 0 (\n"
        batch_content += "    echo 编译完成！.so文件已生成在项目根目录。\n"
        batch_content += ") else (\n"
        batch_content += "    echo 未找到.so文件，编译可能失败。\n"
        batch_content += ")\n"
        batch_content += "echo COMPILE_FINISHED\n"

        # 使用固定的批处理文件名
        batch_filename = "compile_temp.bat"
        batch_file = self.app_path / batch_filename

        with open(batch_file, 'w', encoding='utf-8') as f:
            f.write(batch_content)

        # 调试：记录批处理文件内容
        self.log_compile_message(f"批处理文件已生成，包含 {len(files_to_compile)} 个文件的编译任务")
        self.log_compile_message(f"项目目录: {folder_path}")
        for i, file_path in enumerate(files_to_compile, 1):
            # 显示实际的源文件路径
            if Path(file_path).is_absolute():
                source_path = str(Path(file_path))
            else:
                source_path = str(Path(folder_path) / file_path)
            self.log_compile_message(f"  {i}. {Path(file_path).name} <- {source_path}")
            # 检查文件是否存在
            if not Path(source_path).exists():
                self.log_compile_message(f"     ❌ 文件不存在!")
            else:
                self.log_compile_message(f"     ✅ 文件存在")

        return batch_file

    def create_compile_progress_window(self, folder_path, files_to_compile):
        """创建编译进度窗口"""
        # 创建进度窗口
        progress_window = tk.Toplevel(self.root)
        progress_window.title("编译进度")
        progress_window.geometry("700x500")
        progress_window.transient(self.root)
        progress_window.grab_set()
        progress_window.resizable(True, True)

        # 居中显示
        progress_window.update_idletasks()
        x = (progress_window.winfo_screenwidth() // 2) - (700 // 2)
        y = (progress_window.winfo_screenheight() // 2) - (500 // 2)
        progress_window.geometry(f"700x500+{x}+{y}")

        main_frame = ttk.Frame(progress_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 标题
        title_label = ttk.Label(main_frame, text="正在编译Python文件为.so模块", font=("Arial", 12, "bold"))
        title_label.pack(anchor='w', pady=(0, 10))

        # 文件列表显示
        files_frame = ttk.LabelFrame(main_frame, text="编译文件列表", padding="5")
        files_frame.pack(fill=tk.X, pady=(0, 10))

        files_text = "\n".join([f"• {f}" for f in files_to_compile])
        ttk.Label(files_frame, text=files_text, wraplength=650).pack(anchor='w')

        # 进度条
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(progress_frame, text="编译进度:").pack(anchor='w')
        self.compile_progress_bar = ttk.Progressbar(progress_frame, mode='indeterminate')
        self.compile_progress_bar.pack(fill=tk.X, pady=(5, 0))
        self.compile_progress_bar.start()

        # 状态标签
        self.compile_status_label = ttk.Label(main_frame, text="准备开始编译...", font=("Arial", 10))
        self.compile_status_label.pack(anchor='w', pady=(0, 10))

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="编译日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 创建日志文本框
        self.compile_log_text = scrolledtext.ScrolledText(log_frame, height=15, wrap=tk.WORD, font=("Consolas", 9))
        self.compile_log_text.pack(fill=tk.BOTH, expand=True)

        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        self.compile_cancel_btn = ttk.Button(button_frame, text="取消编译", command=lambda: self.cancel_compile_process(progress_window))
        self.compile_cancel_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.compile_close_btn = ttk.Button(button_frame, text="关闭", command=progress_window.destroy, state="disabled")
        self.compile_close_btn.pack(side=tk.RIGHT)

        # 保存窗口引用
        self.compile_progress_window = progress_window

        # 开始编译过程
        self.start_compile_process(folder_path, files_to_compile)

    def start_compile_process(self, folder_path, files_to_compile):
        """开始编译过程"""
        self._compiling = True
        self._compile_process = None

        try:
            # 创建批处理文件
            batch_file = self.create_compile_batch(folder_path, files_to_compile)

            self.log_compile_message("编译批处理文件已创建")
            self.log_compile_message(f"批处理文件路径: {batch_file}")
            self.log_compile_message("开始执行编译...")

            # 启动批处理进程 - 使用非阻塞方式
            import subprocess
            import threading

            self._compile_process = subprocess.Popen(
                ['cmd', '/c', str(batch_file)],
                cwd=str(self.app_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',  # 使用UTF-8编码匹配批处理文件
                errors='replace',  # 处理编码错误
                bufsize=1,  # 行缓冲
                universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW  # 隐藏命令行窗口
            )

            # 使用线程读取输出，避免阻塞GUI
            self._output_thread = threading.Thread(target=self._read_process_output, daemon=True)
            self._output_thread.start()

            # 定期检查进程状态
            self.check_compile_status()

        except Exception as e:
            self.log_compile_message(f"启动编译失败: {e}")
            self.compile_finished(False, str(e))

    def _read_process_output(self):
        """在线程中读取进程输出"""
        try:
            self.root.after(0, lambda: self.log_compile_message("开始读取编译输出..."))

            while self._compile_process and self._compile_process.poll() is None:
                try:
                    line = self._compile_process.stdout.readline()
                    if line:
                        line = line.strip()
                        if line:
                            # 使用线程安全的方式更新GUI
                            self.root.after(0, lambda msg=line: self._handle_output_line(msg))
                except UnicodeDecodeError as ude:
                    # 处理编码错误
                    self.root.after(0, lambda: self.log_compile_message(f"编码错误，跳过该行: {ude}"))
                    continue

            # 读取剩余输出
            if self._compile_process:
                remaining_output = self._compile_process.stdout.read()
                if remaining_output:
                    for line in remaining_output.split('\n'):
                        line = line.strip()
                        if line:
                            self.root.after(0, lambda msg=line: self._handle_output_line(msg))

        except Exception as e:
            self.root.after(0, lambda: self.log_compile_message(f"读取输出错误: {e}"))

    def _handle_output_line(self, line):
        """处理输出行（在主线程中执行）"""
        self.log_compile_message(line)

        # 更新状态
        if "编译" in line:
            self.update_compile_status(f"正在编译: {line}")
        elif "复制" in line:
            self.update_compile_status(f"正在复制: {line}")
        elif "成功生成" in line:
            self.update_compile_status(f"生成成功: {line}")
        elif "错误" in line:
            self.update_compile_status(f"发生错误: {line}")
        elif "COMPILE_FINISHED" in line:
            self.compile_finished(True, "编译完成")

    def check_compile_status(self):
        """定期检查编译状态"""
        if self._compile_process:
            if self._compile_process.poll() is not None:
                # 进程已结束
                return_code = self._compile_process.returncode
                if return_code == 0:
                    self.compile_finished(True, "编译完成")
                else:
                    self.compile_finished(False, f"编译失败，返回码: {return_code}")
                return

        # 如果还在编译，继续检查
        if self._compiling:
            self.root.after(500, self.check_compile_status)

    def log_compile_message(self, message):
        """添加日志消息"""
        try:
            if hasattr(self, 'compile_log_text') and self.compile_log_text.winfo_exists():
                self.compile_log_text.insert(tk.END, f"{message}\n")
                self.compile_log_text.see(tk.END)
        except tk.TclError:
            pass

    def update_compile_status(self, status):
        """更新编译状态"""
        try:
            if hasattr(self, 'compile_status_label') and self.compile_status_label.winfo_exists():
                self.compile_status_label.config(text=status)
        except tk.TclError:
            pass

    def compile_finished(self, success, message):
        """编译完成"""
        self._compiling = False

        try:
            if hasattr(self, 'compile_progress_bar') and self.compile_progress_bar.winfo_exists():
                self.compile_progress_bar.stop()

            if success:
                self.update_compile_status("✅ 编译完成！")
                self.log_compile_message("========== 编译成功完成 ==========")
            else:
                self.update_compile_status(f"❌ 编译失败: {message}")
                self.log_compile_message(f"========== 编译失败: {message} ==========")

            # 启用关闭按钮，禁用取消按钮
            if hasattr(self, 'compile_cancel_btn') and self.compile_cancel_btn.winfo_exists():
                self.compile_cancel_btn.config(state="disabled")
            if hasattr(self, 'compile_close_btn') and self.compile_close_btn.winfo_exists():
                self.compile_close_btn.config(state="normal")

            # 清理批处理文件
            self.cleanup_batch_file()

        except tk.TclError:
            pass

    def cleanup_batch_file(self):
        """清理批处理文件"""
        try:
            batch_file = self.app_path / "compile_temp.bat"
            if batch_file.exists():
                batch_file.unlink()
                self.log_compile_message("批处理文件已清理: compile_temp.bat")
            else:
                self.log_compile_message("没有需要清理的批处理文件")
        except Exception as e:
            self.log_compile_message(f"清理批处理文件失败: {e}")

    def cancel_compile_process(self, progress_window):
        """取消编译过程"""
        self._compiling = False

        if self._compile_process:
            try:
                self._compile_process.terminate()
                self.log_compile_message("编译已被用户取消")
                # 等待进程结束
                try:
                    self._compile_process.wait(timeout=3)
                except:
                    # 如果进程不响应，强制杀死
                    self._compile_process.kill()
            except:
                pass

        # 清理批处理文件
        self.cleanup_batch_file()
        progress_window.destroy()

    def _rename_compiled_file_simple(self, file_path):
        """简化的文件重命名"""
        try:
            import glob
            import os

            # 获取文件名（不含扩展名和路径）
            file_name = Path(file_path).stem

            # 在当前工作目录查找编译生成的文件
            # Nuitka生成的文件格式通常是: filename.cpython-xxx-win_amd64.pyd 或 filename.cpython-xxx.so
            patterns = [
                f"{file_name}.*.so",
                f"{file_name}.*.pyd",
                f"{file_name}.cpython-*.so",
                f"{file_name}.cpython-*.pyd"
            ]

            compiled_files = []
            for pattern in patterns:
                found_files = glob.glob(pattern)
                if found_files:
                    compiled_files.extend(found_files)
                    break  # 找到就停止

            if compiled_files:
                # 重命名第一个找到的文件
                compiled_file = compiled_files[0]
                target_path = f"{file_name}.so"

                # 如果目标文件已存在，先删除
                if os.path.exists(target_path):
                    os.remove(target_path)

                os.rename(compiled_file, target_path)
                return True
            else:
                return False

        except Exception as e:
            print(f"重命名失败: {e}")  # 调试用
            return False





    def on_generate(self):
        try:
            # 验证私钥
            raw_private_key = self.private_key_text.get("1.0", tk.END)
            key_no_whitespace = re.sub(r'\s+', '', raw_private_key)
            private_key_hex = re.sub(r'[^0-9a-fA-F]', '', key_no_whitespace)
            if not private_key_hex or len(private_key_hex) != 64:
                messagebox.showerror("输入错误", "请输入有效的SM2私钥 (Hex 格式)。\n清理后应为64位十六进制字符。")
                return

            # 验证公钥
            raw_public_key = self.public_key_text.get("1.0", tk.END)
            pub_key_no_whitespace = re.sub(r'\s+', '', raw_public_key)
            public_key_hex = re.sub(r'[^0-9a-fA-F]', '', pub_key_no_whitespace)
            if not public_key_hex or len(public_key_hex) != 130 or not public_key_hex.startswith('04'):
                messagebox.showerror("输入错误", "请输入有效的SM2公钥 (Hex 格式)。\n应为以'04'开头的130位十六进制字符。")
                return

            # 验证UID
            uid_str = self.uid_var.get().strip()
            if not uid_str:
                messagebox.showerror("输入错误", "用户ID (UID) 不能为空。")
                return

            # 检查是否计算了文件哈希
            if not self.file_hashes:
                result = messagebox.askyesno("警告", "尚未计算文件哈希值。\n是否继续生成配置文件？\n\n选择'是'将生成不包含文件完整性验证的配置。")
                if not result:
                    return

            output_dir = self.app_path

            result_message = generate_and_sign_config(
                self.enabled_var.get(), int(self.limit_var.get()), int(self.period_minutes_var.get()),
                private_key_hex, public_key_hex, self.xor_key_text.get("1.0", tk.END).strip().encode('utf-8'), 
                uid_str, Path(output_dir), self.file_hashes
            )
            if "成功" in result_message:
                messagebox.showinfo("成功", result_message)
            else: 
                messagebox.showerror("错误", result_message)
        except ValueError:
            messagebox.showerror("输入错误", "请求次数必须是一个有效的整数。")
        except Exception as e:
            messagebox.showerror("未知错误", f"发生了一个意外错误: {e}\n\n{traceback.format_exc()}")

    def on_verify(self):
        """处理"验证签名文件"按钮的点击事件。"""
        try:
            bin_path_str = filedialog.askopenfilename(title="选择 rate_limit.bin 文件", filetypes=[("Binary files", "*.bin")])
            if not bin_path_str: return
            sig_path_str = filedialog.askopenfilename(title="选择 rate_limit.bin.sig 文件", filetypes=[("Signature files", "*.sig")])
            if not sig_path_str: return
            pem_path_str = filedialog.askopenfilename(title="选择 public_key.pem 文件", filetypes=[("PEM files", "*.pem")])
            if not pem_path_str: return
            uid_path_str = filedialog.askopenfilename(title="选择 rate_limit.uid 文件", filetypes=[("UID files", "*.uid")])
            if not uid_path_str: return

            bin_path = Path(bin_path_str)
            sig_path = Path(sig_path_str)
            pem_path = Path(pem_path_str)
            uid_path = Path(uid_path_str)

            obfuscated_bytes = bin_path.read_bytes()
            signature = sig_path.read_text('utf-8').strip()
            public_key_pem = pem_path.read_text('utf-8')
            uid_str = uid_path.read_text('utf-8').strip()

            public_key_hex = _extract_hex_from_pem(public_key_pem)
            sm2_crypt = sm2.CryptSM2(public_key=public_key_hex, private_key='')

            # 验证签名
            is_valid = sm2_crypt.verify(signature, bytes(obfuscated_bytes), uid=uid_str)

            if is_valid:
                # 解析配置内容，检查文件哈希
                try:
                    # 询问是否要验证文件完整性
                    verify_files = messagebox.askyesno("验证选项", "签名验证通过！\n\n是否同时验证文件完整性？\n\n选择'是'需要选择项目文件夹。")

                    message = "✅ 签名验证通过！配置文件和签名匹配。"

                    if verify_files:
                        folder_path = filedialog.askdirectory(title="选择项目根目录进行文件完整性验证")
                        if folder_path:
                            # 解密配置获取文件哈希
                            xor_key = self.xor_key_text.get("1.0", tk.END).strip().encode('utf-8')
                            decrypted_bytes = bytearray()
                            for i, byte in enumerate(obfuscated_bytes):
                                decrypted_bytes.append(byte ^ xor_key[i % len(xor_key)])

                            config_data = json.loads(decrypted_bytes.decode('utf-8'))
                            stored_hashes = config_data.get('file_hashes', {})

                            if stored_hashes:
                                # 计算当前文件哈希
                                current_hashes = calculate_file_hashes(Path(folder_path))

                                # 比较哈希值
                                mismatched_files = []
                                for file_path, expected_hash in stored_hashes.items():
                                    current_hash = current_hashes.get(file_path)
                                    if current_hash != expected_hash:
                                        mismatched_files.append(file_path)

                                if mismatched_files:
                                    message += f"\n\n❌ 文件完整性验证失败！\n以下文件已被修改：\n" + "\n".join(f"- {f}" for f in mismatched_files)
                                else:
                                    message += f"\n\n✅ 文件完整性验证通过！\n验证了 {len(stored_hashes)} 个文件。"
                            else:
                                message += "\n\n⚠️ 配置文件中没有文件哈希数据。"

                    messagebox.showinfo("验证结果", message)

                except Exception as e:
                    messagebox.showinfo("验证结果", f"✅ 签名验证通过！\n\n⚠️ 文件完整性验证失败: {e}")
            else:
                messagebox.showerror("验证失败", "签名无效！\n\n请检查：\n1. 文件是否被修改。\n2. 公钥是否与生成签名的私钥匹配。")
        except Exception as e:
            messagebox.showerror("验证出错", f"验证过程中发生错误: {e}\n\n{traceback.format_exc()}")

if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style(root)
    style.configure("Accent.TButton", font=('Helvetica', 10, 'bold'))
    app = ConfigGeneratorApp(root)
    root.mainloop()
