#!/usr/bin/env python3
import json, math, os, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import numpy as np
import pandas as pd

SPOT='https://data-api.binance.vision'
FUTURES='https://fapi.binance.com'
KALSHI='https://external-api.kalshi.com/trade-api/v2'
STATE='https://raw.githubusercontent.com/Toddtoddtard/-btc-ai-trading-command-center/learning-state/learning_state.json'
OUT=Path(os.getenv('LEARNING_STATE_OUTPUT','/tmp/learning_state.json'))
BOTS=['Trend AI','Momentum AI','Volume AI','Pattern AI','Support/Resistance AI','Volatility AI','Market Regime AI','Whale AI','Liquidity AI','Derivatives AI','Event AI','Historical Pattern AI','Combination AI']

def get(url,params=None):
    if params:url+='?'+urlencode(params)
    r=Request(url,headers={'User-Agent':'BTC-AI-24x7/1.0','Accept':'application/json','Cache-Control':'no-cache'})
    with urlopen(r,timeout=10) as x:return json.loads(x.read().decode())

def fresh():
    specs={n:{'adaptive_weight':1.0,'samples':0,'direction_hits':0,'ewma_accuracy':.5,'ewma_edge':0.0,'ewma_calibration':0.0} for n in BOTS}
    return {'version':1,'updated_at':None,'forecast':{'w_ret3':.46,'w_ret8':.34,'w_ret15':.20,'momentum_scale':2.2,'target_influence':.18,'bias':0.0,'learning_rate':.08,'samples':0,'direction_hits':0,'avg_abs_error':0.0,'avg_path_error':0.0},'specialists':specs,'master_history':[],'specialist_history':{n:[] for n in BOTS},'pending':None,'status':{}}

def load():
    try:
        s=get(STATE)
        if isinstance(s,dict) and 'forecast' in s:
            d=fresh(); d.update(s); d['forecast'].update(s.get('forecast',{}))
            for n in BOTS:
                d['specialists'].setdefault(n,fresh()['specialists'][n]); d['specialist_history'].setdefault(n,[])
            return d
    except Exception:pass
    return fresh()

def history():
    a=get(SPOT+'/api/v3/klines',{'symbol':'BTCUSDT','interval':'1m','limit':240})
    c=['ot','open','high','low','close','volume','ct','qv','trades','tb','tq','x']
    d=pd.DataFrame(a,columns=c)
    for k in ['open','high','low','close','volume']:d[k]=pd.to_numeric(d[k],errors='coerce')
    d['time']=pd.to_datetime(d.ot,unit='ms',utc=True)
    d['ema9']=d.close.ewm(span=9,adjust=False).mean(); d['ema21']=d.close.ewm(span=21,adjust=False).mean(); d['ema50']=d.close.ewm(span=50,adjust=False).mean()
    delta=d.close.diff(); gain=delta.clip(lower=0).rolling(14).mean(); loss=(-delta.clip(upper=0)).rolling(14).mean(); rs=gain/loss.replace(0,np.nan); d['rsi']=(100-100/(1+rs)).fillna(50)
    d['atr']=(d.high-d.low).rolling(14).mean().bfill(); return d

def strike(m):
    if not isinstance(m,dict): return None
    stype=str(m.get('strike_type') or '').lower()
    keys=('cap_strike','floor_strike') if stype in {'less','less_equal','less-than','less_than'} else ('floor_strike','cap_strike')
    for k in keys:
        try:
            v=float(m.get(k))
            if math.isfinite(v) and v>0:return v
        except Exception:pass
    return None

def market():
    try:m=get(KALSHI+'/markets',{'limit':100,'status':'open','series_ticker':'KXBTC15M'}).get('markets',[])
    except Exception:return None
    now=time.time(); out=[]
    for x in m:
        try:
            exp=pd.Timestamp(x.get('close_time') or x.get('expiration_time') or x.get('expected_expiration_time')).timestamp()
            k=strike(x)
            if exp>now and k is not None:out.append((exp,str(x.get('ticker','')),x,k))
        except Exception:pass
    if not out:return None
    exp,ticker,x,k=sorted(out,key=lambda z:(z[0],z[1]))[0]
    try:
        exact=get(KALSHI+'/markets/'+ticker).get('market',{})
        ek=strike(exact)
        if ek is not None:k=ek
        eraw=exact.get('close_time') or exact.get('expiration_time') or exact.get('expected_expiration_time')
        if eraw:exp=pd.Timestamp(eraw).timestamp()
        if exact:x={**x,**exact}
    except Exception:pass
    vals=[]
    for key in ['yes_bid_dollars','yes_ask_dollars']:
        try:vals.append(float(x[key]))
        except Exception:pass
    return {'ticker':ticker,'expires_at':exp,'target':float(k),'prob':sum(vals)/len(vals) if vals else .5}

