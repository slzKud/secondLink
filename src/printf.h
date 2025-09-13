#ifndef __PRINTFH__
#define __PRINTFH__
int myPrintf(const char *fmt, ...);
#ifdef DEBUG
#define PRINT myPrintf
#endif
#define printf myPrintf
#endif