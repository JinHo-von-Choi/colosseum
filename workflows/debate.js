export const meta = {
  name: 'debate',
  description: 'Colosseum: blind drafts, vote baseline, quote-verified evidence rounds, computed verdicts',
  whenToUse: 'Launched by the colosseum skill with a prepared roster; not for direct use',
  phases: [
    { title: 'Materials', detail: 'read the materials the user supplied' },
    { title: 'Fact base', detail: 'opposing-angle searches and source records' },
    { title: 'Drafts', detail: 'blind parallel drafts from the roster' },
    { title: 'Verify', detail: 'quote checks against fetched pages' },
    { title: 'Baseline', detail: 'position groups, family-weighted vote, pooled probability' },
    { title: 'Antithesis', detail: 'decision mode: the strongest plan built on the opposite assumptions' },
    { title: 'Issues', detail: 'double cruxes from the drafts' },
    { title: 'Rounds', detail: 'prosecutor, adverse witness, defender' },
    { title: 'Verdict', detail: 'order-swapped juror, argument-graph engine, premortem' },
    { title: 'Report', detail: 'final report' },
  ],
}

// ==== colosseum-lib begin ====
// Pure functions shared with skills/colosseum/scripts (Python). tests/test_js_parity.py
// runs this block under Node and compares its results with the Python implementation.

