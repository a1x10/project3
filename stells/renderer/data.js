// Данные: платы, операционные системы, типы моделей, режимы использования.
// kind: 'linux' — на плату ставится агент; 'mcu' — микроконтроллер (скетч по USB);
//       'x86' — мини-ПК; 'router' — OpenWrt-роутеры.

const g = (family, group, kind, list) => list.map(([name, note]) => ({
  id: (family + '-' + name).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''),
  family, group, kind, name, note: note || '',
}));

export const BOARDS = [
  // ---------------- Raspberry Pi
  ...g('Raspberry Pi', 'Raspberry Pi 5', 'linux', [['Raspberry Pi 5', 'Raspberry Pi 5, 500 / 500+, and Compute Module 5']]),
  ...g('Raspberry Pi', 'Raspberry Pi 4', 'linux', [['Raspberry Pi 4', 'Raspberry Pi 4 Model B, 400, and Compute Module 4 / 4S']]),
  ...g('Raspberry Pi', 'Raspberry Pi 3', 'linux', [['Raspberry Pi 3', 'Raspberry Pi 3 Model A+ / B / B+ and Compute Module 3 / 3+']]),
  ...g('Raspberry Pi', 'Raspberry Pi 2', 'linux', [['Raspberry Pi 2', 'Raspberry Pi 2 Model B']]),
  ...g('Raspberry Pi', 'Raspberry Pi 1', 'linux', [['Raspberry Pi 1', 'Raspberry Pi 1 Model A / A+ / B / B+ and Compute Module 1']]),
  ...g('Raspberry Pi', 'Raspberry Pi Zero 2 W', 'linux', [['Raspberry Pi Zero 2 W', 'Raspberry Pi Zero 2 W']]),
  ...g('Raspberry Pi', 'Raspberry Pi Zero', 'linux', [['Raspberry Pi Zero', 'Raspberry Pi Zero, Zero W, and Zero WH']]),
  ...g('Raspberry Pi', 'Микроконтроллеры', 'mcu', [['Raspberry Pi Pico / Pico W', 'RP2040'], ['Raspberry Pi Pico 2 / 2 W', 'RP2350']]),

  // ---------------- Banana Pi
  ...g('Banana Pi', '1 — Классическая M-серия', 'linux', [
    ['Banana Pi BPI-M1', 'самая первая плата'], ['Banana Pi BPI-M1+', 'Banana Pi M1 Plus'], ['Banana Pi BPI-M2'],
    ['Banana Pi BPI-M2+', 'Banana Pi M2 Plus'], ['Banana Pi BPI-M2 Ultra'], ['Banana Pi BPI-M2 Berry'],
    ['Banana Pi BPI-M2 Magic'], ['Banana Pi BPI-M3'], ['Banana Pi BPI-M64'], ['Banana Pro']]),
  ...g('Banana Pi', '2 — Современная M-серия', 'linux', [
    ['Banana Pi BPI-M2 Pro'], ['Banana Pi BPI-M2S'], ['Banana Pi BPI-M4'], ['Banana Pi BPI-M4 Berry'],
    ['Banana Pi BPI-M4 Zero'], ['Banana Pi BPI-M5'], ['Banana Pi BPI-M5 Pro'], ['Banana Pi BPI-M6'],
    ['Banana Pi BPI-M7S'], ['Banana Pi BPI-M8']]),
  ...g('Banana Pi', '3 — Компактная P-серия', 'linux', [
    ['Banana Pi BPI-P2 Zero'], ['Banana Pi BPI-P2 Pro'], ['Banana Pi P2 Maker'], ['Banana Pi BPI-M2 Zero', 'мини-формат M-серии']]),
  ...g('Banana Pi', '4 — Промышленная и RISC-V/AI (F-серия)', 'linux', [
    ['Banana Pi BPI-F2'], ['Banana Pi BPI-F2S'], ['Banana Pi BPI-F3', 'RISC-V'], ['Banana Pi BPI-F4'],
    ['Banana Pi BPI-F5'], ['Banana Pi BPI-Forge1'], ['Banana Pi CanMV-K230D-Zero']]),
  ...g('Banana Pi', '5 — Сетевая R и W-серия (роутеры)', 'router', [
    ['Banana Pi BPI-R1'], ['Banana Pi BPI-R2'], ['Banana Pi BPI-R2 Pro'], ['Banana Pi BPI-R3'], ['Banana Pi BPI-R3 Mini'],
    ['Banana Pi BPI-R4'], ['Banana Pi BPI-R4 Pro'], ['Banana Pi BPI-R4 Lite'], ['Banana Pi BPI-R64'], ['Banana Pi BPI-W2'],
    ['Banana Pi BPI-W3'], ['Banana Pi BPI-RV2'], ['Banana Pi BPI-Wifi5'], ['Banana Pi BPI-Wifi6']]),
  ...g('Banana Pi', '6 — Вычислительные модули (CM)', 'linux', [
    ['Banana Pi BPI-CM2'], ['Banana Pi BPI-CM5 Pro'], ['Banana Pi BPI-CM6'], ['Banana Pi BPI-SM9'],
    ['Banana Pi BPI-SM10'], ['Banana Pi BPI-AIM7'], ['Banana Pi BPI-S64 Core']]),
  ...g('Banana Pi', '7 — Микроконтроллеры (IoT)', 'mcu', [
    ['Banana Pi BPI-Pico-RP2040'], ['Banana Pi BPI-PicoW-S3'], ['Banana Pi BPI-Leaf-S3'], ['Banana Pi BPI-Bit'],
    ['Banana Pi BPI-KVM'], ['Banana Pi BPI-D1', 'мини-плата со встроенной камерой'], ['Banana Pi BPI-G1']]),

  // ---------------- ODROID
  ...g('ODROID', '1 — Серия C', 'linux', [
    ['ODROID-C0', 'супер-микро плата'], ['ODROID-C1'], ['ODROID-C1+'], ['ODROID-C2', 'поддержка 4K'],
    ['ODROID-C4', 'стабильная рабочая лошадка'], ['ODROID-C5', 'графика нового поколения']]),
  ...g('ODROID', '2 — Серия N', 'linux', [
    ['ODROID-N1', 'ранний прототип'], ['ODROID-N2'], ['ODROID-N2+', 'король ретро-эмуляции'], ['ODROID-N2L', 'мини-версия без Ethernet']]),
  ...g('ODROID', '3 — Серия M (Rockchip)', 'linux', [
    ['ODROID-M1', 'NVMe M.2 и SATA'], ['ODROID-M1S', 'распаянная eMMC'], ['ODROID-M2', 'LPDDR5 до 16 ГБ']]),
  ...g('ODROID', '4 — Серия H (x86 Intel)', 'x86', [
    ['ODROID-H2'], ['ODROID-H2+'], ['ODROID-H3'], ['ODROID-H3+'], ['ODROID-H4', 'Intel N97'],
    ['ODROID-H4+', 'много SATA'], ['ODROID-H4 Ultra', '8 ядер Core i3'], ['ODROID-H5', '10 GbE']]),
  ...g('ODROID', '5 — Серия HC и MC (NAS, сервера)', 'linux', [
    ['ODROID-HC1', 'для диска 2.5"'], ['ODROID-HC2', 'для диска 3.5"'], ['ODROID-HC4', 'сервер-тостер'], ['ODROID-MC1', 'модуль для кластеров']]),
  ...g('ODROID', '6 — Серия GO (консоли)', 'linux', [
    ['ODROID-GO', 'ESP32'], ['ODROID-GO Advance'], ['ODROID-GO Super', '5-дюймовый экран'], ['ODROID-GO Ultra']]),
  ...g('ODROID', '7 — Архивные (Samsung Exynos)', 'linux', [
    ['ODROID-X'], ['ODROID-X2'], ['ODROID-U2'], ['ODROID-U3'], ['ODROID-XU'], ['ODROID-XU3'],
    ['ODROID-XU4', 'активный кулер'], ['ODROID-XU4Q', 'пассивный радиатор'], ['ODROID-W', 'мини-клон Raspberry Pi']]),

  // ---------------- Arduino
  ...g('Arduino', '1 — Классические', 'mcu', [
    ['Arduino UNO R3', 'самая популярная плата для новичков'], ['Arduino Leonardo', 'умеет быть клавиатурой/мышкой'],
    ['Arduino Mega 2560', 'много контактов: 3D-принтеры, роботы'], ['Arduino Micro'], ['Arduino Nano'],
    ['Arduino Pro Mini', 'без USB'], ['Arduino LilyPad', 'вшивается в одежду']]),
  ...g('Arduino', '2 — UNO нового поколения', 'mcu', [
    ['Arduino UNO R4 Minima', '32-бит Renesas'], ['Arduino UNO R4 WiFi', 'Wi-Fi, Bluetooth, LED-матрица']]),
  ...g('Arduino', '2 — UNO нового поколения', 'linux', [['Arduino UNO Q (2GB / 4GB)', 'Qualcomm + Debian Linux']]),
  ...g('Arduino', '3 — Семейство Nano', 'mcu', [
    ['Arduino Nano Every'], ['Arduino Nano 33 IoT', 'Wi-Fi + крипточип'], ['Arduino Nano 33 BLE / BLE Sense', 'Bluetooth и датчики'],
    ['Arduino Nano ESP32', 'ESP32-S3, MicroPython'], ['Arduino Nano Matter', 'Thread, Matter, Zigbee']]),
  ...g('Arduino', '4 — Профессиональные', 'mcu', [
    ['Arduino Portenta H7'], ['Arduino Portenta C33'], ['Arduino Nicla Vision', 'камера + ML на борту'],
    ['Arduino GIGA R1 WiFi'], ['Arduino MKR WiFi 1010'], ['Arduino Opta', 'промышленный ПЛК']]),

  // ---------------- NanoPi (FriendlyELEC)
  ...g('NanoPi', '1 — Серия NEO', 'linux', [
    ['NanoPi NEO / NEO Air'], ['NanoPi NEO2 / NEO2 Black'], ['NanoPi NEO3'], ['NanoPi NEO Plus2']]),
  ...g('NanoPi', '2 — Серия R (роутеры)', 'router', [
    ['NanoPi R1 / R1S'], ['NanoPi R2S / R2S Plus / R2C'], ['NanoPi R28S'], ['NanoPi R3S / R3S-LTS'],
    ['NanoPi R4S / R4SE'], ['NanoPi R5S / R5C'], ['NanoPi R6S / R6C', 'RK3588'], ['NanoPi R76S', 'три порта']]),
  ...g('NanoPi', '3 — Серия M', 'linux', [
    ['NanoPi M1 / M1 Plus'], ['NanoPi M2 / M3'], ['NanoPi M4 / M4B / M4V2'], ['NanoPi M5', 'RK3576'], ['NanoPi M6 / M6V2']]),
  ...g('NanoPi', '4 — NanoPC', 'linux', [['NanoPC-T4'], ['NanoPC-T6 / T6-LTS / T6 Plus']]),
  ...g('NanoPi', '5 — Duo и Zero', 'linux', [['NanoPi Duo / Duo2'], ['ZeroPi'], ['NanoPi Zero2']]),
  ...g('NanoPi', '6 — Fire и K', 'linux', [['NanoPi 2 Fire / Fire3'], ['NanoPi K1 Plus / K2']]),
  ...g('NanoPi', '7 — Модули CORE', 'linux', [['NanoPi NEO Core / Core2'], ['SOM-RK3399'], ['CM3588 / CM3588-Plus']]),

  // ---------------- Другие платы, поддерживающие STELLS
  ...g('NVIDIA Jetson', 'Jetson (лучшее для машинного зрения)', 'linux', [
    ['Jetson Nano'], ['Jetson Orin Nano / Orin Nano Super'], ['Jetson Orin NX'], ['Jetson AGX Orin'], ['Jetson Xavier NX'], ['Jetson AGX Thor']]),
  ...g('Orange Pi', 'Orange Pi', 'linux', [
    ['Orange Pi 5 / 5B / 5 Plus / 5 Max / 5 Pro'], ['Orange Pi 5 Ultra'], ['Orange Pi AIpro'], ['Orange Pi 4 LTS / 4A'],
    ['Orange Pi 3B / 3 LTS'], ['Orange Pi Zero 3 / Zero 2W'], ['Orange Pi CM4 / CM5'], ['Orange Pi RV2', 'RISC-V']]),
  ...g('Radxa', 'Radxa ROCK', 'linux', [
    ['Radxa ROCK 5B / 5B+'], ['Radxa ROCK 5A / 5C / 5D'], ['Radxa ROCK 4SE / 4C+'], ['Radxa ROCK 3A / 3C'],
    ['Radxa ZERO 3W / 3E'], ['Radxa X4', 'x86 Intel N100'], ['Radxa CM5']]),
  ...g('Rockchip/Allwinner/прочие', 'Другие одноплатники', 'linux', [
    ['Khadas VIM3 / VIM4'], ['Libre Computer Le Potato / Renegade / Sweet Potato'], ['Pine64 ROCKPro64 / Quartz64 / Star64'],
    ['BeagleBone Black / AI-64 / BeaglePlay / BeagleY-AI'], ['Milk-V Duo / Mars / Jupiter', 'RISC-V'],
    ['StarFive VisionFive 2', 'RISC-V'], ['LattePanda Delta / Sigma / Mu', 'x86'], ['Google Coral Dev Board', 'Edge TPU'],
    ['Hailo-8 / Raspberry Pi AI HAT+', 'NPU-ускоритель'], ['Luckfox Pico', 'камера + NPU'], ['Sipeed LicheeRV / MaixCAM', 'камера + NPU']]),
  ...g('ESP32 и др. МК', 'Микроконтроллеры', 'mcu', [
    ['ESP32 / ESP32-S3 / ESP32-C3 / ESP32-C6'], ['ESP32-CAM', 'камера'], ['ESP8266 / NodeMCU / Wemos D1'],
    ['STM32 (Blue Pill / Nucleo)'], ['Teensy 4.0 / 4.1'], ['Seeed XIAO (ESP32S3 Sense / RP2040 / nRF52840)'],
    ['M5Stack Core / AtomS3 / CoreS3']]),
];

