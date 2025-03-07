import os
import sys
import numpy as np
import torch
from torch.autograd import Variable
import torch.nn as nn
#from qpth.qp import QPFunction
import torch.nn.functional as F
from qpth.qp import QPFunction
import time

def bandwidth(source):
    """
       calculate the bandwidth of RBF kernel using median of distance between support samples
    """
    total = source

    total0 = total.unsqueeze(0).expand(int(total.size(0)), \
                                       int(total.size(0)), \
                                       int(total.size(1)))
    total1 = total.unsqueeze(1).expand(int(total.size(0)), \
                                       int(total.size(0)), \
                                       int(total.size(1)))

    L2_distance = ((total0 - total1) ** 2)
    L2_distance = L2_distance.sum(2)
    a = L2_distance.reshape(-1)
    b = torch.nonzero(a.data).reshape(-1)
    bandwidth_L2 = np.median(a.data[b].cpu())

    return bandwidth_L2


def kernel(source, target, kernel_type, bandwidth_L2):

    """
       Constructs the kernel matrix with the support set and the query set.

       Parameters:
         source:  a (n_shot, dimension, n_query) Tensor.
         target:  a (1, dimension, n_query) Tensor.
         kernel_type: a string. Set as 'tangent' the identity kernel or 'RBF' the RBF kernel.
         bandwidth_L2: a scalar. Represents the bandwidth of RBF kernel.
       Returns: a (tasks_per_batch, n_query, n_way) Tensor.
       """
    total = torch.cat([source, target], dim=0)
    total0 = total.unsqueeze(0).expand(int(total.size(0)), \
                                                                   int(total.size(0)), \
                                                                   int(total.size(1)), \
                                                                   int(total.size(2)))
    total1 = total.unsqueeze(1).expand(int(total.size(0)), \
                                                                   int(total.size(0)), \
                                                                   int(total.size(1)), \
                                                                   int(total.size(2)))

    L2_distance = ((total0 - total1) ** 2).sum(2)
    inner_product = (total0 * total1).sum(2)

    d = total1.size(2)

    if kernel_type == 'RBF':
        kernel_val = 20 * torch.exp(- L2_distance / (2 * d))
        #kernel_val = 20 * torch.exp(- L2_distance / (2 * bandwidth_L2))
    elif kernel_type == 'tangent':
         kernel_val = inner_product

    return kernel_val


def euclidean_metric(a, b):
    #a = torch.div(a, torch.norm(a, dim=1).unsqueeze(1))
    #b = torch.div(b, torch.norm(b, dim=1).unsqueeze(1))
    n = a.shape[0]
    m = b.shape[0]
    a = a.unsqueeze(1).expand(n, m, -1)
    b = b.unsqueeze(0).expand(n, m, -1)
    dist = ((a - b)**2).sum(dim=2)
    return dist

def sqrt_newton_schulz(A, numIters):
    dim = A.shape[0]
    normA = A.mul(A).sum(dim=0).sum(dim=0).sqrt()
    Y = A.div(normA.expand_as(A))
    I = torch.eye(dim, dim).float().cuda()
    Z = torch.eye(dim, dim).float().cuda()
    for i in range(numIters):
        T = 0.5 * (3.0 * I - Z.mm(Y))
        Y = Y.mm(T)
        Z = T.mm(Z)

    # sA = Y * torch.sqrt(normA).view(batchSize, 1, 1).expand_as(A)

    # sA = Y * torch.sqrt(normA).expand_as(A)

    sZ = Z * 1. / torch.sqrt(normA).expand_as(A)
    return sZ


def polar_decompose(input):
    # square_mat = input.mm(input.transpose(0, 1))
    # square_mat = square_mat/torch.norm(torch.diag(square_mat), p=1)
    # ortho_mat = self.sqrt_newton_schulz(square_mat, numIters=1)

    square_mat = input.transpose(0, 1).mm(input)
    sA_minushalf = sqrt_newton_schulz(square_mat, 1)
    ortho_mat = input.mm(sA_minushalf)

    # return ortho_mat

    return ortho_mat.mm(ortho_mat.transpose(0, 1))


def computeGramMatrix(A, B):
    """
    Constructs a linear kernel matrix between A and B.
    We assume that each row in A and B represents a d-dimensional feature vector.
    
    Parameters:
      A:  a (n_batch, n, d) Tensor.
      B:  a (n_batch, m, d) Tensor.
    Returns: a (n_batch, n, m) Tensor.
    """
    
    assert(A.dim() == 3)
    assert(B.dim() == 3)
    assert(A.size(0) == B.size(0) and A.size(2) == B.size(2))

    return torch.bmm(A, B.transpose(1,2))


def binv(b_mat):
    """
    Computes an inverse of each matrix in the batch.
    Pytorch 0.4.1 does not support batched matrix inverse.
    Hence, we are solving AX=I.
    
    Parameters:
      b_mat:  a (n_batch, n, n) Tensor.
    Returns: a (n_batch, n, n) Tensor.
    """

    id_matrix = b_mat.new_ones(b_mat.size(-1)).diag().expand_as(b_mat).cuda()
    b_inv, _ = torch.gesv(id_matrix, b_mat)
    
    return b_inv