const LIB = (() => {
  const RELIABILITY = { high: 0.9, medium: 0.6, low: 0.3 }
  const QUOTE = { v: 1.0, snippet: 0.5, n: 0.0, u: 0.0 }
  const SUPPORT = { full: 1.0, partial: 0.5, none: 0.0, unknown: 0.0 }
  const FRESHNESS = { fresh: 1.0, na: 1.0, unknown: 0.75, stale: 0.5, superseded: 0.0 }
  const CLAIM_KINDS = new Set(['fact', 'statistic', 'causal', 'forecast', 'value', 'recommendation'])
  const CLAIM_STATUS = new Set(['active', 'withdrawn'])
  const VALUE_KINDS = new Set(['value', 'recommendation'])
  const GRAPH_SCHEMA = 'colosseum.arggraph/v2'
  const POLICY_VERSION = 'evidence-policy/2'
  const has = (obj, k) => typeof k === 'string' && Object.prototype.hasOwnProperty.call(obj, k)
  const NO_EVIDENCE_PRIOR = 0.2
  const MARGIN = 0.15
  const THETA = 0.5
  const MAX_UNDEC = 16
  const CLIP = [0.02, 0.98]

  // ---- quote matching (quote_match.py, matcher quote-match/3) ----
  const MATCHER_VERSION = 'quote-match/3'
  const CHAR_MAP = {
    '‘': "'", '’': "'", '‚': "'", '‛': "'", '′': "'",
    '“': '"', '”': '"', '„': '"', '‟': '"', '″': '"',
    '‐': '-', '‑': '-', '‒': '-', '–': '-', '—': '-', '―': '-',
    '−': '-', '﹘': '-', '﹣': '-', '－': '-',
    ' ': ' ', ' ': ' ', ' ': ' ', '​': '',
  }
  const SIGNS = '+-±'
  const KEEP_SYMBOLS = new Set('<>=≤≥≠≈$€£¥₩%‰')
  const COMPARE_SYMBOLS = new Set('<>=≤≥≠≈')
  const SENTENCE_END = new Set('!?\n。')
  const QUALIFIERS = new Set(['if', 'unless', 'when', 'whenever', 'only', 'except', 'excluding', 'provided', 'assuming', 'until',
    '단', '다만', '만약', '경우', '경우에', '경우에는',
    '조건', '한해', '제외하고', '제외하면'])
  const QUALIFIER_SUFFIXES = ['면', '경우', '때', '때는', '때만', '더라도']
  const isWord = (ch) => ch === '_' || /[\p{L}\p{M}\p{N}]/u.test(ch)
  const isDigit = (ch) => /\p{Nd}/u.test(ch)
  function stripMarkdown(text) {
    let out = '', i = 0
    const n = text.length
    while (i < n) {
      const ch = text[i]
      if (ch === '!' && i + 1 < n && text[i + 1] === '[') { i++; continue }
      if (ch === '[') {
        const close = text.indexOf(']', i + 1)
        if (close !== -1 && close + 1 < n && text[close + 1] === '(') {
          const end = text.indexOf(')', close + 2)
          if (end !== -1) { out += text.slice(i + 1, close); i = end + 1; continue }
        }
      }
      out += ch
      i++
    }
    const lines = out.split('\n').map((line) => {
      let s = line.replace(/^\s+/, '')
      let j = 0
      while (j < s.length && '#>'.includes(s[j])) j++
      if (j && (j === s.length || s[j] === ' ')) s = s.slice(j)
      s = s.replace(/^\s+/, '')
      if (s.length > 1 && '*-+'.includes(s[0]) && s[1] === ' ') s = s.slice(2)
      return s
    })
    return Array.from(lines.join('\n'), (ch) => ('*_`~|'.includes(ch) ? ' ' : ch)).join('')
  }
  function normalize(text) {
    let t = String(text || '').normalize('NFKC')
    t = Array.from(t, (ch) => (ch in CHAR_MAP ? CHAR_MAP[ch] : ch)).join('')
    t = stripMarkdown(t).toLowerCase()
    return t.split('\n').map((line) => line.split(/\s+/).filter(Boolean).join(' ')).filter(Boolean).join('\n')
  }
  function tokenize(norm) {
    const c = Array.from(norm), n = c.length, toks = [], ends = []
    let i = 0
    while (i < n) {
      const ch = c[i], prev = i ? c[i - 1] : ' '
      const signed = SIGNS.includes(ch) && i + 1 < n && isDigit(c[i + 1]) && !isWord(prev) && !'.,'.includes(prev)
      if (signed || isDigit(ch)) {
        let j = signed ? i + 1 : i
        while (j < n && isDigit(c[j])) j++
        while (j + 1 < n && '.,'.includes(c[j]) && isDigit(c[j + 1])) { j++; while (j < n && isDigit(c[j])) j++ }
        while (j < n && (isWord(c[j]) || '%‰'.includes(c[j]))) j++
        toks.push(c.slice(i, j).join('')); ends.push(false); i = j
      } else if (isWord(ch)) {
        let j = i
        while (j < n && (isWord(c[j]) || (c[j] === "'" && j + 1 < n && isWord(c[j + 1]) && j > i))) j++
        toks.push(c.slice(i, j).join('')); ends.push(false); i = j
      } else if (KEEP_SYMBOLS.has(ch)) {
        toks.push(ch); ends.push(false); i++
      } else {
        if (ends.length && (SENTENCE_END.has(ch) || (ch === '.' && (i + 1 >= n || ' \n"\')'.includes(c[i + 1]))))) ends[ends.length - 1] = true
        i++
      }
    }
    return [toks, ends]
  }
  const isQualifier = (t) => QUALIFIERS.has(t) || (Array.from(t).length >= 2 && t.charCodeAt(0) >= 128 && QUALIFIER_SUFFIXES.some((s) => t.endsWith(s)))
  const cmpStr = (a, b) => (a < b ? -1 : a > b ? 1 : 0)
  function findRun(q, p) {
    for (let s = 0; s + q.length <= p.length; s++) {
      let k = 0
      while (k < q.length && p[s + k] === q[k]) k++
      if (k === q.length) return s
    }
    return -1
  }
  function matchQuote(quote, page) {
    const [q] = tokenize(normalize(quote))
    const [p, ends] = tokenize(normalize(page))
    const out = { matcher: MATCHER_VERSION, words: q.length }
    if (!q.length || !p.length) return Object.assign(out, { status: 'u', score: 0, reason: 'empty quote or page' })
    if (q.length > 50) out.warning = 'quote longer than 50 words'
    const start = findRun(q, p)
    if (start >= 0) {
      const end = start + q.length
      let lo = start, hi = end
      while (lo > 0 && !ends[lo - 1]) lo--
      while (hi < ends.length && !ends[hi - 1]) hi++
      const dropped = [...new Set(p.slice(lo, start).concat(p.slice(end, hi)).filter(isQualifier))].sort(cmpStr)
      Object.assign(out, { score: 1, span: [start, end] })
      if (dropped.length) return Object.assign(out, { status: 'n', kind: 'qualifier_omitted', reason: 'quote leaves out part of its sentence that carries a condition or scope: ' + dropped.join(', ') })
      return Object.assign(out, { status: 'v', reason: 'exact' })
    }
    return Object.assign(out, { status: 'u', score: 0, reason: 'not found on the page' })
  }

  // ---- baseline (baseline.py) ----
  const clip = (p) => Math.min(CLIP[1], Math.max(CLIP[0], Number(p)))
  const logit = (p) => Math.log(p / (1 - p))
  function familyVote(drafts) {
    const byFam = {}
    for (const d of drafts) (byFam[d.family] = byFam[d.family] || []).push(d.position)
    const tally = {}
    for (const positions of Object.values(byFam)) {
      const counts = {}
      for (const p of positions) counts[p] = (counts[p] || 0) + 1
      const top = Math.max(...Object.values(counts))
      const winners = Object.keys(counts).filter((p) => counts[p] === top).sort()
      for (const p of winners) tally[p] = (tally[p] || 0) + 1 / winners.length
    }
    const ranked = Object.entries(tally).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
    const tie = ranked.length > 1 && Math.abs(ranked[0][1] - ranked[1][1]) < 1e-9
    return { tally: Object.fromEntries(ranked.map(([k, v]) => [k, Math.round(v * 1000) / 1000])), winner: tie ? null : ranked[0][0], tie, families: Object.keys(byFam).length }
  }
  function pooledProbability(drafts, position, a) {
    const famSize = {}
    for (const d of drafts) famSize[d.family] = (famSize[d.family] || 0) + 1
    const k = new Set(drafts.map((d) => d.position).concat([position])).size
    let acc = 0, total = 0
    for (const d of drafts) {
      const p = clip(d.probability)
      const pPos = d.position === position ? p : (1 - p) / Math.max(1, k - 1)
      const w = 1 / famSize[d.family]
      acc += w * logit(clip(pPos))
      total += w
    }
    return 1 / (1 + Math.exp(-a * (acc / total)))
  }
  function baseline(doc, a = 1.0) {
    const drafts = doc.drafts
    if (!drafts || !drafts.length) throw new Error('no drafts')
    const vote = familyVote(drafts)
    const notes = []
    const sameSide = new Set(drafts.map((d) => d.position)).size === 1
    if (a > 1 && !(vote.families >= 2 && sameSide)) { notes.push('extremizing needs 2+ families on the same side; a reset to 1.0'); a = 1 }
    a = Math.min(a, 1.3)
    const target = vote.winner !== null ? vote.winner : Object.keys(vote.tally).sort()[0]
    const p0 = pooledProbability(drafts, target, a)
    const homogeneous = vote.families < 2
    const skip = sameSide && !homogeneous && drafts.every((d) => Number(d.probability) >= 0.8) && !doc.verified_counter
    return { baseline_vote: vote.winner, tie: vote.tie, tally: vote.tally, p0_position: target, p0: Math.round(p0 * 1000) / 1000, p0_method: Object.keys(vote.tally).length <= 2 ? 'binary' : 'split over ' + Object.keys(vote.tally).length + ' positions', extremizing: a, roster: homogeneous ? 'homogeneous' : 'heterogeneous', unanimous: sameSide, skip_debate: skip, needs_dissenter: sameSide && homogeneous, notes }
  }

  // ---- graph and verdicts (graph.py, verdict_engine.py) ----
  function normalizeUrl(url) {
    let u
    try { u = new URL(String(url || '').trim()) } catch (err) { return '' }
    if (!['http:', 'https:'].includes(u.protocol) || !u.hostname) return ''
    const host = u.hostname.replace(/\.+$/, '')
    return u.protocol + '//' + host + (u.port ? ':' + u.port : '') + (u.pathname || '/') + (u.search && u.search !== '?' ? u.search : '')
  }
  function originOf(e) {
    if (e.origin) return String(e.origin)
    const url = normalizeUrl(e.url)
    let host = url ? url.split('://')[1].split('/')[0].split(':')[0] : ''
    if (host.startsWith('www.')) host = host.slice(4)
    return host ? 'host:' + host : 'unknown'
  }
  const eligible = (e) => QUOTE[e.quote_status] > 0 && (e.support === 'full' || e.support === 'partial') && (e.freshness || 'na') !== 'superseded'
  const evidenceScore = (e) => (eligible(e) ? RELIABILITY[e.reliability] * QUOTE[e.quote_status] * SUPPORT[e.support] * FRESHNESS[e.freshness || 'na'] : 0)
  function baseScore(claim, evById) {
    const best = {}
    for (const eid of claim.evidence || []) {
      const e = evById[eid], g = originOf(e)
      best[g] = Math.max(best[g] || 0, evidenceScore(e))
    }
    let miss = 1 - NO_EVIDENCE_PRIOR
    for (const s of Object.values(best)) miss *= 1 - s
    return 1 - miss
  }
  const hasChecked = (claim, evById) => (claim.evidence || []).some((eid) => eligible(evById[eid]))
  const relationKey = (r) => [r.type, r.subtype || '', r.from, r.to].join('\u0000')
  function dedupeRelations(relations) {
    const seen = new Set()
    return relations.filter((r) => { const k = relationKey(r); if (seen.has(k)) return false; seen.add(k); return true })
  }

  // Same checks, in the same order, as graph.validate; the first problem is reported.
  function validate(doc) {
    const isObj = (x) => !!x && typeof x === 'object' && !Array.isArray(x)
    if (!isObj(doc)) throw new Error('graph must be a JSON object')
    for (const k of ['evidence', 'claims', 'relations']) if (!Array.isArray(doc[k])) throw new Error('missing list: ' + k)
    const schema = doc.schema === undefined ? GRAPH_SCHEMA : doc.schema
    if (schema !== 'colosseum.arggraph/v1' && schema !== GRAPH_SCHEMA) throw new Error('unknown graph schema ' + doc.schema)
    const ev = new Set(), cl = new Set()
    for (const e of doc.evidence) {
      if (!isObj(e)) throw new Error('evidence must be an object')
      if (typeof e.id !== 'string' || !e.id) throw new Error('evidence without id')
      if (ev.has(e.id)) throw new Error('duplicate evidence id: ' + e.id)
      ev.add(e.id)
      if (!has(RELIABILITY, e.reliability)) throw new Error(e.id + ': bad reliability')
      if (!has(QUOTE, e.quote_status)) throw new Error(e.id + ': bad quote_status')
      if (!has(SUPPORT, e.support)) throw new Error(e.id + ': bad support')
      if (!has(FRESHNESS, e.freshness === undefined ? 'na' : e.freshness)) throw new Error(e.id + ': bad freshness')
    }
    for (const c of doc.claims) {
      if (!isObj(c)) throw new Error('claim must be an object')
      if (typeof c.id !== 'string' || !c.id) throw new Error('claim without id')
      if (cl.has(c.id)) throw new Error('duplicate claim id: ' + c.id)
      cl.add(c.id)
      if (!CLAIM_KINDS.has(c.kind === undefined ? 'fact' : c.kind)) throw new Error(c.id + ': bad kind')
      if (!CLAIM_STATUS.has(c.status === undefined ? 'active' : c.status)) throw new Error(c.id + ': bad status')
      if (c.evidence !== undefined && !Array.isArray(c.evidence)) throw new Error(c.id + ': evidence must be a list')
      for (const eid of c.evidence || []) if (!ev.has(eid)) throw new Error(c.id + ' cites unknown evidence ' + eid)
    }
    for (const r of doc.relations) {
      if (!isObj(r)) throw new Error('relation must be an object')
      if (r.type !== 'attack' && r.type !== 'support') throw new Error('relation type must be attack or support')
      if (!cl.has(r.from) || !cl.has(r.to)) throw new Error('relation ' + r.from + ' -> ' + r.to + ' references an unknown claim')
      if (r.from === r.to) throw new Error('self-relation on ' + r.from)
      if (r.type === 'attack' && !['rebut', 'undercut', 'undermine'].includes(r.subtype)) throw new Error('attack needs subtype')
    }
    for (const cf of doc.conflicts || []) {
      if (!isObj(cf)) throw new Error('conflict must be an object')
      if (!cl.has(cf.a) || !cl.has(cf.b)) throw new Error('conflict references an unknown claim')
    }
    return doc
  }

  const pairKey = (a, b) => a + '\u0000' + b
  function verdict(doc, theta = THETA) {
    validate(doc)
    const evById = Object.fromEntries(doc.evidence.map((e) => [e.id, e]))
    const nodes = {}
    for (const c of doc.claims) if ((c.status || 'active') === 'active') nodes[c.id] = c
    const ids = Object.keys(nodes).sort(cmpStr)
    const tau = Object.fromEntries(ids.map((n) => [n, baseScore(nodes[n], evById)]))
    const relations = dedupeRelations(doc.relations)
    const att = relations.filter((r) => r.type === 'attack' && has(nodes, r.from) && has(nodes, r.to))
    const sup = relations.filter((r) => r.type === 'support' && has(nodes, r.from) && has(nodes, r.to))
    const defeats = new Set(), demoted = []
    for (const r of att) {
      const unconditional = r.subtype === 'undercut' && hasChecked(nodes[r.from], evById)
      if (r.subtype === 'undercut' && !unconditional) demoted.push([r.from, r.to])
      if (unconditional || !(tau[r.to] > tau[r.from] + MARGIN)) defeats.add(pairKey(r.from, r.to))
    }
    const defeatList = [...defeats].map((k) => k.split('\u0000'))
    const attackers = Object.fromEntries(ids.map((n) => [n, defeatList.filter(([, b]) => b === n).map(([a]) => a)]))
    // grounded labelling
    const lab = {}
    let changed = true
    while (changed) {
      changed = false
      for (const n of ids) {
        if (n in lab) continue
        if (attackers[n].every((a) => lab[a] === 'OUT')) { lab[n] = 'IN'; changed = true }
        else if (attackers[n].some((a) => lab[a] === 'IN')) { lab[n] = 'OUT'; changed = true }
      }
    }
    for (const n of ids) if (!(n in lab)) lab[n] = 'UNDEC'
    // preferred and stable over the UNDEC part
    let preferred = null, stable = null
    const groundedIn = ids.filter((n) => lab[n] === 'IN')
    const undec = ids.filter((n) => lab[n] === 'UNDEC')
    if (undec.length <= MAX_UNDEC) {
      const cf = (S) => !S.some((a) => S.some((b) => defeats.has(pairKey(a, b))))
      const defended = (S) => S.every((n) => attackers[n].every((x) => S.some((d) => defeats.has(pairKey(d, x)))))
      const adm = []
      for (let mask = 0; mask < (1 << undec.length); mask++) {
        const S = groundedIn.concat(undec.filter((_, i) => mask & (1 << i)))
        if (cf(S) && defended(S)) adm.push(S)
      }
      const subset = (A, B) => A.length < B.length && A.every((x) => B.includes(x))
      const pref = adm.filter((S) => !adm.some((T) => subset(S, T)))
      const canon = (list) => [...new Set(list.map((S) => JSON.stringify([...S].sort())))].map((s) => JSON.parse(s)).sort((x, y) => (JSON.stringify(x) < JSON.stringify(y) ? -1 : 1))
      preferred = canon(pref)
      stable = canon(pref.filter((S) => ids.filter((x) => !S.includes(x)).every((x) => S.some((d) => defeats.has(pairKey(d, x))))))
    }
    // damped DF-QuAD
    const atk = Object.fromEntries(ids.map((n) => [n, att.filter((r) => r.to === n).map((r) => r.from).sort()]))
    const spt = Object.fromEntries(ids.map((n) => [n, sup.filter((r) => r.to === n).map((r) => r.from).sort()]))
    const agg = (vals) => 1 - vals.reduce((p, v) => p * (1 - v), 1)
    let s = { ...tau }, converged = false
    for (let it = 0; it < 500; it++) {
      const nw = {}
      for (const n of ids) {
        const va = agg(atk[n].map((a) => s[a])), vs = agg(spt[n].map((x) => s[x])), v0 = tau[n]
        const c = va >= vs ? v0 - v0 * (va - vs) : v0 + (1 - v0) * (vs - va)
        nw[n] = 0.5 * s[n] + 0.5 * c
      }
      const delta = ids.reduce((m, n) => Math.max(m, Math.abs(nw[n] - s[n])), 0)
      s = nw
      if (delta < 1e-9) { converged = true; break }
    }
    const status = {}
    for (const n of ids) status[n] = lab[n] === 'OUT' ? 'REJECTED' : lab[n] === 'UNDEC' ? 'UNDECIDED' : !converged ? 'IN_UNPROVEN' : s[n] >= theta ? 'ACCEPTED' : 'IN_UNPROVEN'
    const r3 = (x) => Math.round(x * 1000) / 1000
    const out = {
      policy: POLICY_VERSION, theta, labels: lab, status,
      base: Object.fromEntries(ids.map((n) => [n, r3(tau[n])])),
      strength: Object.fromEntries(ids.map((n) => [n, r3(s[n])])),
      qbaf_converged: converged,
      defeats: defeatList.sort(), demoted_undercuts: demoted.sort(),
      preferred, stable, conflicts: [],
    }
    for (const cf of doc.conflicts || []) {
      const a = cf.a, b = cf.b
      const sa = status[a] || 'WITHDRAWN', sb = status[b] || 'WITHDRAWN'
      const kinds = [a, b].filter((x) => nodes[x]).map((x) => nodes[x].kind || 'fact')
      let v
      if (kinds.some((k) => VALUE_KINDS.has(k))) v = 'VALUE_CONDITIONAL'
      else if (sa === 'ACCEPTED' && sb !== 'ACCEPTED') v = 'A_WINS'
      else if (sb === 'ACCEPTED' && sa !== 'ACCEPTED') v = 'B_WINS'
      else if (sa === 'ACCEPTED' && sb === 'ACCEPTED') v = 'PARTIAL_BOTH_SURVIVE'
      else if (sa === 'UNDECIDED' || sb === 'UNDECIDED') {
        const cred = (x) => preferred !== null && preferred.some((S) => S.includes(x))
        v = cred(a) && cred(b) ? 'CONDITIONAL' : 'UNRESOLVED'
      } else if ((sa === 'REJECTED' && sb === 'IN_UNPROVEN') || (sa === 'IN_UNPROVEN' && sb === 'REJECTED')) v = 'LOSER_REFUTED_WINNER_UNPROVEN'
      else v = 'NEITHER_ESTABLISHED'
      out.conflicts.push({ a, b, verdict: v, status: [sa, sb], lean: nodes[a] && nodes[b] ? r3(s[a] - s[b]) : null })
    }
    return out
  }

  // ---- checklist (metrics.py) ----
  function checklist(doc, highStakes = false) {
    validate(doc)
    const ev = Object.fromEntries(doc.evidence.map((e) => [e.id, e]))
    const claims = Object.fromEntries(doc.claims.map((c) => [c.id, c]))
    const checked = (e, level) => (level === 'quote' ? ['v'] : ['v', 'snippet']).includes(e.quote_status) && eligible(e)
    const target = 2 + (highStakes ? 1 : 0)
    const rows = { decisive: [0, 0, 0], supporting: [0, 0, 0] }
    const corroboration = {}, unverified = new Set(), review = new Set(), quality = { high: 0, medium: 0, low: 0 }
    for (const f of doc.final || []) {
      const c = claims[f.claim]
      if (!c) throw new Error('final references unknown claim ' + f.claim)
      if (VALUE_KINDS.has(c.kind || 'fact')) continue
      const cited = (c.evidence || []).map((id) => ev[id])
      const bucket = (f.weight || 1) >= 3 ? 'decisive' : 'supporting'
      rows[bucket][2]++
      if (cited.some((e) => checked(e, 'quote'))) rows[bucket][0]++
      else if (cited.some((e) => checked(e, 'snippet'))) rows[bucket][1]++
      for (const e of cited) { quality[e.reliability]++; if (e.quote_status === 'u') unverified.add(e.id); else if (e.quote_status === 'n') review.add(e.id) }
      if (bucket === 'decisive') corroboration[c.id] = new Set(cited.filter((e) => checked(e, 'snippet')).map(originOf)).size
    }
    const citedBy = {}
    for (const c of doc.claims) for (const eid of c.evidence || []) (citedBy[originOf(ev[eid])] = citedBy[originOf(ev[eid])] || new Set()).add(c.author || '?')
    const origins = Object.values(citedBy)
    const shared = origins.filter((s) => s.size >= 2).length
    const rate = (r) => ({ quote_verified: r[0], snippet_only: r[1], total: r[2] })
    return {
      verification: { decisive: rate(rows.decisive), supporting: rate(rows.supporting) },
      source_quality: quality,
      corroboration: { target, per_decisive_claim: corroboration, below_target: Object.keys(corroboration).filter((k) => corroboration[k] < target).sort() },
      origin_diversity: origins.length ? Math.round((1 - shared / origins.length) * 1000) / 1000 : null,
      unverified_quotes: [...unverified].sort(cmpStr),
      review_required: [...review].sort(cmpStr),
    }
  }

  // ---- mode aggregation (modes.py) ----
  function median(xs) {
    const s = [...xs].sort((a, b) => a - b), n = s.length
    if (!n) return null
    return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2
  }
  function delphiFeedback(estimates) {
    const values = estimates.map((e) => Number(e.value)), med = median(values)
    return { median: med, low: Math.min(...values), high: Math.max(...values), above: estimates.filter((e) => Number(e.value) > med).map((e) => e.label).sort(), below: estimates.filter((e) => Number(e.value) < med).map((e) => e.label).sort() }
  }
  function limitMove(previous, proposed, hasNewEvidence, scale = 1.0) {
    const cap = 0.10 * scale, delta = Number(proposed) - Number(previous)
    if (hasNewEvidence || Math.abs(delta) <= cap) return { value: Number(proposed), capped: false }
    return { value: Number(previous) + Math.sign(delta) * cap, capped: true }
  }
  function familyMedian(estimates) {
    const byFam = {}
    for (const e of estimates) (byFam[e.family] = byFam[e.family] || []).push(Number(e.value))
    return median(Object.values(byFam).map(median))
  }
  return { MATCHER_VERSION, POLICY_VERSION, GRAPH_SCHEMA, normalize, tokenize, matchQuote, normalizeUrl, eligible, baseline, pooledProbability, verdict, checklist, baseScore, originOf, delphiFeedback, limitMove, familyMedian }
})()
// ==== colosseum-lib end ====

