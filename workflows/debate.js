export const meta = {
  name: 'debate',
  description: 'Colosseum: blind drafts, vote baseline, quote-verified evidence rounds, computed verdicts',
  whenToUse: 'Launched by the colosseum skill with a prepared roster; not for direct use',
  phases: [
    { title: 'Fact base', detail: 'opposing-angle searches and source records' },
    { title: 'Drafts', detail: 'blind parallel drafts from the roster' },
    { title: 'Verify', detail: 'quote checks against fetched pages' },
    { title: 'Baseline', detail: 'position groups, family-weighted vote, pooled probability' },
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
  const QUOTE = { v: 1.0, n: 0.8, snippet: 0.5, u: 0.0 }
  const SUPPORT = { full: 1.0, partial: 0.5, none: 0.0 }
  const FRESHNESS = { fresh: 1.0, na: 1.0, stale: 0.5, superseded: 0.0 }
  const VALUE_KINDS = new Set(['value', 'recommendation'])
  const NO_EVIDENCE_PRIOR = 0.2
  const MARGIN = 0.15
  const THETA = 0.5
  const MAX_UNDEC = 16
  const NEAR = 0.9
  const CLIP = [0.02, 0.98]

  // ---- quote matching (quote_match.py) ----
  const QUOTE_MAP = { '‘': "'", '’': "'", '“': '"', '”': '"', ' ': ' ' }
  function normalize(text) {
    let t = String(text || '').normalize('NFKC').replace(/[‘’“” ]/g, (c) => QUOTE_MAP[c])
    t = t.replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    t = t.replace(/(^|\s)[#>*\-+]+\s|[*_`~|]+/g, ' ')
    t = t.replace(/[^\p{L}\p{M}\p{N}_\s]/gu, ' ').toLowerCase()
    return t.replace(/\s+/g, ' ').trim()
  }
  function trigrams(words) {
    const out = []
    for (let i = 0; i + 2 < words.length; i++) out.push(words[i] + '\u0001' + words[i + 1] + '\u0001' + words[i + 2])
    if (!out.length && words.length) out.push(words.join('\u0001'))
    return out
  }
  function lcs(a, b) {
    let prev = new Array(b.length + 1).fill(0)
    for (const x of a) {
      const cur = [0]
      for (let j = 0; j < b.length; j++) cur.push(x === b[j] ? prev[j] + 1 : Math.max(prev[j + 1], cur[j]))
      prev = cur
    }
    return prev[b.length]
  }
  function bestWindow(qn, pn) {
    const q = qn ? qn.split(' ') : []
    const p = pn ? pn.split(' ') : []
    if (!q.length || !p.length) return [0, []]
    const qg = new Set(trigrams(q))
    const size = q.length + 5
    const pageGrams = trigrams(p)
    let best = 0, bestSeg = []
    const last = Math.max(1, p.length - q.length + 1)
    for (let start = 0; start < last; start++) {
      if (q.length >= 3) {
        let hits = 0
        for (const g of pageGrams.slice(start, start + size)) if (qg.has(g)) hits++
        if (hits < Math.max(1, Math.floor(qg.size / 5))) continue
      }
      const seg = p.slice(start, start + size)
      const ratio = lcs(q, seg) / q.length
      if (ratio > best) {
        best = ratio
        bestSeg = seg
        if (best === 1) break
      }
    }
    return [best, bestSeg]
  }
  function matchQuote(quote, page) {
    const qn = normalize(quote), pn = normalize(page)
    const words = qn ? qn.split(' ').length : 0
    if (!qn || !pn) return { status: 'u', score: 0, words, reason: 'empty quote or page' }
    if ((' ' + pn + ' ').includes(' ' + qn + ' ')) return { status: 'v', score: 1, words }
    const [ratio, win] = bestWindow(qn, pn)
    const winSet = new Set(win)
    const numbersOk = qn.split(' ').filter((w) => /\p{Nd}/u.test(w)).every((w) => winSet.has(w))
    const score = Math.round(ratio * 1000) / 1000
    const out = { status: score >= NEAR && numbersOk ? 'n' : 'u', score, words }
    if (!numbersOk) out.reason = 'numbers differ from the page'
    return out
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
    let acc = 0, total = 0
    for (const d of drafts) {
      const p = clip(d.probability)
      const pPos = d.position === position ? p : 1 - p
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
    return { baseline_vote: vote.winner, tie: vote.tie, tally: vote.tally, p0_position: target, p0: Math.round(p0 * 1000) / 1000, extremizing: a, roster: homogeneous ? 'homogeneous' : 'heterogeneous', unanimous: sameSide, skip_debate: skip, needs_dissenter: sameSide && homogeneous, notes }
  }

  // ---- graph and verdicts (graph.py, verdict_engine.py) ----
  function originOf(e) {
    if (e.origin) return String(e.origin)
    let host = ''
    try { host = new URL(e.url || '').hostname } catch (err) { host = '' }
    if (host.startsWith('www.')) host = host.slice(4)
    return host ? 'host:' + host : 'unknown'
  }
  const evidenceScore = (e) => RELIABILITY[e.reliability] * QUOTE[e.quote_status] * SUPPORT[e.support] * FRESHNESS[e.freshness || 'na']
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
  const hasChecked = (claim, evById) => (claim.evidence || []).some((eid) => evById[eid].quote_status !== 'u' && evById[eid].support !== 'none')

  function validate(doc) {
    for (const k of ['evidence', 'claims', 'relations']) if (!Array.isArray(doc[k])) throw new Error('missing list: ' + k)
    const ev = new Set(), cl = new Set()
    for (const e of doc.evidence) {
      if (!e.id || ev.has(e.id)) throw new Error('bad evidence id ' + e.id)
      ev.add(e.id)
      if (!(e.reliability in RELIABILITY) || !(e.quote_status in QUOTE) || !(e.support in SUPPORT) || !((e.freshness || 'na') in FRESHNESS)) throw new Error('bad evidence fields ' + e.id)
    }
    for (const c of doc.claims) {
      if (!c.id || cl.has(c.id)) throw new Error('bad claim id ' + c.id)
      cl.add(c.id)
      for (const eid of c.evidence || []) if (!ev.has(eid)) throw new Error(c.id + ' cites unknown evidence ' + eid)
    }
    for (const r of doc.relations) {
      if (!cl.has(r.from) || !cl.has(r.to) || r.from === r.to) throw new Error('bad relation ' + r.from + ' -> ' + r.to)
      if (r.type === 'attack' && !['rebut', 'undercut', 'undermine'].includes(r.subtype)) throw new Error('attack needs subtype')
    }
    for (const cf of doc.conflicts || []) if (!cl.has(cf.a) || !cl.has(cf.b)) throw new Error('conflict references an unknown claim')
    return doc
  }

  const pairKey = (a, b) => a + '\u0000' + b
  function verdict(doc, theta = THETA) {
    validate(doc)
    const evById = Object.fromEntries(doc.evidence.map((e) => [e.id, e]))
    const nodes = {}
    for (const c of doc.claims) if ((c.status || 'active') === 'active') nodes[c.id] = c
    const ids = Object.keys(nodes).sort()
    const tau = Object.fromEntries(ids.map((n) => [n, baseScore(nodes[n], evById)]))
    const att = doc.relations.filter((r) => r.type === 'attack' && nodes[r.from] && nodes[r.to])
    const sup = doc.relations.filter((r) => r.type === 'support' && nodes[r.from] && nodes[r.to])
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
      theta, labels: lab, status,
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
    const checked = (e, level) => (level === 'quote' ? ['v', 'n'] : ['v', 'n', 'snippet']).includes(e.quote_status) && e.support !== 'none'
    const target = 2 + (highStakes ? 1 : 0)
    const rows = { decisive: [0, 0, 0], supporting: [0, 0, 0] }
    const corroboration = {}, unverified = new Set(), quality = { high: 0, medium: 0, low: 0 }
    for (const f of doc.final || []) {
      const c = claims[f.claim]
      if (!c) throw new Error('final references unknown claim ' + f.claim)
      if (VALUE_KINDS.has(c.kind || 'fact')) continue
      const cited = (c.evidence || []).map((id) => ev[id])
      const bucket = (f.weight || 1) >= 3 ? 'decisive' : 'supporting'
      rows[bucket][2]++
      if (cited.some((e) => checked(e, 'quote'))) rows[bucket][0]++
      else if (cited.some((e) => checked(e, 'snippet'))) rows[bucket][1]++
      for (const e of cited) { quality[e.reliability]++; if (e.quote_status === 'u') unverified.add(e.id) }
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
      unverified_quotes: [...unverified].sort(),
    }
  }

  return { normalize, matchQuote, baseline, pooledProbability, verdict, checklist, baseScore, originOf }
})()
// ==== colosseum-lib end ====

// ---------------------------------------------------------------------------
// Orchestration. args:
//   question   : the user's question (string)
//   as_of      : reference date, e.g. "2026-09-30"
//   stakes     : low | medium | high
//   roster     : [{label: "A", family: "claude"}, {label: "B", family: "gemini", cli: "gemini"}, ...]
//   cli_juror  : optional CLI name for the juror when it is not in the roster
//   max_rounds : optional, default 3 (never above 3)
//   budget     : optional {search: 25, fetch: 15}
// ---------------------------------------------------------------------------

const A = args || {}
if (!A.question || !Array.isArray(A.roster) || A.roster.length < 2) {
  throw new Error('colosseum:debate needs args.question and a roster of at least 2 participants')
}
const STAKES = ['low', 'medium', 'high'].includes(A.stakes) ? A.stakes : 'medium'
const MAX_ROUNDS = Math.min(3, Math.max(1, A.max_rounds || 3))
const FETCH_BUDGET = (A.budget && A.budget.fetch) || 15
const ISSUES_PER_ROUND = STAKES === 'high' ? 2 : 1
const THETA = STAKES === 'high' ? 0.7 : 0.5
const AS_OF = A.as_of || 'unspecified'
const FAMILIES = new Set(A.roster.map((p) => p.family))
const HOMOGENEOUS = FAMILIES.size < 2

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
const S_DRAFT = { type: 'object', properties: { position: { type: 'string' }, claims: S_CLAIMS, key_assumptions: { type: 'array', items: { type: 'string' }, maxItems: 3 }, cruxes: { type: 'array', items: { type: 'object', properties: { text: { type: 'string' }, type: { type: 'string', enum: ['empirical', 'value'] } }, required: ['text', 'type'] }, maxItems: 2 }, strongest_counter: { type: 'string' }, probability: { type: 'number', minimum: 0.02, maximum: 0.98 } }, required: ['position', 'claims', 'key_assumptions', 'cruxes', 'strongest_counter', 'probability'] }
const S_CHECK = { type: 'object', properties: { fetch_failed: { type: 'boolean' }, passage: { type: 'string' }, publisher: { type: 'string' }, published: { type: 'string' }, reliability: { type: 'string', enum: ['high', 'medium', 'low'] }, origin: { type: 'string' }, support: { type: 'string', enum: ['full', 'partial', 'none'] } }, required: ['fetch_failed', 'passage', 'reliability', 'origin', 'support'] }
const S_SNIPPET = { type: 'object', properties: { in_snippet: { type: 'boolean' }, snippet: { type: 'string' }, reliability: { type: 'string', enum: ['high', 'medium', 'low'] }, origin: { type: 'string' }, support: { type: 'string', enum: ['full', 'partial', 'none'] } }, required: ['in_snippet', 'reliability', 'origin', 'support'] }
const S_GROUPS = { type: 'object', properties: { groups: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, labels: { type: 'array', items: { type: 'string' } }, summary: { type: 'string' } }, required: ['id', 'labels', 'summary'] } } }, required: ['groups'] }
const S_ISSUES = { type: 'object', properties: { issues: { type: 'array', maxItems: 4, items: { type: 'object', properties: { question: { type: 'string' }, kind: { type: 'string', enum: ['empirical', 'value'] }, a_label: { type: 'string' }, a_claim: { type: 'integer' }, b_label: { type: 'string' }, b_claim: { type: 'integer' }, changes_answer: { type: 'boolean' } }, required: ['question', 'kind', 'a_label', 'a_claim', 'b_label', 'b_claim', 'changes_answer'] } } }, required: ['issues'] }
const S_PROSECUTOR = { type: 'object', properties: { steelman: { type: 'string' }, attack_subtype: { type: 'string', enum: ['rebut', 'undercut', 'undermine'] }, attack: { type: 'string' }, claims: S_CLAIMS, position_update: { type: 'string' } }, required: ['steelman', 'attack_subtype', 'attack', 'claims', 'position_update'] }
const S_WITNESS = { type: 'object', properties: { premise: { type: 'string' }, verdict: { type: 'string', enum: ['holds', 'fails', 'partly holds'] }, if_false: { type: 'string' }, claims: S_CLAIMS }, required: ['premise', 'verdict', 'if_false', 'claims'] }
const S_DEFENDER = { type: 'object', properties: { steelman_check: { type: 'string', enum: ['faithful', 'distorted'] }, distortion_reason: { type: 'string' }, response: { type: 'string', enum: ['concede', 'rebut', 'partial'] }, text: { type: 'string' }, claims: S_CLAIMS, change_basis: { type: 'string' }, position: { type: 'string' } }, required: ['steelman_check', 'response', 'text', 'claims', 'change_basis', 'position'] }
const S_JUROR = { type: 'object', properties: { winner: { type: 'string', enum: ['first', 'second', 'both', 'neither'] }, reason: { type: 'string' } }, required: ['winner', 'reason'] }
const S_PREMORTEM = { type: 'object', properties: { causes: { type: 'array', items: { type: 'object', properties: { cause: { type: 'string' }, check: { type: 'string' } }, required: ['cause', 'check'] }, maxItems: 3 }, underconfidence: { type: 'string' }, claims: S_CLAIMS }, required: ['causes', 'underconfidence', 'claims'] }

