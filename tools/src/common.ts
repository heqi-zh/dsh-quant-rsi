import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-shell'
import type {} from '@deepseek-ai/dsh-tools'

export interface Config { root?: string; dataDir?: string; python?: string }

// Commands and requests travel separately. No model text is inserted into shell code.
const quote = (value: string): string => "'" + value.replaceAll("'", "'\\''") + "'"
export const output = {
  schema: { type: 'json' as const },
  render: (_args: unknown, value: unknown) => [{ type: 'text' as const, text: JSON.stringify(value) }],
}

/** Full curves/fills remain on disk; the model receives the evaluation evidence it needs. */
function modelView(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(modelView)
  if (value === null || typeof value !== 'object') return value
  const result: Record<string, unknown> = {}
  for (const [key, member] of Object.entries(value)) {
    if (key === 'curve' || key === 'fills' || key === 'lots') continue
    result[key] = modelView(member)
  }
  return result
}

export async function call(ctx: Context, config: Config, operation: string, request: unknown,
  exec: { signal: AbortSignal; agent?: { session: unknown } }) {
  if (process.env.DQR_REPORT_JOB) {
    const job = JSON.parse(process.env.DQR_REPORT_JOB)
    const args = request as Record<string, unknown>
    if (!['analysis-context', 'analysis-save'].includes(operation) || ['replay_id', 'kind', 'date'].some(k => args[k] !== job[k])) {
      throw new Error('Isolated as-of report job cannot access other dates, evaluate candidates, or modify programs')
    }
  }
  if (process.env.DQR_REPORT_ONLY === '1' && !['month', 'weekly-report', 'month-evaluation'].includes(operation)) {
    throw new Error('Monthly report-only mode permits replay and saved reports only; candidate search is disabled')
  }
  const root = resolve(config.root ?? resolve(dirname(fileURLToPath(import.meta.url)), '../..'))
  const command = [config.python ?? resolve(root, '.venv/bin/python'), resolve(root, 'scripts/dqr.py'), operation, '--root', root]
  if (config.dataDir) command.push('--data-dir', resolve(config.dataDir))
  // Preserve the calling session's authority when using a confining shell executor.
  const service = ctx.get('sandboxPolicy') as unknown as {
    resolve(input: { session?: unknown }): Parameters<typeof ctx.shell.resolve>[0]['sandboxPolicy']
  } | undefined
  if (ctx.shell.sandboxMode !== undefined && !service) throw new Error('Confining shell requires sandboxPolicy service')
  const policy = service?.resolve(exec.agent ? { session: exec.agent.session } : {})
  const handle = await ctx.shell.execute(ctx.shell.resolve({
    command: command.map(quote).join(' '), workdir: root,
    stdin: JSON.stringify({ ...request as object, ...(process.env.DQR_RESEARCH_RUN_ID ? { research_run_id: process.env.DQR_RESEARCH_RUN_ID } : {}) }),
    timeoutMs: operation === 'snapshot' ? 180_000 : 90_000,
    stdoutMaxBytes: 8 * 1024 * 1024, signal: exec.signal,
    ...(policy ? { sandboxPolicy: policy } : {}),
  }))
  const result = await handle.result()
  if (result.exitCode !== 0 || result.timedOut || result.aborted) {
    throw new Error(`DQR ${operation} failed: ${result.stdout.text.slice(-2000)} ${result.stderr.text.slice(-1000)}`)
  }
  return modelView(JSON.parse(result.stdout.text)) as ReturnType<typeof JSON.parse>
}
