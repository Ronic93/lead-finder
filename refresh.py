#!/usr/bin/env python3
"""Lead finder: NL/BE advertisers from Meta Ad Library (+ Google Ads Transparency enrichment).
Public pages only. Never contacts anyone. Usage: python3 refresh.py [--push] [--quick]"""
import subprocess,re,json,sys,os,time,datetime,urllib.parse,concurrent.futures as cf
import requests
from bs4 import BeautifulSoup as B
D=os.path.dirname(os.path.abspath(__file__)); DATA=f"{D}/data/leads.json"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
NICHES={
 "fashion":["kledingwinkel","dameskleding","fashion webshop","jurken"],
 "beauty":["skincare","huidverzorging","serum"],
 "jewelry":["sieraden","handgemaakte sieraden","jewelry"],
 "haircare":["haarverzorging","haarolie","curly hair"],
 "perfume":["parfum","niche parfum"],
 "interior":["interieur","woonaccessoires","home decor"],
 "webshop":["webshop handgemaakt","conceptstore"],
}
BIG={"zara","h&m","hm","zalando","bol","bol.com","douglas","ici paris xl","rituals","kruidvat","etos","ikea","action","primark","nike","adidas","shein","temu","hema","wehkamp","otto","about you","sephora","loreal","l'oréal","pandora","swarovski","rosefield","lidl","aldi","albert heijn","jumbo","coolblue","mango","c&a","only","vero moda","jysk","leen bakker","xenos","kwantum","lush","the body shop","nivea","garnier","dove","isabel marant","gucci","prada"}
OFF=re.compile(r"alibaba|catawiki|auction|veiling|deals|marktplaats|vinted|amazon|goud(aankoop|inkoop)|inkoop|casino|crypto|lening|hypothe|vacature|webinar|cursus|coach|dokter|kliniek|tandarts|gemeente|partij",re.I)
def chrome(url,budget=15000):
  r=subprocess.run(["google-chrome","--headless=new","--no-sandbox","--disable-gpu","--user-agent="+UA,f"--virtual-time-budget={budget}","--dump-dom",url],capture_output=True,text=True,timeout=90)
  return r.stdout
def unwrap(h):
  if "l.facebook.com/l.php" in h:
    q=urllib.parse.parse_qs(urllib.parse.urlparse(h).query).get("u",[""])[0]; return q
  return h
def dom(u):
  try:
    n=urllib.parse.urlparse(u).netloc.lower()
    return n[4:] if n.startswith("www.") else n
  except: return ""
def meta_search(q,cc):
  url=f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country={cc}&q={urllib.parse.quote(q)}&search_type=keyword_unordered&media_type=all"
  s=B(chrome(url),"html.parser"); [t.decompose() for t in s(["style","script"])]
  out=[]
  for tn in s.find_all(string=re.compile("Library ID:")):
    c=tn.parent
    while c.parent and c.parent.get_text().count("Library ID:")<2: c=c.parent
    txt=c.get_text("\n",strip=True); lines=[l for l in txt.split("\n") if l.strip("\u200b ")]
    lid=re.search(r"Library ID:\s*(\d+)",txt).group(1)
    st=re.search(r"Started running on (\w+ \d+, \d{4})",txt)
    links=[a.get("href") for a in c.find_all("a") if a.get("href")]
    page=next((l for l in links if re.match(r"https://www\.facebook\.com/[^/]+/?$",l)),"")
    ext=[unwrap(l) for l in links if "l.facebook.com" in l]
    try: name=lines[lines.index("Sponsored")-1]
    except: continue
    i=lines.index("Sponsored"); body=" ".join(lines[i+1:i+4])[:300]
    vids=c.find_all("video"); imgs=[im.get("src") for im in c.find_all("img") if "scontent" in (im.get("src") or "")]
    mv=re.search(r"(\d+) ads\s*use this creative",txt.replace("\n"," "))
    out.append(dict(id=lid,name=name,page=page,site=dom(ext[0]) if ext else "",start=st.group(1) if st else "",
      video=bool(vids),img=(vids[0].get("poster") if vids else (imgs[-1] if imgs else "")),text=body,versions=int(mv.group(1)) if mv else 1,
      link=f"https://www.facebook.com/ads/library/?id={lid}",kw=q,cc=cc))
  return out
def google_count(d,cc):
  try:
    t=B(chrome(f"https://adstransparency.google.com/?region={cc}&domain={d}",10000),"html.parser").get_text(" ")
    m=re.search(r"([\d.,]+)\s*(?:\+\s*)?advertenties",t) or re.search(r"([\d.,]+)\s*ads",t)
    return int(re.sub(r"\D","",m.group(1))) if m else 0
  except Exception: return None
