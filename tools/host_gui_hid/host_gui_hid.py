#!/usr/bin/env python3
"""
HID Host图形界面模拟器（USB HID版本）
- 使用USB HID传输替代TCP
- 握手时根据设备ID（PID）0x2107和0x2108判断连接的端口0或是端口1
- 集成SimpleSendData/SimpleRecvData模块
- 支持文件发送和接收解析
- 基于HID协议的SEND_DATA命令进行数据传输
- 支持指定发送端口
"""

import threading
import queue
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk, filedialog
import binascii
import os
import shutil
from datetime import datetime
from simple_send_data import SimpleSendData, SimpleRecvData, MultiSegmentCollector
import protocol
import usb_hid_transport


class HIDHostGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("HID Host 模拟器 - USB HID版本")
        self.root.geometry("1200x800")

        # USB HID相关
        self.hid_client = None
        self.recv_thread = None
        self.running = False
        self.msg_queue = queue.Queue()
        self.bound_port = None  # 绑定的端口号

        # 文件传输相关
        self.send_file_obj = None
        self.recv_file_obj = None
        self.file_transfer_in_progress = False
        self.expected_responses = 0  # 期望的响应包数量（用于文件发送）
        self.sent_packets = 0
        self.total_packets = 0
        self.current_block_index = 0
        self.pending_data_packets = []  # 待发送的数据包列表

        # 自动接收相关
        self.auto_receive_enabled = True
        self.default_recv_dir = os.path.join(os.getcwd(), "received_files")

        # 分段发送相关
        self.current_segment = 0
        self.total_segments = 1
        self.full_file_data = None
        self.full_filename = ""
        self.segment_size = 0
        self.send_transfer_id = 0

        # 分段接收相关
        self.segment_collector = None

        # 发送端等待接收端finish_status回传
        self.waiting_for_finish_status = False

        # 创建界面
        self.create_widgets()

        # 初始化日志文件
        log_dir = os.path.join(os.getcwd(), "log")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        self._log_file = open(log_path, 'w', encoding='utf-8')

        # 启动队列检查
        self.poll_queue()

        # 自动检测设备
        if self.auto_detect_var.get():
            self.root.after(500, self._auto_detect_ports)

    def create_widgets(self):
        # 创建主框架
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧控制面板 - 设置固定宽度，紧凑靠左
        left_frame = ttk.Frame(main_paned, width=680)  # 稍微减小宽度使更紧凑
        main_paned.add(left_frame, weight=0)  # weight=0 防止拉伸

        # 右侧日志面板
        right_frame = ttk.Frame(main_paned, width=500)
        main_paned.add(right_frame, weight=2)

        # ========== 左侧控制面板 ==========
        # 使用grid布局在left_frame内部，使所有内容靠左
        left_frame.columnconfigure(0, weight=1)  # 只有一列，靠左

        # 连接框架
        frame_conn = ttk.LabelFrame(left_frame, text="USB HID连接设置", padding=3)
        frame_conn.grid(row=0, column=0, sticky=tk.W+tk.E, padx=2, pady=2)

        # 第一行：VID和端口选择
        row0 = ttk.Frame(frame_conn)
        row0.pack(fill=tk.X, pady=1)
        ttk.Label(row0, text="供应商ID (VID):").pack(side=tk.LEFT)
        self.entry_vid = ttk.Entry(row0, width=10)
        self.entry_vid.pack(side=tk.LEFT, padx=2)
        self.entry_vid.insert(0, "0x413d")
        ttk.Label(row0, text="绑定端口:").pack(side=tk.LEFT, padx=(5,0))
        self.port_id_var = tk.StringVar(value="0")
        ttk.Radiobutton(row0, text="端口0 (PID=0x2107)", variable=self.port_id_var,
                        value="0").pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(row0, text="端口1 (PID=0x2108)", variable=self.port_id_var,
                        value="1").pack(side=tk.LEFT, padx=2)

        # 第二行：连接按钮和自动检测
        row1 = ttk.Frame(frame_conn)
        row1.pack(fill=tk.X, pady=1)
        self.btn_connect = ttk.Button(row1, text="连接USB HID设备",
                                       command=self.connect_hid)
        self.btn_connect.pack(side=tk.LEFT, padx=3)
        self.btn_disconnect = ttk.Button(row1, text="断开",
                                         command=self.disconnect_hid,
                                         state=tk.DISABLED)
        self.btn_disconnect.pack(side=tk.LEFT, padx=3)
        self.auto_detect_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row1, text="自动检测", variable=self.auto_detect_var,
                        command=self._auto_detect_ports).pack(side=tk.LEFT, padx=5)

        # 检测状态行
        row_detect = ttk.Frame(frame_conn)
        row_detect.pack(fill=tk.X, pady=1)
        self.detect_status_var = tk.StringVar(value="正在检测...")
        ttk.Label(row_detect, textvariable=self.detect_status_var,
                  foreground="gray").pack(side=tk.LEFT)

        # 状态栏
        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(frame_conn, textvariable=self.status_var,
                  foreground="blue").pack(anchor=tk.W, pady=1)

        # 基础命令框架
        frame_cmd = ttk.LabelFrame(left_frame, text="基础命令", padding=3)
        frame_cmd.grid(row=1, column=0, sticky=tk.W+tk.E, padx=2, pady=2)

        # 使用Grid布局在frame_cmd内部，使组件紧凑
        # 第一行：查询版本/端口
        ttk.Button(frame_cmd, text="查询版本", command=self.cmd_version,
                   width=12).grid(row=0, column=0, padx=1, pady=1, sticky=tk.W)
        ttk.Button(frame_cmd, text="查询端口信息", command=self.cmd_port_info,
                   width=12).grid(row=0, column=1, padx=1, pady=1, sticky=tk.W)
        ttk.Label(frame_cmd, text="端口:").grid(row=0, column=2, padx=(5,0), sticky=tk.W)
        self.port_info_var = tk.StringVar(value="0")
        ttk.Entry(frame_cmd, textvariable=self.port_info_var, width=5).grid(row=0, column=3, padx=1, sticky=tk.W)

        # 第二行：读取电平
        ttk.Button(frame_cmd, text="读取电平", command=self.cmd_gpio_read,
                   width=12).grid(row=1, column=0, padx=1, pady=1, sticky=tk.W)
        ttk.Label(frame_cmd, text="GPIO:").grid(row=1, column=1, padx=(5,0), sticky=tk.W)
        self.gpio_read_var = tk.StringVar(value="0")
        ttk.Entry(frame_cmd, textvariable=self.gpio_read_var, width=5).grid(row=1, column=2, padx=1, sticky=tk.W)

        # 第三行：写入电平
        ttk.Button(frame_cmd, text="写入电平", command=self.cmd_gpio_write,
                   width=12).grid(row=2, column=0, padx=1, pady=1, sticky=tk.W)
        ttk.Label(frame_cmd, text="GPIO:").grid(row=2, column=1, padx=(5,0), sticky=tk.W)
        self.gpio_write_num_var = tk.StringVar(value="0")
        ttk.Entry(frame_cmd, textvariable=self.gpio_write_num_var, width=5).grid(row=2, column=2, padx=1, sticky=tk.W)
        ttk.Label(frame_cmd, text="电平:").grid(row=2, column=3, padx=(5,0), sticky=tk.W)
        self.gpio_write_val_var = tk.StringVar(value="0")
        ttk.Entry(frame_cmd, textvariable=self.gpio_write_val_var, width=5).grid(row=2, column=4, padx=1, sticky=tk.W)

        # 第四行：设置方向
        ttk.Button(frame_cmd, text="设置方向", command=self.cmd_gpio_dir,
                   width=12).grid(row=3, column=0, padx=1, pady=1, sticky=tk.W)
        ttk.Label(frame_cmd, text="GPIO:").grid(row=3, column=1, padx=(5,0), sticky=tk.W)
        self.gpio_dir_num_var = tk.StringVar(value="0")
        ttk.Entry(frame_cmd, textvariable=self.gpio_dir_num_var, width=5).grid(row=3, column=2, padx=1, sticky=tk.W)
        ttk.Label(frame_cmd, text="方向:").grid(row=3, column=3, padx=(5,0), sticky=tk.W)
        self.gpio_dir_val_var = tk.StringVar(value="0")
        ttk.Entry(frame_cmd, textvariable=self.gpio_dir_val_var, width=5).grid(row=3, column=4, padx=1, sticky=tk.W)

        # 第五行：发送数据
        ttk.Button(frame_cmd, text="发送数据", command=self.cmd_send_data,
                   width=12).grid(row=4, column=0, padx=1, pady=1, sticky=tk.W)
        ttk.Label(frame_cmd, text="端口:").grid(row=4, column=1, padx=(5,0), sticky=tk.W)
        self.send_port_var = tk.StringVar(value="0")
        ttk.Entry(frame_cmd, textvariable=self.send_port_var, width=5).grid(row=4, column=2, padx=1, sticky=tk.W)
        ttk.Label(frame_cmd, text="数据(hex):").grid(row=4, column=3, padx=(5,0), sticky=tk.W)
        self.send_data_var = tk.StringVar(value="00112233")
        # 此Entry跨多列，但使用grid时需指定columnspan
        ttk.Entry(frame_cmd, textvariable=self.send_data_var, width=45).grid(row=4, column=4, columnspan=2, padx=1, sticky=tk.W)

        # 第六行：原始包
        ttk.Button(frame_cmd, text="原始包", command=self.cmd_raw,
                   width=12).grid(row=5, column=0, padx=1, pady=1, sticky=tk.W)
        ttk.Label(frame_cmd, text="64字节hex:").grid(row=5, column=1, padx=(5,0), sticky=tk.W)
        self.raw_data_var = tk.StringVar()
        ttk.Entry(frame_cmd, textvariable=self.raw_data_var, width=65).grid(row=5, column=2, columnspan=4, padx=1, sticky=tk.W)

        # ========== 文件传输功能 ==========
        frame_file = ttk.LabelFrame(left_frame, text="文件传输 (SimpleSendData协议)", padding=3)
        frame_file.grid(row=2, column=0, sticky=tk.W+tk.E, padx=2, pady=2)

        # 发送文件部分
        ttk.Label(frame_file, text="发送文件:", font=('Arial', 9, 'bold')).grid(row=0, column=0, columnspan=5, sticky=tk.W, pady=1)

        self.file_path_var = tk.StringVar()
        ttk.Entry(frame_file, textvariable=self.file_path_var, width=75).grid(row=1, column=0, columnspan=4, padx=1, sticky=tk.W)
        ttk.Button(frame_file, text="选择文件", command=self.select_file, width=8).grid(row=1, column=4, padx=2)

        # 发送端口选择
        ttk.Label(frame_file, text="发送端口:").grid(row=2, column=0, sticky=tk.W, pady=1)
        self.send_file_port_var = tk.StringVar(value="0")
        ttk.Radiobutton(frame_file, text="端口0", variable=self.send_file_port_var,
                        value="0").grid(row=2, column=1, sticky=tk.W)
        ttk.Radiobutton(frame_file, text="端口1", variable=self.send_file_port_var,
                        value="1").grid(row=2, column=2, sticky=tk.W)

        ttk.Label(frame_file, text="Transfer ID:").grid(row=3, column=0, sticky=tk.W, pady=1)
        self.send_transfer_id_var = tk.StringVar(value="0x12")
        ttk.Entry(frame_file, textvariable=self.send_transfer_id_var, width=8).grid(row=3, column=1, sticky=tk.W, padx=1)

        ttk.Button(frame_file, text="开始发送文件", command=self.start_file_send, width=15).grid(row=3, column=2, columnspan=2, padx=1, pady=1)

        # 进度条
        self.send_progress = ttk.Progressbar(frame_file, orient=tk.HORIZONTAL, length=250, mode='determinate')
        self.send_progress.grid(row=4, column=0, columnspan=5, pady=1, padx=1, sticky=tk.W+tk.E)
        self.send_progress_label = ttk.Label(frame_file, text="")
        self.send_progress_label.grid(row=5, column=0, columnspan=5, sticky=tk.W)
        self.send_segment_label = ttk.Label(frame_file, text="")
        self.send_segment_label.grid(row=6, column=0, columnspan=5, sticky=tk.W)

        # 分隔线
        ttk.Separator(frame_file, orient=tk.HORIZONTAL).grid(row=7, column=0, columnspan=5, pady=3, sticky=tk.W+tk.E)

        # 接收解析部分
        ttk.Label(frame_file, text="接收解析:", font=('Arial', 9, 'bold')).grid(row=8, column=0, columnspan=5, sticky=tk.W, pady=1)

        ttk.Label(frame_file, text="Transfer ID:").grid(row=9, column=0, sticky=tk.W)
        self.recv_transfer_id_var = tk.StringVar(value="0x12")
        ttk.Entry(frame_file, textvariable=self.recv_transfer_id_var, width=15).grid(row=9, column=1, sticky=tk.W)

        ttk.Button(frame_file, text="准备接收", command=self.prepare_receive, width=10).grid(row=9, column=2, padx=1, sticky=tk.W+tk.E)
        ttk.Button(frame_file, text="清除接收状态", command=self.clear_receive_state, width=10).grid(row=9, column=3,  pady=1, padx=1, sticky=tk.W+tk.E)

        # 自动接收选项
        self.auto_recv_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame_file, text="自动接收文件", variable=self.auto_recv_var).grid(row=10, column=0, columnspan=2, sticky=tk.W, pady=1)
        ttk.Label(frame_file, text="默认保存目录:").grid(row=10, column=2, sticky=tk.W)
        self.recv_dir_var = tk.StringVar(value=self.default_recv_dir)
        ttk.Entry(frame_file, textvariable=self.recv_dir_var, width=40).grid(row=11, column=0, columnspan=3, padx=1, sticky=tk.W)
        ttk.Button(frame_file, text="浏览", command=self.select_recv_dir, width=6).grid(row=11, column=3, padx=2, sticky=tk.W)

        # 接收进度条
        self.recv_progress = ttk.Progressbar(frame_file, orient=tk.HORIZONTAL, length=250, mode='determinate')
        self.recv_progress.grid(row=12, column=0, columnspan=5, pady=1, padx=1, sticky=tk.W+tk.E)
        self.recv_progress_label = ttk.Label(frame_file, text="")
        self.recv_progress_label.grid(row=13, column=0, columnspan=5, sticky=tk.W)
        self.recv_segment_label = ttk.Label(frame_file, text="")
        self.recv_segment_label.grid(row=14, column=0, columnspan=5, sticky=tk.W)

        ttk.Button(frame_file, text="保存接收的文件", command=self.save_received_file, width=10).grid(row=15, column=0,columnspan=4,  pady=1, padx=1, sticky=tk.W+tk.E)

        # 接收状态显示
        self.recv_status_var = tk.StringVar(value="未准备接收")
        ttk.Label(frame_file, textvariable=self.recv_status_var, foreground="green").grid(row=16, column=0, columnspan=5, pady=1, sticky=tk.W)

        # ========== 右侧日志面板 ==========
        frame_log = ttk.LabelFrame(right_frame, text="日志与响应", padding=5)
        frame_log.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(frame_log, wrap=tk.WORD,
                                                   height=25, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 清除日志按钮
        ttk.Button(frame_log, text="清除日志", command=self.clear_log).pack(pady=2)
    # ------------------ USB HID操作 ------------------
    def _auto_detect_ports(self):
        """自动探测端口0和端口1的连接状态"""
        if not self.auto_detect_var.get():
            self.detect_status_var.set("自动检测已关闭")
            return
        if self.bound_port is not None:
            self.detect_status_var.set(f"已连接端口{self.bound_port}")
            return

        vid_str = self.entry_vid.get().strip()
        try:
            vid = int(vid_str, 16) if vid_str.startswith("0x") else int(vid_str)
        except ValueError:
            self.detect_status_var.set("VID无效")
            return

        port0_ok, port1_ok = usb_hid_transport.probe_devices(vid)

        if port0_ok and port1_ok:
            self.detect_status_var.set("端口0:在线 端口1:在线 - 请选择端口")
        elif port0_ok:
            self.detect_status_var.set("端口0:在线 端口1:离线")
            self.port_id_var.set("0")
        elif port1_ok:
            self.detect_status_var.set("端口0:离线 端口1:在线")
            self.port_id_var.set("1")
        else:
            self.detect_status_var.set("端口0:离线 端口1:离线")

    def connect_hid(self):
        vid_str = self.entry_vid.get().strip()
        port_id = int(self.port_id_var.get())

        if not vid_str:
            messagebox.showerror("错误", "请输入供应商ID (VID)")
            return
        try:
            if vid_str.startswith("0x"):
                vid = int(vid_str, 16)
            else:
                vid = int(vid_str)
        except ValueError:
            messagebox.showerror("错误", "VID必须是十六进制或十进制数字")
            return

        # 自动检测：连接前检查目标端口是否在线
        if self.auto_detect_var.get():
            port0_ok, port1_ok = usb_hid_transport.probe_devices(vid)
            target_ok = port0_ok if port_id == 0 else port1_ok
            if not target_ok:
                messagebox.showwarning("设备未检测到",
                    f"端口{port_id} (PID=0x{0x2107 + port_id:04X}) 未检测到设备。\n"
                    f"仍尝试连接...")
            self.detect_status_var.set(
                f"端口0:{'在线' if port0_ok else '离线'} 端口1:{'在线' if port1_ok else '离线'}")

        # 创建HID客户端
        self.hid_client = usb_hid_transport.HIDClient(vid=vid, label=f"Port{port_id}")

        # 连接设备
        if not self.hid_client.connect(port=port_id):
            messagebox.showerror("连接失败", "无法连接到USB HID设备")
            self.hid_client = None
            return

        # 发送ID包（保持与TCP协议兼容）
        id_packet = bytes([0x21, 0x07]) if port_id == 0 else bytes([0x21, 0x08])
        if not self.hid_client.send(id_packet):
            messagebox.showerror("发送ID包失败", "无法发送ID包到设备")
            self.hid_client.disconnect()
            self.hid_client = None
            return

        # 等待可能的错误响应（非阻塞检查）
        # USB HID没有直接的超时机制，这里简单等待一小段时间
        # 实际上，设备可能不会立即响应，我们假设连接成功
        self.log(f"已发送ID包: {id_packet.hex()}")

        # 绑定成功
        self.bound_port = port_id
        self.status_var.set(f"已连接USB HID (端口{port_id})")
        self.btn_connect.config(state=tk.DISABLED)
        self.btn_disconnect.config(state=tk.NORMAL)

        # 互锁：自动将发送端口设置为对方端口
        target_port = 1 - port_id
        self.send_file_port_var.set(str(target_port))
        self.send_port_var.set(str(target_port))

        self.log(f"成功连接到USB HID设备 (VID=0x{vid:04X})，绑定端口{port_id}，发送目标自动设为端口{target_port}")
        self.detect_status_var.set(f"已连接端口{port_id}")

        # 启动接收线程
        if not self.hid_client.start_receive_thread(packet_handler=self.handle_hid_packet):
            messagebox.showerror("错误", "无法启动接收线程")
            self.disconnect_hid()
            return

        self.running = True

    def handle_hid_packet(self, data, label):
        """HID数据包接收回调"""
        if len(data) == 64:
            self.msg_queue.put(("packet", data))
        else:
            self.msg_queue.put(("error", f"接收数据长度异常: {len(data)}"))

    def disconnect_hid(self):
        if self.hid_client:
            self.running = False
            self.hid_client.disconnect()
            self.hid_client = None
        if hasattr(self, '_log_file') and self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        if self.recv_thread and self.recv_thread.is_alive():
            self.recv_thread.join(timeout=1.0)
        self.bound_port = None
        self.status_var.set("未连接")
        self.btn_connect.config(state=tk.NORMAL)
        self.btn_disconnect.config(state=tk.DISABLED)
        self.log("已断开USB HID连接")
        # 恢复自动检测
        if self.auto_detect_var.get():
            self.root.after(500, self._auto_detect_ports)
        # 清除文件传输状态
        self.file_transfer_in_progress = False
        self.send_progress['value'] = 0
        self.send_progress_label.config(text="")
        self.send_segment_label.config(text="")

    def poll_queue(self):
        """定期检查队列，更新UI"""
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                if msg[0] == "packet":
                    self.handle_received_packet(msg[1])
                elif msg[0] == "error":
                    self.log(f"[错误] {msg[1]}")
                elif msg[0] == "disconnect":
                    self.log("连接已断开")
                    self.disconnect_hid()  # 自动清理
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.poll_queue)

    def handle_received_packet(self, packet):
        """处理接收到的64字节包，解析并显示"""
        self.log(f"接收: {packet.hex()}")
        # 简单解析
        if packet[0] == protocol.MAGIC1 and packet[1] == protocol.MAGIC2:
            cmd = packet[2]
            dlen = packet[3]
            data = packet[4:4+dlen]
            checksum = packet[4+dlen]
            self.log(f"  命令: 0x{cmd:02X}, 数据长度: {dlen}, 数据: {data.hex()}, 校验和: 0x{checksum:02X}")

            # 特殊处理：如果是接收数据包 (0x04)，可能包含文件传输数据
            if cmd == protocol.CMD_RECV_DATA:
                self.log("  [提示] 这是设备主动发送的接收数据包")
                # 发送端等待finish_status回传的处理
                if self.file_transfer_in_progress and self.waiting_for_finish_status:
                    payload = data[1:] if len(data) > 1 else b''
                    if len(payload) >= 3 and payload[0] == 0x04:
                        self._handle_finish_status_from_receiver(data)
                        return
                    # 非finish_status的CMD_RECV_DATA，继续走正常接收逻辑
                # 自动接收：如果没有接收会话且自动接收已启用，检测FILE_INFO握手
                if not self.recv_file_obj and self.auto_recv_var.get() and data and len(data) > 2:
                    payload = data[1:]  # skip port byte
                    if len(payload) >= 58 and payload[0] == 0x00:
                        self.recv_file_obj = SimpleRecvData()
                        self.recv_file_obj.set_transfer_id(0)  # accept any transfer ID
                        self.recv_file_obj.file_info_parsed = False
                        self.recv_status_var.set("自动接收中...")
                        self.log("检测到文件传输握手，自动启用接收")
                if self.recv_file_obj and data:
                    self.parse_received_file_data(data)

            # 如果是发送数据响应 (0x23)，表示上一个数据包发送成功
            if cmd == protocol.CMD_SEND_DATA_RSP and self.file_transfer_in_progress:
                self.handle_send_data_response(data)
        else:
            self.log("  魔数错误，非标准HID包")

    # ------------------ 文件传输相关函数 ------------------
    def select_file(self):
        """选择要发送的文件"""
        filename = filedialog.askopenfilename(title="选择文件")
        if filename:
            self.file_path_var.set(filename)

    def start_file_send(self):
        """开始发送文件"""
        if not self.hid_client:
            messagebox.showerror("错误", "请先连接到USB HID设备")
            return

        file_path = self.file_path_var.get()
        if not file_path:
            messagebox.showerror("错误", "请选择文件")
            return

        try:
            # 解析发送端口
            send_port = int(self.send_file_port_var.get())
        except ValueError:
            messagebox.showerror("错误", "无效的发送端口")
            return

        # 互锁检查：发送端口不能与绑定端口相同
        if send_port == self.bound_port:
            messagebox.showwarning("端口冲突",
                f"发送端口{send_port}与当前绑定端口{self.bound_port}相同！\n"
                f"请将发送端口改为端口{1 - self.bound_port}。")
            return

        try:
            # 解析Transfer ID
            transfer_id_str = self.send_transfer_id_var.get()
            if transfer_id_str.startswith("0x"):
                transfer_id = int(transfer_id_str, 16)
            else:
                transfer_id = int(transfer_id_str)
            if transfer_id < 0 or transfer_id > 255:
                messagebox.showerror("错误", "Transfer ID必须在0-255之间")
                return
        except ValueError:
            messagebox.showerror("错误", "无效的Transfer ID")
            return

        # 读取文件内容
        try:
            with open(file_path, 'rb') as f:
                file_data = f.read()
            self.log(f"读取文件成功: {file_path}, 大小: {len(file_data)} 字节")
            preview = file_data[:32]
            self.log(f"文件数据预览: {preview.hex()}")
        except Exception as e:
            messagebox.showerror("读取文件失败", str(e))
            return

        filename = os.path.basename(file_path)
        self.full_file_data = file_data
        self.full_filename = filename
        self.send_transfer_id = transfer_id

        # 分段判断
        MAX_SEGMENT_SIZE = 65535
        file_size = len(file_data)
        if file_size > MAX_SEGMENT_SIZE:
            total_segments = (file_size + MAX_SEGMENT_SIZE - 1) // MAX_SEGMENT_SIZE
            segment_size = (file_size + total_segments - 1) // total_segments
            # 对齐到 block_size(54) 的倍数
            segment_size = ((segment_size + 53) // 54) * 54
        else:
            total_segments = 1
            segment_size = file_size

        self.total_segments = total_segments
        self.current_segment = 0
        self.segment_size = segment_size
        self.send_port = send_port

        self.log(f"文件将分为 {total_segments} 段发送，每段约 {segment_size} 字节")

        # 开始发送第0段
        self._start_send_segment(0)

    def _start_send_segment(self, segment_index):
        """开始发送指定段"""
        start = segment_index * self.segment_size
        end = min(start + self.segment_size, len(self.full_file_data))
        segment_data = self.full_file_data[start:end]

        self.send_file_obj = SimpleSendData(
            list(segment_data), self.full_filename,
            segment_index=segment_index, total_segments=self.total_segments
        )
        self.send_file_obj.set_transfer_id(self.send_transfer_id)

        # 生成文件信息包
        ret, file_info_data = self.send_file_obj.make_file_info()
        if not ret:
            messagebox.showerror("错误", "生成文件信息失败")
            return
        self.log(f"段{segment_index} 文件信息数据: {file_info_data.hex()}")

        # 生成所有数据块
        ret, self.send_blocks = self.send_file_obj.make_transfer_datas()
        if not ret:
            messagebox.showerror("错误", "生成数据块失败")
            return
        self.log(f"段{segment_index} 生成了 {len(self.send_blocks)} 个数据块")

        # 生成结束包
        ret, self.finish_data = self.send_file_obj.make_finish()
        if not ret:
            messagebox.showerror("错误", "生成结束包失败")
            return

        # 准备发送 - 将所有需要发送的数据包整理成列表
        self.pending_data_packets = []
        self.pending_data_packets.append(('info', file_info_data))
        for block_idx, block in enumerate(self.send_blocks):
            self.pending_data_packets.append(('data', block, block_idx))
        self.pending_data_packets.append(('finish', self.finish_data))

        # 开始发送
        self.total_packets = len(self.pending_data_packets)
        self.sent_packets = 0
        self.current_block_index = 0
        self.file_transfer_in_progress = True

        seg_text = f"段 {segment_index+1}/{self.total_segments}" if self.total_segments > 1 else ""
        self.log(f"开始发送: {self.full_filename}, {seg_text}, 大小: {len(segment_data)} 字节, 总包数: {self.total_packets}")
        self.send_progress['maximum'] = self.total_packets
        self.send_progress['value'] = 0
        self.send_progress_label.config(text=f"准备发送... 0/{self.total_packets}")
        if self.total_segments > 1:
            self.send_segment_label.config(text=f"段 {segment_index+1}/{self.total_segments}")

        # 发送第一个包
        self.root.after(10, self.send_next_packet)

    def send_next_packet(self):
        """发送下一个待发送的数据包"""
        if not self.file_transfer_in_progress:
            return

        if self.current_block_index < len(self.pending_data_packets):
            packet_info = self.pending_data_packets[self.current_block_index]

            if packet_info[0] == 'info':
                _, chunk = packet_info
                packet_type = "文件信息"
            elif packet_info[0] == 'data':
                _, chunk, block_idx = packet_info
                packet_type = f"数据块{block_idx}"
            else:  # finish
                _, chunk = packet_info
                packet_type = "结束包"

            # 构造并发送SEND_DATA包
            send_packet = bytes([self.send_port]) + chunk
            self.send_packet(protocol.CMD_SEND_DATA_REQ, send_packet)

            self.log(f"发送 {packet_type} 包 {self.current_block_index + 1}/{self.total_packets}")
            self.current_block_index += 1
            self.root.update_idletasks()  # 强制更新UI，避免卡住
            # 不再自动发送下一个包，等待设备的CMD_SEND_DATA_RSP响应后再发送
        else:
            self.log("所有包已发送完成，等待响应...")

    def handle_send_data_response(self, data):
        """处理发送数据响应 (0x23)"""
        self.sent_packets += 1
        self.send_progress['value'] = self.sent_packets
        seg_text = f"段 {self.current_segment+1}/{self.total_segments} - " if self.total_segments > 1 else ""
        self.send_progress_label.config(text=f"{seg_text}已确认 {self.sent_packets}/{self.total_packets} 个包")
        self.root.update_idletasks()

        # 发送下一个包
        self.root.after(10, self.send_next_packet)

        if self.sent_packets >= self.total_packets:
            # 所有包已确认，等待接收端回传finish_status
            self.log("所有数据包已确认，等待接收端finish_status...")
            self.waiting_for_finish_status = True
            self.send_progress_label.config(text=f"{seg_text}等待接收端校验...")
            # 设置5秒超时，兼容不回传finish_status的旧版本
            self.root.after(5000, self._finish_status_timeout)

    def _handle_finish_status_from_receiver(self, data):
        """处理接收端回传的finish_status"""
        payload = data[1:]  # skip port byte
        if len(payload) < 3 or payload[0] != 0x04:  # SIMPLE_CMD_FINISH_STATUS
            self.log(f"收到非finish_status的CMD_RECV_DATA，忽略")
            return

        transfer_id = payload[1]
        status = payload[2]
        self.waiting_for_finish_status = False

        if status == protocol.TRANSFER_SUCCESS:  # 0x01
            self.log("接收端确认：传输成功，CRC校验通过")
            self._complete_current_segment()

        elif status == protocol.TRANSFER_MISSING_BLOCKS:  # 0x02
            if len(payload) >= 4:
                missing_count = payload[3]
                missing_blocks = list(payload[4:4+missing_count])
                self.log(f"接收端报告缺失 {missing_count} 个块: {missing_blocks}")
                self._retransmit_blocks(missing_blocks)
            else:
                self.log("接收端报告缺失块但未提供块号列表")
                self._complete_current_segment()

        elif status == protocol.TRANSFER_CRC_ERROR:  # 0x04
            self.log("接收端报告CRC校验错误！数据可能已损坏")
            self._complete_current_segment()

        else:
            self.log(f"接收端返回未知状态: 0x{status:02X}")
            self._complete_current_segment()

    def _retransmit_blocks(self, missing_block_ids):
        """重传缺失的数据块"""
        # 构建重传包列表：缺失的数据块 + 结束包
        self.pending_data_packets = []
        for block_id in missing_block_ids:
            if 0 <= block_id < len(self.send_blocks):
                block = self.send_blocks[block_id]
                self.pending_data_packets.append(('data', block, block_id))
            else:
                self.log(f"警告：缺失块号 {block_id} 超出范围(0-{len(self.send_blocks)-1})，跳过")
        self.pending_data_packets.append(('finish', self.finish_data))

        self.total_packets = len(self.pending_data_packets)
        self.sent_packets = 0
        self.current_block_index = 0

        self.log(f"开始重传 {len(missing_block_ids)} 个缺失块 + 结束包")
        self.send_progress['maximum'] = self.total_packets
        self.send_progress['value'] = 0
        seg_text = f"段 {self.current_segment+1}/{self.total_segments} - " if self.total_segments > 1 else ""
        self.send_progress_label.config(text=f"{seg_text}重传中... 0/{self.total_packets}")

        self.root.after(10, self.send_next_packet)

    def _finish_status_timeout(self):
        """finish_status等待超时"""
        if self.waiting_for_finish_status:
            self.log("等待接收端finish_status超时，视为传输成功")
            self._complete_current_segment()

    def _complete_current_segment(self):
        """完成当前段的发送"""
        self.waiting_for_finish_status = False
        if self.current_segment + 1 < self.total_segments:
            self.current_segment += 1
            self.log(f"段 {self.current_segment}/{self.total_segments} 发送完成，开始下一段")
            self.root.after(10, lambda: self._start_send_segment(self.current_segment))
        else:
            self.file_transfer_in_progress = False
            self.send_progress_label.config(text="文件发送完成！")
            if self.total_segments > 1:
                self.send_segment_label.config(text=f"全部 {self.total_segments} 段发送完成")
            self.log("所有文件数据包发送完成")
            messagebox.showinfo("完成", "文件发送完成")

    # ------------------ 文件接收解析 ------------------
    def prepare_receive(self):
        """准备接收文件"""
        try:
            transfer_id_str = self.recv_transfer_id_var.get()
            if transfer_id_str.startswith("0x"):
                transfer_id = int(transfer_id_str, 16)
            else:
                transfer_id = int(transfer_id_str)
        except ValueError:
            messagebox.showerror("错误", "无效的Transfer ID")
            return

        self.recv_file_obj = SimpleRecvData()
        self.recv_file_obj.set_transfer_id(transfer_id)
        self.recv_file_obj.file_info_parsed = False
        self.recv_status_var.set(f"已准备接收 Transfer ID: 0x{transfer_id:02X}")
        self.log(f"已准备接收文件，Transfer ID: 0x{transfer_id:02X}")

    def parse_received_file_data(self, data):
        """解析接收到的文件数据"""
        if not self.recv_file_obj:
            self.log("未准备接收，忽略数据")
            return

        if len(data) < 2:
            return

        port = data[0]
        payload = data[1:]

        self.log(f"解析接收数据: port={port}, payload={payload.hex()}")

        # 尝试解析为文件信息包
        if not hasattr(self.recv_file_obj, 'file_info_parsed') or not self.recv_file_obj.file_info_parsed:
            if len(payload) >= 58 and payload[0] == 0x00:
                if self.recv_file_obj.parse_file_info(list(payload)):
                    self.recv_file_obj.file_info_parsed = True
                    seg_idx = self.recv_file_obj.segment_index
                    seg_total = self.recv_file_obj.total_segments
                    self.log(f"解析文件信息成功: 文件名={self.recv_file_obj.filename}, "
                             f"大小={self.recv_file_obj.data_size}, 块数={self.recv_file_obj.block_counts}, "
                             f"段={seg_idx+1}/{seg_total}")
                    if self.recv_file_obj.block_counts > 0:
                        self.recv_progress['maximum'] = self.recv_file_obj.block_counts
                        self.recv_progress['value'] = 0
                    if seg_total > 1:
                        if self.segment_collector is None:
                            self.segment_collector = MultiSegmentCollector(seg_total, self.recv_file_obj.filename)
                        self.recv_segment_label.config(text=f"接收段 {seg_idx+1}/{seg_total}")
                    return

        # 尝试解析为数据块
        if len(payload) >= 5 and payload[0] == 0x02:
            if self.recv_file_obj.transfer_id == 0:
                real_id = payload[1]
                self.recv_file_obj.set_transfer_id(real_id)
                self.log(f"自动检测到Transfer ID: 0x{real_id:02X}")
            if self.recv_file_obj.recv_data(list(payload)):
                received = len(self.recv_file_obj.block_list)
                total = self.recv_file_obj.block_counts
                seg_text = ""
                if self.recv_file_obj.total_segments > 1:
                    seg_text = f"段 {self.recv_file_obj.segment_index+1}/{self.recv_file_obj.total_segments} - "
                self.log(f"接收数据块 {received}/{total}")
                self.recv_status_var.set(f"{seg_text}接收进度: {received}/{total}")
                self.recv_progress['value'] = received
                self.recv_progress_label.config(text=f"{seg_text}块 {received}/{total}")
                return

        # 尝试解析为结束包
        if len(payload) >= 2 and payload[0] == 0x03:
            self.log("收到结束包")
            ret, finish_status, seg_info = self.recv_file_obj.finish()
            segment_index, total_segments, is_last = seg_info

            if finish_status:
                self.log(f"段{segment_index} 接收完成状态: {finish_status.hex()}")
                # 将finish_status回传给发送端（通过MCU中继）
                # port是接收方自己的端口，需要发送到对方端口
                reply_port = 1 - port
                send_back = bytes([reply_port]) + finish_status
                self.send_packet(protocol.CMD_SEND_DATA_REQ, send_back)
                self.log(f"已向发送端(端口{reply_port})回传finish_status")

            if total_segments > 1:
                # 多段模式
                if self.segment_collector:
                    self.segment_collector.add_segment(segment_index, self.recv_file_obj.data, self.recv_file_obj.file_crc)

                if not is_last:
                    # 非末段：保存临时文件，准备接收下一段
                    recv_dir = self.recv_dir_var.get() or self.default_recv_dir
                    os.makedirs(recv_dir, exist_ok=True)
                    temp_path = os.path.join(recv_dir, f"{self.recv_file_obj.filename}.part{segment_index}")
                    with open(temp_path, 'wb') as f:
                        f.write(bytes(self.recv_file_obj.data))
                    self.log(f"段{segment_index} 已保存临时文件: {temp_path}")

                    # 准备接收下一段
                    self.recv_file_obj = SimpleRecvData()
                    self.recv_file_obj.set_transfer_id(0)
                    self.recv_file_obj.file_info_parsed = False
                    self.recv_status_var.set(f"段{segment_index}完成，等待下一段...")
                    self.recv_progress['value'] = 0
                    self.recv_segment_label.config(text=f"段 {segment_index+1}/{total_segments} 已完成")
                else:
                    # 末段：合并所有段
                    self.log("所有段接收完成，开始合并")
                    self.merge_segments()
            else:
                # 单段模式（兼容原有逻辑）
                self.recv_status_var.set("文件接收完成，可保存")
                if self.auto_recv_var.get() and self.recv_file_obj.data:
                    self.auto_save_received_file()
            return

        self.log(f"未知数据包类型: {payload.hex()}")

    def save_received_file(self):
        """保存接收到的文件"""
        if not self.recv_file_obj or not hasattr(self.recv_file_obj, 'data') or not self.recv_file_obj.data:
            messagebox.showerror("错误", "没有接收到文件数据")
            return

        if not self.recv_file_obj.filename:
            filename = "received_file.bin"
        else:
            filename = self.recv_file_obj.filename

        save_path = filedialog.asksaveasfilename(
            title="保存文件",
            initialfile=filename,
            defaultextension=".bin"
        )
        if save_path:
            try:
                with open(save_path, 'wb') as f:
                    f.write(bytes(self.recv_file_obj.data))
                messagebox.showinfo("成功", f"文件已保存到: {save_path}")
                self.log(f"文件已保存: {save_path}")

                # 验证CRC
                calc_crc = self.recv_file_obj.calc_crc()
                if calc_crc == self.recv_file_obj.file_crc:
                    self.log("CRC校验成功")
                else:
                    self.log(f"CRC校验失败: 计算值 0x{calc_crc:08X}, 期望值 0x{self.recv_file_obj.file_crc:08X}")
            except Exception as e:
                messagebox.showerror("保存失败", str(e))

    def clear_receive_state(self):
        """清除接收状态"""
        self.recv_file_obj = None
        self.segment_collector = None
        self.recv_status_var.set("未准备接收")
        self.recv_progress['value'] = 0
        self.recv_progress_label.config(text="")
        self.recv_segment_label.config(text="")
        self.log("已清除接收状态")

    def select_recv_dir(self):
        """选择默认接收目录"""
        dir_path = filedialog.askdirectory(title="选择默认保存目录")
        if dir_path:
            self.recv_dir_var.set(dir_path)
            self.default_recv_dir = dir_path

    def auto_save_received_file(self):
        """自动保存接收到的文件到默认目录，然后提示用户选择最终位置"""
        if not self.recv_file_obj or not self.recv_file_obj.data:
            return
        filename = self.recv_file_obj.filename or "received_file.bin"
        recv_dir = self.recv_dir_var.get() or self.default_recv_dir
        os.makedirs(recv_dir, exist_ok=True)
        save_path = os.path.join(recv_dir, filename)
        base, ext = os.path.splitext(save_path)
        counter = 1
        while os.path.exists(save_path):
            save_path = f"{base}_{counter}{ext}"
            counter += 1
        with open(save_path, 'wb') as f:
            f.write(bytes(self.recv_file_obj.data))
        self.log(f"文件已自动保存: {save_path}")
        self.recv_status_var.set(f"已保存: {os.path.basename(save_path)}")
        # 延迟弹出保存对话框，避免阻塞主线程导致finish_status回传延迟
        self.root.after(0, lambda: self._ask_save_location(save_path, filename, recv_dir, ext))

    def _ask_save_location(self, save_path, filename, recv_dir, ext):
        """弹出保存位置选择对话框（延迟执行，避免阻塞主线程）"""
        final_path = filedialog.asksaveasfilename(
            title="文件已接收完成，选择保存位置",
            initialfile=filename,
            initialdir=recv_dir,
            defaultextension=ext or ".bin"
        )
        if final_path and final_path != save_path:
            shutil.copy2(save_path, final_path)
            self.log(f"文件已复制到: {final_path}")
        self.recv_file_obj = None

    def merge_segments(self):
        """合并多段接收的文件"""
        import glob as glob_module
        collector = self.segment_collector
        if not collector or not collector.is_complete():
            self.log("段数据不完整，无法合并")
            return

        merged = collector.merge()
        filename = collector.filename or "received_file.bin"
        recv_dir = self.recv_dir_var.get() or self.default_recv_dir
        os.makedirs(recv_dir, exist_ok=True)

        # 保存合并后的文件
        save_path = os.path.join(recv_dir, filename)
        base, ext = os.path.splitext(save_path)
        counter = 1
        while os.path.exists(save_path):
            save_path = f"{base}_{counter}{ext}"
            counter += 1
        with open(save_path, 'wb') as f:
            f.write(merged)
        self.log(f"多段文件已合并保存: {save_path} ({len(merged)} 字节)")

        # 清理临时文件
        temp_pattern = os.path.join(recv_dir, f"{collector.filename}.part*")
        for temp_file in glob_module.glob(temp_pattern):
            try:
                os.remove(temp_file)
                self.log(f"已删除临时文件: {temp_file}")
            except Exception as e:
                self.log(f"删除临时文件失败: {e}")

        self.recv_status_var.set(f"已合并保存: {os.path.basename(save_path)}")
        self.recv_segment_label.config(text=f"全部 {collector.total_segments} 段合并完成")

        # 提示用户选择最终位置
        final_path = filedialog.asksaveasfilename(
            title="多段文件合并完成，选择保存位置",
            initialfile=filename,
            initialdir=recv_dir,
            defaultextension=ext or ".bin"
        )
        if final_path and final_path != save_path:
            shutil.copy2(save_path, final_path)
            self.log(f"文件已复制到: {final_path}")

        self.segment_collector = None
        self.recv_file_obj = None

    # ------------------ 发送命令 ------------------
    def send_packet(self, cmd, data):
        """构造并发送64字节HID包，自动填充校验和"""
        if not self.hid_client:
            messagebox.showerror("错误", "未连接到USB HID设备")
            return False
        packet = protocol.build_packet(cmd, data)
        try:
            self.hid_client.send(packet)
            self.log(f"发送: {packet.hex()}")
            return True
        except Exception as e:
            self.log(f"发送失败: {e}")
            messagebox.showerror("发送失败", str(e))
            return False

    def cmd_version(self):
        """查询MCU版本"""
        self.send_packet(protocol.CMD_VERSION_REQ, b'')

    def cmd_port_info(self):
        """查询端口信息"""
        try:
            port = int(self.port_info_var.get())
        except ValueError:
            messagebox.showerror("错误", "端口号必须是数字")
            return
        self.send_packet(protocol.CMD_PORT_INFO_REQ, bytes([port]))

    def cmd_gpio_read(self):
        """读取GPIO电平"""
        try:
            gpio = int(self.gpio_read_var.get())
        except ValueError:
            messagebox.showerror("错误", "GPIO编号必须是数字")
            return
        self.send_packet(protocol.CMD_GPIO_REQ, bytes([protocol.GPIO_OPT_LEVEL, gpio, 0x00]))

    def cmd_gpio_write(self):
        """写入GPIO电平"""
        try:
            gpio = int(self.gpio_write_num_var.get())
            level = int(self.gpio_write_val_var.get())
        except ValueError:
            messagebox.showerror("错误", "GPIO编号和电平必须是数字")
            return
        if level not in (0, 1):
            messagebox.showerror("错误", "电平必须为0或1")
            return
        self.send_packet(protocol.CMD_GPIO_REQ, bytes([protocol.GPIO_OPT_LEVEL, gpio, 0x01, level]))

    def cmd_gpio_dir(self):
        """设置GPIO方向"""
        try:
            gpio = int(self.gpio_dir_num_var.get())
            direction = int(self.gpio_dir_val_var.get())
        except ValueError:
            messagebox.showerror("错误", "GPIO编号和方向必须是数字")
            return
        if direction not in (0, 1):
            messagebox.showerror("错误", "方向必须为0(输出)或1(输入)")
            return
        self.send_packet(protocol.CMD_GPIO_REQ, bytes([protocol.GPIO_OPT_DIR, gpio, direction]))

    def cmd_send_data(self):
        """发送数据命令"""
        try:
            port = int(self.send_port_var.get())
        except ValueError:
            messagebox.showerror("错误", "端口号必须是数字")
            return
        if self.bound_port is not None and port == self.bound_port:
            messagebox.showwarning("端口冲突",
                f"发送端口{port}与当前绑定端口{self.bound_port}相同！\n"
                f"请将发送端口改为端口{1 - self.bound_port}。")
            return
        hex_str = self.send_data_var.get().replace(" ", "")
        try:
            data_bytes = bytes.fromhex(hex_str)
        except ValueError:
            messagebox.showerror("错误", "无效的十六进制字符串")
            return
        if len(data_bytes) > 16:
            messagebox.showerror("错误", "数据不能超过16字节")
            return
        # 填充到16字节
        if len(data_bytes) < 16:
            data_bytes = data_bytes + bytes(16 - len(data_bytes))
        self.send_packet(protocol.CMD_SEND_DATA_REQ, bytes([port]) + data_bytes)

    def cmd_raw(self):
        """发送原始64字节包"""
        hex_str = self.raw_data_var.get().replace(" ", "")
        if len(hex_str) != 128:
            messagebox.showerror("错误", "原始包必须为64字节（128个十六进制字符）")
            return
        try:
            raw = bytes.fromhex(hex_str)
        except ValueError:
            messagebox.showerror("错误", "无效的十六进制字符串")
            return
        if len(raw) != 64:
            messagebox.showerror("错误", "数据长度不是64字节")
            return
        try:
            self.hid_client.send(raw)
            self.log(f"发送原始包: {raw.hex()}")
        except Exception as e:
            self.log(f"发送失败: {e}")
            messagebox.showerror("发送失败", str(e))

    def log(self, msg):
        """在日志区域添加消息，并写入日志文件"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] {msg}"
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        if hasattr(self, '_log_file') and self._log_file:
            try:
                self._log_file.write(line + "\n")
                self._log_file.flush()
            except Exception:
                pass

    def clear_log(self):
        """清除日志"""
        self.log_text.delete(1.0, tk.END)


def main():
    root = tk.Tk()
    app = HIDHostGUI(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.disconnect_hid(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()