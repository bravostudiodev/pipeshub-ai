# Slidev animations

Use `v-click` to reveal an element on the next click, or `v-clicks` to reveal
each child in sequence. Add `v-after` to reveal content with the previous
click. A click sequence is local to its slide.

```md
<v-click>Appears on click</v-click>

<v-clicks>
- First point
- Second point
</v-clicks>
```

Click ranges in code fences are written as `{1|2-3|all}`. Keep motion subtle
and use it to guide attention rather than decorate every element.

Full upstream guide: https://sli.dev/guide/animations
