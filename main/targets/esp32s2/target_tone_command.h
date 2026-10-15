/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "target_tone.h"
/* DAC register 0x60033d6c and controls derived from Espressif's S2 dactrig
 * routine; the receiver uses the adjacent ADC 0x60033d64. The DAC buffer
 * stays inside the three reserved 16 KiB capture banks. */
extern void rom_pbus_xpd_tx_on(unsigned);
extern void force_txon(unsigned);
extern void force_tx_gain(unsigned,unsigned,unsigned);
/* This command is opt-in at build time and never runs automatically.
 * Use only with RF containment: the target is outside the Wi-Fi ISM band.
 */
static bool target_tone_command(char *line) {
    if(strcmp(line,"TXTONE") && strncmp(line,"TXTONE ",7))return false;
    unsigned count,period,gain;char extra;
    if(sscanf(line,"TXTONE %u %u %u %c",&count,&period,&gain,&extra)!=3 ||
       count<1 || count>200 || period<5 || period>50 || count*period>5000 || gain>16) {
        reply("ERR txtone_args\n");return true;
    }
    if(TARGET_TONE_WORDS>IQ_WORDS){reply("ERR tx_buffer\n");return true;}
    unsigned saved_frequency=frequency_mhz;
    frequency_mhz=TARGET_TONE_LO_MHZ;rx_ready=false;prepare_rx();
    unsigned words=target_tone_waveform(IQ_BUFFER,IQ_WORDS);
    char text[128];
    snprintf(text,sizeof(text),"TONESTART %u %u %u\n",TARGET_TONE_HZ,words,gain);reply(text);
    unsigned sent=0,last_us=0,failed=0;
    rom_pbus_workmode();rom_pbus_xpd_rx_on(0);rom_pbus_xpd_tx_on(1);
    force_tx_gain(gain,0,0);
    uint32_t owner=REG_READ(SRAM_OWNER_REG),ctrl=0x80000000u|words;
    REG_WRITE(SRAM_OWNER_REG,(owner&~15u)|7u);
    for(unsigned j=0;j<count;j++) {
        force_txon(1);
        int64_t start=esp_timer_get_time();
        REG_WRITE(0x60033d6c,0);REG_WRITE(0x60033d6c,ctrl);
        REG_WRITE(0x60033d6c,ctrl|(1u<<19));REG_WRITE(0x60033d6c,ctrl);
        while(!(REG_READ(0x60033d6c)&(1u<<18)) && esp_timer_get_time()-start<5000){}
        last_us=esp_timer_get_time()-start;
        bool done=(REG_READ(0x60033d6c)&(1u<<18))!=0;
        REG_WRITE(0x60033d6c,0);force_txon(0);
        if(!done){failed++;break;}sent++;
        vTaskDelay(pdMS_TO_TICKS(period));
    }
    REG_WRITE(0x60033d6c,0);REG_WRITE(SRAM_OWNER_REG,owner);
    rom_pbus_xpd_tx_off();frequency_mhz=saved_frequency;rx_ready=false;prepare_rx();
    snprintf(text,sizeof(text),"TONEEND %u %u %u\n",sent,failed,last_us);reply(text);
    return true;
}