def contacts(d):
  r=dict(email="",instagram="",contact_url="")
  if not d or re.search(r"instagram|facebook|tiktok|alibaba|amazon|bol\.com|linktr|shopee|etsy",d): return r
  S=requests.Session(); S.headers["User-Agent"]=UA
  for p in ["","/contact","/pages/contact","/klantenservice","/contact-us"]:
    try:
      h=S.get(f"https://{d}{p}",timeout=8)
      if h.status_code!=200: continue
      if p and not r["contact_url"]: r["contact_url"]=h.url
      if not r["email"]:
        em=[e for e in re.findall(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?",h.text) if not re.search(r"\.(png|jpg|webp|svg|gif)$|sentry|example|unknown|domain\.com|email\.com|wixpress|shopify|@2x",e,re.I)]
        pref=[e for e in em if d.split(".")[0] in e]; r["email"]=(pref or em or [""])[0]
      if not r["instagram"]:
        ig=[x for x in re.findall(r"instagram\.com/([A-Za-z0-9_.]{2,30})",h.text) if x.lower() not in("p","reel","explore","accounts","shopify","instagram")]
        r["instagram"]=ig[0].rstrip(".") if ig else ""
      if r["email"] and r["instagram"]: break
    except Exception: pass
  return r
def score(a):
  why=[]; s=0
  n=a["ads"]; vs=a["video_ads"]/max(n,1)
  if vs==0: s+=35; why.append("alleen statische beelden")
  elif vs<0.34: s+=22; why.append("weinig video")
  else: s+=5
  if 2<=n<=25: s+=20; why.append(f"{n} actieve ads (actief budget)")
  elif n==1: s+=8
  else: s+=12; why.append(f"{n}+ ads (veel budget)")
  w={"fashion":20,"jewelry":20,"perfume":20,"beauty":16,"haircare":16,"interior":12,"webshop":10}[a["niche"]]; s+=w
  if a["oldest"] and (datetime.date.today()-a["oldest"]).days>90: s+=10; why.append("adverteert al >3 mnd")
  if a.get("google"): s+=5; why.append(f"ook {a['google']} Google-ads")
  if a["contact"].get("email") or a["contact"].get("instagram"): s+=5
  if not a["site"] or re.search(r"instagram|facebook|tiktok|etsy|linktr",a["site"]): s-=25; why.append("geen eigen webshop")
  if a["low_name"] in BIG: s-=60; why.append("groot merk")
  if OFF.search(a["name"]+" "+a["sample_text"]): s-=40; why.append("past niet bij esthetiek")
  return max(0,min(100,s)),why
CONC={
 "fashion":("de collectie als levend kunstwerk","A model in {brand}'s signature piece stands in a moonlit marble greenhouse; the fabric slowly ripples into liquid silk and blooming vines, gold dust drifting","fabric transforms into flowing vines and back"),
 "jewelry":("het sieraad als relikwie","Extreme macro of a {brand} piece resting on dark velvet inside a glass orchid; moonlight hits it and gold filaments grow outward like roots onto a model's collarbone","the piece magnetically floats onto the model"),
 "perfume":("de geur zichtbaar maken","A {brand} bottle on a mirrored pond in a night greenhouse; when the cap lifts, the scent becomes visible as slow golden smoke shaped like flowers that wrap around a model in a velvet gown","scent-smoke blossoms into petals"),
 "beauty":("huid als glanzend porselein","Close-up of a model's dewy skin in moonlit greenhouse light; a drop of {brand} serum falls and the skin ripples like liquid gold, orchids opening in the background","serum drop sends a golden ripple"),
 "haircare":("haar als beweging","A model with voluminous hair in a surreal greenhouse; {brand} product touches the hair and each strand catches light and sways like underwater kelp in slow motion","hair moves like underwater silk"),
 "interior":("het interieur droomt","A {brand} piece stands alone in an empty moonlit conservatory; vines climb it, the walls dissolve into night sky, a model in an editorial gown sits down as everything settles","the room grows around the object"),
 "webshop":("het product als kunstobject","A {brand} product placed on a marble pedestal inside a moonlit greenhouse, surrounded by floating petals; a model in a rust-to-navy gown reaches out and the product glows","petals orbit the product"),
}
def gen(a):
  key,scene,trans=CONC[a["niche"]]; b=a["name"]
  obs=f"{b} draait {a['ads']} actieve Meta-ad(s) in {'/'.join(a['countries'])}"+(", allemaal statisch beeld" if a["video_ads"]==0 else f", waarvan {a['video_ads']} video")+(f", sinds {a['oldest']:%b %Y}" if a["oldest"] else "")+"."
  concept=f"9:16 – '{key}': {scene.format(brand=b)}. Eindigt op logo + product."
  prompt=f"""[Format] 9:16 vertical, 15s, cinematic fashion editorial, surreal Gucci-style, moonlit greenhouse, deep navy + rust + gold palette, 35mm film grain. No music.
[Subject] {scene.format(brand=b)}.
[Style] high-fashion editorial, soft moonlight with warm gold rim light, shallow depth of field, slow elegant motion, luxurious textures.
[Timeline]
0-3s: slow push-in, establishing the moonlit greenhouse, the {b} product glints in the dark.
3-7s: model enters frame, camera orbits slowly; {trans}.
7-11s: macro detail of the product, texture and light, petals and gold dust drifting.
11-15s: pull back to a symmetrical hero shot, model holds still, product centered, space at the bottom for logo.
[Camera] smooth gimbal, slow orbit, macro inserts, no shaky cam.
[Avoid] text artifacts, extra fingers, distorted logo, music."""
  pitch=f"""Hoi {b}-team,

Ik zag jullie advertenties in de Meta Ad Library – mooi werk{' met sterke productbeelden' if a['video_ads']==0 else ''}. Ik ben Ronic (ArtByRonic), ik maak surrealistische fashion-editorial video's met AI, in 9:16 voor Reels en TikTok.

Idee voor {b}: {key} – {scene.format(brand=b).split(';')[0].lower()}. Video's als deze vallen meer op in de feed dan statische beelden en zijn snel te produceren, zonder dure shoot.

Zal ik een gratis 15-seconden concept voor jullie maken? Mijn werk: instagram.com/artbyronic

Groet,
Ronic"""
  return obs,concept,prompt,pitch
def main():
  quick="--quick" in sys.argv
  old={l["key"]:l for l in json.load(open(DATA))["leads"]} if os.path.exists(DATA) else {}
  jobs=[(n,k,cc) for n,ks in NICHES.items() for k in (ks[:1] if quick else ks) for cc in ("NL","BE")]
  ads=[]; src={"meta_ok":0,"meta_fail":0}
  with cf.ThreadPoolExecutor(2) as ex:
    fut={ex.submit(meta_search,k,cc):(n,k,cc) for n,k,cc in jobs}
    for f in cf.as_completed(fut):
      n,k,cc=fut[f]
      try: r=f.result(); [x.update(niche=n) for x in r]; ads+=r; src["meta_ok"]+=bool(r); src["meta_fail"]+=not r; print(k,cc,len(r),flush=True)
      except Exception as e: src["meta_fail"]+=1; print("FAIL",k,cc,e)
  adv={}
  for x in ads:
    key=(x["site"] or x["page"] or x["name"]).lower()
    a=adv.setdefault(key,dict(key=key,name=x["name"],low_name=x["name"].lower(),page=x["page"],site=x["site"],niche=x["niche"],ids=set(),video_ids=set(),countries=set(),dates=[],samples=[],kws=set()))
    a["ids"].add(x["id"]); a["countries"].add(x["cc"]); a["kws"].add(x["kw"])
    if x["video"]: a["video_ids"].add(x["id"])
    if x["start"]: a["dates"].append(datetime.datetime.strptime(x["start"],"%b %d, %Y").date())
    if len(a["samples"])<3 and x["id"] not in [s["id"] for s in a["samples"]]: a["samples"].append({k:x[k] for k in("id","text","img","link","video","start")})
    a["site"]=a["site"] or x["site"]; a["page"]=a["page"] or x["page"]
  L=[]
  for a in adv.values():
    a.update(ads=len(a["ids"]),video_ads=len(a["video_ids"]),countries=sorted(a["countries"]),oldest=min(a["dates"]) if a["dates"] else None,newest=max(a["dates"]) if a["dates"] else None,sample_text=" ".join(s["text"] for s in a["samples"]))
    a["contact"]=old.get(a["key"],{}).get("contact",{}); a["google"]=old.get(a["key"],{}).get("google")
    a["score"],a["why"]=score(a); L.append(a)
  L.sort(key=lambda a:-a["score"])
  top=[a for a in L if a["score"]>=40][:40]
  def enrich(a):
    if not a["contact"]: a["contact"]=contacts(a["site"])
    if a["google"] is None and a["site"]: a["google"]=google_count(a["site"],a["countries"][0])
    return a
  with cf.ThreadPoolExecutor(4) as ex: list(ex.map(enrich,top))
  src["google_ok"]=sum(1 for a in top if a.get("google")); src["contacts_found"]=sum(1 for a in top if a["contact"].get("email") or a["contact"].get("instagram"))
  for a in L: a["score"],a["why"]=score(a)
  L.sort(key=lambda a:-a["score"])
  now=datetime.datetime.now().isoformat(timespec="minutes"); out=[]
  for i,a in enumerate(L):
    o=old.get(a["key"],{})
    r=dict(key=a["key"],name=a["name"],site=a["site"],page=a["page"],niche=a["niche"],countries=a["countries"],ads=a["ads"],video_ads=a["video_ads"],
      oldest=str(a["oldest"] or ""),newest=str(a["newest"] or ""),samples=a["samples"],keywords=sorted(a["kws"]),google_ads=a["google"],contact=a["contact"],
      score=a["score"],why=a["why"],first_seen=o.get("first_seen",now),last_seen=now,
      library=f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country={a['countries'][0]}&q={urllib.parse.quote(a['name'])}&search_type=keyword_unordered")
    if i<40 and a["score"]>=40: r["observation"],r["concept"],r["prompt"],r["pitch"]=gen(a)
    out.append(r)
  for k,o in old.items():
    if k not in adv: o["stale"]=True; out.append(o)
  json.dump(dict(updated=now,sources=src,leads=out),open(DATA,"w"),ensure_ascii=False,indent=1)
  print("leads",len(out),"src",src)
  if "--push" in sys.argv:
    subprocess.run(f"cd {D} && git add -A && git commit -qm 'data {now}' && git push -q",shell=True)
if __name__=="__main__": main()