def one_hot(indices, depth):
    """
    Returns a one-hot tensor.
    This is a PyTorch equivalent of Tensorflow's tf.one_hot.
        
    Parameters:
      indices:  a (n_batch, m) Tensor or (m) Tensor.
      depth: a scalar. Represents the depth of the one hot dimension.
    Returns: a (n_batch, m, depth) Tensor or (m, depth) Tensor.
    """

    encoded_indicies = torch.zeros(indices.size() + torch.Size([depth])).cuda()
    index = indices.view(indices.size()+torch.Size([1]))
    encoded_indicies = encoded_indicies.scatter_(1,index,1)
    
    return encoded_indicies

def batched_kronecker(matrix1, matrix2):
    matrix1_flatten = matrix1.reshape(matrix1.size()[0], -1)
    matrix2_flatten = matrix2.reshape(matrix2.size()[0], -1)
    return torch.bmm(matrix1_flatten.unsqueeze(2), matrix2_flatten.unsqueeze(1)).reshape([matrix1.size()[0]] + list(matrix1.size()[1:]) + list(matrix2.size()[1:])).permute([0, 1, 3, 2, 4]).reshape(matrix1.size(0), matrix1.size(1) * matrix2.size(1), matrix1.size(2) * matrix2.size(2))


#################  uncomment this if you have installed QPFunction and run Ridge
# def MetaOptNetHead_Ridge(query, support, support_labels, n_way, n_shot, lambda_reg=50.0, double_precision=True):
#     """
#     Fits the support set with ridge regression and
#     returns the classification score on the query set.
#
#     Parameters:
#       query:  a (tasks_per_batch, n_query, d) Tensor.
#       support:  a (tasks_per_batch, n_support, d) Tensor.
#       support_labels: a (tasks_per_batch, n_support) Tensor.
#       n_way: a scalar. Represents the number of classes in a few-shot classification task.
#       n_shot: a scalar. Represents the number of support examples given per class.
#       lambda_reg: a scalar. Represents the strength of L2 regularization.
#     Returns: a (tasks_per_batch, n_query, n_way) Tensor.
#     """
#
#     tasks_per_batch = query.size(0)
#     n_support = support.size(1)
#     n_query = query.size(1)
#
#     assert(query.dim() == 3)
#     assert(support.dim() == 3)
#     assert(query.size(0) == support.size(0) and query.size(2) == support.size(2))
#     assert(n_support == n_way * n_shot)      # n_support must equal to n_way * n_shot
#
#     #Here we solve the dual problem:
#     #Note that the classes are indexed by m & samples are indexed by i.
#     #min_{\alpha}  0.5 \sum_m ||w_m(\alpha)||^2 + \sum_i \sum_m e^m_i alpha^m_i
#
#     #where w_m(\alpha) = \sum_i \alpha^m_i x_i,
#
#     #\alpha is an (n_support, n_way) matrix
#     kernel_matrix = computeGramMatrix(support, support)
#     kernel_matrix += lambda_reg * torch.eye(n_support).expand(tasks_per_batch, n_support, n_support).cuda()
#
#     block_kernel_matrix = kernel_matrix.repeat(n_way, 1, 1) #(n_way * tasks_per_batch, n_support, n_support)
#
#     support_labels_one_hot = one_hot(support_labels.view(tasks_per_batch * n_support), n_way) # (tasks_per_batch * n_support, n_way)
#     support_labels_one_hot = support_labels_one_hot.transpose(0, 1) # (n_way, tasks_per_batch * n_support)
#     support_labels_one_hot = support_labels_one_hot.reshape(n_way * tasks_per_batch, n_support)     # (n_way*tasks_per_batch, n_support)
#
#     G = block_kernel_matrix
#     e = -2.0 * support_labels_one_hot
#
#     #This is a fake inequlity constraint as qpth does not support QP without an inequality constraint.
#     id_matrix_1 = torch.zeros(tasks_per_batch*n_way, n_support, n_support)
#     C = Variable(id_matrix_1)
#     h = Variable(torch.zeros((tasks_per_batch*n_way, n_support)))
#     dummy = Variable(torch.Tensor()).cuda()      # We want to ignore the equality constraint.
#
#     #if double_precision:
#     G, e, C, h = [x.double().cuda() for x in [G, e, C, h]]
#
#
#     qp_sol = QPFunction(verbose=False)(G, e.detach(), C.detach(), h.detach(), dummy.detach(), dummy.detach())
#     qp_sol = qp_sol.reshape(n_way, tasks_per_batch, n_support)
#     qp_sol = qp_sol.permute(1, 2, 0)
#
#
#     # Compute the classification score.
#     compatibility = computeGramMatrix(support, query)
#     compatibility = compatibility.float()
#     compatibility = compatibility.unsqueeze(3).expand(tasks_per_batch, n_support, n_query, n_way)
#     qp_sol = qp_sol.reshape(tasks_per_batch, n_support, n_way)
#     logits = qp_sol.float().unsqueeze(2).expand(tasks_per_batch, n_support, n_query, n_way)
#     logits = logits * compatibility
#     logits = torch.sum(logits, 1)
#
#     return logits


