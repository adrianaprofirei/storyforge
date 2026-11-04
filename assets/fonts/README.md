# Caption fonts

Captions and graphics use the font named by the caption style (`Inter` for `bold_pop` and
`clean_minimal`, `DejaVu Sans` for `comic`). Drop `.ttf`/`.otf` files here (git-ignored) and they
are passed to libass via `fontsdir`, so the render does not depend on system fonts; otherwise
the system font of that name is used, with libass' fallback when it is missing.

Inter (SIL Open Font License) is a good default: https://rsms.me/inter/
