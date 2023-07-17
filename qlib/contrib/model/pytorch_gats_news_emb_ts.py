# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.


from __future__ import division
from __future__ import print_function

import numpy as np
import pandas as pd
import random # used for setting the seed
from ...utils import get_or_create_path
from ...log import get_module_logger, get_tensorboard_logger
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import DataLoader
from torch.utils.data import Sampler

from os.path import join
from datetime import datetime
from copy import deepcopy

from .pytorch_utils import count_parameters
from ...model.base import Model
from ...data.dataset.handler import DataHandlerLP
from ...contrib.model.pytorch_lstm import LSTMModel
from ...contrib.model.pytorch_gru import GRUModel

# to ensure the results are reproducible
# def set_seed(seed):
#     torch.manual_seed(seed)
#     torch.cuda.manual_seed(seed)
#     torch.cuda.manual_seed_all(seed)
#     np.random.seed(seed)
#     random.seed(seed)
#     torch.backends.cudnn.benchmark = False
#     torch.backends.cudnn.deterministic = True

# set_seed(seed=12345)

class DailyBatchSampler(Sampler):
    def __init__(self, data_source):
        self.data_source = data_source
        # calculate number of samples in each batch
        self.day_count = pd.Series(index=self.data_source.get_index()).groupby("instrument").size().values[0]
        self.stock_count = pd.Series(index=self.data_source.get_index()).groupby("datetime").size().values
        self.daily_index = np.arange(0, self.day_count)#np.roll(np.cumsum(self.daily_count), 1)  # calculate begin index of each batch
        #self.daily_index[0] = 0

    def __iter__(self):

        for idx, count in zip(self.daily_index, self.stock_count):
            yield np.arange(idx, count * self.day_count, step=self.day_count)

    def __len__(self):
        return len(self.data_source)

# replicates CSRankNorm
def rank(tens, GPU=0):
    device = torch.device("cuda:%d" % (GPU) if torch.cuda.is_available() and GPU >= 0 else "cpu")
    
    tens = tens.squeeze()
    
    ranks = torch.zeros(tens.size(0)).to(device)
    count = torch.linspace(1, tens.size(0), tens.size(0)).to(device)
    
    idx = torch.argsort(tens)
    ranks[idx] = torch.div(count, tens.size(0))
    ranks = (ranks - 0.5) * 3.46

    ranks = ranks.unsqueeze(dim=1)
    ranks = ranks.unsqueeze(dim=2)
    return ranks

def gradient_norm(model):
    total_norm = 0
    for p in model.parameters():
        param_norm = p.grad.detach().data.norm(2)
        total_norm += param_norm.item() ** 2
    total_norm = total_norm ** 0.5   
    return total_norm


