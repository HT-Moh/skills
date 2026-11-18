// Version-specific, fail-closed decoding of observed LinkedIn SDUI values.
// Each DOM reader is self-contained so Puppeteer can execute it in the page.
function paragraphText(editor) {
  const lines = [];
  for (const p of editor.childNodes) {
    if (p.nodeType !== 1 || p.tagName !== 'P' || p.hidden ||
        p.getAttribute?.('aria-hidden') === 'true' || p.getAttribute?.('style')) {
      throw new Error('unsupported editor paragraph');
    }
    const nodes = [...p.childNodes];
    if (nodes.length === 1 && nodes[0].tagName === 'BR' &&
        nodes[0].className === 'ProseMirror-trailingBreak') {
      lines.push(''); continue;
    }
    if (!nodes.length || nodes.some(n => n.nodeType !== 3)) {
      throw new Error('unsupported editor inline content');
    }
    lines.push(nodes.map(n => n.textContent).join(''));
  }
  if (!lines.length) throw new Error('unsupported empty editor structure');
  return lines.join('\n');
}

function scheduleEvidence(requestBody, responseBody, expected) {
  if (requestBody.length > 32768 || responseBody.length > 65536) {
    throw new Error('schedule evidence size limit');
  }
  const request = JSON.parse(requestBody);
  if (request.requestId !== 'com.linkedin.sdui.requests.sharing.ConfirmSchedulePost') {
    throw new Error('uncorrelated schedule confirmation');
  }
  const states = request.states;
  function selected(key) {
    const matches = states?.filter(s => s.key === key && s.namespace === 'MemoryNamespace');
    if (matches?.length !== 1) throw new Error('ambiguous schedule selection');
    return matches[0].value;
  }
  const date = selected('schedulePostNameSpaceschedulePostScheduleDate');
  const minutes = selected('schedulePostNameSpaceschedulePostScheduleTime');
  if (!['Create', 'Scheduled'].includes(selected('ShareBoxshareBoxMode'))) {
    throw new Error('existing scheduled-post edit unsupported');
  }
  const [month, day, year] = expected.dateStr.split('/').map(Number);
  const time = /^(\d{1,2}):(\d{2}) (AM|PM)$/.exec(expected.timeStr);
  const wantedMinutes = (Number(time[1]) % 12 + (time[3] === 'PM' ? 12 : 0)) * 60 + Number(time[2]);
  if (date?.year !== year || date?.month !== month || date?.day !== day || minutes !== wantedMinutes) {
    throw new Error('schedule selection mismatch');
  }
  // RSC root only. Never extract a matching number from a conditional/template branch.
  const roots = responseBody.split('\n').filter(line => line.startsWith('0:'));
  if (roots.length !== 1) throw new Error('unsupported schedule response');
  const response = JSON.parse(roots[0].slice(2)).response;
  if (response?.$type !== 'proto.sdui.responses.ServerRequestResponse' ||
      !Array.isArray(response.errors) || response.errors.length || response.isRetryable !== false) {
    throw new Error('schedule confirmation rejected');
  }
  function update(key) {
    const matches = response.completionAction?.actions?.filter(action =>
      action.$type === 'proto.sdui.actions.core.SetState' &&
      action.value?.state?.key?.key?.value?.id === key);
    if (matches?.length !== 1) throw new Error('ambiguous schedule update');
    return matches[0].value.state.value;
  }
  const lifecycle = update('ShareBoxshareLifeCycleState');
  const instant = update('ShareBoxscheduledPublishTime');
  if (lifecycle.$case !== 'stringValue' || lifecycle.stringValue !== 'ShareLifeCycleState_SCHEDULED' ||
      instant.$case !== 'signedLongValue' || instant.signedLongValue !== `$n${expected.epoch_ms}`) {
    throw new Error('server schedule instant mismatch');
  }
  return {epoch_ms: expected.epoch_ms, date: {day, month, year}, minutes,
    source: 'linkedin-confirm-schedule-post-v1'};
}

const {actorOption, actorVisible} = require('./ws_exact_actor');
module.exports = {paragraphText, actorOption, actorVisible, scheduleEvidence};
