// Observe throughout preview, but accept a request only inside the native Confirm action.
// Request object identity ties the response to that action; matching payloads alone do not.
const {scheduleEvidence} = require('./ws_exact_observation');
const CONFIRM_REQUEST_WAIT_MS = 10000;

function isConfirmation(message) {
  const url = new URL(message.url());
  return url.origin === 'https://www.linkedin.com' &&
    url.pathname === '/flagship-web/rsc-action/actions/server-request' &&
    url.searchParams.get('sduiid') === 'com.linkedin.sdui.requests.sharing.ConfirmSchedulePost';
}

function observeSchedule(page, expected) {
  let armed = false;
  let started = false;
  let closed = false;
  let failure;
  let request;
  let requestBody;
  let responseSeen = false;
  let evidence;
  let requestDeadline = 0;
  let wakeRequest;
  const pending = new Set();
  const fail = message => {
    failure ||= new Error(message);
    wakeRequest?.();
  };
  const check = () => { if (failure) throw failure; };
  const onRequest = candidate => {
    if (!isConfirmation(candidate)) return;
    if (!armed || request) {
      fail('schedule confirmation outside intended action or duplicate request');
      return;
    }
    if (Date.now() >= requestDeadline) {
      fail('schedule confirmation request timeout');
      return;
    }
    request = candidate;
    requestBody = candidate.postData() || '';
    wakeRequest?.();
  };
  const onResponse = response => {
    if (!isConfirmation(response)) return;
    // Count and correlate synchronously, before response.text() can yield.
    if (!request || response.request() !== request || responseSeen) {
      fail('uncorrelated or duplicate schedule confirmation response');
      return;
    }
    responseSeen = true;
    const task = (async () => {
      if (response.status() !== 200) throw new Error('schedule confirmation HTTP failure');
      evidence = scheduleEvidence(requestBody, await response.text(), expected);
    })().catch(error => fail(error.message));
    pending.add(task);
    task.finally(() => pending.delete(task));
  };
  const onFailed = candidate => {
    if (isConfirmation(candidate)) fail('schedule confirmation request failed');
  };
  page.on('request', onRequest);
  page.on('response', onResponse);
  page.on('requestfailed', onFailed);

  function close() {
    closed = true;
    armed = false;
    page.off('request', onRequest);
    page.off('response', onResponse);
    page.off('requestfailed', onFailed);
  }

  return {
    async confirm(click) {
      check();
      if (started || closed) throw new Error('schedule confirmation action reused');
      started = true;
      armed = true;
      requestDeadline = Date.now() + CONFIRM_REQUEST_WAIT_MS;
      const arrived = new Promise(resolve => { wakeRequest = resolve; });
      const timer = setTimeout(() => {
        if (!request) fail('schedule confirmation request timeout');
      }, CONFIRM_REQUEST_WAIT_MS);
      try {
        const clicked = await click();
        check();
        if (!clicked) return clicked;
        // Puppeteer can resolve mouse.click before delivering its network request event.
        // Keep this native action open until that event, without resuming browser work.
        await arrived;
        check();
        return clicked;
      } finally {
        armed = false;
        wakeRequest = undefined;
        clearTimeout(timer);
      }
    },
    async finish(revalidate) {
      try {
        // Drain live work, not one snapshot captured before final browser observations.
        while (pending.size) await Promise.all([...pending]);
        check();
        if (!started || !request || !responseSeen || !evidence) {
          throw new Error('unique verified schedule confirmation unavailable');
        }
        await revalidate();
        // Every subsequent response is a duplicate/uncorrelated and poisons synchronously.
        // No browser await between this check, listener removal and the returned verdict.
        check();
        if (pending.size) throw new Error('schedule evidence changed during final validation');
        return evidence;
      } finally {
        close();
      }
    },
    close,
  };
}

async function verifyScheduleState(root, postingAt) {
  const state = await root.evaluate(element => {
    if (!element.isConnected) throw new Error('composer replaced');
    const visible = el => {
      const box = el.getBoundingClientRect();
      return box.width > 0 && box.height > 0;
    };
    const buttons = [...element.querySelectorAll('button')]
      .filter(button => button.innerText.trim() === 'Schedule' && visible(button));
    const labels = [...element.querySelectorAll('*')].filter(el =>
      el.children.length === 0 && /^Posting at /.test((el.textContent || '').trim()) && visible(el));
    return {ready:buttons.length === 1 && !buttons[0].disabled,
      labels:labels.map(el => el.textContent.trim())};
  });
  if (!state.ready || state.labels.length !== 1 || state.labels[0] !== postingAt) {
    throw new Error('final composer schedule state changed');
  }
}

module.exports = {observeSchedule, verifyScheduleState};
