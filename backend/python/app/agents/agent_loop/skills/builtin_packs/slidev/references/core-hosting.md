# Static hosting

Slidev's production build is a static site. In this fork the build helper
embeds the whole site into one self-contained `dist/index.html` with hash
routing, so it opens directly in a browser and in the OddJeeves preview
without a server.

The downloadable archive includes that `dist/index.html`, the editable
`slides.md`, and local assets. The sandbox does not publish or host the site.
Do not use remote images or fonts; include local copies instead.

Full upstream hosting guide: https://sli.dev/guide/hosting
