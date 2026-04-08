# pre-commit-hooks-cpp

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

为 C/C++ 项目提供的基于 [pre-commit](https://pre-commit.com/) 框架的 Git hook 脚本集合。

## 特性

- ✅ **提交信息规范检查** - 确保提交信息符合团队规范
- ✅ **换行符检查** - 检测并防止 Windows 风格换行符（CRLF）混入
- ✅ **UTF-8 编码检查** - 确保源代码文件使用 UTF-8 编码
- ✅ **版本号检查** - 确保提交信息中的版本号与版本文件一致，且版本递增合法
- 🚀 **易于集成** - 基于 pre-commit 框架，配置简单
- 🔧 **高度可定制** - 支持通过参数自定义检查规则

## 安装

### 前置要求

- Python 3.8+
- [pre-commit](https://pre-commit.com/)

### 安装 pre-commit

```bash
pip install pre-commit
```

## 使用

### 快速开始

在项目根目录创建 `.pre-commit-config.yaml` 文件，添加以下配置：

```yaml
default_install_hook_types: [pre-commit, commit-msg, post-commit]
repos:
  - repo: https://github.com/xyz1001/pre-commit-hooks-cpp
    rev: v1.1.1  # 使用最新版本
    hooks:
      - id: check-commit-msg
      - id: check-linebreak
      - id: check-utf8
      - id: check-version
```

然后安装 hooks：

```bash
pre-commit install
pre-commit install --hook-type commit-msg
pre-commit install --hook-type post-commit
```

## 可用 Hooks

### `check-commit-msg`

检查提交信息是否符合指定的格式规范。

**配置示例：**

```yaml
- id: check-commit-msg
  args: ['(?:^\\[(?:(?:feature)|(?:chore)|(?:refactor)|(?:revert)|(?:test)|(?:doc)|(?:style))\\]\\[\\d+\\.\\d+\\.\\d+\\](?:\\[[A-Z]+\\-\\d+\\])? .+(?:\\n^why: .*)?(?:\\n^how: .*)?(?:\\n^influence: .*)?$)|(?:^\\[bugfix\\]\\[\\d+\\.\\d+\\.\\d+\\](?:\\[[A-Z]+\\-\\d+\\])? .+\\n^why: .+\\n^how: .+\\n^influence: .+$)']
```

**参数说明：**
- `args`: 正则表达式，用于匹配提交信息格式

**符合规范的提交信息示例：**

```
[feature][1.0.0][PROJ-123] 添加用户登录功能
why: 需要实现用户身份验证
how: 使用 JWT 进行身份验证
influence: 影响登录模块
```

```
[bugfix][1.0.1][PROJ-124] 修复内存泄漏问题
why: 在析构函数中未释放资源
how: 添加资源释放代码
influence: 影响核心模块稳定性
```

### `check-linebreak`

检查文件是否包含 Windows 风格的换行符（CRLF），确保使用 Unix 风格的换行符（LF）。

**配置示例：**

```yaml
- id: check-linebreak
  types: [text]
  files: \.(cpp|cc|c|h|hpp|py)$
```

**说明：**
- 自动检测所有文本文件
- 可通过 `files` 参数指定要检查的文件类型
- 发现 CRLF 换行符时会报错并阻止提交

### `check-utf8`

检查源代码文件是否使用 UTF-8 编码（不带 BOM）。

**配置示例：**

```yaml
- id: check-utf8
  types: [text]
  files: \.(cpp|cc|c|h|hpp)$
```

**说明：**
- 确保源代码文件使用 UTF-8 编码
- 防止编码问题导致的编译错误
- 可通过 `files` 参数指定要检查的文件类型

### `check-version`

在提交创建后（post-commit）检查当前提交的版本号是否正确。

**检查规则：**
1. 提交信息中必须包含方括号包围的版本号（如 `[1.0.0]`）
2. 提交信息中的版本号必须与该提交中版本文件的版本号一致
3. 当前提交版本号相比上一次提交，有且仅有一位增加了 1
4. 如果高位增加了 1，所有低位必须置为 0
5. `fixup!` 开头的提交会被跳过

**配置示例：**

```yaml
# 示例 1: conanfile.py 中 version = "x.y.z" 格式
- id: check-version
  args:
    - --version-file=conanfile.py
    - --version-regex=^\s*version\s*=\s*["'](\d+(?:\.\d+)+)["']

# 示例 2: version.properties 中 version=x.y.z 格式
- id: check-version
  args:
    - --version-file=version.properties
    - --version-regex=^\s*version\s*=\s*(\d+(?:\.\d+)+)

# 示例 3: 版本号分开存储（如 major=1, minor=0, patch=0）
- id: check-version
  args:
    - --version-file=version.properties
    - --version-regex=major=(\d+).*minor=(\d+).*patch=(\d+)
```

**参数说明：**
- `--version-file`: 版本文件路径（必需）
- `--version-regex`: 提取版本号的正则表达式（必需）
  - 单个捕获组：直接作为版本号
  - 多个捕获组：各组用 `.` 连接（如 `(1)(0)(0)` → `1.0.0`）

**说明：**
- 运行在 `post-commit` 阶段，比较当前提交与上一个提交的版本号
- 支持 `git commit --amend` 和 `git rebase` 场景
- 支持任意位数的版本号（如 `1.0.0`、`1.0.0.0.1`）
- 首次提交（无历史提交）时跳过版本递增检查
- 正则表达式默认使用 `re.MULTILINE` 模式

**合法的版本递增示例：**

| 上一次版本 | 当前版本 | 是否合法 |
|-----------|---------|---------|
| 1.0.0 | 1.0.1 | ✅ |
| 1.0.0 | 1.1.0 | ✅ |
| 1.0.0 | 2.0.0 | ✅ |
| 1.0.0 | 1.0.2 | ❌ 增加了 2 |
| 1.0.0 | 1.1.1 | ❌ 高位增加后低位未置 0 |
| 1.0.0 | 0.0.1 | ❌ 高位降低 |
| 1.0.0.0.1 | 1.0.0.0.2 | ✅ |
| 1.0.0.0.1 | 1.1.0.0.0 | ✅ |

```yaml
default_install_hook_types: [pre-commit, commit-msg, post-commit]
repos:
  - repo: https://github.com/xyz1001/pre-commit-hooks-cpp
    rev: v1.1.1
    hooks:
      # 检查提交信息格式
      - id: check-commit-msg
        args: ['^\[(?:feature|bugfix|chore|refactor|doc|test|style)\]\[v?\d+\.\d+\.\d+\].*']
      
      # 检查 C/C++ 源文件的换行符
      - id: check-linebreak
        types: [text]
        files: \.(cpp|cc|c|h|hpp)$
      
      # 检查 C/C++ 源文件的编码
      - id: check-utf8
        types: [text]
        files: \.(cpp|cc|c|h|hpp)$
      
      # 检查版本号
      - id: check-version
        args:
          - --version-file=conanfile.py
          - --version-regex=^\s*version\s*=\s*["'](\d+(?:\.\d+)+)["']
```

## 依赖

- `charset_normalizer>=3.3` - 用于字符编码检测

## 开发

### 本地测试

```bash
# 克隆仓库
git clone https://github.com/xyz1001/pre-commit-hooks-cpp.git
cd pre-commit-hooks-cpp

# 安装依赖
pip install -e .

# 运行 pre-commit
pre-commit run --all-files
```

## 许可证

本项目采用 [MIT License](LICENSE) 许可证。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 相关链接

- [pre-commit 官方文档](https://pre-commit.com/)
- [项目主页](https://github.com/xyz1001/pre-commit-hooks-cpp)
