/*
 * Copyright (C) 2024 Hery Dang (henrydang@mijoconnected.com)
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "bl616_glb.h"
#include "bflb_gpio.h"
#include "bflb_spi.h"
#include "bflb_i2c.h"
#include "usbd_core.h"
#include "bflb_mtimer.h"
#include "board.h"
#include "ina229.h"
#include "tca9534.h"
#include "bat_sim.h"
#include "gw1n.h"

#include <stdarg.h>  // For va_list

#define GPIO_LED GPIO_PIN_3
#define BOOT_PIN GPIO_PIN_2

static struct bflb_device_s *gpio;

extern void cdc_acm_init(void);
extern void tca9534_test(void);

void gpio_init(void)
{
    gpio = bflb_device_get_by_name("gpio");

    /* status led */
    bflb_gpio_init(gpio, GPIO_LED, GPIO_OUTPUT | GPIO_SMT_EN | GPIO_DRV_0);
    bflb_gpio_set(gpio, GPIO_LED);

    /* boot button */
    bflb_gpio_init(gpio, BOOT_PIN, GPIO_INPUT | GPIO_SMT_EN | GPIO_DRV_0);

    /* i2c0_scl */
    bflb_gpio_init(gpio, GPIO_PIN_16, GPIO_FUNC_I2C0 | GPIO_ALTERNATE | GPIO_PULLUP | GPIO_SMT_EN | GPIO_DRV_1);
    /* i2c0_sda */
    bflb_gpio_init(gpio, GPIO_PIN_17, GPIO_FUNC_I2C0 | GPIO_ALTERNATE | GPIO_PULLUP | GPIO_SMT_EN | GPIO_DRV_1);
}

void status_led_on(void)
{
    bflb_gpio_reset(gpio, GPIO_LED);    
}

void status_led_off(void)
{
    bflb_gpio_set(gpio, GPIO_LED);    
}

int main(void)
{
    board_init();
    gpio_init();
    tca9534_init();

    /* turn off bat sim output soon as possible */
    tca9534_pin_control(BAT_SIM_ENA, 0);
    tca9534_pin_control(VOL_MEASURE, 0);

    /* initialize usb cdc acm */
    cdc_acm_init();

    printf("Start program...\r\n");
    printf("Power on FPGA\r\n");
    gowin_power_off();
    gowin_power_on();
    bflb_mtimer_delay_ms(200);
    gowin_fpga_config();

    bat_sim_read_config_data_code_epprom();
    bat_sim_fast_mode_write(DATA_3P8); /* Default output voltage */
    //tca9534_pin_control(BAT_SIM_ENA, 1);
    tca9534_pin_control(VOL_MEASURE, 1);
    printf("Enable battery simulator output\r\n");

    printf("Init INA229...\r\n");
    bflb_mtimer_delay_ms(200);
    ina229_init();

    while (1) {
        /* Check if user press boot pin */
        if(bflb_gpio_read(gpio, BOOT_PIN))
        {
            /* wait for button release */
            while(bflb_gpio_read(gpio, BOOT_PIN));
            printf("System will reset after 3s\r\n");

            for(int i = 0; i < 3; i++)
            {
                bflb_mtimer_delay_ms(500);
                status_led_on();
                bflb_mtimer_delay_ms(500);
                status_led_off();
            }

            status_led_on();
            printf("System reset!\r\n");
            GLB_SW_System_Reset();
        }
    }
}
