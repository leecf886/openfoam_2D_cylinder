# 二维圆柱绕流：Re = 200

适用版本：本机 `/opt/openfoam14` 中的 OpenFOAM Foundation 14。
算例使用 `foamRun` 加载 `incompressibleFluid`，流动模型为 `laminar`，采用非定常不可压缩 PIMPLE 求解。
`laminar` 是流动模型设置，不是求解器可执行文件的名称。

## 物性和几何

| 参数 | 初始设置 |
| --- | --- |
| 入口速度 U∞ | 0.02 m/s，沿 x 正方向 |
| 水的密度 ρ | 1000 kg/m³ |
| 动力黏度 μ | 0.001 Pa·s |
| 运动黏度 ν = μ/ρ | 1×10⁻⁶ m²/s |
| 圆柱直径 D | 0.01 m |
| 圆柱轴线 | x = 0，y = 0，沿 z 方向 |
| 计算域 | x ∈ [-0.05, 0.20] m，y ∈ [-0.05, 0.05] m |
| 展向厚度 Lz | 0.01 m，单层网格 |
| 雷诺数 U∞D/ν | 200 |

原始网格来自 `/mnt/e/Openfoam/projects/2D_cylinder/mesh/cylinder2D_3d.msh`，
仓库内保存其独立副本 `mesh/cylinder2D_3d.msh`，坐标按米使用，无缩放。
`Allmesh` 将其转换为 `constant/polyMesh`，并设置几何边界类型。
前后面设为 `empty`，使单层三维网格按二维问题求解。

不可压缩求解器实际读取 `constant/physicalProperties` 中的运动黏度 `nu`。
μ 和 ρ 的关系记录在该文件注释中；受力后处理的密度在 `system/functions` 中设为 1000。
`0/p` 是运动学压力，单位 m²/s²；对应的相对压力（Pa）为 `ρ p`。
本算例不求解温度、重力或湍流变量，因此无需 T、g、k、omega、epsilon 或 nut 文件。

## 边界条件

| 网格边界 | 几何类型 | U | p |
| --- | --- | --- | --- |
| inlet | patch | fixedValue (0.02 0 0) | zeroGradient |
| outlet | patch | zeroGradient | fixedValue 0 |
| top | symmetryPlane | symmetryPlane | symmetryPlane |
| bottom | symmetryPlane | symmetryPlane | symmetryPlane |
| cylinder | wall | noSlip | zeroGradient |
| frontAndBack | empty | empty | empty |

内部初始速度为 `(0.02 0 0)`，内部初始运动学压力为 0。
上下边界采用对称条件；当前配置用于外流，不将上下边界作为固壁。

## 时间和数值格式

- 计算时间：0–100 s；初始时间步：0.0001 s。
- 自动调节时间步：最大 Courant 数 0.5，最大时间步 0.002 s。
- 场文件每 0.1 s 输出一次，ASCII 格式，不自动清除历史结果。
- 时间离散：`backward`；速度对流：`Gauss linearUpwind grad(U)`。
- 速度梯度：`cellLimited Gauss linear 1`；扩散和面法向梯度采用非正交修正。
- PIMPLE：2 次外循环、2 次压力修正、1 次非正交修正。
- 压力求解采用 GAMG，速度求解采用 smoothSolver。

`system/functions` 配置圆柱受力与升阻力系数，每个时间步输出。
参考速度为 0.02 m/s，参考长度为 0.01 m，参考面积为 `D × Lz = 0.0001 m²`。
受力输出对应网格的 0.01 m 展向厚度；除以 0.01 m 可得到单位展向长度的力。

## 目录结构

```text
re200/
├── 0/
│   ├── U
│   └── p
├── constant/
│   ├── physicalProperties
│   ├── momentumTransport
│   └── polyMesh/             # Allmesh 生成的 OpenFOAM 网格
├── system/
│   ├── controlDict
│   ├── fvSchemes
│   ├── fvSolution
│   ├── functions
│   └── decomposeParDict
├── mesh/
│   └── cylinder2D_3d.msh
├── Allmesh
├── Allrun
├── re200.foam
├── .gitignore
└── README.md
```

## 执行方法

加载环境并进入算例目录：

```bash
source /opt/openfoam14/etc/bashrc
cd /home/lcf/CFD/projects/2D_cylinder/re200
```

完整串行运行（重新转换网格，然后启动求解器）：

```bash
./Allrun
```

只重新导入网格：

```bash
./Allmesh
```

使用已有 `constant/polyMesh` 直接启动求解器：

```bash
foamRun > log.foamRun 2>&1
```

可选的 4 进程并行运行：

```bash
decomposePar
mpirun -np 4 foamRun -parallel > log.foamRun 2>&1
reconstructPar
```

`system/decomposeParDict` 中的进程数应与 `mpirun -np` 一致。
如需续算，将 `system/controlDict` 的 `startFrom` 改为 `latestTime`。
使用 ParaView 打开 `re200.foam` 可查看场结果。

本次创建只准备算例文件及转换网格，不执行 `checkMesh`、测试或求解器试运行。
上述时间范围、边界条件、差分格式与输出频率均为初始设置，可按后续研究需要修改。