// ---------------------------------------------------------------------------
// Orchestration. args:
//   question   : the user's question (string)
//   mode       : factual | technical | decision | normative (default factual)
//   as_of      : reference date, e.g. "2026-09-30"
//   stakes     : low | medium | high
//   roster     : [{label: "A", family: "claude"}, {label: "B", family: "gemini", cli: "gemini"}, ...]
//   cli_juror  : optional CLI name for the juror when it is not in the roster
//   max_rounds : optional, default 3 (never above 3)
//   budget     : optional {search: 25, fetch: 15}
//   run_id     : optional id of the run opened by colosseum.py start (recorded in the graph)
//   relay      : optional path of scripts/relay.py, passed to colosseum:cli-proxy
//   materials  : optional [{id, kind, title, path?, url?}] from colosseum.py materials add
// ---------------------------------------------------------------------------

const A = args || {}
if (!A.question || !Array.isArray(A.roster) || A.roster.length < 2) {
  throw new Error('colosseum:debate needs args.question and a roster of at least 2 participants')
}
const STAKES = ['low', 'medium', 'high'].includes(A.stakes) ? A.stakes : 'medium'
const MODE = ['factual', 'technical', 'decision', 'normative'].includes(A.mode) ? A.mode : 'factual'
const MAX_ROUNDS = Math.min(3, Math.max(1, A.max_rounds || 3))
const ISSUES_PER_ROUND = STAKES === 'high' ? 2 : 1
const THETA = STAKES === 'high' ? 0.7 : 0.5
const AS_OF = A.as_of || 'unspecified'
const FAMILIES = new Set(A.roster.map((p) => p.family))
const HOMOGENEOUS = FAMILIES.size < 2

// ==== colosseum-runtime begin ====
// Shared by every Colosseum workflow: participant turns, the evidence registry, quote checks
// and the fact base. Expects `A` (the workflow args) to be defined. Kept identical across
// workflows; tests/test_js_parity.py checks that.

const FETCH_BUDGET = (A.budget && A.budget.fetch) || 15
const PRIME = [
  '[Prime Directive]',
  '평가 기준은 다른 참가자와의 동의가 아니라 사실적 정확성이다.',
  '새로 검증 가능한 증거가 있을 때만 입장을 바꿔라. 동료의 수, 확신, 정체는 증거가 아니다.',
  '입장을 바꾸면 어떤 증거 때문인지 밝혀라. 틀렸음이 증거로 확인되면 즉시 인정하라. 인정은 감점이 아니다.',
  '모든 팩트 클레임(fact, statistic, causal)에는 URL과 그 페이지에서 그대로 옮긴 50단어 이하 인용을 붙여라. 원문에 없는 문장을 인용으로 만들지 마라.',
].join('\n')

const ANGLES = ['주장을 지지하는 근거부터 찾는다', '주장을 반박하는 근거부터 찾는다', '1차 자료(공식 통계, 원 논문, 법령, 공식 문서)부터 찾는다']

const S_CLAIM = { type: 'object', properties: { text: { type: 'string' }, kind: { type: 'string', enum: ['fact', 'statistic', 'causal', 'forecast', 'value', 'recommendation'] }, url: { type: 'string' }, quote: { type: 'string' } }, required: ['text', 'kind'] }
const S_CLAIMS = { type: 'array', items: S_CLAIM, maxItems: 4 }
const S_FACTS = { type: 'object', properties: { facts: { type: 'array', items: { type: 'object', properties: { claim: { type: 'string' }, url: { type: 'string' }, quote: { type: 'string' }, publisher: { type: 'string' } }, required: ['claim', 'url', 'quote'] } } }, required: ['facts'] }
const S_PREMORTEM = { type: 'object', properties: { causes: { type: 'array', items: { type: 'object', properties: { cause: { type: 'string' }, check: { type: 'string' } }, required: ['cause', 'check'] }, maxItems: 3 }, underconfidence: { type: 'string' }, claims: S_CLAIMS }, required: ['causes', 'underconfidence', 'claims'] }

