// Logic tests for the UI code in wuwa_app.py. Run them with:  python tests/test_logic.py
// They call the app's own functions with a fake clock, so the results never depend on today's date.

function runTests() {
  const results = [];
  const realNow = Date.now.bind(Date);
  let fakeNow = null;
  Date.now = () => (fakeNow === null ? realNow() : fakeNow);

  const at = iso => { fakeNow = Date.parse(iso); };
  const iso = ms => new Date(ms).toISOString();
  const useServer = code => { st.set.srv = code; updateResetShift(); };
  const tickDaily = id => { st.done[id] = periodKeys().d; updateStreak(); };
  const untickDaily = id => { st.done[id] = null; updateStreak(); };
  const resetState = () => {
    st = freshState();
    tasks = [{c: 'd', id: 'a', t: 'A', s: ''}];
    useServer('EU');
  };
  const equal = (actual, expected, what = '') => {
    const a = JSON.stringify(actual), e = JSON.stringify(expected);
    if (a !== e) throw new Error(`${what ? what + ': ' : ''}expected ${e}, got ${a}`);
  };
  const test = (name, fn) => {
    resetState();
    try {
      fn();
      results.push({ok: true, name});
    } catch (e) {
      results.push({ok: false, name, error: e.message});
    }
  };

  // ---- reset times
  test('Europe: daily reset at 04:00 server time (03:00 UTC)', () => {
    at('2026-10-12T02:59:00Z');
    const before = periodKeys().d;
    at('2026-10-12T03:00:00Z');
    equal(periodKeys().d, before + 1, 'day changes at the reset');
    equal(iso(periodKeys().next.d), '2026-10-13T03:00:00.000Z', 'next daily reset');
  });

  test('America: daily reset at 09:00 UTC', () => {
    useServer('AM');
    at('2026-10-12T08:59:00Z');
    const before = periodKeys().d;
    at('2026-10-12T09:00:00Z');
    equal(periodKeys().d, before + 1, 'day changes at the reset');
    equal(iso(periodKeys().next.d), '2026-10-13T09:00:00.000Z', 'next daily reset');
  });

  test('Asia: daily reset at 20:00 UTC the day before', () => {
    useServer('AS');
    at('2026-10-11T19:59:00Z');
    equal(iso(periodKeys().next.d), '2026-10-11T20:00:00.000Z', 'just before');
    at('2026-10-11T20:00:00Z');
    equal(iso(periodKeys().next.d), '2026-10-12T20:00:00.000Z', 'just after');
  });

  test('Weekly reset on Monday 04:00 server time', () => {
    at('2026-10-12T02:59:00Z');   // Monday 03:59 server time
    const week = periodKeys().w;
    equal(iso(periodKeys().next.w), '2026-10-12T03:00:00.000Z', 'next weekly reset');
    at('2026-10-12T03:00:00Z');
    equal(periodKeys().w, week + 1, 'week changes at the reset');
    equal(iso(periodKeys().next.w), '2026-10-19T03:00:00.000Z', 'following weekly reset');
  });

  test('Monthly reset on the 1st 04:00 server time', () => {
    at('2026-11-01T02:59:00Z');
    const month = periodKeys().m;
    equal(iso(periodKeys().next.m), '2026-11-01T03:00:00.000Z', 'next monthly reset');
    at('2026-11-01T03:00:00Z');
    equal(periodKeys().m, month + 1, 'month changes at the reset');
    equal(iso(periodKeys().next.m), '2026-12-01T03:00:00.000Z', 'following monthly reset');
  });

  test('Monthly reset over the new year', () => {
    at('2026-12-31T12:00:00Z');
    equal(iso(periodKeys().next.m), '2027-01-01T03:00:00.000Z');
  });

  // ---- Waveplate and Crystal
  test('Waveplate: +1 every 6 minutes', () => {
    at('2026-10-10T10:00:00Z');
    st.wp = {v: 200, ts: Date.now(), c: 10};
    at('2026-10-10T11:00:00Z');
    const w = waveplateNow();
    equal(w.waveplate, 210, 'value after an hour');
    equal(w.fullIn, 180 * MINUTE, 'time until full');
    equal(w.crystal, 10, 'crystal does not move yet');
  });

  test('Waveplate stops at 240', () => {
    at('2026-10-10T10:00:00Z');
    st.wp = {v: 239, ts: Date.now(), c: 0};
    at('2026-10-10T12:00:00Z');
    equal(waveplateNow().waveplate, 240);
    equal(waveplateNow().fullIn, 0);
  });

  test('Crystal starts only once Waveplate is full, then +1 every 12 minutes', () => {
    at('2026-10-10T10:00:00Z');
    st.wp = {v: 230, ts: Date.now(), c: 0};   // full after 60 minutes
    at('2026-10-10T11:00:00Z');
    equal(waveplateNow().crystal, 0, 'right when full');
    at('2026-10-10T11:12:00Z');
    equal(waveplateNow().crystal, 1, '12 minutes later');
  });

  test('Crystal stops at 480', () => {
    at('2026-10-10T10:00:00Z');
    st.wp = {v: 240, ts: Date.now(), c: 479};
    at('2026-10-11T10:00:00Z');
    equal(waveplateNow().crystal, 480);
    equal(waveplateNow().crystalFullIn, 0);
  });

  // ---- streak and week overview
  test('Streak: days in a row, back to 1 after a missed day', () => {
    at('2026-10-10T12:00:00Z'); tickDaily('a');
    equal(st.streak, 1, 'first day');
    at('2026-10-11T12:00:00Z'); tickDaily('a');
    equal(st.streak, 2, 'second day');
    at('2026-10-13T12:00:00Z'); tickDaily('a');
    equal(st.streak, 1, 'after a missed day');
  });

  test('Streak: unticking the last daily task takes the step back', () => {
    at('2026-10-10T12:00:00Z'); tickDaily('a');
    at('2026-10-11T12:00:00Z'); tickDaily('a');
    untickDaily('a');
    equal(st.streak, 1, 'streak');
    equal(st.fullDays.length, 1, 'full days');
  });

  test('Week overview counts the full days of this week', () => {
    at('2026-10-12T12:00:00Z'); tickDaily('a');   // Monday
    at('2026-10-14T12:00:00Z'); tickDaily('a');   // Wednesday
    const strip = renderWeekStrip(periodKeys());
    equal(strip.includes('<b>2</b> / 7 full days'), true, 'total');
    equal((strip.match(/class="day on"/g) || []).length, 2, 'filled days');
    at('2026-10-19T12:00:00Z');                   // next Monday: a new week starts empty
    equal(renderWeekStrip(periodKeys()).includes('<b>0</b> / 7 full days'), true, 'next week');
  });

  // ---- dates, versions, formatting
  test('Server time input converts both ways', () => {
    const value = '2026-11-15T12:30';
    equal(iso(parseServerInput(value)), '2026-11-15T11:30:00.000Z', 'to UTC');
    equal(toServerInput(parseServerInput(value)), value, 'back');
  });

  test('Version comparison', () => {
    equal(compareVersions('1.3.0', '1.2.9') > 0, true, '1.3.0 > 1.2.9');
    equal(compareVersions('1.10.0', '1.9.0') > 0, true, '1.10.0 > 1.9.0');
    equal(compareVersions('1.3', '1.3.0'), 0, '1.3 = 1.3.0');
  });

  test('Duration format', () => {
    equal(formatDuration(0), '0h 00m 00s');
    equal(formatDuration(DAY + HOUR + 61000), '1d 1h 01m 01s');
  });

  // ---- migration of saved data from older versions
  test('Migration from defaults version 4', () => {
    const old = [
      {c: 'd', id: 'daily', t: 'Daily Activity', s: ''},
      {c: 'd', id: 'nest_fg', t: 'Fallen Grave nest', s: ''},
      {c: 'w', id: 'pod', t: 'Pioneer Podcast weekly tasks', s: 'Reset on Monday'},
      {c: 'w', id: 'boss', t: 'Bosses', s: ''},
      {c: 'w', id: 'c1', t: 'My own task', s: ''},
    ];
    loadState(JSON.stringify({done: {}, defV: 4, streak: 2, lastFull: 100}), JSON.stringify(old));
    equal(tasks.map(t => t.id), ['daily', 'nests', 'pod', 'boss', 'c1'], 'task order');
    equal(findTask('pod').s, 'Weekly missions, claim the rewards', 'old text updated');
    equal(findTask('boss').mx, 3, 'counter target added');
    equal(st.defV, DEFAULTS_VERSION, 'defaults version');
    equal(st.fullDays, [100, 99], 'week overview rebuilt from the streak');
  });

  Date.now = realNow;
  return results;
}
