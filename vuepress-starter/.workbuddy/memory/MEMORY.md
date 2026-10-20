# 项目长期备注

- 文档站：VuePress 2 + vuepress-theme-plume（暗色模式选择器 `[data-theme="dark"]`，备选 `html.dark`）。
- `docs/guide/client/wiring.md` 的接线页以「三种方案」组织：方案一 S3+ES8311（推荐）、方案二 S3+I2S 直连、方案三 C3+ES8311；屏幕接线只写一份共用小节，不放进行方案的接线表（用户明确反对重复）。
- 用户偏好：文档要精简、不重复、结构清晰；宁可一行指引链接也不要复述内容。
- markdown 内联 SVG 上色必须用 CSS class（属性 `fill="var(--x)"` 渲染不可靠）；`<style>` 块会被抽进打包 CSS，需用唯一类名（`.wiring`）避免污染全局。
- 构建验证：`npm run docs:build` 末尾 safe-delete 报错可忽略；页内锚点以 dist HTML 里的实际 id 为准。