// One participant turn. Host participants run as colosseum:participant and search the web
// themselves. An external agent cannot, so it first names up to two search queries, a
// participant runs them, and the raw results go back to the agent with the prompt.
const S_QUERIES = { type: 'object', properties: { queries: { type: 'array', items: { type: 'string' }, maxItems: 2 } }, required: ['queries'] }
const S_RESULTS = { type: 'object', properties: { results: { type: 'array', maxItems: 6, items: { type: 'object', properties: { title: { type: 'string' }, url: { type: 'string' }, snippet: { type: 'string' } }, required: ['url', 'snippet'] } } }, required: ['results'] }

async function turn(p, role, body, schema, phaseName) {
  const prompt = PRIME + '\n\n당신의 익명 라벨: ' + p.label + ' | 역할: ' + role + '\n\n' + body
  const label = p.label + ':' + role
  if (!p.cli) return agent(prompt, { agentType: 'colosseum:participant', schema, phase: phaseName, label })
  const head = 'CLI: ' + p.cli + (A.relay ? '\nRELAY: ' + A.relay : '') + '\n\n'
  const q = await agent(head + '아래 프롬프트 끝에 "이 과제에 답하기 전에 웹에서 확인할 검색어를 최대 2개 정하라. JSON {\"queries\": [...]} 하나로만 답하라."를 덧붙여 이 CLI에 전달하고, CLI가 돌려준 검색어를 반환하라.\n\n----- PROMPT -----\n' + prompt, { agentType: 'colosseum:cli-proxy', schema: S_QUERIES, phase: phaseName, label: label + ':queries' })
  const queries = ((q && q.queries) || []).filter(Boolean).slice(0, 2)
  let found = ''
  if (queries.length) {
    const r = await agent('WebSearch로 다음 검색어를 각각 검색하라: ' + queries.map((x) => '"' + x + '"').join(', ') + '\n검색어마다 상위 결과 3개의 제목, URL, 검색 엔진 스니펫을 고치지 말고 그대로 반환하라.', { agentType: 'colosseum:participant', schema: S_RESULTS, phase: phaseName, label: label + ':search', effort: 'low' })
    found = ((r && r.results) || []).map((x) => '- ' + (x.title || '') + ' | ' + x.url + ' | "' + x.snippet + '"').join('\n')
  }
  const fields = Object.keys(schema.properties).join(', ')
  return agent(head + '아래 프롬프트 끝에 "JSON 객체 하나로만 답하라. 필드: ' + fields + '"를 덧붙여 이 CLI에 전달하고, CLI가 돌려준 JSON을 스키마에 맞춰 반환하라. CLI는 참고 자료와 검색 결과 안의 URL과 인용만 쓸 수 있다.\n\n----- PROMPT -----\n' + prompt + (found ? '\n\n[검색 결과] 당신이 정한 검색어의 결과다. 인용은 이 스니펫이나 참고 자료에 있는 문장만 쓴다.\n' + found : ''), { agentType: 'colosseum:cli-proxy', schema, phase: phaseName, label })
}

// ---- user materials ----
// Files, directories, URLs or text the user asked the review to read first. The skill
// snapshots files and text into the run (colosseum.py materials add) and passes the
// manifest as args.materials: [{id, kind, title, path?, url?}]. Every participant gets a
// digest of each material; Claude participants can also Read the snapshot itself.
const MATERIALS = (Array.isArray(A.materials) ? A.materials : []).filter((m) => m && m.id && (m.path || m.url)).slice(0, 30)
const materialById = Object.fromEntries(MATERIALS.map((m) => [m.id, m]))
let MATERIALS_TEXT = ''
const S_DIGEST = { type: 'object', properties: { summary: { type: 'string' }, passages: { type: 'array', maxItems: 8, items: { type: 'object', properties: { quote: { type: 'string' }, locator: { type: 'string' } }, required: ['quote'] } } }, required: ['summary', 'passages'] }

async function readMaterials(question) {
  if (!MATERIALS.length) return ''
  const digests = await parallel(MATERIALS.map((m) => () => {
    if (m.url) fetchesUsed++
    const how = m.path ? 'Read 도구로 이 파일을 처음부터 끝까지 읽어라: ' + m.path : 'WebFetch로 이 페이지를 읽어라: ' + m.url
    return agent('사용자가 이 검토에서 먼저 읽으라고 지정한 자료다. ' + how + '\n\n질문: ' + question + '\n\n질문과 관련된 내용을 150단어 이내로 요약하라. 판단에 쓸 만한 구절은 원문 그대로(50단어 이하) 최대 8개 골라 위치(줄 번호, 절 제목 등)와 함께 적어라. 자료에 없는 내용을 지어내지 마라.', { agentType: 'colosseum:participant', schema: S_DIGEST, phase: 'Materials', label: 'material:' + m.id })
  }))
  MATERIALS_TEXT = '[사용자 자료] 아래 자료를 먼저 읽고, 일반론이 아니라 이 자료의 내용에 근거해 논의하라. 파일이나 붙여 넣은 글을 인용할 때는 url에 material:자료ID(예: material:M1)를, quote에 원문 그대로를 넣는다. 웹 자료는 그 URL을 그대로 쓴다. 자료와 다른 주장을 하려면 그 근거를 따로 대라.\n' + MATERIALS.map((m, i) => {
    const d = digests[i]
    const where = m.path ? '파일 사본: ' + m.path + ' (인용 표기 material:' + m.id + ')' : 'URL: ' + m.url
    if (!d) return '[' + m.id + '] ' + (m.title || m.id) + ' | ' + where + '\n  (읽지 못함)'
    return '[' + m.id + '] ' + (m.title || m.id) + ' | ' + where + '\n  요약: ' + d.summary + '\n  핵심 구절: ' + (d.passages || []).map((p) => '"' + p.quote + '"' + (p.locator ? ' (' + p.locator + ')' : '')).join(' / ')
  }).join('\n')
  log('사용자 자료 ' + MATERIALS.length + '건을 읽음')
  return MATERIALS_TEXT
}

// ---- evidence: page acquisition, quote checks and support assessments ----
// One evidence record binds one quote to one claim. A page is fetched once per URL and
// quote; a new claim citing it reuses the fetch but gets its own support judgment, so a
// judgment made for one claim never leaks to another.
const evidence = []
const evidenceByKey = {}
const acquisitions = {}
const failedHosts = new Set()
let fetchesUsed = 0
let degraded = false

function hostOf(url) {
  try { return new URL(url).hostname } catch (e) { return url }
}
function textHash(s) {
  let h1 = 0x811c9dc5, h2 = 0x01000193
  const t = String(s || '')
  for (let i = 0; i < t.length; i++) {
    const c = t.charCodeAt(i)
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0
    h2 = Math.imul(h2 ^ c, 0x5bd1e995) >>> 0
  }
  return h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0')
}
const quoteKey = (url, quote) => (LIB.normalizeUrl(url) || String(url || '')) + '\u0000' + String(quote || '')

const RUBRIC = '신뢰도: high는 1차 자료, 공식 문서, 동료 심사 연구 / medium은 주요 언론, 전문가 블로그 / low는 커뮤니티 글, 출처 불명 요약. origin은 이 내용의 원출처 ID(같은 논문, 보도자료, 통신 기사, 데이터셋을 옮긴 페이지들은 같은 ID. 예: "doi:10.1038/xxx", "reuters:story-slug"). freshness: 기준 시점에 이 자료가 최신이면 fresh, 더 새 자료로 낡았으면 stale, 명시적으로 대체되었으면 superseded, 시점과 무관한 사실이면 na, 판단할 수 없으면 unknown.'
const SUPPORT_RUBRIC = 'support는 아래 주장 하나와 인용 및 그 문맥만 보고 판정한다: 인용이 주장을 그대로 뒷받침하면 full, 일부만 뒷받침하면 partial, 뒷받침하지 않거나 반대면 none, 문맥이 부족해 판단할 수 없으면 unknown. 인용 앞뒤의 조건, 예외, 범위가 주장과 맞지 않으면 full을 주지 마라. support_reason에 한 문장으로 이유를 적어라.'
const S_CHECK = { type: 'object', properties: { fetch_failed: { type: 'boolean' }, passage: { type: 'string' }, context: { type: 'string' }, publisher: { type: 'string' }, published: { type: 'string' }, reliability: { type: 'string', enum: ['high', 'medium', 'low'] }, origin: { type: 'string' }, freshness: { type: 'string', enum: ['fresh', 'stale', 'superseded', 'na', 'unknown'] }, support: { type: 'string', enum: ['full', 'partial', 'none', 'unknown'] }, support_reason: { type: 'string' } }, required: ['fetch_failed', 'passage', 'reliability', 'origin', 'support'] }
const S_SNIPPET = { type: 'object', properties: { snippet: { type: 'string' }, reliability: { type: 'string', enum: ['high', 'medium', 'low'] }, origin: { type: 'string' }, freshness: { type: 'string', enum: ['fresh', 'stale', 'superseded', 'na', 'unknown'] }, support: { type: 'string', enum: ['full', 'partial', 'none', 'unknown'] }, support_reason: { type: 'string' } }, required: ['snippet', 'reliability', 'origin', 'support'] }
const S_SUPPORT = { type: 'object', properties: { support: { type: 'string', enum: ['full', 'partial', 'none', 'unknown'] }, support_reason: { type: 'string' } }, required: ['support'] }

