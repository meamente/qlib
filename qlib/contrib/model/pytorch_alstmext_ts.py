# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.


from __future__ import division
from __future__ import print_function


import numpy as np
import pandas as pd
from typing import Text, Union
import copy
from ...utils import get_or_create_path
from ...log import get_module_logger, get_tensorboard_logger

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from os.path import join
from datetime import datetime
from copy import deepcopy

from .pytorch_utils import count_parameters
from ...model.base import Model
from ...data.dataset import DatasetH
from ...data.dataset.handler import DataHandlerLP
from ...model.utils import ConcatDataset
from ...data.dataset.weight import Reweighter


from qlib.contrib.model.pytorch_gats_ts import DailyBatchSampler # added by Ashot

# added by Ashot
def create_loader_gat(dl_old):
    sampler = DailyBatchSampler(dl_old)
    loader = DataLoader(dl_old,
                        sampler=sampler, 
                        num_workers=2, 
                        drop_last=False)
    return loader

# added by Ashot
def create_dl_new(loader):
    i = 0
    lst = []
    for data in loader:
        i += 1
        d0 = data.size(0) # 1
        d1 = data.size(1) # 4, number of stock
        d2 = data.size(2) # 30, step_len
        d3 = data.size(3) # 21, number of variables
        
        data1 = data.transpose(1, 2) # from 1x4x30x21 to 1x30x4x21 
        data2 = torch.reshape(data1, (d0, d2, d1*d3)) # 1x30x84
        lst.append(data2)
    
    data_out = torch.stack(lst)
    return data_out.squeeze()


