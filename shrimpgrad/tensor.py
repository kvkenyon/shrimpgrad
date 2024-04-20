from typing import Iterable, Optional, Self, Tuple, TypeAlias, Union, Callable, List
from functools import reduce
import operator
from pprint import pformat
from shrimpgrad.cblas import sgemm
from shrimpgrad.dtype import DType, dtypes

Num: TypeAlias = Union[float, int, complex]
Shape: TypeAlias = Tuple[int, ...]

BinaryOp = Callable[['Tensor', 'Tensor'], 'Tensor']
UnaryOp = Callable[['Tensor'], 'Tensor']

def prod(x: Iterable[int|float]) -> Union[float, int]: return reduce(operator.mul, x, 1)
def pad_left(*shps: Tuple[int, ...], v=1) -> List[Tuple[int ,...]]: return [tuple((v,)*(max(len(s) for s in shps)-len(s)) + s) for s in shps]
def broadcast_shape(*shps: Tuple[int, ...]) -> Tuple[int, ...]: return tuple([max([s[dim] for s in shps]) for dim in range(len(shps[0]))])

def binary_op(F: BinaryOp, a: 'Tensor', b: 'Tensor', dim:int, off_a:int, off_b:int, loops:Iterable[Tuple], result:Iterable[Num]) -> None:
  if not loops:  return 
  s, e, step = loops[0]
  for i in range(s, e, step):
    if len(loops) == 1: result.append(F(a.data[off_a + i*step*a.strides[dim]] , b.data[off_b + i*step*b.strides[dim]]))
    else: binary_op(F, a, b, dim+1, off_a + i*a.strides[dim]*step, off_b + i*b.strides[dim]*step, loops[1:], result)
  return 

