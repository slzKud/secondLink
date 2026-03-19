import array
import binascii

def is_all_less_than_255(arr):
    return all(isinstance(x, (int)) and 0 <= x <= 255 for x in arr)

def make_file_info(file_size, block_size, file_name, file_crc, segment_index=0, total_segments=1):
    k = [0x0]
    # 2:FILE_SIZE
    if file_size > 0xFFFF:
        return False, b''
    k += [(file_size & 0xff00) >> 8]
    k += [(file_size & 0xff)]
    # 2:FILE_BLOCK_NUMBER
    block_number = int(file_size / block_size)
    if (file_size - int(file_size / block_size) * block_size) > 0:
        block_number += 1
    if block_number > 0xFFFF:
        return False, b''
    k += [(block_number & 0xff00) >> 8]
    k += [(block_number & 0xff)]
    # [FILE_NAME:45]
    file_name_bytes = str(file_name).encode().ljust(45, b'\x00')
    if len(file_name_bytes) > 45:
        return False, b''
    k += array.array('B', file_name_bytes).tolist()
    # [FILE_CRC32:4]
    if file_crc > 0xFFFFFFFF:
        return False, b''
    k += [(file_crc & 0xff000000) >> 24]
    k += [(file_crc & 0x00ff0000) >> 16]
    k += [(file_crc & 0xff00) >> 8]
    k += [(file_crc & 0xff)]
    # [SEGMENT_INDEX:2]
    k += [(segment_index >> 8) & 0xFF]
    k += [segment_index & 0xFF]
    # [TOTAL_SEGMENTS:2]
    k += [(total_segments >> 8) & 0xFF]
    k += [total_segments & 0xFF]
    return True, bytes(k)

def make_start_transfer(ret, transfer_id):
    k = [0x1, ret, transfer_id]
    return True, bytes(k)

def make_transfer_data(transfer_id, block_id, data):
    if transfer_id > 0xFF:
        return False, b''
    if block_id > 0xFFFF:
        return False, b''
    if len(data) > 54:
        return False, b''
    if not is_all_less_than_255(data):
        return False, b''
    k = [0x2, transfer_id, (block_id & 0xff00) >> 8, (block_id & 0xff)] + data
    return True, bytes(k)

def make_finish(transfer_id=0x0):
    return True, bytes([0x3, transfer_id])

def make_finish_status(ret, transfer_id, retry_block_ids=[]):
    if ret > 0x3:
        return False, b''
    if len(retry_block_ids) == 0:
        return True, bytes([0x4, transfer_id, ret])
    if len(retry_block_ids) > 28:
        return False, b''
    if not is_all_less_than_255(retry_block_ids):
        return False, b''
    k = [0x4, transfer_id, ret, len(retry_block_ids)] + retry_block_ids
    return True, bytes(k)

def split_list(my_list, n):
    return [my_list[i:i + n] for i in range(0, len(my_list), n)]

class SimpleSendData:
    def __init__(self, data, filename="block_data", segment_index=0, total_segments=1):
        self.data = data
        self.filename = filename
        self.transfer_id = 0
        self.block_size = 54
        self.segment_index = segment_index
        self.total_segments = total_segments

    def calc_crc(self):
        return binascii.crc32(bytes(self.data))

    def make_file_info(self):
        return make_file_info(len(self.data), self.block_size, self.filename, self.calc_crc(),
                              self.segment_index, self.total_segments)

    def set_transfer_id(self, transfer_id):
        self.transfer_id = transfer_id
        return True

    def make_transfer_datas(self):
        data_lists = split_list(self.data, self.block_size)
        transfer_data_lists = []
        i = 0
        for datas in data_lists:
            ret, block_data = make_transfer_data(self.transfer_id, i, datas)
            if ret:
                transfer_data_lists.append(block_data)
            i += 1
        return True, transfer_data_lists

    def make_finish(self):
        return make_finish(self.transfer_id)


