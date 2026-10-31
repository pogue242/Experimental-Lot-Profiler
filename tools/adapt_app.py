#!/usr/bin/env python3
"""adapt_app.py — copy 1.8's app files here and swap the New York specifics for Philadelphia, Vienna and Tokyo"""
import os, re, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, ".."); SRC = os.path.join(ROOT, "..", "1.8")

def sub(s, a, b, count=1):
    n = s.count(a)
    if n < 1 or (count and n != count): raise SystemExit(f"expected {count or 'some'} of: {a[:70]} (found {n})")
    return s.replace(a, b)

for f in ("index.html", "app.js", "style.css"): shutil.copy(os.path.join(SRC, f), os.path.join(ROOT, f))
p = os.path.join(ROOT, "app.js"); s = open(p, encoding="utf-8").read()
s = sub(s, 'const BORO = {1:"Manhattan",2:"Bronx",3:"Brooklyn",4:"Queens",5:"Staten Island"};',
        'const CITY = {phl26:"Philadelphia",vie26:"Vienna",tyo26:"Tokyo"};\nconst BORO = {0:"Philadelphia"};')
s = sub(s, 'const BORO_WORD = {manhattan:1,mn:1,bronx:2,bx:2,brooklyn:3,bk:3,queens:4,qn:4,"staten island":5,si:5,statenisland:5};', 'const BORO_WORD = {};')
s = sub(s, 'attribution:"NYC DCP MapPLUTO"', 'attribution:"City open data"', count=0)
s = sub(s, "NYC DCP MapPLUTO", "${CITY_SRC[st.P.id]||\"\"}", count=0)
s = sub(s, 'tax lots in ${(P.rel.coverage||"the release").replace(/^Five/,"five")}, MapPLUTO ${P.id}`', 'lots in ${P.rel.coverage||CITY[P.id]}`')
s = sub(s, 'const CITY = {', 'const CITY_SRC = {phl26:"City of Philadelphia OPA and PWD parcels",vie26:"BEV cadastre and City of Vienna open data",tyo26:"MLIT PLATEAU (Tokyo 23 wards)"};\nconst CITY = {')
i = s.index('  const groups=[["Property records",'); j = s.index('  const bblX=Math.round(P.bbl[i])')
s = s[:i] + '''  const L=(href,t)=>`<a href="${href}" target="_blank" rel="noopener">${t}</a>`, gm=`https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;
  const groups=st.P.id==="phl26"?[["Property records",[L(`https://atlas.phila.gov/${encodeURIComponent(addrOf(P,i)||"")}`,"Atlas (City of Philadelphia)"),L("https://property.phila.gov/","Property search (OPA)")]],["Neighborhood",[L(gm,"Google Maps")]]]
    :[["Neighborhood",[L(gm,"Google Maps")]]];
''' + s[j:]
s = sub(s, "  const condo=lot>=7501&&lot<=7599, L=(href,t)=>`<a href=\"${href}\" target=\"_blank\" rel=\"noopener\">${t}</a>`;\n", "")
i = s.index('<a href="https://zola.planning.nyc.gov/l/lot/${boro}/${block}/${lot}" target="_blank" rel="noopener">Open in ZoLa</a>')
j = s.index('    <button data-goblock="${boro*1e5+block}">')
s = s[:i] + '${st.P.id==="phl26"?`<a href="https://atlas.phila.gov/${encodeURIComponent(addrOf(P,i)||"")}" target="_blank" rel="noopener">Open in Atlas</a>`:`<a href="https://www.google.com/maps/search/?api=1&query=${P.lat[i].toFixed(6)},${P.lng[i].toFixed(6)}" target="_blank" rel="noopener">Open in Google Maps</a>`}\n' + s[j:]
s = sub(s, "Select block ${block}</button>", "Select block</button>")
s = sub(s, '["Neighborhood (2020 NTA)",', '["Neighborhood",')
s = sub(s, '"Neighborhood tabulation area"', '"Neighborhood"', count=0)
s = sub(s, 'tag:a.kind==="nta"?"NTA":"Tract"', 'tag:a.kind==="nta"?"Neighborhood":"Tract"')
s = sub(s, 'attribution:"Subway: MTA Open Data, © OpenStreetMap contributors"', 'attribution:"Transit: © OpenStreetMap contributors"')
s = sub(s, '; MTA Open Data; © OpenStreetMap contributors', '; transit © OpenStreetMap contributors', count=0)
s = sub(s, "toast(`Subway map now shows ${T.date}", "toast(`Transit map now shows ${T.date}")
s = sub(s, 'const bullet = r => `<span class="rb${MTA[r]==="#FCCC0A"?" dark":""}" style="background:${MTA[r]||"#808183"}">${esc(r)}</span>`;',
        'const RC = r => (st.T&&st.T.rc&&st.T.rc[r])||MTA[r]||"#808183", bullet = r => `<span class="rb${lightBg(RC(r))?" dark":""}" style="background:${RC(r)}">${esc(r)}</span>`;\nconst lightBg = c => { const n=parseInt(String(c).slice(1),16); return ((n>>16&255)*299+(n>>8&255)*587+(n&255)*114)/1000>165; };')