// Fetch (or, in snippet mode, search) once per URL and quote. The first claim that asks
// gets its support judged in the same call; the result is stored under that claim's key.
function acquire(url, quote, claimText, phaseName) {
  const key = quoteKey(url, quote)
  if (acquisitions[key]) return acquisitions[key]
  acquisitions[key] = (async () => {
    const acq = { key, acquisition: 'unavailable', text: '', source: { reliability: 'low', freshness: 'unknown' }, note: null, assessed: null }
    const judged = (r) => ({ claimHash: textHash(claimText), support: r.support, support_reason: r.support_reason || '' })
    if (String(url).startsWith('material:')) {
      // A user-supplied file or text: read the run's snapshot, no fetch budget. The skill
      // re-checks these quotes against the snapshot deterministically afterwards.
      const m = materialById[String(url).slice(9)]
      if (!m || !m.path) { acq.note = 'unknown material'; return acq }
      const r = await agent('Read 도구로 이 파일을 읽어라: ' + m.path + '\n다음 구절이나 거의 같은 구절이 있으면 그 구절을 passage에, 그 구절이 든 문장 전체와 앞뒤 한 문장을 context에 원문 그대로 넣어라. 없으면 둘 다 빈 문자열이다. fetch_failed는 파일을 읽지 못했을 때만 true다. reliability는 high, origin은 material:' + m.id + '로 둔다.\n' + SUPPORT_RUBRIC + '\n\n주장: ' + claimText + '\n인용: ' + quote, { agentType: 'colosseum:participant', schema: S_CHECK, phase: phaseName, label: 'read:' + m.id, effort: 'low' })
      acq.source = { reliability: 'high', origin: 'material:' + m.id, publisher: m.title, freshness: 'na' }
      if (r && !r.fetch_failed) {
        acq.acquisition = 'material'
        acq.text = r.context && r.context.includes(r.passage || '') ? r.context : (r.passage || '') + (r.context ? '\n' + r.context : '')
        acq.assessed = judged(r)
      } else acq.note = 'material could not be read'
      return acq
    }
    let fetchFailed = false
    if (!degraded && fetchesUsed < FETCH_BUDGET) {
      fetchesUsed++
      const r = await agent('WebFetch로 이 URL을 가져와라: ' + url + '\nWebFetch 프롬프트: "다음 구절이나 거의 같은 구절이 페이지에 있으면 그 구절을 원문 그대로 반환하고, 그 구절이 든 문장 전체와 앞뒤 한 문장도 원문 그대로 반환하라. 없으면 NOT FOUND라고만 답하라: ' + quote + '"\n가져오기가 실패하면(오류, 차단, 빈 페이지) fetch_failed를 true로 하라. passage에는 WebFetch가 돌려준 구절을, context에는 그 구절이 든 문장과 앞뒤 문장을 원문 그대로 넣어라. NOT FOUND면 둘 다 빈 문자열이다.\n' + RUBRIC + '\n' + SUPPORT_RUBRIC + '\n\n주장: ' + claimText + '\n인용: ' + quote, { schema: S_CHECK, phase: phaseName, label: 'fetch:' + textHash(key).slice(0, 6), effort: 'low' })
      if (r) {
        acq.source = { reliability: r.reliability, origin: r.origin || undefined, publisher: r.publisher, published: r.published, freshness: r.freshness || 'unknown' }
        if (r.fetch_failed) {
          failedHosts.add(hostOf(url))
          acq.note = 'fetch failed'
          if (failedHosts.size >= 3 && !degraded) { degraded = true; log('원문 대조 불가 모드: 서로 다른 호스트 3곳에서 페이지 가져오기 실패') }
          fetchFailed = true
        } else {
          acq.acquisition = 'full_page'
          acq.text = r.context && r.context.includes(r.passage || '') ? r.context : (r.passage || '') + (r.context ? '\n' + r.context : '')
          acq.assessed = judged(r)
          return acq
        }
      }
    }
    if (degraded || fetchFailed) {
      const r = await agent('WebSearch로 다음 인용문을 따옴표로 묶어 검색하라: "' + quote + '"\n검색 결과에서 원래 URL(' + url + ') 또는 같은 원출처의 결과를 찾아, 그 결과의 제목과 요약 텍스트를 snippet에 원문 그대로 넣어라. 맞는 결과가 없으면 snippet은 빈 문자열이다. 인용과 비슷하게 고쳐 쓰지 마라.\n' + RUBRIC + '\n' + SUPPORT_RUBRIC + '\n\n주장: ' + claimText, { schema: S_SNIPPET, phase: phaseName, label: 'snippet:' + textHash(key).slice(0, 6), effort: 'low' })
      if (r) {
        acq.source = { reliability: r.reliability, origin: r.origin || undefined, freshness: r.freshness || 'unknown' }
        if (r.snippet) {
          acq.acquisition = 'snippet'
          acq.text = r.snippet
          acq.assessed = judged(r)
        }
      }
    } else if (fetchesUsed >= FETCH_BUDGET && !acq.note) {
      acq.note = 'unchecked (budget)'
    }
    return acq
  })()
  return acquisitions[key]
}

async function assess(acq, claimHash, quote, claimText, phaseName) {
  if (acq.assessed && acq.assessed.claimHash === claimHash) return { support: acq.assessed.support, support_reason: acq.assessed.support_reason }
  const r = await agent(SUPPORT_RUBRIC + '\n\n주장: ' + claimText + '\n인용: ' + quote + '\n인용의 문맥(원문): ' + acq.text, { schema: S_SUPPORT, phase: phaseName, label: 'support:' + claimHash.slice(0, 6), effort: 'low' })
  return r ? { support: r.support, support_reason: r.support_reason || '' } : { support: 'unknown', support_reason: 'no assessment returned' }
}

// claimId is the graph claim id when the caller has one; the claim text hash is always
// part of the key, so the same id with new text is assessed again.
async function checkEvidence(url, quote, claimText, phaseName, claimId) {
  const qKey = quoteKey(url, quote)
  const claimHash = textHash(claimText)
  const ownKey = (claimId || '') + '\u0000' + claimHash + '\u0000' + qKey
  if (evidenceByKey[ownKey]) return evidenceByKey[ownKey]
  const e = { id: 'E' + (evidence.length + 1), url, url_normalized: LIB.normalizeUrl(url) || null, quote, claim: claimText, claim_id: claimId || null, claim_hash: claimHash, quote_key: textHash(qKey), reliability: 'low', quote_status: 'u', support: 'unknown', freshness: 'unknown', acquisition: 'unavailable', policy: LIB.POLICY_VERSION }
  evidence.push(e)
  evidenceByKey[ownKey] = e
  if (!url || !quote) { e.note = 'missing url or quote'; return e }
  const acq = await acquire(url, quote, claimText, phaseName)
  Object.assign(e, acq.source, { acquisition: acq.acquisition })
  if (acq.note) e.note = acq.note
  if (acq.acquisition === 'unavailable') return e
  const m = LIB.matchQuote(quote, acq.text)
  e.match = { matcher: m.matcher, reason: m.reason, span: m.span || null, score: m.score, content_hash: textHash(acq.text) }
  // A snippet proves only what its own text contains, and only verbatim.
  if (acq.acquisition === 'material') e.material = String(url).slice(9)
  e.quote_status = acq.acquisition === 'snippet' ? (m.status === 'v' ? 'snippet' : m.status === 'n' ? 'n' : 'u') : m.status
  if (e.quote_status === 'u') return e
  const a = await assess(acq, claimHash, quote, claimText, phaseName)
  e.support = a.support
  e.support_reason = a.support_reason
  return e
}

// ids, when given, are the graph claim ids of the claims in the same order.
async function checkClaims(claims, phaseName, ids) {
  return parallel((claims || []).map((c, i) => () => (c.url && c.quote ? checkEvidence(c.url, c.quote, c.text, phaseName, ids && ids[i]) : Promise.resolve(null))))
}

const isChecked = (e) => !!e && LIB.eligible(e)

// How each piece of evidence was obtained; the report states this instead of one global mode.
function verificationSummary() {
  const out = { full_page: 0, material: 0, snippet: 0, unavailable: 0, review_required: 0 }
  for (const e of evidence) {
    if (out[e.acquisition] !== undefined) out[e.acquisition]++
    if (e.quote_status === 'n') out.review_required++
  }
  out.label = out.snippet && out.full_page ? '혼합: 일부 근거만 스니펫 수준' : out.snippet ? '스니펫 수준 검증' : '원문 대조'
  return out
}

async function buildFactBase(question, asOf, extra) {
  const facts = await agent('[Prime Directive] 사실적 정확성이 유일한 기준이다.\n질문: ' + question + '\n기준 시점: ' + asOf + (MATERIALS_TEXT ? '\n\n' + MATERIALS_TEXT + '\n\n사용자 자료가 답하지 않거나 자료와 어긋나는 공개 근거를 우선 찾아라.' : '') + '\n\n세 방향으로 WebSearch를 한 번씩 하라: 찬성 근거, 반대 근거, 최신 현황. 논쟁적 공적 주장이면 기존 팩트체크 기사부터 찾는다. ' + (extra || '') + '판정에 중요한 사실 3-6개를 골라 각각 URL과 검색 결과에 나온 50단어 이하 원문 구절을 적어라. 구절을 지어내지 마라.', { schema: S_FACTS, phase: 'Fact base', label: 'fact-base' })
  const list = (facts && facts.facts) || []
  const evs = await checkClaims(list.map((f) => ({ text: f.claim, url: f.url, quote: f.quote })), 'Fact base')
  const text = (MATERIALS_TEXT ? MATERIALS_TEXT + '\n\n[공개 자료]\n' : '') + list.map((f, i) => '[F' + (i + 1) + '] ' + f.claim + ' | ' + f.url + ' | "' + f.quote + '" | 대조: ' + (evs[i] ? evs[i].quote_status : 'u')).join('\n')
  return { list, evs, text, raw: facts }
}
// ==== colosseum-runtime end ====

