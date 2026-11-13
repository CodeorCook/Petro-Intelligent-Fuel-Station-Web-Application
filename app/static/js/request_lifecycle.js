(function(root){
 'use strict';
 function remaining(deadline,server,elapsed){return Math.max(0,Date.parse(deadline)-Date.parse(server)-elapsed);}
 function format(ms){const n=Math.ceil(ms/1000);return `${Math.floor(n/60).toString().padStart(2,'0')}:${(n%60).toString().padStart(2,'0')}`;}
 function confirmAction(title,needsNoDispense=false){return new Promise(resolve=>{
  const dialog=document.createElement('dialog');dialog.className='rounded-2xl p-5 max-w-md w-full';
  const form=document.createElement('form'),heading=document.createElement('h3'),label=document.createElement('label');
  heading.textContent=title;heading.id='petro-lifecycle-title';dialog.setAttribute('aria-labelledby',heading.id);label.textContent='Lý do';
  const reason=document.createElement('textarea');reason.name='reason';reason.required=true;reason.maxLength=256;reason.className='block border p-3 w-full';label.append(reason);
  form.append(heading,label);let check;
  if(needsNoDispense){const l=document.createElement('label');check=document.createElement('input');check.type='checkbox';check.required=true;l.append(check,document.createTextNode(' Xác nhận chưa bắt đầu bơm; nếu đã bơm phải liên hệ trạm đối soát.'));form.append(l);}
  const save=document.createElement('button');save.type='submit';save.textContent='Xác nhận';save.className='p-3 border rounded-xl';
  const close=document.createElement('button');close.type='button';close.textContent='Quay lại';close.className='p-3';
  let finished=false;const finish=value=>{if(finished)return;finished=true;dialog.close();dialog.remove();resolve(value);};
  close.onclick=()=>finish(null);dialog.oncancel=e=>{e.preventDefault();finish(null);};
  form.onsubmit=e=>{e.preventDefault();if(form.reportValidity()&&reason.value.trim())finish({reason:reason.value.trim(),confirm_no_dispense:!!check?.checked});};
  form.append(save,close);dialog.append(form);document.body.append(dialog);dialog.showModal();reason.focus();
 });}
 root.PetroLifecycle={remaining,format,confirmAction};
 if(typeof module!=='undefined')module.exports=root.PetroLifecycle;
})(typeof window==='undefined'?globalThis:window);