const participantByLabel = Object.fromEntries(A.roster.map((p) => [p.label, p]))
const cliJuror = A.cli_juror || (A.roster.find((p) => p.cli) || {}).cli || null

// One participant turn. Claude participants run as colosseum:participant; CLI participants
// run through colosseum:cli-proxy, which passes the prompt to the CLI and returns its JSON.
async function turn(p, role, body, schema, phaseName) {
  const prompt = PRIME + '\n\n당신의 익명 라벨: ' + p.label + ' | 역할: ' + role + '\n\n' + body
  if (p.cli) {
    const fields = Object.keys(schema.properties).join(', ')
    return agent('CLI: ' + p.cli + '\n\n아래 프롬프트 끝에 "JSON 객체 하나로만 답하라. 필드: ' + fields + '"를 덧붙여 이 CLI에 전달하고, CLI가 돌려준 JSON을 스키마에 맞춰 반환하라. CLI는 검색할 수 없으므로 참고 자료 안의 URL과 인용만 쓸 수 있다.\n\n----- PROMPT -----\n' + prompt, { agentType: 'colosseum:cli-proxy', schema, phase: phaseName, label: p.label + ':' + role })
  }
  return agent(prompt, { agentType: 'colosseum:participant', schema, phase: phaseName, label: p.label + ':' + role })
}

