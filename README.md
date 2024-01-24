pre-commit-hooks-cpp
================

为C/C++项目提供的基于 [pre-commit](https://pre-commit.com/) 框架的Git hook脚本。

### 使用

将以下代码添加到项目根目录下的`.pre-commit-config.yaml`文件中

```yaml
-   repo: https://github.com/xyz1001/pre-commit-hooks-cpp
    rev: v1.0.0
    hooks:
    -   id: check-commit-msg
```

### 可用hook

#### `check-commit-msg`
检查提交规范是否符合要求.
  - 通过 `args` 指定检查提交内容需满足的的正则表达式.