def MetaOptNetHead_SVM_CS(query, support, support_labels, n_way, n_shot, C_reg=0.1, double_precision=False, maxIter=15):
    """
    Fits the support set with multi-class SVM and
    returns the classification score on the query set.

    This is the multi-class SVM presented in:
    On the Algorithmic Implementation of Multiclass Kernel-based Vector Machines
    (Crammer and Singer, Journal of Machine Learning Research 2001).

    This model is the classification head that we use for the final version.
    Parameters:
      query:  a (tasks_per_batch, n_query, d) Tensor.
      support:  a (tasks_per_batch, n_support, d) Tensor.
      support_labels: a (tasks_per_batch, n_support) Tensor.
      n_way: a scalar. Represents the number of classes in a few-shot classification task.
      n_shot: a scalar. Represents the number of support examples given per class.
      C_reg: a scalar. Represents the cost parameter C in SVM.
    Returns: a (tasks_per_batch, n_query, n_way) Tensor.
    """

    tasks_per_batch = query.size(0)
    n_support = support.size(1)
    n_query = query.size(1)

    assert (query.dim() == 3)
    assert (support.dim() == 3)
    assert (query.size(0) == support.size(0) and query.size(2) == support.size(2))
    assert (n_support == n_way * n_shot)  # n_support must equal to n_way * n_shot

    # Here we solve the dual problem:
    # Note that the classes are indexed by m & samples are indexed by i.
    # min_{\alpha}  0.5 \sum_m ||w_m(\alpha)||^2 + \sum_i \sum_m e^m_i alpha^m_i
    # s.t.  \alpha^m_i <= C^m_i \forall m,i , \sum_m \alpha^m_i=0 \forall i

    # where w_m(\alpha) = \sum_i \alpha^m_i x_i,
    # and C^m_i = C if m  = y_i,
    # C^m_i = 0 if m != y_i.
    # This borrows the notation of liblinear.

    # \alpha is an (n_support, n_way) matrix
    kernel_matrix = computeGramMatrix(support, support)

    id_matrix_0 = torch.eye(n_way).expand(tasks_per_batch, n_way, n_way).cuda()
    block_kernel_matrix = batched_kronecker(kernel_matrix, id_matrix_0)
    # This seems to help avoid PSD error from the QP solver.
    block_kernel_matrix += 1.0 * torch.eye(n_way * n_support).expand(tasks_per_batch, n_way * n_support,
                                                                     n_way * n_support).cuda()

    support_labels_one_hot = one_hot(support_labels.view(tasks_per_batch * n_support),
                                     n_way)  # (tasks_per_batch * n_support, n_support)
    support_labels_one_hot = support_labels_one_hot.view(tasks_per_batch, n_support, n_way)
    support_labels_one_hot = support_labels_one_hot.reshape(tasks_per_batch, n_support * n_way)

    G = block_kernel_matrix
    e = -1.0 * support_labels_one_hot
    # print (G.size())
    # This part is for the inequality constraints:
    # \alpha^m_i <= C^m_i \forall m,i
    # where C^m_i = C if m  = y_i,
    # C^m_i = 0 if m != y_i.
    id_matrix_1 = torch.eye(n_way * n_support).expand(tasks_per_batch, n_way * n_support, n_way * n_support)
    C = Variable(id_matrix_1)
    h = Variable(C_reg * support_labels_one_hot)
    # print (C.size(), h.size())
    # This part is for the equality constraints:
    # \sum_m \alpha^m_i=0 \forall i
    id_matrix_2 = torch.eye(n_support).expand(tasks_per_batch, n_support, n_support).cuda()

    A = Variable(batched_kronecker(id_matrix_2, torch.ones(tasks_per_batch, 1, n_way).cuda()))
    b = Variable(torch.zeros(tasks_per_batch, n_support))
    # print (A.size(), b.size())
    if double_precision:
        G, e, C, h, A, b = [x.double().cuda() for x in [G, e, C, h, A, b]]
    else:
        G, e, C, h, A, b = [x.float().cuda() for x in [G, e, C, h, A, b]]

    # Solve the following QP to fit SVM:
    #        \hat z =   argmin_z 1/2 z^T G z + e^T z
    #                 subject to Cz <= h
    # We use detach() to prevent backpropagation to fixed variables.
    qp_sol = QPFunction(verbose=False, maxIter=maxIter)(G, e.detach(), C.detach(), h.detach(), A.detach(), b.detach())

    # Compute the classification score.
    compatibility = computeGramMatrix(support, query)
    compatibility = compatibility.float()
    compatibility = compatibility.unsqueeze(3).expand(tasks_per_batch, n_support, n_query, n_way)
    qp_sol = qp_sol.reshape(tasks_per_batch, n_support, n_way)
    logits = qp_sol.float().unsqueeze(2).expand(tasks_per_batch, n_support, n_query, n_way)
    logits = logits * compatibility
    logits = torch.sum(logits, 1)

    return logits