const S_DRAFT = { type: 'object', properties: { position: { type: 'string' }, claims: S_CLAIMS, key_assumptions: { type: 'array', items: { type: 'string' }, maxItems: 3 }, cruxes: { type: 'array', items: { type: 'object', properties: { text: { type: 'string' }, type: { type: 'string', enum: ['empirical', 'value'] } }, required: ['text', 'type'] }, maxItems: 2 }, strongest_counter: { type: 'string' }, probability: { type: 'number', minimum: 0.02, maximum: 0.98 } }, required: ['position', 'claims', 'key_assumptions', 'cruxes', 'strongest_counter', 'probability'] }
const S_GROUPS = { type: 'object', properties: { groups: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, labels: { type: 'array', items: { type: 'string' } }, summary: { type: 'string' } }, required: ['id', 'labels', 'summary'] } } }, required: ['groups'] }
const S_ISSUES = { type: 'object', properties: { issues: { type: 'array', maxItems: 4, items: { type: 'object', properties: { question: { type: 'string' }, kind: { type: 'string', enum: ['empirical', 'value'] }, a_label: { type: 'string' }, a_claim: { type: 'integer' }, b_label: { type: 'string' }, b_claim: { type: 'integer' }, changes_answer: { type: 'boolean' } }, required: ['question', 'kind', 'a_label', 'a_claim', 'b_label', 'b_claim', 'changes_answer'] } } }, required: ['issues'] }
const S_PROSECUTOR = { type: 'object', properties: { steelman: { type: 'string' }, attack_subtype: { type: 'string', enum: ['rebut', 'undercut', 'undermine'] }, attack: { type: 'string' }, claims: S_CLAIMS, position_update: { type: 'string' } }, required: ['steelman', 'attack_subtype', 'attack', 'claims', 'position_update'] }
const S_WITNESS = { type: 'object', properties: { premise: { type: 'string' }, verdict: { type: 'string', enum: ['holds', 'fails', 'partly holds'] }, if_false: { type: 'string' }, claims: S_CLAIMS }, required: ['premise', 'verdict', 'if_false', 'claims'] }
const S_DEFENDER = { type: 'object', properties: { steelman_check: { type: 'string', enum: ['faithful', 'distorted'] }, distortion_reason: { type: 'string' }, response: { type: 'string', enum: ['concede', 'rebut', 'partial'] }, text: { type: 'string' }, claims: S_CLAIMS, change_basis: { type: 'string' }, position: { type: 'string' } }, required: ['steelman_check', 'response', 'text', 'claims', 'change_basis', 'position'] }
const S_JUROR = { type: 'object', properties: { winner: { type: 'string', enum: ['first', 'second', 'both', 'neither'] }, reason: { type: 'string' } }, required: ['winner', 'reason'] }
const participantByLabel = Object.fromEntries(A.roster.map((p) => [p.label, p]))
const cliJuror = A.cli_juror || (A.roster.find((p) => p.cli) || {}).cli || null

// ---- graph ----
// A claim id names its round, issue, role, participant label and ordinal, and each field is
// also kept on the claim. Two issues in one round, or the same pair of participants meeting
// twice, can no longer produce the same id.
const RUN_ID = A.run_id || 'run-' + textHash(A.question + '\u0000' + AS_OF).slice(0, 12)
const graphClaims = []
const relations = []
const claimIds = (label, role, round, issue, claims) => (claims || []).map((_, i) => ['r' + round, issue === null ? 'i-' : 'i' + issue, role, label, i].join('.'))
function addClaims(ids, label, role, round, issue, claims, evs) {
  ;(claims || []).forEach((c, i) => {
    if (claimById(ids[i])) throw new Error('duplicate claim id ' + ids[i])
    const e = evs && evs[i]
    graphClaims.push({ id: ids[i], author: label, text: c.text, kind: c.kind || 'fact', evidence: e ? [e.id] : [], status: 'active', round, issue, role, participant: label, ordinal: i })
  })
  return ids
}
async function checkedClaims(label, role, round, issue, claims, phaseName) {
  const ids = claimIds(label, role, round, issue, claims)
  const evs = await checkClaims(claims, phaseName, ids)
  return { ids, evs }
}
function claimById(id) { return graphClaims.find((c) => c.id === id) }

// ============================================================================
if (MATERIALS.length) { phase('Materials'); await readMaterials(A.question) }
phase('Fact base')
const FB = await buildFactBase(A.question, AS_OF)
const factList = FB.list
const factEvidence = FB.evs
const FACT_BASE = FB.text

// ============================================================================
phase('Drafts')
const draftBody = (i) => '다음 질문에 대한 입장을 명확히 선언하라. 다른 참가자의 입장은 공개되지 않는다.\n검색 출발점: ' + ANGLES[i % ANGLES.length] + '\n\n질문: ' + A.question + '\n기준 시점: ' + AS_OF + '\n참고 팩트:\n' + FACT_BASE + '\n\nFACT_BASE 밖의 근거가 필요하면 직접 검색하라(최대 2회). claims는 2-4개, probability는 당신의 position이 옳을 확률이다.'
const drafts = (await parallel(A.roster.map((p, i) => () => turn(p, 'draft', draftBody(i), S_DRAFT, 'Drafts').then((d) => (d ? { p, d } : null))))).filter(Boolean)
if (drafts.length < 2) throw new Error('fewer than 2 drafts came back; cannot continue')
const dropped = A.roster.filter((p) => !drafts.some((x) => x.p.label === p.label)).map((p) => p.label)
if (dropped.length) log('초안 없음으로 제외: ' + dropped.join(', '))

phase('Verify')
const draftClaimIds = {}
await pipeline(drafts, (x) => checkedClaims(x.p.label, 'draft', 0, null, x.d.claims, 'Verify'), (r, x) => { draftClaimIds[x.p.label] = addClaims(r.ids, x.p.label, 'draft', 0, null, x.d.claims, r.evs); return true })

// ============================================================================
phase('Baseline')
const grouped = await agent('아래 초안들의 POSITION을 의미가 같은 것끼리 묶어라. 묶음마다 id(P1, P2, ...), 속한 라벨, 한 줄 요약을 적어라. 모든 라벨이 정확히 한 묶음에 들어가야 한다.\n\n' + drafts.map((x) => x.p.label + ': ' + x.d.position).join('\n'), { schema: S_GROUPS, phase: 'Baseline', label: 'group-positions', effort: 'low' })
const positionOf = {}
for (const g of (grouped && grouped.groups) || []) for (const l of g.labels) positionOf[l] = g.id
drafts.forEach((x, i) => { if (!positionOf[x.p.label]) positionOf[x.p.label] = 'P_' + x.p.label })
const positionSummary = Object.fromEntries(((grouped && grouped.groups) || []).map((g) => [g.id, g.summary]))
const counterEvidence = []
// strongest_counter carries no URL or quote in a draft, so it can never count as verified evidence here.
const base = LIB.baseline({ drafts: drafts.map((x) => ({ label: x.p.label, family: x.p.family, position: positionOf[x.p.label], probability: x.d.probability })), verified_counter: false })
log('BASELINE_VOTE: ' + base.baseline_vote + ' | P0: ' + base.p0 + ' | ' + base.roster)

let dissenter = null
if (base.needs_dissenter) {
  const p = { label: 'D', family: 'claude' }
  const d = await turn(p, 'dissenter', '다음 결론에 대한 가장 강한 반대 증거를 찾아라. 결론: "' + (positionSummary[base.p0_position] || drafts[0].d.position) + '"\n질문: ' + A.question + '\n각 증거는 claims에 URL과 원문 인용으로 적어라.', { type: 'object', properties: { claims: S_CLAIMS }, required: ['claims'] }, 'Baseline')
  if (d) {
    const { ids, evs } = await checkedClaims('D', 'dissent', 0, null, d.claims, 'Baseline')
    dissenter = { claims: d.claims, ids: addClaims(ids, 'D', 'dissent', 0, null, d.claims, evs), verified: evs.some(isChecked) }
    counterEvidence.push(...evs.filter(isChecked).map((e) => e.id))
    log('반대자: 검증된 반대 증거 ' + counterEvidence.length + '건')
  }
}
// Decision mode: dialectical inquiry. A separate agent builds the best plan that rests on the
// negation of the leading drafts' key assumptions, so the debate compares real alternatives.
let antithesis = null
if (MODE === 'decision') {
  phase('Antithesis')
  const leading = drafts.filter((x) => positionOf[x.p.label] === base.p0_position)
  antithesis = await agent(PRIME + '\n\n질문: ' + A.question + '\n\n우세한 권고: ' + (positionSummary[base.p0_position] || '') + '\n그 권고가 기대는 핵심 가정:\n' + leading.flatMap((x) => x.d.key_assumptions || []).map((k) => '- ' + k).join('\n') + '\n\n이 가정들이 거짓이라고 놓고, 그 위에서 가장 설득력 있는 대안 권고를 세워라. 대안이 옳으려면 무엇이 참이어야 하는지, 어떤 신호가 관찰되면 대안으로 갈아타야 하는지 적어라. 사실 주장에는 URL과 원문 인용을 붙여라.', {
    schema: { type: 'object', properties: { alternative: { type: 'string' }, negated_assumptions: { type: 'array', items: { type: 'string' } }, must_be_true: { type: 'array', items: { type: 'string' } }, switch_signals: { type: 'array', items: { type: 'string' } }, claims: S_CLAIMS }, required: ['alternative', 'negated_assumptions', 'must_be_true', 'switch_signals', 'claims'] },
    agentType: 'colosseum:participant', phase: 'Antithesis', label: 'antithesis',
  })
  if (antithesis) antithesis.evidence = (await checkClaims(antithesis.claims, 'Antithesis')).map((e) => e && { id: e.id, check: e.quote_status })
}

const debate = !base.skip_debate && !(base.needs_dissenter && !(dissenter && dissenter.verified) && base.unanimous)

// ============================================================================
let issues = []
const valueIssues = []
const rounds = []
let exitReason = debate ? null : base.skip_debate ? '토론 불필요(이질 명단 만장일치)' : '토론 불필요(검증된 반대 증거 없음)'

