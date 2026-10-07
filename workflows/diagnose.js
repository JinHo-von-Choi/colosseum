export const meta = {
  name: 'diagnose',
  description: 'Colosseum diagnostic mode (experimental): competing hypotheses, evidence diagnosticity matrix, pooled probabilities',
  whenToUse: 'Launched by the colosseum skill for "why did X happen" questions; not for direct use',
  phases: [
    { title: 'Materials', detail: 'read the materials the user supplied' },
    { title: 'Fact base', detail: 'opposing-angle searches and source records' },
    { title: 'Hypotheses', detail: 'blind hypotheses with evidence' },
    { title: 'Verify', detail: 'quote checks against fetched pages' },
    { title: 'Matrix', detail: 'consistency of each piece of evidence with each hypothesis' },
    { title: 'Probabilities', detail: 'blind probability distributions, pooled' },
    { title: 'Premortem', detail: 'assume the leading hypothesis is wrong' },
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
  function borda(ballots) {
    const k = ballots.reduce((m, b) => Math.max(m, b.length), 0)
    const points = {}, voters = {}
    for (const ballot of ballots) {
      const seen = new Set()
      ballot.forEach((idea, rank) => {
        if (seen.has(idea)) return
        seen.add(idea)
        points[idea] = (points[idea] || 0) + (k - rank)
        voters[idea] = (voters[idea] || 0) + 1
      })
    }
    return Object.keys(points).sort((a, b) => points[b] - points[a] || voters[b] - voters[a] || (a < b ? -1 : a > b ? 1 : 0)).map((id) => ({ id, points: points[id], voters: voters[id] }))
  }
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
  const ACH_WEIGHT = { v: 1.0, n: 0.0, snippet: 0.5, u: 0.0 }
  function ach(hypotheses, rows) {
    const kept = [], dropped = []
    for (const r of rows) {
      const ratings = hypotheses.map((h) => r.ratings[h] || 'N')
      ;(new Set(ratings).size === 1 ? dropped : kept).push(r)
    }
    const inconsistency = {}, weak = {}
    for (const h of hypotheses) {
      let s = 0, w = 0
      for (const r of kept) {
        if (r.ratings[h] === 'I') {
          s += ACH_WEIGHT[r.quote_status] * RELIABILITY[r.reliability]
          if (r.quote_status === 'snippet' || r.quote_status === 'n' || r.quote_status === 'u' || r.reliability === 'low') w++
        }
      }
      inconsistency[h] = Math.round(s * 1000) / 1000
      weak[h] = w
    }
    const order = [...hypotheses].sort((a, b) => inconsistency[a] - inconsistency[b] || (a < b ? -1 : 1))
    return { diagnostic: kept.map((r) => r.id), dropped: dropped.map((r) => r.id), inconsistency, weak_inconsistencies: weak, least_inconsistent: order }
  }
  function coherent(dist, hypotheses) {
    const raw = Object.fromEntries(hypotheses.map((h) => [h, Math.max(0.01, Number(dist[h] || 0))]))
    const total = hypotheses.reduce((t, h) => t + raw[h], 0)
    return Object.fromEntries(hypotheses.map((h) => [h, raw[h] / total]))
  }
  function logLinearPool(entries, hypotheses) {
    const famSize = {}
    for (const e of entries) famSize[e.family] = (famSize[e.family] || 0) + 1
    const logs = Object.fromEntries(hypotheses.map((h) => [h, 0]))
    let total = 0
    for (const e of entries) {
      const w = 1 / famSize[e.family], d = coherent(e.dist, hypotheses)
      for (const h of hypotheses) logs[h] += w * Math.log(d[h])
      total += w
    }
    const raw = Object.fromEntries(hypotheses.map((h) => [h, Math.exp(logs[h] / total)]))
    const z = hypotheses.reduce((t, h) => t + raw[h], 0)
    return Object.fromEntries(hypotheses.map((h) => [h, Math.round((raw[h] / z) * 1000) / 1000]))
  }

  return { MATCHER_VERSION, POLICY_VERSION, GRAPH_SCHEMA, normalize, tokenize, matchQuote, normalizeUrl, eligible, baseline, pooledProbability, verdict, checklist, baseScore, originOf, borda, delphiFeedback, limitMove, familyMedian, ach, coherent, logLinearPool }
})()
// ==== colosseum-lib end ====

