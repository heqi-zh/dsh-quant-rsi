/** Audit a real DSH session and its archived experiment without another model call. */
import { readFileSync, writeFileSync, readdirSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { zstdDecompressSync } from 'node:zlib'
import { dirname, resolve, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const run = resolve(process.argv[2] ?? '')
assert(run.startsWith(join(root, 'data/dsh-runs') + '/'), 'Expected a DQR run directory')
const read = path => JSON.parse(readFileSync(path, 'utf8'))
const hash = value => createHash('sha256').update(value).digest('hex')
const manifest = read(join(run, 'manifest.json'))
assert.equal(manifest.status, 'completed')
assert.equal(manifest.exit_code, 0)
const events = readFileSync(join(run, 'events.jsonl'), 'utf8').trim().split('\n').map(line => JSON.parse(line))
const sessionId = events.find(event => event.type === 'session')?.sessionId
assert(sessionId, 'Missing real DSH session ID')
const sessions = join(root, '.dsh/sessions')
const matches = readdirSync(sessions, { withFileTypes: true })
  .filter(entry => entry.isDirectory())
  .map(entry => join(sessions, entry.name, sessionId, 'session.v4.jsonl.zstd'))
let sessionPath, source
for (const path of matches) {
  try { source = readFileSync(path); sessionPath = path; break } catch (error) {
    if (error.code !== 'ENOENT') throw error
  }
}
assert(source, 'Missing durable DSH session')
// Node's one-shot decoder returns one frame; DSH appends several independent frames.
let offset = 0
const frames = []
while (offset < source.length) {
  const result = zstdDecompressSync(source.subarray(offset), { info: true })
  assert(result.engine.bytesWritten > 0, 'Zstd decoder made no progress')
  offset += result.engine.bytesWritten
  frames.push(result.buffer)
}
const durable = Buffer.concat(frames).toString('utf8').trim().split('\n').map(line => JSON.parse(line))
const header = durable.find(event => event.type === 'request/header')?.data.header
assert(header, 'Missing durable model request')
assert.equal(header.config.provider, 'openai-codex')
assert.equal(header.config.model, manifest.model)
const tools = header.tools.map(tool => tool.name)
for (const name of ['fund_snapshot', 'fund_daily', 'strategy_evaluate', 'research_trial']) {
  assert(tools.includes(name), `Plugin tool was not actually loaded: ${name}`)
}
const calls = events.filter(event => event.type === 'tool_call')
const trialCalls = calls.filter(event => event.tool === 'research_trial')
const research = manifest.research_run_id ? read(join(run, 'research.json')) : null
assert(trialCalls.length >= 1, 'No model-authored trial')
assert(trialCalls.length <= (manifest.max_rounds ?? 1), 'Run exceeded round budget')
if (research) {
  assert.equal(research.rounds_used, trialCalls.length)
  assert.equal(research.status, 'stopped')
  assert(['round_limit', 'no_improvement', 'failure_limit', 'global_budget_exhausted', 'time_limit'].includes(research.stop_reason), 'Model stopped before a host budget/early-stop condition')
}
const dailyCall = calls.find(event => event.tool === 'fund_daily')
assert(dailyCall)
const toolResult = call => events.find(event => event.type === 'tool_result' && event.callId === call.callId)
const dailyResult = toolResult(dailyCall)
assert.equal(dailyResult?.status, 'completed')
const textEvents = events.filter(event => event.type === 'text' && event.text?.trim())
const final = textEvents.at(-1)
assert(final, 'Missing final model response')
let priorResult = dailyResult
let expectedParent = manifest.seed_trial_id ?? null
const rounds = []
for (const [index, trialCall] of trialCalls.entries()) {
  assert(events.indexOf(priorResult) < events.indexOf(trialCall), 'Next candidate did not follow previous feedback')
  const trialResult = toolResult(trialCall)
  assert.equal(trialResult?.status, 'completed')
  const result = JSON.parse(trialResult.result)
  assert(['ok', 'failed'].includes(result.status), 'Unexpected evaluator status')
  assert.equal(result.snapshot_id, manifest.snapshot_id)
  const folder = resolve(result.artifact_dir)
  assert(folder.startsWith(join(root, 'data/experiments', manifest.snapshot_id) + '/'))
  const archived = read(join(folder, 'result.json'))
  assert.equal(archived.trial_id, result.trial_id)
  assert.equal(archived.decision, result.decision)
  const code = readFileSync(join(folder, 'candidate.py'), 'utf8')
  const parent = readFileSync(join(folder, 'parent.py'), 'utf8')
  assert.equal(code, trialCall.input.code, 'Archived code differs from model tool arguments')
  assert.notEqual(code, parent, 'Model did not change the parent strategy')
  const request = read(join(folder, 'request.json'))
  assert.deepEqual(request.evaluation, manifest.evaluation ?? read(join(root, 'configs/evaluation.json')), 'Fixed evaluator changed')
  assert.equal(request.hypothesis, trialCall.input.hypothesis)
  assert.equal(request.parent_trial_id, expectedParent, 'Broken sequential parent lineage')
  if (expectedParent) {
    const parentPath = join(root, 'data/experiments', manifest.snapshot_id, expectedParent, 'candidate.py')
    assert.equal(parent, readFileSync(parentPath, 'utf8'))
  } else assert.equal(hash(parent), manifest.parent_sha256)
  if (research) {
    assert.equal(request.research_run_id, manifest.research_run_id)
    assert.equal(request.round, index + 1)
    assert.equal(request.previous_feedback, trialCall.input.previous_feedback ?? '')
    if (expectedParent) assert(request.previous_feedback.trim(), 'Missing model analysis of previous feedback')
    assert.equal(research.trials[index].trial_id, result.trial_id)
  }
  assert(events.indexOf(final) > events.indexOf(trialResult), 'No final response after evaluation')
  assert(final.text.includes(result.trial_id), 'Final response omitted a trial ID')
  rounds.push({ round: index + 1, trial_id: result.trial_id, parent_trial_id: expectedParent,
    hypothesis: request.hypothesis, previous_feedback: request.previous_feedback ?? '',
    status: result.status, decision: result.decision ?? 'failed', error: result.error,
    candidate_sha256: hash(code), parent_sha256: hash(parent), experiment_dir: folder,
    candidate_metrics: result.candidate?.metrics, baseline_metrics: result.baseline?.metrics,
    parent_metrics: result.parent_evaluation?.candidate?.metrics })
  priorResult = trialResult
  expectedParent = result.trial_id
}
assert.equal(hash(readFileSync(join(root, 'strategies/current.py'))), manifest.parent_sha256)
assert(final.text.includes('retain_for_review') || /保留|拒绝|淘汰|失败/.test(final.text), 'Missing model decision discussion')
assert(durable.some(event => event.type === 'turn/end' && event.data.reason.kind === 'completed'))
const proof = {
  verified: true, session_id: sessionId, provider: header.config.provider, model: manifest.model,
  loaded_tools: tools, model_tool_calls: calls.map(call => call.tool),
  snapshot_id: manifest.snapshot_id, trial_id: rounds.at(-1).trial_id,
  rounds, max_rounds: manifest.max_rounds ?? 1, stop_reason: research?.stop_reason ?? 'single_round',
  best_trial_id: research?.best_trial_id ?? rounds.at(-1).trial_id,
  parent_sha256: manifest.parent_sha256, candidate_changed: true,
  evaluator_unchanged: true, current_strategy_unchanged: true,
  feedback_precedes_next_candidate_and_final: true,
  durable_session_path: sessionPath, durable_session_sha256: hash(source),
}
writeFileSync(join(run, 'proof.json'), JSON.stringify(proof, null, 2) + '\n')
writeFileSync(join(run, 'final.md'), final.text + '\n')
console.log(JSON.stringify({ verified: true, session_id: sessionId, trial_id: rounds.at(-1).trial_id, rounds: rounds.length, proof: join(run, 'proof.json') }))
