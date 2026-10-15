#include <stdio.h>
#include <stdlib.h>
#include <complex.h>
#include <math.h>
#include "target_tone.h"
int main(void) {
    uint32_t *bank=calloc(TARGET_TONE_WORDS+2,sizeof(*bank));
    if(!bank)return 1;
    bank[TARGET_TONE_WORDS]=0x12345678;
    if(target_tone_waveform(bank,TARGET_TONE_WORDS-1)!=0 || bank[0]!=0)return 2;
    if(target_tone_waveform(bank,TARGET_TONE_WORDS)!=TARGET_TONE_WORDS)return 3;
    if(bank[TARGET_TONE_WORDS]!=0x12345678 || bank[0] || bank[TARGET_TONE_WORDS-1])return 4;
    double complex correlation=0,mirror=0;
    double energy=0;
    const double offset=TARGET_TONE_HZ-TARGET_TONE_LO_MHZ*1000000u;
    for(unsigned j=128;j<TARGET_TONE_WORDS-128;j++) {
        int i=(int32_t)(bank[j]<<22)>>22,q=(int32_t)(bank[j]<<12)>>22;
        if(abs(i)>32 || abs(q)>32 || (bank[j]>>20))return 5;
        double complex x=i+I*q;
        double angle=2*3.141592653589793*offset*j/TARGET_TONE_FS;
        correlation+=x*cexp(-I*angle);mirror+=x*cexp(I*angle);energy+=creal(x*conj(x));
    }
    double n=TARGET_TONE_WORDS-256;
    double coherence=pow(cabs(correlation),2)/(n*energy);
    double mirror_db=20*log10(cabs(mirror)/cabs(correlation));
    printf("Nominal RF: %u Hz; duration %.1f us; coherent fraction %.6f; opposite-frequency response %.1f dB\n",
        TARGET_TONE_HZ,TARGET_TONE_WORDS*1e6/TARGET_TONE_FS,coherence,mirror_db);
    free(bank);
    if(coherence<.999 || mirror_db>-40)return 6;
    puts("PASS: waveform bounds, ramp endpoints, sample packing, frequency and sideband checks. No RF transmitted.");
    return 0;
}