s = sub(s, "    other:(raw.other_stations||[]).filter(x=>x&&x.lng!=null)};", "    other:(raw.other_stations||[]).filter(x=>x&&x.lng!=null), rc:raw.route_colors||{}};")
s = sub(s, 'const CAT_VIEWS = new Set(["lu","ub","fc","zn","dq","fl"]);', 'const CAT_VIEWS = new Set(["lu","ub","fc","zn","dq","fl","nl"]);\nconst NOU = () => !!(st.P&&st.P.rel&&st.P.rel.noUnits), UNOTE = "Not in source data";')
s = sub(s, 'order:["lu","ub","fl","fc","age","zone","list"]}', 'order:["lu","nl","ub","fl","fc","age","zone","list"]}')
s = sub(s, 'hidden:{lu:new Set(),ub:new Set(),fc:new Set(),zn:new Set(),dq:new Set(),fl:new Set()}', 'hidden:{lu:new Set(),ub:new Set(),fc:new Set(),zn:new Set(),dq:new Set(),fl:new Set(),nl:new Set()}')
s = sub(s, "blk:S.blk, floors:S.floors||null,", "blk:S.blk, floors:S.floors||null, nl:S.nl||null, native:H.native||null,")
s = sub(s, "hasFar:!!P.far&&!allLots, ageLots:0, dqLots:0, dqUnits:0};", "hasFar:!!P.far&&!allLots, ageLots:0, dqLots:0, dqUnits:0, nlL:new Float64Array(256),nlA:new Float64Array(256),nlU:new Float64Array(256)};")
s = sub(s, "    S.luL[lu]++; S.luA[lu]+=a; S.luU[lu]+=u;", "    S.luL[lu]++; S.luA[lu]+=a; S.luU[lu]+=u;\n    if (P.nl){ const c=P.nl[i]; S.nlL[c]++; S.nlA[c]+=a; S.nlU[c]+=u; }")
s = sub(s, "  const gl=S.groups.map(groupLabel), gc=groupColors(S.groups.length);\n", """  if (P.nl){ const N=nlNames(P), C=nlColors(P), ix=nlIdx(P);
    const nSeg=(arr,tot,metric,vf)=>ix.filter(k=>arr[k]).map(k=>seg(N[k],C[k],arr[k],tot,metric,vf(arr[k])));
    specs.nl={title:P.native.title+" (original classes)",barCap:"Share of land area",
      charts:[{cap:"Lots",segs:nSeg(S.nlL,S.lots,"of lots",v=>fmt(v)+" lots")},{cap:"Land area",segs:nSeg(S.nlA,S.area,"of land area",acres)},
              {cap:"Housing units",segs:nSeg(S.nlU,S.units,"of housing units",v=>fmt(v)+" units")}],
      bar:1, headers:["Class","% lots","% area","% units"], rows:ix.map(k=>[C[k],N[k],pct(S.nlL[k],S.lots),pct(S.nlA[k],S.area),pct(S.nlU[k],S.units)]).filter(r=>r[2]||r[3])}; }
  const gl=S.groups.map(groupLabel), gc=groupColors(S.groups.length);
""")
s = sub(s, '  cat("lu","Land use",["lots","area","units"],lu);', '  cat("lu","Land use",["lots","area","units"],lu); if (P.nl) cat("nl",P.native.title+" (original classes)",["lots","area","units"],S=>nlIdx(P).map(k=>({name:nlNames(P)[k],color:nlColors(P)[k],v:[S.nlL[k],S.nlA[k],S.nlU[k]]})));')
s = sub(s, '  if (v==="lu"){ LU_COLORS.forEach((c,i)=>m.push(i,c)); m.push(NODATA); return m; }', '  if (v==="lu"){ LU_COLORS.forEach((c,i)=>m.push(i,c)); m.push(NODATA); return m; }\n  if (v==="nl"){ const C=st.P.native?st.P.native.colors:[]; if (!C.length) return NODATA; C.forEach((c,i)=>m.push(i,c)); m.push(NODATA); return m; }')
s = sub(s, 'arr=v==="lu"?P.lu:', 'arr=v==="nl"?P.nl:v==="lu"?P.lu:')
s = sub(s, '  if (v==="lu") h=st.P.dict.lu.map', '  if (v==="nl"&&st.P.nl) h=nlIdx(st.P).filter(k=>k<255).map(k=>sw(k,nlColors(st.P)[k],nlNames(st.P)[k])).join("")+sw(255,NODATA,"Unknown");\n  if (v==="lu") h=st.P.dict.lu.map')
s = sub(s, 'const opts=[["lu","Land use"],["ub","Units per building"],', 'const opts=[["lu","Land use (NYC categories)"],...(P.nl?[["nl",P.native.title+" (original)"]]:[]),...(NOU()?[]:[["ub","Units per building"]]),')
s = sub(s, '["Land use",P.dict.lu[P.lu[i]]],', '["Land use",P.dict.lu[P.lu[i]]],...(P.nl?[["Original class ("+esc(P.native.title)+")",P.nl[i]<255?esc(P.dict.nl[P.nl[i]]):"—"]]:[]),')
s = sub(s, "st.specs=sectionSpecs(S);", "st.specs=nou(sectionSpecs(S));")
s = sub(s, "specs=cmpSpecs(cols); st.specs=specs;", "specs=nou(cmpSpecs(cols)); st.specs=specs;")
s = sub(s, "function sectionSpecs(S){", """const nlNames=P=>[...P.dict.nl,...Array(255-P.dict.nl.length).fill(""),"Unknown"], nlColors=P=>[...P.native.colors,...Array(255-P.native.colors.length).fill(NODATA),NODATA];
const nlIdx=P=>[...P.dict.nl.keys(),255];
function nou(specs){
  if (!NOU()) return specs; delete specs.ub;
  const gone=new Set(["Housing units","Units per acre","Lots with housing"]);
  for (const sp of Object.values(specs)){
    if (sp.charts){ sp.charts=sp.charts.filter(c=>!/unit/i.test(c.cap)); if (sp.bar>=sp.charts.length) sp.bar=0; }
    if (sp.headers){ const k=sp.headers.indexOf("% units"); if (k>=0){ sp.headers=sp.headers.filter((_,j)=>j!==k); if (sp.rows) sp.rows=sp.rows.map(r=>r.filter((_,j)=>j!==k+1)); } }
    if (sp.metrics) sp.metrics=sp.metrics.filter(m=>m!=="units");
    if (sp.mrows) sp.mrows=sp.mrows.filter(r=>!gone.has(r[0]));
  }
  return specs; }
function sectionSpecs(S){""")
s = sub(s, '<div><div class="v">${fmt(S.units)}</div><div class="k">Housing units</div></div>', '<div><div class="v">${NOU()?"—":fmt(S.units)}</div><div class="k">Housing units${NOU()?" (not in source data)":""}</div></div>')
s = sub(s, '<div><div class="v">${fmt(S.upa,1)}</div><div class="k">Units per acre</div></div></div>', '<div><div class="v">${NOU()?"—":fmt(S.upa,1)}</div><div class="k">Units per acre</div></div></div>')
s = sub(s, '<p class="subline">${fmt(S.resLots)} lots with housing. The median lot is ${fmt(S.medLot)} sq ft.</p>', '<p class="subline">${NOU()?"":`${fmt(S.resLots)} lots with housing. `}The median lot is ${fmt(S.medLot)} sq ft.</p>')
s = sub(s, '<div><div class="v">${fmt(P.units[i])}</div><div class="k">Housing units</div></div>', '<div><div class="v">${NOU()?"—":fmt(P.units[i])}</div><div class="k">Housing units${NOU()?" (not in source data)":""}</div></div>')
s = sub(s, '["Residential units",fmt(P.units[i])],["Total units",!R?wait:fmt(g("UnitsTotal"))],', '...(NOU()?[["Housing units",UNOTE]]:[["Residential units",fmt(P.units[i])],["Total units",!R?wait:fmt(g("UnitsTotal"))]]),')
s = sub(s, '<span class="val">${fmt(P.units[i])}</span><span class="val">${fmt(P.bfar[i],2)}', '<span class="val">${NOU()?"—":fmt(P.units[i])}</span><span class="val">${fmt(P.bfar[i],2)}')
s = sub(s, '<div><dt>Housing units</dt><dd>${fmt(P.units[i])}</dd></div>', '<div><dt>Housing units</dt><dd>${NOU()?"—":fmt(P.units[i])}</dd></div>')
s = sub(s, "    st.P=await getPack(want.id);\n", "    st.P=await getPack(want.id); BORO[0]=CITY[want.id]||\"\";\n")
s = sub(s, "  if (id===st.P.id) return; $(\"#loading\").hidden=false; $(\"#loading\").textContent=`Loading ${id}…`;\n  st.P=await getPack(id); if (st.C&&st.C.id===id) st.C=null;\n",
        "  if (id===st.P.id) return; $(\"#loading\").hidden=false; $(\"#loading\").textContent=`Loading ${CITY[id]||id}…`;\n"
        "  st.P=await getPack(id); st.C=null; BORO[0]=CITY[id]||\"\"; st.sels=[]; st.view=\"all\"; st.peek=null; st.zpeek=null; undoStack.length=0; redoStack.length=0;\n"
        "  map.fitBounds(st.P.bbox,{padding:40,duration:0});\n")
