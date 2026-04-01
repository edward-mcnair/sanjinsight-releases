/*
 * SanjINSIGHT I/O Controller Firmware
 * ====================================
 * Target:  Arduino Nano (ATmega328P, 16 MHz)
 * Serial:  115200 baud, 8N1
 * Version: 1.0
 *
 * This firmware turns the Arduino Nano into an LED wavelength selector
 * and general-purpose I/O controller for Microsanj thermoreflectance
 * systems.
 *
 * Pin assignments:
 *   D2  — LED Channel 0 (470 nm Blue)
 *   D3  — LED Channel 1 (530 nm Green)
 *   D4  — LED Channel 2 (590 nm Amber)
 *   D5  — LED Channel 3 (625 nm Red)
 *   D6–D13 — General-purpose digital I/O
 *   A0–A7  — Analog inputs (10-bit ADC)
 *
 * Serial Protocol (line-based ASCII, \n terminated):
 *
 *   Command              Response
 *   -------              --------
 *   IDENT                IDENT SanjIO 1.0
 *   LED <ch>             OK           (ch: 0-3 select, -1 all off)
 *   PIN <pin> <0|1>      OK           (set digital output)
 *   READ <pin>           PIN <pin> <0|1>
 *   ADC <ch>             ADC <ch> <value>  (value: 0-1023)
 *   STATUS               STATUS <led> <uptime_ms>
 *
 * Notes:
 *   - Only one LED channel is active at a time.
 *   - LED pins are active-HIGH (HIGH = LED on).
 *   - The Arduino resets on serial open; the host waits 2 s for boot.
 *   - Unrecognised commands return "ERR Unknown command".
 */

// ── Pin Definitions ─────────────────────────────────────────────────

#define NUM_LED_CHANNELS 4
const int LED_PINS[NUM_LED_CHANNELS] = {2, 3, 4, 5};

// General-purpose output pins
#define GPIO_FIRST 6
#define GPIO_LAST  13

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

    // Analog pins are input by default (no setup needed)
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
        Serial.println("IDENT SanjIO 1.0");
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
        if (pin >= 2 && pin <= 13) {
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

    // ADC <ch> — read analog channel (A0–A7)
    if (strncmp(cmd, "ADC ", 4) == 0) {
        int ch = atoi(cmd + 4);
        if (ch >= 0 && ch <= 7) {
            int val = analogRead(A0 + ch);
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
