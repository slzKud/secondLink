#ifndef __SIMPLE_HID_H__
#define __SIMPLE_HID_H__
#define SUCCESS 0
#define FAILED 1

#define PARSE_STATUS_SUCCESS 0x00
#define PARSE_STATUS_FAILED 0x01
#define PARSE_STATUS_CHECKSUM_ERROR 0x02
#define PARSE_STATUS_PACKET_FORMAT_ERROR 0x03
#define PARSE_STATUS_INVALID_COMMAND 0x04
#define PARSE_STATUS_PACKET_DATA_LEN_INVALID 0x05

#define MAGIC_CODE_1 'D'
#define MAGIC_CODE_2 'G'
#define MAGIC_CODE_LENGTH 2

#define COMMAND_MCU_VER 0x0
#define COMMAND_PORT_INFO 0x1
#define COMMAND_MCU_OPT 0x2
#define COMMAND_SEND_DATA 0x3
#define COMMAND_RECV_DATA 0x4

#define MCU_OPT_COMMAND_GPIO_LEVEL 0x01
#define MCU_OPT_GPIO_SET_DIRECTION 0x02

#define MCU_GPIO_WRITE 0x1
#define MCU_GPIO_READ 0x0
#define MCU_GPIO_OUTPUT 0x0
#define MCU_GPIO_INPUT 0x1
#define MCU_GPIO_HIGH 0x1
#define MCU_GPIO_LOW 0x0

#define MCU_OPT_GPIO_SUCCESS 0x0
#define MCU_OPT_GPIO_FAILED 0x1
#define MCU_OPT_GPIO_NUMBER_INVALID 0x2

#define ERROR_RESP 0xFF

void print_hex(const char* label, const uint8_t* data, size_t length);
uint8_t make_checksum(uint8_t *data,uint8_t data_length);
int verify_checksum(uint8_t *data,uint8_t data_length);

uint8_t make_mcu_ver_req(uint8_t **req_data);
uint8_t make_send_data_req(int port_number,uint8_t *recv_data,uint8_t recv_data_length,uint8_t **req_data);
uint8_t make_mcu_opt_gpio_req(int opt,int gpio_number,int gpio_direction,int gpio_level,uint8_t **req_data);

uint8_t make_mcu_ver_resp(int major,int minor,uint8_t **req_data);
uint8_t make_simple_code_resp(uint8_t req_code,uint8_t simple_code,uint8_t **req_data);
uint8_t make_recv_data_resp(int port_number,uint8_t *recv_data,uint8_t recv_data_length,uint8_t **req_data);
uint8_t make_error_resp(int error_code,uint8_t **req_data);
uint8_t make_port_info_resp(int port_number,int connection,uint8_t **req_data);
uint8_t make_mcu_opt_gpio_resp(int status,int gpio_number,int gpio_direction,uint8_t **req_data);

int parse_data(uint8_t *data,uint8_t data_length,int port_number,uint8_t **resp_data,uint8_t *resp_data_length);

int handle_mcu_ver(uint8_t *data,uint8_t data_length,int port_number,uint8_t **resp_data,uint8_t *resp_data_length);
int handle_port_info(uint8_t *data,uint8_t data_length,int port_number,uint8_t **resp_data,uint8_t *resp_data_length);
int handle_mcu_opt_gpio_level(uint8_t *data,uint8_t data_length,int port_number,uint8_t **resp_data,uint8_t *resp_data_length);
int handle_mcu_opt_gpio_set_direction(uint8_t *data,uint8_t data_length,int port_number,uint8_t **resp_data,uint8_t *resp_data_length);
int handle_mcu_opt(uint8_t *data,uint8_t data_length,int port_number,uint8_t **resp_data,uint8_t *resp_data_length);
int handle_send_data(uint8_t *data,uint8_t data_length,int port_number,uint8_t **resp_data,uint8_t *resp_data_length);
#endif