class ALSTM(Model):
    """ALSTM Model

    Parameters
    ----------
    d_feat : int
        input dimension for each time step
    metric: str
        the evaluation metric used in early stop
    optimizer : str
        optimizer name
    GPU : int
        the GPU ID used for training
    """

    def __init__(
        self,
        d_feat=6,
        hidden_size=64,
        num_layers=2,
        dropout=0.0,
        n_epochs=200,
        lr=0.001,
        metric="",
        batch_size=2000,
        early_stop=20,
        loss="mse",
        optimizer="adam",
        n_jobs=10,
        GPU=0,
        tensorboard_path="",
        print_iter=50,
        seed=None,
        **kwargs
    ):
        # Set logger.
        self.logger = get_module_logger("ALSTM")
        self.logger.info("ALSTM pytorch version...")

        # set hyper-parameters.
        self.d_feat = d_feat
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.n_epochs = n_epochs
        self.lr = lr
        self.metric = metric
        self.batch_size = batch_size
        self.early_stop = early_stop
        self.optimizer = optimizer.lower()
        self.loss = loss
        self.device = torch.device("cuda:%d" % (GPU) if torch.cuda.is_available() and GPU >= 0 else "cpu")
        self.n_jobs = n_jobs
        self.seed = seed
        self.tensorboard_path = tensorboard_path
        self.print_iter = print_iter

        self.logger.info(
            "ALSTM parameters setting:"
            "\nd_feat : {}"
            "\nhidden_size : {}"
            "\nnum_layers : {}"
            "\ndropout : {}"
            "\nn_epochs : {}"
            "\nlr : {}"
            "\nmetric : {}"
            "\nbatch_size : {}"
            "\nearly_stop : {}"
            "\noptimizer : {}"
            "\nloss_type : {}"
            "\ndevice : {}"
            "\nn_jobs : {}"
            "\nuse_GPU : {}"
            "\nseed : {}".format(
                d_feat,
                hidden_size,
                num_layers,
                dropout,
                n_epochs,
                lr,
                metric,
                batch_size,
                early_stop,
                optimizer.lower(),
                loss,
                self.device,
                n_jobs,
                self.use_gpu,
                seed,
            )
        )

        if self.seed is not None:
            np.random.seed(self.seed)
            torch.manual_seed(self.seed)

        self.ALSTM_model = ALSTMModel(
            d_feat=self.d_feat,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout,
        )
        self.logger.info("model:\n{:}".format(self.ALSTM_model))
        self.logger.info("model size: {:.4f} MB".format(count_parameters(self.ALSTM_model)))

        if optimizer.lower() == "adam":
            self.train_optimizer = optim.Adam(self.ALSTM_model.parameters(), lr=self.lr)
        elif optimizer.lower() == "gd":
            self.train_optimizer = optim.SGD(self.ALSTM_model.parameters(), lr=self.lr)
        else:
            raise NotImplementedError("optimizer {} is not supported!".format(optimizer))

        self.fitted = False
        self.ALSTM_model.to(self.device)

    @property
    def use_gpu(self):
        return self.device != torch.device("cpu")

    def mse(self, pred, label, weight):
        loss = weight * (pred - label) ** 2
        return torch.mean(loss)

    def loss_fn(self, pred, label, weight=None):
        mask = ~torch.isnan(label)

        if weight is None:
            weight = torch.ones_like(label)
        
        if self.loss == "mse":
            return self.mse(pred[mask], label[mask], weight[mask])

        raise ValueError("unknown loss `%s`" % self.loss)

    def metric_fn(self, pred, label):

        mask = torch.isfinite(label)

        if self.metric in ("", "loss"):
            return -self.loss_fn(pred[mask], label[mask])

        raise ValueError("unknown metric `%s`" % self.metric)

    def train_epoch(self, data_loader, train_loader, val_loader, epoch=0, split='train', writer=None):

        self.ALSTM_model.train()

        for batch_id, (data, weight) in enumerate(data_loader):
            # added by Ashot
            
            number_of_var = 21
            d = data.size(2)

            all_idx = list(range(d))
            target_lst = list(range(number_of_var, d+1, number_of_var))
            target_idx = [entry - 1 for entry in target_lst]
            feat_idx = [entry for entry in all_idx if entry not in target_idx]

            feature = data[:, :, feat_idx].to(self.device)
            label = data[:, -1, target_idx].to(self.device)
            
            # feature = data[:, :, 0:-1].to(self.device)
            # label = data[:, -1, -1].to(self.device)

            pred = self.ALSTM_model(feature.float())
            loss = self.loss_fn(pred, label, weight.to(self.device))

            self.train_optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_value_(self.ALSTM_model.parameters(), 3.0)
            self.train_optimizer.step()
            if batch_id % self.print_iter == 0 and writer:
                train_loss, train_score = self.test_epoch(train_loader)
                val_loss, val_score = self.test_epoch(val_loader)
                writer.add_scalars(f'Loss', {'train': train_loss, 'val': val_loss}, (len(data_loader) * epoch + batch_id) * self.batch_size)


    def test_epoch(self, data_loader):

        self.ALSTM_model.eval()

        scores = []
        losses = []

        for (data, weight) in data_loader:
            # added by Ashot
            number_of_var = 21
            d = data.size(2)

            all_idx = list(range(d))
            target_lst = list(range(number_of_var, d+1, number_of_var))
            target_idx = [entry - 1 for entry in target_lst]
            feat_idx = [entry for entry in all_idx if entry not in target_idx] 

            feature = data[:, :, feat_idx].to(self.device)
            label = data[:, -1, target_idx].to(self.device)
                        
            # feature = data[:, :, 0:-1].to(self.device)
            # # feature[torch.isnan(feature)] = 0
            # label = data[:, -1, -1].to(self.device)

            with torch.no_grad():
                pred = self.ALSTM_model(feature.float())
                loss = self.loss_fn(pred, label, weight.to(self.device))
                losses.append(loss.item())

                score = self.metric_fn(pred, label)
                scores.append(score.item())
        
        self.ALSTM_model.train()
        return np.mean(losses), np.mean(scores)

    def fit(
        self,
        dataset,
        evals_result=dict(),
        save_path=None,
        reweighter=None,
    ):
        dl_train = dataset.prepare("train", col_set=["feature", "label"], data_key=DataHandlerLP.DK_L)
        dl_valid = dataset.prepare("valid", col_set=["feature", "label"], data_key=DataHandlerLP.DK_L)
        if dl_train.empty or dl_valid.empty:
            raise ValueError("Empty data from dataset, please check your dataset config.")

        dl_train.config(fillna_type="ffill+bfill")  # process nan brought by dataloader
        dl_valid.config(fillna_type="ffill+bfill")  # process nan brought by dataloader
        
        new_loader_train = create_loader_gat(dl_train) # added by Ashot
        dl_train = create_dl_new(new_loader_train) # added by Ashot
        
        new_loader_valid = create_loader_gat(dl_valid) # added by Ashot
        dl_valid = create_dl_new(new_loader_valid) # added by Ashot
        
        if reweighter is None:
            wl_train = np.ones((len(dl_train), 300)) # modified by Ashot, 300 is the number of stocks
            wl_valid = np.ones((len(dl_valid), 300)) # modified by Ashot, 300 is the number of stocks
        elif isinstance(reweighter, Reweighter):
            wl_train = reweighter.reweight(dl_train)
            wl_valid = reweighter.reweight(dl_valid)
        else:
            raise ValueError("Unsupported reweighter type.")
        
        train_loader = DataLoader(
            ConcatDataset(dl_train, wl_train),
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=self.n_jobs,
            drop_last=True,
        )
        valid_loader = DataLoader(
            ConcatDataset(dl_valid, wl_valid),
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.n_jobs,
            drop_last=True,
        )

        save_path = get_or_create_path(save_path)
        current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        tboard_writer = get_tensorboard_logger(save_path=join(self.tensorboard_path, f"ALSTMEXT_{current_time}"))
        stop_steps = 0
        train_loss = 0
        best_score = -np.inf
        best_epoch = 0
        evals_result["train"] = []
        evals_result["valid"] = []

        # train
        self.logger.info("training...")
        self.fitted = True

        for step in range(self.n_epochs):
            self.logger.info("Epoch%d:", step)
            self.logger.info("training...")
            self.train_epoch(train_loader, deepcopy(train_loader), valid_loader, epoch=step, split='train', writer=tboard_writer)
            self.logger.info("evaluating...")
            train_loss, train_score = self.test_epoch(train_loader)
            val_loss, val_score = self.test_epoch(valid_loader)
            self.logger.info("train %.6f, valid %.6f" % (train_score, val_score))
            evals_result["train"].append(train_score)
            evals_result["valid"].append(val_score)

            if val_score > best_score:
                best_score = val_score
                stop_steps = 0
                best_epoch = step
                best_param = copy.deepcopy(self.ALSTM_model.state_dict())
            else:
                stop_steps += 1
                if stop_steps >= self.early_stop:
                    self.logger.info("early stop")
                    break

        self.logger.info("best score: %.6lf @ %d" % (best_score, best_epoch))
        self.ALSTM_model.load_state_dict(best_param)
        torch.save(best_param, save_path)

        if self.use_gpu:
            torch.cuda.empty_cache()

    def predict(self, dataset: DatasetH, segment: Union[Text, slice] = "test"):
        if not self.fitted:
            raise ValueError("model is not fitted yet!")

        dl_test = dataset.prepare(segment, col_set=["feature", "label"], data_key=DataHandlerLP.DK_I)
        dl_test.config(fillna_type="ffill+bfill")
        
        new_loader_test = create_loader_gat(dl_test) # added by Ashot
        dl_test_new = create_dl_new(new_loader_test) # added by Ashot
        
        test_loader = DataLoader(dl_test_new, batch_size=self.batch_size, num_workers=self.n_jobs)
        self.ALSTM_model.eval()
        preds = []

        for data in test_loader:
            # added by Ashot
            number_of_var = 21
            d = data.size(2)

            all_idx = list(range(d))
            target_lst = list(range(number_of_var, d+1, number_of_var))
            target_idx = [entry - 1 for entry in target_lst]
            feat_idx = [entry for entry in all_idx if entry not in target_idx] 

            feature = data[:, :, feat_idx].to(self.device)
            label = data[:, -1, target_idx].to(self.device)

            # feature = data[:, :, 0:-1].to(self.device)

            with torch.no_grad():
                pred = self.ALSTM_model(feature.float()).detach().cpu().numpy()
                pred_reshaped = pred.transpose(1, 0).flatten() # added by Ashot
            preds.append(pred_reshaped)

        return pd.Series(np.concatenate(preds), index=dl_test.get_index())