export const FAMILY_FILTERS = ['Все', 'Raspberry Pi', 'Banana Pi', 'ODROID', 'Arduino', 'NanoPi', 'NVIDIA Jetson', 'Orange Pi', 'Radxa', 'Rockchip/Allwinner/прочие', 'ESP32 и др. МК'];

// Операционные системы. for: на каких типах плат применимо.
const L = ['linux'], X = ['x86'], M = ['mcu'], R = ['router'];
const LX = ['linux', 'x86'], LR = ['linux', 'router'], ALL = ['linux', 'x86', 'router'];
export const OS_LIST = [
  // Raspberry Pi и Debian-семейство
  { cat: 'Raspberry Pi OS', for: L, items: ['Raspberry Pi OS (64-bit) Bookworm/Trixie', 'Raspberry Pi OS (32-bit)', 'Raspberry Pi OS Lite (64-bit)', 'Raspberry Pi OS Lite (32-bit)', 'Raspberry Pi OS Legacy (Bullseye)', 'Raspberry Pi Desktop (x86)'] },
  { cat: 'Ubuntu', for: ALL, items: ['Ubuntu 25.10', 'Ubuntu 24.04 LTS Desktop', 'Ubuntu 24.04 LTS Server', 'Ubuntu 22.04 LTS Desktop', 'Ubuntu 22.04 LTS Server', 'Ubuntu 20.04 LTS', 'Ubuntu Core 24', 'Ubuntu MATE', 'Kubuntu', 'Xubuntu', 'Lubuntu', 'Ubuntu Rockchip (Joshua Riek)'] },
  { cat: 'Debian и производные', for: ALL, items: ['Debian 13 Trixie', 'Debian 12 Bookworm', 'Debian 11 Bullseye', 'Armbian (Debian/Ubuntu)', 'DietPi', 'Linux Mint', 'MX Linux', 'Kali Linux (ARM)', 'Parrot OS', 'Pop!_OS', 'Zorin OS', 'elementary OS', 'Devuan', 'Raspbian (старый)'] },
  { cat: 'Образы производителей', for: L, items: ['Bianbu (Banana Pi F3)', 'Banana Pi BPI-OS', 'Hardkernel Ubuntu (ODROID)', 'FriendlyCore / FriendlyWrt / FriendlyDesktop (NanoPi)', 'Orange Pi OS (OH/Arch/Droid)', 'Radxa OS', 'NVIDIA JetPack / Jetson Linux (L4T)', 'Khadas OOWOW / Fenix', 'Arduino App Lab Debian (UNO Q)', 'BeagleBoard Debian', 'Coral Mendel Linux'] },
  { cat: 'Fedora / Red Hat', for: ALL, items: ['Fedora Workstation 43', 'Fedora Server', 'Fedora IoT', 'Rocky Linux 9/10', 'AlmaLinux 9/10', 'CentOS Stream', 'RHEL for Edge', 'openEuler'] },
  { cat: 'Arch и др. rolling', for: ALL, items: ['Arch Linux ARM', 'Arch Linux', 'Manjaro ARM', 'Manjaro', 'EndeavourOS', 'openSUSE Tumbleweed', 'openSUSE Leap', 'Gentoo', 'Void Linux', 'NixOS', 'Slackware ARM'] },
  { cat: 'Лёгкие / встраиваемые Linux', for: LR, items: ['Alpine Linux', 'Buildroot', 'Yocto / Poky', 'Tiny Core / piCore', 'postmarketOS', 'Ubuntu Core', 'balenaOS', 'Flatcar'] },
  { cat: 'Роутеры', for: LR, items: ['OpenWrt', 'ImmortalWrt', 'FriendlyWrt', 'OPNsense', 'pfSense', 'RouterOS (MikroTik CHR)', 'VyOS', 'IPFire'] },
  { cat: 'Медиа / игры / умный дом', for: ALL, items: ['LibreELEC (Kodi)', 'OSMC', 'Batocera', 'RetroPie', 'Recalbox', 'Lakka', 'ArkOS / ROCKNIX (ODROID-GO)', 'Home Assistant OS', 'OctoPi (3D-печать)', 'Volumio', 'moOde audio', 'Pi-hole (Raspberry Pi OS)'] },
  { cat: 'NAS / сервер', for: ALL, items: ['OpenMediaVault', 'TrueNAS SCALE', 'Unraid', 'Proxmox VE', 'CasaOS / ZimaOS', 'Umbrel'] },
  { cat: 'Android и др.', for: L, items: ['Android 14/15 (AOSP)', 'LineageOS', 'Android TV', 'emteria.OS', 'KonstaKANG Android (Raspberry Pi)', 'HarmonyOS / OpenHarmony', 'Chromium OS / FydeOS'] },
  { cat: 'BSD и прочие', for: ALL, items: ['FreeBSD 14', 'NetBSD', 'OpenBSD', 'RISC OS', 'Plan 9 / 9front', 'Haiku', 'Redox OS'] },
  { cat: 'Windows', for: LX, items: ['Windows 11 (x64)', 'Windows 11 on ARM', 'Windows 10 (x64)', 'Windows 10 IoT Enterprise', 'Windows 10 IoT Core', 'Windows Server 2022/2025'] },
  { cat: 'macOS (компьютер)', for: X, items: ['macOS 26 Tahoe', 'macOS 15 Sequoia', 'macOS 14 Sonoma', 'macOS 13 Ventura'] },
  { cat: 'Микроконтроллеры (без ОС / RTOS)', for: M, items: ['Arduino (без ОС, bare-metal)', 'Arduino Mbed OS', 'FreeRTOS', 'ESP-IDF', 'MicroPython', 'CircuitPython', 'Zephyr RTOS', 'RT-Thread', 'NuttX', 'Mongoose OS', 'Tasmota', 'ESPHome', 'Pico SDK', 'STM32 HAL / CubeIDE', 'Embassy (Rust)'] },
];