def R2D2Head(query, support, support_labels, n_way, n_shot, l2_regularizer_lambda=50.0):
    """
    Fits the support set with ridge regression and 
    returns the classification score on the query set.
    
    This model is the classification head described in:
    Meta-learning with differentiable closed-form solvers
    (Bertinetto et al., in submission to NIPS 2018).
    
    Parameters:
      query:  a (tasks_per_batch, n_query, d) Tensor.
      support:  a (tasks_per_batch, n_support, d) Tensor.
      support_labels: a (tasks_per_batch, n_support) Tensor.
      n_way: a scalar. Represents the number of classes in a few-shot classification task.
      n_shot: a scalar. Represents the number of support examples given per class.
      l2_regularizer_lambda: a scalar. Represents the strength of L2 regularization.
    Returns: a (tasks_per_batch, n_query, n_way) Tensor.
    """
    
    tasks_per_batch = query.size(0)
    n_support = support.size(1)

    assert(query.dim() == 3)
    assert(support.dim() == 3)
    assert(query.size(0) == support.size(0) and query.size(2) == support.size(2))
    assert(n_support == n_way * n_shot)      # n_support must equal to n_way * n_shot
    
    support_labels_one_hot = one_hot(support_labels.view(tasks_per_batch * n_support), n_way)
    support_labels_one_hot = support_labels_one_hot.view(tasks_per_batch, n_support, n_way)

    id_matrix = torch.eye(n_support).expand(tasks_per_batch, n_support, n_support).cuda()
    
    # Compute the dual form solution of the ridge regression.
    # W = X^T(X X^T - lambda * I)^(-1) Y
    ridge_sol = computeGramMatrix(support, support) + l2_regularizer_lambda * id_matrix
    ridge_sol = binv(ridge_sol)
    ridge_sol = torch.bmm(support.transpose(1,2), ridge_sol)
    ridge_sol = torch.bmm(ridge_sol, support_labels_one_hot)
    
    # Compute the classification score.
    # score = W X
    logits = torch.bmm(query, ridge_sol)

    return logits


def MetaOptNetHead_Ridge(query, support, support_labels, n_way, n_shot, lambda_reg=50.0, double_precision=False):
    """
    Fits the support set with ridge regression and
    returns the classification score on the query set.

    Parameters:
      query:  a (tasks_per_batch, n_query, d) Tensor.
      support:  a (tasks_per_batch, n_support, d) Tensor.
      support_labels: a (tasks_per_batch, n_support) Tensor.
      n_way: a scalar. Represents the number of classes in a few-shot classification task.
      n_shot: a scalar. Represents the number of support examples given per class.
      lambda_reg: a scalar. Represents the strength of L2 regularization.
    Returns: a (tasks_per_batch, n_query, n_way) Tensor.
    """

    tasks_per_batch = query.size(0)
    n_support = support.size(1)
    n_query = query.size(1)

    assert (query.dim() == 3)
    assert (support.dim() == 3)
    assert (query.size(0) == support.size(0) and query.size(2) == support.size(2))
    assert (n_support == n_way * n_shot)  # n_support must equal to n_way * n_shot

    # Here we solve the dual problem:
    # Note that the classes are indexed by m & samples are indexed by i.
    # min_{\alpha}  0.5 \sum_m ||w_m(\alpha)||^2 + \sum_i \sum_m e^m_i alpha^m_i

    # where w_m(\alpha) = \sum_i \alpha^m_i x_i,

    # \alpha is an (n_support, n_way) matrix
    kernel_matrix = computeGramMatrix(support, support)
    kernel_matrix += lambda_reg * torch.eye(n_support).expand(tasks_per_batch, n_support, n_support).cuda()

    block_kernel_matrix = kernel_matrix.repeat(n_way, 1, 1)  # (n_way * tasks_per_batch, n_support, n_support)

    support_labels_one_hot = one_hot(support_labels.view(tasks_per_batch * n_support),
                                     n_way)  # (tasks_per_batch * n_support, n_way)
    support_labels_one_hot = support_labels_one_hot.transpose(0, 1)  # (n_way, tasks_per_batch * n_support)
    support_labels_one_hot = support_labels_one_hot.reshape(n_way * tasks_per_batch,
                                                            n_support)  # (n_way*tasks_per_batch, n_support)

    G = block_kernel_matrix
    e = -2.0 * support_labels_one_hot

    # This is a fake inequlity constraint as qpth does not support QP without an inequality constraint.
    id_matrix_1 = torch.zeros(tasks_per_batch * n_way, n_support, n_support)
    C = Variable(id_matrix_1)
    h = Variable(torch.zeros((tasks_per_batch * n_way, n_support)))
    dummy = Variable(torch.Tensor()).cuda()  # We want to ignore the equality constraint.

    if double_precision:
        G, e, C, h = [x.double().cuda() for x in [G, e, C, h]]

    else:
        G, e, C, h = [x.float().cuda() for x in [G, e, C, h]]

    # Solve the following QP to fit SVM:
    #        \hat z =   argmin_z 1/2 z^T G z + e^T z
    #                 subject to Cz <= h
    # We use detach() to prevent backpropagation to fixed variables.
    qp_sol = QPFunction(verbose=False)(G, e.detach(), C.detach(), h.detach(), dummy.detach(), dummy.detach())
    # qp_sol = QPFunction(verbose=False)(G, e.detach(), dummy.detach(), dummy.detach(), dummy.detach(), dummy.detach())

    # qp_sol (n_way*tasks_per_batch, n_support)
    qp_sol = qp_sol.reshape(n_way, tasks_per_batch, n_support)
    # qp_sol (n_way, tasks_per_batch, n_support)
    qp_sol = qp_sol.permute(1, 2, 0)
    # qp_sol (tasks_per_batch, n_support, n_way)

    # Compute the classification score.
    compatibility = computeGramMatrix(support, query)
    compatibility = compatibility.float()
    compatibility = compatibility.unsqueeze(3).expand(tasks_per_batch, n_support, n_query, n_way)
    qp_sol = qp_sol.reshape(tasks_per_batch, n_support, n_way)
    logits = qp_sol.float().unsqueeze(2).expand(tasks_per_batch, n_support, n_query, n_way)
    logits = logits * compatibility
    logits = torch.sum(logits, 1)

    return logits

