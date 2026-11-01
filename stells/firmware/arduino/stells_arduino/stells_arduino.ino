/*
  STELLS firmware для микроконтроллеров (Arduino UNO/Nano/Mega/Leonardo, UNO R4,
  Nano ESP32, ESP32, Banana Pi BPI-Pico/Leaf и др.).

  Плата подключается к компьютеру по USB. Приложение STELLS отправляет
  команды JSON построчно (115200 бод), плата отвечает телеметрией.

  Команды:
    {"type":"hello"}
    {"type":"drive","x":0.0,"y":0.5}      // машина: x — поворот, y — газ (-1..1)
    {"type":"stop"}
    {"type":"servo","index":0,"angle":30}  // робот: угол -90..90
    {"type":"lights","on":true}
    {"type":"pin","pin":13,"value":1}      // произвольный цифровой выход

  Схема по умолчанию (драйвер L298N / TB6612):
    Левый мотор:  ENA=5 (PWM), IN1=7, IN2=8
    Правый мотор: ENB=6 (PWM), IN3=9, IN4=4
    Сервоприводы: 3, 10, 11, 12      Фары: 13
*/
#include <Servo.h>   // для ESP32 установите библиотеку ESP32Servo и замените include

const int ENA = 5, IN1 = 7, IN2 = 8;
const int ENB = 6, IN3 = 9, IN4 = 4;
const int LIGHTS = 13;
const int SERVO_PINS[] = {3, 10, 11, 12};
const int SERVO_COUNT = 4;

Servo servos[SERVO_COUNT];
String line;
unsigned long lastCmd = 0, lastTel = 0;

float numAfter(const String &s, const char *key, float def) {
  int i = s.indexOf(key);
  if (i < 0) return def;
  i = s.indexOf(':', i);
  if (i < 0) return def;
  return s.substring(i + 1).toFloat();
}

void motor(int en, int a, int b, float v) {
  v = constrain(v, -1.0, 1.0);
  digitalWrite(a, v >= 0 ? HIGH : LOW);
  digitalWrite(b, v >= 0 ? LOW : HIGH);
  analogWrite(en, (int)(fabs(v) * 255));
}

void stopAll() { motor(ENA, IN1, IN2, 0); motor(ENB, IN3, IN4, 0); }

void handle(const String &s) {
  lastCmd = millis();
  if (s.indexOf("\"hello\"") >= 0) {
    Serial.println(F("{\"type\":\"welcome\",\"ok\":true,\"name\":\"STELLS MCU\",\"version\":\"1.0.0\"}"));
  } else if (s.indexOf("\"drive\"") >= 0) {
    float x = numAfter(s, "\"x\"", 0), y = numAfter(s, "\"y\"", 0);
    motor(ENA, IN1, IN2, y + x);
    motor(ENB, IN3, IN4, y - x);
  } else if (s.indexOf("\"stop\"") >= 0) {
    stopAll();
  } else if (s.indexOf("\"servo\"") >= 0) {
    int idx = (int)numAfter(s, "\"index\"", 0);
    int ang = (int)numAfter(s, "\"angle\"", 0);
    if (idx >= 0 && idx < SERVO_COUNT) servos[idx].write(constrain(ang + 90, 0, 180));
  } else if (s.indexOf("\"lights\"") >= 0) {
    digitalWrite(LIGHTS, s.indexOf("true") >= 0 ? HIGH : LOW);
  } else if (s.indexOf("\"pin\"") >= 0) {
    int p = (int)numAfter(s, "\"pin\"", -1);
    if (p >= 0) { pinMode(p, OUTPUT); digitalWrite(p, numAfter(s, "\"value\"", 0) > 0 ? HIGH : LOW); }
  }
}

void setup() {
  Serial.begin(115200);
  int outs[] = {ENA, IN1, IN2, ENB, IN3, IN4, LIGHTS};
  for (int p : outs) pinMode(p, OUTPUT);
  for (int i = 0; i < SERVO_COUNT; i++) { servos[i].attach(SERVO_PINS[i]); servos[i].write(90); }
  stopAll();
  Serial.println(F("{\"type\":\"welcome\",\"ok\":true,\"name\":\"STELLS MCU\"}"));
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { handle(line); line = ""; }
    else if (line.length() < 200) line += c;
  }
  if (millis() - lastCmd > 1500) stopAll();          // failsafe: нет связи — стоп
  if (millis() - lastTel > 1000) {
    lastTel = millis();
    Serial.print(F("{\"type\":\"telemetry\",\"system\":{\"uptime\":"));
    Serial.print(millis() / 1000);
    Serial.print(F(",\"a0\":"));
    Serial.print(analogRead(A0));
    Serial.println(F("}}"));
  }
}
