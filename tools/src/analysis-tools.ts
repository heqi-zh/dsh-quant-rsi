import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { call, output, type Config } from './common.js'

export function registerAnalysisTools(ctx: Context, config: Config, kind: 'daily' | 'weekly'): void {
  const prefix = kind === 'daily' ? 'daily_analysis' : 'operator_weekly'
  const parameters = { replay_id: { type: 'string' as const, required: true as const }, date: { type: 'string' as const, required: true as const } }
  ctx.tools.register(defineTool({
    name: `${prefix}_context`,
    description: 'Read as-of program-computed report evidence, actual operator expressions and operator catalogue. No future observations or full-month results. Use this before writing your own analysis.',
    parameters, output,
    async execute(args, exec) { return call(ctx, config, 'analysis-context', { ...args, kind }, exec) },
  }))
  ctx.tools.register(defineTool({
    name: `${prefix}_save`,
    description: 'Save YOUR model-authored Chinese analysis, separate from numeric results. Cite at least 3 exact scalar values via JSON pointers into the context. Weekly reports require concrete operator expressions, reasons and limitations. No optimization or deployment.',
    parameters: { ...parameters,
      analysis: { type: 'string', required: true, description: '100..12000 characters of evidence-grounded Chinese analysis; distinguish deductions from observed facts.' },
      evidence_json: { type: 'string', required: true, description: 'JSON array of {path,value}; path is a JSON pointer starting /report/; value exactly matches the returned context scalar. At least three.' },
      proposals_json: { type: 'string', description: 'Weekly required JSON array (1..5): {feature,expression,reason}. Expressions use registered or existing custom operators; all proposals remain untested. Daily may use [].' },
    }, output,
    async execute(args, exec) { return call(ctx, config, 'analysis-save', { ...args, kind }, exec) },
  }))
}