def ProtoNetHead(query, support, support_labels, n_way, n_shot, normalize=True):
    """
    Constructs the prototype representation of each class(=mean of support vectors of each class) and 
    returns the classification score (=L2 distance to each class prototype) on the query set.
    
    This model is the classification head described in:
    Prototypical Networks for Few-shot Learning
    (Snell et al., NIPS 2017).
    
    Parameters:
      query:  a (tasks_per_batch, n_query, d) Tensor.
      support:  a (tasks_per_batch, n_support, d) Tensor.
      support_labels: a (tasks_per_batch, n_support) Tensor.
      n_way: a scalar. Represents the number of classes in a few-shot classification task.
      n_shot: a scalar. Represents the number of support examples given per class.
      normalize: a boolean. Represents whether if we want to normalize the distances by the embedding dimension.
    Returns: a (tasks_per_batch, n_query, n_way) Tensor.
    """
    
    tasks_per_batch = query.size(0)
    n_support = support.size(1)
    n_query = query.size(1)
    d = query.size(2)
    
    assert(query.dim() == 3)
    assert(support.dim() == 3)
    assert(query.size(0) == support.size(0) and query.size(2) == support.size(2))
    assert(n_support == n_way * n_shot)      # n_support must equal to n_way * n_shot
    
    support_labels_one_hot = one_hot(support_labels.view(tasks_per_batch * n_support), n_way)
    support_labels_one_hot = support_labels_one_hot.view(tasks_per_batch, n_support, n_way)
    
    # From:
    # https://github.com/gidariss/FewShotWithoutForgetting/blob/master/architectures/PrototypicalNetworksHead.py
    #************************* Compute Prototypes **************************
    labels_train_transposed = support_labels_one_hot.transpose(1,2)

    prototypes = torch.bmm(labels_train_transposed, support)
    # Divide with the number of examples per novel category.
    prototypes = prototypes.div(
        labels_train_transposed.sum(dim=2, keepdim=True).expand_as(prototypes)
    )

    # Distance Matrix Vectorization Trick
    AB = computeGramMatrix(query, prototypes)
    AA = (query * query).sum(dim=2, keepdim=True)
    BB = (prototypes * prototypes).sum(dim=2, keepdim=True).reshape(tasks_per_batch, 1, n_way)
    logits = AA.expand_as(AB) - 2 * AB + BB.expand_as(AB)
    logits = -logits
    
    if normalize:
        logits = logits / d

    return logits

def SubspaceNetHead(query, support, support_labels, n_way, n_shot, normalize=True):

    """
       Constructs the subspace representation of each class and
       returns the classification score (=L2 distance to each class prototype) on the query set.

      This model is the classification head described in:
      Adaptive Subspaces for Few-Shot Learning
      (Christian Simon et al., CVPR 2020).

       Parameters:
         query:  a (tasks_per_batch, n_query, d) Tensor.
         support:  a (tasks_per_batch, n_support, d) Tensor.
         support_labels: a (tasks_per_batch, n_support) Tensor.
         n_way: a scalar. Represents the number of classes in a few-shot classification task.
         n_shot: a scalar. Represents the number of support examples given per class.
         normalize: a boolean. Represents whether if we want to normalize the distances by the embedding dimension.
       Returns: a (tasks_per_batch, n_query, n_way) Tensor.
       """

    tasks_per_batch = query.size(0)
    n_support = support.size(1)
    n_query = query.size(1)
    d = query.size(2)

    assert(query.dim() == 3)
    assert(support.dim() == 3)
    assert(query.size(0) == support.size(0) and query.size(2) == support.size(2))
    assert(n_support == n_way * n_shot)      # n_support must equal to n_way * n_shot

    support_labels_one_hot = one_hot(support_labels.view(tasks_per_batch * n_support), n_way)
    #support_labels_one_hot = support_labels_one_hot.view(tasks_per_batch, n_support, n_way)


    support_reshape = support.view(tasks_per_batch * n_support, -1)

    support_labels_reshaped = support_labels.contiguous().view(-1)
    class_representatives = []
    for nn in range(n_way):
        idxss = (support_labels_reshaped == nn).nonzero()
        all_support_perclass = support_reshape[idxss, :]
        class_representatives.append(all_support_perclass.view(tasks_per_batch, n_shot, -1))

    class_representatives = torch.stack(class_representatives)
    class_representatives = class_representatives.transpose(0, 1) #tasks_per_batch, n_way, n_support, -1
    class_representatives = class_representatives.transpose(2, 3).contiguous().view(tasks_per_batch*n_way, -1, n_shot)

    dist = []
    for cc in range(tasks_per_batch*n_way):
        batch_idx = cc//n_way
        qq = query[batch_idx]
        rr = class_representatives[cc]

        mean_ = torch.mean(rr, dim=1, keepdim=True)
        rr = rr - mean_
        qq = qq - mean_.transpose(0, 1)
        uu, _, _ = torch.svd(rr.double())
        uu = uu.float()
        subspace = uu[:, :n_shot].transpose(0, 1)
        projection = subspace.transpose(0, 1).mm(subspace.mm(qq.transpose(0, 1))).transpose(0, 1)
        dist_perclass = torch.sum((qq - projection)**2, dim=-1)
        dist.append(dist_perclass)

    dist = torch.stack(dist).view(tasks_per_batch, n_way, -1).transpose(1, 2)
    logits = -dist

    if normalize:
        logits = logits / d

    return logits

