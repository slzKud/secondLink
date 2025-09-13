#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include "CH58x_common.h"

int myPrintf(const char *fmt, ...)
{
    va_list arg;
    va_start(arg, fmt);
    int len = vsnprintf(NULL, 0, fmt, arg);
    uint8_t *data = (uint8_t *) malloc(len);
    vsprintf((char *) data, fmt, arg);
    UART1_SendString(data, len); // 修改为你的串口发送函数
    free(data);
    va_end(arg);
    data = NULL;
    return 0;
}