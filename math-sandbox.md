## 行级建模

在每个 `case*.tsv` 文件中，一行数据表示一条可行匹配关系：一个运单组合、一个骑手、以及对应的 `cost`。决策变量定义在"候选行是否被选中"上。

### 集合、索引与参数

- $O$：订单集合
- $R$：骑手集合
- $M$：所有候选行集合

对于每个候选项 $m\in M$：

- $S_m \subseteq O$：运单组合（由第一列解析，如 `136,158,653,572`）
- $r_m \in R$：对应骑手（第二列）
- $c_m \in \mathbb{R}$：匹配代价（第三列）

### 决策变量

$$
x_m=
\begin{cases}
1, & \text{若选择候选项 } m,\\
0, & \text{否则}.
\end{cases}
$$

### 0-1 参数

定义两个 0-1 参数：

$$
a_{im}=
\begin{cases}
1, & i \in S_m\\
0, & \text{otherwise}
\end{cases}
\qquad
b_{rm}=
\begin{cases}
1, & r_m = r\\
0, & \text{otherwise}
\end{cases}
$$

### 完整模型（0-1 整数规划）

$$
\min \sum_{m\in M} c_m x_m
$$

$$
\text{s.t.} \quad \sum_{m\in M} b_{rm}\, x_m \le 1, \qquad \forall r\in R
$$

$$
\sum_{m\in M} a_{im}\, x_m = 1, \qquad \forall i\in O
$$

$$
x_m \in \{0,1\}, \qquad \forall m\in M
$$

### 矩阵形式

$$
\min\ c^\top x \quad \text{s.t.} \quad Bx \le \mathbf{1},\quad Ax = \mathbf{1},\quad x \in \{0,1\}^{|M|}
$$

其中 $A \in \{0,1\}^{|O|\times|M|}$，$B \in \{0,1\}^{|R|\times|M|}$，$c \in \mathbb{R}^{|M|}$。

该问题本质上是一个定义在候选行集合上的加权集合划分问题，同时带有骑手侧容量约束，因此属于大规模 0-1 组合优化问题。
