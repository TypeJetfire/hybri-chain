# 四川大学本科毕业论文 LaTeX 模板

一个面向四川大学本科毕业论文（设计）的非官方 LaTeX 模板，适用于 `XeLaTeX`，可在本地 `TeX Live` 和 `Overleaf` 中使用。

这个仓库的目标不是机械复刻某一届的 Word 模板，而是提供一个更稳定、更清晰、也更容易维护和二次修改的起始工程。

## 适用场景

- 四川大学本科毕业论文（设计）写作
- 想使用 LaTeX 完成封面、摘要、目录、正文、参考文献、声明等页面排版
- 希望同时兼容本地编译和 Overleaf
- 想要一个结构清晰、方便后续微调的模板项目

## 模板特点

- 内置封面、中英文摘要、目录、正文、参考文献、声明、学位论文使用授权书、AI 工具使用声明、致谢
- `main.tex` 只控制论文顺序，结构更清楚
- `scuthesis.sty` 集中管理封面、目录、标题、页眉页脚、摘要和图表样式
- `src/*.tex` 只放页面和章节内容，便于替换
- 样式文件中包含较详细的中文注释，方便按学院要求继续微调
- 保留少量示例章节和示例参考文献，便于直接上手

## 仓库结构

```text
.
├── main.tex
├── scuthesis.sty
├── compile.bat
├── README.md
├── README_OVERLEAF.md
├── LICENSE
├── images/
│   ├── scu-bw.png
│   └── logo-bw.png
├── ref/
│   └── refs.bib
└── src/
    ├── basic_info.tex
    ├── cover.tex
    ├── abstract_cn.tex
    ├── abstract_en.tex
    ├── toc.tex
    ├── chap01.tex
    ├── chap02.tex
    ├── declaration.tex
    ├── ai_statement.tex
    └── acknowledgement.tex
```

## 快速开始

### 本地 TeX Live

1. 安装带 `XeLaTeX` 的 `TeX Live`。
2. 打开项目根目录。
3. 运行：

```powershell
cmd /c compile.bat thesis
```

默认输出文件为 `main_v1/main.pdf`。

### Overleaf

1. 新建一个空白项目。
2. 将本仓库全部文件上传到项目根目录。
3. 在 Overleaf 菜单中将 Compiler 设置为 `XeLaTeX`。
4. 确认主文件为 `main.tex`。
5. 重新编译。

详细说明可见 [README_OVERLEAF.md](README_OVERLEAF.md)。

## 推荐修改顺序

如果你第一次使用这份模板，建议按下面顺序修改：

1. 修改 `src/basic_info.tex` 中的题目、姓名、学院、专业、学号、日期等信息。
2. 修改 `src/abstract_cn.tex` 和 `src/abstract_en.tex`。
3. 修改 `src/chap01.tex`、`src/chap02.tex`，再按需要继续增加章节。
4. 修改 `ref/refs.bib` 中的参考文献条目。
5. 最后再根据学院要求微调 `scuthesis.sty` 中的样式参数。

## 最常改的文件

- `src/basic_info.tex`
  用于填写封面与摘要页的基础信息。
- `src/abstract_cn.tex`
  中文摘要。
- `src/abstract_en.tex`
  英文摘要。
- `src/chap01.tex`、`src/chap02.tex`
  正文章节示例。
- `ref/refs.bib`
  参考文献库。
- `scuthesis.sty`
  样式总控文件，封面、目录、标题和页眉页脚都在这里调。

## 设计思路

这份模板尽量把“文档顺序”“页面内容”“样式控制”拆开处理：

- `main.tex` 负责决定论文由哪些部分组成，以及这些部分的先后顺序。
- `src/*.tex` 负责每一页或每一章的具体内容。
- `scuthesis.sty` 负责统一样式。

这样做的好处是，后续修改目录位置、封面间距、标题格式时，不容易误伤正文内容；同时也更方便在 Overleaf 中定位问题。

## 注意事项

- 这是非官方模板，最终提交前请务必对照学院当年的最新格式要求逐项检查。
- 模板中的声明、AI 工具使用声明与致谢是示例文本，请根据你的真实情况修改。
- 不同学院的细节要求可能略有差异，特别是封面格式、声明文本、参考文献格式和页码要求。
- 如果你使用的是云端环境，遇到目录、引用、页码不同步时，通常连续编译两到三次即可。

## 开源说明

本仓库使用 MIT License 开源，见 [LICENSE](LICENSE)。

如果你基于本模板做了适配或改进，欢迎继续公开分享，也欢迎提交修改建议。
