model_config = {
        "model": {
            "class": "GATs",
            "module_path": "qlib.contrib.model.pytorch_gats_ts",
            "kwargs": {
                "d_feat": 20,
                "hidden_size": 64,
                "num_layers": 2,
                "dropout": 0.5,
                "n_epochs": 200,
                "lr": 1e-4,
                "weight_decay": 0.001,
                "early_stop": 10,
                "metric": "loss",
                "loss": "precise_margin_ranking_w_mse",
                "lamb1_precise_margin_ranking": 0.8,
                "lamb2_precise_margin_ranking": 0.2,
                "func_precise_margin_ranking": "linear",
                "base_model": "LSTM",
                "model_path": "/home/erohar/qlib/examples/benchmarks/LSTM/csi300_lstm_ts.pkl",
                "GPU": 0,
                "tensorboard_path": "/home/erohar/qlib/tensorboard_logs",
                "print_iter": 200,
                "seed": 1234
            }
        },
        "dataset": {
            "class": "TSDatasetH",
            "module_path": "qlib.data.dataset",
            "kwargs": {
                "handler": {
                    "class": "Alpha158",
                    "module_path": "qlib.contrib.data.handler",
                    "kwargs": {
                        "start_time": "2008-01-01",
                        "end_time": "2022-12-29",
                        "fit_start_time": "2008-01-01",
                        "fit_end_time": "2014-12-31",
                        "instruments": [
                            'PNW', 'MA', 'FDX', 'BEN', 'NKE', 'CSX', 'F', 'PKI', 'PHM', 'ADSK', 'JNJ', 'LMT', 'FIS', 'ITW', 'SHW', 'ADI', 
                            'PRU', 'PFG', 'USB', 'GILD', 'LIN', 'FITB', 'UNM', 'NSC', 'HIG', 'AIZ', 'BDX', 'CMS', 'DVN', 'PEP', 'PGR', 'AMT', 
                            'CMA', 'PWR', 'K', 'BKNG', 'ABC', 'CMI', 'COST', 'UNP', 'LEG', 'TROW', 'MMM', 'GD', 'CTSH', 'CMCSA', 'FISV', 
                            'ZION', 'CL', 'HPQ', 'RF', 'CHRW', 'MAR', 'WEC', 'TPR', 'APH', 'LHX', 'CINF', 'PFE', 'JPM', 'SJM', 'HD', 'JNPR', 
                            'IRM', 'RSG', 'LLY', 'KLAC', 'GIS', 'WMB', 'AIG', 'AIV', 'NRG', 'RL', 'GPC', 'XRX', 'TMO', 'UNH', 'CF', 'EOG', 
                            'PEG', 'COF', 'STT', 'LH', 'GS', 'WMT', 'C', 'HST', 'OMC', 'PLD', 'PXD', 'ROST', 'SYK', 'OXY', 'DGX', 'AAPL', 
                            'CTAS', 'GPS', 'IPG', 'GL', 'AXP', 'HON', 'KIM', 'ROP', 'AES', 'ES', 'PSA', 'AFL', 'KMB', 'CCL', 'ORLY', 'GWW', 
                            'GE', 'EXC', 'MDT', 'SEE', 'TGT', 'TRV', 'MCHP', 'WDC', 'XOM', 'HBAN', 'APD', 'MKC', 'MS', 'HES', 'ETR', 'MMC', 
                            'VNO', 'LNC', 'NEM', 'TAP', 'BAC', 'MRO', 'PEAK', 'IFF', 'AKAM', 'ALL', 'IP', 'VMC', 'FLS', 'DHR', 'MET', 'NUE', 
                            'CNP', 'CAT', 'TXT', 'ED', 'CVX', 'SCHW', 'ETN', 'WM', 'WU', 'GOOG', 'MTB', 'SWK', 'RHI', 'KEY', 'AVB', 'GLW', 
                            'CAG', 'AEE', 'T', 'PPG', 'ORCL', 'WELL', 'AMGN', 'SPGI', 'MU', 'CBRE', 'UAA', 'WY', 'EFX', 'IVZ', 'HAL', 'OKE', 
                            'WFC', 'DUK', 'WYNN', 'WAT', 'PG', 'EA', 'NOC', 'BSX', 'NDAQ', 'LEN', 'BA', 'RTX', 'BMY', 'FMC', 'NVDA', 'WHR', 
                            'YUM', 'NEE', 'AMP', 'SO', '^GSPC', 'EIX', 'CSCO', 'VFC', 'COP', 'EMR', 'ISRG', 'ZBH', 'AEP', 'AMAT', 'AZO', 'NOV', 
                            'LOW', 'MSI', 'VRSN', 'TFC', 'INTU', 'SBUX', 'NTAP', 'DRI', 'SRE', 'DE', 'EXPE', 'PAYX', 'VLO', 'FCX', 'ROK', 'AVY', 
                            'LUV', 'PH', 'SPG', 'DFS', 'CI', 'KO', 'PNC', 'CPB', 'WBA', 'MDLZ', 'TXN', 'A', 'EMN', 'HAS', 'STZ', 'D', 'ECL', 
                            'IBM', 'QCOM', 'HUM', 'HSY', 'DIS', 'DTE', 'DOV', 'INTC', 'UPS', 'CLX', 'KR', 'PCAR', 'FE', 'BKR', 'LUMN', 'MO', 
                            'APA', 'AMZN', 'NWL', 'ADM', 'BBY', 'NI', 'TJX', 'XEL', 'DVA', 'EL', 'EQR', 'EXPD', 'XRAY', 'DHI', 'CAH', 'MRK', 
                            'MSFT', 'AON', 'BIIB', 'ICE', 'L', 'SNA', 'VZ', 'TT', 'NTRS', 'BXP', 'EBAY', 'BK', 'MAS', 'MCK', 'SLB', 'FTI', 'J', 
                            'PPL', 'SYY', 'BAX', 'MCO', 'CME', 'ABT', 'ADP', 'TSN', 'MCD', 'ADBE', 'CVS'
                        ],
                        "infer_processors": [
                            {
                                "class": "FilterCol",
                                "kwargs": {
                                    "fields_group": "feature",
                                    "col_list": ["RESI5", "WVMA5", "RSQR5", "KLEN", "RSQR10", "CORR5", "CORD5", "CORR10", "ROC60",
                                                "RESI10", "VSTD5", "RSQR60", "CORR60", "WVMA60", "STD5", "RSQR20", "CORD60", "CORD10", "CORR20",
                                                "KLOW"
                                    ]
                                }
                            },
                            {
                                "class": "RobustZScoreNorm",
                                "kwargs": {
                                    "fields_group": "feature",
                                    "clip_outlier": True
                                }
                            },
                            {
                                "class": "Fillna",
                                "kwargs": {
                                    "fields_group": "feature"
                                }
                            }
                        ],
                        "label": ['Ref($close, -2) / Ref($close, -1) - 1']
                    },
                },
                "segments": {
                    "train": ("2008-01-01", "2014-12-31"),
                    "valid": ("2015-01-01", "2016-12-31"),
                    "test": ("2017-01-01", "2022-12-29"),
                },
                "step_len": 20
            },
        },
        "record": [
            {
                "class": "SignalRecord",
                "module_path": "qlib.workflow.record_temp",
                "kwargs": {
                    "dataset": "<DATASET>",
                    "model": "<MODEL>",
                },
            },
            {
                "class": "SigAnaRecord",
                "module_path": "qlib.workflow.record_temp",
            },
        ],
    }