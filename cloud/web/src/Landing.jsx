import React from 'react';

const features = [
  { icon: '⌘', title: 'STELLA CODER', text: 'Автономный ИИ-агент в терминале: читает проект, правит код, запускает команды и тесты.', cmd: 'stella-coder login' },
  { icon: '✦', title: 'Vibing AI Studio', text: 'Приложение для Windows: опишите сайт словами — студия соберёт, покажет превью и выгрузит проект.' },
  { icon: '⇄', title: 'OpenAI-совместимый API', text: 'Ключ из бота подходит к любому клиенту: Cursor, Continue, LangChain, curl.' },
];

export default function Landing({ config, me, onLogin }) {
  const downloads = config?.downloads ?? [];
  const exe = downloads.find((d) => /\.exe$/i.test(d.name));
  return (
    <div className="landing">
      <section className="hero">
        <div className="glow" />
        <h1>
          Один аккаунт — <span className="grad">все ИИ-инструменты Stella</span>
        </h1>
        <p className="lead">Регистрация за 10 секунд через Telegram. Без паролей и почты. Ключи, лимиты и история — в личном кабинете.</p>
        <div className="row center-row">
          {me ? (
            <a className="btn primary lg" href="#/cabinet">
              Открыть кабинет
            </a>
          ) : (
            <button className="btn primary lg" onClick={onLogin}>
              Войти через Telegram
            </button>
          )}
          {exe ? (
            <a className="btn lg" href={exe.url} download>
              Скачать Studio для Windows
            </a>
          ) : (
            <a className="btn lg" href="#download">
              Скачать
            </a>
          )}
        </div>
      </section>

      <section className="grid3">
        {features.map((f) => (
          <div className="card feature" key={f.title}>
            <div className="ficon">{f.icon}</div>
            <h3>{f.title}</h3>
            <p className="muted">{f.text}</p>
            {f.cmd && <code className="cmd">{f.cmd}</code>}
          </div>
        ))}
      </section>

      <section className="card" id="download">
        <h2>Скачать и подключить</h2>
        <div className="grid2">
          <div>
            <h3>Vibing AI Studio (Windows)</h3>
            {downloads.length ? (
              <ul className="list">
                {downloads.map((d) => (
                  <li key={d.name}>
                    <a href={d.url} download>
                      {d.name}
                    </a>{' '}
                    <span className="muted small">{(d.size / 1048576).toFixed(1)} МБ</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">Установщик появится здесь, когда администратор загрузит его на сервер.</p>
            )}
            <p className="muted small">После запуска нажмите «Войти через Telegram» — и всё.</p>
          </div>
          <div>
            <h3>STELLA CODER (терминал)</h3>
            <pre className="code-block">{`stella-coder login ${config?.publicUrl || ''}`}</pre>
            <h3>Любой OpenAI-клиент</h3>
            <pre className="code-block">{`Base URL: ${config?.apiBase || '/v1'}
API key:  /key в Telegram-боте
Model:    auto`}</pre>
          </div>
        </div>
      </section>

      {config?.plans && (
        <section>
          <h2 className="center-text">Тарифы</h2>
          <div className="grid3">
            {Object.entries(config.plans).map(([id, p]) => (
              <div className="card plan" key={id}>
                <h3>{p.name}</h3>
                <div className="big">{p.dailyRequests === null ? '∞' : p.dailyRequests}</div>
                <div className="muted">запросов в день</div>
                <div className="muted small">{p.dailyTokens === null ? 'без лимита токенов' : `${p.dailyTokens.toLocaleString('ru-RU')} токенов в день`}</div>
              </div>
            ))}
          </div>
          <p className="muted center-text small">Тариф назначает администратор — напишите ему в Telegram.</p>
        </section>
      )}
    </div>
  );
}
