/* Speak only through a real Vietnamese voice after user activation. */
(function(root){
  'use strict';
  function orderText(o){
    const digits=['không','một','hai','ba','bốn','năm','sáu','bảy','tám','chín'];
    const letters={A:'a',B:'bê',C:'xê',D:'dê',E:'e',F:'ép',G:'giê',H:'hát',I:'i',J:'giây',K:'ca',L:'e lờ',M:'em mờ',N:'en nờ',O:'ô',P:'pê',Q:'quy',R:'e rờ',S:'ét',T:'tê',U:'u',V:'vê',X:'ích',Y:'i dài',Z:'dét'};
    const plate=String(o.plate||'').toUpperCase().replace(/[A-Z0-9]/g,n=>' '+(digits[Number(n)]||letters[n]||n)+' ').replace(/[-.]/g,' ').replace(/\s+/g,' ').trim();
    const number=n=>Number(n).toLocaleString('vi-VN',{useGrouping:false,maximumFractionDigits:3}).replace(',', ' phẩy ');
    const qty=o.mode==='DO_DAY_BINH'?'đổ đầy bình':o.amount?number(o.amount)+' đồng':o.liters?number(o.liters)+' lít':'đổ đầy bình';
    const fuel={NL000001:'xăng E mười, RON chín mươi lăm',NL000002:'xăng E năm, RON chín mươi hai',NL000003:'dầu đi ê den'}[o.nl_ma]||'nhiên liệu';
    return `Có yêu cầu mới. Xe ${plate||'chưa có biển số'}, ${qty}, ${fuel}.`;
  }
  function create({notice=()=>{},state=()=>{}}={}){
    const synth=root.speechSynthesis;let enabled=true,activated=false,voice=null,busy=false,queue=[],revision=0;
    function voices(){voice=(synth?.getVoices()||[]).find(v=>v.lang.toLowerCase()==='vi-vn')||(synth?.getVoices()||[]).find(v=>/^vi(?:-|$)/i.test(v.lang));
      if(enabled&&activated){notice(voice?'':'Thiết bị chưa có giọng tiếng Việt. Hãy cài/kích hoạt giọng Việt trong hệ điều hành hoặc trình duyệt.');drain();}}
    function drain(){
      if(!enabled||!activated||busy||!voice||!queue.length)return;
      const utter=new root.SpeechSynthesisUtterance(queue.shift()),version=revision;
      utter.voice=voice;utter.lang='vi-VN';utter.rate=0.95;utter.pitch=1;
      busy=true;
      utter.onend=()=>{if(version===revision){busy=false;drain();}};
      utter.onerror=()=>{if(version===revision){busy=false;queue=[];notice('Trình duyệt chưa cho phát loa. Nhấn bật loa để thử lại.');}};
      try{synth.speak(utter);}catch(error){utter.onerror();}
    }
    function clear(){revision++;queue=[];busy=false;synth?.cancel();}
    synth?.addEventListener('voiceschanged',voices);root.addEventListener?.('pagehide',clear);voices();state(false);
    return {speak(text){if(!enabled||!activated)return;if(queue.length<20)queue.push(text);voices();drain();},
      toggle(){if(!activated){activated=true;enabled=true;}else enabled=!enabled;
        if(!enabled){clear();notice('');}else voices();state(enabled);return enabled;},
      clear,orderText,get active(){return activated&&enabled;}};
  }
  root.PetroShiftVoice={create,orderText};
  if(typeof module!=='undefined')module.exports=root.PetroShiftVoice;
})(typeof window==='undefined'?globalThis:window);
