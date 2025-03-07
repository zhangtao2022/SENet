# Kernel Relative-prototype Spectral Filtering for Few-shot Learning

This repository contains the code for the paper: [Kernel Relative-prototype Spectral Filtering for Few-shot Learning](https://www.ecva.net/papers/eccv_2022/papers_ECCV/papers/136800527.pdf)
 
## Dependencies:
* Python 3.9.7
* PyTorch 1.11.0
* qpth 0.0.15
* tqdm
 
 ## Dataset:
[**miniImageNet**](https://drive.google.com/file/d/1fJAK5WZTjerW7EWHHQAR9pRJVNg1T1Y7), [**tieredImageNet**](https://drive.google.com/file/d/1nVGCTd9ttULRXFezh4xILQ9lUkg0WZCG), [**CIFAR-FS**](https://www.cs.toronto.edu/~kriz/cifar-100-python.tar.gz)

## Training:
1. Train shrinkage classifier using ResNet-12 on 5-way mini-ImageNet 5-shot/1-shot benchmark:
    ```bash
    python train.py --gpu 0,1,2,3 --save-path "./experiments/miniImageNet_shrinkage" --train-shot 15 --train-query 10\
    --head shrinkage --network ResNet --dataset miniImageNet --eps 0.1
    ```
2. Train shrinkage classifier using Conv-4 on 5-way mini-ImageNet 5-shot/1-shot benchmark:
    ```bash
    python train.py --gpu 0 --save-path "./experiments/miniImageNet_shrinkage" --train-shot 15 --train-query 10\
    --head shrinkage --network ProtoNet --dataset miniImageNet
    ```
3. Train shrinkage classifier using ResNet-12 on 5-way tieredImageNet  5-shot/1-shot benchmark:
    ```bash
    python train.py --gpu 0,1,2,3 --save-path "./experiments/tieredImageNet_shrinkage" --train-shot 15 --train-query 10\
    --head shrinkage --network ResNet --dataset tieredImageNet
    ```
4. Train shrinkage classifier using ResNet-12 on 5-way CIFAR-FS 1-shot benchmark:
    ```bash
    python train.py --gpu 0 --save-path "./experiments/CIFAR_FS_shrinkage" --train-shot 15 --train-query 10\
    --head shrinkage --network ResNet --dataset CIFAR_FS
    ```

5. Train shrinkage classifier using ResNet-12 on 5-way CIFAR-FS 5-shot benchmark:
    ```bash
    python train.py --gpu 0 --save-path "./experiments/CIFAR_FS_shrinkage" --train-shot 15 --train-query 10\
    --head shrinkage --network ResNet --dataset CIFAR_FS
    ```
## Testing:
1. Test shrinkage classifier with ResNet-12 on 5-way miniImageNet 5-shot benchmark:
```
python test.py --gpu 0 --load ./experiments/miniImageNet_shrinkage/best_model.pth --episode 1000 \
--way 5 --shot 5 --query 15 --head shrinkage --network ResNet --dataset miniImageNet
```

2. Train shrinkage classifier with ResNet-12 on 5-way miniImageNet 1-shot benchmark:
```
python test.py --gpu 0 --load ./experiments/miniImageNet_shrinkage/best_model.pth --episode 1000 \
--way 5 --shot 1 --query 15 --head shrinkage --network ResNet --dataset miniImageNet
```

## Acknowledgement:
This code is based on the codebases:

[Prototypical Network](https://github.com/jakesnell/prototypical-networks),
[MetaOpt](https://github.com/kjunelee/MetaOptNet),
[DSN](https://github.com/chrysts/dsn_fewshot)
