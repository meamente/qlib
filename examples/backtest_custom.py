import numpy as np
import qlib
from qlib.utils.time import Freq
from qlib.backtest import backtest, executor
from qlib.contrib.strategy import TopkDropoutRiskAdjustedStrategy

# init qlib
qlib.init(provider_uri='~/.qlib/qlib_data/my_data/sp500_components')

BENCH = "^GSPC"
# Benchmark is for calculating the excess return of your strategy.
# Its data format will be like **ONE normal instrument**.
# For example, you can query its data with the code below
# `D.features(["SH000300"], ["$close"], start_time='2010-01-01', end_time='2017-12-31', freq='day')`
# It is different from the argument `market`, which indicates a universe of stocks (e.g. **A SET** of stocks like csi300)
# For example, you can query all data from a stock market with the code below.
# ` D.features(D.instruments(market='csi300'), ["$close"], start_time='2010-01-01', end_time='2017-12-31', freq='day')`
pred_score = np.load('test_gats/decay_001/1/69bdd9a5a84c48e3a1852e76809315e1/artifacts/pred.pkl', allow_pickle=True)

FREQ = "day"
STRATEGY_CONFIG = {
    "topk": 50,
    "n_drop": 5,
    "riskmodel_path": "/home/erohar/qlib/examples/portfolio/riskdata",
    # pred_score, pd.Series
    "signal": pred_score,
}

EXECUTOR_CONFIG = {
    "time_per_step": "day",
    "generate_portfolio_metrics": True,
}

backtest_config = {
    "start_time": "2017-01-01",
    "end_time": "2022-12-29",
    "account": 100000000,
    "benchmark": BENCH,
    "exchange_kwargs": {
        "freq": FREQ,
        "limit_threshold": 0.095,
        "deal_price": "close",
        "open_cost": 0.0005,
        "close_cost": 0.0015,
        "min_cost": 5,
    },
}

# strategy object
strategy_obj = TopkDropoutRiskAdjustedStrategy(**STRATEGY_CONFIG)
# executor object
executor_obj = executor.SimulatorExecutor(**EXECUTOR_CONFIG)
# backtest
portfolio_metric_dict, indicator_dict = backtest(executor=executor_obj, strategy=strategy_obj, **backtest_config)
analysis_freq = "{0}{1}".format(*Freq.parse(FREQ))
# backtest info
report_normal, positions_normal = portfolio_metric_dict.get(analysis_freq)

report_normal.to_csv('risk_adjusted_top50_5.csv')
print(report_normal)