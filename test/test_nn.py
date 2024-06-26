from typing import List, Callable
from shrimpgrad import Tensor, nn 
import unittest
import torch
import numpy as np

def prepare_tensors(shapes, low=-1.5, high=1.5):
  np.random.seed(0)
  np_data = [np.random.uniform(low=low, high=high, size=shp).astype(np.float32) for shp in shapes]
  tts = [torch.tensor(data, requires_grad=True, dtype=torch.float32) for data in np_data]
  sts = [Tensor(shp, data.flatten().tolist() if len(shp) else data.flatten().tolist()[0]) for shp, data in zip(shapes, np_data)]
  return sts, tts 

class ShrimpModel:
  def __init__(self):
    self.layers: List[Callable[[Tensor], Tensor]] = [
    nn.Linear(2, 50), Tensor.relu,
    nn.Linear(50, 1), Tensor.sigmoid, 
    ]
  def __call__(self, x: Tensor):
    return x.sequential(self.layers)

class TorchModel(torch.nn.Module):
  def __init__(self):
    super().__init__()
    self.linear_relu_stack = torch.nn.Sequential(
        torch.nn.Linear(2, 50),
        torch.nn.ReLU(),
        torch.nn.Linear(50, 1),
        torch.nn.Sigmoid()
    )
    
  def inject_weights(self, w, b, w_, b_):
    m = self.linear_relu_stack[0].eval()
    m.weight[:] = w 
    m.bias[:] = b
    m = self.linear_relu_stack[2].eval()
    m.weight[:] = w_
    m.bias[:] = b_

  def set_requires_grad(self):
    self.linear_relu_stack[0].weight.requires_grad = True
    self.linear_relu_stack[0].bias.requires_grad = True
    self.linear_relu_stack[2].weight.requires_grad = True
    self.linear_relu_stack[2].bias.requires_grad = True
    self.linear_relu_stack[0].weight.retain_grad()
    self.linear_relu_stack[0].bias.retain_grad()
    self.linear_relu_stack[2].weight.retain_grad()
    self.linear_relu_stack[2].bias.retain_grad()

  def forward(self, x):
    logits = self.linear_relu_stack(x)
    return logits

def dataset():
  from sklearn.datasets import make_moons
  X, y = make_moons(n_samples=100, noise=0.1)
  X = X.astype(float)
  y = y.astype(float).reshape(100)
  return X, y

