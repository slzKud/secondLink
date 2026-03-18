#include "../printf.h"
#include <unistd.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

#include "simple_hid.h"

#include "CH58x_common.h"

uint8_t *recv_data_buffer = NULL;

uint8_t gpio_sim_level[2] = {0x0, 0x0};
uint8_t gpio_sim_direction[2] = {0x0, 0x0};

void print_hex(const char *label, const uint8_t *data, size_t length)
{
    printf("%s: ", label);
    for (size_t i = 0; i < length; i++)
    {
        printf("%02X ", data[i]);
    }
    printf("\n");
}

uint8_t make_checksum(uint8_t *data, uint8_t data_length)
{ // 这里的data_length不包含checksum
    int i = 0;
    uint8_t n = 0;
    for (i = 0; i < data_length; i++)
    {
        n += *(data + i);
        // //printf("plus:%x,%x\n",*(data+i),n);
    }
    // //printf("checksum:%x,%x\n",n,(n & 0xff));
    return (n & 0xff);
}
int verify_checksum(uint8_t *data, uint8_t data_length)
{ // 这里的data_length包含checksum
    uint8_t ori_checksum = *(data + (data_length - 1));
    uint8_t new_checksum = make_checksum(data, data_length - 1);
    if (ori_checksum == new_checksum)
        return SUCCESS;
    return FAILED;
}
uint8_t *make_header()
{
    uint8_t *req = NULL;
    req = malloc(sizeof(uint8_t) * 64);
    memset(req, 0, 64);
    *(req) = MAGIC_CODE_1;
    *(req + 1) = MAGIC_CODE_2;
    return req;
}
uint8_t make_mcu_ver_req(uint8_t **req_data)
{
    uint8_t *req = make_header();
    uint8_t *data = (req + MAGIC_CODE_LENGTH);
    uint8_t checksum = 0;
    *(data) = COMMAND_MCU_VER;
    *(data + 1) = 0x0;                        // 长度为0
    checksum = make_checksum(req, 2 + 1 + 1); // 2个魔法字，1个命令类型，1个长度
    *(data + 2) = checksum;
    *req_data = req;
    return 2 + 1 + 1 + 1;
}

uint8_t make_mcu_ver_resp(int major, int minor, uint8_t **req_data)
{
    uint8_t *req = make_header();
    uint8_t *data = (req + MAGIC_CODE_LENGTH);
    uint8_t checksum = 0;
    *(data) = COMMAND_MCU_VER | 0x20;
    *(data + 1) = 0x2;                            // 长度为2
    *(data + 2) = major;                          // 长度为0
    *(data + 3) = minor;                          // 长度为0
    checksum = make_checksum(req, 2 + 1 + 1 + 2); // 2个魔法字，1个命令类型，1个长度，2个数据
    *(data + 4) = checksum;
    *req_data = req;
    return 2 + 1 + 1 + 2 + 1;
}
uint8_t make_send_data_req(int port_number, uint8_t *recv_data, uint8_t recv_data_length, uint8_t **req_data)
{
    int resp_data_len = MAGIC_CODE_LENGTH;
    uint8_t *resp = make_header();
    uint8_t *data = (resp + MAGIC_CODE_LENGTH);
    uint8_t checksum = 0;
    *(data) = COMMAND_SEND_DATA;
    *(data + 1) = recv_data_length + 1; // 长度为N+1
    *(data + 2) = port_number;
    memcpy(data + 3, recv_data, recv_data_length);
    resp_data_len += (recv_data_length + 1 + 1 + 1);
    checksum = make_checksum(resp, resp_data_len);
    *(data + 3 + recv_data_length) = checksum;
    resp_data_len += 1;
    *req_data = resp;
    return resp_data_len;
}
uint8_t make_simple_code_resp(uint8_t req_code, uint8_t simple_code, uint8_t **req_data)
{
    uint8_t *req = make_header();
    uint8_t *data = (req + MAGIC_CODE_LENGTH);
    uint8_t checksum = 0;
    *(data) = req_code | 0x20;
    *(data + 1) = 0x1; // 长度为1
    *(data + 2) = simple_code;
    checksum = make_checksum(req, 2 + 1 + 1 + 1); // 2个魔法字，1个命令类型，1个长度,1个数据
    *(data + 3) = checksum;
    *req_data = req;
    return 2 + 1 + 1 + 1 + 1;
}
uint8_t make_recv_data_resp(int port_number, uint8_t *recv_data, uint8_t recv_data_length, uint8_t **req_data)
{
    int resp_data_len = MAGIC_CODE_LENGTH;
    uint8_t *resp = make_header();
    uint8_t *data = (resp + MAGIC_CODE_LENGTH);
    uint8_t checksum = 0;
    *(data) = COMMAND_RECV_DATA;
    *(data + 1) = recv_data_length + 1; // 长度为N+1
    *(data + 2) = port_number;
    memcpy(data + 3, recv_data, recv_data_length);
    resp_data_len += (recv_data_length + 1 + 1 + 1);
    checksum = make_checksum(resp, resp_data_len);
    *(data + 3 + recv_data_length) = checksum;
    resp_data_len += 1;
    *req_data = resp;
    return resp_data_len;
}
uint8_t make_error_resp(int error_code, uint8_t **req_data)
{
    uint8_t *req = make_header();
    uint8_t *data = (req + MAGIC_CODE_LENGTH);
    uint8_t checksum = 0;
    *(data) = ERROR_RESP;
    *(data + 1) = 0x1;                            // 长度为1
    *(data + 2) = error_code;                     // 错误码
    checksum = make_checksum(req, 2 + 1 + 1 + 1); // 2个魔法字，1个命令类型，1个长度，1个数据
    *(data + 3) = checksum;
    *req_data = req;
    return 2 + 1 + 1 + 1 + 1;
}