// ---------------------------------------------------------------------------
// args:
//   question : the diagnostic question ("why did X happen")
//   as_of    : today "YYYY-MM-DD"
//   roster   : [{label, family, cli?}, ...]
//   budget   : optional {search, fetch}
// ---------------------------------------------------------------------------

const A = args || {}
if (!A.question || !Array.isArray(A.roster) || A.roster.length < 2) {
  throw new Error('colosseum:diagnose needs args.question and a roster of at least 2 participants')
}
const AS_OF = A.as_of || 'unspecified'

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

// One participant turn. Claude participants run as colosseum:participant; CLI participants
// run through colosseum:cli-proxy, which passes the prompt to the CLI and returns its JSON.
async function turn(p, role, body, schema, phaseName) {
  const prompt = PRIME + '\n\n당신의 익명 라벨: ' + p.label + ' | 역할: ' + role + '\n\n' + body
  if (p.cli) {
    const fields = Object.keys(schema.properties).join(', ')
    return agent('CLI: ' + p.cli + (A.relay ? '\nRELAY: ' + A.relay : '') + '\n\n아래 프롬프트 끝에 "JSON 객체 하나로만 답하라. 필드: ' + fields + '"를 덧붙여 이 CLI에 전달하고, CLI가 돌려준 JSON을 스키마에 맞춰 반환하라. CLI는 검색할 수 없으므로 참고 자료 안의 URL과 인용만 쓸 수 있다.\n\n----- PROMPT -----\n' + prompt, { agentType: 'colosseum:cli-proxy', schema, phase: phaseName, label: p.label + ':' + role })
  }
  return agent(prompt, { agentType: 'colosseum:participant', schema, phase: phaseName, label: p.label + ':' + role })
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
// One evidence record binds one quote to one claim. Three caches keep their own keys:
//   acquisitions : normalized URL + quote -> page passage or snippet, source fields (fetched once)
//   quote checks : content hash + quote + matcher version (pure, recomputed from the cached text)
//   assessments  : claim id + claim text hash + quote key + context hash + policy version -> support
// A new claim citing an already fetched quote reuses the acquisition but gets its own
// support assessment, so a judgment made for one claim never leaks to another.
const evidence = []
const evidenceByKey = {}
const acquisitions = {}
const assessments = {}
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

async function assess(aKey, acq, claimHash, quote, claimText, phaseName) {
  if (!assessments[aKey]) {
    assessments[aKey] = (async () => {
      if (acq.assessed && acq.assessed.claimHash === claimHash) return { support: acq.assessed.support, support_reason: acq.assessed.support_reason }
      const r = await agent(SUPPORT_RUBRIC + '\n\n주장: ' + claimText + '\n인용: ' + quote + '\n인용의 문맥(원문): ' + acq.text, { schema: S_SUPPORT, phase: phaseName, label: 'support:' + textHash(aKey).slice(0, 6), effort: 'low' })
      return r ? { support: r.support, support_reason: r.support_reason || '' } : { support: 'unknown', support_reason: 'no assessment returned' }
    })()
  }
  return assessments[aKey]
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
  e.assessment_key = [claimId || '', claimHash, e.quote_key, e.match.content_hash, LIB.POLICY_VERSION].join('|')
  const a = await assess(e.assessment_key, acq, claimHash, quote, claimText, phaseName)
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

// ============================================================================
if (MATERIALS.length) { phase('Materials'); await readMaterials(A.question) }
phase('Fact base')
const FB = await buildFactBase(A.question, AS_OF)

// ============================================================================
phase('Hypotheses')
const S_HYP = { type: 'object', properties: { hypotheses: { type: 'array', maxItems: 2, items: { type: 'object', properties: { text: { type: 'string' }, why: { type: 'string' } }, required: ['text', 'why'] } }, claims: S_CLAIMS, key_assumptions: { type: 'array', items: { type: 'string' }, maxItems: 3 } }, required: ['hypotheses', 'claims', 'key_assumptions'] }
const drafts = (await parallel(A.roster.map((p, i) => () => turn(p, 'diagnostician', '질문: ' + A.question + '\n기준 시점: ' + AS_OF + '\n검색 출발점: ' + ANGLES[i % ANGLES.length] + '\n참고 팩트:\n' + FB.text + '\n\n원인에 대한 가설을 최대 2개 세우고, 각 가설을 뒷받침하거나 반박하는 사실을 claims에 URL과 원문 인용으로 적어라. 다른 참가자의 가설은 보이지 않는다.', S_HYP, 'Hypotheses').then((d) => (d ? { p, d } : null))))).filter(Boolean)
if (drafts.length < 2) throw new Error('fewer than 2 participants proposed hypotheses')

phase('Verify')
for (const x of drafts) x.evs = await checkClaims(x.d.claims, 'Verify')

const S_CONS = { type: 'object', properties: { hypotheses: { type: 'array', maxItems: 5, items: { type: 'object', properties: { text: { type: 'string' }, from: { type: 'array', items: { type: 'string' } } }, required: ['text', 'from'] } } }, required: ['hypotheses'] }
const cons = await agent('아래 가설들을 서로 배타적인 가설 최대 5개로 정리하라. 사실상 같은 것은 합치고, 합친 원래 라벨을 from에 적어라.\n\n' + drafts.flatMap((x) => x.d.hypotheses.map((h) => x.p.label + ': ' + h.text + ' (' + h.why + ')')).join('\n'), { schema: S_CONS, phase: 'Hypotheses', label: 'consolidate', effort: 'low' })
const H = ((cons && cons.hypotheses) || []).map((h, i) => ({ id: 'H' + (i + 1), text: h.text }))
H.push({ id: 'H0', text: '위 가설들로 설명되지 않는 다른 원인' })
const hids = H.map((h) => h.id)

// ============================================================================
phase('Matrix')
const rows = [...FB.evs, ...drafts.flatMap((x) => x.evs)].filter(Boolean).filter((e, i, arr) => arr.findIndex((y) => y.id === e.id) === i)
const ratingProps = Object.fromEntries(hids.map((h) => [h, { type: 'string', enum: ['C', 'I', 'N'] }]))
const S_RATE = { type: 'object', properties: { ratings: { type: 'object', properties: ratingProps, required: hids } }, required: ['ratings'] }
const hypList = H.map((h) => h.id + ': ' + h.text).join('\n')
const rated = (await parallel(rows.map((e) => () => agent('증거: "' + e.quote + '" (' + e.url + ')\n이 증거가 드러내는 사실: ' + (e.claim || '') + '\n\n가설마다 이 증거가 가설과 일관되면 C, 가설과 맞지 않으면 I, 관계가 없으면 N으로 매겨라. 가설이 참이라면 이 증거가 나올 법한지를 기준으로 삼는다.\n\n' + hypList, { schema: S_RATE, phase: 'Matrix', label: 'rate:' + e.id, effort: 'low' }).then((r) => (r ? { id: e.id, quote_status: e.quote_status, reliability: e.reliability, ratings: r.ratings } : null))))).filter(Boolean)
const matrix = LIB.ach(hids, rated)
log('진단적 증거 ' + matrix.diagnostic.length + '개, 비진단적 제외 ' + matrix.dropped.length + '개')

// ============================================================================
phase('Probabilities')
const probProps = Object.fromEntries(hids.map((h) => [h, { type: 'number', minimum: 0, maximum: 1 }]))
const S_DIST = { type: 'object', properties: { dist: { type: 'object', properties: probProps, required: hids }, reason: { type: 'string' } }, required: ['dist', 'reason'] }
const matrixText = rated.filter((r) => matrix.diagnostic.includes(r.id)).map((r) => r.id + ' [' + r.quote_status + ', ' + r.reliability + ']: ' + hids.map((h) => h + '=' + r.ratings[h]).join(' ')).join('\n')
const dists = (await parallel(drafts.map((x) => () => turn(x.p, 'estimator', '질문: ' + A.question + '\n\n가설:\n' + hypList + '\n\n진단적 증거 행렬(C 일관, I 불일치, N 무관):\n' + (matrixText || '진단적 증거 없음') + '\n\n각 가설이 참일 확률을 적어라. 합이 1이 되게 하라. 불일치(I) 증거가 많은 가설일수록 낮게 보되, 약한 증거(snippet, low)에 기댄 불일치는 덜 믿어라. 다른 참가자의 확률은 보이지 않는다.', S_DIST, 'Probabilities').then((d) => (d ? { family: x.p.family, label: x.p.label, dist: d.dist, reason: d.reason } : null))))).filter(Boolean)
const pooled = LIB.logLinearPool(dists, hids)
const ranking = hids.slice().sort((a, b) => pooled[b] - pooled[a])

// ============================================================================
phase('Premortem')
const lead = H.find((h) => h.id === ranking[0])
const critic = drafts.find((x) => !(((cons && cons.hypotheses) || [])[Number(lead.id.slice(1)) - 1] || { from: [] }).from.includes(x.p.label)) || drafts[drafts.length - 1]
const premortem = await turn(critic.p, 'premortem', '가장 유력한 원인으로 판단된 가설 "' + lead.text + '"이 틀린 것으로 확정되었다.\n질문: ' + A.question + '\n가장 그럴듯한 이유 3가지와 확인 방법을 적고, 적어도 하나는 검색해 claims에 URL과 원문 인용으로 붙여라. underconfidence에는 이 가설을 오히려 더 확신해도 되는 가장 강한 근거를 적어라.', S_PREMORTEM, 'Premortem')
const premortemEvs = premortem ? await checkClaims(premortem.claims, 'Premortem') : []

// ============================================================================
phase('Report')
const data = {
  status: 'experimental',
  materials: MATERIALS.map((m) => ({ id: m.id, title: m.title, kind: m.kind })),
  question: A.question, as_of: AS_OF, roster: drafts.map((x) => ({ label: x.p.label, family: x.p.family })),
  roster_kind: new Set(A.roster.map((p) => p.family)).size < 2 ? '동종 명단' : '이질 명단',
  verification: verificationSummary(),
  fact_base: FB.list.map((f, i) => ({ id: 'F' + (i + 1), claim: f.claim, url: f.url, check: FB.evs[i] && FB.evs[i].quote_status })),
  hypotheses: H, matrix: { rows: rated, summary: matrix }, distributions: dists, pooled, ranking,
  premortem: premortem && { causes: premortem.causes, underconfidence: premortem.underconfidence, evidence: premortemEvs.filter(Boolean).map((e) => ({ id: e.id, url: e.url, check: e.quote_status, support: e.support })) },
  evidence: evidence.map((e) => ({ id: e.id, url: e.url, quote: e.quote, reliability: e.reliability, acquisition: e.acquisition, check: e.quote_status, check_reason: e.match ? e.match.reason : null, support: e.support, support_reason: e.support_reason, note: e.note })),
  budget: { fetches: fetchesUsed + '/' + FETCH_BUDGET, failed_hosts: [...failedHosts] },
}
const report = await agent('아래 JSON은 Colosseum 진단 모드 결과다. 이 모드는 실험 단계다(status: experimental). 보고서 첫 줄에 "실험 모드: 정확도와 보정이 검증되지 않았다"를 적어라. 이 데이터만으로 한국어 보고서를 써라. 데이터에 없는 사실을 보태지 마라. 형식:\n\n=== COLOSSEUM (진단) ===\n질문, 기준 시점, 명단(이질/동종), 모드\n## 가설 (id와 내용)\n## 원인 확률 (풀링된 확률 순위, UNCALIBRATED. 참가자별 분포 요약)\n## 증거 행렬 (진단적 증거만 표로: 증거, 대조 결과, 신뢰도, 가설별 C/I/N. 제외된 비진단적 증거 수)\n## 불일치 점수 (가설별 가중 불일치와 약한 증거에 기댄 불일치 수. 이 점수는 설명용이며 확률을 정하지 않았다고 밝힌다)\n## 사전부검 (원인과 확인 방법, 증거 반영/기각)\n## 이 결론이 틀릴 수 있는 조건\n## 출처\n\n' + JSON.stringify(data), { phase: 'Report', label: 'report' })

return { report, data }
