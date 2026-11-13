/* Sequential polling only; authorization and workflow remain server-owned. */
(function(root){
  'use strict';
  function createPoll(work, {interval=1500, hiddenInterval=15000, timeout=12000, onError=()=>{}}={}) {
    let running=false, timer=null, flight=null, controller=null, generation=0, failures=0, pending=false, resume=false, refreshFlight=null;
    const hidden=()=>!!root.document?.hidden;
    function schedule(delay) { clearTimeout(timer); if(running) timer=setTimeout(run,delay); }
    function run() {
      clearTimeout(timer);
      if(!running)return Promise.resolve();
      if(flight){pending=true;return flight;}
      const epoch=generation, abort=new AbortController(); controller=abort;
      const deadline=setTimeout(()=>abort.abort(Object.assign(new Error('Request timeout'),{name:'TimeoutError'})),timeout);
      flight=Promise.resolve().then(()=>work(abort.signal)).then(()=>{if(epoch===generation)failures=0;})
        .catch(error=>{if(epoch===generation&&running){failures++;onError(error);}})
        .finally(()=>{
          clearTimeout(deadline);
          if(epoch!==generation)return;
          flight=null;controller=null;
          const immediate=pending;pending=false;
          schedule(immediate?0:hidden()?hiddenInterval:Math.min(20000,interval*Math.pow(2,failures)));
        });
      return flight;
    }
    const api={
      start(){if(!running){running=true;return run();}return flight||Promise.resolve();},
      refresh(){
        if(!flight)return run();
        if(!refreshFlight){const epoch=generation;
          refreshFlight=flight.then(()=>{if(epoch!==generation)return;refreshFlight=null;return run();});}
        return refreshFlight;
      },
      stop(){running=false;resume=false;generation++;pending=false;clearTimeout(timer);controller?.abort();controller=null;flight=null;refreshFlight=null;},
      dispose(){api.stop();root.document?.removeEventListener('visibilitychange',visibility);root.removeEventListener?.('pagehide',hide);root.removeEventListener?.('pageshow',show);},
      get running(){return running;}
    };
    function visibility(){if(running){if(!hidden())run();else if(!flight)schedule(hiddenInterval);}}
    // pagehide covers navigation and BFCache; pageshow resumes only an active poll.
    function hide(){const active=running;api.stop();resume=active;}
    function show(event){if(event.persisted&&resume)api.start();}
    root.document?.addEventListener('visibilitychange',visibility);
    root.addEventListener?.('pagehide',hide);
    root.addEventListener?.('pageshow',show);
    return api;
  }
  root.PetroLive={createPoll};
  if(typeof module!=='undefined')module.exports=root.PetroLive;
})(typeof window==='undefined'?globalThis:window);