class GATs(Model):
    """GATs Model

    Parameters
    ----------
    lr : float
        learning rate
    d_feat : int
        input dimensions for each time step
    metric : str
        the evaluation metric used in early stop
    optimizer : str
        optimizer name
    GPU : int
        the GPU ID used for training
    """

    def __init__(
        self,
        d_feat=20,
        hidden_size=64,
        num_layers=2,
        dropout=0.0,
        n_epochs=200,
        lr=0.001,
        weight_decay=0, # added by Ashot
        metric="",
        early_stop=20,
        loss="mse",
        lamb1_precise_margin_ranking=0.8, # on SSE
        lamb2_precise_margin_ranking=0.2, # on PMRL
        rand_perm_n=1,
        func_precise_margin_ranking="linear", # "cubic"
        base_model="GRU",
        model_path=None,
        optimizer="adam",
        GPU=0,
        n_jobs=10,
        tensorboard_path="",
        print_iter=50,
        seed=None,
        **kwargs
    ):
        # Set logger.
        self.logger = get_module_logger("GATs")
        self.logger.info("GATs pytorch version...")

        # set hyper-parameters.
        self.d_feat = d_feat
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.n_epochs = n_epochs
        self.lr = lr
        self.weight_decay = weight_decay # added by Ashot
        self.metric = metric
        self.early_stop = early_stop
        self.optimizer = optimizer.lower()
        self.loss = loss
        self.lamb1_precise_margin_ranking = lamb1_precise_margin_ranking
        self.lamb2_precise_margin_ranking = lamb2_precise_margin_ranking
        self.rand_perm_n = rand_perm_n
        self.func_precise_margin_ranking = func_precise_margin_ranking
        self.base_model = base_model
        self.model_path = model_path
        self.device = torch.device("cuda:%d" % (GPU) if torch.cuda.is_available() and GPU >= 0 else "cpu")
        self.n_jobs = n_jobs
        self.seed = seed
        self.tensorboard_path = tensorboard_path
        self.print_iter = print_iter

        
        self.logger.info(
            "GATs parameters setting:"
            "\nd_feat : {}"
            "\nhidden_size : {}"
            "\nnum_layers : {}"
            "\ndropout : {}"
            "\nn_epochs : {}"
            "\nlr : {}"
            "\nmetric : {}"
            "\nearly_stop : {}"
            "\noptimizer : {}"
            "\nloss_type : {}"
            "\nbase_model : {}"
            "\nmodel_path : {}"
            "\nvisible_GPU : {}"
            "\nuse_GPU : {}"
            "\nseed : {}".format(
                d_feat,
                hidden_size,
                num_layers,
                dropout,
                n_epochs,
                lr,
                metric,
                early_stop,
                optimizer.lower(),
                loss,
                base_model,
                model_path,
                GPU,
                self.use_gpu,
                seed,
            )
        )

        if self.seed is not None:
            np.random.seed(self.seed)
            torch.manual_seed(self.seed)

        self.GAT_model = GATModel(
            d_feat=self.d_feat,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout,
            base_model=self.base_model,
        )
        self.logger.info("model:\n{:}".format(self.GAT_model))
        self.logger.info("model size: {:.4f} MB".format(count_parameters(self.GAT_model)))

        if optimizer.lower() == "adam":
            self.train_optimizer = optim.AdamW(self.GAT_model.parameters(), lr=self.lr, weight_decay=self.weight_decay)
        elif optimizer.lower() == "gd":
            self.train_optimizer = optim.SGD(self.GAT_model.parameters(), lr=self.lr, weight_decay=self.weight_decay)
        else:
            raise NotImplementedError("optimizer {} is not supported!".format(optimizer))

        self.fitted = False
        self.GAT_model.to(self.device)

    @property
    def use_gpu(self):
        return self.device != torch.device("cpu")

    def mse(self, pred, label):
        loss = (pred - label) ** 2
        return torch.mean(loss)
    
    def bce(self, pred, label):
        return F.binary_cross_entropy_with_logits(pred, label)

    def margin_ranking(self, pred, label, use_mse=False):
        idx = torch.randperm(pred.size(0))
        pair_1, pair_2 = idx[::2], idx[1::2]
        if pred.size(0) % 2 == 1:
            pair_1 = pair_1[:-1]
        target = torch.sign(label[pair_1] - label[pair_2])
        loss = F.margin_ranking_loss(pred[pair_1], pred[pair_2], target, margin=0, reduction='mean')
        if use_mse:
            loss += torch.mean(torch.sqrt((pred - label) ** 2))
        
        return loss
    
    def half_margin_ranking(self, pred, label, use_mse=False):
        idx = torch.randperm(pred.size(0))
        pair_1, pair_2 = idx[::2], idx[1::2]
        if pred.size(0) % 2 == 1:
            pair_1 = pair_1[:-1]
        target = torch.sign(label[pair_1] - label[pair_2])
        pred_ord = torch.sign(pred[pair_1] - pred[pair_2])
        loss = F.margin_ranking_loss(pred[pair_1][target != pred_ord], pred[pair_2][target != pred_ord], target[target != pred_ord], margin=0.05, reduction='mean')
        if use_mse:
            loss += torch.mean(torch.sqrt((pred - label) ** 2))
        
        return loss
    
    def precise_margin_ranking(self, pred, label, use_mse=False):
        lamb1 = self.lamb1_precise_margin_ranking
        lamb2 = self.lamb2_precise_margin_ranking
        rand_perm_n = self.rand_perm_n

        total_loss = torch.tensor(0).to(self.device).float()
        for i in range(rand_perm_n):
            idx = torch.randperm(pred.size(0))
            pair_1, pair_2 = idx[::2], idx[1::2]
            if pred.size(0) % 2 == 1:
                pair_1 = pair_1[:-1]

            if self.func_precise_margin_ranking == "linear":
                f = - (label[pair_1] - label[pair_2]) * (pred[pair_1] - pred[pair_2])
            elif self.func_precise_margin_ranking == "cubic":
                f = - torch.sign(label[pair_1] - label[pair_2]) * \
                    torch.pow(torch.abs(label[pair_1] - label[pair_2]), 1/3) * \
                    (pred[pair_1] - pred[pair_2])
            else:
                print("The func_precise_margin_ranking "
                      f"{self.func_precise_margin_ranking} is not supported!")
            loss = torch.sum(torch.maximum(torch.tensor(0).to(self.device), f))
            total_loss += loss
        loss = total_loss / rand_perm_n
        if use_mse:
            loss = lamb2 * loss + lamb1 * torch.sum((pred - label) ** 2)
        return loss
            
    def precise_margin_ranking_max_min(self, pred, label):
        
        lamb1 = self.lamb1_precise_margin_ranking
        lamb2 = self.lamb2_precise_margin_ranking
        
        idx = torch.randperm(pred.size(0))
        pair_1, pair_2 = idx[::2], idx[1::2]
        if pred.size(0) % 2 == 1:
            pair_1 = pair_1[:-1]

        # normalizing predictions only in PMRL
        pred_adj = pred / (torch.quantile(pred, 0.95) - torch.quantile(pred, 0.05))
        if self.func_precise_margin_ranking == "linear":
            f = - (label[pair_1] - label[pair_2]) * (pred_adj[pair_1] - pred_adj[pair_2])
        elif self.func_precise_margin_ranking == "cubic":
            f = - torch.sign(label[pair_1] - label[pair_2]) * \
                torch.pow(torch.abs(label[pair_1] - label[pair_2]), 1/3) * \
                (pred_adj[pair_1] - pred_adj[pair_2])
        else:
            print("The func_precise_margin_ranking "
                  f"{self.func_precise_margin_ranking} is not supported!")
        loss = torch.sum(torch.maximum(torch.tensor(0).to(self.device), f))
        
        loss = lamb2 * loss + lamb1 * torch.sum((pred - label) ** 2)
        
        return loss
    
    def precise_margin_ranking_w_rank(self, pred, label):
        
        lamb1 = self.lamb1_precise_margin_ranking
        lamb2 = self.lamb2_precise_margin_ranking

        idx = torch.randperm(pred.size(0))
        pair_1, pair_2 = idx[::2], idx[1::2]
        if pred.size(0) % 2 == 1:
            pair_1 = pair_1[:-1]
        
        # applying ranks (percentiles) to labels only in PMRL
        label_rank = rank(label)
        if self.func_precise_margin_ranking == "linear":
            f = - (label_rank[pair_1] - label_rank[pair_2]) * (pred[pair_1] - pred[pair_2])
        elif self.func_precise_margin_ranking == "cubic":
            f = - torch.sign(label_rank[pair_1] - label_rank[pair_2]) * \
                torch.pow(torch.abs(label_rank[pair_1] - label_rank[pair_2]), 1/3) * \
                (pred[pair_1] - pred[pair_2])
        else:
            print("The func_precise_margin_ranking "
                  f"{self.func_precise_margin_ranking} is not supported!")
        loss = torch.sum(torch.maximum(torch.tensor(0).to(self.device), f))
        
        loss = lamb2 * loss + lamb1 * torch.sum((pred - label) ** 2)
        return loss

    def loss_fn(self, pred, label):
        mask = ~torch.isnan(label)

        if self.loss == "mse":
            return self.mse(pred[mask], label[mask])
        elif self.loss == "bce":
            return self.bce(pred[mask], label[mask])
        elif self.loss == "margin_ranking":
            return self.margin_ranking(pred[mask], label[mask])
        elif self.loss == "margin_ranking_w_mse":
            return self.margin_ranking(pred[mask], label[mask], use_mse=True)
        elif self.loss == "precise_margin_ranking":
            return self.precise_margin_ranking(pred[mask], label[mask])
        elif self.loss == "precise_margin_ranking_w_mse":
            return self.precise_margin_ranking(pred[mask], label[mask], use_mse=True)
        elif self.loss == "half_margin_ranking":
            return self.half_margin_ranking(pred[mask], label[mask])
        elif self.loss == "half_margin_ranking_w_mse":
            return self.half_margin_ranking(pred[mask], label[mask], use_mse=True)
        elif self.loss == "precise_margin_ranking_w_rank":
            return self.precise_margin_ranking_w_rank(pred[mask], label[mask])
        elif self.loss == "precise_margin_ranking_max_min":
            return self.precise_margin_ranking_max_min(pred[mask], label[mask])

        raise ValueError("unknown loss `%s`" % self.loss)

    def metric_fn(self, pred, label):

        mask = torch.isfinite(label)

        if self.metric in ("", "loss"):
            return -self.loss_fn(pred[mask], label[mask])

        raise ValueError("unknown metric `%s`" % self.metric)

    def get_daily_inter(self, df, shuffle=False):
        # organize the train data into daily batches
        daily_count = df.groupby(level=0).size().values
        daily_index = np.roll(np.cumsum(daily_count), 1)
        daily_index[0] = 0
        if shuffle:
            # shuffle data
            daily_shuffle = list(zip(daily_index, daily_count))
            np.random.shuffle(daily_shuffle)
            daily_index, daily_count = zip(*daily_shuffle)
        return daily_index, daily_count

    def train_epoch(self, data_loader, train_loader, val_loader, epoch=0, split='train', writer=None):

        self.GAT_model.train()

        for batch_id, data in enumerate(data_loader):
            
            data = data.squeeze()
            feature = data[:, :, 0:-1].to(self.device)
            label = data[:, -1, -1].to(self.device)
            
            pred = self.GAT_model(feature.float())
            loss = self.loss_fn(pred, label)

            self.train_optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_value_(self.GAT_model.parameters(), 3.0)
            grad_norm = gradient_norm(self.GAT_model)
            # print("Gradient norm is ", grad_norm)
            self.train_optimizer.step()
            if batch_id % self.print_iter == 0 and writer:
                train_loss, train_score = self.test_epoch(train_loader)
                val_loss, val_score = self.test_epoch(val_loader)
                writer.add_scalars('Loss', {'train': train_loss, 'val': val_loss}, (len(data_loader) * epoch / data.size(0) + batch_id) * data.size(0))
                writer.add_scalars('Grad', {'grad_norm': grad_norm}, (len(data_loader) * epoch / data.size(0) + batch_id) * data.size(0))
                 
    def test_epoch(self, data_loader):

        self.GAT_model.eval()

        scores = []
        losses = []

        for data in data_loader:

            data = data.squeeze()
            feature = data[:, :, 0:-1].to(self.device)
            # feature[torch.isnan(feature)] = 0
            label = data[:, -1, -1].to(self.device)

            pred = self.GAT_model(feature.float())
            loss = self.loss_fn(pred, label)
            losses.append(loss.item())

            score = self.metric_fn(pred, label)
            scores.append(score.item())
        
        self.GAT_model.train()
        return np.mean(losses), np.mean(scores)

    def fit(
        self,
        dataset,
        evals_result=dict(),
        save_path=None,
    ):

        dl_train = dataset.prepare("train", col_set=["feature", "label"], data_key=DataHandlerLP.DK_L)
        dl_valid = dataset.prepare("valid", col_set=["feature", "label"], data_key=DataHandlerLP.DK_L)
        if dl_train.empty or dl_valid.empty:
            raise ValueError("Empty data from dataset, please check your dataset config.")
        
        dl_train.config(fillna_type="ffill+bfill")  # process nan brought by dataloader
        dl_valid.config(fillna_type="ffill+bfill")  # process nan brought by dataloader

        sampler_train = DailyBatchSampler(dl_train)
        sampler_valid = DailyBatchSampler(dl_valid)

        train_loader = DataLoader(dl_train, sampler=sampler_train, num_workers=self.n_jobs, drop_last=True)
        valid_loader = DataLoader(dl_valid, sampler=sampler_valid, num_workers=self.n_jobs, drop_last=True)

        save_path = get_or_create_path(save_path)
        current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        tboard_writer = get_tensorboard_logger(save_path=join(self.tensorboard_path, f"GATs_{current_time}"))
        stop_steps = 0
        train_loss = 0
        best_score = -np.inf
        best_epoch = 0
        evals_result["train"] = []
        evals_result["valid"] = []

        # load pretrained base_model
        if self.base_model == "LSTM":
            pretrained_model = LSTMModel(d_feat=self.d_feat, hidden_size=self.hidden_size, num_layers=self.num_layers)
        elif self.base_model == "GRU":
            pretrained_model = GRUModel(d_feat=self.d_feat, hidden_size=self.hidden_size, num_layers=self.num_layers)
        else:
            raise ValueError("unknown base model name `%s`" % self.base_model)

        if self.model_path is not None:
            self.logger.info("Loading pretrained model...")
            pretrained_model.load_state_dict(torch.load(self.model_path, map_location=self.device))

        model_dict = self.GAT_model.state_dict()
        pretrained_dict = {
            k: v for k, v in pretrained_model.state_dict().items() if k in model_dict  # pylint: disable=E1135
        }
        model_dict.update(pretrained_dict)
        self.GAT_model.load_state_dict(model_dict)
        self.logger.info("Loading pretrained model Done...")

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
                best_param = deepcopy(self.GAT_model.state_dict())
            else:
                stop_steps += 1
                if stop_steps >= self.early_stop:
                    self.logger.info("early stop")
                    break

        self.logger.info("best score: %.6lf @ %d" % (best_score, best_epoch))
        self.GAT_model.load_state_dict(best_param)
        torch.save(best_param, save_path)

        if self.use_gpu:
            torch.cuda.empty_cache()

    def predict(self, dataset):
        if not self.fitted:
            raise ValueError("model is not fitted yet!")

        dl_test = dataset.prepare("test", col_set=["feature", "label"], data_key=DataHandlerLP.DK_I)
        dl_test.config(fillna_type="ffill+bfill")
        sampler_test = DailyBatchSampler(dl_test)
        idx = list(sampler_test)
        idx = np.concatenate(idx)
        sampler_test = DailyBatchSampler(dl_test)
        test_loader = DataLoader(dl_test, sampler=sampler_test, num_workers=self.n_jobs)
        self.GAT_model.eval()
        preds = []

        for data in test_loader:

            data = data.squeeze()
            feature = data[:, :, 0:-1].to(self.device)

            with torch.no_grad():
                pred = self.GAT_model(feature.float()).detach().cpu().numpy()

            preds.append(pred)

        return pd.Series(np.concatenate(preds), index=dl_test.get_index()[idx])


