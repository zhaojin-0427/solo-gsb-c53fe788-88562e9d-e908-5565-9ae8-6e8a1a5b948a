# 卷区段安全搬移规划服务 (Volume Segment Relocation Planner)

使用 **Python + FastAPI** 实现的卷区段安全搬移 HTTP API。给定卷容量、若干区段
（ID、当前起点、长度、目标起点）以及保留区，服务返回一个**逐步可重放**的整段
复制序列，把所有区段搬到各自的目标位置。

## 语义与规则

- 所有坐标都是非负 64 位整数，区间采用左闭右开 `[start, start + length)`。
- 区段长度必须为正；所有当前区间两两不重叠，所有目标区间两两不重叠，
  且当前区间、目标区间均不越界、不与保留区相交（端点相接允许，不算相交）。
- 一次动作只能把**一个完整区段**复制到一块**当时连续且等长**的空闲区：
  - 源区间与目的区间不得重叠；
  - 复制完成之后才释放旧址（因此临时目的位不能与源重叠）；
  - 区段不可拆分；目的区不能覆盖任何尚未迁出的数据或保留区。
- 目标互相占位时允许借用临时空位（一个区段可能被搬动多次）。
- 优化目标按以下优先级取最优：
  1. **总写入块数最少**（每搬一次写入该段长度的块数）；
  2. 在总写入块数相同的前提下，**步数最少**；
  3. 仍相同时，按 `(区段 ID, 目的起点)` 的动作序列取**字典序最小**。
- 所有区段本就在目标位置时返回**空序列**；合法但无可行方案时返回
  `{"feasible": false}`；非法输入返回 **HTTP 422**。

规划器只在区间端点构成的符号状态上搜索，**不会按卷容量逐块枚举**，因此
容量接近 `2^64` 与容量只有几个块的开销相同。

## 目录结构

```
app/
  planner.py   # 纯区间端点的符号化规划器（与容量无关）
  main.py      # FastAPI 应用、请求校验、/plans 与 /health
tests/         # 单元测试、HTTP 测试、随机模糊对照（逐块暴力参考实现）
Dockerfile
docker-compose.yml
requirements.txt
```

## 方式一：Docker Compose 一键启动

需要安装 Docker 与 Docker Compose v2。

```bash
docker compose up --build
```

服务监听 `http://localhost:8000`。停止：`docker compose down`。

## 方式二：本地直接运行

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后可访问交互式文档：

- Swagger UI: http://localhost:8000/docs
- OpenAPI:    http://localhost:8000/openapi.json
- 健康检查:   http://localhost:8000/health

## API：`POST /plans`

### 请求体

| 字段       | 类型                              | 说明                                       |
| ---------- | --------------------------------- | ------------------------------------------ |
| `capacity` | 整数，`[0, 2^64-1]`               | 卷容量（块数）                             |
| `segments` | 区段数组                          | 每项含 `id`、`start`、`length`、`target`   |
| `reserved` | `[start, end)` 数组，可省略       | 保留区，任何时刻都不可占用                 |

区段字段：

| 字段     | 类型                       | 说明            |
| -------- | -------------------------- | --------------- |
| `id`     | 非空字符串，全卷唯一       | 区段标识        |
| `start`  | 整数，`[0, 2^64-1]`        | 当前起点        |
| `length` | 整数，`[1, 2^64-1]`        | 区段长度（正）  |
| `target` | 整数，`[0, 2^64-1]`        | 目标起点        |

布尔值、小数、缺字段、重复 ID、长度为 0、越界、当前/目标重叠、与保留区相交等
都会得到 **422**，响应体 `detail` 中给出原因。

### 成功响应（有方案）

`200 OK`，字段：

- `feasible`: `true`
- `moves`: 动作序列，按执行顺序排列，每项 `{id, src, dst}`；`src` 为该步
  复制的源起点、`dst` 为目的起点（重放时每一步的源都由前序状态确定）。
- `steps`: 步数
- `written_blocks`: 总写入块数

### 成功响应（无可行方案）

`200 OK`，响应体固定为 `{"feasible": false}`。

## 实际请求与响应示例

以下示例均来自本实现的真实 HTTP 响应。

### 示例 1：需要先借用临时空位（题目示例）

容量 5，`A:[0,2)→[2,4)`、`B:[2,3)→[0,1)`。最优为 3 步、4 个写入块：
必须先把 B 搬到唯一的临时空位 `[4,5)`，腾出 A 的目标，再把 B 搬到最终目标。

```bash
curl -s -X POST http://localhost:8000/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "capacity": 5,
    "segments": [
      {"id": "A", "start": 0, "length": 2, "target": 2},
      {"id": "B", "start": 2, "length": 1, "target": 0}
    ],
    "reserved": []
  }'
```

```json
{
    "feasible": true,
    "moves": [
        { "id": "B", "src": 2, "dst": 4 },
        { "id": "A", "src": 0, "dst": 2 },
        { "id": "B", "src": 4, "dst": 0 }
    ],
    "steps": 3,
    "written_blocks": 4
}
```

### 示例 2：已经全部就位

```bash
curl -s -X POST http://localhost:8000/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "capacity": 4,
    "segments": [ {"id": "A", "start": 0, "length": 2, "target": 0} ]
  }'
```

```json
{
    "feasible": true,
    "moves": [],
    "steps": 0,
    "written_blocks": 0
}
```

### 示例 3：无可行方案

容量 2 被两个长度为 1 的区段占满，二者要互换位置，没有任何临时空位：

```bash
curl -s -X POST http://localhost:8000/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "capacity": 2,
    "segments": [
      {"id": "A", "start": 0, "length": 1, "target": 1},
      {"id": "B", "start": 1, "length": 1, "target": 0}
    ]
  }'
```

```
HTTP 200
```
```json
{ "feasible": false }
```

### 示例 4：保留区

容量 8，保留 `[6,8)`，区段 `data:[0,3)→[3,6)` 直接一步搬入，目的与保留区
仅在端点 6 相接：

```bash
curl -s -X POST http://localhost:8000/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "capacity": 8,
    "segments": [
      {"id": "data", "start": 0, "length": 3, "target": 3}
    ],
    "reserved": [[6, 8]]
  }'
```

```json
{
    "feasible": true,
    "moves": [
        { "id": "data", "src": 0, "dst": 3 }
    ],
    "steps": 1,
    "written_blocks": 3
}
```

### 示例 5：非法输入（长度为 0）

```bash
curl -i -X POST http://localhost:8000/plans \
  -H 'Content-Type: application/json' \
  -d '{"capacity": 3, "segments": [{"id": "A", "start": 0, "length": 0, "target": 1}]}'
```

```
HTTP/1.1 422 Unprocessable Content
```
```json
{
    "detail": [
        {
            "type": "value_error",
            "loc": ["body"],
            "msg": "Value error, segment 'A' length must be positive",
            ...
        }
    ]
}
```

当前区间互相重叠时同样返回 422，例如：

```json
{ "msg": "Value error, current intervals of segments 'A' and 'B' overlap" }
```

## 运行测试

```bash
pip install pytest httpx
python -m pytest -q
```

测试包含：题目示例与逐步可重放性校验、保留区/无空位/边界相接等情形、
HTTP 422 校验，以及数百到上千个小容量随机实例与**逐块枚举暴力参考解**在
「总写入块数、步数、完整字典序」三个维度上的逐一对照。
