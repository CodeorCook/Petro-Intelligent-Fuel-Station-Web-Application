/* Read-only advisory UI. Server rechecks every write; stale replies never enable submit. */
(function(root){
  'use strict';
  const codes=['NL000001','NL000002','NL000003'];
  function fuelOrder(rows,key){return [...rows].sort((a,b)=>{
    const x=String(key(a)).trim(), y=String(key(b)).trim();
    const rank=x=>codes.includes(x)?codes.indexOf(x):codes.length;
    return rank(x)-rank(y)||x.localeCompare(y);
  });}
  function create(fetcher,render,delay=250){
    let version=0,timer=null,params=null;
    const loading=()=>render({orderable:false,loading:true,message:'Đang kiểm tra điều kiện tiếp nhận…'});
    async function refresh(){
      clearTimeout(timer);const mine=++version, current=params;loading();
      if(!current){render({orderable:false,message:'Chọn trạm và nhiên liệu để kiểm tra.'});return false;}
      const mode=current.query.mode;
      if(mode==='SO_LIT'||mode==='SO_TIEN'){
        const value=Number(mode==='SO_LIT'?current.query.liters:current.query.budget);
        if(!Number.isFinite(value)||value<=0||value>=(mode==='SO_LIT'?1000000:100000000)){
          render({orderable:false,message:'Vui lòng nhập định mức tiền/lít hợp lệ.'});return false;
        }
      }
      try{
        const q=new URLSearchParams(current.query);
        const response=await fetcher(`/api/workflow/station-info/${encodeURIComponent(current.station)}/readiness?${q}`,{cache:'no-store'});
        if(!response.ok)throw new Error('readiness unavailable');
        const value=await response.json();
        if(mine!==version)return false;
        render(value);return value.orderable===true;
      }catch(error){
        if(mine===version)render({orderable:false,error:true,message:'Không thể kiểm tra điều kiện tiếp nhận. Vui lòng thử lại.'});
        return false;
      }
    }
    function update(value){params=value;++version;clearTimeout(timer);loading();timer=setTimeout(refresh,delay);}
    function dispose(){++version;clearTimeout(timer);params=null;}
    return {update,refresh,dispose};
  }
  root.PetroOrderReadiness={create,fuelOrder};
  if(typeof module!=='undefined')module.exports=root.PetroOrderReadiness;
})(typeof window!=='undefined'?window:globalThis);
