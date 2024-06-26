from typing import Callable, List, Union
import shrimpgrad as shrimp 
from functools import reduce
import math
import operator
from shrimpgrad.runtime.ops import UnaryOps, BinaryOps, TernaryOps, Op
from shrimpgrad.util import calc_loops

def ternary_op(F: Callable, a: shrimp.Tensor, b: shrimp.Tensor, c: shrimp.Tensor, result:Union[List[float|int]|int|float]) -> None:
  if a.is_scalar() and b.is_scalar() and c.is_scalar(): 
    return F(a.data, b.data, c.data)
  def run(loops, dim=0, off_a=0, off_b=0, off_c=0, result=result):
    if not loops:  return 
    s, e, step = loops[0]
    for i in range(s, e, step):
      if len(loops) == 1: result.append(F(a.data[off_a + i*step*a.strides[dim]], b.data[off_b + i*step*b.strides[dim]], c.data[off_c +i*step*c.strides[dim]]))
      else: run(loops[1:], dim+1, off_a + i*a.strides[dim]*step, off_b + i*b.strides[dim]*step, off_c + i*c.strides[dim]*step, result)
    return 
  run(calc_loops(a, None))
  return result

def binary_op(F: Callable, a: shrimp.Tensor, b: shrimp.Tensor, result:Union[List[float|int]|int|float]) -> None:
  if a.is_scalar() and b.is_scalar(): 
    return F(a.data, b.data)
  def run(loops, dim=0, off_a=0, off_b=0, result=result):
    if not loops:  return 
    s, e, step = loops[0]
    for i in range(s, e, step):
      if len(loops) == 1: result.append(F(a.data[off_a + i*step*a.strides[dim]] , b.data[off_b + i*step*b.strides[dim]]))
      else: run(loops[1:], dim+1, off_a + i*a.strides[dim]*step, off_b + i*b.strides[dim]*step, result)
    return 
  run(calc_loops(a, None))
  return result

def unary_op(F: Callable, a: shrimp.Tensor, result: Union[List[float|int], int, float]) -> None:
  if a.is_scalar():
    return F(a.data)
  def run(loops, dim=0, off=0, result=result):
    if not loops: return
    s, e, step = loops[0]
    for i in range(s, e, step):
      if len(loops) == 1: result.append(F(a.data[off + i*step*a.strides[dim]]))
      else: run(loops[1:], dim+1, off + i*a.strides[dim]*step, result)
    return 
  run(calc_loops(a, None))
  return result

def reduce_op(F: Callable, x: shrimp.Tensor, ax=0):
  assert x.ndim > 0, 'scalars cannot be reduced'
  ax = ax + x.ndim if ax < 0 else ax
  assert ax < x.ndim, f'axis={ax} is out of bounds for tensor with shape={x.shape}'
  def run(loops, off=0, dim=0):
    s,e,step = loops[0]
    res, accum = [], []
    for _ in range(s,e,step):
      if ax == dim: accum.append(x.data[off:off+x.strides[dim]])
      else: res += run(loops[1:], off, dim+1)
      off += x.strides[dim]
    return [reduce(F,r) for r in zip(*accum)] if accum else res 
  return run(calc_loops(x, None))

python_alu = {
  UnaryOps.LOG2: lambda x: math.log2(x) if x > 0 else -math.inf if x == 0 else math.nan,
  UnaryOps.EXP2: lambda x: math.exp(x*math.log(2)),
  UnaryOps.SQRT: lambda x: math.sqrt(x) if x >= 0 else math.nan, UnaryOps.SIN: math.sin,
  UnaryOps.NEG: lambda x: (not x) if isinstance(x, bool) else -x,
  BinaryOps.MUL: operator.mul, BinaryOps.ADD: operator.add, BinaryOps.SUB: operator.sub, BinaryOps.XOR: operator.xor,
  BinaryOps.MAX: max, BinaryOps.CMPEQ: operator.eq, BinaryOps.CMPLT: operator.lt,
  BinaryOps.MOD: lambda x,y: abs(int(x))%abs(int(y))*(1,-1)[x<0],
  BinaryOps.DIV: lambda x,y: int(x/y) if isinstance(x, int) else (x/y if y != 0 else x*math.inf),
  TernaryOps.WHERE: lambda x,y,z: y if x else z}

class PythonRuntime:
  @staticmethod 
  def exec(op: Op, *tensors, **kwargs):
    if op in BinaryOps:
      result = binary_op(python_alu[op], x:=tensors[0], tensors[1], [])
      return shrimp.Tensor(x.shape, result, dtype=x.dtype)
    
    if op in UnaryOps:
      result = unary_op(python_alu[op], x:=tensors[0], [])
      return shrimp.Tensor(x.shape, result, dtype=x.dtype)
    
    if op in TernaryOps:
      result = ternary_op(python_alu[op], x:=tensors[0], tensors[1], tensors[2], [])
      return shrimp.Tensor(x.shape, result, dtype=x.dtype)

    axis = kwargs['ax']
    x = tensors[0]
    if not axis:
      # Reduction of scalar yields no changes
      return shrimp.Tensor((), x.data, x.dtype)
    for ax in axis: 
      ret = reduce_op(operator.add, x, ax=ax)
      x = shrimp.Tensor((*x.shape[0:ax],*[1], *x.shape[ax+1:]), ret)
    return x