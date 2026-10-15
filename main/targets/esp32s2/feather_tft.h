#pragma once
#include <stdbool.h>
#include <stdint.h>
void feather_tft_init(void);
/* Natural FFT bin order; display applies fftshift. */
/* footer: one status line drawn at the bottom of the screen. */
void feather_tft_draw(const uint8_t *bins, unsigned n, unsigned mhz, unsigned span_mhz, const char *footer);
/* 1: tap (<0.6 s), 2: hold, 3: long hold (>=1.5 s). Debounced on release. */
unsigned feather_tft_button(void);
bool feather_tft_command(const char *line);
