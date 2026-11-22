"""Native Windows editor for the Markdown resume generator."""

from __future__ import annotations

import re
import os
import tempfile
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

import yaml

import generate_resume


ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data"
LAYOUT_ROOT = ROOT / "layouts"
CONFIG_PATH = ROOT / "config.yaml"


class ResumeEditor(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Resume Generation Studio")
        self.geometry("1420x860")
        self.minsize(1100, 700)
        self.current_path: Path | None = None
        self.current_kind = "data"
        self.dirty = False
        self.raw_config: dict = {}
        self.generations: list[dict] = []
        self._build_style()
        self._build_menu()
        self._build_ui()
        self.load_config()
        self.refresh_files()
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 14, "bold"))
        style.configure("Section.TLabel", font=("Segoe UI", 10, "bold"), foreground="#2F4858")
        style.configure("Muted.TLabel", foreground="#666666")
        style.configure("Action.TButton", padding=(14, 8), font=("Segoe UI", 9, "bold"))
        style.configure("Secondary.TButton", padding=(9, 6))
        style.configure("Card.TLabelframe", padding=10)
        style.configure("Card.TLabelframe.Label", font=("Segoe UI", 10, "bold"), foreground="#2F4858")
        style.configure("TNotebook.Tab", padding=(16, 8), font=("Segoe UI", 9))

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Save", command=self.save_current, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="New data file...", command=self.new_data)
        file_menu.add_command(label="New template...", command=self.new_template)
        file_menu.add_command(label="Delete selected file", command=self.delete_selected)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close)
        menu.add_cascade(label="File", menu=file_menu)
        build_menu = tk.Menu(menu, tearoff=False)
        build_menu.add_command(label="Save configuration", command=self.save_config)
        build_menu.add_command(label="Preview", command=self.preview)
        build_menu.add_command(label="Generate output", command=self.generate_output)
        menu.add_cascade(label="Build", menu=build_menu)
        self.config(menu=menu)
        self.bind_all("<Control-s>", lambda _event: self.save_current())

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=(12, 10))
        top.pack(fill="x")
        ttk.Label(top, text="Resume Generation Studio", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="Edit data, templates, styles, and generate PDFs", style="Muted.TLabel").pack(side="left", padx=18)
        ttk.Button(top, text="Save", style="Action.TButton", command=self.save_current).pack(side="right", padx=4)
        ttk.Button(top, text="Generate output", style="Action.TButton", command=self.generate_output).pack(side="right", padx=4)
        ttk.Button(top, text="Preview", style="Action.TButton", command=self.preview).pack(side="right", padx=4)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._build_editor_tab()
        self._build_templates_tab()
        self._build_generation_tab()
        self._build_log_tab()

    def _build_editor_tab(self) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Data editor")
        pane = ttk.PanedWindow(tab, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane, padding=8)
        center = ttk.Frame(pane, padding=8)
        pane.add(left, weight=1)
        pane.add(center, weight=4)
        ttk.Label(left, text="Data files", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        buttons = ttk.Frame(left)
        buttons.pack(fill="x", pady=(0, 6))
        ttk.Button(buttons, text="＋ New", style="Secondary.TButton", command=self.new_data).pack(side="left")
        ttk.Button(buttons, text="Delete", style="Secondary.TButton", command=self.delete_selected).pack(side="left", padx=4)
        self.data_tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.data_tree.pack(fill="both", expand=True)
        self.data_tree.bind("<<TreeviewSelect>>", self.on_file_select)

        self.file_label = ttk.Label(center, text="Select a data file", style="Section.TLabel")
        self.file_label.pack(anchor="w")
        self.file_hint = ttk.Label(center, text="Markdown is edited directly; Ctrl+S saves it.", style="Muted.TLabel")
        self.file_hint.pack(anchor="w", pady=(2, 8))
        text_frame = ttk.Frame(center)
        text_frame.pack(fill="both", expand=True)
        self.editor = tk.Text(text_frame, wrap="none", undo=True, font=("Cascadia Mono", 10), padx=10, pady=8)
        yscroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.editor.yview)
        xscroll = ttk.Scrollbar(text_frame, orient="horizontal", command=self.editor.xview)
        self.editor.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.editor.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        self.editor.bind("<<Modified>>", self.mark_dirty)

    def _build_templates_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="Templates & style")
        ttk.Label(tab, text="Templates & style", style="Title.TLabel").pack(anchor="w")
        ttk.Label(tab, text="Edit a Markdown template on the left; configure its generation and appearance on the right.", style="Muted.TLabel").pack(anchor="w", pady=(2, 8))
        row = ttk.PanedWindow(tab, orient="horizontal")
        row.pack(fill="both", expand=True)
        template_pane = ttk.Frame(row, padding=(0, 0, 10, 0))
        settings_pane = ttk.Frame(row, padding=(10, 0, 0, 0))
        row.add(template_pane, weight=3)
        row.add(settings_pane, weight=2)
        left = ttk.Frame(template_pane)
        left.pack(side="left", fill="y", padx=(0, 10))
        self.template_list = tk.Listbox(left, width=28, exportselection=False)
        self.template_list.pack(fill="y", expand=True)
        self.template_list.bind("<<ListboxSelect>>", self.on_template_select)
        tf = ttk.Frame(template_pane)
        tf.pack(side="left", fill="both", expand=True)
        self.template_editor = tk.Text(tf, wrap="none", undo=True, font=("Cascadia Mono", 10), padx=10, pady=8)
        self.template_editor.pack(fill="both", expand=True)
        self.template_editor.bind("<<Modified>>", self.mark_dirty)
        actions = ttk.Frame(left)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="＋ New", style="Secondary.TButton", command=self.new_template).pack(side="left")
        ttk.Button(actions, text="Delete", style="Secondary.TButton", command=self.delete_template).pack(side="left", padx=4)
        self._build_style_panel(settings_pane)

    def _build_generation_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="Generations")
        main = ttk.PanedWindow(tab, orient="horizontal")
        main.pack(fill="both", expand=True)
        left = ttk.Frame(main, padding=(0, 0, 12, 0))
        right = ttk.Frame(main, padding=(12, 0, 0, 0))
        main.add(left, weight=2)
        main.add(right, weight=3)
        ttk.Label(left, text="Generation targets", style="Section.TLabel").pack(anchor="w")
        self.gen_list = tk.Listbox(left, exportselection=False, height=12)
        self.gen_list.pack(fill="both", expand=True, pady=(8, 8))
        self.gen_list.bind("<<ListboxSelect>>", self.on_generation_select)
        gen_buttons = ttk.Frame(left)
        gen_buttons.pack(fill="x")
        ttk.Button(gen_buttons, text="＋ New", style="Secondary.TButton", command=self.new_generation).pack(side="left")
        ttk.Button(gen_buttons, text="Delete", style="Secondary.TButton", command=self.delete_generation).pack(side="left", padx=4)
        form_box = ttk.LabelFrame(right, text="Generation settings", style="Card.TLabelframe")
        form_box.pack(fill="x", pady=(0, 12))
        form = ttk.Frame(form_box)
        form.pack(fill="x")
        self.gen_vars = {key: tk.StringVar() for key in ("name", "template", "output", "pages", "font")}
        fields = [("Name", "name"), ("Template", "template"), ("Output", "output"), ("Pages", "pages"), ("Font", "font")]
        for i, (label, key) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=5)
            widget: tk.Widget
            if key == "template":
                self.template_combo = ttk.Combobox(form, textvariable=self.gen_vars[key], state="normal")
                widget = self.template_combo
            elif key == "pages":
                widget = ttk.Spinbox(form, textvariable=self.gen_vars[key], from_=1, to=10, width=8)
            elif key == "font":
                widget = ttk.Combobox(form, textvariable=self.gen_vars[key], values=generate_resume.available_fonts(), state="readonly")
            else:
                widget = ttk.Entry(form, textvariable=self.gen_vars[key])
            widget.grid(row=i, column=1, sticky="ew", padx=(10, 0), pady=5)
        form.columnconfigure(1, weight=1)
        options = ttk.LabelFrame(right, text="Build options", style="Card.TLabelframe")
        options.pack(fill="x")
        ttk.Label(options, text="Pages are stored in each template's front matter (expected_pages).", style="Muted.TLabel", wraplength=300).pack(anchor="w")

    def _build_style_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Visual style", style="Section.TLabel").pack(anchor="w")
        ttk.Label(parent, text="Colors apply to the selected generation.", style="Muted.TLabel", wraplength=320).pack(anchor="w", pady=(2, 8))
        self.color_vars = {key: tk.StringVar() for key in ("emphasis", "section_title", "separator", "work_title", "project_title", "education_title")}
        card = ttk.LabelFrame(parent, text="Color palette", style="Card.TLabelframe")
        card.pack(fill="x", pady=8)
        color_frame = ttk.Frame(card)
        color_frame.pack(fill="x")
        color_frame.columnconfigure(1, weight=1)
        for row, key in enumerate(self.color_vars):
            ttk.Label(color_frame, text=key.replace("_", " ").title()).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
            ttk.Entry(color_frame, textvariable=self.color_vars[key], width=10).grid(row=row, column=1, sticky="ew", pady=5)
            ttk.Button(color_frame, text="Pick", style="Secondary.TButton", command=lambda k=key: self.choose_color(k)).grid(row=row, column=2, sticky="e", padx=(8, 0), pady=5)
        ttk.Button(parent, text="Apply style", style="Action.TButton", command=self.apply_generation_fields).pack(anchor="e", pady=8)

    def _build_log_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="Build log")
        self.log = tk.Text(tab, wrap="word", state="disabled", font=("Cascadia Mono", 10))
        self.log.pack(fill="both", expand=True)

    def mark_dirty(self, _event=None) -> None:
        if self.editor.edit_modified() or self.template_editor.edit_modified():
            self.dirty = True
        self.editor.edit_modified(False)
        self.template_editor.edit_modified(False)

    def log_message(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def refresh_files(self) -> None:
        self.data_tree.delete(*self.data_tree.get_children())
        for category in sorted((p for p in DATA_ROOT.iterdir() if p.is_dir()), key=lambda p: p.name):
            node = self.data_tree.insert("", "end", text=category.name, open=True)
            for path in sorted(category.glob("*.md")):
                self.data_tree.insert(node, "end", text=path.name, values=(str(path),))
        self.template_list.delete(0, "end")
        for path in sorted(LAYOUT_ROOT.glob("*.md")):
            self.template_list.insert("end", path.name)

    def on_file_select(self, _event=None) -> None:
        selected = self.data_tree.selection()
        if not selected:
            return
        path_text = self.data_tree.item(selected[0], "values")
        if not path_text:
            return
        self.open_file(Path(path_text[0]), "data")

    def open_file(self, path: Path, kind: str) -> None:
        if self.dirty and not messagebox.askyesno("Unsaved changes", "Save current changes before switching?"):
            return
        if self.dirty:
            self.save_current()
        self.current_path, self.current_kind, self.dirty = path, kind, False
        target = self.editor if kind == "data" else self.template_editor
        target.delete("1.0", "end")
        target.insert("1.0", path.read_text(encoding="utf-8"))
        target.edit_modified(False)
        if kind == "data":
            self.file_label.configure(text=path.relative_to(ROOT))
        self.notebook.select(0 if kind == "data" else 1)

    def save_current(self) -> None:
        if not self.current_path:
            return
        target = self.editor if self.current_kind == "data" else self.template_editor
        self.current_path.write_text(target.get("1.0", "end-1c"), encoding="utf-8")
        self.dirty = False
        self.log_message(f"Saved {self.current_path.relative_to(ROOT)}")
        self.refresh_files()

    def new_data(self) -> None:
        category = simpledialog.askstring("New data file", "Category folder (about/career/education/projects):", parent=self)
        name = simpledialog.askstring("New data file", "File name without .md:", parent=self)
        if not category or not name:
            return
        path = DATA_ROOT / category.strip() / (name.strip().replace(" ", "-") + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            messagebox.showerror("Already exists", str(path)); return
        path.write_text(f"# {name.strip()}\n\n## compact\n\n### Title: {name.strip()}\n\n### Content\n\n## detailed\n\n### Title: {name.strip()}\n\n### Content\n", encoding="utf-8")
        self.refresh_files(); self.open_file(path, "data")

    def new_template(self) -> None:
        name = simpledialog.askstring("New template", "Template name without .md:", parent=self)
        if not name: return
        path = LAYOUT_ROOT / (name.strip().replace(" ", "-") + ".md")
        if path.exists(): messagebox.showerror("Already exists", str(path)); return
        path.write_text("---\nexpected_pages: 1\n---\n\n# Resume\n\n## Personal Information\n\n", encoding="utf-8")
        self.refresh_files(); self.open_file(path, "template")

    def delete_selected(self) -> None:
        selected = self.data_tree.selection()
        if selected:
            values = self.data_tree.item(selected[0], "values")
            if values: self._delete_path(Path(values[0]))

    def delete_template(self) -> None:
        selection = self.template_list.curselection()
        if selection: self._delete_path(LAYOUT_ROOT / self.template_list.get(selection[0]))

    def _delete_path(self, path: Path) -> None:
        if path.exists() and messagebox.askyesno("Delete file", f"Delete {path.name}?"):
            path.unlink(); self.current_path = None; self.dirty = False; self.refresh_files()

    def on_template_select(self, _event=None) -> None:
        selection = self.template_list.curselection()
        if selection: self.open_file(LAYOUT_ROOT / self.template_list.get(selection[0]), "template")

    def load_config(self) -> None:
        self.raw_config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        self.generations = list(self.raw_config.get("generations") or [])
        self.refresh_generation_list()

    def refresh_generation_list(self) -> None:
        self.gen_list.delete(0, "end")
        self.gen_list.insert("end", *[g.get("name", "Unnamed") for g in self.generations])
        if hasattr(self, "template_combo"):
            self.template_combo.configure(values=[str(p.relative_to(ROOT)) for p in sorted(LAYOUT_ROOT.glob("*.md"))])

    def on_generation_select(self, _event=None) -> None:
        selection = self.gen_list.curselection()
        if not selection: return
        gen = self.generations[selection[0]]
        for key in self.gen_vars: self.gen_vars[key].set(str(gen.get(key, "")))
        self.gen_vars["pages"].set(str(self.template_pages(gen.get("template", ""))))
        colors = {**(self.raw_config.get("defaults", {}).get("colors") or {}), **(gen.get("colors") or {})}
        for key in self.color_vars: self.color_vars[key].set(str(colors.get(key, "#3F6F82")))

    def template_pages(self, template: str) -> int:
        path = ROOT / template
        if not path.exists(): return 1
        try:
            metadata, _ = generate_resume.split_front_matter(path)
            return int(metadata.get("expected_pages", 1))
        except Exception: return 1

    def choose_color(self, key: str) -> None:
        color = colorchooser.askcolor(self.color_vars[key].get(), parent=self)[1]
        if color: self.color_vars[key].set(color.upper())

    def apply_generation_fields(self) -> None:
        selection = self.gen_list.curselection()
        if not selection: return
        gen = self.generations[selection[0]]
        for key in ("name", "template", "output", "font"):
            gen[key] = self.gen_vars[key].get().strip()
        try:
            pages = max(1, min(10, int(self.gen_vars["pages"].get())))
            template_path = ROOT / gen["template"]
            if template_path.exists():
                metadata, lines = generate_resume.split_front_matter(template_path)
                metadata["expected_pages"] = pages
                front_matter = "---\n" + yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip() + "\n---\n"
                body = "\n".join(lines)
                template_path.write_text(front_matter + body + ("\n" if body else ""), encoding="utf-8")
        except (ValueError, OSError) as exc:
            messagebox.showerror("Invalid pages/template", str(exc)); return
        try: gen["colors"] = {key: value for key, value in ((k, v.get().strip()) for k, v in self.color_vars.items()) if value}
        except Exception as exc: messagebox.showerror("Invalid settings", str(exc)); return
        self.refresh_generation_list(); self.gen_list.selection_set(selection[0]); self.log_message(f"Updated generation {gen['name']}")

    def new_generation(self) -> None:
        self.generations.append({"name": f"generation-{len(self.generations)+1}", "template": "layouts/resume.md", "output": "resumes_output/resume.pdf", "font": "SimHei"})
        self.refresh_generation_list(); self.gen_list.selection_set(len(self.generations)-1); self.on_generation_select()

    def delete_generation(self) -> None:
        selection = self.gen_list.curselection()
        if selection and len(self.generations) > 1 and messagebox.askyesno("Delete generation", "Remove this generation from config?"):
            self.generations.pop(selection[0]); self.refresh_generation_list()

    def save_config(self) -> None:
        self.raw_config["generations"] = self.generations
        CONFIG_PATH.write_text(yaml.safe_dump(self.raw_config, sort_keys=False, allow_unicode=True), encoding="utf-8")
        self.log_message("Saved config.yaml")

    def _prepare_build(self) -> None:
        self.save_current()
        self.save_config()
        self.notebook.select(2)

    def preview(self) -> None:
        self._prepare_build()
        self.log_message("Starting preview render (temporary files only)...")
        preview_root = Path(tempfile.mkdtemp(prefix="resume-preview-"))
        try:
            for generation in generate_resume.load_generations(CONFIG_PATH):
                target = preview_root / f"{generation.name}.pdf"
                generate_resume.build(generation.template, target, generation.theme, ROOT, generation.font)
                if hasattr(os, "startfile"):
                    os.startfile(str(target))
                self.log_message(f"Opened preview: {target}")
        except Exception as exc:
            self.log_message(f"Preview failed: {exc}")
            messagebox.showerror("Preview failed", str(exc))

    def generate_output(self) -> None:
        self._prepare_build()
        self.log_message("Starting output generation...")
        try:
            generate_resume.build_config(CONFIG_PATH)
            self.log_message("Output generation completed successfully.")
            if hasattr(os, "startfile"):
                for generation in generate_resume.load_generations(CONFIG_PATH):
                    output = generation.output
                    if output.exists():
                        os.startfile(str(output))
                        self.log_message(f"Opened output preview: {output.relative_to(ROOT)}")
        except Exception as exc:
            self.log_message(f"Generation failed: {exc}")
            messagebox.showerror("Generation failed", str(exc))

    def close(self) -> None:
        if self.dirty and not messagebox.askyesno("Unsaved changes", "Exit without saving current changes?"):
            return
        self.destroy()


def main() -> None:
    ResumeEditor().mainloop()


if __name__ == "__main__":
    main()