// ---- evidence registry and quote checks ----
const evidence = []
const evidenceByKey = {}
const failedHosts = new Set()
let fetchesUsed = 0
let degraded = false

function hostOf(url) {
  try { return new URL(url).hostname } catch (e) { return url }
}

async function checkEvidence(url, quote, claimText, phaseName) {
  const key = url + '\u0000' + quote
  if (evidenceByKey[key]) return evidenceByKey[key]
  const e = { id: 'E' + (evidence.length + 1), url, quote, claim: claimText, reliability: 'low', quote_status: 'u', support: 'none', freshness: 'na' }
  evidence.push(e)
  evidenceByKey[key] = e
  if (!url || !quote) { e.note = 'missing url or quote'; return e }
  const rubric = '신뢰도: high는 1차 자료, 공식 문서, 동료 심사 연구 / medium은 주요 언론, 전문가 블로그 / low는 커뮤니티 글, 출처 불명 요약. origin은 이 내용의 원출처 ID(같은 논문, 보도자료, 통신 기사, 데이터셋을 옮긴 페이지들은 같은 ID. 예: "doi:10.1038/xxx", "reuters:story-slug"). support는 아래 주장과 인용만 보고 판단한다: 인용이 주장을 그대로 뒷받침하면 full, 일부만 뒷받침하면 partial, 아니면 none.'
  let fetchFailed = false
  if (!degraded && fetchesUsed < FETCH_BUDGET) {
    fetchesUsed++
    const r = await agent('WebFetch로 이 URL을 가져와라: ' + url + '\nWebFetch 프롬프트: "다음 구절이나 거의 같은 구절이 페이지에 있으면 그 구절을 원문 그대로 반환하고, 없으면 NOT FOUND라고만 답하라: ' + quote + '"\n가져오기가 실패하면(오류, 차단, 빈 페이지) fetch_failed를 true로 하라. passage에는 WebFetch가 돌려준 구절을 그대로 넣고, NOT FOUND면 빈 문자열을 넣어라.\n' + rubric + '\n\n주장: ' + claimText + '\n인용: ' + quote, { schema: S_CHECK, phase: phaseName, label: 'check:' + e.id, effort: 'low' })
    if (r) {
      Object.assign(e, { reliability: r.reliability, origin: r.origin || undefined, support: r.support, publisher: r.publisher, published: r.published })
      if (r.fetch_failed) {
        failedHosts.add(hostOf(url))
        e.note = 'fetch failed'
        if (failedHosts.size >= 3 && !degraded) { degraded = true; log('원문 대조 불가 모드: 서로 다른 호스트 3곳에서 페이지 가져오기 실패') }
        fetchFailed = true
      } else {
        const m = LIB.matchQuote(quote, r.passage || '')
        e.quote_status = m.status
        e.match_score = m.score
        return e
      }
    }
  }
  if (degraded || fetchFailed) {
    const r = await agent('WebSearch로 다음 인용문을 따옴표로 묶어 검색하라: "' + quote + '"\n검색 결과의 제목이나 요약에 이 인용이 (따옴표, 대소문자, 공백 차이를 빼고) 그대로 들어 있으면 in_snippet을 true로 하고 그 스니펫을 넣어라. 원래 URL: ' + url + '\n' + rubric + '\n\n주장: ' + claimText, { schema: S_SNIPPET, phase: phaseName, label: 'snippet:' + e.id, effort: 'low' })
    if (r) {
      Object.assign(e, { reliability: r.reliability, origin: r.origin || undefined, support: r.support })
      const m = LIB.matchQuote(quote, r.snippet || '')
      e.quote_status = r.in_snippet || m.status !== 'u' ? 'snippet' : 'u'
    }
  } else if (fetchesUsed >= FETCH_BUDGET && e.quote_status === 'u' && !e.note) {
    e.note = 'unchecked (budget)'
  }
  return e
}

