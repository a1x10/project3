// Подмена ответов API BilimClass для проверки скриншотов на НАСТОЯЩЕМ сайте www.bilimclass.kz
// (сайт загружается по-настоящему, а вход и дневник — тестовые). Используется в tests/site/*.
const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const WD = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье'];

const USER = {
  userId: 1, role: 'student', firstname: 'Тест', surname: 'Ученик', school_id: 1, chatToken: 'c',
  school: { id: 1, name: 'Школа №1', eduYears: [{ eduYear: 2026, isCurrent: true }] },
  group: { id: 2, name: '7 «А»' }, studentInfo: { studentGroupUuid: 'g1', studentGroupUuids: ['g1'] },
};

// spec: { 0: [['Алгебра', '№ 250']], ... } — по дням недели (0 = пн)
export function mockWeek(mondayDMY, spec) {
  const [d, m, y] = mondayDMY.split('.').map(Number);
  const base = Date.UTC(y, m - 1, d);
  return {
    date: mondayDMY,
    days: [0, 1, 2, 3, 4, 5, 6].map((i) => {
      const dt = new Date(base + i * 86400000);
      return {
        date: `${dt.getUTCDate()} ${MONTHS[dt.getUTCMonth()]}`, day: WD[i], isHoliday: false,
        subjects: (spec[i] || []).map(([label, hw], n) => ({
          scheduleUuid: `s${i}${n}`, label, timeslot: `${String(8 + n).padStart(2, '0')}:00 - ${String(8 + n).padStart(2, '0')}:45`,
          cabinet: `${200 + n}`, teacherFio: 'Иванова А.', theme: 'Тема урока',
          homeworkBody: hw, homeworkUuid: hw ? `h${i}${n}` : null, homeworkType: 'simple', hasFiles: false, hasBooks: false, type: 'regular',
        })),
      };
    }),
  };
}

// weeks: { '12.10.2026': spec, ... }, scores: оценки по scheduleUuid (должны быть скрыты на скриншоте)
export function installMocks(context, { currentWeek, weeks, scores = {} }) {
  const calls = [];
  const publicPaths = ['/api/translate', '/api/v3/translate-hash', '/api/v4/os/system/settings', '/api/v2/os/config/microservices',
    '/api/v4/os/system/sendpulse', '/api/v4/os/system/general-banners', '/api/v2/os/guest/article'];
  return context.route(/api\.bilimclass\.kz|journal-service\.bilimclass\.kz/, async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    calls.push(`${p}${url.search}`);
    const json = (data) => route.fulfill({ json: data });
    if (url.hostname === 'journal-service.bilimclass.kz') return json({ data: scores });
    if (publicPaths.includes(p)) return route.continue();
    if (p === '/api/v2/os/login') {
      return json({ access_token: 'T', refresh_token: 'R', exp_time: '2099-01-01 00:00:00', user_info: USER });
    }
    if (p === '/api/v2/os/user-info') return json({ data: USER });
    if (p.endsWith('/education-years')) return json({ data: [{ eduYear: 2026, isCurrent: true, status: 'active', label: '2026-2027' }] });
    if (p.endsWith('/related-children') || p.endsWith('/static-modal')) return json({ data: [] });
    if (p.endsWith('/group-list')) return json({ data: [{ value: 2, label: '7 «А»', id: 2, name: '7 «А»' }] });
    if (p.endsWith('/need-pass-change')) return json({ data: false });
    if (p.endsWith('/clientoffice/diary/weeks')) {
      return json({ data: { week: currentWeek, weeks: Object.keys(weeks).map((w) => ({ value: w, label: w })), periods: [{ value: 1, label: '1 четверть' }] } });
    }
    if (p.endsWith('/clientoffice/diary')) {
      const date = url.searchParams.get('date');
      return json({ data: mockWeek(date, weeks[date] || {}) });
    }
    return json({ data: {} });
  }).then(() => calls);
}