uint8_t make_port_info_resp(int port_number, int connection, uint8_t **req_data)
{
    uint8_t *req = make_header();
    uint8_t *data = (req + MAGIC_CODE_LENGTH);
    uint8_t checksum = 0;
    *(data) = COMMAND_PORT_INFO | 0x20;
    *(data + 1) = 0x4; // 长度为4
    *(data + 2) = port_number;
    *(data + 3) = connection;
    *(data + 4) = 0;
    *(data + 5) = 0;
    checksum = make_checksum(req, 2 + 1 + 1 + 4); // 2个魔法字，1个命令类型，1个长度,4个数据
    *(data + 6) = checksum;
    *req_data = req;
    return 2 + 1 + 1 + 4 + 1;
}

uint8_t make_mcu_opt_gpio_req(int opt, int gpio_number, int gpio_direction, int gpio_level, uint8_t **req_data)
{
    //printf("make_mcu_opt_gpio_req:opt=%d,gpio_number=%d,gpio_direction=%d,gpio_level=%d\n", opt, gpio_number, gpio_direction, gpio_level);
    uint8_t mcu_opt_gpio_req_array[4] = {0, 0, 0, 0};
    int mcu_opt_gpio_req_array_len = 4;
    mcu_opt_gpio_req_array[0] = opt;
    mcu_opt_gpio_req_array[1] = gpio_number;
    if (opt == MCU_OPT_COMMAND_GPIO_LEVEL)
    {
        mcu_opt_gpio_req_array[2] = gpio_direction;
        if (gpio_direction == MCU_GPIO_WRITE)
            mcu_opt_gpio_req_array[3] = gpio_level;
        mcu_opt_gpio_req_array_len = (gpio_direction == MCU_GPIO_WRITE) ? 4 : 3;
    }
    else if (opt == MCU_OPT_GPIO_SET_DIRECTION)
    {
        mcu_opt_gpio_req_array[2] = gpio_direction;
        mcu_opt_gpio_req_array_len = 3;
    }
    //print_hex("make_mcu_opt_gpio_req:", mcu_opt_gpio_req_array, mcu_opt_gpio_req_array_len);
    uint8_t *req = make_header();
    uint8_t *data = (req + MAGIC_CODE_LENGTH);
    uint8_t checksum = 0;
    uint8_t resp_data_len = 4;
    *(data) = COMMAND_MCU_OPT;
    *(data + 1) = mcu_opt_gpio_req_array_len; // 长度为N+1
    memcpy(data + 2, mcu_opt_gpio_req_array, mcu_opt_gpio_req_array_len);
    resp_data_len += (mcu_opt_gpio_req_array_len);
    checksum = make_checksum(req, resp_data_len);
    *(data + 2 + mcu_opt_gpio_req_array_len) = checksum;
    resp_data_len += 1;
    *req_data = req;
    return resp_data_len;
}
uint8_t make_mcu_opt_gpio_resp(int status, int gpio_number, int gpio_direction, uint8_t **req_data)
{
    uint8_t *req = make_header();
    uint8_t *data = (req + MAGIC_CODE_LENGTH);
    uint8_t checksum = 0;
    *(data) = COMMAND_MCU_OPT | 0x20;
    *(data + 1) = 0x3; // 长度为3
    *(data + 2) = status;
    *(data + 3) = gpio_number;
    *(data + 4) = gpio_direction;
    checksum = make_checksum(req, 2 + 1 + 1 + 3); // 2个魔法字，1个命令类型，1个长度,3个数据
    *(data + 5) = checksum;
    *req_data = req;
    return 2 + 1 + 1 + 3 + 1;
}
int handle_mcu_ver(uint8_t *data, uint8_t data_length, int port_number, uint8_t **resp_data, uint8_t *resp_data_length)
{
    uint8_t data_len = make_mcu_ver_resp(1, 2, resp_data);
    *resp_data_length = data_len;
    return PARSE_STATUS_SUCCESS;
}

