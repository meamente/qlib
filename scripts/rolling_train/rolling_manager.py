from pprint import pprint
import os
import numpy as np
import torch
import random
import fire
import qlib
from qlib.constant import REG_US
from qlib.workflow import R
from qlib.workflow.task.gen import RollingGen, task_generator
from qlib.workflow.task.manage import TaskManager, run_task
from qlib.workflow.task.collect import RecorderCollector
from qlib.model.ens.group import RollingGroup
from qlib.model.trainer import TrainerR, TrainerRM, task_train
from model_config import model_config

"""torch.manual_seed(1234)
torch.cuda.manual_seed(1234)
torch.cuda.manual_seed_all(1234)
np.random.seed(1234)
random.seed(1234)
torch.backends.cudnn.benchmark = False
torch.backends.cudnn.deterministic = True
torch.set_deterministic(True)"""

class RollingTaskExample:
    def __init__(
        self,
        provider_uri="~/.qlib/qlib_data/my_data/sp500_components",
        region=REG_US,
        task_url="mongodb://10.0.0.4:27017/",
        task_db_name="rolling_db",
        experiment_name="rolling_exp",
        task_pool=None,  # if user want to  "rolling_task"
        task_config=None,
        rolling_step=90,
        rolling_type="sliding",
    ):
        # TaskManager config
        if task_config is None:
            task_config = [model_config]
        mongo_conf = {
            "task_url": task_url,
            "task_db_name": task_db_name,
        }
        qlib.init(provider_uri=provider_uri, region=region)#, mongo=mongo_conf)
        self.experiment_name = experiment_name
        if task_pool is None:
            self.trainer = TrainerR(experiment_name=self.experiment_name)
        else:
            self.task_pool = task_pool
            self.trainer = TrainerRM(self.experiment_name, self.task_pool)
        self.task_config = task_config
        print(rolling_type)
        self.rolling_gen = RollingGen(step=rolling_step, rtype=RollingGen.ROLL_EX if rolling_type == "expanding" else RollingGen.ROLL_SD)

    # Reset all things to the first status, be careful to save important data
    def reset(self):
        print("========== reset ==========")
        if isinstance(self.trainer, TrainerRM):
            TaskManager(task_pool=self.task_pool).remove()
        exp = R.get_exp(experiment_name=self.experiment_name)
        for rid in exp.list_recorders():
            exp.delete_recorder(rid)

    def task_generating(self):
        print("========== task_generating ==========")
        tasks = task_generator(
            tasks=self.task_config,
            generators=self.rolling_gen,  # generate different date segments
        )
        print("NUMBER OF TASKS: ", len(tasks))
        for task in tasks:
            pprint(task['dataset']['kwargs']['segments'])
        return tasks

    def task_training(self, tasks):
        print("========== task_training ==========")
        self.trainer.train(tasks)

    def worker(self):
        # NOTE: this is only used for TrainerRM
        # train tasks by other progress or machines for multiprocessing. It is same as TrainerRM.worker.
        print("========== worker ==========")
        run_task(task_train, self.task_pool, experiment_name=self.experiment_name)

    def task_collecting(self):
        print("========== task_collecting ==========")

        def rec_key(recorder):
            task_config = recorder.load_object("task")
            model_key = task_config["model"]["class"]
            rolling_key = task_config["dataset"]["kwargs"]["segments"]["test"]
            return model_key, rolling_key

        def my_filter(recorder):
            # only choose the results of "LGBModel"
            model_key, rolling_key = rec_key(recorder)
            if model_key == "GATs":
                return True
            return False

        collector = RecorderCollector(
            experiment=self.experiment_name,
            process_list=RollingGroup(),
            rec_key_func=rec_key,
            rec_filter_func=my_filter,
        )
        res = collector()
        res['pred'][('GATs',)].to_pickle(f'{self.experiment_name}_pred.pkl')
        print(collector())

    def main(self):
        self.reset()
        tasks = self.task_generating()
        self.task_training(tasks)
        self.task_collecting()


if __name__ == "__main__":
    ## to see the whole process with your own parameters, use the command below
    # python task_manager_rolling.py main --experiment_name="your_exp_name"
    fire.Fire(RollingTaskExample)
