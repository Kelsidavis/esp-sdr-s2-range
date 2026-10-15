/* Standalone display for Adafruit product 5300 (regular S2 TFT Feather).
 * GPL-3.0-or-later. LCD register settings follow the ST7789 datasheet and
 * the board orientation documented by Adafruit. No Arduino runtime needed. */
#include "feather_tft.h"
#include "burst_serial.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_err.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdio.h>
#include <string.h>

#define WIDTH 240
#define HEIGHT 135
#define PIXEL_BYTES (WIDTH * HEIGHT * sizeof(uint16_t))
#define WATER_Y 89
#define FOOT_Y 125
#define WHITE 0xffff
#define CYAN 0x07ff
#define GRID 0x18c3
static spi_device_handle_t lcd;
/* Big-endian RGB565 in external RAM, outside the RF capture aperture. */
static uint16_t *pixels;
static uint8_t level[WIDTH];
static unsigned frames, current_mhz=2412, current_span=40;
static int64_t last_draw;

static void transfer(bool data, const void *bytes, unsigned count) {
    ESP_ERROR_CHECK(gpio_set_level(39,data));
    spi_transaction_t t={.length=count*8,.tx_buffer=bytes};
    ESP_ERROR_CHECK(spi_device_polling_transmit(lcd,&t));
}
static void command(uint8_t cmd, const void *args, unsigned count) {
    transfer(false,&cmd,1);
    if(count)transfer(true,args,count);
}
static uint16_t wire(uint16_t color) {return (color<<8)|(color>>8);}
static void dot(int x,int y,uint16_t color) {
    if(x>=0 && x<WIDTH && y>=0 && y<HEIGHT)pixels[y*WIDTH+x]=wire(color);
}
/* Compact 3x5 glyphs: each row occupies three bits, from top to bottom. */
static unsigned glyph(char c) {
    switch(c) {
    case '0':return 075557;case '1':return 026227;case '2':return 071747;
    case '3':return 071717;case '4':return 055711;case '5':return 074717;
    case '6':return 074757;case '7':return 071111;case '8':return 075757;
    case '9':return 075717;case 'A':return 025755;case 'B':return 065656;
    case 'C':return 074447;case 'D':return 065556;case 'E':return 074647;
    case 'F':return 074644;case 'G':return 074557;case 'H':return 055755;
    case 'I':return 072227;case 'J':return 011157;case 'K':return 055655;
    case 'L':return 044447;case 'M':return 057555;case 'N':return 057755;
    case 'O':return 025552;case 'P':return 075744;case 'Q':return 075573;
    case 'R':return 075765;case 'S':return 074717;case 'T':return 072222;
    case 'U':return 055557;case 'V':return 055552;case 'W':return 055575;
    case 'X':return 055255;case 'Y':return 055222;case 'Z':return 071247;
    case '-':return 000700;case '.':return 000002;case '/':return 011244;
    case ':':return 002020;case '+':return 002720;default:return 0;
    }
}
static void text(int x,int y,const char *s,unsigned scale,uint16_t color) {
    for(;*s;s++,x+=4*scale) {
        unsigned bits=glyph(*s);
        for(int row=0;row<5;row++)for(int col=0;col<3;col++)
            if(bits&(1u<<(14-row*3-col)))
                for(unsigned dy=0;dy<scale;dy++)for(unsigned dx=0;dx<scale;dx++)
                    dot(x+col*scale+dx,y+row*scale+dy,color);
    }
}
static void flush(void) {
    const uint8_t cols[]={0,40,1,23}; /* 40..279 */
    const uint8_t rows[]={0,53,0,187}; /* 53..187 */
    command(0x2a,cols,4);command(0x2b,rows,4);command(0x2c,NULL,0);
    const uint8_t *p=(const uint8_t *)pixels;
    for(unsigned offset=0;offset<PIXEL_BYTES;) {
        unsigned count=PIXEL_BYTES-offset;
        if(count>3840)count=3840;
        transfer(true,p+offset,count);offset+=count;
    }
}
void feather_tft_init(void) {
    pixels=heap_caps_calloc(WIDTH*HEIGHT,sizeof(uint16_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!pixels)ESP_ERROR_CHECK(ESP_ERR_NO_MEM);
    gpio_config_t out={.pin_bit_mask=(1ULL<<21)|(1ULL<<39)|(1ULL<<40)|(1ULL<<45),.mode=GPIO_MODE_OUTPUT};
    ESP_ERROR_CHECK(gpio_config(&out));
    ESP_ERROR_CHECK(gpio_set_level(21,1));
    ESP_ERROR_CHECK(gpio_set_level(45,0));
    ESP_ERROR_CHECK(gpio_set_level(40,0));vTaskDelay(pdMS_TO_TICKS(20));
    ESP_ERROR_CHECK(gpio_set_level(40,1));vTaskDelay(pdMS_TO_TICKS(120));
    const spi_bus_config_t bus={.mosi_io_num=35,.miso_io_num=-1,.sclk_io_num=36,
        .quadwp_io_num=-1,.quadhd_io_num=-1,.max_transfer_sz=3840};
    /* The SPI driver stages each PSRAM block in a small DMA-capable buffer. */
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST,&bus,SPI_DMA_CH_AUTO));
    const spi_device_interface_config_t dev={.clock_speed_hz=40000000,.mode=0,
        .spics_io_num=7,.queue_size=1};
    ESP_ERROR_CHECK(spi_bus_add_device(SPI2_HOST,&dev,&lcd));
    command(0x01,NULL,0);vTaskDelay(pdMS_TO_TICKS(150));
    command(0x11,NULL,0);vTaskDelay(pdMS_TO_TICKS(120));
    uint8_t arg=0x55;command(0x3a,&arg,1);
    arg=0x60;command(0x36,&arg,1); /* Adafruit rotation 3; RGB order */
    command(0x21,NULL,0);command(0x13,NULL,0);command(0x29,NULL,0);
    vTaskDelay(pdMS_TO_TICKS(20));
    text(16,20,"ESP SDR",4,CYAN);
    text(16,54,"FEATHER ESP32 S2",2,WHITE);
    text(16,80,"STARTING RECEIVER",2,WHITE);
    flush();ESP_ERROR_CHECK(gpio_set_level(45,1));
    const gpio_config_t button={.pin_bit_mask=1ULL,.mode=GPIO_MODE_INPUT,.pull_up_en=GPIO_PULLUP_ENABLE};
    ESP_ERROR_CHECK(gpio_config(&button));
}
static uint16_t heat(unsigned v) {
    if(v<64)return (v/2)&31;
    if(v<128)return (((v-64)*63/64)<<5)|31;
    if(v<192)return (((v-128)*31/64)<<11)|(63<<5)|(31-(v-128)*31/64);
    return (31<<11)|((63-(v-192)*63/63)<<5);
}
void feather_tft_draw(const uint8_t *bins,unsigned n,unsigned mhz,unsigned span_mhz,const char *footer) {
    if(!lcd || !bins || !n)return;
    int64_t now=esp_timer_get_time();
    if(now-last_draw<100000)return;
    last_draw=now;
    if(mhz!=current_mhz || span_mhz!=current_span)memset(pixels,0,PIXEL_BYTES);
    current_mhz=mhz;current_span=span_mhz;
    memmove(pixels+(WATER_Y+1)*WIDTH,pixels+WATER_Y*WIDTH,(FOOT_Y-WATER_Y-1)*WIDTH*2);
    memset(pixels,0,WATER_Y*WIDTH*2);
    memset(pixels+FOOT_Y*WIDTH,0,(HEIGHT-FOOT_Y)*WIDTH*2);
    unsigned peak=0;
    for(unsigned x=0;x<WIDTH;x++) {
        unsigned lo=x*n/WIDTH,hi=(x+1)*n/WIDTH;
        if(hi<=lo)hi=lo+1;
        unsigned v=0;
        for(unsigned j=lo;j<hi;j++){unsigned code=bins[(j+n/2)%n];if(code>v)v=code;}
        if(v>peak)peak=v;
        level[x]=v;
    }
    /* Fixed 60 dB relative scale, explicitly uncalibrated (never dBm). */
    for(unsigned x=0;x<WIDTH;x++) {
        int relative=(int)level[x]-(int)peak+120;
        unsigned h=relative>0?relative*50/120:0;
        if(h>50)h=50;
        for(unsigned y=28;y<=78;y++)if(y==28 || y==53 || y==78 || x%60==0)dot(x,y,GRID);
        for(unsigned y=78-h;y<=78;y++)dot(x,y,CYAN);
        unsigned value=relative>0?relative*255/120:0;
        if(value>255)value=255;
        dot(x,WATER_Y,heat(value));
    }
    char s[64];
    snprintf(s,sizeof(s),"%u MHZ",mhz);text(4,3,s,3,WHITE);
    snprintf(s,sizeof(s),"SPAN %u",span_mhz);text(168,5,s,2,CYAN);
    text(4,20,"RELATIVE POWER / SNAPSHOTS",1,WHITE);
    snprintf(s,sizeof(s),"%u",mhz-span_mhz/2);text(2,81,s,1,WHITE);
    snprintf(s,sizeof(s),"%u",mhz);text(112,81,s,1,WHITE);
    snprintf(s,sizeof(s),"%u",mhz+span_mhz/2);text(220,81,s,1,WHITE);
    text(4,128,footer?footer:"",1,WHITE);
    flush();frames++;
}
unsigned feather_tft_button(void) {
    static bool pressed;
    static int64_t down,last_change;
    int64_t now=esp_timer_get_time();
    bool state=!gpio_get_level(0);
    if(state==pressed || now-last_change<30000)return 0;
    last_change=now;pressed=state;
    if(state){down=now;return 0;}
    int64_t duration=now-down;
    return duration>=1500000?3:duration>=600000?2:duration>=30000?1:0;
}
bool feather_tft_command(const char *line) {
    if(!strcmp(line,"LCD?")) {
        char s[100];int n=snprintf(s,sizeof(s),"LCD %u %u %u 240 135\n",current_mhz,current_span,frames);
        burst_serial_send(s,n);return true;
    }
    if(!strcmp(line,"LCDSHOT")) {
        const char *header="LCDSHOT 240 135 RGB565BE 64800\n";
        burst_serial_send(header,strlen(header));burst_serial_send(pixels,PIXEL_BYTES);return true;
    }
    return false;
}