s = sub(s, "<span data-rel=\"${r.id}\">${r.id}${r.coverage&&!/New York City/.test(r.coverage)?`<small>${esc(shortCov(r.coverage))}</small>`:\"\"}</span>",
        "<span data-rel=\"${r.id}\">${esc(CITY[r.id]||r.id)}</span>")
s = sub(s, "    `<li class=\"ghost\"><button title=\"Add the next release: python tools/build.py path/to/MapPLUTO.gdb\" aria-label=\"How to add a release\"></button><span>next</span></li>`;", "    \"\";")
i = s.index("function zoneBase(z){"); j = s.index("\n", s.index('return "#B7BEC6"; }', i)) + 1
s = s[:i] + '''function zoneBase(z){ z=z||""; const v=st.P&&st.P.id, f=z[0], pc=/(\\d+)%/.exec(z), d=/(\\d+)/.exec(z);
  const k=v==="vie26"?(f==="W"?"R":f==="G"?"C":/^(B|I)/.test(z)?"M":/^(S(?!O)|E|L|P|F)/.test(z)?"P":""):/^(R|W)/.test(z)?"R":f==="C"?"C":/^(M|I)/.test(z)?"M":/^(PARK|SP-PO|SP-REC)/.test(z)?"P":"";
  const t=pc?Math.min(1,Math.max(0,(+pc[1]-100)/1100)):d?Math.min(1,(+d[1]-1)/(v==="vie26"?5:v==="phl26"?4:9)):0;
  if (k==="R") return mix("#F5E3A0","#B97A12",t); if (k==="C") return mix("#F0A898","#A8272B",t);
  if (k==="M") return mix("#CDB8E2","#5E3F8F",t); if (k==="P") return "#7FB36E"; return z?"#B7BEC6":NODATA; }
''' + s[j:]
s = sub(s, '"dq","fl","nl"]);', '"dq","fl","nl","zc"]);')
s = sub(s, '"age","zone","list"]}', '"age","zc","zone","list"]}')
s = sub(s, "fl:new Set(),nl:new Set()}", "fl:new Set(),nl:new Set(),zc:new Set()}")
s = sub(s, 'zn:"Zoning district",', 'zn:"Zoning district",zc:"Zoning category",')
s = sub(s, "nl:S.nl||null, native:H.native||null,", "nl:S.nl||null, native:H.native||null, zc:S.zc||null, zcat:H.zcat||null,")
s = sub(s, "nlU:new Float64Array(256)};", "nlU:new Float64Array(256),zcL:new Float64Array(256),zcA:new Float64Array(256),zcU:new Float64Array(256)};")
s = sub(s, "S.nlU[c]+=u; }\n", "S.nlU[c]+=u; }\n    if (P.zc){ const c=P.zc[i]; S.zcL[c]++; S.zcA[c]+=a; S.zcU[c]+=u; }\n")
s = sub(s, "  const gl=S.groups.map(groupLabel), gc=groupColors(S.groups.length);\n", """  if (P.zc){ const N=zcNames(P), C=zcColors(P), ix=zcIdx(P);
    const zSeg=(arr,tot,metric,vf)=>ix.filter(k=>arr[k]).map(k=>seg(N[k],C[k],arr[k],tot,metric,vf(arr[k])));
    specs.zc={title:"Zoning categories",barCap:"Share of land area",soft:`${ix.filter(k=>k<255&&S.zcL[k]).length} categories`,
      charts:[{cap:"Lots",segs:zSeg(S.zcL,S.lots,"of lots",v=>fmt(v)+" lots")},{cap:"Land area",segs:zSeg(S.zcA,S.area,"of land area",acres)},
              {cap:"Housing units",segs:zSeg(S.zcU,S.units,"of housing units",v=>fmt(v)+" units")}],
      bar:1, headers:["Category","% lots","% area","% units"], rows:ix.map(k=>[C[k],N[k],pct(S.zcL[k],S.lots),pct(S.zcA[k],S.area),pct(S.zcU[k],S.units)]).filter(r=>r[2]||r[3])}; }
  const gl=S.groups.map(groupLabel), gc=groupColors(S.groups.length);
""")
s = sub(s, '(original classes)",["lots","area","units"],S=>nlIdx(P).map(k=>({name:nlNames(P)[k],color:nlColors(P)[k],v:[S.nlL[k],S.nlA[k],S.nlU[k]]})));',
        '(original classes)",["lots","area","units"],S=>nlIdx(P).map(k=>({name:nlNames(P)[k],color:nlColors(P)[k],v:[S.nlL[k],S.nlA[k],S.nlU[k]]})));'
        ' if (P.zc) cat("zc","Zoning categories",["lots","area","units"],S=>zcIdx(P).map(k=>({name:zcNames(P)[k],color:zcColors(P)[k],v:[S.zcL[k],S.zcA[k],S.zcU[k]]})));')
