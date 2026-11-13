/* Private dashboard presentation only. Backend ownership is always authoritative. */
(function(root){
  'use strict';
  function createScope(){
    let epoch=0,sid=null;const requests=new Map();
    return {
      select(id){epoch++;sid=id||null;requests.clear();},
      capture(){return {epoch,sid};},
      begin(resource){const serial=(requests.get(resource)||0)+1;requests.set(resource,serial);return {epoch,sid,resource,serial};},
      current(t){return !!t&&!!sid&&t.epoch===epoch&&t.sid===sid&&(!t.resource||requests.get(t.resource)===t.serial);}
    };
  }
  const accessible=rows=>(rows||[]).filter(s=>s.tx_trangthai==='DA_DUYET'&&s.tx_congkhai===true);
  function choose(rows,wanted){const stations=accessible(rows);return {stations,selected:stations.find(s=>s.tx_ma===wanted)||stations[0]||null,missing:!!wanted&&!stations.some(s=>s.tx_ma===wanted)};}
  function operationURL(href,sid,tab){const url=new URL(href);if(sid)url.searchParams.set('ops_station',sid);else url.searchParams.delete('ops_station');if(tab)url.searchParams.set('ops_tab',tab);return url;}
  const names={
    NL000001:['Bồn E10 RON95-III','Trụ số 1 – E10 RON95-III'],
    NL000002:['Bồn E5 RON92-II','Trụ số 2 – E5 RON92-II'],
    NL000003:['Bồn dầu DO 0,05S-II','Trụ số 3 – DO 0,05S-II']
  };
  function equipment(row,sid,kind){
    const tank=kind==='tank',raw=tank?row.tank_name:row.pump_name;
    const id=tank?row.tank_id:row.pump_id;
    const match=/^DEMO58C_(TX00000[1-6])_(NL00000[1-3])_([TP])$/.exec(String(id));
    const fid=match?.[2];
    const recognized=!!match&&match[1]===sid&&match[3]===(tank?'T':'P')&&
      (tank?row.nl_ma===fid:row.fuels?.length===1&&row.fuels[0]===fid&&row.pump_code==='DEMO58C_F'+fid.slice(-1));
    if(!recognized)return {label:raw||id||'',note:'',demo:false};
    const original=tank?`DEMO synthetic ${fid} tank`:`DEMO ${fid} SYNTHETIC ZERO BASELINE - NOT PHYSICAL`;
    return {label:raw===original?names[fid][tank?0:1]:raw,
      note:tank?'DEMO · dữ liệu kho giả lập Phase 5.8C.':'DEMO · mốc đồng hồ ban đầu 0 L là giả lập, chưa xác minh vật lý.',demo:true};
  }
  // Orders/history DTOs may carry a name without an equipment ID. Only substitute
  // through an actual current inventory row, never infer provenance from text alone.
  function tankLabel(raw,inventory,sid){const row=inventory?.tanks?.find(t=>t.tank_name===raw);return row?equipment(row,sid,'tank').label:raw;}
  const api={createScope,accessible,choose,operationURL,equipment,tankLabel};
  root.PetroEnterpriseUI=api;
  if(typeof module!=='undefined')module.exports=api;
})(typeof window==='undefined'?globalThis:window);
