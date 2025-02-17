/*
 * Copyright (C) 2024 Hery Dang (henrydang@mijoconnected.com)
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "bflb_gpio.h"
#include "bflb_spi.h"
#include "bflb_mtimer.h"
#include "board.h"
#include "tca9534.h"
#include "ina229.h"
#include <stdio.h>
#include <string.h>

#define MAX_REG_VALUE_SIZE (40/8 + 1)

extern uint8_t *p_data_rpt_buf;
extern void cdc_acm_data_rpt_send(void);

static struct bflb_device_s *spi0;
static struct bflb_device_s *gpio;

void ina229_reg_read(uint8_t addr, uint8_t *value, uint8_t len);
void ina229_reg_write(uint8_t addr, uint16_t value);

/* Default ina229 configuration */
ina229_config_t ina229_config = {
    .cnv_time  = CONV_TIME_280uS,
    .avg_num   = AVG_NUM_1,
    .adc_range = ADC_RANGE_0,
    .avg_alert = AVG_ALERT_YES
};

ina229_lsb_param_t ina229_lsb = {
    .current_lsb = CURRENT_LSB_0,
    .vshunt_lsb  = VSHUNT_LSB_0,
    .vbus_lsb    = VBUS_LSB_0
};

static volatile uint8_t irq_flag = 0;
static uint8_t vbus_buff[4];
static uint8_t current_buff[4];
static uint8_t diag_alrt[3];

static volatile uint32_t g_id = 0;
static uint32_t g_sample_idx = 0;

static void gpio0_isr(uint8_t pin)
{
    uint32_t vbus_raw, current_raw;
    int32_t vbus, current;

    ina229_data_report_t *p_data_rpt = (ina229_data_report_t *)p_data_rpt_buf;

    if (pin == GPIO_PIN_0) {
        ina229_reg_read(DIAG_ALRT, diag_alrt, 3);
        ina229_reg_read(VBUS, vbus_buff, 4);
        ina229_reg_read(CURRENT, current_buff, 4);

        vbus_raw = ((vbus_buff[1] << 16) | (vbus_buff[2] << 8) | vbus_buff[3]) & 0xFFFFFF;
        current_raw = ((current_buff[1] << 16) | (current_buff[2] << 8) | current_buff[3]) & 0xFFFFFF;
        vbus = (vbus_raw >> 4) & 0xFFFFF; // Extract bits [23:4]
        current = (current_raw >> 4) & 0xFFFFF; // Extract bits [23:4]

        // Convert the 20-bit two's complement value to a signed integer
        if (vbus & 0x80000) { // Check the sign bit (bit 19 in the 20-bit value)
            vbus |= 0xFFF00000; // If the sign bit is set, extend the sign to the 32-bit value
        }

        // Convert the 20-bit two's complement value to a signed integer
        if (current & 0x80000) { // Check the sign bit (bit 19 in the 20-bit value)
            current |= 0xFFF00000; // If the sign bit is set, extend the sign to the 32-bit value
        }

        p_data_rpt->voltage[g_sample_idx] = vbus*ina229_lsb.vbus_lsb;
        p_data_rpt->current[g_sample_idx] = current*ina229_lsb.current_lsb*1000;

        // printf("Vbus[V] = %f\t current[mA] = %f\r\n",  p_data_rpt->voltage[g_sample_idx], p_data_rpt->current[g_sample_idx]);

        if(g_sample_idx >= DATA_RPT_SAMPLE_SIZE)
        {
            p_data_rpt->sign = 0x87654321;
            p_data_rpt->id = g_id;
            g_id += 1;
            g_sample_idx = 0;
            irq_flag = 1; /* flag to send out the report data */
        }
        else
        {
            g_sample_idx += 1;
        }
    }
}

static void spi_gpio_init(void)
{
    gpio = bflb_device_get_by_name("gpio");

    /* spi cs */
    bflb_gpio_init(gpio, GPIO_PIN_28, GPIO_FUNC_SPI0 | GPIO_ALTERNATE | GPIO_SMT_EN | GPIO_DRV_1);
    /* spi clk */
    bflb_gpio_init(gpio, GPIO_PIN_29, GPIO_FUNC_SPI0 | GPIO_ALTERNATE | GPIO_SMT_EN | GPIO_DRV_1);
    /* spi miso */
    bflb_gpio_init(gpio, GPIO_PIN_30, GPIO_FUNC_SPI0 | GPIO_ALTERNATE | GPIO_SMT_EN | GPIO_DRV_1);
    /* spi mosi */
    bflb_gpio_init(gpio, GPIO_PIN_27, GPIO_FUNC_SPI0 | GPIO_ALTERNATE | GPIO_SMT_EN | GPIO_DRV_1);

    /* configure alert as external interrupt gpio */
    bflb_irq_disable(gpio->irq_num);
    bflb_gpio_init(gpio, GPIO_PIN_0, GPIO_INPUT | GPIO_PULLUP | GPIO_SMT_EN);
    bflb_gpio_int_init(gpio, GPIO_PIN_0, GPIO_INT_TRIG_MODE_SYNC_RISING_EDGE);
    bflb_gpio_irq_attach(GPIO_PIN_0, gpio0_isr);
}

