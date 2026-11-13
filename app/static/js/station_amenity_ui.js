/* Immutable-snapshot labels, not live catalog names, are used for historical review. */
(function(root) {
  function checkedIds(container) {return [...container.querySelectorAll('input:checked')].map(input=>input.value);}
  function sameIds(left, right) {return left.length===right.length && [...left].sort().every((id,index)=>id===[...right].sort()[index]);}
  function checkboxes(container,catalog,ids,history=[],onChange=()=>{}) {
    container.replaceChildren();const selected=new Set(ids);
    const options=[...catalog];const known=new Set(catalog.map(item=>item.dv_ma));
    for(const id of ids)if(!known.has(id)) {
      const old=history.find(item=>item.dv_ma===id);
      options.push({dv_ma:id,dv_ten:(old?.dv_ten||id)+' — không còn trong danh mục; bỏ chọn trước khi gửi lại'});
    }
    for(const item of options) {
      const label=document.createElement('label'),input=document.createElement('input');
      label.className='flex items-center gap-2 text-sm';input.type='checkbox';input.value=item.dv_ma;
      input.checked=selected.has(item.dv_ma);input.addEventListener('change',onChange);
      label.append(input,document.createTextNode(item.dv_ten));container.append(label);
    }
    if(!options.length)container.textContent='Danh mục tiện ích đang trống.';
    onChange();
  }
  function review(container,change,submittedAmenities) {
    container.replaceChildren();
    if(!change && Array.isArray(submittedAmenities)) {
      const heading=document.createElement('h4'),list=document.createElement('ul');
      heading.textContent='Tiện ích trạm mới tại lần nộp';heading.className='font-bold';
      for(const item of submittedAmenities){const li=document.createElement('li');li.textContent=`${item.dv_ten} (${item.dv_ma})`;list.append(li);}
      if(!submittedAmenities.length)list.textContent='Không đăng ký tiện ích.';
      container.append(heading,list);return;
    }
    if(!change){container.textContent='Hồ sơ này không đề xuất thay đổi tiện ích; giữ nguyên tập hiện tại.';return;}
    const labels={current:'Tiện ích hiện tại (tại lần nộp)',proposed:'Tập tiện ích đề xuất',added:'Bổ sung',removed:'Loại bỏ'};
    for(const [key,title] of Object.entries(labels)) {
      const section=document.createElement('section'),heading=document.createElement('h4'),list=document.createElement('ul');
      section.className='border rounded-lg p-3';heading.className='font-bold';heading.textContent=title;
      const rows=change[key]||[];
      for(const item of rows){const li=document.createElement('li');li.textContent=`${item.dv_ten} (${item.dv_ma})`;list.append(li);}
      if(!rows.length)list.textContent='Không có.';
      section.append(heading,list);container.append(section);
    }
  }
  const api={checkedIds,sameIds,checkboxes,review};root.PetroStationAmenities=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