class ALSTMModel(nn.Module):
    def __init__(self, d_feat=6, hidden_size=64, num_layers=2, dropout=0.0, rnn_type="GRU", output_size=300):
        super().__init__()
        self.hid_size = hidden_size
        self.input_size = d_feat
        self.output_size = output_size # modified by Ashot
        self.dropout = dropout
        self.rnn_type = rnn_type
        self.rnn_layer = num_layers
        self._build_model()

    def _build_model(self):
        try:
            klass = getattr(nn, self.rnn_type.upper())
        except Exception as e:
            raise ValueError("unknown rnn_type `%s`" % self.rnn_type) from e
        self.net = nn.Sequential()
        self.net.add_module("fc_in", nn.Linear(in_features=self.input_size, out_features=self.hid_size))
        self.net.add_module("act", nn.Tanh())
        self.rnn = klass(
            input_size=self.hid_size,
            hidden_size=self.hid_size,
            num_layers=self.rnn_layer,
            batch_first=True,
            dropout=self.dropout,
        )
        self.fc_out = nn.Linear(in_features=self.hid_size * 2, out_features=self.output_size) # modified by Ashot
        self.att_net = nn.Sequential()
        self.att_net.add_module(
            "att_fc_in",
            nn.Linear(in_features=self.hid_size, out_features=int(self.hid_size / 2)),
        )
        self.att_net.add_module("att_dropout", torch.nn.Dropout(self.dropout))
        self.att_net.add_module("att_act", nn.Tanh())
        self.att_net.add_module(
            "att_fc_out",
            nn.Linear(in_features=int(self.hid_size / 2), out_features=1, bias=False),
        )
        self.att_net.add_module("att_softmax", nn.Softmax(dim=1))

    def forward(self, inputs):
        rnn_out, _ = self.rnn(self.net(inputs))  # [batch, seq_len, num_directions * hidden_size]
        attention_score = self.att_net(rnn_out)  # [batch, seq_len, 1]
        out_att = torch.mul(rnn_out, attention_score)
        out_att = torch.sum(out_att, dim=1)
        out = self.fc_out(
            torch.cat((rnn_out[:, -1, :], out_att), dim=1)
        )  # [batch, seq_len, num_directions * hidden_size] -> [batch, 1]
        return out # out[..., 0]
