"""Corroborate an official release with a stable, complete public price widget.
Image OCR is never sufficient alone: both region columns and all three exact
products must agree with two independently fetched structured widget snapshots.
"""
import asyncio,json,re,subprocess,tempfile
from pathlib import Path
from datetime import datetime,time,timedelta,timezone
from urllib.parse import urljoin,urlparse
from bs4 import BeautifulSoup
from app.services import fuel_crawler as c


def image_values(lines, payload):
    headers={}
    for line in lines:
        t=line['text'].lower()
        m=re.fullmatch(r'v(?:u|i|ù|ü)ng\s+([12])',t)
        if m:headers[m[1]]=line['words']
    if set(headers)!={'1','2'}:raise c.FuelCrawlerParseError('Image lacks explicit region headers')
    centers={k:sum(w['x']+w['width']/2 for w in v)/len(v) for k,v in headers.items()}
    if centers['2']<=centers['1']:raise c.FuelCrawlerParseError('Ambiguous region columns')
    products={c._map_petrolimex_api_product(i):i for i in payload['Objects'] if c._map_petrolimex_api_product(i)}
    values={};words=[w for line in lines for w in line['words']]
    for line in lines:
        left=[w for w in line['words'] if w['x']<centers['1']-100]
        label=' '.join(w['text'] for w in left).lower().replace('eio','e10').replace('o,05s','0,05s')
        fuel=None
        if re.search(r'e10\s+ron\s*95',label) and re.search(r'\b3$',label):fuel='NL000001'
        elif re.search(r'e5\s+ron\s*92',label) and re.search(r'\b2$',label):fuel='NL000002'
        elif '0,05s' in label and re.search(r'\b2$',label):fuel='NL000003'
        if not fuel:continue
        y=sum(w['y']+w['height']/2 for w in left)/len(left)
        for region in ('1','2'):
            candidates=[w for w in words if abs(w['y']+w['height']/2-y)<12 and abs(w['x']+w['width']/2-centers[region])<85 and re.fullmatch(r'\d{2,3}[.,]\d{3}',w['text'])]
            if len(candidates)!=1 or c.parse_vnd_price(candidates[0]['text'])!=c.Decimal(str(products[fuel]['Zone'+region+'Price'])):
                raise c.FuelCrawlerParseError('Release image and widget disagree or image cells ambiguous')
        if fuel in values:raise c.FuelCrawlerParseError('Duplicate image fuel row')
        values[fuel]=True
    if set(values)!=set(products):raise c.FuelCrawlerParseError('Image does not corroborate all three exact fuel grades')

async def corroborate(session,html,payload,period):
    try:
        release=c.parse_petrolimex_html(html)
        widget=c.parse_petrolimex_api_payload(payload,effective_period=period)
        if {(p.fuel_id,p.price) for p in release}!={(p.fuel_id,p.price) for p in widget}:raise c.FuelCrawlerParseError('Release table/widget mismatch')
        return widget
    except c.FuelCrawlerParseError:
        pass
    images=[urljoin(c.PETROLIMEX_PRICE_URL,i['src']) for i in BeautifulSoup(html,'html.parser').select('img[src]') if '/jpgs/' in i['src'] or '/pngs/' in i['src']]
    for url in images[:3]:
        if urlparse(url).hostname!='files.petrolimex.com.vn':continue
        try:
            r=await session.get(url,timeout=10)
            if r.status_code!=200 or len(r.content)>8000000:continue
            with tempfile.TemporaryDirectory(prefix='petro-price-') as folder:
                path=Path(folder)/'release.img';path.write_bytes(r.content)
                def read():
                    p=subprocess.run(['powershell','-NoProfile','-File',str(Path(__file__).with_name('petrolimex_ocr.ps1')),'-ImagePath',str(path)],capture_output=True,encoding='utf-8-sig',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=20)
                    if p.returncode:raise c.FuelCrawlerParseError('Image verification engine unavailable')
                    return json.loads(p.stdout)
                image_values(await asyncio.to_thread(read),payload)
                return c.parse_petrolimex_api_payload(payload,effective_period=period)
        except (c.FuelCrawlerError,ValueError,subprocess.SubprocessError,OSError):continue
    raise c.FuelCrawlerParseError('Insufficient evidence: full official release table/image does not corroborate all widget prices')

async def verified_snapshot(session):
    landing=await c.fetch_petrolimex_text(session,c.PETROLIMEX_PRICE_URL,expected_content='html')
    links=c.find_petrolimex_announcements(landing)
    releases=[]
    for url in links[:6]:
        html=await c.fetch_petrolimex_text(session,url,expected_content='html')
        try:period=c._parse_petrolimex_effective_datetime(BeautifulSoup(html,'html.parser'))
        except c.FuelCrawlerError:continue
        releases.append((period,url,html))
    if not releases:raise c.FuelCrawlerParseError('No complete official effective-period announcement')
    period,url,html=max(releases,key=lambda r:(r[0][0],r[0][1] or ''))
    if not period[1] or datetime.combine(period[0],time.fromisoformat(period[1]),tzinfo=timezone(timedelta(hours=7)))>datetime.now(timezone.utc):
        raise c.FuelCrawlerParseError('Latest announced period is not yet effective')
    first=json.loads(await c.fetch_petrolimex_text(session,c._build_petrolimex_api_url(),expected_content='json'))
    prices=await corroborate(session,html,first,period)
    second=json.loads(await c.fetch_petrolimex_text(session,c._build_petrolimex_api_url(),expected_content='json'))
    def signature(data):return sorted((c._map_petrolimex_api_product(i),str(i.get('Zone1Price')),str(i.get('Zone2Price')),i.get('LastModified'),i.get('Status')) for i in data['Objects'] if c._map_petrolimex_api_product(i))
    if signature(first)!=signature(second):raise c.FuelCrawlerParseError('Widget changed during verification; retry later')
    again=await c.fetch_petrolimex_text(session,url,expected_content='html')
    if again!=html:raise c.FuelCrawlerParseError('Announcement changed during verification; retry later')
    return prices,url
