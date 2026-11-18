const test = require('node:test');
const assert = require('node:assert/strict');
const {actorControl, ownedActorPopup} = require('../social/linkedin-post/scripts/ws_exact_actor');

function fixture() {
  const dialog = {contains:e=>e===portal};
  const root = {isConnected:true, contains:e=>e===control||e===anchor,
    closest:()=>dialog, querySelectorAll:()=>[control]};
  const control = {isConnected:true, getAttribute:()=> 'true',
    __reactFiber$x:{memoizedProps:{viewName:'share-view-actor-list'},return:null}};
  const popup = {isConnected:true, matches:()=>true, checkVisibility:()=>true,
    __reactFiber$x:{memoizedProps:{isOpen:true,context:{refs:{
      reference:{current:control},floating:{current:null}}}},return:null}};
  popup.__reactFiber$x.memoizedProps.context.refs.floating.current=popup;
  const portal = {id:'portal-1', querySelectorAll:()=>[popup]};
  const owner = {getAttribute:()=> 'portal-1'};
  const anchor = {matches:()=>true,querySelectorAll:()=>[owner]};
  control.parentElement={children:[control,anchor]};
  root.ownerDocument={getElementById:id=>id==='portal-1'?portal:null};
  return {root,control,popup,portal,anchor,owner};
}

test('semantic actor control excludes other expandable controls',()=>{
  const f=fixture();
  assert.equal(actorControl(f.root),f.control);
  f.root.querySelectorAll=()=>[f.control,f.control];
  assert.throws(()=>actorControl(f.root),/unique actor control/);
});

test('popup must belong to concrete composer control and live portal',()=>{
  const f=fixture();
  assert.equal(ownedActorPopup(f.root,f.control),f.popup);
  f.popup.__reactFiber$x.memoizedProps.context.refs.reference.current={};
  assert.throws(()=>ownedActorPopup(f.root,f.control),/ownership/);
});

for(const [name,mutate] of [
  ['detached composer',f=>f.root.isConnected=false],
  ['closed control',f=>f.control.getAttribute=()=> 'false'],
  ['hidden but sized popup',f=>f.popup.checkVisibility=()=>false],
  ['stale popup',f=>f.popup.matches=()=>false],
  ['wrong portal',f=>f.root.ownerDocument.getElementById=()=>null],
  ['ambiguous anchors',f=>f.control.parentElement.children.push(f.anchor)],
]) test(`rejects ${name}`,()=>{
  const f=fixture();mutate(f);
  assert.throws(()=>ownedActorPopup(f.root,f.control));
});

test('readActor uses only owned popup radios; unrelated document radios cannot qualify',async()=>{
  const {readActor} = require('../social/linkedin-post/scripts/ws_exact_dom');
  const f=fixture();
  let expanded='false',globalRadioQueries=0;
  f.control.getAttribute=()=>expanded;
  f.control.click=async()=>{expanded='true';};
  f.control.evaluate=async fn=>fn(f.control);
  f.control.dispose=async()=>{};
  f.root.evaluate=async fn=>fn(f.root);
  const label={htmlFor:'radio-1',getBoundingClientRect:()=>({width:24,height:24}),
    checkVisibility:()=>true};
  const radio={id:'radio-1',isConnected:true,disabled:false,checked:true,closest:()=>null,
    parentElement:{querySelectorAll:()=>[label]},
    __reactFiber$x:{memoizedProps:{checked:true},return:{
      memoizedProps:{viewName:'share-actor-select'},return:{
        memoizedProps:{selectedStateKey:{key:{value:{id:'ShareBoxactorState_Self_Self'}}}}}}}};
  let owned=[radio];
  f.popup.$$=async()=>owned;
  f.popup.querySelectorAll=()=>owned;
  f.popup.contains=radio=>owned.includes(radio);
  const handle=value=>({asElement:()=>value,value,dispose:async()=>{},
    evaluate:async(fn,...args)=>fn(value,...args),
    evaluateHandle:async(fn,...args)=>handle(fn(value,...args))});
  const page={
    evaluate:async(fn,...args)=>fn(...args),
    evaluateHandle:async(fn,...args)=>handle(fn(...args)),
    waitForFunction:async(fn,_options,...args)=>assert.equal(fn(...args),true),
    keyboard:{press:async()=>{expanded='false';}},
  };
  // Puppeteer resolves handles before page evaluation.
  page.evaluate=async(fn,...args)=>fn(...args.map(arg=>arg?.value||arg));
  const previous=global.document;
  global.document={querySelectorAll:selector=>{
    if(selector.includes('shareboxProfilePictureComponentRef'))
      return [{href:'https://www.linkedin.com/in/example-member/'}];
    globalRadioQueries++; return [radio];
  }};
  try {
    const result=await readActor(page,f.root);
    assert.equal(result.account_url,'https://www.linkedin.com/in/example-member/');
    assert.equal(globalRadioQueries,0);
    page.evaluate=async(fn,...args)=>{
      const value=fn(...args.map(arg=>arg?.value||arg));
      // A render commits between CDP calls after the personal option was sampled.
      if(fn.name==='actorOption') {
        radio.isConnected=false;
        owned=[{...radio,isConnected:true,
          __reactFiber$x:{memoizedProps:{checked:true},return:{
            memoizedProps:{viewName:'share-actor-select'},return:{
              memoizedProps:{selectedStateKey:{key:{value:{id:'ShareBoxactorState_Self_123'}}}}}}}}];
      }
      return value;
    };
    try {
      const observed=await readActor(page,f.root);
      assert.equal(observed.selected_actor_key,
        owned[0].__reactFiber$x.return.return.memoizedProps.selectedStateKey.key.value.id,
        'receipt must represent current options, not a detached personal option');
    } catch(error) {
      if(error.code==='ERR_ASSERTION') throw error;
      assert.match(error.message,/actor/);
    }
    expanded='false';
    let replaced=false;
    page.evaluateHandle=async(fn,...args)=>{
      const result=handle(fn(...args));
      result.evaluate=async(fn,...args)=>{
        replaced=true;
        owned=[{...radio,isConnected:true,
          __reactFiber$x:{memoizedProps:{checked:true},return:{
            memoizedProps:{viewName:'share-actor-select'},return:{
              memoizedProps:{selectedStateKey:{key:{value:{id:'ShareBoxactorState_Self_123'}}}}}}}}];
        return fn(result.value,...args);
      };
      return result;
    };
    await assert.rejects(readActor(page,f.root),/actor is not authenticated personal/);
    assert.equal(replaced,true,'exercise current atomic reader path');
    page.evaluateHandle=async(fn,...args)=>handle(fn(...args));
    expanded='false';
    owned=[];
    await assert.rejects(readActor(page,f.root),/actor options ambiguous/);
    assert.equal(globalRadioQueries,0);
  } finally {global.document=previous;}
});