int handle_port_info(uint8_t *data, uint8_t data_length, int port_number, uint8_t **resp_data, uint8_t *resp_data_length)
{
    int query_port_number = port_number;
    if (data_length >= 1)
        query_port_number = *(data);
    if (query_port_number > 1)
        return PARSE_STATUS_FAILED;
    //printf("handle_port_info:port %d\n", query_port_number);
    uint8_t data_len = 0;
    if (query_port_number == 0)
    {
        data_len = make_port_info_resp(0, 0, resp_data);
    }
    else
    {
        data_len = make_port_info_resp(1, 1, resp_data);
    }
    *resp_data_length = data_len;
    return PARSE_STATUS_SUCCESS;
}
int handle_mcu_opt_gpio_level(uint8_t *data, uint8_t data_length, int port_number, uint8_t **resp_data, uint8_t *resp_data_length)
{
    //printf("handle_mcu_opt_gpio_level:data_length:%d\n", data_length);
    //print_hex("handle_mcu_opt_gpio_level:data", data, data_length);
    if (data_length < 3)
        return PARSE_STATUS_PACKET_DATA_LEN_INVALID;
    uint8_t gpio_number = *(data + 1);
    uint8_t gpio_rw_flag = *(data + 2);
    uint8_t gpio_level = 0;
    uint8_t data_len = 0;
    //printf("handle_mcu_opt_gpio_level:gpio_number:%d\n", gpio_number);
    //printf("handle_mcu_opt_gpio_level:gpio_rw_flag:%d\n", gpio_rw_flag);
    if (gpio_number >= sizeof(gpio_sim_direction))
    {
        data_len = make_mcu_opt_gpio_resp(MCU_OPT_GPIO_NUMBER_INVALID, gpio_number, 0, resp_data);
        goto final;
    }
    if (gpio_rw_flag == MCU_GPIO_WRITE)
    {
        if (data_length < 4)
            return PARSE_STATUS_PACKET_DATA_LEN_INVALID;
        gpio_level = *(data + 3);
        if (gpio_level != MCU_GPIO_HIGH && gpio_level != MCU_GPIO_LOW)
        {
            data_len = make_mcu_opt_gpio_resp(MCU_OPT_GPIO_FAILED, gpio_number, gpio_level, resp_data);
            goto final;
        }
        gpio_sim_level[gpio_number] = gpio_level;
    }
    else if (gpio_rw_flag == MCU_GPIO_READ)
    {
        // todo
    }
    data_len = make_mcu_opt_gpio_resp(MCU_OPT_GPIO_SUCCESS, gpio_number, gpio_sim_level[gpio_number], resp_data);
final:
    *resp_data_length = data_len;
    return PARSE_STATUS_SUCCESS;
}
int handle_mcu_opt_gpio_set_direction(uint8_t *data, uint8_t data_length, int port_number, uint8_t **resp_data, uint8_t *resp_data_length)
{
    if (data_length < 2)
        return PARSE_STATUS_PACKET_DATA_LEN_INVALID;
    uint8_t gpio_number = *(data + 1);
    uint8_t gpio_direction = *(data + 2);
    uint8_t data_len = 0;
    if (gpio_number >= sizeof(gpio_sim_direction))
    {
        data_len = make_mcu_opt_gpio_resp(MCU_OPT_GPIO_NUMBER_INVALID, gpio_number, 0, resp_data);
        goto final;
    }
    if (gpio_direction != MCU_GPIO_INPUT && gpio_direction != MCU_GPIO_OUTPUT)
    {
        data_len = make_mcu_opt_gpio_resp(MCU_OPT_GPIO_FAILED, gpio_number, gpio_direction, resp_data);
        goto final;
    }
    gpio_sim_direction[gpio_number] = gpio_direction;
    data_len = make_mcu_opt_gpio_resp(MCU_OPT_GPIO_SUCCESS, gpio_number, gpio_sim_direction[gpio_number], resp_data);
final:
    *resp_data_length = data_len;
    return PARSE_STATUS_SUCCESS;
}
int handle_mcu_opt(uint8_t *data, uint8_t data_length, int port_number, uint8_t **resp_data, uint8_t *resp_data_length)
{
    //printf("handle_mcu_opt:data_length:%d\n", data_length);
    if (data_length < 1)
        return PARSE_STATUS_PACKET_DATA_LEN_INVALID;
    uint8_t mcu_opt_command = *(data);
    if (mcu_opt_command == MCU_OPT_COMMAND_GPIO_LEVEL)
    {
        return handle_mcu_opt_gpio_level(data, data_length, port_number, resp_data, resp_data_length);
    }
    if (mcu_opt_command == MCU_OPT_GPIO_SET_DIRECTION)
    {
        return handle_mcu_opt_gpio_set_direction(data, data_length, port_number, resp_data, resp_data_length);
    }
    return PARSE_STATUS_INVALID_COMMAND;
}
int handle_send_data(uint8_t *data, uint8_t data_length, int port_number, uint8_t **resp_data, uint8_t *resp_data_length)
{
    uint8_t recv_port_number = *(data);
    //print_hex("handle_send_data:port", data, 1);
    //print_hex("handle_send_data:data", data + 1, data_length - 1);
    uint8_t data_len = make_simple_code_resp(COMMAND_SEND_DATA, 0x1, resp_data);
    *resp_data_length = data_len;
    //printf("already set recv_data\n");
    if(recv_data_buffer != NULL) {
      free(recv_data_buffer);
      recv_data_buffer = NULL;
  }
    uint8_t recv_data_len = make_recv_data_resp(recv_port_number, data + 1, data_length - 1, &recv_data_buffer);
    if(recv_port_number==0){
        memset(pEP1_IN_DataBuf,0,64);
        memcpy(pEP1_IN_DataBuf,recv_data_buffer,recv_data_len);
        free(recv_data_buffer);
        recv_data_buffer=NULL;
        DevEP1_IN_Deal(64);
    }else if(recv_port_number==1){
        memset(pU2EP1_IN_DataBuf,0,64);
        memcpy(pU2EP1_IN_DataBuf,recv_data_buffer,recv_data_len);
        free(recv_data_buffer);
        recv_data_buffer=NULL;
        U2DevEP1_IN_Deal(64);
    }
    return PARSE_STATUS_SUCCESS;
}