s = sub(s, '  if (v==="nl"){ const C=st.P.native', '  if (v==="zc"){ const C=st.P.zcat?st.P.zcat.colors:[]; if (!C.length) return NODATA; C.forEach((c,i)=>m.push(i,c)); m.push(NODATA); return m; }\n  if (v==="nl"){ const C=st.P.native')
s = sub(s, 'arr=v==="nl"?P.nl:', 'arr=v==="zc"?P.zc:v==="nl"?P.nl:')
s = sub(s, '  if (v==="nl"&&st.P.nl) h=', '  if (v==="zc"&&st.P.zc) h=zcIdx(st.P).filter(k=>k<255).map(k=>sw(k,zcColors(st.P)[k],zcNames(st.P)[k])).join("")+sw(255,NODATA,"No zoning");\n  if (v==="nl"&&st.P.nl) h=')
s = sub(s, '...(P.nl?[["nl",P.native.title+" (original)"]]:[]),', '...(P.nl?[["nl",P.native.title+" (original)"]]:[]),...(P.zc?[["zc","Zoning category"],["zn","Zoning district (full code)"]]:[]),')
s = sub(s, 'specs.zoning={title:"Zoning", kv:[["Zoning district",!R?esc(P.dict.zone[P.zone[i]]||"—"):esc(nonEmpty(g("ZoneDist1"),g("ZoneDist2"),g("ZoneDist3"),g("ZoneDist4")))],',
        'specs.zoning={title:"Zoning", kv:[...(P.zc?[["Zoning category",P.zc[i]<255?esc(P.dict.zc[P.zc[i]]):"—"]]:[]),["Zoning district",!R?esc(P.dict.zone[P.zone[i]]||"—"):esc(nonEmpty(g("ZoneDist1"),g("ZoneDist2"),g("ZoneDist3"),g("ZoneDist4")))],')
