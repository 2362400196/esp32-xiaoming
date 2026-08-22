export const siteData = JSON.parse("{\"base\":\"/\",\"lang\":\"zh-CN\",\"title\":\"小明同学\",\"description\":\"小明同学智能语音助手 - 服务端 · 客户端 · 硬件\",\"head\":[],\"locales\":{\"/\":{\"lang\":\"zh-CN\",\"title\":\"小明同学\",\"description\":\"小明同学智能语音助手 - 服务端 · 客户端 · 硬件\"}}}")

if (import.meta.webpackHot) {
  import.meta.webpackHot.accept()
  __VUE_HMR_RUNTIME__.updateSiteData?.(siteData)
}

if (import.meta.hot) {
  import.meta.hot.accept((m) => {
    __VUE_HMR_RUNTIME__.updateSiteData?.(m.siteData)
  })
}