def ExemplarHead(query, support, support_labels, n_way, n_shot, lam =100000, normalize=True, type='s2'):#lam = 10**6

    """
       Constructs the subspace representation of each class and
       returns the classification score (=L2 distance to each class prototype) on the query set.

      This model is the classification head described in:
      Adaptive Subspaces for Few-Shot Learning
      (Christian Simon et al., CVPR 2020).

       Parameters:
         query:  a (tasks_per_batch, n_query, d) Tensor.
         support:  a (tasks_per_batch, n_support, d) Tensor.
         support_labels: a (tasks_per_batch, n_support) Tensor.
         n_way: a scalar. Represents the number of classes in a few-shot classification task.
         n_shot: a scalar. Represents the number of support examples given per class.
         normalize: a boolean. Represents whether if we want to normalize the distances by the embedding dimension.
       Returns: a (tasks_per_batch, n_query, n_way) Tensor.
    """

    tasks_per_batch = query.size(0)
    n_support = support.size(1)
    n_query = query.size(1)
    d = query.size(2)

    assert(query.dim() == 3)
    assert(support.dim() == 3)
    assert(query.size(0) == support.size(0) and query.size(2) == support.size(2))
    assert(n_support == n_way * n_shot)      # n_support must equal to n_way * n_shot

    support_reshape = support.view(tasks_per_batch * n_support, -1)

    support_labels_reshaped = support_labels.contiguous().view(-1)

    class_representatives = []
    for nn in range(n_way):
        idxss = (support_labels_reshaped == nn).nonzero()
        all_support_perclass = support_reshape[idxss, :]
        noise_ = np.random.normal(0, 4, (tasks_per_batch * n_shot, d))
        noise_1 = torch.from_numpy(noise_)
        noise_1 = noise_1.unsqueeze(1)

        class_representatives.append(
            all_support_perclass.view(tasks_per_batch, n_shot, -1) + noise_1.view(tasks_per_batch, n_shot,
                                                                                  -1).cuda().float())

        #class_representatives.append(all_support_perclass.view(tasks_per_batch, n_shot, -1))

    class_representatives = torch.stack(class_representatives)
    class_representatives = class_representatives.transpose(0, 1)  # tasks_per_batch, n_way, n_support, -1
    class_representatives = class_representatives.transpose(2, 3).contiguous().view(tasks_per_batch * n_way, -1, n_shot)

    dist = []
    for cc in range(tasks_per_batch*n_way):
        batch_idx = cc//n_way
        qq = query[batch_idx]
        rr = class_representatives[cc]

        mean_ = torch.mean(rr, dim=1, keepdim=True)
        rr = rr - mean_
        qq = qq - mean_.transpose(0, 1)
        uu, ss, _ = torch.svd(rr.double())
        uu = uu.float()
        ss_2 = (ss ** 2 ) / (lam + ss ** 2)
        ss_2 = ss_2.unsqueeze(1).float()

        subspace2 = uu.transpose(0, 1)

        if type == 's1':

            part1 = torch.mm(torch.mm(uu, ss_2 * (uu.transpose(0, 1))), qq.transpose(0, 1)).transpose(0, 1)
            part2 = torch.mm(torch.mm(uu, ss_2 * (uu.transpose(0, 1))), rr).transpose(0, 1)
            part3 = qq - subspace2.transpose(0, 1).mm(subspace2.mm(qq.transpose(0, 1))).transpose(0, 1)
            part4 = rr.transpose(0, 1) - subspace2.transpose(0, 1).mm(subspace2.mm(rr)).transpose(0, 1)

            dist_perclass = euclidean_metric(part1 + part3, part2 + part4)

        elif type == 's2':

            dist_perclass = euclidean_metric(qq, torch.mm(torch.mm(uu, ss_2 * (uu.transpose(0, 1))), rr).transpose(0, 1))

        dist.append(dist_perclass)

    dist = torch.stack(dist).view(tasks_per_batch, n_way, n_query, -1).transpose(1, 2)

    logits = -dist

    if normalize:
        logits = logits / d

    return logits