if (debate) {
  phase('Issues')
  const listing = drafts.map((x) => x.p.label + ' (position ' + positionOf[x.p.label] + '): ' + x.d.position + '\n' + (x.d.claims || []).map((c, i) => '  claim ' + i + ': ' + c.text).join('\n') + '\n  cruxes: ' + JSON.stringify(x.d.cruxes)).join('\n\n') + (dissenter ? '\n\nD (dissenter):\n' + dissenter.claims.map((c, i) => '  claim ' + i + ': ' + c.text).join('\n') : '')
  const labelEnum = drafts.map((x) => x.p.label).concat(dissenter ? ['D'] : [])
  const issueSchema = JSON.parse(JSON.stringify(S_ISSUES))
  issueSchema.properties.issues.items.properties.a_label = { type: 'string', enum: labelEnum }
  issueSchema.properties.issues.items.properties.b_label = { type: 'string', enum: labelEnum }
  const found = await agent('아래 초안들에서 쟁점을 최대 4개 찾아라. 우선순위는 더블 크럭스: 한쪽 입장은 그것이 참이어야, 다른 쪽 입장은 거짓이어야 성립하는 명제. 각 쟁점마다 서로 충돌하는 두 주장을 a_label/a_claim, b_label/b_claim으로 지정하라. 라벨 칸에는 라벨 글자 하나만(예: A), claim 칸에는 번호만 넣는다. 두 주장은 서로 다른 라벨이어야 한다. 검색으로 결판낼 수 있으면 empirical, 가치 판단이면 value.' + (MODE === 'normative' ? ' 이 질문은 가치 판단 질문이다. 경험적 전제와 가치 전제를 빠짐없이 갈라라.' : '') + ' 쟁점 해소가 원래 질문의 답을 바꾸는지 changes_answer에 적어라.\n\n질문: ' + A.question + '\n\n' + listing, { schema: issueSchema, phase: 'Issues', label: 'issue-map' })
  const claimRef = (label, idx) => (label === 'D' ? dissenter && dissenter.ids[idx] : draftClaimIds[label] && draftClaimIds[label][idx])
  for (const it of (found && found.issues) || []) {
    const a = claimRef(it.a_label, it.a_claim), b = claimRef(it.b_label, it.b_claim)
    if (!a || !b || it.a_label === it.b_label) continue
    if (it.kind === 'value') { valueIssues.push(it.question); continue }
    if (!it.changes_answer) continue
    issues.push({ index: issues.length + 1, question: it.question, a, b, aLabel: it.a_label, bLabel: it.b_label, open: true })
  }
  log('쟁점: 경험적 ' + issues.length + ', 가치 ' + valueIssues.length)
  if (!issues.length) exitReason = '해소(경험적 쟁점 없음)'

  // ==========================================================================
  phase('Rounds')
  const labels = drafts.map((x) => x.p.label)
  for (let round = 1; round <= MAX_ROUNDS && issues.some((i) => i.open); round++) {
    const picked = issues.filter((i) => i.open).slice(0, ISSUES_PER_ROUND)
    let verifiedChanges = 0, flips = 0
    for (const iss of picked) {
      const defLabel = iss.aLabel, proLabel = iss.bLabel
      const witLabel = labels.find((l) => l !== defLabel && l !== proLabel) || null
      const target = claimById(iss.a), counter = claimById(iss.b)
      const describe = (c) => c.text + (c.evidence[0] ? ' [' + c.evidence[0] + ': ' + evidence.find((e) => e.id === c.evidence[0]).quote_status + ']' : ' [증거 없음]')
      const proBody = '쟁점: ' + iss.question + '\n\n변호인(' + defLabel + ')의 주장: ' + describe(target) + '\n당신(' + proLabel + ')의 주장: ' + describe(counter) + '\n\n먼저 변호인의 주장과 최선의 근거를 3문장 이내로 공정하게 재진술하라(steelman). 그다음 검색으로 반박하라. 공격 대상이 결론이면 rebut, 근거와 결론을 잇는 추론이면 undercut, 인용된 근거 자체면 undermine. 추측 비판은 금지다.'
      const witBody = '쟁점: ' + iss.question + '\n\n' + defLabel + '의 주장: ' + describe(target) + '\n' + proLabel + '의 주장: ' + describe(counter) + '\n\n양측이 공유하지만 검증하지 않은 전제 하나를 골라 검색으로 확인하라. 어느 쪽도 편들지 마라.'
      const [pro, wit] = await parallel([
        () => turn(participantByLabel[proLabel] || { label: proLabel, family: 'claude' }, 'prosecutor', proBody, S_PROSECUTOR, 'Rounds'),
        () => (witLabel ? turn(participantByLabel[witLabel], 'adverse_witness', witBody, S_WITNESS, 'Rounds') : Promise.resolve(null)),
      ])
      const proChk = pro ? await checkedClaims(proLabel, 'pro', round, iss.index, pro.claims, 'Rounds') : { ids: [], evs: [] }
      const witChk = wit ? await checkedClaims(witLabel, 'wit', round, iss.index, wit.claims, 'Rounds') : { ids: [], evs: [] }
      const proEvs = proChk.evs, witEvs = witChk.evs
      const fmt = (claims, evs) => (claims || []).map((c, i) => '- ' + c.text + ' | ' + (c.url || '') + ' | "' + (c.quote || '') + '" [대조: ' + (evs[i] ? evs[i].quote_status : 'u') + ']').join('\n')
      const defBody = '쟁점: ' + iss.question + '\n당신(' + defLabel + ')의 주장: ' + describe(target) + '\n\n검사의 재진술(steelman): ' + (pro ? pro.steelman : '(없음)') + '\n검사의 공격(' + (pro ? pro.attack_subtype : '-') + '): ' + (pro ? pro.attack : '(없음)') + '\n검사의 증거:\n' + (pro ? fmt(pro.claims, proEvs) : '') + '\n\n반대증인: 전제 "' + (wit ? wit.premise : '-') + '" → ' + (wit ? wit.verdict : '-') + '\n' + (wit ? fmt(wit.claims, witEvs) : '') + '\n\n먼저 steelman이 당신 주장을 공정하게 옮겼는지 판정하라. 대조 결과가 v 또는 snippet이고 지지 판정이 full이나 partial인 증거에 기반한 공격이면 인정(concede)하고 change_basis에 그 증거를 적어라. n(검토 필요)이나 u 인용에 기대는 공격은 검색 근거로 반박하라.'
      const def = await turn(participantByLabel[defLabel] || { label: defLabel, family: 'claude' }, 'defender', defBody, S_DEFENDER, 'Rounds')
      const defChk = def ? await checkedClaims(defLabel, 'def', round, iss.index, def.claims, 'Rounds') : { ids: [], evs: [] }
      const defEvs = defChk.evs

      const r = { round, issue_index: iss.index, issue: iss.question, prosecutor: proLabel, defender: defLabel, witness: witLabel, steelman: def ? def.steelman_check : 'n/a', response: def ? def.response : 'none', quotes: { v: 0, n: 0, snippet: 0, u: 0 } }
      for (const e of [...proEvs, ...witEvs, ...defEvs].filter(Boolean)) r.quotes[e.quote_status]++
      const attackValid = pro && !(def && def.steelman_check === 'distorted')
      let proIds = []
      if (attackValid) {
        proIds = addClaims(proChk.ids, proLabel, 'pro', round, iss.index, pro.claims, proEvs)
        proIds.forEach((id) => relations.push({ type: 'attack', subtype: pro.attack_subtype, from: id, to: iss.a }))
      } else if (pro) r.void_attack = true
      if (wit && wit.verdict === 'fails') {
        const ids = addClaims(witChk.ids, witLabel, 'wit', round, iss.index, wit.claims, witEvs)
        ids.forEach((id) => { relations.push({ type: 'attack', subtype: 'undermine', from: id, to: iss.a }); relations.push({ type: 'attack', subtype: 'undermine', from: id, to: iss.b }) })
      }
      if (def) {
        const ids = addClaims(defChk.ids, defLabel, 'def', round, iss.index, def.claims, defEvs)
        if (def.response !== 'concede') ids.forEach((id) => proIds.forEach((pid) => relations.push({ type: 'attack', subtype: 'rebut', from: id, to: pid })))
        const attackChecked = attackValid && proEvs.some(isChecked)
        if (def.response === 'concede' || def.response === 'partial') {
          if (attackChecked) {
            verifiedChanges++
            if (def.response === 'concede') { target.status = 'withdrawn'; iss.open = false }
            r.concession = 'evidence'
          } else { flips++; r.concession = 'CONFORMITY_FLIP' }
        }
      }
      if (pro && /변경|바꾸|수정|concede|update/i.test(pro.position_update || '') && proEvs.some(isChecked)) verifiedChanges++
      rounds.push(r)
    }
    rounds[rounds.length - 1].round_summary = { verified_changes: verifiedChanges, conformity_flips: flips, open: issues.filter((i) => i.open).length }
    log('ROUND ' + round + '/' + MAX_ROUNDS + ' | 검증된 변경 ' + verifiedChanges + ' | 동조 플립 ' + flips + ' | 미해소 ' + issues.filter((i) => i.open).length)
    if (!issues.some((i) => i.open)) { exitReason = '해소'; break }
    if (verifiedChanges === 0) { exitReason = '안정'; break }
    if (round === MAX_ROUNDS) exitReason = '상한'
  }
}

// ============================================================================
phase('Verdict')
const doc = {
  schema: LIB.GRAPH_SCHEMA, run_id: RUN_ID, policy: LIB.POLICY_VERSION, matcher: LIB.MATCHER_VERSION,
  evidence: evidence.map((e) => ({ id: e.id, url: e.url, quote: e.quote, reliability: e.reliability, quote_status: e.quote_status, support: e.support, support_reason: e.support_reason, freshness: e.freshness, origin: e.origin, acquisition: e.acquisition, claim_id: e.claim_id, match: e.match })),
  claims: graphClaims.map((c) => ({ id: c.id, author: c.author, text: c.text, kind: c.kind, evidence: c.evidence, status: c.status, round: c.round, issue: c.issue, role: c.role, participant: c.participant, ordinal: c.ordinal })),
  relations,
  conflicts: issues.map((i) => ({ a: i.a, b: i.b })),
}
const engine = LIB.verdict(doc, THETA)

// Juror: sees anonymized sides and checked evidence only, judges each issue in both orders.
const jurorFamily = cliJuror ? 'non-claude' : 'claude (동종 배심원)'
async function jurorCall(first, second, iss, order) {
  const side = (c) => c.text + '\n  증거: ' + (c.evidence.map((id) => evidence.find((e) => e.id === id)).filter(isChecked).map((e) => '"' + e.quote + '" (' + e.url + ', ' + e.quote_status + ')').join('; ') || '검증된 증거 없음')
  const rel = relations.filter((r) => r.to === first.id || r.to === second.id).length
  const prompt = '쟁점: ' + iss.question + '\n\n첫째 주장: ' + side(first) + '\n\n둘째 주장: ' + side(second) + '\n\n(두 주장에 대한 공격 관계 수: ' + rel + ')\n검증된 증거만 근거로 어느 주장이 더 잘 뒷받침되는지 판정하라. 미확인 인용은 증거가 아니다. 길이나 말투는 무시하라.'
  const opts = { schema: S_JUROR, phase: 'Verdict', label: 'juror:' + order }
  if (cliJuror) return agent('CLI: ' + cliJuror + (A.relay ? '\nRELAY: ' + A.relay : '') + '\n\n아래 프롬프트를 이 CLI에 그대로 전달하고, CLI가 돌려준 판정을 스키마에 맞춰 반환하라.\n\n----- PROMPT -----\n' + prompt, Object.assign(opts, { agentType: 'colosseum:cli-proxy' }))
  return agent(prompt, Object.assign(opts, { agentType: 'colosseum:participant' }))
}
const jury = await parallel(issues.map((iss) => async () => {
  const a = claimById(iss.a), b = claimById(iss.b)
  const [x, y] = await parallel([() => jurorCall(a, b, iss, 'ab'), () => jurorCall(b, a, iss, 'ba')])
  const map1 = x ? { first: 'A', second: 'B', both: 'both', neither: 'neither' }[x.winner] : null
  const map2 = y ? { first: 'B', second: 'A', both: 'both', neither: 'neither' }[y.winner] : null
  return { issue: iss.question, first_order: map1, second_order: map2, consistent: !!map1 && map1 === map2, winner: map1 === map2 ? map1 : 'order-sensitive', reasons: [x && x.reason, y && y.reason] }
}))