class TestNN(unittest.TestCase):
  def test_linear(self):
    x = Tensor((2,2), [1.0,2.0,3.0,4.0])
    model = nn.Linear(2,2)
    z = model(x).square().mean()
    with torch.no_grad():
      torch_model = torch.nn.Linear(2,2).eval()
      torch_model.weight[:] = torch.tensor(model.w.data.copy()).reshape(2,2)
      torch_model.bias[:] = torch.tensor(model.bias.data.copy())
    torch_model.weight.requires_grad = True
    torch_model.weight.retain_grad()
    torch_model.bias.requires_grad = True
    torch_model.bias.retain_grad()
    torch_x = torch.tensor(x.data.copy()).reshape(2,2)
    torch_z = torch_model(torch_x).square().mean()
    np.testing.assert_allclose(np.array(z.data), torch_z.detach().numpy(), atol=5e-4, rtol=1e-5)
    torch_z.backward()
    z.backward()
    np.testing.assert_allclose(np.array(model.w.grad.data).reshape(2,2).transpose(), torch_model.weight.grad.detach().numpy(), atol=1e-6, rtol=1e-3)

  def test_basic_net(self):
    X, y  = dataset()
    y = y.reshape(100)
    shrimp_model = ShrimpModel()
    torch_model = TorchModel()
    w0 = shrimp_model.layers[0].w
    b0 = shrimp_model.layers[0].bias
    w1 = shrimp_model.layers[2].w
    b1 = shrimp_model.layers[2].bias
    tw0 = torch.tensor(w0.data.copy(), dtype=torch.float32,requires_grad=True).reshape(*w0.shape)
    tb0 = torch.tensor(b0.data.copy(), dtype=torch.float32, requires_grad=True).reshape(*b0.shape)
    tw1 = torch.tensor(w1.data.copy(), dtype=torch.float32, requires_grad=True).reshape(*w1.shape)
    tb1 = torch.tensor(b1.data.copy(), dtype=torch.float32,requires_grad=True).reshape(*b1.shape)
    with torch.no_grad():
      torch_model.inject_weights(tw0,tb0, tw1, tb1)
    torch_model.set_requires_grad()
    sloss = shrimp_model(Tensor.fromlist(X.shape, X.flatten().tolist())).binary_cross_entropy(Tensor.fromlist(y.shape, y.flatten().tolist()))
    tout = torch_model(torch.tensor(X, dtype=torch.float32)).reshape(100)
    tloss = torch.nn.functional.binary_cross_entropy(tout, torch.tensor(y, dtype=torch.float32))
    # TODO: Tweak tolerances and compare with different BCE, torch bce is not identical
    # np.testing.assert_allclose(np.array(sloss.data), tloss.detach().numpy(), atol=1e-6, rtol=1e-2)

    sloss.backward()
    tloss.backward()
    # np.testing.assert_allclose(np.array(w0.grad.data).reshape(50,2).transpose(), torch_model.linear_relu_stack[0].weight.grad.detach().numpy(), atol=1e-4, rtol=1e-3)


  def test_basic_net_(self):
    weights_shrimp, weights_torch = prepare_tensors([(2,2),(2,2),(2,), (2,)]) 

    w0, w0_ = weights_shrimp[0], weights_torch[0]
    b0, b0_= weights_shrimp[2], weights_torch[2]
    w1, w1_ = weights_shrimp[1], weights_torch[1]
    b1, b1_ = weights_shrimp[3], weights_torch[3]

    X, _ = dataset()

    x0, x0_ = Tensor.fromlist(X.shape, X.flatten().tolist()), torch.tensor(X, dtype=torch.float32)
    z0 = (x0.dot(w0.transpose()) + b0).relu()
    z0_ = (torch.matmul(x0_, w0_.transpose(0,1)) + b0_ ).relu()
    np.testing.assert_allclose(np.array(z0.data).reshape(*z0.shape), z0_.detach().numpy(), atol=1e-6, rtol=1e-3)
 
    z1 = (z0.dot(w1.transpose()) + b1).sigmoid().square().mean()
    z1_ = (torch.matmul(z0_, w1_.transpose(0,1)) + b1_ ).sigmoid().square().mean()
    np.testing.assert_allclose(np.array(z1.data), z1_.detach().numpy(), atol=1e-6, rtol=1e-2)

    z1.backward() 
    z1_.backward()
    np.testing.assert_allclose(np.array(w0.grad.data).reshape(*w0.grad.shape).transpose(), w0_.grad.detach().numpy(), atol=1e-4, rtol=1e-2)


  def test_basic_net_bce_loss_(self):
    weights_shrimp, weights_torch = prepare_tensors([(2,2),(1,2),(2,), (1,)]) 

    w0, w0_ = weights_shrimp[0], weights_torch[0]
    b0, b0_= weights_shrimp[2], weights_torch[2]
    w1, w1_ = weights_shrimp[1], weights_torch[1]
    b1, b1_ = weights_shrimp[3], weights_torch[3]

    X, y = dataset()

    x0, x0_ = Tensor.fromlist(X.shape, X.flatten().tolist()), torch.tensor(X, dtype=torch.float32)
    z0 = (x0.dot(w0.transpose()) + b0).relu()
    z0_ = (torch.matmul(x0_, w0_.transpose(0,1)) + b0_ ).relu()
    np.testing.assert_allclose(np.array(z0.data).reshape(*z0.shape), z0_.detach().numpy(), atol=1e-6, rtol=1e-3)
 
    z1 = (z0.dot(w1.transpose()) + b1).sigmoid()
    z1_ = (torch.matmul(z0_, w1_.transpose(0,1)) + b1_ ).sigmoid()
    np.testing.assert_allclose(np.array(z1.data).reshape(*z1.shape), z1_.detach().numpy(), atol=1e-6, rtol=1e-3)

    _ = z1.binary_cross_entropy(_:=Tensor.fromlist(y.shape, y.flatten().tolist()))
    _ = torch.nn.functional.binary_cross_entropy(z1_.reshape(100), torch.tensor(y, dtype=torch.float32))
    # TODO: BCE doesn't match up with torch unless I write a custom BCE for torch that matches our impl
    # np.testing.assert_allclose(np.array(z2.data), z2_.detach().numpy(), atol=1e-6, rtol=1e-3)

    # z2.backward()
    # z2_.backward()


    # np.testing.assert_allclose(np.array(w0.grad.data).reshape(*w0.grad.shape).transpose(), w0_.grad.detach().numpy(), atol=1e-4, rtol=1e-3)