void ina229_enable_alert_interrupt(void)
{
    bflb_irq_enable(gpio->irq_num);
}

void ina229_disable_alert_interrupt(void)
{
    bflb_irq_disable(gpio->irq_num);
}

void ina229_enable_volt_measurement(void)
{
    tca9534_pin_control(VOL_MEASURE, 1);
}

void ina229_disable_volt_measurement(void)
{
    tca9534_pin_control(VOL_MEASURE, 0);
}

static void spi_init(uint8_t baudmhz)
{
    struct bflb_spi_config_s spi_cfg = {
        .freq = baudmhz * 1000 * 1000,
        .role = SPI_ROLE_MASTER,
        .mode = SPI_MODE1,
        .data_width = SPI_DATA_WIDTH_8BIT,
        .bit_order = SPI_BIT_MSB,
        .byte_order = SPI_BYTE_LSB,
        .tx_fifo_threshold = 0,
        .rx_fifo_threshold = 0,
    };

    spi0 = bflb_device_get_by_name("spi0");
    bflb_spi_init(spi0, &spi_cfg);
    bflb_spi_feature_control(spi0, SPI_CMD_SET_CS_INTERVAL, 1);
    bflb_spi_feature_control(spi0, SPI_CMD_SET_DATA_WIDTH, SPI_DATA_WIDTH_8BIT);
}

void ina229_interface_bus_init(void)
{
    spi_gpio_init();
    spi_init(10);
}

void ina229_reg_read(uint8_t addr, uint8_t *value, uint8_t len)
{
    uint8_t p_tx[MAX_REG_VALUE_SIZE];

    memset(p_tx, 0, MAX_REG_VALUE_SIZE);
    memset(value, 0, len);

    p_tx[0] = (addr << 2) | 0x01;

    if(len < MAX_REG_VALUE_SIZE)
    {
        bflb_spi_poll_exchange(spi0, p_tx, value, len);
    }
    else
    {
        bflb_spi_poll_exchange(spi0, p_tx, value, MAX_REG_VALUE_SIZE);
    }
}

void ina229_reg_write(uint8_t addr, uint16_t value)
{
    uint8_t p_tx[3],  p_rx[3];

    p_tx[0] = (addr << 2);
    p_tx[1] = (uint8_t)(value >> 8);
    p_tx[2] = (uint8_t)(value & 0xFF);

    bflb_spi_poll_exchange(spi0, p_tx, p_rx, 3);
}

void ina229_reset(void)
{
    ina229_reg_write(CONFIG, (0x1 << 15));
    bflb_mtimer_delay_ms(10);
}

void ina229_start_measure(void)
{
    uint8_t adc_cfg[3];
    uint16_t adc_cfg_value;

    /* Reset data report id */
    g_id = 0;
    g_sample_idx = 0;

    ina229_reg_read(ADC_CONFIG, adc_cfg, 3);
    adc_cfg_value = (uint16_t)((adc_cfg[1] << 8) | (adc_cfg[2]));
    ina229_reg_write(ADC_CONFIG, (0xB << 12) | adc_cfg_value);
}

void ina229_stop_measure(void)
{
    uint8_t adc_cfg[3];
    uint16_t adc_cfg_value;
    ina229_reg_read(ADC_CONFIG, adc_cfg, 3);
    adc_cfg_value = (uint16_t)((adc_cfg[1] << 8) | (adc_cfg[2]));
    ina229_reg_write(ADC_CONFIG, adc_cfg_value & 0xFFF);
}

/*
 * Full scale ranges:
 *    Shunt voltage:
 *        ±163.84 mV (ADCRANGE = 0)  312.5 nV/LSB
 *        ±40.96 mV  (ADCRANGE = 1) 78.125 nV/LSB
 *    Bus voltage:
 *        0V to 85V 195.3125 µV/LSB
 *    Temperature:
 *        –40°C to +125°C 7.8125 m°C/LSB
 *
 *    SHUNT_CAL = 13107.2 x 10^6 x CURRENT_LSB x RSHUNT
 *    the value of SHUNT_CAL must be multiplied by 4 for ADCRANGE = 1
 *    CURRENT_LSB = Maximum Expected Current / 2^19
 *
 *    Current [A] = CURRENT_LSB x CURRENT
 *    CURRENT is the value read from the CURRENT register
 *
 *    Power [W] = 3.2 x CURRENT_LSB x POWER
 *    POWER is the value read from the POWER register
 *
 *    Energy [J] = 16 x 3.2 x CURRENT_LSB x ENERGY
 *    Charge [C] = CURRENT_LSB x CHARGE
 *
 *    In case ADCRANGE = 0:
 *        Imax = 163.84mV / 50mΩ = 3.2768A
 *        CURRENT_LSB = 3.2768 / 2^19 = 0.00000625A = 6.25µA
 *        SHUNT_CAL = 13107.2 x 10^6 x 0.00000625 x 0.05 = 4096
 *
 *    In case ADCRANGE = 1:
 *        Imax = 40.96mV / 50mΩ = 0.8192A
 *        CURRENT_LSB = 0.8192 / 2^19 = 0.0000015625A = 1.5625µA
 *        SHUNT_CAL = (13107.2 x 10^6 x 0.0000015625 x 0.05) x 4 = 4096
 *
 */

