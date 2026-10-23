import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { call, output, type Config } from '../common.js'

export const name = 'dqr-strategy-eval'
export const inject = ['tools', 'shell']
export function apply(ctx: Context, config: Config = {}): void {
  ctx.tools.register(defineTool({
    name: 'screening_evaluation', description: 'Read completed-month category-relative 1/5-session gross NAV signal diagnostics for the fixed screening program. Not portfolio P&L. Forbidden inside isolated as-of report jobs; no search or promotion.',
    parameters: { replay_id: { type: 'string', required: true } }, output,
    async execute(args, exec) { return call(ctx, config, 'screening-evaluation', args, exec) },
  }))
  ctx.tools.register(defineTool({
    name: 'operator_program_evaluate', description: 'Independently evaluate an explicit operator program for a full month using fixed fund execution rules and same-exposure baseline; save all reports and archive via OpenEvolve. No automatic promotion. Disabled in isolated report-only jobs.',
    parameters: { snapshot_id: { type: 'string', required: true }, month: { type: 'string', required: true }, program_json: { type: 'string', required: true } }, output,
    async execute(args, exec) { return call(ctx, config, 'program-evaluate', args, exec) },
  }))
  ctx.tools.register(defineTool({
    name: 'month_evaluation',
    description: 'Read the fixed operator-program monthly evaluation and equal-initial-exposure baseline. A single month is workflow verification, not evidence of optimization. Does not run candidate search or consume its budget.',
    parameters: { replay_id: { type: 'string', required: true } }, output,
    async execute(args, exec) { return call(ctx, config, 'month-evaluation', args, exec) },
  }))
  ctx.tools.register(defineTool({
    name: 'strategy_evaluate',
    description: 'Evaluate and archive a candidate against fixed OTC simulation rules and a buy-and-hold baseline. Consumes the shared research budget, including failed candidates. Cannot change evaluator or promote a strategy.',
    parameters: {
      snapshot_id: { type: 'string', required: true },
      parent_trial_id: { type: 'string' },
      previous_feedback: { type: 'string', description: 'Analysis of the previous trial; required for parent-linked rounds.' },
      code: { type: 'string', required: true, description: 'One pure def strategy(history, portfolio). No imports, attributes, file/network access or arbitrary function calls. Return weights or None.' },
      hypothesis: { type: 'string', required: true },
    }, output,
    async execute(args, exec) { return call(ctx, config, 'evaluate', args, exec) },
  }))
  ctx.logger.info('DQR strategy-eval loaded: strategy_evaluate')
}
