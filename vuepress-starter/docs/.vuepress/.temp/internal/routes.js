export const redirects = JSON.parse("{}")

export const routes = Object.fromEntries([
  ["/", { loader: () => import(/* webpackChunkName: "index.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/README.md"), meta: {"title":""} }],
  ["/dev/api.html", { loader: () => import(/* webpackChunkName: "dev_api.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/api.md"), meta: {"title":"API 文档"} }],
  ["/dev/music.html", { loader: () => import(/* webpackChunkName: "dev_music.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/music.md"), meta: {"title":"音乐播放协议"} }],
  ["/guide/features.html", { loader: () => import(/* webpackChunkName: "guide_features.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/guide/features.md"), meta: {"title":"全功能总览"} }],
  ["/guide/intro.html", { loader: () => import(/* webpackChunkName: "guide_intro.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/guide/intro.md"), meta: {"title":"项目简介"} }],
  ["/plugin/plugin-dev.html", { loader: () => import(/* webpackChunkName: "plugin_plugin-dev.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/plugin/plugin-dev.md"), meta: {"title":"插件开发教程"} }],
  ["/plugin/plugin-sdk.html", { loader: () => import(/* webpackChunkName: "plugin_plugin-sdk.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/plugin/plugin-sdk.md"), meta: {"title":"插件公共工具库（Plugin SDK）"} }],
  ["/plugin/sandbox.html", { loader: () => import(/* webpackChunkName: "plugin_sandbox.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/plugin/sandbox.md"), meta: {"title":"插件沙箱机制"} }],
  ["/plugin/writing-first-plugin.html", { loader: () => import(/* webpackChunkName: "plugin_writing-first-plugin.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/plugin/writing-first-plugin.md"), meta: {"title":"编写第一个插件"} }],
  ["/dev/client/idf-board-adaptation.html", { loader: () => import(/* webpackChunkName: "dev_client_idf-board-adaptation.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/client/idf-board-adaptation.md"), meta: {"title":"适配自己的开发板"} }],
  ["/dev/client/idf-board-switch.html", { loader: () => import(/* webpackChunkName: "dev_client_idf-board-switch.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/client/idf-board-switch.md"), meta: {"title":"切换开发板"} }],
  ["/dev/client/idf-compile.html", { loader: () => import(/* webpackChunkName: "dev_client_idf-compile.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/client/idf-compile.md"), meta: {"title":"编译固件"} }],
  ["/dev/client/idf-es8311.html", { loader: () => import(/* webpackChunkName: "dev_client_idf-es8311.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/client/idf-es8311.md"), meta: {"title":"ES8311 开发指南"} }],
  ["/dev/client/idf-intro.html", { loader: () => import(/* webpackChunkName: "dev_client_idf-intro.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/client/idf-intro.md"), meta: {"title":""} }],
  ["/dev/server/config.html", { loader: () => import(/* webpackChunkName: "dev_server_config.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/server/config.md"), meta: {"title":"配置文档"} }],
  ["/dev/server/database.html", { loader: () => import(/* webpackChunkName: "dev_server_database.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/server/database.md"), meta: {"title":"数据库设计"} }],
  ["/dev/server/extend.html", { loader: () => import(/* webpackChunkName: "dev_server_extend.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/server/extend.md"), meta: {"title":"扩展 ASR/LLM/TTS 方案"} }],
  ["/dev/server/intro.html", { loader: () => import(/* webpackChunkName: "dev_server_intro.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/server/intro.md"), meta: {"title":"简介"} }],
  ["/dev/server/mcp.html", { loader: () => import(/* webpackChunkName: "dev_server_mcp.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/server/mcp.md"), meta: {"title":"MCP 工具集成"} }],
  ["/dev/server/memory-system.html", { loader: () => import(/* webpackChunkName: "dev_server_memory-system.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/server/memory-system.md"), meta: {"title":"记忆系统"} }],
  ["/dev/server/permissions.html", { loader: () => import(/* webpackChunkName: "dev_server_permissions.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/server/permissions.md"), meta: {"title":"权限体系（角色与 API 分级）"} }],
  ["/dev/server/pipeline.html", { loader: () => import(/* webpackChunkName: "dev_server_pipeline.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/server/pipeline.md"), meta: {"title":"Pipeline 流式处理详解"} }],
  ["/dev/server/sdk.html", { loader: () => import(/* webpackChunkName: "dev_server_sdk.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/server/sdk.md"), meta: {"title":"服务端编程接口"} }],
  ["/dev/server/session-engine.html", { loader: () => import(/* webpackChunkName: "dev_server_session-engine.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/server/session-engine.md"), meta: {"title":"会话引擎与状态机"} }],
  ["/dev/server/skill-system.html", { loader: () => import(/* webpackChunkName: "dev_server_skill-system.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/server/skill-system.md"), meta: {"title":"技能系统"} }],
  ["/dev/server/ws.html", { loader: () => import(/* webpackChunkName: "dev_server_ws.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/dev/server/ws.md"), meta: {"title":"WebSocket 通信协议"} }],
  ["/guide/app/guide.html", { loader: () => import(/* webpackChunkName: "guide_app_guide.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/guide/app/guide.md"), meta: {"title":"App 操作指南"} }],
  ["/guide/client/flash.html", { loader: () => import(/* webpackChunkName: "guide_client_flash.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/guide/client/flash.md"), meta: {"title":"烧录固件"} }],
  ["/guide/client/wiring.html", { loader: () => import(/* webpackChunkName: "guide_client_wiring.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/guide/client/wiring.md"), meta: {"title":"默认接线"} }],
  ["/guide/server/config.html", { loader: () => import(/* webpackChunkName: "guide_server_config.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/guide/server/config.md"), meta: {"title":"最小配置"} }],
  ["/guide/server/get-started.html", { loader: () => import(/* webpackChunkName: "guide_server_get-started.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/guide/server/get-started.md"), meta: {"title":"快速开始"} }],
  ["/404.html", { loader: () => import(/* webpackChunkName: "404.html" */"C:/Users/23624/Desktop/esp/esp32-xiaoming/vuepress-starter/docs/.vuepress/.temp/pages/404.html.vue"), meta: {"title":""} }],
]);

if (import.meta.webpackHot) {
  import.meta.webpackHot.accept()
  __VUE_HMR_RUNTIME__.updateRoutes?.(routes)
  __VUE_HMR_RUNTIME__.updateRedirects?.(redirects)
}

if (import.meta.hot) {
  import.meta.hot.accept((m) => {
    __VUE_HMR_RUNTIME__.updateRoutes?.(m.routes)
    __VUE_HMR_RUNTIME__.updateRedirects?.(m.redirects)
  })
}
