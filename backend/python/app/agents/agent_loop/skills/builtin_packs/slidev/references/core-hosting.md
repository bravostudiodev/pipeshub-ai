# Static hosting

Slidev's production build is a static site. In this fork the site uses a
relative base and hash routing so it can be served from a folder without
server-side history rewrites.

The downloadable archive includes `dist/`, editable `slides.md`, and local
assets. To review it locally, extract the ZIP and run:

```sh
python3 -m http.server 8000 --directory dist
```

Then open `http://localhost:8000/`. The sandbox does not publish or host the
site. Do not use remote images or fonts; include local copies instead.

Full upstream hosting guide: https://sli.dev/guide/hosting