export const MODEL_TYPES = [
  { type: 'LLM', title: 'LLM', sub: 'Большая языковая модель', desc: 'Диалог, код, рассуждения. Нужен мощный ПК или Jetson Orin / RK3588.', heavy: 3 },
  { type: 'LM', title: 'LM', sub: 'Языковая модель', desc: 'Команды, тексты, автоматизация на средних платах.', heavy: 2 },
  { type: 'CV', title: 'Машинное зрение', sub: 'Computer Vision', desc: 'Объекты, люди, движение, трекинг. Работает от Raspberry Pi 4.', heavy: 1 },
  { type: 'VLM', title: 'VLM', sub: 'Зрение + язык', desc: 'Описывает, что видит камера, отвечает на вопросы по изображению.', heavy: 3 },
  { type: 'SLM', title: 'SLM', sub: 'Малая языковая модель', desc: 'Компактная модель, работает прямо на плате.', heavy: 1 },
  { type: 'LMM', title: 'LMM', sub: 'Мультимодальная модель', desc: 'Текст, изображения и звук в одной модели.', heavy: 3 },
];

export const USAGES = [
  { id: 'cars', n: 1, title: 'Машины', icon: '🚗', desc: 'Радиоуправляемые машины и роверы: моторы, руль, фары, автопилот по камере.' },
  { id: 'robots', n: 2, title: 'Роботы', icon: '🤖', desc: 'Манипуляторы и роботы: сервоприводы, захват, распознавание объектов.' },
  { id: 'drones', n: 3, title: 'Дроны', icon: '🛸', desc: 'Отдельный пульт: MAVLink (ArduPilot/PX4), видео, телеметрия, AI-пилот.' },
  { id: 'cameras', n: 4, title: 'Камеры', icon: '📷', desc: 'Видеонаблюдение с ИИ: детекция, запись, снимки, несколько камер.' },
  { id: 'wol', n: 5, title: 'WOL', icon: '⚡', desc: 'Wake-on-LAN: удалённое включение компьютеров и серверов по сети.' },
];

