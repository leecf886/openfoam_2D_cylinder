# 二维圆柱绕流：Re = 200

本算例适用于 **OpenFOAM Foundation 14**（本机安装于 `/opt/openfoam14`）。
`foamRun` 加载 `incompressibleFluid`，采用 laminar 模型和非定常 PIMPLE 求解。
统一入口 `Allrun` 负责恢复初始场、势流初始化、检查网格、MPI 并行求解和逐步记录监控数据。

## 物理参数与现有数值设置

| 参数 | 值 |
| --- | --- |
| 来流速度 | 0.02 m/s，沿 x 正方向 |
| 密度 | 1000 kg/m³ |
| 运动黏度 | 1×10⁻⁶ m²/s |
| 动力黏度 | 0.001 Pa·s |
| 圆柱直径 D | 0.01 m |
| 计算域 | x ∈ [-0.05, 0.20] m，y ∈ [-0.05, 0.05] m |
| 展向厚度 Lz | 0.01 m，单层网格，前后面 empty |
| 网格单元数 | 119744 |
| 雷诺数 | U∞D/ν = 200 |
| 正式计算时间 | 0–70 s |
| 初始时间步 | 0.0001 s |
| 自动时间步 | maxCo = 0.5，maxDeltaT = 0.001 s |
| 场写出间隔 | 0.05 s |
| 时间离散 / 速度对流离散 | backward / Gauss linear |
| PIMPLE | 2 次外循环、2 次压力修正、1 次非正交修正 |

保留本次修改前已有的速度对流格式 `Gauss linear` 及时间参数。
压力使用 GAMG，速度使用 smoothSolver；`potentialFoam` 单独使用 `Phi` 的 GAMG 配置。
`0_org/p` 是运动学压力 p/ρ，单位 m²/s²；乘以密度后为相对压力 Pa。

| 边界 | U | p |
| --- | --- | --- |
| inlet | fixedValue (0.02 0 0) | zeroGradient |
| outlet | zeroGradient | fixedValue 0 |
| top、bottom | symmetryPlane | symmetryPlane |
| cylinder | noSlip | zeroGradient |
| frontAndBack | empty | empty |

`0_org` 是首次备份的原始初始场，内部 U=(0 0 0)、p=0；后续运行不覆盖此备份。
每次全新启动均从 `0_org` 复制出 `0`，再执行势流初始化。需要修改初始条件时编辑 `0_org/U`、`0_org/p`。
势流初始化不是最终黏性流解；圆柱壁面的 noSlip 条件仍由原始场设置保留。

## 从加载环境开始运行

以下命令均在 WSL/Linux 的 Bash 终端中执行。

### 1. 加载 OpenFOAM 并进入目录

```bash
source /opt/openfoam14/etc/bashrc
cd /home/lcf/CFD/projects/2D_cylinder/re200
foamVersion
```

应显示 `OpenFOAM-14`。求解使用系统已有的 MPI；监控图使用 Python 3、matplotlib 和 tkinter。

### 2. 查看当前可用资源

```bash
python3 scripts/resources.py
nproc
free -h
```

资源脚本结合 CPU 亲和性、物理核心拓扑以及 cgroup 的 CPU/内存限制，输出建议进程数。
`Allrun` 每次也会重新检测并保存 `log.resources.json`。

2026-10-21 本机检测：AMD Ryzen 7 8745H，8 个物理核心、16 个逻辑 CPU，
WSL 可见内存约 11.68 GiB，当时可用约 9.5 GiB，交换空间 4 GiB；未发现额外 cgroup 配额。
本机默认使用 **8 个 MPI 进程**，各进程使用一个物理核心，`OMP_NUM_THREADS=1`。
这是 MPI 多进程并行；超线程不保证提高速度。
单机 MPI 使用共享内存通信并关闭不需要的 TCP 数据通道，避免 WSL 虚拟网卡配对警告；
当前脚本面向单台机器，跨机器并行需要另外调整 MPI 通信配置。