s = sub(s, "const nlIdx=P=>[...P.dict.nl.keys(),255];", """const nlIdx=P=>[...P.dict.nl.keys(),255];
const zcNames=P=>[...P.dict.zc,...Array(255-P.dict.zc.length).fill(""),"No zoning"], zcColors=P=>[...P.zcat.colors,...Array(255-P.zcat.colors.length).fill(NODATA),NODATA];
const zcIdx=P=>[...P.dict.zc.keys(),255];""")
s = sub(s, 'if (h.m&&h.m!=="zn") st.colorBy=h.m;', "if (h.m) st.colorBy=h.m;")
s = sub(s, ':v==="dq"?[]:[...(hasStandard(v)', ':v==="dq"||v==="zc"?[]:[...(hasStandard(v)')
s = sub(s, "  return \"pmtiles://\"+url;\n}", """  const np=!EMB&&partCount(path);
  if (np && !pmProto.tiles.has(url)){
    pmProto.add(new pmtiles.PMTiles({getKey:()=>url, getBytes:async(off,len)=>{ const out=new Uint8Array(len); let o=off;
      while (o<off+len){ const k=Math.floor(o/PART), e=Math.min(off+len,(k+1)*PART); out.set(await fetchRange(`${path}.${k+1}`,o-k*PART,e-k*PART),o-off); o=e; }
      return {data:out.buffer}; }})); }
  return "pmtiles://"+url;
}
const PART=64*1024*1024;
function partCount(path){ for (const r of st.releases||[]) if (r.parts&&path.startsWith(relDir(r))&&r.parts[path.slice(relDir(r).length)]) return r.parts[path.slice(relDir(r).length)]; return 0; }""")
open(p, "w", encoding="utf-8").write(s)