export const SUPPORT = {
  whatsapp: '+7 702 538 97 49', whatsappUrl: 'https://wa.me/77025389749',
  telegram: '@Stells_help', telegramUrl: 'https://t.me/Stells_help',
  creator: '@l3xn0', creatorUrl: 'https://t.me/l3xn0',
};

// Шаблоны коннекторов на разных языках (Python и JS приходят из папки firmware/connectors).
export const LANGS = [
  ['python', 'Python'], ['javascript', 'JavaScript (Node)'], ['typescript', 'TypeScript'], ['c', 'C'], ['cpp', 'C++'],
  ['rust', 'Rust'], ['go', 'Go'], ['java', 'Java'], ['kotlin', 'Kotlin'], ['csharp', 'C# (dotnet-script)'], ['lua', 'Lua'],
  ['ruby', 'Ruby'], ['php', 'PHP'], ['perl', 'Perl'], ['bash', 'Bash'], ['powershell', 'PowerShell'],
];

const PROTO = 'Команды пульта приходят JSON-строками в stdin, телеметрию печатайте JSON-строками в stdout.';
export const TEMPLATES = {
  c: `// Коннектор STELLS на C. ${PROTO}
#include <stdio.h>
#include <string.h>
int main(void) {
  char line[512]; double alt = 0; int armed = 0;
  setvbuf(stdout, NULL, _IONBF, 0);
  printf("{\\"type\\":\\"log\\",\\"text\\":\\"C-коннектор запущен\\"}\\n");
  while (fgets(line, sizeof line, stdin)) {
    if (strstr(line, "\\"arm\\"") || strstr(line, "\\"takeoff\\"")) armed = 1;
    if (strstr(line, "\\"disarm\\"") || strstr(line, "\\"land\\"")) armed = 0;
    if (strstr(line, "\\"takeoff\\"")) alt = 3;
    /* TODO: отправьте команду своему дрону (UART: open("/dev/ttyUSB0"), UDP: sendto) */
    printf("{\\"type\\":\\"telemetry\\",\\"drone\\":{\\"alt\\":%.1f,\\"armed\\":%s,\\"mode\\":\\"C\\"}}\\n", alt, armed ? "true" : "false");
  }
  return 0;
}
`,
  cpp: `// Коннектор STELLS на C++. ${PROTO}
#include <iostream>
#include <string>
int main() {
  std::ios::sync_with_stdio(false);
  std::string line; bool armed = false; double alt = 0;
  std::cout << R"({"type":"log","text":"C++-коннектор запущен"})" << std::endl;
  while (std::getline(std::cin, line)) {
    if (line.find("\\"arm\\"") != std::string::npos || line.find("takeoff") != std::string::npos) armed = true;
    if (line.find("disarm") != std::string::npos || line.find("\\"land\\"") != std::string::npos) armed = false;
    if (line.find("takeoff") != std::string::npos) alt = 3;
    // TODO: отправьте команду своему дрону
    std::cout << R"({"type":"telemetry","drone":{"alt":)" << alt << R"(,"armed":)" << (armed ? "true" : "false") << R"(,"mode":"CPP"}})" << std::endl;
  }
}
`,
  rust: `// Коннектор STELLS на Rust. ${PROTO}
use std::io::{self, BufRead, Write};
fn main() {
    let stdin = io::stdin();
    let mut out = io::stdout();
    let (mut armed, mut alt) = (false, 0.0f32);
    writeln!(out, r#"{{"type":"log","text":"Rust-коннектор запущен"}}"#).unwrap();
    for line in stdin.lock().lines() {
        let l = line.unwrap();
        if l.contains("\\"arm\\"") || l.contains("takeoff") { armed = true; }
        if l.contains("disarm") || l.contains("\\"land\\"") { armed = false; }
        if l.contains("takeoff") { alt = 3.0; }
        // TODO: отправьте команду своему дрону
        writeln!(out, r#"{{"type":"telemetry","drone":{{"alt":{},"armed":{},"mode":"RUST"}}}}"#, alt, armed).unwrap();
        out.flush().unwrap();
    }
}
`,
  go: `// Коннектор STELLS на Go. ${PROTO}
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
)

func main() {
	state := map[string]any{"alt": 0.0, "armed": false, "mode": "GO"}
	fmt.Println(\`{"type":"log","text":"Go-коннектор запущен"}\`)
	sc := bufio.NewScanner(os.Stdin)
	for sc.Scan() {
		var cmd map[string]any
		if json.Unmarshal(sc.Bytes(), &cmd) != nil { continue }
		switch cmd["cmd"] {
		case "arm": state["armed"] = true
		case "takeoff": state["armed"], state["alt"] = true, 3.0
		case "land", "disarm": state["armed"], state["alt"] = false, 0.0
		}
		// TODO: отправьте команду своему дрону (net.Dial("udp", ...) или serial)
		b, _ := json.Marshal(map[string]any{"type": "telemetry", "drone": state})
		fmt.Println(string(b))
	}
}
`,
  java: `// Коннектор STELLS на Java (запуск: java Connector.java). ${PROTO}
import java.io.*;
public class Connector {
  public static void main(String[] a) throws IOException {
    BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
    boolean armed = false; double alt = 0; String line;
    System.out.println("{\\"type\\":\\"log\\",\\"text\\":\\"Java-коннектор запущен\\"}");
    while ((line = in.readLine()) != null) {
      if (line.contains("\\"arm\\"") || line.contains("takeoff")) armed = true;
      if (line.contains("disarm") || line.contains("\\"land\\"")) armed = false;
      if (line.contains("takeoff")) alt = 3;
      System.out.println("{\\"type\\":\\"telemetry\\",\\"drone\\":{\\"alt\\":" + alt + ",\\"armed\\":" + armed + ",\\"mode\\":\\"JAVA\\"}}");
    }
  }
}
`,
  kotlin: `// Коннектор STELLS на Kotlin script. ${PROTO}
var armed = false
println("""{"type":"log","text":"Kotlin-коннектор запущен"}""")
generateSequence(::readLine).forEach { l ->
    if ("takeoff" in l || "\\"arm\\"" in l) armed = true
    if ("disarm" in l || "\\"land\\"" in l) armed = false
    println("""{"type":"telemetry","drone":{"armed":$armed,"mode":"KT"}}""")
}
`,
  csharp: `// Коннектор STELLS на C# (dotnet tool install -g dotnet-script). ${PROTO}
using System;
bool armed = false;
Console.WriteLine("{\\"type\\":\\"log\\",\\"text\\":\\"C#-коннектор запущен\\"}");
string line;
while ((line = Console.ReadLine()) != null) {
  if (line.Contains("takeoff") || line.Contains("\\"arm\\"")) armed = true;
  if (line.Contains("disarm") || line.Contains("\\"land\\"")) armed = false;
  Console.WriteLine("{\\"type\\":\\"telemetry\\",\\"drone\\":{\\"armed\\":" + armed.ToString().ToLower() + ",\\"mode\\":\\"CS\\"}}");
}
`,
  typescript: `// Коннектор STELLS на TypeScript (запуск через npx tsx). ${PROTO}
import * as readline from 'readline';
const state = { alt: 0, armed: false, mode: 'TS' };
console.log(JSON.stringify({ type: 'log', text: 'TS-коннектор запущен' }));
readline.createInterface({ input: process.stdin }).on('line', (l: string) => {
  const c = JSON.parse(l);
  if (c.cmd === 'arm' || c.cmd === 'takeoff') state.armed = true;
  if (c.cmd === 'land' || c.cmd === 'disarm') state.armed = false;
  console.log(JSON.stringify({ type: 'telemetry', drone: state }));
});
`,
  lua: `-- Коннектор STELLS на Lua. ${PROTO}
local armed = false
print('{"type":"log","text":"Lua-коннектор запущен"}')
io.stdout:setvbuf('no')
for line in io.lines() do
  if line:find('takeoff') or line:find('"arm"') then armed = true end
  if line:find('disarm') or line:find('"land"') then armed = false end
  print(string.format('{"type":"telemetry","drone":{"armed":%s,"mode":"LUA"}}', tostring(armed)))
end
`,
  ruby: `# Коннектор STELLS на Ruby. ${PROTO}
require 'json'
$stdout.sync = true
state = { alt: 0, armed: false, mode: 'RUBY' }
puts({ type: 'log', text: 'Ruby-коннектор запущен' }.to_json)
$stdin.each_line do |l|
  c = JSON.parse(l) rescue next
  state[:armed] = true if %w[arm takeoff].include?(c['cmd'])
  state[:armed] = false if %w[disarm land].include?(c['cmd'])
  puts({ type: 'telemetry', drone: state }.to_json)
end
`,
  php: `<?php
// Коннектор STELLS на PHP. ${PROTO}
$state = ['alt' => 0, 'armed' => false, 'mode' => 'PHP'];
echo json_encode(['type' => 'log', 'text' => 'PHP-коннектор запущен']), "\\n";
while (($l = fgets(STDIN)) !== false) {
  $c = json_decode($l, true);
  if (in_array($c['cmd'] ?? '', ['arm', 'takeoff'])) $state['armed'] = true;
  if (in_array($c['cmd'] ?? '', ['disarm', 'land'])) $state['armed'] = false;
  echo json_encode(['type' => 'telemetry', 'drone' => $state]), "\\n";
}
`,
  perl: `# Коннектор STELLS на Perl. ${PROTO}
$| = 1; my $armed = 'false';
print qq({"type":"log","text":"Perl-коннектор запущен"}\\n);
while (my $l = <STDIN>) {
  $armed = 'true' if $l =~ /takeoff|"arm"/;
  $armed = 'false' if $l =~ /disarm|"land"/;
  print qq({"type":"telemetry","drone":{"armed":$armed,"mode":"PERL"}}\\n);
}
`,
  bash: `#!/usr/bin/env bash
# Коннектор STELLS на Bash. ${PROTO}
# Пример: пересылка каждой команды на дрон по UDP (nc) или в UART (echo > /dev/ttyUSB0)
echo '{"type":"log","text":"Bash-коннектор запущен"}'
armed=false
while IFS= read -r line; do
  case "$line" in *takeoff*|*'"arm"'*) armed=true;; *disarm*|*'"land"'*) armed=false;; esac
  # echo "$line" | nc -u -w0 192.168.4.1 8888
  echo "{\\"type\\":\\"telemetry\\",\\"drone\\":{\\"armed\\":$armed,\\"mode\\":\\"BASH\\"}}"
done
`,
  powershell: `# Коннектор STELLS на PowerShell. ${PROTO}
$armed = $false
Write-Output '{"type":"log","text":"PowerShell-коннектор запущен"}'
while ($null -ne ($line = [Console]::In.ReadLine())) {
  if ($line -match 'takeoff|"arm"') { $armed = $true }
  if ($line -match 'disarm|"land"') { $armed = $false }
  Write-Output ('{"type":"telemetry","drone":{"armed":' + $armed.ToString().ToLower() + ',"mode":"PS"}}')
}
`,
};
