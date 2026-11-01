// Коннектор STELLS (JavaScript / Node.js).
// Команды пульта приходят JSON-строками в stdin, телеметрию печатайте JSON-строками в stdout.
// Пример: пересылка команд на дрон/робота по UDP (ESP32/ESP8266, Tello-подобные, свои прошивки).
const dgram = require('dgram');
const readline = require('readline');

const TARGET_HOST = '192.168.4.1';   // IP вашего дрона/контроллера
const TARGET_PORT = 8888;            // порт, который слушает ваша прошивка
const sock = dgram.createSocket('udp4');
const state = { alt: 0, battery: 100, armed: false, mode: 'UDP', roll: 0, pitch: 0, yaw: 0 };

sock.on('message', (msg) => {
  // если устройство шлёт JSON-телеметрию — пробрасываем в пульт
  try { Object.assign(state, JSON.parse(msg.toString())); } catch { /* не JSON */ }
});
sock.bind(0);

readline.createInterface({ input: process.stdin }).on('line', (line) => {
  let cmd; try { cmd = JSON.parse(line); } catch { return; }
  sock.send(Buffer.from(line), TARGET_PORT, TARGET_HOST);       // пересылаем как есть
  if (cmd.type === 'drone') {
    if (cmd.cmd === 'arm' || cmd.cmd === 'takeoff') state.armed = true;
    if (cmd.cmd === 'disarm' || cmd.cmd === 'land') state.armed = false;
  }
  if (cmd.type === 'rc') { state.roll = cmd.roll * 30; state.pitch = cmd.pitch * 30; }
});

setInterval(() => console.log(JSON.stringify({ type: 'telemetry', drone: state })), 250);
console.log(JSON.stringify({ type: 'log', text: `UDP-коннектор → ${TARGET_HOST}:${TARGET_PORT}` }));
