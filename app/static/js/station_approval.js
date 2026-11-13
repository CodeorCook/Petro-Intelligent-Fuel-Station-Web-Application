(() => {
  const page=document.querySelector("[data-station-approval-page]"); if(!page)return;
  const message=document.getElementById("station-approval-message");
  const modalMessage=document.getElementById('station-modal-message');
  if(modalMessage)new MutationObserver(()=>{modalMessage.textContent=message.textContent;if(message.textContent&&!document.getElementById('modal-station-registration').classList.contains('hidden'))modalMessage.scrollIntoView({block:'nearest',behavior:'smooth'});}).observe(message,{childList:true,characterData:true,subtree:true});
  let selected=null,staged=[],busy=false,offset=0,map=null,marker=null;
  let syncControls=()=>{};
  async function api(url,options={}){
    const response=await fetch(url,{credentials:"same-origin",cache:"no-store",...options});
    if(response.status===204)return null;
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:"Không thể xử lý; kiểm tra đăng nhập, thông tin và quyền truy cập.");
    return data;
  }
  const json=(method,body)=>({method,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  async function action(fn){if(busy)return;busy=true;syncControls();page.setAttribute("aria-busy","true");try{message.textContent="";await fn();}catch(e){message.textContent=e.message;}finally{busy=false;syncControls();page.removeAttribute("aria-busy");}}
  function evidence(container,files){container.replaceChildren();for(const file of files){const li=document.createElement("li"),a=document.createElement("a");a.textContent=file.tmc_ten;a.className="text-primary underline";a.href=`/api/station-approval/evidence/${encodeURIComponent(file.tmc_ma)}`;a.setAttribute("download","");li.append(a);container.append(li);}}
  if(page.dataset.stationApprovalPage==="enterprise"){
    const form=document.getElementById("station-draft-form");
    const amenities=window.PetroStationAmenities,amenityBox=document.getElementById('station-amenity-options');
    const amenityFieldset=document.getElementById('station-amenity-proposal');
    const saveAmenities=document.getElementById('save-station-amenities');
    let persistedIds=[],pending=false,ready=false,amenityError='',staleSelection=false,catalogItems=[];
    const base=()=>`/api/enterprise/stations/${encodeURIComponent(selected.tx_ma)}`;
    function formValues(validate=true){if(validate&&!form.reportValidity())throw new Error("Cần tên, địa chỉ và GPS thực tế.");return Object.fromEntries([...form.elements].filter(i=>i.name).map(i=>[i.name,i.type==="checkbox"?i.checked:(i.value.trim()||null)]));}
    const draftEditable=()=>selected&&selected.tx_phienban_hientai===0&&!selected.tx_congkhai&&['NHAP','CAN_BO_SUNG','TU_CHOI'].includes(selected.tx_trangthai)&&!pending;
    const amenityDirty=()=>!!selected&&!amenities.sameIds(persistedIds,amenities.checkedIds(amenityBox));
    syncControls=()=>{
      const draft=draftEditable(),update=selected?.tx_phienban_hientai>0&&selected.tx_trangthai==='DA_DUYET'&&!pending;
      amenityFieldset.disabled=busy||!ready||!(draft||update);
      saveAmenities.hidden=!selected||selected.tx_phienban_hientai>0;
      saveAmenities.disabled=busy||!ready||staleSelection||!draft||!amenityDirty();
      document.getElementById('station-amenity-count').textContent=amenities.checkedIds(amenityBox).length;
      document.getElementById('save-station-draft').disabled=busy||!!selected&&(selected.tx_phienban_hientai>0||pending)||!!selected&&!ready;
      document.getElementById('submit-station-approval').disabled=busy;
      document.getElementById('upload-station-evidence').disabled=busy;
      document.getElementById('station-activation-help').textContent=busy?'Đang xử lý, vui lòng chờ…':!selected?'Bước 1: Lưu nháp; bước 2: lưu tiện ích; bước 3: tải minh chứng; bước 4: kích hoạt.':pending?'Hồ sơ lịch sử đang chờ xử lý; cần chủ máy đối soát, không tự đổi trạng thái.':!staged.length?'Chọn file rồi bấm Tải Lên Minh Chứng. Chọn file chưa phải đã upload.':draft&&amenityDirty()?'Cần lưu tiện ích nháp trước khi kích hoạt.':'Kích hoạt/cập nhật chỉ thành công khi backend xác nhận schema audit và mọi điều kiện hợp lệ.';
      document.getElementById('station-amenity-title').textContent=selected?.tx_phienban_hientai>0?'Đề xuất tiện ích cho trạm đã duyệt':'Tiện ích trạm nháp';
      document.getElementById('station-amenity-help').textContent=selected?.tx_phienban_hientai>0?
        'Chọn toàn bộ tập tiện ích mới; chỉ áp dụng cùng lần cập nhật đã được backend xác nhận.':
        'Lưu toàn bộ tập tiện ích nháp trước khi kích hoạt. Bỏ chọn tất cả sẽ lưu tập rỗng.';
      document.getElementById('station-amenity-save-status').textContent=!selected?'Lưu trạm nháp trước để chọn tiện ích.':
        !ready?'Chưa tải đủ dữ liệu trạm; hãy thử tải lại.':pending?'Hồ sơ đang chờ duyệt; tiện ích đã khóa.':staleSelection?'Trạm hoặc tiện ích đã đổi ở phiên khác. Tải lại và chọn lại trước khi lưu/nộp.':amenityError||
        (draft?(amenityDirty()?'Có thay đổi chưa lưu. Lưu tiện ích trước khi gửi hồ sơ.':'Tập tiện ích đã lưu; sẽ được chụp vào hồ sơ khi nộp.'):
        'Tiện ích đang hoạt động giữ nguyên đến khi cập nhật thành công.');
    };
    function mayDiscard(){return !amenityDirty()||confirm('Có lựa chọn tiện ích chưa lưu/chưa nộp. Bỏ các lựa chọn này để tải trạm?');}
    function showCurrent(ids){document.getElementById('station-current-amenities').textContent='Tiện ích đã lưu: '+(ids.map(id=>catalogItems.find(item=>item.dv_ma===id)?.dv_ten||id).join(', ')||'Không có.');}
    async function list(){
      const [rows,me]=await Promise.all([api("/api/enterprise/stations"),api("/api/auth/me")]);
      const account=document.getElementById("dn-username");if(account)account.textContent=me.username;
      const box=document.getElementById("owned-station-list");box.replaceChildren();
      if(!rows||!rows.length){
        const empty=document.createElement("tr");
        empty.innerHTML=`
          <td colspan="8" class="py-8 text-center text-secondary">
            <span class="material-symbols-outlined text-4xl mb-1 text-outline block">domain_disabled</span>
            <p class="text-xs font-bold text-on-surface">Chưa có trạm xăng nào trực thuộc doanh nghiệp</p>
            <p class="text-[11px] text-secondary mt-1">Bấm nút "Đăng Ký Trạm Mới" phía trên để khởi tạo hồ sơ đăng ký trạm.</p>
          </td>
        `;
        box.append(empty);
        return;
      }
      for(const row of rows){
        const tr=document.createElement("tr");
        const isSelected=selected&&selected.tx_ma===row.tx_ma;
        tr.className=`hover:bg-surface-container-lowest/70 transition-colors ${isSelected?'bg-primary/5':''}`;
        
        let statusBadge='';
        if(row.tx_trangthai==='DA_DUYET') statusBadge='<span class="px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">Đã duyệt</span>';
        else if(row.tx_trangthai==='CHO_DUYET') statusBadge='<span class="px-2.5 py-1 rounded-full text-[11px] font-bold bg-amber-100 text-amber-800 border border-amber-300">Chờ duyệt</span>';
        else if(row.tx_trangthai==='CAN_BO_SUNG') statusBadge='<span class="px-2.5 py-1 rounded-full text-[11px] font-bold bg-blue-100 text-blue-800 border border-blue-300">Cần bổ sung</span>';
        else if(row.tx_trangthai==='TU_CHOI') statusBadge='<span class="px-2.5 py-1 rounded-full text-[11px] font-bold bg-rose-100 text-rose-800 border border-rose-300">Từ chối</span>';
        else statusBadge='<span class="px-2.5 py-1 rounded-full text-[11px] font-bold bg-slate-100 text-slate-800 border border-slate-300">Bản nháp</span>';

        const gps = (row.tx_vido != null && row.tx_kinhdo != null) 
          ? `${Number(row.tx_vido).toFixed(4)}, ${Number(row.tx_kinhdo).toFixed(4)}` 
          : '—';

        tr.innerHTML=`
          <td class="py-3 px-3.5 whitespace-nowrap font-mono font-bold text-primary">${row.tx_ma}</td>
          <td class="py-3 px-3.5 whitespace-nowrap font-bold text-on-surface">${row.tx_ten}</td>
          <td class="py-3 px-3.5 whitespace-nowrap text-secondary max-w-xs truncate" title="${row.tx_diachi||''}">${row.tx_diachi||'—'}</td>
          <td class="py-3 px-3.5 whitespace-nowrap text-secondary">${row.tx_trucduong||'—'}</td>
          <td class="py-3 px-3.5 whitespace-nowrap font-mono text-xs text-secondary">${gps}</td>
          <td class="py-3 px-3.5 whitespace-nowrap text-center">${statusBadge}</td>
          <td class="py-3 px-3.5 whitespace-nowrap text-center font-mono text-xs font-semibold text-secondary">v${row.tx_phienban_hientai}</td>
          <td class="py-3 px-3.5 whitespace-nowrap text-center">
            <div class="inline-flex items-center gap-1.5">
              <button type="button" class="btn-select-station py-1 px-2.5 rounded-lg text-xs font-semibold bg-surface-container-low hover:bg-surface-container text-primary border border-outline-variant/30 inline-flex items-center gap-1 transition-all" title="Xem hồ sơ / Chỉnh sửa trạm">
                <span class="material-symbols-outlined text-[15px]">edit_note</span>
                <span>Hồ sơ</span>
              </button>
              ${row.tx_trangthai==='DA_DUYET'?`
                <button type="button" class="btn-operate-station py-1 px-2.5 rounded-lg text-xs font-bold bg-emerald-700 hover:bg-emerald-800 text-white inline-flex items-center gap-1 shadow-xs transition-all" title="Vào chế độ quản lý vòi bơm">
                  <span class="material-symbols-outlined text-[15px]">local_gas_station</span>
                  <span>Vận hành</span>
                </button>
              `:''}
            </div>
          </td>
        `;

        tr.querySelector('.btn-select-station').addEventListener('click',()=>{
          action(async()=>{
            await choose(row.tx_ma);
            if(typeof window.openStationModal === 'function') {
              window.openStationModal('edit');
            }
          });
        });

        if(row.tx_trangthai==='DA_DUYET'){
          tr.querySelector('.btn-operate-station')?.addEventListener('click',()=>{
            if(typeof loadAllEnterpriseData==='function') loadAllEnterpriseData(row.tx_ma);
            if(typeof switchDnTab==='function') switchDnTab('pumps');
          });
        }

        box.append(tr);
      }
    }
    async function choose(id,keepDraft=false,force=false){
      if(!keepDraft&&!force&&!mayDiscard())return;
      const preserved=keepDraft?formValues(false):null;
      const preservedAmenities=keepDraft&&amenityDirty()?amenities.checkedIds(amenityBox):null;
      const baseline=[...persistedIds],oldVersion=selected?.tx_phienban_hientai;
      ready=false;syncControls();
      const path=`/api/enterprise/stations/${encodeURIComponent(id)}`;
      const station=await api(path);
      const [history,stages,catalog,links]=await Promise.all([api(path+"/approvals"),
        api(path+"/evidence/staging"),api('/api/services'),api(path+"/services")]);
      const loadedIds=links.map(link=>link.dv_ma);
      if(!keepDraft)staleSelection=false;
      else if((preservedAmenities&&!amenities.sameIds(baseline,loadedIds))||oldVersion!==station.tx_phienban_hientai)staleSelection=true;
      selected=station;staged=stages;persistedIds=preservedAmenities?baseline:loadedIds;amenityError='';catalogItems=catalog;
      const latest=history[0],proposal=preserved||(selected.tx_phienban_hientai>0&&latest&&["CAN_BO_SUNG","TU_CHOI"].includes(latest.ycdt_trangthai)?latest.ycdt_dulieu:selected);
      for(const i of form.elements){if(!i.name)continue;if(i.type==="checkbox")i.checked=!!proposal[i.name];else i.value=proposal[i.name]??"";}
      document.getElementById("station-version-note").textContent="Nháp chưa công khai. Trạm đang hoạt động chỉ đổi khi cập nhật có audit thành công.";
      pending=history.some(r=>r.ycdt_trangthai==='CHO_DUYET');
      const previous=selected.tx_phienban_hientai>0&&latest&&['CAN_BO_SUNG','TU_CHOI','CHO_DUYET'].includes(latest.ycdt_trangthai)?latest.ycdt_dulieu.amenity_change:null;
      const chosen=preservedAmenities??previous?.proposed?.map(item=>item.dv_ma)??links.map(link=>link.dv_ma);
      showCurrent(loadedIds);
      amenities.checkboxes(amenityBox,catalog,chosen,previous?.proposed||[],()=>{amenityError='';syncControls();});
      ready=true;
      const url=new URL(window.location.href);url.hash='station='+encodeURIComponent(id);window.history.replaceState(null,'',url);
      const uploads=document.getElementById("station-staging-list");uploads.replaceChildren();
      for(const file of staged){const li=document.createElement("li"),remove=document.createElement("button");li.append(document.createTextNode(file.name+" "));remove.textContent="Xóa nháp";remove.className="text-primary underline";remove.addEventListener("click",()=>action(async()=>{await api(base()+`/evidence/staging/${file.token}`,{method:"DELETE"});await choose(selected.tx_ma,true);}));li.append(remove);uploads.append(li);}
      const box=document.getElementById("station-approval-history");box.replaceChildren();
      if(!history||!history.length){
        const empty=document.createElement("p");
        empty.className="text-xs text-secondary italic";
        empty.textContent="Chưa có lịch sử cập nhật hồ sơ nào.";
        box.append(empty);
      }else{
        for(const req of history){
          const article=document.createElement("article");
          article.className="border border-outline-variant/30 p-3.5 rounded-xl bg-white space-y-2";
          let badgeClass='bg-slate-100 text-slate-800 border-slate-300';
          if(req.ycdt_trangthai==='DA_DUYET') badgeClass='bg-emerald-100 text-emerald-800 border-emerald-300';
          else if(req.ycdt_trangthai==='CHO_DUYET') badgeClass='bg-amber-100 text-amber-800 border-amber-300';
          else if(req.ycdt_trangthai==='CAN_BO_SUNG') badgeClass='bg-blue-100 text-blue-800 border-blue-300';
          else if(req.ycdt_trangthai==='TU_CHOI') badgeClass='bg-rose-100 text-rose-800 border-rose-300';
          const topDiv=document.createElement("div");
          topDiv.className="flex items-center justify-between text-xs";
          topDiv.innerHTML=`<span class="font-bold text-primary">Lần #${req.ycdt_lan_gui} — ${req.ycdt_loai==='DANG_KY_MOI'?'Đăng ký mới':'Cập nhật trạm'}</span><span class="px-2 py-0.5 rounded-full text-[10px] font-bold border ${badgeClass}">${req.ycdt_trangthai}</span>`;
          const p=document.createElement("p");
          p.className="text-xs text-secondary";
          p.textContent=`${req.ycdt_trangthai} — ${req.ycdt_lydo||"Hồ sơ lịch sử"}${req.ycdt_dulieu.activation_actor?" — Doanh nghiệp: "+req.ycdt_dulieu.activation_actor+" — "+req.ycdt_dulieu.activation_method:""}${req.ycdt_ngayxuly?" — "+req.ycdt_ngayxuly:""}`;
          const files=document.createElement("ul");
          files.className="text-xs space-y-1 list-disc pl-4 text-primary";
          evidence(files,req.tep_minh_chung);
          article.append(topDiv,p,files);
          if(req.ycdt_dulieu.amenity_change||Array.isArray(req.ycdt_dulieu.amenities)){
            const details=document.createElement('details'),summary=document.createElement('summary'),diff=document.createElement('div');
            details.className="text-xs pt-1";
            summary.className="cursor-pointer text-primary font-medium";
            summary.textContent='Xem tiện ích trong hồ sơ đã nộp';
            amenities.review(diff,req.ycdt_dulieu.amenity_change,req.ycdt_loai==='DANG_KY_MOI'?req.ycdt_dulieu.amenities:undefined);
            details.append(summary,diff);
            article.append(details);
          }
          box.append(article);
        }
      }
    }
    function reset(){selected=null;staged=[];persistedIds=[];pending=false;ready=false;amenityError='';staleSelection=false;form.reset();document.getElementById("station-staging-list").replaceChildren();document.getElementById("station-approval-history").replaceChildren();document.getElementById("station-version-note").textContent="Nhập GPS thực tế; hệ thống không tự gán tọa độ.";
      amenityBox.textContent='Lưu trạm nháp trước để tải danh mục và chọn tiện ích.';document.getElementById('station-current-amenities').textContent='';
      const url=new URL(window.location.href);url.hash='';window.history.replaceState(null,'',url);syncControls();}
    document.getElementById("new-station-draft").addEventListener("click",()=>{
      if(!busy&&mayDiscard()){
        reset();
        if(typeof window.openStationModal === 'function') {
          window.openStationModal('create');
        }
        const f=document.getElementById("station-draft-form");
        if(f){
          f.elements['tx_ten']?.focus();
        }
      }
    });
    form.addEventListener("submit",e=>{e.preventDefault();action(async()=>{const data=formValues(),keep=ready;if(selected){await api(base(),json("PATCH",data));}else{selected=await api("/api/enterprise/stations",json("POST",data));}await list();await choose(selected.tx_ma,keep,true);message.textContent="Đã lưu trạm nháp; lưu riêng thay đổi tiện ích trước khi nộp.";});});
    saveAmenities.addEventListener('click',()=>action(async()=>{
      if(!ready||staleSelection||!draftEditable())throw new Error('Tải lại trạm nháp có thể chỉnh sửa trước khi lưu tiện ích.');
      try{
        const rows=await api(base()+'/services',json('PUT',{service_ids:amenities.checkedIds(amenityBox),expected_amenity_ids:persistedIds}));
        persistedIds=rows.map(row=>row.dv_ma);showCurrent(persistedIds);amenityError='';message.textContent='Đã lưu toàn bộ tiện ích nháp. Trạm vẫn chưa công khai.';
      }catch(error){amenityError='Lưu tiện ích thất bại; chưa xác nhận thay đổi. '+error.message;throw error;}
    }));
    document.getElementById("upload-station-evidence").addEventListener("click",()=>action(async()=>{if(!selected)throw new Error("Lưu trạm nháp trước khi tải minh chứng.");const file=document.getElementById("station-evidence-file").files[0];if(!file||file.size>5*1024*1024)throw new Error("Chọn PDF/PNG/JPEG không quá 5 MB.");const body=new FormData();body.append("file",file);await api(base()+"/evidence/staging",{method:"POST",body});document.getElementById("station-evidence-file").value="";await choose(selected.tx_ma,true);message.textContent="Minh chứng đã lưu riêng tư.";}));
    document.getElementById("submit-station-approval").addEventListener("click",()=>action(async()=>{if(!selected||!ready)throw new Error("Lưu nháp trạm trước khi kích hoạt.");if(pending)throw new Error("Hồ sơ lịch sử đang chờ xử lý; cần chủ máy đối soát.");if(document.getElementById("station-evidence-file").files.length)throw new Error("File mới chỉ được chọn. Bấm Tải Lên Minh Chứng trước.");if(!staged.length)throw new Error("Chưa có minh chứng đã tải lên cho lần kích hoạt/cập nhật này.");if(staleSelection)throw new Error('Trạm đã thay đổi ở phiên khác; tải lại trước khi nộp.');if(selected.tx_phienban_hientai===0&&amenityDirty())throw new Error('Có tiện ích chưa lưu. Lưu toàn bộ tập trước khi kích hoạt.');if(!confirm("Xác nhận kích hoạt/cập nhật trạm theo thông tin, tiện ích và minh chứng đã lưu?"))return;const proposed=formValues();const result=await api(base()+"/activate",json("POST",{evidence_tokens:staged.map(f=>f.token),proposed_values:proposed,base_version:selected.tx_phienban_hientai,
      proposed_amenity_ids:selected.tx_phienban_hientai>0?amenities.checkedIds(amenityBox):null,
      expected_amenity_ids:selected.tx_phienban_hientai===0?persistedIds:null}));if(result.ycdt_trangthai!=="DA_DUYET"||result.ycdt_dulieu?.activation_method!=="SELF_SERVICE_DEMO")throw new Error("Backend chưa xác nhận kích hoạt; tải lại hồ sơ.");await list();await choose(selected.tx_ma,false,true);message.textContent=`${selected.tx_ten}: ${selected.tx_trangthai}, phiên bản ${selected.tx_phienban_hientai}.`;if(typeof loadAllEnterpriseData==="function")await loadAllEnterpriseData(selected.tx_ma);}));
    document.getElementById('refresh-station-proposal').addEventListener('click',()=>action(async()=>{if(selected)await choose(selected.tx_ma);await list();message.textContent='Đã tải lại trạng thái và phản hồi; khôi phục tập đã nộp nếu cần sửa/gửi lại.';}));
    document.getElementById("station-evidence-file").addEventListener("change",()=>{message.textContent="File đã chọn, chưa tải lên. Bấm Tải Lên Minh Chứng và kiểm tra danh sách tài liệu đã lưu.";});
    window.addEventListener('focus',()=>action(list)); // Does not erase unsent proposals.
    window.addEventListener('beforeunload',event=>{if(amenityDirty()&&!pending){event.preventDefault();event.returnValue='';}});
    const initialId=new URLSearchParams(window.location.hash.slice(1)).get('station');
    reset();action(async()=>{await list();if(initialId)await choose(initialId,false,true);});
  }else{
    async function detail(id){selected=await api(`/api/admin/station-approvals/${id}`);document.getElementById("station-admin-detail").classList.remove("hidden");document.getElementById("station-admin-title").textContent=`${selected.ycdt_dulieu.tx_ten} — ${selected.ycdt_loai} — Lần ${selected.ycdt_lan_gui}`;document.getElementById("station-admin-snapshot").textContent=JSON.stringify(selected.ycdt_dulieu,null,2);document.getElementById("station-admin-feedback").textContent=selected.ycdt_lydo||selected.ycdt_trangthai;document.getElementById("station-admin-reason").value="";evidence(document.getElementById("station-admin-evidence"),selected.tep_minh_chung);page.querySelectorAll(".station-decision").forEach(b=>b.disabled=selected.ycdt_trangthai!=="CHO_DUYET");
      window.PetroStationAmenities.review(document.getElementById('station-admin-amenity-review'),selected.ycdt_dulieu.amenity_change,selected.ycdt_loai==='DANG_KY_MOI'?selected.ycdt_dulieu.amenities:undefined);
      const lat=Number(selected.ycdt_dulieu.tx_vido),lon=Number(selected.ycdt_dulieu.tx_kinhdo);
      const valid=selected.ycdt_dulieu.tx_vido!=null&&selected.ycdt_dulieu.tx_kinhdo!=null&&String(selected.ycdt_dulieu.tx_vido).trim()!==""&&String(selected.ycdt_dulieu.tx_kinhdo).trim()!==""&&Number.isFinite(lat)&&Number.isFinite(lon)&&lat>=-90&&lat<=90&&lon>=-180&&lon<=180; document.getElementById("station-review-map").classList.toggle("hidden",!valid); if(valid&&typeof L!=="undefined"){if(!map){map=L.map("station-review-map");L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:"© OpenStreetMap contributors"}).addTo(map);}map.setView([lat,lon],15);if(marker)marker.remove();marker=L.marker([lat,lon]).addTo(map);requestAnimationFrame(()=>map.invalidateSize());}
    }
    async function list(){const status=document.getElementById("station-admin-filter").value;const rows=await api(`/api/admin/station-approvals?status=${status}&limit=20&offset=${offset}`);const box=document.getElementById("station-admin-list");box.replaceChildren();if(!rows.length)box.textContent="Không có yêu cầu trạm.";for(const row of rows){const b=document.createElement("button");b.className="btn-secondary block w-full";b.textContent=`${row.ycdt_dulieu.tx_ten} — ${row.ycdt_loai} — ${row.ycdt_trangthai}`;b.addEventListener("click",()=>action(()=>detail(row.ycdt_ma)));box.append(b);}document.getElementById("station-admin-prev").disabled=offset===0;document.getElementById("station-admin-next").disabled=rows.length<20;}
    document.getElementById("station-admin-filter").addEventListener("change",()=>action(async()=>{offset=0;selected=null;document.getElementById("station-admin-detail").classList.add("hidden");await list();}));
    for(const[id,step]of[["station-admin-prev",-20],["station-admin-next",20]])document.getElementById(id).addEventListener("click",()=>action(async()=>{offset=Math.max(0,offset+step);await list();}));
    page.querySelectorAll(".station-decision").forEach(b=>b.addEventListener("click",()=>action(async()=>{if(!selected)return;const decision=b.dataset.decision,reason=document.getElementById("station-admin-reason").value.trim();if(decision!=="DA_DUYET"&&!reason)throw new Error("Cần nhập lý do.");if(!confirm(`Xác nhận ${decision} cho riêng trạm này?`))return;const id=selected.ycdt_ma;await api(`/api/admin/station-approvals/${id}/decision`,json("POST",{decision,reason:reason||null}));await detail(id);await list();message.textContent="Đã lưu quyết định trạm.";})));
    action(list);
  }
})();
