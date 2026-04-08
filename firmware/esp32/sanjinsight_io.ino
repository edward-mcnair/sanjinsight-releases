/*
 * SanjINSIGHT I/O Controller Firmware — ESP32 Edition
 * =====================================================
 * Target:  ESP32 / ESP32-S2 / ESP32-S3 / ESP32-C3
 * Serial:  115200 baud, 8N1 (USB-serial via CP2102 or native USB)
 * Version: 1.0
 *
 * Drop-in replacement for the Arduino Nano SanjINSIGHT I/O firmware.
 * Speaks the same ASCII serial protocol so no host-side code changes
 * are needed — just set driver: "esp32" in config.yaml.
 *
 * Differences from the Nano version:
 *   - 12-bit ADC (0–4095) instead of 10-bit (0–1023).
 *     Set adc_bits: 12 in config.yaml, or change ADC_RESOLUTION
 *     below to 10 for backwards compatibility.
 *   - Default LED pins are GPIO 16–19 (safe GPIOs that avoid
 *     boot-strapping and flash pins).
 *   - GPIO range 25–33 for general-purpose I/O (avoids SPI flash
 *     pins 6–11 and strapping pins 0, 2, 12, 15).
 *   - No bootloader reset on serial open — host skips the 2 s wait.
 *   - WiFi/BT radios are disabled at boot to reduce power and noise.
 *
 * Pin assignments (default — override via config.yaml led_channels):
 *   GPIO 16 — LED Channel 0 (470 nm Blue)
 *   GPIO 17 — LED Channel 1 (530 nm Green)
 *   GPIO 18 — LED Channel 2 (590 nm Amber)
 *   GPIO 19 — LED Channel 3 (625 nm Red)
 *   GPIO 25–33 — General-purpose digital I/O
 *   ADC1 CH0–CH7 (GPIO 36, 37, 38, 39, 32, 33, 34, 35) — Analog inputs
 *
 * Serial Protocol (identical to Arduino Nano firmware):
 *
 *   Command              Response
 *   -------              --------
 *   IDENT                IDENT SanjIO-ESP32 1.0
 *   LED <ch>             OK           (ch: 0-3 select, -1 all off)
 *   PIN <pin> <0|1>      OK           (set digital output)
 *   READ <pin>           PIN <pin> <0|1>
 *   ADC <ch>             ADC <ch> <value>  (value: 0-4095 at 12-bit)
 *   STATUS               STATUS <led> <uptime_ms>
 *
 * Build:
 *   Arduino IDE: Select board "ESP32 Dev Module" (or your variant),
 *   set Upload Speed to 921600, Flash Frequency 80 MHz.
 *
 *   PlatformIO:
 *     [env:esp32]
 *     platform = espressif32
 *     board = esp32dev
 *     framework = arduino
 *     monitor_speed = 115200
 */

#include <WiFi.h>     // For WiFi.mode(WIFI_OFF)
#include <esp_bt.h>   // For esp_bt_controller_disable()

// ── Configuration ───────────────────────────────────────────────────

// ADC resolution: 12 = native ESP32 (0–4095), 10 = Nano-compatible (0–1023)
#define ADC_RESOLUTION 12

// LED channel pins (active-HIGH)
#define NUM_LED_CHANNELS 4
const int LED_PINS[NUM_LED_CHANNELS] = {16, 17, 18, 19};

// General-purpose digital I/O pin range
// GPIO 25–33 are safe on standard ESP32 modules.
// Avoid: 0 (boot), 2 (boot), 6–11 (flash), 12 (boot), 15 (boot).
#define GPIO_FIRST 25
#define GPIO_LAST  33

// ADC1 channel-to-GPIO mapping (ESP32)
// ADC1_CH0=GPIO36, CH1=37, CH2=38, CH3=39, CH4=32, CH5=33, CH6=34, CH7=35
const int ADC_PINS[8] = {36, 37, 38, 39, 32, 33, 34, 35};

// ── State ───────────────────────────────────────────────────────────

int activeLed = -1;            // -1 = all off
unsigned long bootTime;

// ── Serial Buffer ───────────────────────────────────────────────────

#define BUF_SIZE 64
char cmdBuf[BUF_SIZE];
int  cmdLen = 0;