def microstructure():
    out={'whale':0.0,'liquidity':0.0,'derivatives':0.0}
    try:
        a=get(SPOT+'/api/v3/aggTrades',{'symbol':'BTCUSDT','limit':700})
        rows=[]
        for r in a:
            pr=float(r['p']); q=float(r['q']); n=pr*q; side='SELL' if bool(r.get('m')) else 'BUY'; rows.append((n,side))
        buy=sum(n for n,s in rows if s=='BUY'); sell=sum(n for n,s in rows if s=='SELL'); total=buy+sell; flow=(buy-sell)/total if total else 0.0
        vals=np.array([n for n,_ in rows],dtype=float); med=float(np.median(vals)) if len(vals) else 0.0; cutoff=max(med*6,50000.0)
        wb=sum(n for n,s in rows if n>=cutoff and s=='BUY'); ws=sum(n for n,s in rows if n>=cutoff and s=='SELL'); wt=wb+ws; wflow=(wb-ws)/wt if wt else flow
        out['whale']=float(np.clip(.55*flow*3+.45*wflow*3,-1,1))
    except Exception:pass
    book=0.0; funding=0.0
    try:
        depth=get(FUTURES+'/fapi/v1/depth',{'symbol':'BTCUSDT','limit':20})
        bids=sum(float(x[0])*float(x[1]) for x in depth.get('bids',[])); asks=sum(float(x[0])*float(x[1]) for x in depth.get('asks',[])); den=bids+asks; book=(bids-asks)/den if den else 0.0
        out['liquidity']=float(np.clip(book*3,-1,1))
    except Exception:pass
    try:
        prem=get(FUTURES+'/fapi/v1/premiumIndex',{'symbol':'BTCUSDT'}); funding=float(prem.get('lastFundingRate') or 0.0)
    except Exception:pass
    out['derivatives']=float(np.clip(book*1.6-np.sign(funding)*min(abs(funding)/.0005,1)*.25,-1,1))
    return out

def calls(d,m,micro):
    z=d.iloc[-1]; p=float(z.close); r3=p/float(d.close.iloc[-4])-1; r8=p/float(d.close.iloc[-9])-1; r15=p/float(d.close.iloc[-16])-1
    trend=.55*np.sign(z.ema9-z.ema21)+.45*np.sign(z.ema21-z.ema50); mom=np.clip((float(z.rsi)-50)/30,-1,1)
    body=float(z.close-z.open); rng=max(float(z.high-z.low),1); pattern=np.clip(body/rng,-1,1)
    vm=float(d.volume.tail(30).mean()); vs=float(d.volume.tail(30).std()); vz=(float(z.volume)-vm)/vs if vs>0 else 0.0; volume=np.clip(np.sign(body)*min(abs(vz)/2.5,1),-1,1)
    sr=np.clip((.5-(p-float(d.low.tail(60).min()))/max(float(d.high.tail(60).max()-d.low.tail(60).min()),1))*1.4,-1,1); regime=np.clip(np.sign(z.ema9-z.ema50)*abs(float(z.ema9-z.ema50))/max(p*.003,1),-1,1); event=np.clip(.55*((m['prob']-.5)*2)+.45*((p-m['target'])/max(p*.0025,1)),-1,1)
    base={'Trend AI':trend,'Momentum AI':mom,'Volume AI':volume,'Pattern AI':pattern,'Support/Resistance AI':sr,'Volatility AI':-np.clip((p-float(d.close.tail(20).mean()))/max(float(d.close.tail(20).std())*3,1),-1,1),'Market Regime AI':regime,'Whale AI':micro.get('whale',0.0),'Liquidity AI':micro.get('liquidity',0.0),'Derivatives AI':micro.get('derivatives',0.0),'Event AI':event,'Historical Pattern AI':np.clip(r3/.003,-1,1)}
    base['Combination AI']=float(np.mean(list(base.values())))
    return {n:{'score':float(np.clip(v,-1,1)),'confidence':float(min(.99,.48+abs(v)*.48))} for n,v in base.items()},(r3,r8,r15)

