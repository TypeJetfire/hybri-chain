# 四川大学本科毕业论文 XeLaTeX 编译 Makefile

TEX := xelatex
BIB := bibtex
TARGET := main
SRCDIR := src
CHAPDIR := $(SRCDIR)/chap
REF := ref/refs

# XeLaTeX 选项
# -interaction=nonstopmode  无交互模式
# -halt-on-error           遇错停止
# -file-line-error         显示文件:行号 错误格式
XELATEX_OPTS := -interaction=nonstopmode -halt-on-error -file-line-error
BIB_OPTS := $(TARGET)

# 超时秒数（单次 xelatex 超过此时间则中止）
TIMEOUT := timeout --signal=KILL 20

# 运行 xelatex 并检查错误
define RUN_XELATEX
	@echo "=== XeLaTeX $(1) 遍 ===" ; \
	$(TIMEOUT) $(TEX) $(XELATEX_OPTS) $(TARGET).tex 2>&1 | tee $(TARGET).log ; \
	if grep -q "^! " $(TARGET).log; then \
		echo "*** 编译出错，见上方 ***" ; \
		exit 1 ; \
	fi
endef

.PHONY: all clean pdf view

all: pdf

pdf: $(TARGET).pdf

$(TARGET).pdf: $(TARGET).tex $(wildcard $(SRCDIR)/*.tex) $(wildcard $(CHAPDIR)/*.tex) $(wildcard $(REF).bib)
	$(call RUN_XELATEX,1)
ifneq ($(wildcard $(REF).bib),)
	@echo "=== BibTeX 处理文献 ==="
	-$(BIB) $(BIB_OPTS)
endif
	$(call RUN_XELATEX,2)
	$(call RUN_XELATEX,3)
	@echo "=== 完成 ==="

clean:
	@echo "清理辅助文件..."
	rm -f $(TARGET).pdf
	rm -f $(TARGET).aux $(TARGET).bbl $(TARGET).blg
	rm -f $(TARGET).bcf $(TARGET).run.xml
	rm -f $(TARGET).log $(TARGET).out
	rm -f $(TARGET)-blx.bib
	rm -f $(CHAPDIR)/*.aux $(SRCDIR)/*.aux
	rm -f *.acn *.acr *.alg *.glg *.glo *.gls *.glsdefs *.ist
	find . -name "*.fls" -delete
	find . -name "*.fdb_latexmk" -delete
	@echo "清理完成。"

view: $(TARGET).pdf
	xdg-open $(TARGET).pdf

help:
	@echo "用法:"
	@echo "  make          编译生成 PDF（等效于 make pdf）"
	@echo "  make pdf      编译生成 PDF"
	@echo "  make view     编译并用默认 PDF 阅读器打开"
	@echo "  make clean    清理所有辅助文件（保留 PDF）"
	@echo "  make help     显示本帮助信息"
