# tools

- `pack_pbab.py`：把一个模组源码目录打成 `.pbab`（会自动生成 checksums.json）

```bash
python tools/pack_pbab.py examples/module_template dist/template_module.pbab
```

打完的包在模组页「外部导入 .pbab」里选它。