def register(s,d,m):
    if not m or s.get('pending') is not None:return False
    p=float(d.close.iloc[-1]); bot,rets=calls(d,m,microstructure()); f=s['forecast']; directional=f['w_ret3']*rets[0]+f['w_ret8']*rets[1]+f['w_ret15']*rets[2]+f['bias']; move=p*np.clip(directional,-.012,.012)*f['momentum_scale']; move+=np.clip((m['target']-p)*f['target_influence'],-p*.003,p*.003); pred=p+move
    s['pending']={'ticker':m['ticker'],'opened_at':time.time(),'expires_at':m['expires_at'],'target':m['target'],'start_price':p,'predicted_end':pred,'predicted_direction':1 if pred>=p else -1,'ret3':rets[0],'ret8':rets[1],'ret15':rets[2],'specialists':bot}; return True

def grade(s,d):
    q=s.get('pending')
    if not q or time.time()<q['expires_at']:return False
    expiry=pd.to_datetime(q['expires_at'],unit='s',utc=True); row=d.iloc[(d.time-expiry).abs().argsort()[:1]]
    if row.empty:return False
    actual=float(row.iloc[0].close); start=q['start_price']; ad=1 if actual>=start else -1; correct=int(ad==q['predicted_direction']); err=actual-q['predicted_end']; f=s['forecast']; lr=f['learning_rate']; feats=np.array([q['ret3'],q['ret8'],q['ret15']]); scale=max(float(abs(feats).sum()),1e-6); adj=lr*(err/start)*(feats/scale)*8
    w=np.clip(np.array([f['w_ret3'],f['w_ret8'],f['w_ret15']])+adj,.05,.9); w=w/w.sum(); f['w_ret3'],f['w_ret8'],f['w_ret15']=map(float,w); f['bias']=float(np.clip(f['bias']+lr*(err/start)*.12,-.004,.004)); f['samples']+=1; f['direction_hits']+=correct; n=f['samples']; ae=abs(err); f['avg_abs_error']=ae if n==1 else f['avg_abs_error']+(ae-f['avg_abs_error'])/n
    s['master_history'].append({'ticker':q['ticker'],'expires_at':q['expires_at'],'direction_correct':correct,'abs_error':ae,'path_error':ae}); s['master_history']=s['master_history'][-1000:]; realized=actual/start-1
    for name,c in q['specialists'].items():
        x=s['specialists'][name]; score=c['score']; pdirection=1 if score>.03 else -1 if score<-.03 else 0; hit=int(pdirection!=0 and pdirection==ad); edge=score*realized*100 if pdirection else 0; cal=c['confidence'] if hit else -c['confidence']; a=.1; x['ewma_accuracy']=(1-a)*x['ewma_accuracy']+a*hit; x['ewma_edge']=(1-a)*x['ewma_edge']+a*edge; x['ewma_calibration']=(1-a)*x['ewma_calibration']+a*cal; x['samples']+=1; x['direction_hits']+=hit; quality=.55*(x['ewma_accuracy']-.5)*2+.25*np.tanh(x['ewma_edge']*4)+.20*x['ewma_calibration']; target=float(np.clip(1+quality,.35,1.85)); x['adaptive_weight']=float(np.clip(.9*x['adaptive_weight']+.1*target,.35,1.85)); s['specialist_history'][name].append({'ticker':q['ticker'],'expires_at':q['expires_at'],'direction_correct':hit,'signed_edge':edge}); s['specialist_history'][name]=s['specialist_history'][name][-1000:]
    s['pending']=None; s['status']['last_graded_ticker']=q['ticker']; return True

def main():
    s=load(); d=history(); m=market(); graded=grade(s,d); registered=register(s,d,m); s['updated_at']=datetime.now(timezone.utc).isoformat(); s['status'].update({'worker_ok':True,'graded_this_run':graded,'registered_this_run':registered,'btc_price':float(d.close.iloc[-1]),'active_ticker':m['ticker'] if m else '','active_target':m['target'] if m else None,'forecast_samples':s['forecast']['samples']}); OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(s,indent=2,sort_keys=True)); print(json.dumps(s['status'],indent=2))

if __name__=='__main__':main()
