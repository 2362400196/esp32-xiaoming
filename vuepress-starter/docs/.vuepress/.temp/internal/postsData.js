export const postsData = {}

if (import.meta.webpackHot) {
  import.meta.webpackHot.accept()
  if (__VUE_HMR_RUNTIME__.updatePostsData) {
    __VUE_HMR_RUNTIME__.updatePostsData(postsData)
  }
}

if (import.meta.hot) {
  import.meta.hot.accept(({ postsData }) => {
    __VUE_HMR_RUNTIME__.updatePostsData(postsData)
  })
}
