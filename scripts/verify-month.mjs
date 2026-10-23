/** Audit real DSH sessions for every report, including durable model identity. */
import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs'
import { resolve, join } from 'node:path'
import { zstdDecompressSync } from 'node:zlib'
import assert from 'node:assert/strict'

const root = resolve(import.meta.dirname, '..')
const id = process.argv[2]
assert.match(id ?? '', /^[a-f0-9]{64}$/)
const screening = join(root, 'data/screening/runs', id)
const product = join(root, 'data/product/runs', id)
const folder = existsSync(product) ? product : existsSync(screening) ? screening : join(root, 'data/monthly', id)
const read = path => JSON.parse(readFileSync(path, 'utf8'))
const manifest = read(join(folder, 'manifest.json'))
const arg = name => { const i = process.argv.indexOf(name); return i < 0 ? null : process.argv[i + 1] }
const selectedDate = arg('--date'), selectedKind = arg('--kind')
if (selectedDate) assert.match(selectedDate, /^\d{4}-\d{2}-\d{2}$/)
if (selectedKind) assert(['daily','weekly'].includes(selectedKind))
const evidence = []
for (const [kind, dates] of [['daily', manifest.report_days], ['weekly', manifest.weekly_dates]]) {
  if (selectedKind && selectedKind !== kind) continue
  for (const day of dates) {
    if (selectedDate && selectedDate !== day) continue
    const report = read(join(folder, kind, `${day}.json`))
    const analysis = report.model_analysis
    assert(analysis?.verified_session, `${kind} ${day}: no verified model analysis`)
    const run = analysis.verified_session
    const proof = read(join(run, 'manifest.json'))
    assert.equal(proof.status, 'verified')
    assert.equal(proof.date, day)
    assert.equal(proof.kind, kind)
    assert.equal(proof.replay_id, id)
    assert.equal(proof.context_hash, analysis.context_hash)
    const events = readFileSync(join(run, 'events.jsonl'), 'utf8').trim().split('\n').map(JSON.parse)
    const sessionId = events.find(e => e.type === 'session')?.sessionId
    assert(sessionId)
    const dirs = readdirSync(join(root, '.dsh/sessions'), { withFileTypes: true }).filter(e => e.isDirectory())
    let source
    for (const dir of dirs) {
      try { source = readFileSync(join(root, '.dsh/sessions', dir.name, sessionId, 'session.v4.jsonl.zstd')); break } catch (e) { if (e.code !== 'ENOENT') throw e }
    }
    assert(source, 'missing durable DSH session')
    let offset = 0
    const frames = []
    while (offset < source.length) {
      const frame = zstdDecompressSync(source.subarray(offset), { info: true })
      assert(frame.engine.bytesWritten > 0)
      offset += frame.engine.bytesWritten
      frames.push(frame.buffer)
    }
    const durable = Buffer.concat(frames).toString('utf8').trim().split('\n').map(JSON.parse)
    const header = durable.find(e => e.type === 'request/header')?.data.header
    assert.equal(header?.config.provider, 'openai-codex')
    assert.equal(header.config.model, proof.model)
    for (const name of ['fund_daily', 'operator_catalog', 'operator_program_preview', 'operator_program_evaluate']) {
      assert(header.tools.some(t => t.name === name), `plugin tool missing: ${name}`)
    }
    if (folder === screening || folder === product) {
      for (const name of ['fund_screening_report', 'screening_weekly_report', 'screening_evaluation']) {
        assert(header.tools.some(t => t.name === name), `screening plugin missing: ${name}`)
      }
    }
    const prefix = kind === 'daily' ? 'daily_analysis' : 'operator_weekly'
    const calls = events.filter(e => e.type === 'tool_call')
    assert(calls.every(c => [prefix + '_context', prefix + '_save'].includes(c.tool)))
    assert(calls.every(c => c.input.date === day && c.input.replay_id === id))
    const contextCall = calls.find(c => c.tool === prefix + '_context')
    const contextResult = events.find(e => e.type === 'tool_result' && e.callId === contextCall.callId && e.status === 'completed')
    assert(contextResult)
    const saves = calls.filter(c => c.tool === prefix + '_save' && events.some(e => e.type === 'tool_result' && e.callId === c.callId && e.status === 'completed'))
    const saved = saves.at(-1)
    assert(saved && events.indexOf(saved) > events.indexOf(contextResult))
    assert.equal(saved.input.analysis, analysis.analysis)
    assert.deepEqual(JSON.parse(saved.input.evidence_json), analysis.evidence)
    if (kind === 'weekly') {
      const proposed = JSON.parse(saved.input.proposals_json)
      assert(proposed.length > 0)
      assert.deepEqual(proposed.map(p => p.expression), analysis.proposals.map(p => p.expression))
    }
    const rendered = readFileSync(join(folder, kind, `${day}.md`), 'utf8')
    if (analysis.reader_format === 'fund-cards-v1') {
      for (const line of analysis.analysis.split('\n')) assert(rendered.includes(line))
    } else assert(rendered.includes(analysis.analysis))
    evidence.push({ kind, day, sessionId, model: proof.model, context_hash: proof.context_hash })
  }
}
assert(evidence.length > 0, 'verification scope has no reports')
const proof = { status: 'verified', scope: { date: selectedDate, kind: selectedKind }, daily: evidence.filter(e=>e.kind==='daily').length, weekly: evidence.filter(e=>e.kind==='weekly').length, sessions: evidence }
writeFileSync(join(folder, selectedDate || selectedKind ? `model-proof-${selectedDate ?? 'all'}-${selectedKind ?? 'all'}.json` : 'model-proof.json'), JSON.stringify(proof, null, 2) + '\n')
console.log(JSON.stringify({ status: proof.status, daily: proof.daily, weekly: proof.weekly }))
