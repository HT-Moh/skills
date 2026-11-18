const test = require('node:test');
const assert = require('node:assert/strict');
const {instantReader} = require('../social/linkedin-post/scripts/ws_exact_instant');

const names = ['ShareBoxscheduledPublishTime','ShareBoxshareLifeCycleState','ShareBoxshareBoxMode'];
const key = name => `sdui_${name}_MemoryNamespace`;
function fixture() {
  const values = [1795505400000n,'ShareLifeCycleState_SCHEDULED','Scheduled'];
  const records = names.map((name,i)=>({
    key:{namespace:'MemoryNamespace',key:{$type:'proto.sdui.Key',value:{$case:'id',id:name}},
      isEncrypted:false},
    value:values[i],internalValue:values[i],optimisticValue:undefined,committedState:undefined,
    shouldForceEvaluateOnGet:undefined,originalProtoCase:i?'stringValue':'signedLongValue',
    updateSource:'setStateAction',lastUpdateTimestamp:1795032863782,
  }));
  const store = {store:new Map(names.map((name,i)=>[key(name),records[i]]))};
  const context = {getStore(){throw Error('getter must never be invoked');}};
  const visible = {isConnected:true,checkVisibility:()=>true,
    getBoundingClientRect:()=>({width:100,height:30})};
  const editor = {...visible};
  const control = {...visible,innerText:'Schedule',disabled:false};
  const root = {...visible,contains:n=>[editor,control].includes(n),
    querySelectorAll:s=>s==='button'?[control]:[editor]};
  root.ownerDocument = {querySelectorAll:()=>[editor]};
  const top = {tag:3,return:null};
  top.stateNode={current:top};
  const owner = {tag:0,return:top,dependencies:{firstContext:{memoizedValue:context,next:null}},
    memoizedState:{memoizedState:[()=>{},[store]],next:null}};
  top.child=owner;
  const host = {tag:5,stateNode:root,return:owner};
  owner.child=host;
  const button = {tag:5,stateNode:control,return:host};
  host.child=button;
  root.__reactFiber$x=host;
  control.__reactFiber$x=button;
  return {root,control,editor,store,context,owner,top,host,button,records};
}

test('reads existing native store without invoking getter, returns current full epoch',()=>{
  const f=fixture(),reader=instantReader(f.root);
  assert.equal(reader.read(),1795505400000);
  f.records[0].value=f.records[0].internalValue=1827041400000n;
  assert.equal(reader.read(),1827041400000,'same wall-clock label cannot pin old year');
  reader.close();
  assert.throws(()=>reader.read(),/closed/);
});

test('resolves committed alternate rather than stale attached host ancestry',()=>{
  const f=fixture();
  const stale={...f.host,alternate:f.host};
  f.host.alternate=stale;
  f.root.__reactFiber$x=stale;
  assert.equal(instantReader(f.root).read(),1795505400000);
});

for(const [name,mutate] of [
  ['detached root',f=>f.root.isConnected=false],
  ['hidden root',f=>f.root.checkVisibility=()=>false],
  ['detached control',f=>f.control.isConnected=false],
  ['disabled control',f=>f.control.disabled=true],
  ['duplicate control',f=>f.root.querySelectorAll=s=>s==='button'?[f.control,{...f.control}]:[f.editor]],
  ['duplicate editor',f=>f.root.ownerDocument.querySelectorAll=()=>[f.editor,{...f.editor}]],
  ['unowned editor',f=>f.root.contains=()=>false],
  ['uncommitted ancestry',f=>f.top.stateNode.current={}],
  ['broken membership',f=>f.owner.child={}],
  ['cycle',f=>f.owner.return=f.host],
  ['wrong host node',f=>f.host.stateNode={}],
  ['context cycle',f=>f.owner.dependencies.firstContext.next=f.owner.dependencies.firstContext],
  ['hook cycle',f=>f.owner.memoizedState.next=f.owner.memoizedState],
  ['absent store',f=>f.owner.memoizedState.memoizedState[1]=[]],
  ['ambiguous stores',f=>f.owner.memoizedState.memoizedState[1].push({store:new Map(f.store.store)})],
  ['ambiguous contexts',f=>f.owner.dependencies.firstContext.next={memoizedValue:{getStore(){}},next:null}],
  ['missing record',f=>f.store.store.delete(key(names[0]))],
  ['numeric epoch',f=>f.records[0].value=f.records[0].internalValue=1795505400000],
  ['unsafe epoch',f=>f.records[0].value=f.records[0].internalValue=9007199254740993n],
  ['different internal epoch',f=>f.records[0].internalValue=1795505400001n],
  ['optimistic epoch',f=>f.records[0].optimisticValue=1795505400000n],
  ['committed overlay',f=>f.records[0].committedState={}],
  ['forced expression',f=>f.records[0].shouldForceEvaluateOnGet=true],
  ['expression',f=>f.records[0].expression={}],
  ['dirty flag',f=>f.records[0].isDirty=false],
  ['encryption',f=>f.records[0].key.isEncrypted=true],
  ['wrong namespace',f=>f.records[0].key.namespace='Other'],
  ['wrong key',f=>f.records[0].key.key.value.id='Other'],
  ['wrong case',f=>f.records[0].originalProtoCase='stringValue'],
  ['unknown field',f=>f.records[0].futureState=true],
  ['symbol field',f=>f.records[0][Symbol('hidden')]=true],
  ['unexpected prototype',f=>Object.setPrototypeOf(f.records[0],{hidden:true})],
  ['null optimistic',f=>f.records[0].optimisticValue=null],
  ['wrong lifecycle',f=>f.records[1].value=f.records[1].internalValue='DRAFT'],
  ['wrong mode',f=>f.records[2].value=f.records[2].internalValue='Post'],
  ['invalid timestamp',f=>f.records[0].lastUpdateTimestamp=NaN],
  ['wrong update source',f=>f.records[0].updateSource='unknown'],
]) test(`refuses ${name}`,()=>{
  const f=fixture();mutate(f);
  assert.throws(()=>instantReader(f.root).read());
});

