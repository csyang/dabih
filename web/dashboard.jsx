import { useState, useRef, useMemo } from "react";

const T = {
  bg:"#04060e", surface:"#090c18", surfaceHi:"#0e1225",
  border:"#1a1f35", borderHi:"#262d48",
  accent:"#00c8ff", accent2:"#a855f7", accent3:"#6366f1",
  warn:"#eab308", danger:"#ef4444",
  text:"#e2e8f0", textDim:"#64748b", textMuted:"#262d48",
};

const RUNS = [
  {
    run_id: "seed_0042", simulator: "questa", covergroup: "rx_cross_cg",
    timestamp: "2026-05-24T08:14", method: "polya",
    orbits_total: 330, orbits_hit: 110, orbits_missed: 220, class_pct: 33.3,
    bins_total: 4096, bins_covered: 1092, bin_pct: 26.7, compression: 12.41,
    complete: false, unresolved: 0, sim_bins_obs: 110, sim_hits_total: 1820,
    holes: Array.from({length: 220}, (_, i) => [`IDLE`,`LO`,`ACTIVE`,`HI`].slice(i%4,i%4+2)),
    coverpoints: ["inst0.state","inst0.ready","inst1.state","inst1.ready","inst2.state","inst2.ready","inst3.state","inst3.ready"],
    declarations: [{type:"instance",instance_indices:[0,1,2,3],block_size:2,group:"S4",n_generators:2}],
    provenance: null,
  },
  {
    run_id: "seed_1337", simulator: "questa", covergroup: "rx_cross_cg",
    timestamp: "2026-05-24T09:02", method: "polya",
    orbits_total: 330, orbits_hit: 214, orbits_missed: 116, class_pct: 64.8,
    bins_total: 4096, bins_covered: 2813, bin_pct: 68.7, compression: 12.41,
    complete: false, unresolved: 2, sim_bins_obs: 214, sim_hits_total: 4312,
    holes: Array.from({length: 116}, (_, i) => [`STALL`,`HI`].slice(i%2,i%2+2)),
    coverpoints: ["inst0.state","inst0.ready","inst1.state","inst1.ready","inst2.state","inst2.ready","inst3.state","inst3.ready"],
    declarations: [{type:"instance",instance_indices:[0,1,2,3],block_size:2,group:"S4",n_generators:2}],
    provenance: null,
  },
  {
    run_id: "seed_9999", simulator: "questa", covergroup: "rx_cross_cg",
    timestamp: "2026-05-24T10:18", method: "polya",
    orbits_total: 330, orbits_hit: 280, orbits_missed: 50, class_pct: 84.8,
    bins_total: 4096, bins_covered: 3701, bin_pct: 90.4, compression: 12.41,
    complete: false, unresolved: 0, sim_bins_obs: 280, sim_hits_total: 7840,
    holes: Array.from({length: 50}, (_, i) => [`ERROR`,`LO`]),
    coverpoints: ["inst0.state","inst0.ready","inst1.state","inst1.ready","inst2.state","inst2.ready","inst3.state","inst3.ready"],
    declarations: [{type:"instance",instance_indices:[0,1,2,3],block_size:2,group:"S4",n_generators:2}],
    // Synthetic provenance for the merged view
    provenance: {
      histogram: {"1": 42, "2": 91, "3": 147},
      fragile_count: 42,
      fragile_reps: Array.from({length:42},(_,i)=>[`IDLE`,`LO`,`IDLE`,`LO`]),
      well_covered: 147,
      single_count: 42,
      two_count: 91,
      max_seeds: 3,
    },
  },
];

function fmt(n) {
  if(!n&&n!==0) return "—";
  if(n>=1e6) return (n/1e6).toFixed(1)+"M";
  if(n>=1e3) return (n/1e3).toFixed(1)+"K";
  return n.toLocaleString();
}

