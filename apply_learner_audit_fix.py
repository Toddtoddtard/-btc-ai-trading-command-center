from pathlib import Path
import ast

p = Path('learner.py')
text = p.read_text()

text = text.replace("SPOT='https://data-api.binance.vision'\nKALSHI=", "SPOT='https://data-api.binance.vision'\nFUTURES='https://fapi.binance.com'\nKALSHI=")

start = text.index('def market():')
end = text.index('\ndef calls(', start)
new_market = '''def strike(m):
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

'''
text = text[:start] + new_market + text[end+1:]

start = text.index('def calls(d,m):')
end = text.index('\ndef register(', start)
new_calls = '''def calls(d,m,micro):
    z=d.iloc[-1]; p=float(z.close); r3=p/float(d.close.iloc[-4])-1; r8=p/float(d.close.iloc[-9])-1; r15=p/float(d.close.iloc[-16])-1
    trend=.55*np.sign(z.ema9-z.ema21)+.45*np.sign(z.ema21-z.ema50); mom=np.clip((float(z.rsi)-50)/30,-1,1)
    body=float(z.close-z.open); rng=max(float(z.high-z.low),1); pattern=np.clip(body/rng,-1,1)
    vm=float(d.volume.tail(30).mean()); vs=float(d.volume.tail(30).std()); vz=(float(z.volume)-vm)/vs if vs>0 else 0.0; volume=np.clip(np.sign(body)*min(abs(vz)/2.5,1),-1,1)
    sr=np.clip((.5-(p-float(d.low.tail(60).min()))/max(float(d.high.tail(60).max()-d.low.tail(60).min()),1))*1.4,-1,1); regime=np.clip(np.sign(z.ema9-z.ema50)*abs(float(z.ema9-z.ema50))/max(p*.003,1),-1,1); event=np.clip(.55*((m['prob']-.5)*2)+.45*((p-m['target'])/max(p*.0025,1)),-1,1)
    base={'Trend AI':trend,'Momentum AI':mom,'Volume AI':volume,'Pattern AI':pattern,'Support/Resistance AI':sr,'Volatility AI':-np.clip((p-float(d.close.tail(20).mean()))/max(float(d.close.tail(20).std())*3,1),-1,1),'Market Regime AI':regime,'Whale AI':micro.get('whale',0.0),'Liquidity AI':micro.get('liquidity',0.0),'Derivatives AI':micro.get('derivatives',0.0),'Event AI':event,'Historical Pattern AI':np.clip(r3/.003,-1,1)}
    base['Combination AI']=float(np.mean(list(base.values())))
    return {n:{'score':float(np.clip(v,-1,1)),'confidence':float(min(.99,.48+abs(v)*.48))} for n,v in base.items()},(r3,r8,r15)

'''
text = text[:start] + new_calls + text[end+1:]

text = text.replace("p=float(d.close.iloc[-1]); bot,rets=calls(d,m); f=s['forecast'];", "p=float(d.close.iloc[-1]); bot,rets=calls(d,m,microstructure()); f=s['forecast'];")

ast.parse(text)
p.write_text(text)
print('learner.py audited target + specialist feed fix applied')
