// Page-local current-state reader. No store getter, expression evaluator or setter runs.
function instantReader(root) {
  let active = true, retained;
  const names = ['ShareBoxscheduledPublishTime','ShareBoxshareLifeCycleState','ShareBoxshareBoxMode'];
  const fail = message => { throw Error(`current full-instant ${message}`); };
  const own = (value, key) => {
    const descriptor = value && Object.getOwnPropertyDescriptor(value, key);
    if (descriptor && !('value' in descriptor)) fail('accessor unsupported');
    return descriptor?.value;
  };
  const visible = node => {
    if (!node?.isConnected || !node.checkVisibility({
      visibilityProperty:true,opacityProperty:true,contentVisibilityAuto:true,
    })) return false;
    const box=node.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  };
  function fields(value, required, optional = []) {
    if (!value || Object.getPrototypeOf(value) !== Object.prototype) fail('record prototype');
    const keys = Reflect.ownKeys(value);
    if (keys.some(key => typeof key !== 'string' || ![...required,...optional].includes(key)) ||
        required.some(key => !keys.includes(key))) fail('record fields');
    for (const key of keys) own(value, key);
  }
  function epoch(store) {
    const map = own(store,'store');
    if (!map || Object.getPrototypeOf(map) !== Map.prototype) fail('backing map unavailable');
    const values = names.map((name,index) => {
      const record = Map.prototype.get.call(map,`sdui_${name}_MemoryNamespace`);
      fields(record,['key','value','internalValue','originalProtoCase','updateSource','lastUpdateTimestamp'],
        ['optimisticValue','committedState','shouldForceEvaluateOnGet']);
      fields(record.key,['namespace','key','isEncrypted']);
      fields(record.key.key,['$type','value']);
      fields(record.key.key.value,['$case','id']);
      if (record.key.namespace !== 'MemoryNamespace' || record.key.isEncrypted !== false ||
          record.key.key.$type !== 'proto.sdui.Key' || record.key.key.value.$case !== 'id' ||
          record.key.key.value.id !== name) fail('record key');
      if (record.optimisticValue !== undefined || record.committedState !== undefined ||
          record.shouldForceEvaluateOnGet !== undefined) fail('state overlay');
      if (record.originalProtoCase !== (index ? 'stringValue' : 'signedLongValue') ||
          record.updateSource !== 'setStateAction' ||
          !Number.isFinite(record.lastUpdateTimestamp) ||
          record.value !== record.internalValue) fail('state representation');
      return record.value;
    });
    if (typeof values[0] !== 'bigint' || values[0] <= 0n ||
        values[0] > BigInt(Number.MAX_SAFE_INTEGER) ||
        values[1] !== 'ShareLifeCycleState_SCHEDULED' || values[2] !== 'Scheduled') {
      fail('state value');
    }
    return {map,value:Number(values[0])};
  }
  function resolve() {
    let work = 0;
    const step = () => { if (++work > 100000) fail('inspection budget'); };
    function list(first, next, limit) {
      const result = [], seen = new Set();
      for (let item=first; item; item=item[next]) {
        step();
        if (seen.has(item) || result.length >= limit) {
          fail(`${next} traversal ${seen.has(item) ? 'cycle' : 'truncated'} at ${result.length}/${limit}`);
        }
        seen.add(item); result.push(item);
      }
      return result;
    }
    function path(node) {
      const keys=Object.keys(node).filter(key=>key.startsWith('__reactFiber$'));
      if (keys.length !== 1) fail('host fiber unavailable');
      const attached=own(node,keys[0]), paths=[];
      for (const candidate of new Set([attached,attached?.alternate].filter(Boolean))) {
        if (candidate.tag !== 5 || candidate.stateNode !== node) fail('host ownership');
        const nodes=list(candidate,'return',256);
        const top=nodes.at(-1);
        if (top?.tag !== 3 || top.stateNode?.current !== top) continue;
        let member=true;
        for (let i=0;i<nodes.length-1;i++) {
          if (!list(nodes[i+1].child,'sibling',1024).includes(nodes[i])) member=false;
        }
        if (member) paths.push({nodes,owner:top.stateNode});
      }
      if (paths.length !== 1) fail('committed host path ambiguous');
      return paths[0];
    }
    function state(path) {
      const contexts=new Set(), consumers=[];
      for (const node of path.nodes) {
        const local=new Set();
        for (const dep of list(node.dependencies?.firstContext,'next',4096)) {
          const value=dep.memoizedValue;
          if (value && typeof own(value,'getStore') === 'function') {
            contexts.add(value); local.add(value);
          }
        }
        if (local.size) consumers.push(node);
      }
      if (contexts.size !== 1) fail('store context ambiguous');
      const stores=new Set();
      for (const node of consumers) {
        for (const hook of list(node.memoizedState,'next',4096)) {
          const memo=own(hook,'memoizedState');
          if (!Array.isArray(memo) || !Array.isArray(memo[1])) continue;
          if (memo[1].length > 512) fail('dependency budget');
          for (const dependency of memo[1]) {
            step();
            if (dependency && typeof dependency === 'object' &&
                own(dependency,'store') instanceof Map) stores.add(dependency);
          }
        }
      }
      if (stores.size !== 1) fail('existing store ambiguous');
      return {context:[...contexts][0],store:[...stores][0]};
    }
    if (!visible(root)) fail('composer disconnected or hidden');
    const editors=[...root.ownerDocument.querySelectorAll(
      '[componentkey="ShareBox_textEditor"].ProseMirror[contenteditable="true"]')].filter(visible);
    if (editors.length !== 1 || !root.contains(editors[0])) fail('unique owned editor required');
    const controls=[...root.querySelectorAll('button')].filter(node=>
      visible(node) && node.innerText.trim()==='Schedule' && !node.disabled);
    if (controls.length !== 1 || !root.contains(controls[0])) fail('unique owned Schedule required');
    const control=controls[0], left=path(root), right=path(control);
    if (left.owner !== right.owner) fail('different React owners');
    const a=state(left),b=state(right);
    if (a.context !== b.context || a.store !== b.store) fail('different store owners');
    const {map,value}=epoch(a.store);
    return {control,owner:left.owner,context:a.context,store:a.store,map,value};
  }
  function read() {
    if (!active) fail('reader closed');
    const current=resolve();
    if (retained && ['control','owner','context','store','map'].some(
      key=>current[key] !== retained[key])) fail('retained ownership changed');
    retained=current;
    return current.value;
  }
  read();
  return {read,close:()=>{active=false;retained=null;root=null;}};
}

module.exports = {instantReader};
