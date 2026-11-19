// Private Linux positional cleanup cell. Existing worker owns this through channel close.
const fs = require('node:fs');
const NS = 1000000000n;
const MAGIC = Buffer.from([0x42,0x32,0x43,0x4c,0x4e,0x55,0x50,1]);
const min = (...values) => values.reduce((a,b) => a < b ? a : b);
const max = (a,b) => a > b ? a : b;
const now = () => process.hrtime.bigint();

function unsigned(text, maximum) {
  if (typeof text !== 'string' || !/^(0|[1-9][0-9]{0,19})$/.test(text)) {
    throw Error('invalid private cleanup integer');
  }
  const value = BigInt(text);
  if (value > maximum) throw Error('private cleanup integer exceeded');
  return value;
}

function transfer(fd, expiry) {
  let interruptions = 0;
  const exact = (buffer, position, write) => {
    let offset = 0;
    while (offset < buffer.length) {
      let size;
      try {
        size = (write ? fs.writeSync : fs.readSync)(
          fd, buffer, offset, buffer.length-offset, position+offset);
      } catch (error) {
        if (error.code !== 'EINTR') throw error;
        if (++interruptions > 8 || now() >= expiry) throw Error('cleanup control EINTR budget exhausted');
        continue;
      }
      if (size <= 0 || size > buffer.length-offset) throw Error('cleanup control short/zero transfer');
      offset += size;
      if (offset < buffer.length && now() >= expiry) throw Error('cleanup control transfer deadline expired');
    }
    return buffer;
  };
  return {read:(length,position)=>exact(Buffer.alloc(length),position,false),
    write:(buffer,position)=>exact(buffer,position,true)};
}

class CaptureControl {
  constructor(fd, expiry, nonce, policy) {
    this.fd=fd; this.expiry=expiry; this.policy=Object.freeze(policy);
    this.header=Buffer.alloc(32); MAGIC.copy(this.header);
    this.header.writeBigUInt64LE(expiry,8); Buffer.from(nonce,'hex').copy(this.header,16);
    this.epoch=null; this.aborted=false; this.error=null; this.cleanupEntry=null;
    this.limits=[expiry-5n*NS,expiry-3n*NS,expiry];
    this.seen=[[0,null],[0,null],[0,null]];
    this.guards=new Set(); this.abortHook=null; this.ticking=false;
    this.publishing=false; this.pendingAbort=false;
    this.read();
    if (this.seen[2][0] !== 0) throw Error('cleanup role already published');
    transfer(fd,expiry).write(Buffer.alloc(1),127);
    this.timer=setInterval(()=>this.tick(),25);
  }

  backing() {
    const info=fs.fstatSync(this.fd);
    const fields=fs.readFileSync(`/proc/self/fdinfo/${this.fd}`,'utf8');
    const match=/^flags:\s+([0-7]+)$/m.exec(fields);
    const flags=match ? Number.parseInt(match[1],8) : -1;
    if (!info.isFile() || info.nlink!==0 || info.size!==128 ||
        (flags & 3)!==2 || (flags & fs.constants.O_APPEND) ||
        fs.readlinkSync(`/proc/self/fd/${this.fd}`)!=='/memfd:b2-capture-cleanup (deleted)') {
      throw Error('invalid cleanup control backing');
    }
  }

  tighten(epoch) {
    this.epoch=this.epoch===null ? epoch : min(this.epoch,epoch);
    const t=min(this.epoch+this.policy[0],this.expiry-5n*NS);
    const k=min(t+this.policy[1],this.expiry-3n*NS);
    const o=min(k+this.policy[2],this.expiry);
    this.limits=this.limits.map((old,index)=>min(old,[t,k,o][index]));
  }

  read() {
    this.backing();
    const io=transfer(this.fd,this.expiry);
    if (!io.read(32,0).equals(this.header)) throw Error('cleanup control binding changed');
    for (const [index,base] of [32,64,96].entries()) {
      const first=io.read(1,base+8)[0], payload=io.read(32,base), last=io.read(1,base+8)[0];
      const [previous,epoch]=this.seen[index];
      if (first>2 || last>2 || first<previous || last<first ||
          !payload.subarray(9).equals(Buffer.alloc(23))) throw Error('invalid cleanup committed state');
      if (!first) continue;
      const value=payload.readBigUInt64LE();
      if (value<max(1n,this.expiry-300n*NS) || value>now() || (epoch!==null && epoch!==value)) {
        throw Error('invalid cleanup committed epoch');
      }
      this.seen[index]=[last,value]; this.tighten(value); this.aborted ||= last===2;
    }
  }

  fail(error) {
    if (!this.error) {
      this.error=Error(`cleanup control unknown: ${error.message}`,{cause:error});
      this.error.cleanupUnknown=true;
      this.tighten(now());
    }
    this.aborted=true;
  }

