#!/usr/bin/env python3
"""
HID协议定义和数据包处理模块
包含协议常量、数据包构建和解析函数
"""

# 协议魔数
MAGIC1 = 0x44
MAGIC2 = 0x47

# 命令字
CMD_VERSION_REQ = 0x00
CMD_VERSION_RSP = 0x20
CMD_PORT_INFO_REQ = 0x01
CMD_PORT_INFO_RSP = 0x21
CMD_GPIO_REQ = 0x02
CMD_GPIO_RSP = 0x22
CMD_SEND_DATA_REQ = 0x03
CMD_SEND_DATA_RSP = 0x23
CMD_RECV_DATA = 0x04
CMD_ERROR = 0xFF

# GPIO子命令
GPIO_OPT_LEVEL = 0x01
GPIO_OPT_DIR = 0x02

GPIO_SUCCESS = 0x00
GPIO_FAILED = 0x01
GPIO_INVALID = 0x02

# 错误码
ERR_PARSE_FAILED = 0x01
ERR_CHECKSUM = 0x02
ERR_FORMAT = 0x03
ERR_INVALID_CMD = 0x04
ERR_DATA_LEN = 0x05
ERR_TARGET_PORT_NOT_CONNECTED = 0x06  # 目标端口未连接

# 端口ID包
ID_PORT0 = bytes([0x21, 0x07])
ID_PORT1 = bytes([0x21, 0x08])


def build_packet(cmd, data):
    """
    构建64字节HID数据包

    参数:
        cmd: 命令字节
        data: 数据字节串

    返回:
        64字节的数据包
    """
    data_len = len(data)
    header = bytes([MAGIC1, MAGIC2, cmd, data_len])
    payload = header + data
    checksum = sum(payload) & 0xFF
    packet = payload + bytes([checksum])
    # 填充到64字节
    if len(packet) < 64:
        packet += bytes(64 - len(packet))
    return packet


def parse_packet(data):
    """
    解析64字节HID数据包

    参数:
        data: 64字节的数据包

    返回:
        (cmd, data_field, error_code)
        如果解析成功，error_code为None
        如果解析失败，cmd和data_field为None，error_code为错误码
    """
    if len(data) != 64:
        return None, None, ERR_FORMAT
    if data[0] != MAGIC1 or data[1] != MAGIC2:
        return None, None, ERR_PARSE_FAILED
    data_len = data[3]
    if data_len > 59:
        return None, None, ERR_DATA_LEN
    payload_len = 4 + data_len
    if payload_len > 64:
        return None, None, ERR_DATA_LEN
    received_checksum = data[payload_len]
    calc_checksum = sum(data[:payload_len]) & 0xFF
    if calc_checksum != received_checksum:
        return None, None, ERR_CHECKSUM
    cmd = data[2]
    data_field = data[4:payload_len]
    return cmd, data_field, None


def print_packet(prefix, data):
    """
    打印数据包信息，用于调试

    参数:
        prefix: 前缀字符串
        data: 数据包字节串
    """
    print(f"{prefix} 收到数据包 ({len(data)} 字节):")
    print("  ", data.hex())
    if len(data) >= 5 and data[0] == MAGIC1 and data[1] == MAGIC2:
        cmd = data[2]
        dlen = data[3]
        data_field = data[4:4+dlen]
        checksum = data[4+dlen]
        print(f"    命令: 0x{cmd:02X}, 数据长度: {dlen}, 数据: {data_field.hex()}, 校验和: 0x{checksum:02X}")
    else:
        print("    不是有效的HID包或长度不足")


def get_error_description(error_code):
    """
    获取错误码的描述

    参数:
        error_code: 错误码

    返回:
        错误描述字符串
    """
    error_descriptions = {
        ERR_PARSE_FAILED: "解析失败",
        ERR_CHECKSUM: "校验和错误",
        ERR_FORMAT: "数据包格式错误",
        ERR_INVALID_CMD: "无效命令",
        ERR_DATA_LEN: "数据长度错误",
        ERR_TARGET_PORT_NOT_CONNECTED: "目标端口未连接",
    }
    return error_descriptions.get(error_code, f"未知错误码: 0x{error_code:02X}")


# SimpleSendData协议相关常量（从simple_send_data.py中提取）
# 这些常量用于文件传输协议
SIMPLE_CMD_FILE_INFO = 0x00
SIMPLE_CMD_START_TRANSFER = 0x01
SIMPLE_CMD_TRANSFER_DATA = 0x02
SIMPLE_CMD_FINISH = 0x03
SIMPLE_CMD_FINISH_STATUS = 0x04

# 传输状态码
TRANSFER_SUCCESS = 0x01
TRANSFER_MISSING_BLOCKS = 0x02
TRANSFER_ABORTED = 0x03
TRANSFER_CRC_ERROR = 0x04