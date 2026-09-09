# Image drop folder

Put NCC 2025 Volume Two and ABCB Housing Provisions figures here, then run:

```bash
cd backend
python scripts/describe_images.py
```

Sub-folders are fine and are recommended — the output is keyed by the path
relative to this folder, so `ncc_vol2/part_11/figure_11_2_2.png` and
`housing_provisions/part_11/figure_11_2_2.png` stay distinct. Suggested layout:

```
data/images/
  ncc_vol2/
  housing_provisions/
```

The images themselves are gitignored (copyright + repo size). Only this README
is tracked. Descriptions land in `../image_descriptions/`.
