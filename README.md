# ShrimpGrad
![shrimpgrad]("https://github.com/kvkenyon/shrimpgrad/blob/main/logo.png")

## A shrimp sized autograd engine
Tensors are generated the usual way with a pytorch style API. Behind the scenes we create an AST of the computations and minimize memory usage until execution. Given a device we compile the tensor graph to accelerator specific code and execute on device. Right now we are migrating from the python runtime to a general implementation that uses FutureTensors and stack memory (ctypes) to allow interop with accelerator. The first accelerator (again for testing) is clang.

You can look at shrimpgrad/examples to see the usage. We train a linear-relu-sigmoid model on the CPU using python to predict make_moons.
