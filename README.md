# pre-commit-hooks-cpp

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

为 C/C++ 项目提供的基于 [pre-commit](https://pre-commit.com/) 框架的 Git hook 脚本集合。

## 特性

- ✅ **提交信息规范检查** - 确保提交信息符合团队规范
- ✅ **换行符检查** - 检测并防止 Windows 风格换行符（CRLF）混入
- ✅ **UTF-8 编码检查** - 确保源代码文件使用 UTF-8 编码
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
default_install_hook_types: [pre-commit, commit-msg]
repos:
  - repo: https://github.com/xyz1001/pre-commit-hooks-cpp
    rev: v1.0.2  # 使用最新版本
    hooks:
      - id: check-commit-msg
      - id: check-linebreak
      - id: check-utf8
```

然后安装 hooks：

```bash
pre-commit install
pre-commit install --hook-type commit-msg
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

## 完整配置示例

```yaml
default_install_hook_types: [pre-commit, commit-msg]
repos:
  - repo: https://github.com/xyz1001/pre-commit-hooks-cpp
    rev: v1.0.2
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
