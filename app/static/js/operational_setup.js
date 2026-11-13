/* Staged operational UI. Backend remains authoritative for role, scope and stock. */
(function (global) {
  'use strict';
  const api = async (path, body, method = 'POST') => {
    const response = await fetch(path, { method, credentials: 'same-origin',
      headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Dữ liệu không hợp lệ; kiểm tra lại các trường.');
    return data;
  };
  function readinessText(r) {
    if (!r) return 'Chưa có dữ liệu cấu hình vận hành.';
    if (!r.has_tanks) return 'Chưa cấu hình bồn chứa. Thêm bồn trước khi nhập kho.';
    if (!r.has_usable_pump) return 'Chưa có trụ khả dụng. Thêm trụ hoặc kiểm tra trạng thái trụ.';
    if (!r.has_prices) return 'Chưa có giá bán riêng của trạm.';
    return r.ready_fuels.length ? 'Có nhiên liệu sẵn sàng phục vụ; lượng khả dụng được kiểm tra khi tiếp nhận.' : 'Chưa đủ nhiên liệu khả dụng để phục vụ.';
  }
  if (typeof module !== 'undefined') module.exports = {readinessText, api};
  if (!global.document) return;
  let inventory=null, station=null, refillKey=null, refillIntent=null, saving=false;
  const capture=()=>global.PetroStationScope?.capture();
  const current=token=>!global.PetroStationScope||global.PetroStationScope.current(token);
  const equipment=(row,kind)=>global.PetroEnterpriseUI?.equipment(row,station?.tx_ma,kind)||{label:kind==='tank'?row.tank_name:row.pump_name,note:'',demo:false};
  const label=(row,kind)=>{const view=equipment(row,kind);return view.label+(view.demo?' · DEMO':'');};
  const $ = id => document.getElementById(id);
  const section=document.createElement('section');
  section.hidden=true;
  section.className='card-base p-5 md:p-6 rounded-2xl border border-outline-variant/30 shadow-xs bg-white space-y-4';
  section.innerHTML=`
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-outline-variant/20">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-primary/10 text-primary flex items-center justify-center shrink-0">
          <span class="material-symbols-outlined text-2xl">tune</span>
        </div>
        <div>
          <h3 class="font-black text-on-surface text-base md:text-lg">Cấu hình vận hành trạm</h3>
          <p class="text-xs text-secondary">Thiết lập danh mục bồn chứa ngầm & trụ bơm nhiên liệu tại trạm</p>
        </div>
      </div>
      <div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-surface-container-low border border-outline-variant/40 text-xs font-semibold text-on-surface">
        <span class="material-symbols-outlined text-base text-primary">info</span>
        <span id="ops-readiness" role="status" aria-live="polite">Đang tải cấu hình…</span>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <!-- Card Bồn chứa -->
      <div class="p-4 rounded-xl bg-surface-container-lowest border border-outline-variant/30 space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="material-symbols-outlined text-primary text-xl">database</span>
            <h4 class="font-bold text-sm text-on-surface">Bồn Chứa Nhiên Liệu</h4>
          </div>
          <button type="button" id="ops-add-tank" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-primary text-white hover:bg-primary/90 transition-all shadow-xs cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed">
            <span class="material-symbols-outlined text-[16px]">add_circle</span> Thêm bồn mới
          </button>
        </div>
        <div class="pt-2 border-t border-outline-variant/20">
          <label for="ops-tank-picker" class="block text-[11px] font-bold text-secondary uppercase tracking-wider mb-1.5">Chọn bồn để chỉnh sửa:</label>
          <div class="flex items-center gap-2">
            <select id="ops-tank-picker" aria-label="Chọn bồn sửa" class="flex-1 bg-white border border-outline-variant/60 rounded-xl px-3 py-2 text-xs font-medium text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 shadow-2xs"></select>
            <button type="button" id="ops-edit-tank" class="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-xs font-bold border border-primary/40 text-primary hover:bg-primary/5 transition-all shadow-2xs cursor-pointer shrink-0 disabled:opacity-40 disabled:cursor-not-allowed">
              <span class="material-symbols-outlined text-[15px]">edit</span> Sửa bồn
            </button>
          </div>
        </div>
      </div>

      <!-- Card Trụ bơm -->
      <div class="p-4 rounded-xl bg-surface-container-lowest border border-outline-variant/30 space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="material-symbols-outlined text-emerald-700 text-xl">local_gas_station</span>
            <h4 class="font-bold text-sm text-on-surface">Trụ Bơm & Vòi Cấp</h4>
          </div>
          <button type="button" id="ops-add-pump" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-emerald-700 text-white hover:bg-emerald-800 transition-all shadow-xs cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed">
            <span class="material-symbols-outlined text-[16px]">add_circle</span> Thêm trụ bơm mới
          </button>
        </div>
        <div class="pt-2 border-t border-outline-variant/20">
          <label for="ops-pump-picker" class="block text-[11px] font-bold text-secondary uppercase tracking-wider mb-1.5">Chọn trụ để chỉnh sửa:</label>
          <div class="flex items-center gap-2">
            <select id="ops-pump-picker" aria-label="Chọn trụ sửa" class="flex-1 bg-white border border-outline-variant/60 rounded-xl px-3 py-2 text-xs font-medium text-on-surface focus:outline-none focus:ring-2 focus:ring-emerald-600/20 shadow-2xs"></select>
            <button type="button" id="ops-edit-pump" class="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-xs font-bold border border-emerald-700/40 text-emerald-800 hover:bg-emerald-50 transition-all shadow-2xs cursor-pointer shrink-0 disabled:opacity-40 disabled:cursor-not-allowed">
              <span class="material-symbols-outlined text-[15px]">tune</span> Sửa trụ
            </button>
          </div>
        </div>
      </div>
    </div>

    <p id="ops-feedback" role="status" aria-live="polite" class="text-xs text-red-600 font-semibold empty:hidden"></p>`;
  const mount=$('panel-dn-inventory'); if (!mount) return;
  mount.prepend(section);
  const dialog=document.createElement('dialog');
  dialog.className='rounded-3xl p-6 w-full max-w-lg bg-white shadow-2xl border border-outline-variant/30 backdrop:bg-black/50 backdrop:backdrop-blur-xs transition-all';
  dialog.style.maxHeight='90dvh'; dialog.style.overflowY='auto';
  document.body.append(dialog);
  const message=text => {$('ops-feedback').textContent=text;};
  const key=()=>global.crypto.randomUUID();
  const endpoint=(sid,kind,id)=>`/api/doanh-nghiep/stations/${encodeURIComponent(sid)}/${kind}${id?'/'+encodeURIComponent(id):''}`;
  const option=(value,label)=>{const o=document.createElement('option');o.value=value;o.textContent=label;return o;};
  function update(data,selected) {
    if(data.storage!=='postgresql') return;
    section.hidden=false;
    global.PetroOperations={update,error:message,accept,start:rid=>accept(rid,true),refill,setStatus};
    // Operational fuel IDs are canonical, fixed-width codes; lexical order is canonical.
    const order=(rows,key)=>[...rows].sort((a,b)=>String(key(a)).localeCompare(String(key(b))));
    inventory={...data,tanks:order(data.tanks,t=>t.nl_ma)};
    station={...selected,prices:order(selected.prices,f=>f.nl_ma)};
    message('');
    $('ops-add-tank').disabled=false;
    $('ops-readiness').textContent=readinessText(data.readiness);
    const tankPicker=$('ops-tank-picker'),pumpPicker=$('ops-pump-picker');
    tankPicker.replaceChildren(...data.tanks.map(t=>option(t.tank_id,label(t,'tank'))));
    pumpPicker.replaceChildren(...data.pumps.map(p=>option(p.pump_id,label(p,'pump'))));
    $('ops-edit-tank').disabled=!data.tanks.length; $('ops-edit-pump').disabled=!data.pumps.length;
    $('ops-add-pump').disabled=!data.tanks.length;
  }
  function field(form,name,label,type='text',value='',required=true) {
    const wrapper=document.createElement('label'); wrapper.className='block my-2.5';
    const span=document.createElement('span'); span.className='block text-xs font-bold text-secondary uppercase tracking-wider mb-1'; span.textContent=label;
    const input=document.createElement('input'); input.name=name; input.type=type; input.value=value;
    input.required=required;
    if (type==='checkbox') {
      wrapper.className='flex items-center gap-2.5 my-3 cursor-pointer select-none';
      span.className='text-xs font-bold text-on-surface';
      input.className='w-4 h-4 rounded text-primary focus:ring-primary/30';
      wrapper.append(input, span);
    } else {
      input.className='block w-full border border-outline-variant/60 rounded-xl px-3.5 py-2.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 shadow-2xs';
      if(type==='number') { input.step='0.01';input.min='0'; }
      wrapper.append(span, input);
    }
    form.append(wrapper); return input;
  }
  function open(kind,id=null) {
    if (!station || !inventory) return message('Chọn trạm và tải cấu hình trước.');
    const action=capture();
    const sid=station.tx_ma, tank=kind==='tanks';
    const existing=id?(tank?inventory.tanks.find(t=>t.tank_id===id):inventory.pumps.find(p=>p.pump_id===id)):null;
    if (id&&!existing) return message('Dữ liệu đã thay đổi. Tải lại cấu hình.');
    dialog.replaceChildren(); const form=document.createElement('form'); dialog.append(form);
    const h=document.createElement('h3');
    h.className='text-base md:text-lg font-black text-on-surface mb-3 flex items-center gap-2 pb-2.5 border-b border-outline-variant/20';
    h.innerHTML=`<span class="material-symbols-outlined text-primary">${tank ? 'database' : 'local_gas_station'}</span> <span>${(id?'Chỉnh sửa ':'Thêm mới ')+(tank?'bồn chứa ngầm':'trụ bơm nhiên liệu')}</span>`;
    form.append(h);
    if(existing){const view=equipment(existing,tank?'tank':'pump');if(view.demo){const note=document.createElement('p');note.className='text-xs font-bold text-amber-700 bg-amber-50 p-2 rounded-lg mb-2';note.textContent=view.label+' — '+view.note;form.append(note);}}
    const ident=field(form,'id','Mã thiết bị ổn định','text',id||'');ident.pattern='[A-Za-z0-9][A-Za-z0-9_-]{0,31}';ident.maxLength=32;ident.disabled=!!id;
    const name=field(form,'name','Tên thiết bị','text',existing?(tank?existing.tank_name:existing.pump_name):'');name.maxLength=128;
    if (tank) {
      field(form,'capacity','Dung tích tối đa (L)','number',existing?.capacity||'');
      field(form,'threshold','Ngưỡng cảnh báo (L)','number',existing?.min_alert_liters??'');
      if (!id) {
        const label=document.createElement('label'); label.className='block my-2.5';
        const span=document.createElement('span'); span.className='block text-xs font-bold text-secondary uppercase tracking-wider mb-1'; span.textContent='Nhiên liệu chứa';
        const select=document.createElement('select');select.name='fuel';select.required=true;select.className='block w-full border border-outline-variant/60 rounded-xl px-3.5 py-2.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 shadow-2xs';
        select.append(...station.prices.filter(f=>['NL000001','NL000002','NL000003'].includes(f.nl_ma)).map(f=>option(f.nl_ma,f.nl_ten)));
        label.append(span,select);form.append(label);
        const note=document.createElement('p');note.className='text-xs text-secondary italic mt-1';note.textContent='* Tồn kho ban đầu bằng 0; nhập kho bằng xe bồn sau khi tạo.';form.append(note);
      }
    } else {
      const code=field(form,'code','Mã hiển thị trụ','text',existing?.pump_code||'');code.pattern='[A-Z0-9][A-Z0-9_-]{0,31}';code.disabled=!!id;
      if (!id) {
        field(form,'baseline','Chỉ số totalizer ban đầu đã kiểm tra (L)','number','');
        const confirmed=field(form,'confirmed','Tôi đã xác nhận chỉ số ban đầu','checkbox');confirmed.value='yes';
      } else {
        const label=document.createElement('label');label.className='block my-2.5';
        const span=document.createElement('span'); span.className='block text-xs font-bold text-secondary uppercase tracking-wider mb-1'; span.textContent='Trạng thái thiết bị';
        const select=document.createElement('select');select.name='status';select.className='block w-full border border-outline-variant/60 rounded-xl px-3.5 py-2.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/20 shadow-2xs';
        select.append(...['READY','OFFLINE','MAINTENANCE'].map(state=>option(state,state)));
        select.value=existing.status;label.append(span,select);form.append(label);
      }
      const fs=document.createElement('fieldset');fs.className='my-3 p-3 rounded-xl border border-outline-variant/40 bg-surface-container-lowest';
      const legend=document.createElement('legend');legend.className='text-xs font-bold text-secondary uppercase tracking-wider px-1';legend.textContent='Nhiên liệu tương thích với trụ';fs.append(legend);
      for (const fid of [...new Set(inventory.tanks.filter(t=>t.active).map(t=>t.nl_ma))]) {
        const label=document.createElement('label');label.className='flex items-center gap-2 p-1.5 cursor-pointer text-xs font-semibold text-on-surface hover:bg-white rounded-lg transition-colors';
        const input=document.createElement('input');input.type='checkbox';input.name='fuels';input.value=fid;input.checked=!!existing?.fuels.includes(fid);
        input.className='w-4 h-4 rounded text-primary focus:ring-primary/30';
        label.append(input,document.createTextNode(' '+(station.prices.find(f=>f.nl_ma===fid)?.nl_ten||fid)));fs.append(label);
      }
      form.append(fs);
    }
    const error=document.createElement('p');error.setAttribute('role','alert');error.className='text-xs text-red-600 font-semibold my-2';form.append(error);
    const actionRow=document.createElement('div');actionRow.className='flex justify-end gap-2.5 pt-3 border-t border-outline-variant/20 mt-4';
    const close=document.createElement('button');close.type='button';close.textContent='Đóng';close.className='px-4 py-2 rounded-xl text-xs font-bold border border-outline-variant/50 text-secondary hover:bg-surface-container-high transition-all cursor-pointer';close.onclick=()=>dialog.close();
    const save=document.createElement('button');save.type='submit';save.textContent='Lưu cấu hình';save.className='px-5 py-2 rounded-xl text-xs font-bold bg-primary text-white shadow-xs hover:bg-primary/90 transition-all cursor-pointer';
    actionRow.append(close,save);
    form.append(actionRow);
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(saving||!form.reportValidity())return;
      if(!current(action)||station?.tx_ma!==sid) {error.textContent='Đã đổi trạm. Đóng và mở lại biểu mẫu.';return;}
      const f=new FormData(form);let body;
      if(tank) body={bc_ten:f.get('name'),bc_dungtich:f.get('capacity'),bc_nguong:f.get('threshold'),...(id?{bc_phienban:existing.version}:{bc_ma:f.get('id'),nl_ma:f.get('fuel')})};
      else body={tb_ten:f.get('name'),nl_ma:f.getAll('fuels'),...(id?{tb_phienban:existing.version,tb_trangthai:f.get('status')}:{tb_ma:f.get('id'),tb_code:f.get('code'),tb_mocdau:f.get('baseline'),baseline_confirmed:f.get('confirmed')==='yes',tb_trangthai:'OFFLINE'})};
      saving=true;save.disabled=true;error.textContent='Đang lưu…';
      try {await api(endpoint(sid,kind,id),body,id?'PATCH':'POST');if(!current(action))return;dialog.close();await fetchInventoryData();if(current(action))message('Đã lưu cấu hình.');}
      catch(e){if(current(action))error.textContent=e.message;}finally{if(current(action))saving=false;save.disabled=false;}
    });
    dialog.showModal();
  }
  $('ops-add-tank').onclick=()=>open('tanks');$('ops-add-pump').onclick=()=>open('pumps');
  $('ops-edit-tank').onclick=()=>open('tanks',$('ops-tank-picker').value);$('ops-edit-pump').onclick=()=>open('pumps',$('ops-pump-picker').value);
  async function accept(rid,start=false) {
    if (!station) return;
    const action=capture();
    const sid=station.tx_ma;
    try {
      await fetchInventoryData();
      if(!current(action))return;
      const detail=await api(`/api/workflow/fuel-requests/${encodeURIComponent(rid)}`,null,'GET');
      if(!current(action))return;
      if(station?.tx_ma!==sid||detail.tx_ma!==sid)throw new Error('Trạm đã thay đổi; tải lại đơn.');
      const candidates=inventory.pumps.filter(p=>p.status==='READY'&&p.fuels.includes(detail.nl_ma));
      if(start&&!candidates.length)throw new Error('Không có trụ bơm tương thích sẵn sàng.');
      dialog.replaceChildren();const form=document.createElement('form');dialog.append(form);
      const h=document.createElement('h3');h.className='text-base font-bold text-on-surface mb-3';h.textContent=(start?'Chọn trụ bơm thực tế cho ':'Tiếp nhận và giữ chỗ cho ')+rid;form.append(h);
      if(start){const select=document.createElement('select');select.name='pump';select.className='border border-outline-variant/60 rounded-xl p-3 w-full text-sm bg-white';select.append(...candidates.map(p=>option(p.pump_id,label(p,'pump'))));form.append(select);}
      if(!start&&detail.hinh_thuc_do_xang==='DO_DAY_BINH')field(form,'maximum','Xác nhận số lít tối đa với khách hàng','number');
      const status=document.createElement('p');status.setAttribute('role','alert');status.className='text-xs text-red-600 font-semibold my-2';form.append(status);
      const actionRow=document.createElement('div');actionRow.className='flex justify-end gap-2.5 pt-3 border-t border-outline-variant/20 mt-4';
      const close=document.createElement('button');close.type='button';close.textContent='Đóng';close.className='px-4 py-2 rounded-xl text-xs font-bold border border-outline-variant/50 text-secondary hover:bg-surface-container-high transition-all cursor-pointer';close.onclick=()=>dialog.close();
      const submit=document.createElement('button');submit.type='submit';submit.textContent=start?'Bắt đầu bơm':'Tiếp nhận — chỉ giữ chỗ';submit.className='px-5 py-2 rounded-xl text-xs font-bold bg-primary text-white shadow-xs hover:bg-primary/90 transition-all cursor-pointer';
      actionRow.append(close,submit);
      form.append(actionRow);
      form.onsubmit=async event=>{
        event.preventDefault();if(!form.reportValidity()||saving)return;
        if(!current(action)||station?.tx_ma!==sid)return status.textContent='Đã đổi trạm; mở lại đơn.';
        saving=true;submit.disabled=true;
        try {const f=new FormData(form);await api(`/api/workflow/fuel-requests/${encodeURIComponent(rid)}/${start?'confirm-pump':'accept'}`,start?{pump_id:f.get('pump')}:(f.has('maximum')?{maximum_liters:f.get('maximum')}:{}));if(!current(action))return;dialog.close();await fetchOrdersOnly();if(current(action))await fetchInventoryData();}
        catch(e){if(current(action))status.textContent=e.message;}finally{if(current(action))saving=false;submit.disabled=false;}
      };dialog.showModal();
    }catch(e){if(current(action)){message(e.message);alert(e.message);}}
  }
  async function refill() {
    if(!station||!inventory?.tanks.length)return message('Hãy thêm bồn trước khi nhập kho.');
    if(saving)return;
    const action=capture();
    const body={tx_ma:station.tx_ma,tank_id:$('refill-select-tank').value,liters:$('refill-input-liters').value,supplier:$('refill-input-supplier').value.trim()||null};
    const intent=JSON.stringify(body);
    if(intent!==refillIntent){refillIntent=intent;refillKey=key();}
    saving=true;
    try{await api('/api/doanh-nghiep/inventory/refill',{...body,operation_key:refillKey});if(!current(action))return;refillKey=refillIntent=null;closeRefillModal();await fetchInventoryData();if(current(action))message('Đã nhập kho.');}
    catch(e){if(current(action)){message(e.message);alert(e.message);}}finally{if(current(action))saving=false;}
  }
  async function setStatus(pid,status) {
    const p=inventory?.pumps.find(item=>item.pump_id===pid);if(!p||!station)return;
    const action=capture();
    try{await api(`/api/doanh-nghiep/pumps/${encodeURIComponent(station.tx_ma)}/${encodeURIComponent(pid)}/status`,{status,version:p.version},'PUT');if(current(action))await fetchInventoryData();}
    catch(e){if(current(action))message(e.message);}
  }
  function unavailable(state,text) {
    inventory=null; station=null; refillKey=refillIntent=null;
    saving=false;
    section.hidden=false;
    $('ops-readiness').textContent=state==='loading'?'Đang tải cấu hình…':'Cấu hình tạm thời không khả dụng.';
    message(state==='error'?text:'');
    for(const id of ['ops-add-tank','ops-add-pump','ops-edit-tank','ops-edit-pump']) $(id).disabled=true;
    $('ops-tank-picker').replaceChildren();$('ops-pump-picker').replaceChildren();
    if(dialog.open)dialog.close();
  }
  global.PetroOperationalSetup={update,error:message,unavailable};
})(typeof window==='undefined'?globalThis:window);
