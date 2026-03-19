#!/usr/bin/env python3
"""
USB HID传输模块
仿照tcp_transport的API，提供USB HID客户端功能
握手时根据设备ID（PID）0x2107和0x2108判断连接的端口0或是端口1
"""

import threading
import queue
import time
import sys

try:
    import hid
    HID_AVAILABLE = True
except ImportError:
    HID_AVAILABLE = False
    print("警告: hidapi模块未安装，USB HID功能不可用。请使用 'pip install hidapi' 安装。")

# 设备ID定义
DEVICE_ID_PORT0 = 0x2107
DEVICE_ID_PORT1 = 0x2108

# 默认供应商ID（可以根据实际情况修改）
DEFAULT_VENDOR_ID = 0x413d  # 示例VID，需根据实际设备修改


class HIDClient:
    """
    USB HID客户端，管理设备连接和接收线程
    """

    def __init__(self, vid=None, pid=None, label="HIDClient", packet_handler=None):
        """
        初始化USB HID客户端

        参数:
            vid: 供应商ID（十六进制整数），如果为None则使用默认值
            pid: 产品ID（十六进制整数），如果为None则根据端口自动选择（0x2107或0x2108）
            label: 客户端标签，用于日志
            packet_handler: 数据包处理回调函数，接收(data, label)参数
        """
        self.vid = vid if vid is not None else DEFAULT_VENDOR_ID
        self.pid = pid  # 可能为None，在connect中根据端口选择
        self.label = label
        self.packet_handler = packet_handler
        self.device = None
        self.recv_thread = None
        self.running = False
        self.stop_event = threading.Event()
        self.port = None  # 绑定的端口（0或1）

    def connect(self, port=0, timeout=10.0):
        """
        连接到USB HID设备

        参数:
            port: 要绑定的端口（0或1），对应设备ID 0x2107或0x2108
            timeout: 连接超时时间（秒）（未完全实现）

        返回:
            成功返回True，失败返回False
        """
        if not HID_AVAILABLE:
            print(f"[{self.label}] hidapi模块不可用，无法连接USB HID设备")
            return False

        if port not in (0, 1):
            print(f"[{self.label}] 端口必须是0或1")
            return False

        self.port = port
        target_pid = DEVICE_ID_PORT0 if port == 0 else DEVICE_ID_PORT1
        if self.pid is not None and self.pid != target_pid:
            print(f"[{self.label}] 指定的PID与端口不匹配，使用端口{port}对应的PID 0x{target_pid:04X}")

        self.pid = target_pid

        try:
            # 枚举设备
            devices = hid.enumerate(self.vid, self.pid)
            if not devices:
                print(f"[{self.label}] 未找到VID=0x{self.vid:04X}, PID=0x{self.pid:04X}的USB HID设备")
                return False

            # 选择第一个设备
            device_info = devices[0]
            self.device = hid.device()
            self.device.open_path(device_info['path'])

            # 设置非阻塞读取
            self.device.set_nonblocking(1)

            # 验证设备ID（通过PID已确认）
            print(f"[{self.label}] 成功连接到USB HID设备 (VID=0x{self.vid:04X}, PID=0x{self.pid:04X})，绑定端口{port}")
            return True
        except Exception as e:
            print(f"[{self.label}] 连接失败: {e}")
            self.device = None
            return False

    def start_receive_thread(self, packet_handler=None):
        """
        启动接收线程

        参数:
            packet_handler: 可选的覆盖数据包处理回调函数

        返回:
            成功返回True，失败返回False
        """
        if not self.device:
            print(f"[{self.label}] 未连接，无法启动接收线程")
            return False

        if packet_handler:
            self.packet_handler = packet_handler

        self.stop_event.clear()
        self.running = True
        self.recv_thread = threading.Thread(
            target=self._recv_loop,
            daemon=True
        )
        self.recv_thread.start()
        
        return True

    def _recv_loop(self):
        """
        接收循环，在新线程中运行
        从HID设备读取64字节报告
        """
        print(f"[{self.label}] 接收线程已启动")
        while self.running and not self.stop_event.is_set():
            try:
                # HID读取，超时1秒（通过非阻塞模式实现）
                data = self.device.read(64)
                if data:
                    # data是整数列表，转换为bytes
                    data_bytes = bytes(data)
                    if len(data_bytes) == 64:
                        if self.packet_handler:
                            print(f"[{self.label}] 收到数据: {len(data_bytes)} 字节")
                            self.packet_handler(data_bytes, self.label)
                    else:
                        print(f"[{self.label}] 收到异常长度数据: {len(data_bytes)} 字节")
                # 无数据时继续循环
            except Exception as e:
                if self.running:
                    print(f"[{self.label}] 接收错误: {e}")
                break
        self.disconnect()

    def send(self, data):
        """
        发送数据到USB HID设备

        参数:
            data: 要发送的字节数据（应为64字节）

        返回:
            成功返回True，失败返回False
        """
        if not self.device:
            print(f"[{self.label}] 未连接，无法发送")
            return False

        if len(data) != 64:
            print(f"[{self.label}] 警告: HID报告应为64字节，实际为{len(data)}字节，已自动填充或截断")
            # 填充到64字节
            if len(data) < 64:
                data = data + bytes(64 - len(data))
            else:
                data = data[:64]

        try:
            # HID写入，data应为整数列表
            self.device.write([0]+list(data))
            return True
        except Exception as e:
            print(f"[{self.label}] 发送失败: {e}")
            return False

    def disconnect(self):
        """
        断开连接并停止接收线程
        """
        self.running = False
        self.stop_event.set()

        if self.device:
            try:
                self.device.close()
            except:
                pass
            self.device = None

        if self.recv_thread and self.recv_thread.is_alive():
            self.recv_thread.join(timeout=2.0)

        print(f"[{self.label}] 已断开连接")


