/* The guides' motion engine (tools/figure/guide-*.html). Build-time only.

   Built on GSAP 3, fetched at render time by tools/render_guides.py (never shipped):
   - core: one paused timeline holds every motion; render(t) seeks it, so a frame is a
     function of t alone, and the eases are GSAP's;
   - scroll (ScrollToPlugin): the steps are one tall page and the camera scrolls to the
     next step, so a step change is one continuous motion, not a cut;
   - text (SplitText, TextPlugin): headlines rise word by word, body copy line by line;
     commands and chat input are typed;
   - SVG (DrawSVGPlugin): the logo and the role icons are drawn in, stroke by stroke;
   - UI (Flip): a kept score flies from its cycle to "best so far".

   Pacing is computed, not hand-tuned: inside a step every cue is PACE.at times its
   data-at, every motion PACE.dur times its base length, and a step holds until its
   headline and text can be read at PACE.wps words a second, and at least PACE.hold
   seconds after its last motion. A page calls DECK.start({ steps: [...] }) and gets window.render(t) and
   window.TOTAL. Discrete states (a class, a swapped label, a caret, the progress line) are
   set from t after the seek, without callbacks. */
(function () {
  gsap.registerPlugin(ScrollToPlugin, SplitText, TextPlugin, DrawSVGPlugin, Flip);
  const PACE = { at: 1.4, dur: 1.3, cps: 18, wps: 4.2, hold: 2.4, scroll: 1.1, end: 3.5 };
  const H = 1080;
  const A = s => +s * PACE.at, M = s => s * PACE.dur;
  const clamp = k => Math.max(0, Math.min(1, k));
  const words = e => (e.textContent.match(/\S+/g) || []).length;

  function start(cfg) {
    const STEPS = cfg.steps, NSTEP = STEPS.length;
    const css = document.createElement("style");
    css.textContent = `
      #view { position: absolute; inset: 0; overflow: hidden;
        -webkit-mask-image: linear-gradient(to bottom, transparent 108px, #000 146px, #000 936px, transparent 972px);
                mask-image: linear-gradient(to bottom, transparent 108px, #000 146px, #000 936px, transparent 972px); }
      #reel { position: relative; width: 100%; }
      .top, .prog { z-index: 2; }
      .hl { background-repeat: no-repeat; background-size: 100% 100%; }`;
    document.head.appendChild(css);
    const scenes = [...document.querySelectorAll(".scene")];

    // the tall page: every step stacked, inside a masked viewport the camera scrolls
    const view = document.createElement("div"); view.id = "view";
    const reel = document.createElement("div"); reel.id = "reel";
    view.appendChild(reel); document.body.insertBefore(view, document.querySelector(".top"));
    scenes.forEach((sc, i) => {
      reel.appendChild(sc);
      Object.assign(sc.style, { visibility: "visible", top: `${i * H}px`, height: `${H}px`, bottom: "auto" });
    });
    reel.style.height = `${scenes.length * H}px`;

    // cues: data-fx / data-at, with defaults for the headline, the body and the main card
    scenes.forEach(sc => {
      [[".left .body", 0.55], [".left .tags", 0.85], [".src", 1.05], [".card", 0.15]].forEach(([q, at]) =>
        sc.querySelectorAll(q).forEach(e => {
          if (!e.dataset.at) { e.dataset.at = at; e.dataset.fx = e.dataset.fx || (q === ".card" ? "card" : q === ".left .body" ? "lines" : "up"); }
        }));
      sc.h1 = sc.querySelector("h1");
      sc.cues = [...sc.querySelectorAll("[data-fx]")];
      sc.cues.forEach(e => {
        if (e.dataset.fx === "swap") { e.vals = e.dataset.vals.split("|"); e.ats = e.dataset.ats.split("|").map(Number); }
        if (e.dataset.fx === "type") {
          e.dataset.full = e.dataset.text;   // what the line says once typed (checked against kl.py)
          e.textContent = "";
          e.caret = document.createElement("span"); e.caret.className = "caret"; e.after(e.caret);
          e.typeDur = e.dataset.dur ? M(+e.dataset.dur) : e.dataset.text.length / PACE.cps;
        }
        if (e.dataset.fx === "compose") {
          e.innerHTML = '<span class="ph">Message</span><span class="tx"></span><span class="caret"></span>';
          [e.ph, e.tx, e.caret] = e.children;
        }
      });
    });

    // how long each cue runs, in step-local seconds, and so how long each step lasts
    function end(e) {
      const at = A(e.dataset.at), f = e.dataset.fx;
      if (f === "type") return at + e.typeDur + 0.5;
      if (f === "compose") return A(e.dataset.send) + 0.2;
      if (f === "swap") return A(Math.max(...e.ats)) + M(0.4);
      if (f === "state") return Math.max(...[e.dataset.on, e.dataset.cur].map(v => +(v ?? -1)).filter(v => v < 50).map(A), 0);
      return at + M({ card: 0.6, deal: 0.6, pop: 0.4, lines: 0.9 }[f] || 0.45);
    }
    const DUR = scenes.map((sc, i) => {
      const last = Math.max(1.2, ...sc.cues.map(end));
      const read = words(sc.querySelector(".left")) / PACE.wps + 1.0;   // the headline and its text
      const hold = Math.max(last + PACE.hold, read);
      return hold + (i === scenes.length - 1 ? PACE.end : PACE.scroll);
    }).map(d => Math.round(d * 10) / 10);
    const START = DUR.reduce((a, d, i) => (a.push(i ? a[i - 1] + DUR[i - 1] : 0), a), []);
    const TOTAL = START[START.length - 1] + DUR[DUR.length - 1];

    // the progress line and the step counter
    const prog = document.getElementById("prog");
    STEPS.forEach((s, i) => {
      const g = document.createElement("div"); g.className = "sg";
      g.innerHTML = `<div class="tr"><div class="fl"></div></div><div class="lb"><b>${String(i + 1).padStart(2, "0")}</b>${s}</div>`;
      prog.appendChild(g);
    });
    const segs = [...prog.children], stepno = document.getElementById("stepno");

    // inline <use> icons so DrawSVG can reach their strokes
    function inline(svg) {
      const use = svg.querySelector("use"); if (!use) return svg;
      const sym = document.querySelector(use.getAttribute("href"));
      svg.setAttribute("viewBox", sym.getAttribute("viewBox"));
      [...sym.children].forEach(c => svg.appendChild(c.cloneNode(true))); use.remove();
      return svg;
    }
    const strokes = svg => [...svg.querySelectorAll("path,rect,circle")].filter(s => s.getAttribute("stroke"));

    let tl = null;
    function build() {
      tl = gsap.timeline({ paused: true, defaults: { ease: "power3.out" } });
      // Flip measures layout, so it goes first, before any other motion is set
      const flights = [];
      scenes.forEach((sc, i) => sc.querySelectorAll("[data-fly]").forEach(src => {
        const dst = sc.querySelector("[data-fly-dst]"), ghost = src.cloneNode(true);
        dst.textContent = dst.vals[dst.vals.length - 1]; gsap.set(dst, { display: "inline-block" });   // measure it as it will be
        ghost.removeAttribute("data-fly"); sc.querySelector(".win").appendChild(ghost);
        Object.assign(ghost.style, { position: "absolute", left: "0px", top: "0px", margin: "0", zIndex: 5 });
        const from = Flip.fit(ghost, src, { getVars: true, scale: true });
        const to = Flip.fit(ghost, dst, { getVars: true, scale: true });
        const at = START[i] + A(src.dataset.fly), d = M(0.75);
        flights.push([ghost, from, to, at, d]);
        dst.ats[dst.ats.length - 1] = (at + d - START[i]) / PACE.at;   // the header changes as it lands
      }));

      const logo = inline(document.querySelector(".brand svg"));
      tl.fromTo(strokes(logo), { drawSVG: "0%" }, { drawSVG: "100%", duration: 1.4, ease: "power2.inOut", stagger: 0.15 }, 0.1);

      scenes.forEach((sc, i) => {
        const S = START[i];
        if (i) tl.to(view, { scrollTo: { y: i * H, autoKill: false }, duration: PACE.scroll, ease: "power2.inOut" }, S - PACE.scroll);
        // the headline: words rise in, then the marker sweeps under the key phrase
        const split = SplitText.create(sc.h1, { type: "words" });
        tl.fromTo(split.words, { opacity: 0, y: 42 }, { opacity: 1, y: 0, duration: M(0.6), stagger: 0.07 }, S + 0.1);
        sc.h1.querySelectorAll(".hl").forEach(h =>
          tl.fromTo(h, { backgroundSize: "0% 100%" }, { backgroundSize: "100% 100%", duration: M(0.5), ease: "power2.inOut" },
            S + 0.1 + split.words.length * 0.07 + M(0.3)));
        // the step's main card is already there as the camera scrolls to it
        sc.cues.forEach(e => cue(e, S, i && e.dataset.fx === "card" ? -PACE.scroll : A(e.dataset.at), e.dataset.fx));
      });
      flights.forEach(([g, from, to, at, d]) => {
        tl.fromTo(g, from, { ...to, duration: d, ease: "power2.inOut", immediateRender: true }, at);
        tl.fromTo(g, { opacity: 0 }, { opacity: 1, duration: 0.12, ease: "none" }, at);
        tl.to(g, { opacity: 0, duration: 0.15, ease: "none" }, at + d);
      });
    }

    function cue(e, S, at, f) {
      const t0 = S + at;
      if (f === "up") tl.fromTo(e, { opacity: 0, y: 26 }, { opacity: 1, y: 0, duration: M(0.45) }, t0);
      else if (f === "card") tl.fromTo(e, { opacity: 0, x: 70, scale: 0.97 }, { opacity: 1, x: 0, scale: 1, duration: at < 0 ? PACE.scroll : M(0.6) }, t0);
      else if (f === "lines") {
        const s = SplitText.create(e, { type: "lines" });
        tl.fromTo(s.lines, { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: M(0.5), stagger: 0.12 }, t0);
      } else if (f === "deal") {
        tl.fromTo(e, { y: 160, rotation: +(e.dataset.rot || -6) }, { y: 0, rotation: 0, duration: M(0.6), ease: "back.out(1.1)" }, t0);
        tl.fromTo(e, { opacity: 0 }, { opacity: 1, duration: M(0.2), ease: "none" }, t0);
        e.querySelectorAll(".av svg").forEach(svg =>
          tl.fromTo(strokes(inline(svg)), { drawSVG: "0%" }, { drawSVG: "100%", duration: M(0.7), ease: "power2.inOut", stagger: 0.1 }, t0 + M(0.35)));
      } else if (f === "pop") {
        gsap.set(e, { display: "inline-block" });
        tl.fromTo(e, { opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1, duration: M(0.4), ease: "back.out(2)" }, t0);
      } else if (f === "ai") {
        const [who, dots, body] = e.children, typing = 0.9;
        tl.fromTo(who, { opacity: 0 }, { opacity: 1, duration: 0.2, ease: "none" }, t0 - typing);
        tl.fromTo(dots, { opacity: 0 }, { opacity: 1, duration: 0.15, ease: "none" }, t0 - typing);
        tl.fromTo(dots.children, { y: 0 }, { y: -6, duration: 0.2, ease: "sine.inOut", yoyo: true, repeat: 3, stagger: 0.1 }, t0 - typing);
        tl.to(dots, { opacity: 0, duration: 0.12, ease: "none" }, t0);
        tl.fromTo(body, { opacity: 0, y: 22 }, { opacity: 1, y: 0, duration: M(0.45) }, t0);
        e.querySelectorAll(".hd svg").forEach(svg =>
          tl.fromTo(strokes(inline(svg)), { drawSVG: "0%" }, { drawSVG: "100%", duration: M(0.5), ease: "power2.inOut" }, t0 + 0.2));
      } else if (f === "swap") {
        gsap.set(e, { display: "inline-block" });
        e.ats.slice(1).forEach(a => tl.fromTo(e, { scale: 0.75 }, { scale: 1, duration: M(0.4), ease: "back.out(2)", immediateRender: false }, S + A(a)));
      } else if (f === "type") {
        tl.fromTo(e, { text: "" }, { text: e.dataset.text, duration: e.typeDur, ease: "none" }, t0);
      } else if (f === "compose") {
        const snd = S + A(e.dataset.send);
        tl.fromTo(e.ph, { opacity: 1 }, { opacity: 0, duration: 0.05, ease: "none" }, t0);
        tl.fromTo(e.tx, { text: "" }, { text: e.dataset.text, duration: Math.max(0.3, snd - 0.3 - t0), ease: "none" }, t0);
        tl.set(e.tx, { text: "" }, snd);
        tl.set(e.ph, { opacity: 1 }, snd);
      }
    }

    // discrete states, from t alone
    const blink = t => Math.floor(t * 2.4) % 2 === 0;
    function states(t, cur) {
      scenes.forEach((sc, i) => {
        const lt = t - START[i];
        sc.cues.forEach(e => {
          const f = e.dataset.fx;
          if (f === "state") {
            const on = lt >= A(e.dataset.on ?? 99), now = lt >= A(e.dataset.cur ?? 99) && !on;
            e.classList.toggle("on", on); e.classList.toggle("cur", now);
          } else if (f === "swap") {
            let k = 0; e.ats.forEach((a, j) => { if (lt >= A(a)) k = j; });
            if (e.textContent !== e.vals[k]) e.textContent = e.vals[k];
            if (e.dataset.cls) e.classList.toggle(e.dataset.cls, k > 0);
          } else if (f === "type") {
            const at = A(e.dataset.at), live = lt >= at && lt < at + e.typeDur + 0.6;
            e.caret.style.opacity = live && (lt < at + e.typeDur || blink(t)) ? 1 : 0;
          } else if (f === "compose") {
            const at = A(e.dataset.at), snd = A(e.dataset.send);
            e.caret.style.opacity = lt >= at && lt < snd && (lt < snd - 0.3 || blink(t)) ? 1 : 0;
          }
        });
      });
      const lt = t - START[cur];
      stepno.innerHTML = cur === 0 ? `<b>${NSTEP}</b> STEPS` : cur > NSTEP ? "<b>DONE</b>" :
        `STEP <b>${String(cur).padStart(2, "0")}</b> / ${String(NSTEP).padStart(2, "0")}`;
      segs.forEach((g, j) => {
        const step = j + 1, f = step < cur ? 1 : step === cur ? clamp(lt / (DUR[cur] - PACE.scroll)) : 0;
        g.querySelector(".fl").style.width = `${f * 100}%`;
        g.classList.toggle("cur", step === cur); g.classList.toggle("done", step < cur);
      });
    }

    function render(t) {
      if (!tl) build();
      t = Math.max(0, Math.min(t, TOTAL - 1e-6));
      tl.time(t, true);
      // the step on screen: the next one once the camera is more than half way there
      let cur = START.findIndex((s, i) => t >= s && t < s + DUR[i]);
      if (cur < scenes.length - 1 && t > START[cur + 1] - PACE.scroll / 2) cur += 1;
      states(t, cur);
    }
    window.render = render;
    window.TOTAL = TOTAL;
    window.STEP_TIMES = START.map((s, i) => [s, DUR[i]]);
    window.POSTER = START[cfg.poster] + DUR[cfg.poster] - PACE.scroll - 0.6;   // a finished, busy frame
  }
  window.DECK = { start, PACE };
})();