void ina229_param_config(ina229_config_t *config)
{
    uint8_t man_id[3], device_id[3];

    ina229_reg_read(MANUFACTURER_ID, man_id, 3);
    ina229_reg_read(DEVICE_ID, device_id, 3);
    printf("Manufacturer ID = %x%x\r\n", man_id[1], man_id[2]);
    printf("Device ID       = %x%x\r\n", device_id[1], device_id[2]);

    if(config->adc_range == ADC_RANGE_0)
    {
        ina229_lsb.current_lsb = CURRENT_LSB_0;
        ina229_lsb.vshunt_lsb  = VSHUNT_LSB_0;
        ina229_lsb.vbus_lsb    = VBUS_LSB_0;
    }
    else
    {
        ina229_lsb.current_lsb = CURRENT_LSB_1;
        ina229_lsb.vshunt_lsb  = VSHUNT_LSB_1;
        ina229_lsb.vbus_lsb    = VBUS_LSB_1;
    }

    printf("Conversion time config : %X\r\n", config->cnv_time);
    printf("Average num config     : %X\r\n", config->avg_num);
    printf("ADC range config       : %X\r\n", config->adc_range);
    printf("Alert on AVG config    : %X\r\n", config->avg_alert);
    printf("Current LSB            : %f\r\n", ina229_lsb.current_lsb);
    printf("Vshunt LSB             : %f\r\n", ina229_lsb.vshunt_lsb);
    printf("Vbus LSB               : %f\r\n", ina229_lsb.vbus_lsb);

    /*
     * Reset the ina229
     * RST[15]
     * RSTACC[14]
     * CONVDLY[13:6]
     * TEMPCOMP[5]
     * ADCRANGE[4]
     */
    ina229_reg_write(CONFIG, (0x1 << 15));
    bflb_mtimer_delay_ms(200);
    ina229_reg_write(CONFIG, (config->adc_range << 4));

    /* shunt calibration */
    ina229_reg_write(SHUNT_CAL, 4096);

    /*
     * ALATCH[15]
     * CNVR[14]     : 1h = Enables conversion ready flag on ALERT pin
     * SLOWALERT[13]: 1h = ALERT comparison on averaged value
     * APOL[12]     : 0h = Normal (Active-low, open-drain)
     */
    ina229_reg_write(DIAG_ALRT, (0x1 << 14) | (config->avg_alert << 13) | (0x0 << 12));

    /* enable alert interrupt */
    ina229_enable_alert_interrupt();

    /*
     * MODE[15:12]:
     *               9h => Continuous bus voltage only
     *               ah => Continuous shunt voltage only
     *               bh => Continuous shunt and bus voltage
     *               ch => Continuous temperature only
     *               dh => Continuous bus voltage and temperature
     *               eh => Continuous temperature and shunt voltage
     *               fh => Continuous bus voltage, shunt voltage and temperature
     *
     * VBUSCT[11:9]: (doesn't works at 50, 84, 150µs)
     *               3h => 280µs
     *               4h => 540µs
     *               5h => 1052µs
     *               6h => 2074µs
     *               7h => 4120µs
     * VSHCT[8:6]:
     *               3h => 280µs
     *               4h => 540µs
     *               5h => 1052µs
     *               6h => 2074µs
     *               7h => 4120µs
     * VTCT[5:3]:
     *               3h => 280µs
     *               4h => 540µs
     *               5h => 1052µs
     *               6h => 2074µs
     *               7h => 4120µs
     * AVG[2:0]:
     *               0h =>  1
     *               1h =>  4
     *               2h => 16
     *               3h => 64
     *               4h => 128
     *               5h => 256
     *               6h => 512
     *               7h => 1024
     *
     * Continuous shunt and bus voltage
     * VBUSCT -> 280µs
     * VSHCT  -> 280µs
     * AVG    -> 1024
     */
    ina229_reg_write(ADC_CONFIG, (config->cnv_time << 9) | (config->cnv_time << 6) | config->avg_num);
}

void ina229_init(void)
{
    ina229_interface_bus_init();

    ina229_param_config(&ina229_config);

    while(1)
    {
        if(irq_flag)
        {
            //printf("g_id[D] = %d\r\n", g_id);
            //printf("g_id[H] = %x\r\n", g_id);
            cdc_acm_data_rpt_send();
            irq_flag = 0;
        }
    }
}
