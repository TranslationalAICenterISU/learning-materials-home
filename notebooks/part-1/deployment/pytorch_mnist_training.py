#
# Trains an MNIST digit recognizer using PyTorch, and uses tensorboardX to log training metrics
# and weights in TensorBoard event format to the MLflow run's artifact directory. This stores the
# TensorBoard events in MLflow for later access using the TensorBoard command line tool.
#
# NOTE: This example requires you to first install PyTorch (using the instructions at pytorch.org)
#       and tensorboardX (using pip install tensorboardX).
#
# Code based on https://github.com/lanpa/tensorboard-pytorch-examples/blob/master/mnist/main.py.
#
# Custom PytorchModelWrapper to load image bytestring list as input

import argparse
import os
import mlflow
import mlflow.pytorch
import mlflow.pyfunc
from  mlflow.tracking import MlflowClient


import pickle
import tempfile
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import datasets, transforms
from torch.autograd import Variable
from torch.utils.tensorboard import SummaryWriter

# Command-line arguments
parser = argparse.ArgumentParser(description='PyTorch MNIST Example')
parser.add_argument('--batch-size', type=int, default=64, metavar='N',
                    help='input batch size for training (default: 64)')
parser.add_argument('--test-batch-size', type=int, default=1000, metavar='N',
                    help='input batch size for testing (default: 1000)')
parser.add_argument('--epochs', type=int, default=10, metavar='N',
                    help='number of epochs to train (default: 10)')
parser.add_argument('--lr', type=float, default=0.01, metavar='LR',
                    help='learning rate (default: 0.01)')
parser.add_argument('--momentum', type=float, default=0.5, metavar='M',
                    help='SGD momentum (default: 0.5)')
parser.add_argument('--enable-cuda', type=str, choices=['True', 'False'], default='True',
                    help='enables or disables CUDA training')
parser.add_argument('--seed', type=int, default=1, metavar='S',
                    help='random seed (default: 1)')
parser.add_argument('--log-interval', type=int, default=100, metavar='N',
                    help='how many batches to wait before logging training status')
args = parser.parse_args()

enable_cuda_flag = True if args.enable_cuda == 'True' else False

args.cuda = enable_cuda_flag and torch.cuda.is_available()

torch.manual_seed(args.seed)
if args.cuda:
    torch.cuda.manual_seed(args.seed)

kwargs = {'num_workers': 1, 'pin_memory': True} if args.cuda else {}
train_loader = torch.utils.data.DataLoader(
    datasets.MNIST('../data', train=True, download=True,
                   transform=transforms.Compose([
                       transforms.ToTensor(),
                       transforms.Normalize((0.1307,), (0.3081,))
                   ])),
    batch_size=args.batch_size, shuffle=True, **kwargs)
test_loader = torch.utils.data.DataLoader(
    datasets.MNIST('../data', train=False, transform=transforms.Compose([
                       transforms.ToTensor(),
                       transforms.Normalize((0.1307,), (0.3081,))
                   ])),
    batch_size=args.test_batch_size, shuffle=True, **kwargs)


## Setting up Mlflow Experiment
experiment_name = "pytorch_exp_1"
tracking_uri = os.environ.get("TRACKING_URL")
client = MlflowClient(tracking_uri=tracking_uri)
mlflow.set_tracking_uri(tracking_uri)
experiments = client.list_experiments()

experiment_names = []
for exp in experiments:
    experiment_names.append(exp.name)
if experiment_name not in experiment_names:
    try:
        mlflow.create_experiment(experiment_name)
    except:
        pass
mlflow.set_experiment(experiment_name)

## Neural Network Module
class Net(nn.Module):
    def __init__(self):
        super(Net, self).__init__()
        self.conv1 = nn.Conv2d(1, 10, kernel_size=5)
        self.conv2 = nn.Conv2d(10, 20, kernel_size=5)
        self.conv2_drop = nn.Dropout2d()
        self.fc1 = nn.Linear(320, 50)
        self.fc2 = nn.Linear(50, 10)

    def forward(self, x):
        x = F.relu(F.max_pool2d(self.conv1(x), 2))
        x = F.relu(F.max_pool2d(self.conv2_drop(self.conv2(x)), 2))
        x = x.view(-1, 320)
        x = F.relu(self.fc1(x))
        x = F.dropout(x, training=self.training)
        x = self.fc2(x)
        return F.log_softmax(x, dim=0)

    def log_weights(self, step):
        writer.add_histogram('weights/conv1/weight', model.conv1.weight.data, step)
        writer.add_histogram('weights/conv1/bias', model.conv1.bias.data, step)
        writer.add_histogram('weights/conv2/weight', model.conv2.weight.data, step)
        writer.add_histogram('weights/conv2/bias', model.conv2.bias.data, step)
        writer.add_histogram('weights/fc1/weight', model.fc1.weight.data, step)
        writer.add_histogram('weights/fc1/bias', model.fc1.bias.data, step)
        writer.add_histogram('weights/fc2/weight', model.fc2.weight.data, step)
        writer.add_histogram('weights/fc2/bias', model.fc2.bias.data, step)

model = Net()
if args.cuda:
    model.cuda()