function Gauge({pct,color,label,size=108}) {
  const r=40, circ=2*Math.PI*r;
  const offset=circ*(1-(pct||0)/100);
  return (
    <div style={{position:"relative",width:size,height:size}}>
      <svg width={size} height={size} viewBox="0 0 100 100" style={{transform:"rotate(-90deg)"}}>
        <circle cx="50" cy="50" r={r} fill="none" stroke={T.border} strokeWidth="8"/>
        <circle cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="8"
          strokeLinecap="round" strokeDasharray={circ}
          strokeDashoffset={offset}
          style={{transition:"stroke-dashoffset .9s cubic-bezier(.4,0,.2,1)"}}/>
      </svg>
      <div style={{position:"absolute",inset:0,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center"}}>
        <span style={{fontWeight:800,fontSize:size>90?18:13,color,lineHeight:1}}>{pct?.toFixed(1)}%</span>
        <span style={{fontSize:9,color:T.textDim,marginTop:2}}>{label}</span>
      </div>
    </div>
  );
}

function ProgressBar({pct,color1,color2,height=6}) {
  return (
    <div style={{height,background:T.border,borderRadius:height/2,overflow:"hidden"}}>
      <div style={{height:"100%",width:`${pct}%`,borderRadius:height/2,
        background:`linear-gradient(90deg,${color1},${color2})`,
        transition:"width .9s cubic-bezier(.4,0,.2,1)"}}/>
    </div>
  );
}

function StatCard({label,value,sub,color}) {
  return (
    <div style={{background:T.surface,border:`1px solid ${T.border}`,borderRadius:10,padding:"16px 18px",flex:1,minWidth:120}}>
      <div style={{fontSize:10,fontWeight:600,letterSpacing:"0.1em",textTransform:"uppercase",color:T.textDim,marginBottom:6}}>{label}</div>
      <div style={{fontWeight:800,fontSize:22,color:color||T.text,lineHeight:1}}>{value}</div>
      {sub&&<div style={{fontSize:11,color:T.textDim,marginTop:5}}>{sub}</div>}
    </div>
  );
}

function HoleGrid({holes,search}) {
  const filtered = !search ? holes : holes.filter(h=>h.join(" ").toLowerCase().includes(search.toLowerCase()));
  if(!filtered.length) return <div style={{padding:32,textAlign:"center",color:T.textDim,fontSize:13}}>{holes.length===0?"✓ All classes covered":"No matching holes"}</div>;
  return (
    <div style={{display:"flex",flexWrap:"wrap",gap:6,padding:16,maxHeight:260,overflowY:"auto"}}>
      {filtered.slice(0,100).map((h,i)=>(
        <div key={i} style={{background:"#ef444410",border:"1px solid #ef444428",borderRadius:4,
          padding:"3px 8px",fontSize:11,fontFamily:"monospace",color:T.danger,
          display:"flex",gap:4}}>
          {h.map((v,j)=><span key={j} style={{color:j%2===0?T.accent2:T.textDim}}>{v}</span>)}
        </div>
      ))}
      {filtered.length>100&&<div style={{color:T.textDim,fontSize:11,alignSelf:"center"}}>+{filtered.length-100} more…</div>}
    </div>
  );
}

function mergeRuns(runs) {
  if(!runs.length) return null;
  const t = runs[0].orbits_total;
  const hit = Math.min(t, Math.round(t*(1-runs.reduce((p,r)=>p*(1-r.class_pct/100),1))));
  const pct = (hit/t)*100;
  return {
    run_id:`merged (${runs.length} runs)`, simulator:"—", method:runs[0].method,
    orbits_total:t, orbits_hit:hit, orbits_missed:t-hit, class_pct:pct,
    bins_total:runs[0].bins_total, bins_covered:Math.round(runs[0].bins_total*pct/100),
    bin_pct:pct, compression:runs[0].compression, complete:pct>=100,
    unresolved:runs.reduce((a,r)=>a+(r.unresolved||0),0),
    sim_bins_obs:runs.reduce((a,r)=>a+r.sim_bins_obs,0),
    sim_hits_total:runs.reduce((a,r)=>a+r.sim_hits_total,0),
    holes:[], coverpoints:runs[0].coverpoints, declarations:runs[0].declarations,
    timestamp:runs[runs.length-1].timestamp,
  };
}

export default function App() {
  const [runs,setRuns]        = useState(RUNS);
  const [activeIdx,setActive] = useState(0);
  const [tab,setTab]          = useState("overview");
  const [hSearch,setHSearch]  = useState("");
  const [showDrop,setDrop]    = useState(false);
  const fileRef               = useRef();

  const merged  = useMemo(()=>mergeRuns(runs),[runs]);
  const current = activeIdx===-1 ? merged : runs[activeIdx];

  const handleFile = files => {
    if(!files?.length) return;
    const r=new FileReader();
    r.onload=e=>{try{const d=JSON.parse(e.target.result);setRuns(Array.isArray(d)?d:[d]);setActive(0);setDrop(false);}catch{alert("Invalid JSON");}};
    r.readAsText(files[0]);
  };

  const c = (active) => ({
    display:"flex",alignItems:"center",gap:8,padding:"8px 16px",
    fontSize:12,color:active?T.text:T.textDim,cursor:"pointer",
    borderLeft:`2px solid ${active?T.accent:"transparent"}`,
    background:active?"#00c8ff12":"transparent",
    border:"none",width:"100%",textAlign:"left",fontFamily:"inherit",
    transition:"all .15s",
  });

  const tabBtn = (id,active) => ({
    padding:"6px 14px",borderRadius:6,fontSize:11,
    fontFamily:"monospace",background:active?T.accent:T.surfaceHi,
    color:active?"#fff":T.textDim,border:`1px solid ${active?T.accent:T.border}`,
    cursor:"pointer",transition:"all .15s",
  });

  const card = {background:T.surface,border:`1px solid ${T.border}`,borderRadius:10,overflow:"hidden",marginBottom:16};
  const cardHdr = {padding:"10px 16px",borderBottom:`1px solid ${T.border}`,background:T.surfaceHi,
    fontSize:10,fontWeight:600,letterSpacing:"0.1em",textTransform:"uppercase",color:T.textDim,
    display:"flex",alignItems:"center",justifyContent:"space-between"};

  return (
    <div style={{minHeight:"100vh",background:T.bg,color:T.text,fontFamily:"system-ui,sans-serif",fontSize:13,display:"flex",flexDirection:"column"}}>
      <style>{`
        @keyframes pulse{0%,100%{box-shadow:0 0 8px #00c8ff}50%{box-shadow:0 0 2px #00c8ff}}
        ::-webkit-scrollbar{width:3px;height:3px}
        ::-webkit-scrollbar-thumb{background:#1e2330;border-radius:2px}
      `}</style>

      {/* ── Header ── */}
      <div style={{background:T.surface,borderBottom:`1px solid ${T.border}`,
        padding:"0 24px",height:52,display:"flex",alignItems:"center",
        justifyContent:"space-between",flexShrink:0,gap:12}}>

        <div style={{display:"flex",alignItems:"center",gap:10,fontWeight:800,fontSize:17,letterSpacing:"-0.3px"}}>
          <div style={{width:7,height:7,borderRadius:"50%",background:T.accent,
            boxShadow:`0 0 8px ${T.accent}`,animation:"pulse 2.4s ease-in-out infinite"}}/>
          Dabih
          <span style={{fontSize:11,color:T.textDim,fontWeight:400,marginLeft:2}}>
            Coverage Dashboard
          </span>
        </div>

        <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
          {runs.map((r,i)=>(
            <button key={i} style={tabBtn(i,activeIdx===i)} onClick={()=>setActive(i)}>
              {r.run_id}
            </button>
          ))}
          <button style={tabBtn(-1,activeIdx===-1)} onClick={()=>setActive(-1)}>
            ⊕ Merged
          </button>
          <button onClick={()=>setDrop(v=>!v)} style={{...tabBtn(-99,false),color:T.accent,borderColor:"#00c8ff44"}}>
            Load JSON
          </button>
        </div>
      </div>

      <div style={{display:"flex",flex:1,overflow:"hidden"}}>

        {/* ── Sidebar ── */}
        <div style={{width:190,background:T.surface,borderRight:`1px solid ${T.border}`,
          padding:"14px 0",display:"flex",flexDirection:"column",gap:2,overflowY:"auto",flexShrink:0}}>

          {[["overview","◈","Overview"],["coverage","◎","Coverage"],
            ["holes","◌","Holes"],["runs","⊞","Run History"],
            ["confidence","◐","Confidence"]].map(([id,icon,label])=>(
            <button key={id} style={c(tab===id)} onClick={()=>setTab(id)}>
              <span style={{fontSize:13,width:16,textAlign:"center"}}>{icon}</span>{label}
            </button>
          ))}

          <div style={{fontSize:10,fontWeight:600,letterSpacing:"0.1em",textTransform:"uppercase",
            color:T.textMuted,padding:"12px 16px 4px"}}>Design</div>

          {[["symmetry","⧖","Symmetry"],["coverpoints","≡","Coverpoints"]].map(([id,icon,label])=>(
            <button key={id} style={c(tab===id)} onClick={()=>setTab(id)}>
              <span style={{fontSize:13,width:16,textAlign:"center"}}>{icon}</span>{label}
            </button>
          ))}

          {/* Compression panel */}
          <div style={{margin:"16px 12px 0",background:T.surfaceHi,border:`1px solid ${T.border}`,
            borderRadius:8,padding:14}}>
            <div style={{fontSize:10,letterSpacing:"0.1em",textTransform:"uppercase",
              color:T.textMuted,marginBottom:6}}>Compression</div>
            <div style={{fontWeight:800,fontSize:26,color:T.accent,lineHeight:1}}>
              {current?.compression}×
            </div>
            <div style={{fontSize:11,color:T.textDim,marginTop:4}}>
              {fmt(current?.bins_total)} → {fmt(current?.orbits_total)} orbits
            </div>
            <div style={{fontSize:10,color:T.accent2,marginTop:3,fontFamily:"monospace",
              background:"#a855f70d",border:"1px solid #00c9a720",borderRadius:3,padding:"2px 6px",display:"inline-block"}}>
              {current?.method}
            </div>
          </div>
        </div>

        {/* ── Main ── */}
        <div style={{flex:1,padding:"24px 28px",overflowY:"auto"}}>

          {showDrop && (
            <div
              onDragOver={e=>{e.preventDefault();}}
              onDrop={e=>{e.preventDefault();handleFile(e.dataTransfer.files);}}
              onClick={()=>fileRef.current.click()}
              style={{border:`1.5px dashed ${T.border}`,borderRadius:10,padding:"24px 32px",
                textAlign:"center",cursor:"pointer",marginBottom:20,background:T.surface}}>
              <div style={{fontSize:24,marginBottom:8}}>⊕</div>
              <div style={{color:T.textDim,fontSize:13}}>Drop Dabih JSON or <span style={{color:T.accent}}>browse</span></div>
              <input ref={fileRef} type="file" accept=".json" style={{display:"none"}}
                onChange={e=>handleFile(e.target.files)}/>
            </div>
          )}

          {/* Run label */}
          <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:20}}>
            <div style={{fontWeight:800,fontSize:16,letterSpacing:"-0.3px"}}>
              {current?.run_id}
            </div>
            <span style={{fontSize:11,padding:"3px 10px",borderRadius:10,
              background:current?.complete?"#a855f718":"#f59e0b18",
              color:current?.complete?T.accent2:T.warn,
              border:`1px solid ${current?.complete?"#a855f730":"#f59e0b30"}`}}>
              {current?.complete?"✓ Complete":"⚠ Incomplete"}
            </span>
            <span style={{fontSize:10,padding:"2px 8px",borderRadius:4,
              background:"#00c8ff12",color:T.accent,border:"1px solid #3d7fff25",
              fontFamily:"monospace"}}>
              {current?.method}
            </span>
          </div>

          {/* ── OVERVIEW TAB ── */}
          {tab==="overview" && (
            <div>
              <div style={{display:"flex",gap:10,flexWrap:"wrap",marginBottom:20}}>
                <StatCard label="Class Coverage" value={current?.class_pct?.toFixed(1)+"%"} color={T.accent}
                  sub={`${fmt(current?.orbits_hit)} / ${fmt(current?.orbits_total)} orbits`}/>
                <StatCard label="Bin Coverage" value={current?.bin_pct?.toFixed(1)+"%"} color={T.accent2}
                  sub={`${fmt(current?.bins_covered)} / ${fmt(current?.bins_total)} bins`}/>
                <StatCard label="Sim Hits" value={fmt(current?.sim_hits_total)}
                  sub={`${fmt(current?.sim_bins_obs)} unique`}/>
                <StatCard label="Missed" value={fmt(current?.orbits_missed)}
                  color={current?.orbits_missed>0?T.warn:T.accent2}
                  sub="orbits"/>
                <StatCard label="Unresolved" value={current?.unresolved??0}
                  color={current?.unresolved>0?T.danger:T.accent2}
                  sub="labels"/>
              </div>

              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14}}>
                <div style={card}>
                  <div style={cardHdr}>Equivalence Class Coverage</div>
                  <div style={{padding:20,display:"flex",alignItems:"center",gap:20}}>
                    <Gauge pct={current?.class_pct} color={T.accent} label="classes"/>
                    <div style={{fontSize:12,color:T.textDim,lineHeight:2}}>
                      <div><span style={{color:T.text,fontWeight:600}}>{fmt(current?.orbits_hit)}</span> orbits hit</div>
                      <div><span style={{color:T.warn,fontWeight:600}}>{fmt(current?.orbits_missed)}</span> orbits missed</div>
                      <div><span style={{color:T.textDim}}>{fmt(current?.orbits_total)}</span> total classes</div>
                    </div>
                  </div>
                  <div style={{padding:"0 20px 18px"}}>
                    <ProgressBar pct={current?.class_pct} color1={T.accent} color2="#6ea8ff"/>
                  </div>
                </div>
                <div style={card}>
                  <div style={cardHdr}>Implied Bin Coverage</div>
                  <div style={{padding:20,display:"flex",alignItems:"center",gap:20}}>
                    <Gauge pct={current?.bin_pct} color={T.accent2} label="bins"/>
                    <div style={{fontSize:12,color:T.textDim,lineHeight:2}}>
                      <div><span style={{color:T.text,fontWeight:600}}>{fmt(current?.bins_covered)}</span> bins covered</div>
                      <div><span style={{color:T.textDim}}>{fmt(current?.bins_total-current?.bins_covered)}</span> uncovered</div>
                      <div><span style={{color:T.textDim}}>{fmt(current?.bins_total)}</span> total bins</div>
                    </div>
                  </div>
                  <div style={{padding:"0 20px 18px"}}>
                    <ProgressBar pct={current?.bin_pct} color1={T.accent2} color2="#7fffdc"/>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── COVERAGE TAB ── */}
          {tab==="coverage" && (
            <div>
              <div style={card}>
                <div style={cardHdr}>Class Coverage per Run</div>
                <div style={{padding:20}}>
                  {runs.map((r,i)=>(
                    <div key={i} style={{marginBottom:18}}>
                      <div style={{display:"flex",justifyContent:"space-between",
                        fontSize:12,marginBottom:6}}>
                        <span style={{fontFamily:"monospace",color:T.textDim}}>{r.run_id}</span>
                        <span style={{color:T.accent2,fontWeight:700}}>{r.class_pct.toFixed(1)}%</span>
                      </div>
                      <ProgressBar pct={r.class_pct} color1={T.accent} color2={T.accent2} height={8}/>
                      <div style={{fontSize:11,color:T.textMuted,marginTop:4}}>
                        {fmt(r.orbits_hit)} / {fmt(r.orbits_total)} orbits · {fmt(r.sim_hits_total)} hits
                      </div>
                    </div>
                  ))}
                  {merged && (
                    <div style={{marginTop:16,paddingTop:14,borderTop:`1px solid ${T.border}`}}>
                      <div style={{display:"flex",justifyContent:"space-between",fontSize:12,marginBottom:6}}>
                        <span style={{color:T.accent,fontWeight:600}}>⊕ Merged</span>
                        <span style={{color:T.accent2,fontWeight:700}}>{merged.class_pct.toFixed(1)}%</span>
                      </div>
                      <div style={{height:10,background:T.border,borderRadius:5,overflow:"hidden"}}>
                        <div style={{height:"100%",width:`${merged.class_pct}%`,
                          background:"linear-gradient(90deg,#6366f1,#00c8ff,#a855f7)",
                          borderRadius:5,transition:"width .9s cubic-bezier(.4,0,.2,1)"}}/>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ── HOLES TAB ── */}
          {tab==="holes" && (
            <div>
              <div style={card}>
                <div style={cardHdr}>
                  <span>Uncovered Orbit Representatives — {current?.holes?.length??0} holes</span>
                  <input value={hSearch} onChange={e=>setHSearch(e.target.value)}
                    placeholder="Filter…"
                    style={{background:T.bg,border:`1px solid ${T.border}`,borderRadius:5,
                      padding:"3px 9px",fontSize:11,color:T.text,fontFamily:"monospace",
                      outline:"none",width:180}}/>
                </div>
                <HoleGrid holes={current?.holes??[]} search={hSearch}/>
              </div>
            </div>
          )}

          {/* ── RUN HISTORY TAB ── */}
          {tab==="runs" && (
            <div>
              <div style={card}>
                <div style={cardHdr}>Class Coverage by Run</div>
                <div style={{padding:20,display:"flex",alignItems:"flex-end",gap:12,height:130}}>
                  {runs.map((r,i)=>(
                    <div key={i} style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center",gap:5,cursor:"pointer"}}
                      onClick={()=>{setActive(i);setTab("overview");}}>
                      <span style={{fontSize:11,color:T.accent2,fontWeight:700}}>
                        {r.class_pct.toFixed(0)}%
                      </span>
                      <div style={{width:"100%",height:80,background:T.border,borderRadius:4,position:"relative",overflow:"hidden"}}>
                        <div style={{position:"absolute",bottom:0,width:"100%",height:`${r.class_pct}%`,
                          background:"linear-gradient(180deg,#00c8ff,#a855f7)",
                          borderRadius:4,transition:"height .6s cubic-bezier(.4,0,.2,1)"}}/>
                      </div>
                      <span style={{fontSize:9,color:T.textDim,fontFamily:"monospace",
                        maxWidth:60,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>
                        {r.run_id}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
              <div style={card}>
                <div style={cardHdr}>Run Details</div>
                <table style={{width:"100%",borderCollapse:"collapse"}}>
                  <thead>
                    <tr style={{background:T.surfaceHi}}>
                      {["Run ID","Simulator","Method","Hit / Total","Class %","Bin %","Hits"].map(h=>(
                        <th key={h} style={{padding:"8px 14px",fontSize:10,letterSpacing:"0.08em",
                          textTransform:"uppercase",color:T.textDim,textAlign:"left",
                          borderBottom:`1px solid ${T.border}`}}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((r,i)=>(
                      <tr key={i} onClick={()=>{setActive(i);setTab("overview");}}
                        style={{cursor:"pointer"}}>
                        {[r.run_id,r.simulator,r.method,
                          `${fmt(r.orbits_hit)} / ${fmt(r.orbits_total)}`,
                          <span style={{color:T.accent}}>{r.class_pct.toFixed(1)}%</span>,
                          <span style={{color:T.accent2}}>{r.bin_pct.toFixed(1)}%</span>,
                          fmt(r.sim_hits_total)
                        ].map((v,j)=>(
                          <td key={j} style={{padding:"9px 14px",fontSize:11,fontFamily:"monospace",
                            borderBottom:`1px solid ${T.border}`,color:T.textDim}}>{v}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── CONFIDENCE TAB ── */}
          {tab==="confidence" && (
            <div>
              {!current?.provenance ? (
                <div style={{color:T.textDim,fontSize:13,padding:"32px 0"}}>
                  No provenance data — run with <span style={{color:T.accent,fontFamily:"monospace"}}>
                  track_provenance=True</span> or <span style={{color:T.accent,
                  fontFamily:"monospace"}}>dabih expand --provenance</span> to enable.
                </div>
              ) : (()=>{
                const P = current.provenance;
                const hist = P.histogram || {};
                const maxV = Math.max(...Object.values(hist).map(Number), 1);
                return (
                  <div>
                    {/* Summary cards */}
                    <div style={{display:"flex",gap:10,flexWrap:"wrap",marginBottom:20}}>
                      <StatCard label="Single-seed (fragile)" value={fmt(P.single_count)}
                        color={T.warn} sub="covered by 1 run only"/>
                      <StatCard label="Two-seed" value={fmt(P.two_count)}
                        color={T.textDim}/>
                      <StatCard label="Well-covered (≥3)" value={fmt(P.well_covered)}
                        color={T.accent2} sub="robust coverage"/>
                      <StatCard label="Fragile orbits" value={fmt(P.fragile_count)}
                        color={T.warn} sub={`threshold: 2 seeds`}/>
                    </div>

                    {/* Histogram */}
                    <div style={card}>
                      <div style={cardHdr}>
                        <span>Seed Coverage Histogram</span>
                        <span style={{fontSize:11,color:T.textDim,fontFamily:"monospace"}}>
                          {Object.keys(hist).length} bucket(s) · max {P.max_seeds} seed{P.max_seeds!==1?"s":""}
                        </span>
                      </div>
                      <div style={{padding:20}}>
                        {Object.entries(hist)
                          .sort((a,b)=>+a[0]-+b[0])
                          .map(([seeds,n])=>{
                            const w   = Math.round((Number(n)/maxV)*300);
                            const col = +seeds===1 ? T.warn
                                      : +seeds===2 ? T.textDim : T.accent2;
                            return (
                              <div key={seeds} style={{display:"flex",alignItems:"center",
                                gap:12,marginBottom:12,fontSize:12,fontFamily:"monospace"}}>
                                <span style={{width:70,textAlign:"right",color:T.textDim}}>
                                  {seeds} seed{+seeds!==1?"s":""}
                                </span>
                                <div style={{height:10,width:Math.max(w,2),
                                  background:col,borderRadius:3,
                                  transition:"width .7s cubic-bezier(.4,0,.2,1)"}}/>
                                <span style={{color:col,fontWeight:700}}>
                                  {Number(n).toLocaleString()}
                                </span>
                                <span style={{color:T.textMuted}}>
                                  orbit{n!==1?"s":""}
                                </span>
                              </div>
                            );
                          })
                        }
                      </div>
                    </div>

                    {/* Fragile orbits */}
                    <div style={card}>
                      <div style={cardHdr}>
                        <span>
                          Fragile Orbits
                          <span style={{color:T.warn,marginLeft:8,fontWeight:400}}>
                            ⚠ covered by 1 seed only
                          </span>
                        </span>
                        <span style={{fontSize:11,color:T.textDim,fontFamily:"monospace"}}>
                          {P.fragile_count} orbit{P.fragile_count!==1?"s":""}
                        </span>
                      </div>
                      {P.fragile_reps?.length ? (
                        <div style={{display:"flex",flexWrap:"wrap",gap:6,
                          padding:16,maxHeight:260,overflowY:"auto"}}>
                          {P.fragile_reps.slice(0,80).map((r,i)=>(
                            <div key={i} style={{background:"#f59e0b10",
                              border:"1px solid #f59e0b28",borderRadius:4,
                              padding:"3px 8px",fontSize:11,fontFamily:"monospace",
                              color:T.warn,display:"flex",gap:4}}>
                              {r.map((v,j)=>(
                                <span key={j} style={{color:j%2===0?T.accent2:T.textDim}}>
                                  {v}
                                </span>
                              ))}
                            </div>
                          ))}
                          {P.fragile_reps.length>80 && (
                            <span style={{color:T.textDim,fontSize:11,alignSelf:"center"}}>
                              +{P.fragile_reps.length-80} more…
                            </span>
                          )}
                        </div>
                      ) : (
                        <div style={{padding:32,textAlign:"center",
                          color:T.textDim,fontSize:13}}>✓ No fragile orbits</div>
                      )}
                    </div>
                  </div>
                );
              })()}
            </div>
          )}

          {/* ── SYMMETRY TAB ── */}
          {tab==="symmetry" && (
            <div>
              <div style={{display:"flex",flexWrap:"wrap",gap:14}}>
                {(current?.declarations??[]).map((d,i)=>(
                  <div key={i} style={{...card,padding:22,minWidth:230,marginBottom:0}}>
                    <div style={{fontSize:10,fontWeight:600,letterSpacing:"0.1em",textTransform:"uppercase",
                      color:T.accent,marginBottom:8}}>{d.type}</div>
                    <div style={{fontWeight:800,fontSize:20,color:T.text,marginBottom:10}}>{d.group}</div>
                    <div style={{fontSize:11,color:T.textDim,fontFamily:"monospace",lineHeight:1.9}}>
                      {d.instance_indices&&`Instances: [${d.instance_indices.join(", ")}]`}
                      {d.pairs&&`Pairs: ${d.pairs.map(p=>p.join("↔")).join(", ")}`}
                      <br/>Block size: {d.block_size??1}
                      <br/>Generators: {d.n_generators}
                    </div>
                  </div>
                ))}
                {(!current?.declarations?.length)&&(
                  <div style={{color:T.textDim,fontSize:13}}>No structured declarations.</div>
                )}
              </div>
            </div>
          )}

          {/* ── COVERPOINTS TAB ── */}
          {tab==="coverpoints" && (
            <div>
              <div style={{display:"flex",flexWrap:"wrap",gap:8}}>
                {(current?.coverpoints??[]).map((cp,i)=>(
                  <div key={i} style={{background:T.surfaceHi,border:`1px solid ${T.border}`,
                    borderRadius:5,padding:"4px 10px",fontSize:11,fontFamily:"monospace",
                    color:T.textDim}}>{cp}</div>
                ))}
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