### 3. 启动正式计算

```bash
./Allrun
```

默认按当次检测到的可用物理核心数选择进程数。也可以明确指定：

```bash
./Allrun -np 8
```

在有 16 个可用物理核心的机器上可以执行 `./Allrun -np 16`。
当前 8核16线程机器也允许 `-np 16`，此时绑定逻辑 CPU；是否更快需要实测。
`-np 1` 采用串行求解。脚本拒绝超过当前可用 CPU 容量的进程数。
`numberOfSubdomains` 会自动与实际进程数同步，分区方法为 `scotch`。

每次启动依次完成：

1. 检查是否存在旧计算输出，并取得算例运行锁。
2. 从 `0_org` 完整恢复 `0`。`0` 中上次留下的势流场不会混入新计算。
3. 使用已有网格；若网格不存在，调用 `Allmesh`。随后运行 `checkMesh`。
   原始网格有 2 个未被任何面或单元使用的孤立点，它们不参与求解；
   只有这一项已知检查失败且其他检查全部通过时允许继续，其他失败均停止。
4. 执行 `potentialFoam -initialiseUBCs -writep`，写入 U、phi 和近似 p。
5. 调用 `decomposePar`，然后以所选 MPI 进程数执行 `foamRun -parallel`。
6. 一边输出终端日志，一边保存完整日志和逐时间步监控表。

需要重新转换原始 Gmsh 网格时：

```bash
./Allrun -np 8 --mesh
```

原始网格副本位于 `mesh/cylinder2D_3d.msh`。`Allmesh` 会将圆柱设为 wall、
上下边界设为 symmetryPlane、前后面设为 empty；平时不需要重复转换网格。

### 4. 在另一个终端打开实时监控图

```bash
source /opt/openfoam14/etc/bashrc
cd /home/lcf/CFD/projects/2D_cylinder/re200
./Allmonitor
```

图形每秒刷新一次：第一幅是 Ux、Uy、p 的初始残差（对数坐标），
第二幅是平均/最大 Courant 数，第三幅是 Cd、Cl。
图形窗口需要 WSLg 或可用的图形显示环境；关闭窗口不影响计算。
可以先打开监控窗口再启动计算，窗口会等待数据出现。

没有图形环境时，直接在另一个终端查看日志或监控表：

```bash
tail -f log.foamRun
```

```bash
tail -f monitoring.csv
```

需要保存当前曲线图片时（此命令不打开图形窗口）：

```bash
./Allmonitor --save monitoring.png
```

### 5. 合并并查看场结果

等待并行计算正常结束后执行：

```bash
reconstructPar > log.reconstructPar 2>&1
paraview re200.foam
```

也可以只合并最近一次写出的场：

```bash
reconstructPar -latestTime > log.reconstructPar 2>&1
```

ParaView 的 OpenFOAM reader 也可以直接选择 decomposed case 读取分区结果。
升阻力系数和监控表已是全局统计，不需要 reconstructPar。

### 6. 重新从零开始计算

确认已有结果不再需要后执行：

```bash
./Allclean
./Allrun -np 8
```

`Allclean` 删除正时间目录、处理器分区目录、`postProcessing`、运行日志和监控 CSV/PNG，
以及 `decomposePar` 生成的 `constant/polyMesh/cellProc` 分区标记，
并从 `0_org` 恢复 `0`；保留原始备份、网格、配置和原有网格导入日志。
算例运行期间清理会被运行锁阻止。`Allrun` 本身不会自动删除旧计算结果。
停止求解在运行终端按 Ctrl+C；脚本会停止 MPI 子进程并保留已有输出供排查。

本入口用于全新计算。断点续算不能使用 `Allrun`，因为它会恢复初始场；
需要续算时保留分区结果，将 `controlDict` 的 `startFrom` 设为 `latestTime`，
使用原分区数直接启动 MPI 求解，另行保存续算日志。

## 日志和数据含义