optimizer = optim.SGD(model.parameters(), lr=args.lr, momentum=args.momentum)

writer = None # Will be used to write TensorBoard events


def train(epoch):
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        if args.cuda:
            data, target = data.cuda(), target.cuda()
        data, target = Variable(data), Variable(target)
        optimizer.zero_grad()
        output = model(data)
        loss = F.nll_loss(output, target)
        loss.backward()
        optimizer.step()
        if batch_idx % args.log_interval == 0:
            print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                epoch, batch_idx * len(data), len(train_loader.dataset),
                100. * batch_idx / len(train_loader), loss.data.item()))
            step = epoch * len(train_loader) + batch_idx
            log_scalar('train_loss', loss.data.item(), step)
            model.log_weights(step)

def test(epoch):
    model.eval()
    test_loss = 0
    correct = 0
    with torch.no_grad():
        for data, target in test_loader:
            if args.cuda:
                data, target = data.cuda(), target.cuda()
            data, target = Variable(data), Variable(target)
            output = model(data)
            test_loss += F.nll_loss(output, target, reduction='sum').data.item() # sum up batch loss
            pred = output.data.max(1)[1] # get the index of the max log-probability
            correct += pred.eq(target.data).cpu().sum().item()

    test_loss /= len(test_loader.dataset)
    test_accuracy = 100.0 * correct / len(test_loader.dataset)
    print('\nTest set: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)\n'.format(
        test_loss, correct, len(test_loader.dataset), test_accuracy))
    step = (epoch + 1) * len(train_loader)
    log_scalar('test_loss', test_loss, step)
    log_scalar('test_accuracy', test_accuracy, step)

def log_scalar(name, value, step):
    """Log a scalar value to both MLflow and TensorBoard"""
    writer.add_scalar(name, value, step)
    mlflow.log_metric(name, value)

## Pytorch Model Wrapper that takes encoded image strings as inputs
class PytorchModelWrapper(mlflow.pyfunc.PythonModel):
    def load_context(self,context):
        import torch
        scripted_model = context.artifacts["scripted_model"]
        self.model = torch.jit.load(scripted_model).cpu()
        print("Pytorch model initialized")
    
    def predict(self, context, model_input):
        import numpy as np
        import base64
        from PIL import Image
        import io
        import torch
        print("Predicting %d samples"%len(model_input))
        nparray_list = []
        for _,row in model_input.iterrows():
            base64_decoded = base64.b64decode(row["images"])
            image = Image.open(io.BytesIO(base64_decoded))
            image_np = np.array(image,dtype=np.uint8)
            image_np = np.expand_dims(image_np,axis=0)
            nparray_list.append(image_np)
        nparray = np.stack(nparray_list,axis=0).astype(np.float32)
        torch_tensor = torch.from_numpy(nparray)
        predictions = self.model(torch_tensor).data.max(1)[1]
        return predictions.detach().cpu().numpy()

## Utility function to add libraries to conda environment
def add_libraries_to_conda_env(_conda_env,libraries=[],conda_dependencies=[]):
    dependencies = _conda_env["dependencies"]
    dependencies = dependencies + conda_dependencies
    pip_index = None
    for _index,_element in enumerate(dependencies):
        if type(_element) == dict:
            if "pip" in _element.keys():
                pip_index = _index
                break
    dependencies[pip_index]["pip"] =  dependencies[pip_index]["pip"] + libraries
    _conda_env["dependencies"] = dependencies
    return _conda_env

## Start MLflow Run
with mlflow.start_run():
    # Log our parameters into mlflow
    for key, value in vars(args).items():
        mlflow.log_param(key, value)

    # Create a SummaryWriter to write TensorBoard events locally
    output_dir = dirpath = tempfile.mkdtemp()
    writer = SummaryWriter(output_dir)
    print("Writing TensorBoard events locally to %s\n" % output_dir)

    # Perform the training
    for epoch in range(1, args.epochs + 1):
        train(epoch)
        test(epoch)

    # Upload the TensorBoard event logs as a run artifact
    print("Uploading TensorBoard events as a run artifact...")
    mlflow.log_artifacts(output_dir, artifact_path="events")
    print("\nLaunch TensorBoard with:\n\ntensorboard --logdir=%s" %
        os.path.join(mlflow.get_artifact_uri(), "events"))
    
    # Log the model as an artifact of the MLflow run.
    print("\nLogging the trained scripted model as a run artifact...")
    scripted_model = torch.jit.script(model)
    torch.jit.save(scripted_model,"scripted_model.pth")
    model_artifacts = {"scripted_model" : "scripted_model.pth"}
    pyfunc_pytorch_model = PytorchModelWrapper()
    conda_env = mlflow.pytorch.get_default_conda_env()
    conda_env = add_libraries_to_conda_env(conda_env,libraries=["typing-extensions", "Pillow"])
#     mlflow.pytorch.log_model(scripted_model, artifact_path="pytorch-model")
    mlflow.pyfunc.log_model("pytorch-model",python_model=pyfunc_pytorch_model,artifacts=model_artifacts,conda_env=conda_env)
    print(
        "\nThe model is logged at:\n%s" % os.path.join(mlflow.get_artifact_uri(), "pytorch-model")
    )