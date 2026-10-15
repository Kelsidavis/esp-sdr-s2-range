#pragma once
#include <stdbool.h>
#include <stdint.h>
void feather_tft_init(void);
/* Natural FFT bin order; display applies fftshift. */
void feather_tft_draw(const uint8_t *bins, unsigned n, unsigned mhz, unsigned span_mhz);
/* 1: next channel, 2+: next span. Debounced on release. */
unsigned feather_tft_button(void);
bool feather_tft_command(const char *line);