class SimpleRecvData:
    def __init__(self):
        self.data = []
        self.filename = ""
        self.transfer_id = 0
        self.block_counts = 0
        self.data_size = 0
        self.file_crc = 0
        self.block_list = []
        self.block_size = 0
        self.file_info_parsed = False
        self.segment_index = 0
        self.total_segments = 1

    def calc_crc(self):
        return binascii.crc32(bytes(self.data))

    def parse_file_info(self, data):
        if len(data) < 58:
            return False
        if data[0] != 0x0:
            return False
        self.data_size = (data[1] << 8) | data[2]
        self.block_counts = (data[3] << 8) | data[4]
        file_name_bytes = data[5:50]
        self.filename = bytes(file_name_bytes).rstrip(b'\x00').decode('utf-8')
        self.file_crc = (data[50] << 24) | (data[51] << 16) | (data[52] << 8) | data[53]
        self.segment_index = (data[54] << 8) | data[55]
        self.total_segments = (data[56] << 8) | data[57]
        self.data = [0x0] * self.data_size
        self.block_list = []

        # 计算块大小
        if self.block_counts > 0:
            self.block_size = self.data_size // self.block_counts
            if self.data_size % self.block_counts != 0:
                self.block_size += 1
        else:
            self.block_size = 0

        self.file_info_parsed = True
        return True

    def make_start_transfer(self, ret):
        return make_start_transfer(ret, self.transfer_id)

    def set_transfer_id(self, transfer_id):
        self.transfer_id = transfer_id
        return True

    def recv_data(self, data):
        if len(data) < 5:
            return False
        if data[0] != 0x2:
            return False
        transfer_id = data[1]
        block_number = (data[2] << 8) | data[3]
        recv_datas = data[4:]

        if self.transfer_id != transfer_id:
            return False

        # 确保block_size已计算
        if self.block_size <= 0:
            # 如果block_size还未计算，根据当前接收的数据估算
            if self.block_counts > 0:
                self.block_size = self.data_size // self.block_counts
                if self.data_size % self.block_counts != 0:
                    self.block_size += 1
            else:
                # 如果还没有文件信息，暂时使用接收数据的长度作为块大小
                self.block_size = len(recv_datas)

        # 计算数据在self.data中的起始位置
        start_pos = block_number * self.block_size
        end_pos = start_pos + len(recv_datas)

        # 确保不超出数据范围
        if end_pos > len(self.data):
            end_pos = len(self.data)
            recv_datas = recv_datas[:end_pos - start_pos]

        # 将接收到的数据插入到对应位置
        for i in range(len(recv_datas)):
            if start_pos + i < len(self.data):
                self.data[start_pos + i] = recv_datas[i]

        # 记录已接收的块号
        if block_number not in self.block_list:
            self.block_list.append(block_number)

        return True

    def finish(self):
        segment_done_info = (self.segment_index, self.total_segments,
                             self.segment_index >= self.total_segments - 1)
        if len(self.block_list) < self.block_counts:
            missing_blocks = []
            for i in range(self.block_counts):
                if i not in self.block_list:
                    missing_blocks.append(i)
            print(f"接收未完成，缺失的块号: {missing_blocks}")
            return True, make_finish_status(0x2, self.transfer_id, missing_blocks)[1], segment_done_info
        if self.calc_crc() != self.file_crc:
            return True, make_finish_status(0x4, self.transfer_id)[1], segment_done_info
        return True, make_finish_status(0x1, self.transfer_id)[1], segment_done_info

    def abort_transfer(self):
        return True, make_finish_status(0x3, self.transfer_id)[1]


class MultiSegmentCollector:
    def __init__(self, total_segments, filename):
        self.total_segments = total_segments
        self.filename = filename
        self.segments = {}          # {segment_index: bytes}
        self.segment_crcs = {}      # {segment_index: crc32}

    def add_segment(self, index, data, crc):
        self.segments[index] = bytes(data)
        self.segment_crcs[index] = crc

    def is_complete(self):
        return len(self.segments) >= self.total_segments

    def merge(self):
        result = b''
        for i in range(self.total_segments):
            result += self.segments[i]
        return result


if __name__ == "__main__":
    import random
    import string

    def generate_random_string(length):
        """生成指定长度的随机字符串。"""
        characters = string.ascii_letters + string.digits
        random_string = ''.join(random.choices(characters, k=length))
        return random_string

    random_size = 1024
    random_data = generate_random_string(random_size)
    print(f"random_str:{random_data}")

    send_data = SimpleSendData(list(random_data.encode()))
    send_data.set_transfer_id(0x12)
    ret, start_data = send_data.make_file_info()
    ret, send_data_list = send_data.make_transfer_datas()
    ret, finish_data = send_data.make_finish()
    print(f"文件信息: {start_data.hex()}")
    print(f"数据块数量: {len(send_data_list)}")
    print(f"结束包: {finish_data.hex()}")

    recv_data = SimpleRecvData()
    recv_data.set_transfer_id(0x12)
    
    # 解析文件信息
    if recv_data.parse_file_info(list(start_data)):
        print("解析文件信息成功")
        print(f"文件名: {recv_data.filename}")
        print(f"文件大小: {recv_data.data_size}")
        print(f"块数量: {recv_data.block_counts}")
        print(f"块大小: {recv_data.block_size}")
        print(f"CRC: 0x{recv_data.file_crc:08X}")
        
        # 接收数据块
        for i, send_data_item in enumerate(send_data_list):
            result = recv_data.recv_data(list(send_data_item))
            print(f"接收数据块 {i}: {result}")
            
        # 完成接收
        ret, finish_data_recv, seg_info = recv_data.finish()
        print(f"接收完成状态: {finish_data_recv.hex()}")
        print(f"分段信息: segment_index={seg_info[0]}, total_segments={seg_info[1]}, is_last={seg_info[2]}")
        
        # 验证数据
        recv_str = bytes(recv_data.data).decode()
        print(f"接收数据长度: {len(recv_str)}")
        if recv_str == random_data:
            print("数据验证成功: OK")
        else:
            print("数据验证失败")
            # 打印前100个字符对比
            print(f"原始: {random_data[:100]}")
            print(f"接收: {recv_str[:100]}")
    else:
        print("解析文件信息失败")