class ThreadedHIDServer:
    """
    线程化HID服务器（占位符）
    USB HID通常不采用服务器模式，此类仅用于API兼容性
    """
    def __init__(self, vid=None, pid=None, client_handler=None):
        print("警告: USB HID不支持服务器模式，ThreadedHIDServer仅为兼容性占位符")
        self.vid = vid
        self.pid = pid
        self.client_handler = client_handler
        self.running = False

    def start(self):
        print("ThreadedHIDServer.start() 未实现")
        return False

    def stop(self):
        print("ThreadedHIDServer.stop() 未实现")
        self.running = False


def recv_exact(hid_device, size, timeout=None):
    """
    从HID设备接收指定大小的数据（模拟TCP行为）

    参数:
        hid_device: hid.device对象
        size: 要接收的数据大小
        timeout: 超时时间（秒），None表示无超时

    返回:
        接收到的数据，如果连接关闭或出错返回空字节串
    """
    if not hid_device:
        return b''

    data = b''
    start_time = time.time()
    while len(data) < size:
        if timeout is not None and time.time() - start_time > timeout:
            return b''
        try:
            chunk_list = hid_device.read(64, timeout_ms=100 if timeout else 1000)
            if chunk_list:
                chunk = bytes(chunk_list)
                # 取所需部分
                remaining = size - len(data)
                if len(chunk) >= remaining:
                    data += chunk[:remaining]
                    break
                else:
                    data += chunk
        except Exception:
            return b''
    return data


def send_all(hid_device, data):
    """
    确保发送所有数据（模拟TCP行为）

    参数:
        hid_device: hid.device对象
        data: 要发送的数据

    返回:
        成功返回True，失败返回False
    """
    if not hid_device:
        return False

    # HID报告固定为64字节，需要分片
    report_size = 64
    for i in range(0, len(data), report_size):
        chunk = data[i:i+report_size]
        if len(chunk) < report_size:
            chunk = chunk + bytes(report_size - len(chunk))
        try:
            hid_device.write(list(chunk))
        except Exception:
            return False
    return True


class QueuePacketHandler:
    """
    将接收到的数据包放入队列，供其他线程处理
    与tcp_transport中的相同
    """

    def __init__(self, queue_obj):
        """
        初始化队列数据包处理器

        参数:
            queue_obj: queue.Queue对象
        """
        self.queue = queue_obj

    def __call__(self, data, label):
        """
        回调函数，将数据包放入队列

        参数:
            data: 接收到的数据
            label: 客户端标签
        """
        self.queue.put((label, data))