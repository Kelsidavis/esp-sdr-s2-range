#pragma once

/* The S2 channel calibration holds a capacitor code for the Wi-Fi channel.
 * Its ROM offset helper changes the SDM word without finding a new code.
 * Search the nine-bit VCO capacitor bank, using RFPLL's voltage-window
 * indication, and hold the middle of the widest usable interval. This is
 * bounded (~11 ms plus I2C overhead); a failed search restores all fields. */
/* Diagnostics from the most recent search, reported by PLL?. Flag counts
 * tally reg-12 bits 0x04 and 0x08 across all 512 codes, showing which side
 * of the VCO range the requested frequency falls outside of. */
static struct {
    unsigned searched,ok,best,cap,first,last,good,flag4,flag8,status;
} s2_pll_diag;
static bool s2_pll_calibrate(void) {
    unsigned mode=rom_chip_i2c_readReg(0x62,1,11);
    unsigned control=rom_chip_i2c_readReg(0x62,1,0);
    unsigned low=rom_chip_i2c_readReg(0x62,1,1);
    unsigned high=rom_chip_i2c_readReg(0x62,1,2);
    rom_chip_i2c_writeReg(0x62,1,11,mode|0x40u);
    rom_chip_i2c_writeReg(0x62,1,0,control|0x80u);
    unsigned run=0,best=0,end=0;
    s2_pll_diag.searched=1;s2_pll_diag.first=512;s2_pll_diag.last=0;
    s2_pll_diag.good=s2_pll_diag.flag4=s2_pll_diag.flag8=0;
    for(unsigned cap=0;cap<512;cap++) {
        rom_chip_i2c_writeReg(0x62,1,1,cap&255u);
        rom_chip_i2c_writeReg(0x62,1,2,(high&~0x10u)|((cap>>4)&0x10u));
        esp_rom_delay_us(20);
        unsigned flags=rom_chip_i2c_readReg(0x62,1,12)&0x0cu;
        s2_pll_diag.flag4+=!!(flags&4u);s2_pll_diag.flag8+=!!(flags&8u);
        if(!flags) {
            s2_pll_diag.good++;
            if(cap<s2_pll_diag.first)s2_pll_diag.first=cap;
            s2_pll_diag.last=cap;
            if(++run>best){best=run;end=cap;}
        } else run=0;
    }
    s2_pll_diag.best=best;s2_pll_diag.ok=best!=0;
    if(best) {
        unsigned cap=end-(best-1)/2;
        rom_chip_i2c_writeReg(0x62,1,1,cap&255u);
        rom_chip_i2c_writeReg(0x62,1,2,(high&~0x10u)|((cap>>4)&0x10u));
        esp_rom_delay_us(20);
        s2_pll_diag.cap=cap;
        s2_pll_diag.status=rom_chip_i2c_readReg(0x62,1,12);
        return true;
    }
    rom_chip_i2c_writeReg(0x62,1,1,low);
    rom_chip_i2c_writeReg(0x62,1,2,high);
    rom_chip_i2c_writeReg(0x62,1,0,control);
    rom_chip_i2c_writeReg(0x62,1,11,mode);
    s2_pll_diag.cap=0;s2_pll_diag.status=rom_chip_i2c_readReg(0x62,1,12);
    return false;
}