'''
def ExemplarHead(query, support, support_labels, n_way, n_shot, normalize=True, lam = float('inf')):#lam = 10**6
    """
       Constructs the subspace representation of each class and
       returns the classification score (=L2 distance to each class prototype) on the query set.

      This model is the classification head described in:
      Adaptive Subspaces for Few-Shot Learning
      (Christian Simon et al., CVPR 2020).

       Parameters:
         query:  a (tasks_per_batch, n_query, d) Tensor.
         support:  a (tasks_per_batch, n_support, d) Tensor.
         support_labels: a (tasks_per_batch, n_support) Tensor.
         n_way: a scalar. Represents the number of classes in a few-shot classification task.
         n_shot: a scalar. Represents the number of support examples given per class.
         normalize: a boolean. Represents whether if we want to normalize the distances by the embedding dimension.
       Returns: a (tasks_per_batch, n_query, n_way) Tensor.
"""

    tasks_per_batch = query.size(0)
    n_support = support.size(1)
    n_query = query.size(1)
    d = query.size(2)

    assert(query.dim() == 3)
    assert(support.dim() == 3)
    assert(query.size(0) == support.size(0) and query.size(2) == support.size(2))
    assert(n_support == n_way * n_shot)      # n_support must equal to n_way * n_shot

    support_reshape = support.view(tasks_per_batch * n_support, -1)

    support_labels_reshaped = support_labels.contiguous().view(-1)

    class_representatives = []
    for nn in range(n_way):
        idxss = (support_labels_reshaped == nn).nonzero()
        all_support_perclass = support_reshape[idxss, :]
        class_representatives.append(all_support_perclass.view(tasks_per_batch, n_shot, -1))

    class_representatives = torch.stack(class_representatives)
    class_representatives = class_representatives.transpose(0, 1) #tasks_per_batch, n_way, n_support, -1
    class_representatives = class_representatives.contiguous().view(tasks_per_batch*n_way, n_shot, -1)

    dist = []
    for cc in range(tasks_per_batch*n_way):
        batch_idx = cc//n_way
        qq = query[batch_idx].transpose(0, 1)
        rr = class_representatives[cc].transpose(0, 1)
        rr_re = rr - torch.mean(rr, dim=1, keepdim=True)
        qq_re = qq - torch.mean(rr, dim=1, keepdim=True)
        #M_rr = torch.mm(rr_re, rr_re.transpose(0, 1))
        uu, ss, _ = torch.linalg.svd(rr_re.double())
        ss_2 = torch.cat((ss**2 / (lam + ss**2), torch.ones(d-n_shot).cuda()), 0)
        #ss_2 = torch.diag_embed(torch.cat((ss ** 2, torch.zeros(d - n_shot).cuda()), 0))
        uu = uu.float()
        ss_2 = ss_2.unsqueeze(1).float()
        MM = torch.mm(uu, ss_2 * (uu.transpose(0, 1)))
        qq_M = torch.mm(MM, qq_re)
        rr_M = torch.mm(MM, rr_re)
        #dist_perclass = euclidean_metric(qq_M.transpose(0, 1), rr_M.transpose(0, 1))
        dist_perclass = torch.sum(qq_M**2, dim=0)
        dist.append(dist_perclass)

    #dist = torch.stack(dist).view(tasks_per_batch, n_way, n_query, -1).transpose(1, 2)
    dist = torch.stack(dist).view(tasks_per_batch, n_way, -1).transpose(1, 2)

    logits = -dist

    if normalize:
        logits = logits / d

    return logits#(logits,SubspaceNetHead(query, support, support_labels, n_way, n_shot))
'''
def ShrinkageNetHead(query, support, support_labels, n_way, n_shot,
                     s_T=0.01,kernel_type='tangent', use_shrinkage=True, shrinkage_type='Tikhonov'):

    """
       Constructs the shrinkage representation of each class and
       returns the classification score (=L2 distance to each class prototype) on the query set.

       Our algorithm using shrinkage representation here

       Parameters:
         query:  a (tasks_per_batch, n_query, d) Tensor.
         support:  a (tasks_per_batch, n_support, d) Tensor.
         support_labels: a (tasks_per_batch, n_support) Tensor.
         n_way: a scalar. Represents the number of classes in a few-shot classification task.
         n_shot: a scalar. Represents the number of support examples given per class.
         s_T: a scalar. Represents the shrinkage coefficient.
         kernel_type: a string. Set as 'tangent' the identity kernel or 'RBF' the RBF kernel.
         use_shrinkage:  a boolean. Represents whether to use the shrink function.
         shrinkage_type: a string. The filter function set as 'Tikhonov' the Tikhonov regularization or 'TSVD' the Truncated SVD.
       Returns: a (tasks_per_batch, n_query, n_way) Tensor.
       """

    tasks_per_batch = query.size(0)
    n_support = support.size(1)
    n_query = query.size(1)
    d = query.size(2)

    assert(query.dim() == 3)
    assert(support.dim() == 3)
    assert(query.size(0) == support.size(0) and query.size(2) == support.size(2))
    assert(n_support == n_way * n_shot)      # n_support must equal to n_way * n_shot

    support_labels_one_hot = one_hot(support_labels.view(tasks_per_batch * n_support), n_way)
    #support_labels_one_hot = support_labels_one_hot.view(tasks_per_batch, n_support, n_way)

    support_reshape = support.view(tasks_per_batch * n_support, -1)

    support_labels_reshaped = support_labels.contiguous().view(-1)
    class_representatives = []

    for nn in range(n_way):
        idxss = (support_labels_reshaped == nn).nonzero()
        all_support_perclass = support_reshape[idxss, :]
        class_representatives.append(all_support_perclass.view(tasks_per_batch, n_shot, -1))

    class_representatives = torch.stack(class_representatives)
    class_representatives = class_representatives.transpose(0, 1)
    class_representatives = class_representatives.contiguous().view(tasks_per_batch*n_way,  n_shot, -1)

    bandwidth_L2 = bandwidth(support.view(support.size(0) * support.size(1), -1))

    dist = []
    for cc in range(tasks_per_batch*n_way):
        batch_idx = cc//n_way
        target = query[batch_idx]
        source = class_representatives[cc]

        source = source.unsqueeze(2).repeat_interleave(n_query, dim=2)
        target = target.unsqueeze(0).transpose(1, 2)

        kernels = kernel(source, target, kernel_type, bandwidth_L2)

        K_ss = kernels[:n_shot, :n_shot, :].repeat(1, 1, 1).permute(2, 0, 1).cuda()
        K_qq = kernels[n_shot:, n_shot:, :].repeat(n_shot, n_shot, 1).permute(2, 0, 1).cuda()
        K_qs = kernels[:n_shot, n_shot:, :].repeat(1, n_shot, 1).permute(2, 0, 1).cuda()
        K_sq = kernels[n_shot:, :n_shot, :].repeat(n_shot, 1, 1).permute(2, 0, 1).cuda()

        I_nn = (torch.ones(K_ss.size(0), n_shot, n_shot) / n_shot).cuda()

        hat_K_ss = K_ss + torch.matmul(torch.matmul(I_nn, K_ss), I_nn) - torch.matmul(K_ss, I_nn) - torch.matmul(I_nn, K_ss)
        hat_K_qq = K_ss + K_qq - K_qs - K_sq
        hat_K_qs = K_qs - torch.matmul(I_nn, K_qs) - K_ss + torch.matmul(I_nn, K_ss)

        S, V = torch.linalg.eig(hat_K_ss.double())

        S = torch.real(S)
        S = S.float()
        V = torch.real(V)
        V = V.float()



        if use_shrinkage:
            if shrinkage_type == "TSVD":
                SLambda = (n_shot - 1) * torch.ones(n_query, 1).cuda()
                SS, ind1 = torch.sort(S, dim=1, descending=True)
                ind = ((SLambda - 1) * (SLambda- 1 >= -0.5)).type_as(ind1)
                mask = (S - SS.gather(1, ind) + 10 ** (-6) >= 0).cuda()
                Sg = ((S + 10 ** (-12)) ** (-1)).cuda() * (SLambda- 1 >= -0.5).cuda()
                Sg = Sg * mask
                C = torch.diag_embed(Sg)
            else:
                if shrinkage_type == "Tikhonov":
                    SS_final, _ = torch.sort(S, dim=1, descending=True)
                    SS_final1, _ = torch.sort(SS_final, dim=0, descending=True)
                    SLambda = s_T * SS_final[:, 0].unsqueeze(1).cuda()
                    #SLambda = s_T * SS_final1[0,0] * torch.ones(n_query, 1).cuda() #test
                    Sg = ((S + SLambda + 10 ** (-12)) ** (-1)).cuda()
                    C = torch.diag_embed(Sg)

            g_KSS = torch.matmul(torch.matmul(V.cuda(), C.cuda()), torch.transpose(V, 2, 1).cuda())
            alpha = torch.matmul(g_KSS.cuda(), hat_K_qs.cuda()).sum(2) / g_KSS.size(2)
            alpha = alpha.unsqueeze(2).cuda()
        else:
            alpha = torch.zeros(n_query, n_shot, 1).cuda()

        I_n = (torch.ones(alpha.size(0), n_shot, 1) / n_shot).cuda()

        dist_per_tasksperbatch = torch.matmul(torch.matmul(torch.transpose(alpha, 1, 2), hat_K_ss), alpha) + \
                                                      torch.matmul(torch.matmul(torch.transpose(I_n, 1, 2), hat_K_qq), I_n) - \
                                                2 * torch.matmul(torch.matmul(torch.transpose(alpha, 1, 2), hat_K_qs), I_n)

        dist_per_tasksperbatch = dist_per_tasksperbatch.squeeze(1).squeeze(1)
        dist.append(dist_per_tasksperbatch)

    dist = torch.stack(dist).view(tasks_per_batch, n_way, -1).transpose(1, 2)
    logits = -dist

    if kernel_type == 'tangent':
        logits = logits / d

    return logits