// ── Setup ───────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    bootTime = millis();

    // Disable WiFi and Bluetooth to reduce power draw and RF noise
    WiFi.mode(WIFI_OFF);
    esp_bt_controller_disable();

    // Set ADC resolution
    analogReadResolution(ADC_RESOLUTION);

    // Initialise LED pins as outputs, all off
    for (int i = 0; i < NUM_LED_CHANNELS; i++) {
        pinMode(LED_PINS[i], OUTPUT);
        digitalWrite(LED_PINS[i], LOW);
    }

    // Initialise GPIO pins as outputs, all low
    for (int pin = GPIO_FIRST; pin <= GPIO_LAST; pin++) {
        pinMode(pin, OUTPUT);
        digitalWrite(pin, LOW);
    }

    // ADC input pins are input by default (no setup needed)
    // Note: GPIO 34–39 are input-only on ESP32 — cannot be used as outputs.
}

// ── Main Loop ───────────────────────────────────────────────────────

void loop() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (cmdLen > 0) {
                cmdBuf[cmdLen] = '\0';
                processCommand(cmdBuf);
                cmdLen = 0;
            }
        } else if (cmdLen < BUF_SIZE - 1) {
            cmdBuf[cmdLen++] = c;
        }
    }
}

// ── Command Processor ───────────────────────────────────────────────

void processCommand(const char* cmd) {
    // IDENT — report firmware version
    if (strncmp(cmd, "IDENT", 5) == 0) {
        Serial.println("IDENT SanjIO-ESP32 1.0");
        return;
    }

    // LED <ch> — select LED channel (-1 = all off)
    if (strncmp(cmd, "LED ", 4) == 0) {
        int ch = atoi(cmd + 4);
        selectLed(ch);
        Serial.println("OK");
        return;
    }

    // PIN <pin> <0|1> — set digital output
    if (strncmp(cmd, "PIN ", 4) == 0) {
        int pin, val;
        if (sscanf(cmd + 4, "%d %d", &pin, &val) == 2) {
            if (pin >= GPIO_FIRST && pin <= GPIO_LAST) {
                digitalWrite(pin, val ? HIGH : LOW);
                Serial.println("OK");
            } else {
                Serial.println("ERR Pin out of range");
            }
        } else {
            Serial.println("ERR Bad PIN args");
        }
        return;
    }

    // READ <pin> — read digital pin state
    if (strncmp(cmd, "READ ", 5) == 0) {
        int pin = atoi(cmd + 5);
        // Allow reading LED pins (16–19), GPIO pins (25–33), and ADC pins (32–39)
        if ((pin >= 16 && pin <= 19) || (pin >= 25 && pin <= 39)) {
            int val = digitalRead(pin);
            Serial.print("PIN ");
            Serial.print(pin);
            Serial.print(" ");
            Serial.println(val);
        } else {
            Serial.println("ERR Pin out of range");
        }
        return;
    }

    // ADC <ch> — read analog channel (0–7 → ADC1 channels)
    if (strncmp(cmd, "ADC ", 4) == 0) {
        int ch = atoi(cmd + 4);
        if (ch >= 0 && ch <= 7) {
            int val = analogRead(ADC_PINS[ch]);
            Serial.print("ADC ");
            Serial.print(ch);
            Serial.print(" ");
            Serial.println(val);
        } else {
            Serial.println("ERR ADC channel out of range");
        }
        return;
    }

    // STATUS — report current state
    if (strncmp(cmd, "STATUS", 6) == 0) {
        unsigned long uptime = millis() - bootTime;
        Serial.print("STATUS ");
        Serial.print(activeLed);
        Serial.print(" ");
        Serial.println(uptime);
        return;
    }

    // Unknown command
    Serial.println("ERR Unknown command");
}

// ── LED Selection ───────────────────────────────────────────────────

void selectLed(int ch) {
    // Turn off all LED channels first
    for (int i = 0; i < NUM_LED_CHANNELS; i++) {
        digitalWrite(LED_PINS[i], LOW);
    }

    // Activate the requested channel
    if (ch >= 0 && ch < NUM_LED_CHANNELS) {
        digitalWrite(LED_PINS[ch], HIGH);
        activeLed = ch;
    } else {
        activeLed = -1;  // all off
    }
}
