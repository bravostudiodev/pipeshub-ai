// Build a Slidev deck as one JS and one CSS file with imported assets embedded,
// so build_deck.py can fold everything into a single dist/index.html.
// `enforce: 'post'` lets this override the chunk splitting Slidev configures.
const singleFile = {
  name: 'oddjeeves-single-file',
  enforce: 'post',
  config(config) {
    config.build ??= {}
    config.build.assetsInlineLimit = () => true
    config.build.cssCodeSplit = false
    config.build.modulePreload = false
    // The `?print#/print` view, which build_deck.py's layout check renders, only exists
    // in builds with `download` on; enable it without showing a download button.
    config.define = { ...config.define, __SLIDEV_FEATURE_PRINT__: 'true' }
    for (const key of ['rollupOptions', 'rolldownOptions']) {
      const options = (config.build[key] ??= {})
      const outputs = Array.isArray(options.output) ? options.output : [(options.output ??= {})]
      for (const output of outputs) {
        delete output.manualChunks
        delete output.advancedChunks
        output.codeSplitting = false
      }
    }
  },
}

export default { plugins: [singleFile] }