int parse_data(uint8_t *data, uint8_t data_length, int port_number, uint8_t **resp_data, uint8_t *resp_data_length)
{
    int ret = PARSE_STATUS_INVALID_COMMAND;
    if (data_length < 5)
    {
        ret = PARSE_STATUS_PACKET_FORMAT_ERROR;
        goto error;
    }
    if (*(data) != MAGIC_CODE_1 || *(data + 1) != MAGIC_CODE_2)
    {
        ret = PARSE_STATUS_PACKET_FORMAT_ERROR;
        goto error;
    }
    uint8_t command_type = *(data + MAGIC_CODE_LENGTH);
    uint8_t command_data_len = *(data + MAGIC_CODE_LENGTH + 1);
    if ((command_data_len + MAGIC_CODE_LENGTH + 1 + 1 + 1) > data_length)
    {
        ret = PARSE_STATUS_PACKET_DATA_LEN_INVALID;
        goto error;
    }
    if (verify_checksum(data, (command_data_len + MAGIC_CODE_LENGTH + 1 + 1 + 1)) == FAILED)
    {
        ret = PARSE_STATUS_CHECKSUM_ERROR;
        goto error;
    }
    uint8_t *command_data = NULL;
    if (command_data_len > 0)
    {
        command_data = malloc(sizeof(uint8_t) * command_data_len);
        memcpy(command_data, data + MAGIC_CODE_LENGTH + 1 + 1, command_data_len);
    }
    if (command_type == COMMAND_MCU_VER)
    {
        ret = handle_mcu_ver(command_data, command_data_len, port_number, resp_data, resp_data_length);
    }
    if (command_type == COMMAND_MCU_OPT)
    {
        ret = handle_mcu_opt(command_data, command_data_len, port_number, resp_data, resp_data_length);
    }
    if (command_type == COMMAND_PORT_INFO)
    {
        ret = handle_port_info(command_data, command_data_len, port_number, resp_data, resp_data_length);
    }
    if (command_type == COMMAND_SEND_DATA)
    {
        ret = handle_send_data(command_data, command_data_len, port_number, resp_data, resp_data_length);
    }
    if (ret == PARSE_STATUS_SUCCESS && resp_data != NULL){
        if(command_data!=NULL)
            free(command_data);
        command_data=NULL;
        return ret;
    }
error:
    *resp_data_length = make_error_resp(ret, resp_data);
    if(command_data!=NULL)
        free(command_data);
    command_data=NULL;
    return ret;
}