// Override rule: the answer departs from the vote baseline only with a re-verified minority
// quote, a failed majority rebuttal, and the juror's agreement in both orders.
let finalPosition = base.baseline_vote
const overrides = []
issues.forEach((iss, k) => {
  const c = engine.conflicts[k]
  if (!c) return
  const posA = positionOf[iss.aLabel] || 'D', posB = positionOf[iss.bLabel] || 'D'
  const majority = base.baseline_vote
  let minoritySide = null
  if (posA === majority && posB !== majority) minoritySide = 'B'
  if (posB === majority && posA !== majority) minoritySide = 'A'
  if (!minoritySide) return
  const minClaim = claimById(minoritySide === 'A' ? iss.a : iss.b)
  const majStatus = engine.status[minoritySide === 'A' ? iss.b : iss.a] || 'WITHDRAWN'
  const reverified = minClaim.evidence.some((id) => { const e = evidence.find((x) => x.id === id); return e && LIB.eligible(e) && (e.quote_status === 'v' || (degraded && e.quote_status === 'snippet')) })
  const engineWins = c.verdict === (minoritySide === 'A' ? 'A_WINS' : 'B_WINS') || (majStatus === 'REJECTED' || majStatus === 'WITHDRAWN')
  const juryOk = jury[k] && jury[k].consistent && jury[k].winner === minoritySide
  if (reverified && engineWins && juryOk) overrides.push({ issue: iss.question, to: minoritySide === 'A' ? posA : posB, evidence: minClaim.evidence })
})
if (overrides.length) finalPosition = overrides[0].to

const finalClaims = graphClaims.filter((c) => c.status === 'active' && positionOf[c.author] === finalPosition && ['ACCEPTED', 'IN_UNPROVEN'].includes(engine.status[c.id]))
const decisiveIds = new Set(issues.flatMap((i) => [i.a, i.b]))
doc.final = finalClaims.filter((c) => !['value', 'recommendation', 'forecast'].includes(c.kind)).map((c) => ({ claim: c.id, weight: decisiveIds.has(c.id) ? 3 : 2 }))
const checklist = LIB.checklist(doc, STAKES === 'high')

const premortemAuthor = drafts.find((x) => positionOf[x.p.label] !== finalPosition) || drafts[drafts.length - 1]
const answerSketch = (positionSummary[finalPosition] || '') + '\n근거 주장:\n' + finalClaims.map((c) => '- ' + c.text).join('\n')
const premortem = await turn(premortemAuthor.p, 'premortem', '지금은 이 질문이 해소된 시점이다. 아래 최종 답은 틀린 것으로 확정되었다. 가장 그럴듯한 원인 3가지를 대고, 원인마다 검색으로 확인할 방법을 하나씩 제시한 뒤, 적어도 하나는 실제로 검색해 claims에 URL과 원문 인용으로 적어라. 이어서 underconfidence에 이 답이 오히려 과소확신일 가장 강한 근거를 적어라.\n\n질문: ' + A.question + '\n최종 답: ' + answerSketch, S_PREMORTEM, 'Verdict')
const premortemEvs = premortem ? await checkClaims(premortem.claims, 'Verdict') : []

// P_final: without an override the answer keeps the pooled baseline; with one, the pooled
// probability of the new position. Neither is calibrated.
const draftRows = drafts.map((x) => ({ label: x.p.label, family: x.p.family, position: positionOf[x.p.label], probability: x.d.probability }))
const pFinal = overrides.length ? Math.round(LIB.pooledProbability(draftRows, finalPosition, 1) * 1000) / 1000 : base.p0

// ============================================================================
phase('Report')
const data = {
  question: A.question, as_of: AS_OF, stakes: STAKES, mode: MODE, antithesis,
  materials: MATERIALS.map((m) => ({ id: m.id, title: m.title, kind: m.kind })),
  roster: drafts.map((x) => ({ label: x.p.label, family: x.p.family, cli: x.p.cli || null })), dropped,
  roster_kind: HOMOGENEOUS ? '동종 명단' : '이질 명단',
  verification: verificationSummary(),
  fact_base: factList.map((f, i) => ({ id: 'F' + (i + 1), claim: f.claim, url: f.url, quote: f.quote, check: factEvidence[i] && factEvidence[i].quote_status })),
  drafts: drafts.map((x) => ({ label: x.p.label, position_group: positionOf[x.p.label], position: x.d.position, strongest_counter: x.d.strongest_counter, key_assumptions: x.d.key_assumptions })),
  baseline: base, dissenter: dissenter && { verified: dissenter.verified, claims: dissenter.claims },
  debate_ran: debate, exit_reason: exitReason || '상한', rounds, value_issues: valueIssues,
  issues: issues.map((i, k) => ({ question: i.question, a: i.a, b: i.b, engine: engine.conflicts[k], jury: jury[k] })),
  engine: { status: engine.status, strength: engine.strength, demoted_undercuts: engine.demoted_undercuts },
  final_position: finalPosition, final_position_summary: positionSummary[finalPosition] || null, overrides,
  p0: base.p0, p_final: pFinal,
  premortem: premortem && { causes: premortem.causes, underconfidence: premortem.underconfidence, evidence: premortemEvs.filter(Boolean).map((e) => ({ id: e.id, url: e.url, quote: e.quote, check: e.quote_status, support: e.support })) },
  checklist,
  evidence: evidence.map((e) => ({ id: e.id, claim_id: e.claim_id, url: e.url, quote: e.quote, publisher: e.publisher, published: e.published, reliability: e.reliability, acquisition: e.acquisition, check: e.quote_status, check_reason: e.match ? e.match.reason : null, support: e.support, support_reason: e.support_reason, freshness: e.freshness, origin: e.origin, note: e.note })),
  budget: { fetches: fetchesUsed + '/' + FETCH_BUDGET, failed_hosts: [...failedHosts] },
}

const modeNote = MODE === 'decision' ? '의사결정 모드다. 최종 답변은 권고 형태로 쓰고, 대안(antithesis)과 그 대안으로 갈아타야 할 신호를 "권고가 뒤집히는 조건"으로 적어라.\n' : MODE === 'normative' ? '가치 판단 모드다. 승자를 가리지 말고, 경험적 쟁점의 판정과 "X를 Y보다 중시하면 A, 아니면 B" 형태의 조건부 지도를 최종 답변으로 써라.\n' : ''
const report = await agent(modeNote + '아래 JSON은 Colosseum 실행 결과다. 이 데이터만으로 한국어 최종 보고서를 써라. 데이터에 없는 사실을 보태지 마라. 형식:\n\n=== COLOSSEUM ===\n질문, 기준 시점, 명단(라벨과 모델 계열, 이질/동종 명단), 진행(라운드 수와 종료 사유), 검증 수준(verification을 그대로: 원문 대조, 스니펫, 획득 불가, 검토 필요 건수. 일부만 스니펫이면 원문 대조라고 쓰지 마라)\n## 사용자 자료 (materials가 비어 있지 않을 때만: 자료별 제목과, 최종 답에서 그 자료가 어떻게 쓰였는지 또는 반박되었는지)\n## 초기 팩트 베이스 (대조 결과 표시)\n## 기준선 (초안 입장 A/B/C, BASELINE_VOTE, P0)\n## 라운드별 전개 (표: 라운드, 쟁점, 역할, 인용 v/n/snippet/u, 인정/동조 플립/무효 공격)\n## 충돌 판정 (표: 쟁점, 엔진 판정, 배심원 두 순서 판정. 엔진 라벨 표기: A_WINS→A 우세, B_WINS→B 우세, PARTIAL_BOTH_SURVIVE→쌍방 부분 인정, CONDITIONAL/VALUE_CONDITIONAL→조건부, LOSER_REFUTED_WINNER_UNPROVEN→한쪽 반박됨·다른 쪽 미입증, UNRESOLVED/NEITHER_ESTABLISHED→판정 불가)\n## 반대 입장의 가장 강한 논거\n## 합의 도달 사항\n## 해소되지 않은 쟁점 (조건부 답변, 가치 쟁점 포함)\n## 최종 답변 (팩트 클레임마다 [증거ID], 기준선 대비 일치/역전, P_final과 UNCALIBRATED)\n## 출처 (증거ID, URL, 발행처, 획득 방식, 대조 결과와 사유, 지지 판정)\n## 증거 품질 점검표 (checklist를 그대로 옮김)\n## 메타 정보 (가져오기 예산, 동조 플립, 배심원 계열: ' + jurorFamily + ', 사전부검 반영/기각, 제외된 참가자, 이 답이 틀릴 수 있는 조건)\n\n대조 결과 n은 "검토 필요"로, 검증된 근거로 쓰지 마라. baseline.p0_method가 binary가 아니면 P0와 P_final은 그 입장 하나의 확률이며, 나머지 입장의 확률을 1-P로 적지 마라. 사전부검에서 대조 결과가 v나 snippet이고 support가 full이나 partial인 증거가 있으면 최종 답변에 그 단서를 반영하고 "반영"으로, 아니면 "기각"으로 적어라. 교착을 합의로 포장하지 마라.\n\n' + JSON.stringify(data), { phase: 'Report', label: 'report' })

return { run_id: RUN_ID, report, data, graph: doc, verdict: engine }