class ClassificationHead(nn.Module):
    def __init__(self, base_learner='MetaOptNet', enable_scale=True):
        super(ClassificationHead, self).__init__()
        if ('Subspace' in base_learner):
            self.head = SubspaceNetHead
        elif ('Ridge' in base_learner):
            self.head = MetaOptNetHead_Ridge
        elif ('Shrinkage' in base_learner):
            self.head = ShrinkageNetHead
        elif ('R2D2' in base_learner):
            self.head = R2D2Head
        elif ('Proto' in base_learner):
            self.head = ProtoNetHead
        elif ('SVM-CS' in base_learner):
            self.head = MetaOptNetHead_SVM_CS
        elif ('Exemplar' in base_learner):
            self.head = ExemplarHead
        else:
            print ("Cannot recognize the base learner type")
            assert(False)
        
        # Add a learnable scale
        self.enable_scale = enable_scale
        self.scale = nn.Parameter(torch.FloatTensor([1.0]))
        self.shrink = nn.Parameter(torch.FloatTensor([10000.0]))
        
    def forward(self, query, support, support_labels, n_way, n_shot, **kwargs):
        if self.enable_scale:
            return self.scale * self.head(query, support, support_labels, n_way, n_shot, self.shrink, **kwargs)
        else:
            return self.head(query, support, support_labels, n_way, n_shot, **kwargs)