p = os.path.join(ROOT, "index.html"); s = open(p, encoding="utf-8").read()
s = sub(s, "<span>Tax lots, zoning and land use for New York City</span>", "<span>Prototype: Philadelphia, Vienna and Tokyo</span>")
s = re.sub(r"<title>[^<]*</title>", "<title>Lot Profiler · city prototypes</title>", s)
s = sub(s, "A map of every tax lot in New York City, built from the city's MapPLUTO data.",
        "A prototype of Lot Profiler for three more cities: Philadelphia, Vienna and Tokyo. Switch cities with the buttons at the top.")
s = sub(s, " Switch the map to Zoning to see districts and ZoLa's other zoning layers.", "")
s = sub(s, 'placeholder="Address, BBL, neighborhood or station"', 'placeholder="Address or neighborhood"')
s = sub(s, '<span class="hlabel">PLUTO release</span>', '<span class="hlabel">City</span>')
s = sub(s, '<span class="ol">Subway</span>', '<span class="ol">Transit</span>')
s = re.sub(r'<label title="PATH and New Jersey light rail[^"]*"><input type="checkbox" data-sub="rail" checked> PATH, NJ light rail, LIRR, Metro-North</label>',
           '<label><input type="checkbox" data-sub="rail" checked> Rail and tram lines</label>', s)
s = sub(s, 'aria-label="PLUTO releases"', 'aria-label="Cities"')
s = sub(s, 'title="Select a Neighborhood Tabulation Area (N)">NTAs</button>', 'title="Select a neighborhood, district or ward (N)">Areas</button>')
open(p, "w", encoding="utf-8").write(s)

p = os.path.join(ROOT, "style.css"); s = open(p, encoding="utf-8").read()
s += "#layerMode,#zonOpts,#boroFilter,#history .compare{display:none!important}\n"
open(p, "w", encoding="utf-8").write(s)
print("app adapted")
