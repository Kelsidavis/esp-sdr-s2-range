/* SPDX-License-Identifier: GPL-3.0-or-later
 * Bounded waveform for a shielded golden-ratio-frequency reception test.
 * Nominal RF is 2294 MHz LO + 4.264784 MHz complex baseband.
 * The board's crystal and PLL accuracy are not calibrated by this generator.
 */
#pragma once
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#define TARGET_TONE_HZ 2298264784u
#define TARGET_TONE_LO_MHZ 2294u
#define TARGET_TONE_WORDS 12000u
#define TARGET_TONE_FS 40000000u
static size_t target_tone_waveform(uint32_t *out,size_t capacity) {
    if(!out || capacity<TARGET_TONE_WORDS)return 0;
    const double offset=TARGET_TONE_HZ-TARGET_TONE_LO_MHZ*1000000u;
    for(unsigned j=0;j<TARGET_TONE_WORDS;j++) {
        unsigned distance=j<TARGET_TONE_WORDS-1-j?j:TARGET_TONE_WORDS-1-j;
        double envelope=distance<128?.5-.5*cos(3.141592653589793*distance/128):1;
        double angle=2*3.141592653589793*offset*j/TARGET_TONE_FS;
        int i=(int)lrint(32*envelope*cos(angle)),q=(int)lrint(32*envelope*sin(angle));
        out[j]=((uint32_t)i&1023u)|(((uint32_t)q&1023u)<<10);
    }
    return TARGET_TONE_WORDS;
}