test('record accessors refuse without execution',()=>{
  const f=fixture();let reads=0;
  Object.defineProperty(f.records[0],'value',{get(){reads++;return 1795505400000n;}});
  assert.throws(()=>instantReader(f.root).read());
  assert.equal(reads,0);
});

for(const [name,mutate] of [
  ['context',f=>f.owner.dependencies.firstContext.memoizedValue={getStore(){}}],
  ['store',f=>f.owner.memoizedState.memoizedState[1]=[{store:f.store.store}]],
  ['map',f=>f.store.store=new Map(f.store.store)],
  ['control',f=>{const next={...f.control};f.root.querySelectorAll=s=>s==='button'?[next]:[f.editor];}],
]) test(`refuses replaced ${name} even with matching epoch`,()=>{
  const f=fixture(),reader=instantReader(f.root);
  reader.read();mutate(f);
  assert.throws(()=>reader.read());
});

test('unfinished ancestor traversal refuses instead of accepting early matching context',()=>{
  const f=fixture();
  let below=f.owner;
  for(let i=0;i<300;i++) {
    const parent={tag:0,child:below};below.return=parent;below=parent;
  }
  below.return=f.top;f.top.child=below;
  assert.throws(()=>instantReader(f.root).read());
});

test('legitimate committed alternate flip keeps retained DOM/store ownership',()=>{
  const f=fixture(),reader=instantReader(f.root);
  const next={...f.host,alternate:f.host};
  f.host.alternate=next;
  f.owner.child=next;f.button.return=next;
  assert.equal(reader.read(),1795505400000);
});

test('same store/context cannot qualify a control in a different React root',()=>{
  const f=fixture();
  const top={tag:3,return:null};top.stateNode={current:top};
  const owner={...f.owner,return:top,child:f.button};
  top.child=owner;f.button.return=owner;
  assert.throws(()=>instantReader(f.root).read(),/React owners/);
});

test('unfinished native hook list refuses even after finding matching store',()=>{
  const f=fixture();
  let current=f.owner.memoizedState;
  for(let i=0;i<4100;i++) current=current.next={memoizedState:null,next:null};
  assert.throws(()=>instantReader(f.root).read(),/truncated/);
});

test('unfinished context list refuses even after finding matching context',()=>{
  const f=fixture();
  let current=f.owner.dependencies.firstContext;
  for(let i=0;i<4100;i++) current=current.next={memoizedValue:{},next:null};
  assert.throws(()=>instantReader(f.root).read(),/truncated/);
});

test('complete context chain beyond old256 bound remains supported',()=>{
  const f=fixture();
  let current=f.owner.dependencies.firstContext;
  for(let i=0;i<650;i++) current=current.next={memoizedValue:f.context,next:null};
  assert.equal(instantReader(f.root).read(),1795505400000);
  current.next={memoizedValue:{getStore(){}},next:null};
  assert.throws(()=>instantReader(f.root).read(),/ambiguous/);
});

for(const part of ['root','control','editor']) {
  test(`zero-height ${part} cannot establish current composer`,()=>{
    const f=fixture();
    f[part].getBoundingClientRect=()=>({width:100,height:0});
    assert.throws(()=>instantReader(f.root).read());
  });
  test(`CSS-hidden ${part} requires explicit visibility checking`,()=>{
    const f=fixture();
    f[part].checkVisibility=options=>!options?.visibilityProperty;
    assert.throws(()=>instantReader(f.root).read());
  });
}

module.exports={fixture};
