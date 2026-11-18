// Self-contained page reader factory. Ownership comes from actual DOM/React references,
// never names, document-wide radio selection, generated classes or ancestor indices.
function actorReaders() {
function actorControl(root) {
  if (!root.isConnected) throw new Error('composer replaced');
  const matches = [...root.querySelectorAll('[role="button"][aria-expanded]')].filter(control => {
    const keys = Object.keys(control).filter(k => k.startsWith('__reactFiber$'));
    if (keys.length !== 1) return false;
    let fiber = control[keys[0]];
    for (let n=0; fiber && n<12; n++, fiber=fiber.return) {
      const view = fiber.memoizedProps?.viewName;
      if (view) return view === 'share-view-actor-list';
    }
    return false;
  });
  if (matches.length !== 1) throw new Error('unique actor control required');
  return matches[0];
}

function ownedActorPopup(root, control) {
  if (!root.isConnected || !control.isConnected || !root.contains(control) ||
      control.getAttribute('aria-expanded') !== 'true') throw new Error('actor control invalidated');
  const anchors = [...control.parentElement.children]
    .filter(e => e !== control && e.matches('[data-menu-portal-anchor]'));
  if (anchors.length !== 1 || !root.contains(anchors[0])) throw new Error('actor portal ownership unavailable');
  const owners = [...anchors[0].querySelectorAll('[aria-owns]')];
  if (owners.length !== 1) throw new Error('actor portal ownership ambiguous');
  const id = owners[0].getAttribute('aria-owns');
  if (!id || /\s/.test(id)) throw new Error('unsupported actor portal identifier');
  const portal = root.ownerDocument.getElementById(id);
  if (!portal || !root.closest('dialog[open]')?.contains(portal)) throw new Error('actor portal outside composer');
  const popups = [...portal.querySelectorAll('[popover][data-floating-ui-focusable]')];
  if (popups.length !== 1) throw new Error('actor popup ambiguous');
  const popup = popups[0];
  if (!popup.isConnected || !popup.matches(':popover-open') ||
      !popup.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) throw new Error('actor popup hidden');
  const keys = Object.keys(popup).filter(k => k.startsWith('__reactFiber$'));
  if (keys.length !== 1) throw new Error('actor popup renderer unavailable');
  let fiber = popup[keys[0]];
  for (let n=0; fiber && n<16; n++, fiber=fiber.return) {
    const props = fiber.memoizedProps;
    if (props && Object.hasOwn(props, 'isOpen') &&
        props.context?.refs?.reference && props.context?.refs?.floating) {
      if (props.isOpen !== true || props.context.refs.reference.current !== control ||
          props.context.refs.floating.current !== popup) throw new Error('actor popup ownership mismatch');
      return popup;
    }
  }
  throw new Error('actor popup ownership unavailable');
}

function actorVisible(radio) {
  if (!radio.isConnected || radio.closest('[inert]')) return false;
  const labels = [...radio.parentElement.querySelectorAll('label')].filter(e => e.htmlFor === radio.id);
  return labels.length === 1 && labels[0].getBoundingClientRect().width > 0 &&
    labels[0].getBoundingClientRect().height > 0 &&
    labels[0].checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
}

function actorOption(radio) {
  if (!radio.isConnected || radio.disabled) throw new Error('actor option unavailable');
  const keys = Object.keys(radio).filter(k => k.startsWith('__reactFiber$'));
  if (keys.length !== 1) throw new Error('unsupported actor renderer');
  let fiber = radio[keys[0]];
  if (fiber.memoizedProps?.checked !== radio.checked) throw new Error('stale actor state');
  let context = false;
  for (let n = 0; fiber && n < 40; n++, fiber = fiber.return) {
    const props = fiber.memoizedProps;
    if (props?.viewName === 'share-actor-select') context = true;
    const id = props?.selectedStateKey?.key?.value?.id;
    if (id?.startsWith('ShareBoxactorState_')) {
      if (!context || !/^ShareBoxactorState_Self_(Self|[0-9]+)$/.test(id)) {
        throw new Error('unsupported actor binding');
      }
      return {key: id, checked: radio.checked};
    }
  }
  throw new Error('actor binding unavailable');
}

function selection(root, control) {
  // One synchronous browser evaluation: no render can interleave ownership,
  // membership, checked properties and option bindings.
  const popup = ownedActorPopup(root, control);
  const radios = [...popup.querySelectorAll('input[type="radio"]')];
  const options = radios.map(radio => {
    if (!popup.contains(radio) || !actorVisible(radio)) throw new Error('actor option hidden or moved');
    return actorOption(radio);
  });
  if (!options.length || new Set(options.map(o=>o.key)).size !== options.length) {
    throw new Error('actor options ambiguous');
  }
  const selected = options.filter(o=>o.checked);
  if (selected.length !== 1 || selected[0].key !== 'ShareBoxactorState_Self_Self') {
    throw new Error('selected composer actor is not authenticated personal account');
  }
  return {selected_actor_key:selected[0].key, checked_count:1};
}

return {actorControl, ownedActorPopup, actorOption, actorVisible, selection};
}

module.exports = {actorReaders, ...actorReaders()};
