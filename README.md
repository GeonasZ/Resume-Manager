# rusume manager

一个可以直接作为独立 Git 仓库使用的、去敏感化的简历管理与生成器项目。它包含原生 Windows 编辑器、Markdown 数据、多个模板和 PDF 生成流程。项目目录名称按当前仓库约定保留为 `rusume manager`。

`data/` 中的姓名、联系方式、学校、公司、职位、项目和经历均为虚构示例数据，不包含原项目的个人信息。

## Windows 图形应用

双击 `launch_resume_editor.bat` 即可启动。脚本会优先使用项目虚拟环境；如果首次运行尚未创建虚拟环境，会自动使用 `uv run` 按 `pyproject.toml` 安装依赖并启动。

也可以手动运行：

```powershell
uv run main.py
```

如果不使用 `uv`，请先在项目虚拟环境中安装依赖：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe main.py
```

窗口提供：

- `Data editor`：编辑、新建和删除示例数据。
- `Templates & style`：编辑模板并设置颜色样式。
- `Generations`：管理模板、输出路径、目标页数和字体。
- `Build log`：查看生成日志。

顶部按钮：

- `Preview`：只渲染到临时目录，不覆盖 `resumes_output/`。
- `Generate output`：生成并打开正式 PDF。
- `Save`：保存当前编辑内容。

## 命令行

### 生成全部 generation

这条命令读取 `config.yaml`，按其中定义的全部 generation 生成对应 PDF。当前示例配置定义了两个独立的 generation，会生成两份简历；生成器不把它们限制为固定的语言组合：

```powershell
python generate_resume.py --config config.yaml
```

Windows 也可以双击 `build_resume.bat`；Linux/macOS 使用 `bash build_resume.sh`。

### 只生成一个模板

如需只测试某一个模板，可以直接指定模板和输出路径。当前示例中的两个模板可以分别运行：

```powershell
python generate_resume.py layouts/resume.md -o resumes_output/resume.pdf
python generate_resume.py layouts/resume_en.md -o resumes_output/resume_en.pdf
```

配置中的 generation 使用字体而不是 language：

```yaml
generations:
  - name: default
    template: layouts/resume.md
    output: resumes_output/resume.pdf
    font: SimHei
  - name: english
    template: layouts/resume_en.md
    output: resumes_output/resume_en.pdf
    font: Arial
```

GUI 会扫描当前系统字体并提供下拉选择。模板 front matter 中的 `expected_pages` 控制目标页数，颜色可以在 `Templates & style` 中编辑。

## 数据结构

文件顶部一级标题只作为注释；二级标题表示版本；三级标题表示功能性字段；四级标题表示内容分组：

```markdown
# Example Project

## eng_compact

### Title: Example Project

- Type: Personal Project
- Time: 2024.01-2024.06

This is example content.
```

解析器使用语义 alias，例如 `项目经历`/`Projects`、`职位`/`Position`、`时间`/`Time`、`专业`/`Major` 和 `学位`/`Degree` 会被识别为相同语义，不依赖语言预设。

## 输出

正式 PDF 输出到 `resumes_output/`。项目也可以直接提交到新的 Git 仓库中使用。
