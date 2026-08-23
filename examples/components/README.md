# Components

Components is the executable reference for `pyjs.web.ui`. It combines the
individual component catalog with composed application blocks and uses PyJS
partial navigation to keep its outer shell mounted between pages.

It demonstrates:

- the complete reusable component collection;
- accessible component states and interaction;
- a cohesive project workspace assembled from those components;
- server rendering of each page;
- a persistent `NavigationLayout` and `PageOutlet`;
- partial page downloads, History API updates, and browser hydration; and
- focused Python and managed-browser tests.

The same application is intended to power the future `/components/` section
of the PyJS website. Documentation can add prose, Python source, generated
JavaScript, and tests around these executable demonstrations.

## Run Components

From the repository root:

```console
uv run python -m pyjs_examples.components
```

Open the printed URL. Move between **Catalog** and **Workspace block** to see
the persistent shell and partial navigation.

## Run the tests

```console
uv run pytest -q examples/components/tests
uv run pytest -q examples/components/tests --pyjs-target=web \
  --pyjs-browser=managed
```