async function checkClaims(claims, phaseName) {
  return parallel((claims || []).map((c) => () => (c.url && c.quote ? checkEvidence(c.url, c.quote, c.text, phaseName) : Promise.resolve(null))))
}

const isChecked = (e) => !!e && ['v', 'n', 'snippet'].includes(e.quote_status) && e.support !== 'none'

// ---- graph ----
const graphClaims = []
const relations = []
function addClaims(label, prefix, claims, evs) {
  return (claims || []).map((c, i) => {
    const id = label + '.' + prefix + i
    const e = evs && evs[i]
    graphClaims.push({ id, author: label, text: c.text, kind: c.kind || 'fact', evidence: e ? [e.id] : [], status: 'active' })
    return id
  })
}
const claimById = (id) => graphClaims.find((c) => c.id === id)

// ============================================================================
phase('Fact base')
const facts = await agent(PRIME.split('\n')[0] + '\n질문: ' + A.question + '\n기준 시점: ' + AS_OF + '\n\n세 방향으로 WebSearch를 한 번씩 하라: 찬성 근거, 반대 근거, 최신 현황. 논쟁적 공적 주장이면 기존 팩트체크 기사부터 찾는다. 판정에 중요한 사실 3-6개를 골라 각각 URL과 검색 결과에 나온 50단어 이하 원문 구절을 적어라. 구절을 지어내지 마라.', { schema: S_FACTS, phase: 'Fact base', label: 'fact-base' })
const factList = (facts && facts.facts) || []
const factEvidence = await checkClaims(factList.map((f) => ({ text: f.claim, url: f.url, quote: f.quote })), 'Fact base')
const FACT_BASE = factList.map((f, i) => '[F' + (i + 1) + '] ' + f.claim + ' | ' + f.url + ' | "' + f.quote + '" | 대조: ' + (factEvidence[i] ? factEvidence[i].quote_status : 'u')).join('\n')