class Tensor:
  def __init__(self, shape: Shape, data: Union[Iterable[Num], Num], dtype:DType=dtypes.float32, lazy=False) -> Self:
    self.shape, self.data, self.size, self.strides, self.dtype, self.lazy = shape, data, prod(shape), [], dtype, lazy
    # Scalar value
    if not len(self.shape):
      # Ensure it's a number not dimensional data
      assert isinstance(data, Num)
      self.data = data
      self.base_view = data
      return
    self.__calc_strides()
    if not self.lazy:
      self.base_view = self.__build_view(None)

  def __calc_strides(self) -> None:
    self.strides.clear()
    out: int = 1
    for dim in self.shape:
      out *= dim
      self.strides.append(self.size // out)
  
  def __calc_loops(self, key: Optional[slice|int]) -> Iterable[int]:
    if not key:  key = [slice(0, dim, 1) for dim in self.shape]
    if isinstance(key, int) or isinstance(key, slice): key = (key,)
    if len(key) > len(self.shape): raise IndexError(f'index of {key} is larger than dim {self.shape}.')
    extra_dim = 0
    if len(key) < len(self.shape): extra_dim = len(self.shape) - len(key)
    loops = []
    for i, k in enumerate(key):
      if isinstance(k, int):
        if k >= self.shape[i]:  raise IndexError(f'index of {k} is out of bounds for dim with size {self.shape[i]}')
        start = k
        if start < 0:
          if abs(start) >= self.shape[i]:
            raise IndexError(f'index of {start} is out of bounds for dim with size {self.shape[i]}')
          k = self.shape[i] + start
        start, end = k, k + 1
        loops.append((start,end, 1))
      elif isinstance(k, slice):
        start, end, step = k.indices(self.shape[i])
        if start < 0:
          if abs(start) >= self.shape[i]:
            raise IndexError(f'index of {start} is out of bounds for dim with size {self.shape[i]}')
          start = self.shape[i] + start 
        if end < 0:
          if abs(end) >= self.shape[i]:
            raise IndexError(f'index of {end} is out of bounds for dim with size {self.shape[i]}')
          end = self.shape[i] + end
        if start >= end: return [] 
        loops.append((start, end, step))
    if extra_dim: 
      for ed in range(len(key), len(key) + extra_dim): loops.append((0, self.shape[ed], 1))
    return loops

  def __build_view(self, key: Optional[slice|int]) -> Iterable:
    self.lazy = False
    def build(dim:int, offset:int, loops:Iterable[tuple], tensor:Iterable[Num]) -> Iterable[Num]:
      if not loops: return tensor
      s, e, step = loops[0]
      for i in range(s, e, step):
        if len(loops) == 1:
          # add elements
          tensor.append(self.data[offset+i*step*self.strides[dim]])
        else:
          # add dimension
          tensor.append([])
          build(dim+1, i*self.strides[dim]*step, loops[1:], tensor[-1])
      return tensor 
    return build(0, 0, self.__calc_loops(key), []) 
  
  def item(self) -> Num:
    if len(self.shape): raise RuntimeError(f'a Tensor with {self.size} elements cannot be converted to Scalar')
    return self.data

  def __getitem__(self, key) -> Self:
    if not len(self.shape): raise IndexError('invalid index of a 0-dim tensor. Use `tensor.item()`')
    new_view = self.__build_view(key)
    new_tensor = Tensor(self.shape, self.data)
    new_tensor.base_view = new_view
    return new_tensor
    
  def broadcast_to(self: Self, broadcast_shape: Shape) -> Self:
    if self.shape == broadcast_shape:
      return self
    pad_s = pad_left(self.shape, broadcast_shape)
    nt = Tensor(broadcast_shape, self.data, self.dtype, lazy=True)
    for i, v in enumerate(pad_s[0]): 
      if v == 1: nt.strides[i] = 0
    nt.__build_view(None)  
    return nt

  def __broadcast(self: Self, other: Self):
    new_shapes = pad_left(self.shape, other.shape)
    bs = broadcast_shape(*new_shapes)
    a = self.broadcast_to(bs) 
    b = other.broadcast_to(bs)
    return a,b
  
  def __mul__(self, other: Self) -> Self:
    a, b = self.__broadcast(other)
    result = []
    binary_op(lambda x,y: x*y, a,b, 0, 0,0, a.__calc_loops(None), result) 
    return Tensor(a.shape, result, dtype=a.dtype)

  def __add__(self, other: Self) -> Self:
    a, b = self.__broadcast(other)
    result = []
    binary_op(lambda x,y: x+y, a,b, 0, 0,0, a.__calc_loops(None), result) 
    return Tensor(a.shape, result, dtype=a.dtype)

  def __matmul__(self, other) -> Self:
    return self.matmul(other)

  def matmul(self, other: Self) -> Self:
    # 1D x 1D (dot product) 
    if len(self.shape) == 1 and len(other.shape) == 1:
      if self.shape[0] != other.shape[0]: raise RuntimeError(f'inconsistent tensor size, expected tensor [{self.shape[0]}] and src [{other.shape[0]}] to have the same number of elements, but got {self.shape[0]} and {other.shape[0]} elements respectively')
      return Tensor((), sum(map(lambda x: x[0]*x[1], zip(self.data, other.data))))

    # Classic NxM * MxN matrix mult
    if len(self.shape) == 2 and len(other.shape) == 2:
      if self.shape[1] != other.shape[0]: raise RuntimeError('mat1 and mat2 shapes cannot be multiplied ({self.shape[0]}x{self.shape[1]} and {other.shape[0]}x{other.shape[1]})')
      result = sgemm(self, other)
      return Tensor((self.shape[0], other.shape[1]), [x for x in result])

  def reshape(self, *args) -> Self: 
    new_size = prod(args)
    if new_size != self.size: raise RuntimeError('shape \'{args}\' is invalid for input of size {self.size}')
    return Tensor(tuple(args), self.data, dtype=self.dtype)

  def transpose(self, ax0=1, ax1=0):
    new_shape = list(self.shape)
    new_shape[ax0], new_shape[ax1] = new_shape[ax1], new_shape[ax0]
    return Tensor(tuple(new_shape), self.data, dtype=self.dtype) 

  def __repr__(self): return f'tensor({pformat(self.base_view, width=40)})'
  def __str__(self): return self.__repr__()

  @staticmethod
  def zeros(shape: Shape, dtype:DType=dtypes.float32) -> Self: return Tensor(shape, [0.0 if dtype == dtypes.float32 else 0]*prod(shape))

  @staticmethod
  def ones(shape: Shape, dtype:DType=dtypes.float32) -> Self: return Tensor(shape, [1.0 if dtype == dtypes.float32 else 1]*prod(shape))

  @staticmethod
  def arange(x: int, dtype:DType=dtypes.float32) -> Self: return Tensor((x,), [float(i) if dtype == dtypes.float32 else int(i) for i in range(x)], dtype) 