  observe() {
    if (!this.error && !this.publishing) {try {this.read();} catch(error) {this.fail(error);}}
    return this.limits;
  }

  begin(abort=false) {
    // Entry is known before I/O; failures must not grant a fresh budget.
    this.tighten(now());
    this.pendingAbort ||= abort;
    if (this.publishing) return;
    this.observe();
    if (this.error) return;
    this.publishing=true;
    try {
      const io=transfer(this.fd,this.expiry);
      let [state,epoch]=this.seen[2];
      if (!state) {
        epoch=this.epoch;
        const encoded=Buffer.alloc(8); encoded.writeBigUInt64LE(epoch);
        io.write(encoded,96);
        state=this.pendingAbort ? 2 : 1; io.write(Buffer.from([state]),104);
        this.seen[2]=[state,epoch]; this.tighten(epoch);
      }
      if (state===1 && this.pendingAbort) {io.write(Buffer.from([2]),104);this.seen[2]=[2,epoch];}
      this.aborted ||= this.pendingAbort;
    } catch(error) {this.fail(error);}
    finally {this.publishing=false;}
  }

  startCleanup() {
    this.begin();
    if (this.cleanupEntry===null) this.cleanupEntry=now();
  }

  workEnd() {return min(this.expiry-15n*NS,this.limits[0]);}

  browserEnd() {
    const available=max(0n,this.limits[0]-this.cleanupEntry);
    return this.limits[0]-min(NS,available/10n);
  }

  check() {
    this.observe();
    if (this.aborted) throw this.error || Error('capture peer aborted');
    if (now()>=this.workEnd()) {this.begin(true);throw Error('capture work deadline expired');}
  }

  bindAbort(callback) {
    this.abortHook=callback;
    this.tick();
  }

  tick() {
    if (this.ticking || this.fd===null) return;
    this.ticking=true;
    try {
      this.observe();
      if (this.aborted && this.abortHook) this.abortHook(this.error || Error('capture peer aborted'));
      for (const guard of [...this.guards]) guard.update();
    } finally {this.ticking=false;}
  }

  settle(operation,{phase='work',share=1,until=null,reserve=15,interrupted=null}={}) {
    const entry=now();
    if (phase!=='work' && this.cleanupEntry===null) this.startCleanup();
    const candidate=()=>{
      let end=phase==='work' ? min(this.workEnd(),this.expiry-BigInt(reserve)*NS) :
        phase==='browser' ? this.browserEnd() : this.limits[0];
      if (until!==null) end=min(end,until);
      return entry+(end-entry)/BigInt(share);
    };
    let cutoff=candidate(), timer, done=false;
    return new Promise((resolve,reject)=>{
      const finish=(error,value)=>{
        if (done) return;
        done=true;clearTimeout(timer);this.guards.delete(guard);
        error ? reject(error) : resolve(value);
      };
      const guard={cancel:error=>finish(error),update:()=>{
        if (done) return;
        cutoff=min(cutoff,candidate());
        if (phase==='work' && this.aborted) return finish(this.error || Error('capture peer aborted'));
        const left=cutoff-now();
        if (left<=0n) return finish(Error('capture settlement deadline expired'));
        clearTimeout(timer);
        timer=setTimeout(()=>{this.observe();guard.update();},Math.max(1,Number(left)/1e6));
      }};
      this.guards.add(guard);this.observe();guard.update();
      if (phase==='work' && interrupted) interrupted.catch(error=>finish(error));
      if (done) return;
      Promise.resolve().then(()=>{
        this.observe();guard.update();
        if (!done) return operation();
      }).then(value=>{
        this.observe();guard.update();
        if (!done) finish(null,value);
      },error=>finish(error));
    });
  }

  close() {
    if (this.fd===null) return;
    this.observe();
    clearInterval(this.timer);
    // All registered settlements must have discharged before their owner closes.
    if (this.guards.size) {
      this.fail(Error('control closed with active settlements'));
      for (const guard of [...this.guards]) guard.cancel(this.error);
    }
    const fd=this.fd;this.fd=null;
    try {fs.closeSync(fd);} catch(error) {this.fail(error);}
    if (this.error) throw this.error;
  }
}

function openControl(args) {
  const fd=Number(unsigned(args[0],2147483647n));
  if (fd<3) throw Error('cleanup fd aliases stdio');
  try {
    if (args.length!==7) throw Error('private capture control fields required');
    const expiry=unsigned(args[1],18446744073709551615n);
    if (expiry===0n || !/^[0-9a-f]{32}$/.test(args[2]) || args[3]!=='node') {
      throw Error('invalid private cleanup binding');
    }
    const policy=args.slice(4).map((v,i)=>unsigned(v,[10n*NS,2n*NS,2n*NS][i]));
    return new CaptureControl(fd,expiry,args[2],policy);
  } catch(error) {fs.closeSync(fd);throw error;}
}

module.exports={openControl};