// ============================================================================
phase('Drafts')
const draftBody = (i) => '다음 질문에 대한 입장을 명확히 선언하라. 다른 참가자의 입장은 공개되지 않는다.\n검색 출발점: ' + ANGLES[i % ANGLES.length] + '\n\n질문: ' + A.question + '\n기준 시점: ' + AS_OF + '\n참고 팩트:\n' + FACT_BASE + '\n\nFACT_BASE 밖의 근거가 필요하면 직접 검색하라(최대 2회). claims는 2-4개, probability는 당신의 position이 옳을 확률이다.'
const drafts = (await parallel(A.roster.map((p, i) => () => turn(p, 'draft', draftBody(i), S_DRAFT, 'Drafts').then((d) => (d ? { p, d } : null))))).filter(Boolean)
if (drafts.length < 2) throw new Error('fewer than 2 drafts came back; cannot continue')
const dropped = A.roster.filter((p) => !drafts.some((x) => x.p.label === p.label)).map((p) => p.label)
if (dropped.length) log('초안 없음으로 제외: ' + dropped.join(', '))

phase('Verify')
const draftClaimIds = {}
await pipeline(drafts, (x) => checkClaims(x.d.claims, 'Verify'), (evs, x) => { draftClaimIds[x.p.label] = addClaims(x.p.label, 'd', x.d.claims, evs); return true })

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
    const evs = await checkClaims(d.claims, 'Baseline')
    dissenter = { claims: d.claims, ids: addClaims('D', 'x', d.claims, evs), verified: evs.some(isChecked) }
    counterEvidence.push(...evs.filter(isChecked).map((e) => e.id))
    log('반대자: 검증된 반대 증거 ' + counterEvidence.length + '건')
  }
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
  const found = await agent('아래 초안들에서 쟁점을 최대 4개 찾아라. 우선순위는 더블 크럭스: 한쪽 입장은 그것이 참이어야, 다른 쪽 입장은 거짓이어야 성립하는 명제. 각 쟁점마다 서로 충돌하는 두 주장을 a_label/a_claim, b_label/b_claim으로 지정하라. 라벨 칸에는 라벨 글자 하나만(예: A), claim 칸에는 번호만 넣는다. 두 주장은 서로 다른 라벨이어야 한다. 검색으로 결판낼 수 있으면 empirical, 가치 판단이면 value. 쟁점 해소가 원래 질문의 답을 바꾸는지 changes_answer에 적어라.\n\n질문: ' + A.question + '\n\n' + listing, { schema: issueSchema, phase: 'Issues', label: 'issue-map' })
  const claimRef = (label, idx) => (label === 'D' ? dissenter && dissenter.ids[idx] : draftClaimIds[label] && draftClaimIds[label][idx])
  for (const it of (found && found.issues) || []) {
    const a = claimRef(it.a_label, it.a_claim), b = claimRef(it.b_label, it.b_claim)
    if (!a || !b || it.a_label === it.b_label) continue
    if (it.kind === 'value') { valueIssues.push(it.question); continue }
    if (!it.changes_answer) continue
    issues.push({ question: it.question, a, b, aLabel: it.a_label, bLabel: it.b_label, open: true })
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
      const proEvs = pro ? await checkClaims(pro.claims, 'Rounds') : []
      const witEvs = wit ? await checkClaims(wit.claims, 'Rounds') : []
      const fmt = (claims, evs) => (claims || []).map((c, i) => '- ' + c.text + ' | ' + (c.url || '') + ' | "' + (c.quote || '') + '" [대조: ' + (evs[i] ? evs[i].quote_status : 'u') + ']').join('\n')
      const defBody = '쟁점: ' + iss.question + '\n당신(' + defLabel + ')의 주장: ' + describe(target) + '\n\n검사의 재진술(steelman): ' + (pro ? pro.steelman : '(없음)') + '\n검사의 공격(' + (pro ? pro.attack_subtype : '-') + '): ' + (pro ? pro.attack : '(없음)') + '\n검사의 증거:\n' + (pro ? fmt(pro.claims, proEvs) : '') + '\n\n반대증인: 전제 "' + (wit ? wit.premise : '-') + '" → ' + (wit ? wit.verdict : '-') + '\n' + (wit ? fmt(wit.claims, witEvs) : '') + '\n\n먼저 steelman이 당신 주장을 공정하게 옮겼는지 판정하라. 대조 결과가 v, n, snippet인 증거에 기반한 공격이면 인정(concede)하고 change_basis에 그 증거를 적어라. u 인용에 기대는 공격은 검색 근거로 반박하라.'
      const def = await turn(participantByLabel[defLabel] || { label: defLabel, family: 'claude' }, 'defender', defBody, S_DEFENDER, 'Rounds')
      const defEvs = def ? await checkClaims(def.claims, 'Rounds') : []

      const r = { round, issue: iss.question, prosecutor: proLabel, defender: defLabel, witness: witLabel, steelman: def ? def.steelman_check : 'n/a', response: def ? def.response : 'none', quotes: { v: 0, n: 0, snippet: 0, u: 0 } }
      for (const e of [...proEvs, ...witEvs, ...defEvs].filter(Boolean)) r.quotes[e.quote_status]++
      const attackValid = pro && !(def && def.steelman_check === 'distorted')
      if (attackValid) {
        const ids = addClaims(proLabel, 'r' + round + 'p', pro.claims, proEvs)
        ids.forEach((id) => relations.push({ type: 'attack', subtype: pro.attack_subtype, from: id, to: iss.a }))
      } else if (pro) r.void_attack = true
      if (wit && wit.verdict === 'fails') {
        const ids = addClaims(witLabel, 'r' + round + 'w', wit.claims, witEvs)
        ids.forEach((id) => { relations.push({ type: 'attack', subtype: 'undermine', from: id, to: iss.a }); relations.push({ type: 'attack', subtype: 'undermine', from: id, to: iss.b }) })
      }
      if (def) {
        const ids = addClaims(defLabel, 'r' + round + 'd', def.claims, defEvs)
        const proIds = graphClaims.filter((c) => c.id.startsWith(proLabel + '.r' + round + 'p')).map((c) => c.id)
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
  evidence: evidence.map((e) => ({ id: e.id, url: e.url, quote: e.quote, reliability: e.reliability, quote_status: e.quote_status, support: e.support, freshness: e.freshness, origin: e.origin })),
  claims: graphClaims.map((c) => ({ id: c.id, author: c.author, text: c.text, kind: c.kind, evidence: c.evidence, status: c.status })),
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
  if (cliJuror) return agent('CLI: ' + cliJuror + '\n\n아래 프롬프트를 이 CLI에 그대로 전달하고, CLI가 돌려준 판정을 스키마에 맞춰 반환하라.\n\n----- PROMPT -----\n' + prompt, Object.assign(opts, { agentType: 'colosseum:cli-proxy' }))
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
  const reverified = minClaim.evidence.some((id) => { const e = evidence.find((x) => x.id === id); return e && (e.quote_status === 'v' || (degraded && e.quote_status === 'snippet')) })
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
  question: A.question, as_of: AS_OF, stakes: STAKES,
  roster: drafts.map((x) => ({ label: x.p.label, family: x.p.family, cli: x.p.cli || null })), dropped,
  roster_kind: HOMOGENEOUS ? '동종 명단' : '이질 명단',
  mode: degraded ? '원문 대조 불가: 스니펫 수준 검증' : '원문 대조',
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
  evidence: evidence.map((e) => ({ id: e.id, url: e.url, quote: e.quote, publisher: e.publisher, published: e.published, reliability: e.reliability, check: e.quote_status, support: e.support, origin: e.origin, note: e.note })),
  budget: { fetches: fetchesUsed + '/' + FETCH_BUDGET, failed_hosts: [...failedHosts] },
}

const report = await agent('아래 JSON은 Colosseum 실행 결과다. 이 데이터만으로 한국어 최종 보고서를 써라. 데이터에 없는 사실을 보태지 마라. 형식:\n\n=== COLOSSEUM ===\n질문, 기준 시점, 명단(라벨과 모델 계열, 이질/동종 명단), 진행(라운드 수와 종료 사유), 모드\n## 초기 팩트 베이스 (대조 결과 표시)\n## 기준선 (초안 입장 A/B/C, BASELINE_VOTE, P0)\n## 라운드별 전개 (표: 라운드, 쟁점, 역할, 인용 v/n/snippet/u, 인정/동조 플립/무효 공격)\n## 충돌 판정 (표: 쟁점, 엔진 판정, 배심원 두 순서 판정. 엔진 라벨 표기: A_WINS→A 우세, B_WINS→B 우세, PARTIAL_BOTH_SURVIVE→쌍방 부분 인정, CONDITIONAL/VALUE_CONDITIONAL→조건부, LOSER_REFUTED_WINNER_UNPROVEN→한쪽 반박됨·다른 쪽 미입증, UNRESOLVED/NEITHER_ESTABLISHED→판정 불가)\n## 반대 입장의 가장 강한 논거\n## 합의 도달 사항\n## 해소되지 않은 쟁점 (조건부 답변, 가치 쟁점 포함)\n## 최종 답변 (팩트 클레임마다 [증거ID], 기준선 대비 일치/역전, P_final과 UNCALIBRATED)\n## 출처 (증거ID, URL, 발행처, 대조 결과)\n## 증거 품질 점검표 (checklist를 그대로 옮김)\n## 메타 정보 (가져오기 예산, 동조 플립, 배심원 계열: ' + jurorFamily + ', 사전부검 반영/기각, 제외된 참가자, 이 답이 틀릴 수 있는 조건)\n\n사전부검에서 대조 결과가 v, n, snippet이고 support가 none이 아닌 증거가 있으면 최종 답변에 그 단서를 반영하고 "반영"으로, 아니면 "기각"으로 적어라. 교착을 합의로 포장하지 마라.\n\n' + JSON.stringify(data), { phase: 'Report', label: 'report' })

return { report, data, graph: doc, verdict: engine }