| 文件/目录 | 内容 |
| --- | --- |
| `log.resources.json` | 当次可用 CPU、内存和实际进程数 |
| `log.checkMesh` | 网格检查 |
| `log.potentialFoam` | 势函数与压力初始化、连续性误差 |
| `log.decomposePar` | 网格分区情况 |
| `log.foamRun` | 完整求解输出及错误信息：Time、deltaT、Courant、所有线性求解残差、连续性误差、力、Cd、Cl |
| `monitoring.csv` | 每个完成的时间步一行，立即刷新写入 |
| `postProcessing/residuals/0/residuals.dat` | 原生 Ux、Uy、p 初始残差 |
| `postProcessing/cylinderForces/0/forces.dat` | 圆柱全局力和力矩 |
| `postProcessing/cylinderForceCoeffs/0/forceCoeffs.dat` | 全局 Cm、Cd、Cl 等系数 |

残差曲线取每个时间步**首次求解**该方程的 initial residual；CSV 的 final 列取该时间步
**最后一次求解**的 final residual。完整日志保存所有内迭代的 initial/final residual 和迭代次数。
这些是线性方程求解残差，不是流场误差。

Foundation 14 在推进时间之前输出 Courant 数并据此调节下一步步长。
因此 CSV 明确使用 `Co_mean_before_step`、`Co_max_before_step` 列名：
它们是进入对应时间步前求解器报告的值，使用当时的通量和步长，
不代表该时间步求解完成后重新计算的 Courant 数。CSV 中的 deltaT 是实际推进该步所用步长。
并行求解器打印的平均/最大 Courant 数均已做全域归约。

圆柱力和系数由 `system/functions` 中的原生功能对象每步计算、写出并打印。
参考速度 0.02 m/s、参考长度 0.01 m、参考面积 D×Lz=0.0001 m²，
阻力沿 +x、升力沿 +y。力对应实际 0.01 m 展向厚度；除以该厚度可得到单位展向长度的力。

## 五步试运行

只检查运行链路时使用：

```bash
source /opt/openfoam14/etc/bashrc
cd /home/lcf/CFD/projects/2D_cylinder/re200
./Allrun -np 8 --test
./Allmonitor --save monitoring.png
```

试运行临时固定 deltaT=0.0001 s，计算5步至 0.0005 s，每步写场。
正常退出、失败或 Ctrl+C 都会恢复原来的正式 `controlDict`。
试运行完成后可检查日志与数据，确认无误再执行 `./Allclean` 清理。
五步只验证初始化、并行通信、求解与监控链路；正式长时间计算的稳定性及涡脱落统计仍需观察。

2026-10-21 验证记录：8 个 MPI 进程完成 5 步至 0.0005 s；
监控表每步的 Ux、Uy、p 初始残差和 Cd、Cl 与原生输出匹配，
报告的最大 Courant 数约 0.03286，最终各方程线性求解残差小于 1×10⁻⁸。
静态图片输出和实时监控窗口启动均已验证。试运行输出已清理，`0` 已由 `0_org` 恢复，
正式 `controlDict` 已恢复为 0–70 s 的自动时间步配置。

## 文件结构

```text
0_org/                     原始初始场备份（U、p）
0/                         每次启动时由 0_org 恢复
constant/                  物性、流动模型及现有网格
mesh/                      Gmsh 原始网格副本
system/controlDict         正式时间设置
system/fvSolution          p、U、Phi 求解和 PIMPLE/potentialFlow 配置
system/fvSchemes           瞬态格式及势流压力初始化所需散度项
system/functions           力、系数、残差功能对象
system/decomposeParDict    scotch 分区，进程数由 Allrun 同步
scripts/resources.py       检测 CPU、内存及 cgroup 限额
scripts/run_case.py        初始化、运行、清理与锁管理
scripts/monitor.py         实时记录及绘图
Allmesh                    导入网格
Allrun                     从初始场启动
Allmonitor                 打开监控图或保存图片
Allclean                   清除计算输出并恢复 0
re200.foam                 ParaView 入口
```