class GATModel(nn.Module):
    def __init__(self, d_feat=6, hidden_size=64, num_layers=2, dropout=0.0, base_model="GRU"):
        super().__init__()

        if base_model == "GRU":
            self.rnn = nn.GRU(
                input_size=d_feat,
                hidden_size=hidden_size,
                num_layers=num_layers,
                batch_first=True,
                dropout=dropout,
            )
        elif base_model == "LSTM":
            self.rnn = nn.LSTM(
                input_size=d_feat,
                hidden_size=hidden_size,
                num_layers=num_layers,
                batch_first=True,
                dropout=dropout,
            )
        else:
            raise ValueError("unknown base model name `%s`" % base_model)
        self.openai_emb_size = 1536
        self.hidden_size = hidden_size
        self.d_feat = d_feat
        self.transformation = nn.Linear(self.hidden_size, self.hidden_size)
        self.a = nn.Parameter(torch.randn(self.hidden_size * 2, 1))
        self.a.requires_grad = True
        self.fc = nn.Linear(self.hidden_size, self.hidden_size)
        self.fc_out = nn.Linear(hidden_size, 1)
        self.emb_fc = nn.Linear(self.openai_emb_size, self.hidden_size)
        self.leaky_relu = nn.LeakyReLU()
        self.softmax = nn.Softmax(dim=1)

    def cal_attention(self, x, y):
        x = self.transformation(x)
        y = self.transformation(y)

        sample_num = x.shape[0]
        dim = x.shape[1]
        e_x = x.expand(sample_num, sample_num, dim)
        e_y = torch.transpose(e_x, 0, 1)
        attention_in = torch.cat((e_x, e_y), 2).view(-1, dim * 2)
        self.a_t = torch.t(self.a)
        attention_out = self.a_t.mm(torch.t(attention_in)).view(sample_num, sample_num)
        attention_out = self.leaky_relu(attention_out)
        att_weight = self.softmax(attention_out)
        return att_weight

    def forward(self, x):
        out, _ = self.rnn(x[:20])
        hidden = out[:, -1, :]
        emb_hidden = self.emb_fc(x[20:-1])
        hidden = hidden + emb_hidden
        att_weight = self.cal_attention(hidden, hidden)
        hidden = att_weight.mm(hidden) + hidden
        hidden = self.fc(hidden)
        hidden = self.leaky_relu(hidden)
        return self.fc_out(hidden).squeeze()
