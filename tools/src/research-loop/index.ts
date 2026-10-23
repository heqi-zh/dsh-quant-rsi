import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { call, output, type Config } from '../common.js'
import { registerAnalysisTools } from '../analysis-tools.js'

export const name = 'dqr-research-loop'
export const inject = ['tools', 'shell']
export function apply(ctx: Context, config: Config = {}): void {
  registerAnalysisTools(ctx, config, 'weekly')
  ctx.tools.register(defineTool({
    name: 'screening_weekly_report',
    description: 'Read as-of weekly shortlist turnover and matured signal diagnostics. RSI means proposed program improvements; no optimization or candidate execution.',
    parameters: { replay_id: { type: 'string', required: true }, date: { type: 'string', required: true } }, output,
    async execute(args, exec) { return call(ctx, config, 'screening-report', { ...args, kind: 'weekly' }, exec) },
  }))
  ctx.tools.register(defineTool({
    name: 'operator_catalog', description: 'List actual pinned vn.py operators, signatures, sources and required inputs. OHLCV indicators cannot run on invented fund bars.',
    parameters: {}, output,
    async execute(args, exec) { return call(ctx, config, 'operators', args, exec) },
  }))
  ctx.tools.register(defineTool({
    name: 'operator_program_preview', description: 'Compose or write custom expression operators in a JSON operator program; validate and preview against past-only data. Optional save creates a draft, never promotes. No backtest or optimization.',
    parameters: {
      snapshot_id: { type: 'string', required: true }, as_of: { type: 'string', required: true },
      program_json: { type: 'string', required: true, description: 'dqr.operator-program.v1: operators {name:{parameters,expression}}, ordered features [{name,expression}], score expression, portfolio {rebalance:weekly,top_k,exposure}.' },
      save: { type: 'boolean' },
    }, output,
    async execute(args, exec) { return call(ctx, config, 'program-preview', args, exec) },
  }))
  ctx.tools.register(defineTool({
    name: 'operator_weekly_report',
    description: 'Read a saved weekly report including separately attributed model-authored operator-improvement proposals. Supports screening runs and legacy monthly replays. No candidate execution, optimization or promotion.',
    parameters: {
      replay_id: { type: 'string', required: true },
      date: { type: 'string', required: true, description: 'Recorded weekly date YYYY-MM-DD.' },
    }, output,
    async execute(args, exec) { return call(ctx, config, 'weekly-report', args, exec) },
  }))
  ctx.tools.register(defineTool({
    name: 'research_trial',
    description: 'Run the next budgeted research round: persist hypothesis, candidate and your analysis of previous feedback; invoke the fixed evaluator; compare parent/baseline; archive results. Follow research.stop_reason. Each next round MUST name the previous trial as parent and modify its code. Host enforces run/global budgets, failure/no-improvement stops. Never promotes a strategy.',
    parameters: {
      snapshot_id: { type: 'string', required: true },
      parent_trial_id: { type: 'string', description: 'Optional previous trial in the same snapshot. Omit to start from current.py.' },
      previous_feedback: { type: 'string', description: 'Required when a parent trial exists: analyze its actual metrics/error and explain how the next code change responds.' },
      hypothesis: { type: 'string', required: true, description: 'A specific testable change and expected effect.' },
      code: { type: 'string', required: true, description: 'One restricted Python strategy(history, portfolio); return target fund weights or None.' },
    }, output,
    async execute(args, exec) { return call(ctx, config, 'trial', args, exec) },
  }))
  ctx.logger.info('DQR research-loop loaded: research_trial')
}
