import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { call, output, type Config } from '../common.js'
import { registerAnalysisTools } from '../analysis-tools.js'

export const name = 'dqr-fund-analysis'
export const inject = ['tools', 'shell']
export function apply(ctx: Context, config: Config = {}): void {
  registerAnalysisTools(ctx, config, 'daily')
  ctx.tools.register(defineTool({
    name: 'fund_screening_report',
    description: 'Read a saved multi-theme fund daily shortlist with category-relative vn.py operator values and interactive chart data. No holdings, no orders. Use daily_analysis_context/save for model interpretation.',
    parameters: { replay_id: { type: 'string', required: true }, date: { type: 'string', required: true } }, output,
    async execute(args, exec) { return call(ctx, config, 'screening-report', { ...args, kind: 'daily' }, exec) },
  }))
  ctx.tools.register(defineTool({
    name: 'fund_month_replay',
    description: 'Replay one full historical calendar month from an existing snapshot. Save daily morning reports and weekly operator proposals. Uses a fixed momentum/volatility operator program; no optimization, no promotion, no live account. Defaults to the month before the latest common NAV month.',
    parameters: {
      snapshot_id: { type: 'string', required: true },
      month: { type: 'string', description: 'YYYY-MM; optional complete historical month.' },
    }, output,
    async execute(args, exec) { return call(ctx, config, 'month', args, exec) },
  }))
  ctx.tools.register(defineTool({
    name: 'fund_snapshot',
    description: 'LEGACY two-fund simulator snapshot. For the multi-theme fund shortlist use the host prepare-product.py dataset and fund_daily or fund_screening_report. No account connection.',
    parameters: {}, output,
    async execute(args, exec) { return call(ctx, config, 'snapshot', args, exec) },
  }))
  ctx.tools.register(defineTool({
    name: 'fund_daily',
    description: 'Default: read the prepared multi-theme fund daily shortlist, interactive chart data, named operator values and model analysis. Defaults to last recorded report, explicitly dated; not live data. Optional snapshot_id selects the legacy two-fund simulation instead. No orders.',
    parameters: { replay_id: { type: 'string' }, snapshot_id: { type: 'string', description: 'Legacy simulator only; omit for multi-theme fund screening.' }, as_of: { type: 'string', description: 'Recorded report date YYYY-MM-DD. Default last report in latest screening run.' } }, output,
    async execute(args, exec) { return call(ctx, config, 'daily', args, exec) },
  }))
  ctx.logger.info('DQR fund-analysis loaded: fund_snapshot, fund_daily')
}
