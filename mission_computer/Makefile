# Host build for the dual-core Flight Sequencer reference implementation.
#
#   make            build ./flight_seq
#   make run        build then run (3 s default; use `make run ARGS=5`)
#   make clean      remove build artefacts
#
# MSYS2/mingw32-make on Windows and make on Linux both work; pthreads need
# -pthread (mingw via the MSYS2 runtime, Linux via glibc).
#
# Manual equivalent:
#   gcc -std=c11 -O2 -Iinclude -Iconfig \
#       src/main.c src/modules/flight_sequencer.c platform/host_bsp.c \
#       -o flight_seq -pthread

CC       ?= gcc
CFLAGS   ?= -std=c11 -O2 -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion
CPPFLAGS := -Iinclude -Iconfig
LDLIBS   := -pthread
ARGS     ?=

SRCS := src/main.c src/modules/flight_sequencer.c platform/host_bsp.c
HDRS := include/types.h include/mailbox.h include/bsp_api.h \
        include/flight_sequencer.h config/simulation.h

ifeq ($(OS),Windows_NT)
TARGET := flight_seq.exe
DEL    := cmd //c del //Q
else
TARGET := flight_seq
DEL    := rm -f
endif

.PHONY: all run clean

all: $(TARGET)

$(TARGET): $(SRCS) $(HDRS)
	$(CC) $(CFLAGS) $(CPPFLAGS) $(SRCS) -o $@ $(LDLIBS)

run: $(TARGET)
	./$(TARGET) $(ARGS)

clean:
	-$(DEL) $(TARGET)
