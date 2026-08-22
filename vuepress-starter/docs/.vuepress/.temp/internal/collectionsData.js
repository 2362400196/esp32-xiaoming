export const collections = {}

if (import.meta.webpackHot) {
  import.meta.webpackHot.accept()
  if (__VUE_HMR_RUNTIME__.updateCollections) {
    __VUE_HMR_RUNTIME__.updateCollections(collections)
  }
}

if (import.meta.hot) {
  import.meta.hot.accept(({ collections }) => {
    __VUE_HMR_RUNTIME__.updateCollections(collections)
  })
}
