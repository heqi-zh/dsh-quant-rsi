# vn.py 算子目录

接入 86 个具名接口，源版本 `c6e231caf32b7fc97e6459817fff66458cf7e7c4`。Alpha 为 38 个函数；ArrayManager 的 41 个指标拆出 48 个具名接口，多输出指标不重复计作不同原始指标。

所有函数调用实际内置的 vn.py 实现。Alpha 文件保持原样，ArrayManager 类原样提取，来源与哈希见 `runtime/dqr/vendor/vnpy/provenance.json`。

## 输入和组合

基金输入字段为 `nav`、`dividend`、`return_1`、`total_return_index`。需要价格序列的函数显式传 `total_return_index`；不创建虚假的 OHLCV。`am_*` 所列 close 是函数参数，不是默认会从净值假造的字段。

算子通过函数调用、算术和比较组合；程序可定义带参数的表达式函数，例如 `momentum(series,n) = series / ts_delay(series,n) - 1`。随后以有序具名因子复用，评分再引用因子。

保留上游窗口、缺失值及秩的语义；不同函数的预热行为可能不同。特征非有限值归为空，完全无有效评分时持现金。技术分析 ta_rsi 与 Recursive Self-Improvement 无关。

| 接口 | 调用签名 | 输入适用性 | 源码 |
|---|---|---|---|
| `abs` | `(feature: dqr.vendor.vnpy.utility.DataProxy) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/math_function.py` |
| `am_ad` | `(close, high, low, volume)` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.ad` |
| `am_adosc` | `(close, high, low, volume, fast_period: 'int', slow_period: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.adosc` |
| `am_adx` | `(close, high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.adx` |
| `am_adxr` | `(close, high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.adxr` |
| `am_apo` | `(close, fast_period: 'int', slow_period: 'int', matype: 'int' = 0)` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.apo` |
| `am_aroon_down` | `(high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.aroon` |
| `am_aroon_up` | `(high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.aroon` |
| `am_aroonosc` | `(high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.aroonosc` |
| `am_atr` | `(close, high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.atr` |
| `am_boll_lower` | `(close, n: 'int', dev: 'float')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.boll` |
| `am_boll_upper` | `(close, n: 'int', dev: 'float')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.boll` |
| `am_bop` | `(close, high, low, open)` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.bop` |
| `am_cci` | `(close, high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.cci` |
| `am_cmo` | `(close, n: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.cmo` |
| `am_donchian_lower` | `(high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.donchian` |
| `am_donchian_upper` | `(high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.donchian` |
| `am_dx` | `(close, high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.dx` |
| `am_ema` | `(close, n: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.ema` |
| `am_kama` | `(close, n: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.kama` |
| `am_keltner_lower` | `(close, high, low, n: 'int', dev: 'float')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.keltner` |
| `am_keltner_upper` | `(close, high, low, n: 'int', dev: 'float')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.keltner` |
| `am_macd_hist` | `(close, fast_period: 'int', slow_period: 'int', signal_period: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.macd` |
| `am_macd_line` | `(close, fast_period: 'int', slow_period: 'int', signal_period: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.macd` |
| `am_macd_signal` | `(close, fast_period: 'int', slow_period: 'int', signal_period: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.macd` |
| `am_mfi` | `(close, high, low, volume, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.mfi` |
| `am_minus_di` | `(close, high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.minus_di` |
| `am_minus_dm` | `(high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.minus_dm` |
| `am_mom` | `(close, n: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.mom` |
| `am_natr` | `(close, high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.natr` |
| `am_obv` | `(close, volume)` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.obv` |
| `am_plus_di` | `(close, high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.plus_di` |
| `am_plus_dm` | `(high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.plus_dm` |
| `am_ppo` | `(close, fast_period: 'int', slow_period: 'int', matype: 'int' = 0)` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.ppo` |
| `am_roc` | `(close, n: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.roc` |
| `am_rocp` | `(close, n: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.rocp` |
| `am_rocr` | `(close, n: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.rocr` |
| `am_rocr_100` | `(close, n: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.rocr_100` |
| `am_rsi` | `(close, n: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.rsi` |
| `am_sar` | `(high, low, acceleration: 'float', maximum: 'float')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.sar` |
| `am_sma` | `(close, n: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.sma` |
| `am_std` | `(close, n: 'int', nbdev: 'int' = 1)` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.std` |
| `am_stoch_d` | `(close, high, low, fastk_period: 'int', slowk_period: 'int', slowk_matype: 'int', slowd_period: 'int', slowd_matype: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.stoch` |
| `am_stoch_k` | `(close, high, low, fastk_period: 'int', slowk_period: 'int', slowk_matype: 'int', slowd_period: 'int', slowd_matype: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.stoch` |
| `am_trange` | `(close, high, low)` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.trange` |
| `am_trix` | `(close, n: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.trix` |
| `am_ultosc` | `(close, high, low, time_period1: 'int' = 7, time_period2: 'int' = 14, time_period3: 'int' = 28)` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.ultosc` |
| `am_willr` | `(close, high, low, n: 'int')` | requires real OHLC/volume inputs | `vnpy/trader/utility.py:ArrayManager.willr` |
| `am_wma` | `(close, n: 'int')` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/trader/utility.py:ArrayManager.wma` |
| `cs_mean` | `(feature: dqr.vendor.vnpy.utility.DataProxy) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/cs_function.py` |
| `cs_rank` | `(feature: dqr.vendor.vnpy.utility.DataProxy) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/cs_function.py` |
| `cs_scale` | `(feature: dqr.vendor.vnpy.utility.DataProxy) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/cs_function.py` |
| `cs_std` | `(feature: dqr.vendor.vnpy.utility.DataProxy) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/cs_function.py` |
| `cs_sum` | `(feature: dqr.vendor.vnpy.utility.DataProxy) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/cs_function.py` |
| `greater` | `(feature1: dqr.vendor.vnpy.utility.DataProxy, feature2: dqr.vendor.vnpy.utility.DataProxy &#124; float) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/math_function.py` |
| `less` | `(feature1: dqr.vendor.vnpy.utility.DataProxy, feature2: dqr.vendor.vnpy.utility.DataProxy &#124; float) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/math_function.py` |
| `log` | `(feature: dqr.vendor.vnpy.utility.DataProxy) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/math_function.py` |
| `pow1` | `(base: dqr.vendor.vnpy.utility.DataProxy, exponent: float) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/math_function.py` |
| `pow2` | `(base: dqr.vendor.vnpy.utility.DataProxy, exponent: dqr.vendor.vnpy.utility.DataProxy) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/math_function.py` |
| `quesval` | `(threshold: float, feature1: dqr.vendor.vnpy.utility.DataProxy, feature2: dqr.vendor.vnpy.utility.DataProxy &#124; float &#124; int, feature3: dqr.vendor.vnpy.utility.DataProxy &#124; float &#124; int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/math_function.py` |
| `quesval2` | `(threshold: dqr.vendor.vnpy.utility.DataProxy, feature1: dqr.vendor.vnpy.utility.DataProxy, feature2: dqr.vendor.vnpy.utility.DataProxy &#124; float &#124; int, feature3: dqr.vendor.vnpy.utility.DataProxy &#124; float &#124; int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/math_function.py` |
| `sign` | `(feature: dqr.vendor.vnpy.utility.DataProxy) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/math_function.py` |
| `ta_atr` | `(high: dqr.vendor.vnpy.utility.DataProxy, low: dqr.vendor.vnpy.utility.DataProxy, close: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | requires real OHLC/volume inputs | `vnpy/alpha/dataset/ta_function.py` |
| `ta_rsi` | `(close: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ta_function.py` |
| `ts_abs` | `(feature: dqr.vendor.vnpy.utility.DataProxy) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_argmax` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_argmin` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_corr` | `(feature1: dqr.vendor.vnpy.utility.DataProxy, feature2: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_cov` | `(feature1: dqr.vendor.vnpy.utility.DataProxy, feature2: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_decay_linear` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_delay` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_delta` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_greater` | `(feature1: dqr.vendor.vnpy.utility.DataProxy, feature2: dqr.vendor.vnpy.utility.DataProxy &#124; float) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_less` | `(feature1: dqr.vendor.vnpy.utility.DataProxy, feature2: dqr.vendor.vnpy.utility.DataProxy &#124; float) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_log` | `(feature: dqr.vendor.vnpy.utility.DataProxy) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_max` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_mean` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_min` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_product` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_quantile` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int, quantile: float) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_rank` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_resi` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_rsquare` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_slope` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_std` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |
| `ts_sum` | `(feature: dqr.vendor.vnpy.utility.DataProxy, window: int) -> dqr.vendor.vnpy.utility.DataProxy` | usable with NAV-derived series; pass total_return_index explicitly for close | `vnpy/alpha/dataset/ts_function.py` |

## 验证

测试逐一执行全部 86 个接口，在多标的 OHLCV 合成数据上检查输出形状和前缀因果性；另外对均值、排名、RSI、MACD、现金分红适配做独立数值检查。完整模拟中使用真实基金快照，不将合成 OHLCV 测试当作基金数据。

常用逻辑示例见 `strategies/operators-current.json`；`operator_catalog` 可供 Agent 查询同一目录，`operator_program_preview` 支持编写组合/自定义表达式并查看过去时点输出。
