import { defineClientConfig } from 'vuepress/client'
import VPCopyButton from 'C:/Users/23624/Desktop/esp-ai/vuepress-starter/node_modules/vuepress-theme-plume/node_modules/vuepress-plugin-md-power/dist/client/components/VPCopyButton.vue'
import Tabs from 'C:/Users/23624/Desktop/esp-ai/vuepress-starter/node_modules/vuepress-theme-plume/node_modules/vuepress-plugin-md-power/dist/client/components/Tabs.vue'
import CodeTabs from 'C:/Users/23624/Desktop/esp-ai/vuepress-starter/node_modules/vuepress-theme-plume/node_modules/vuepress-plugin-md-power/dist/client/components/CodeTabs.vue'
import Plot from 'C:/Users/23624/Desktop/esp-ai/vuepress-starter/node_modules/vuepress-theme-plume/node_modules/vuepress-plugin-md-power/dist/client/components/Plot.vue'
import FileTreeNode from 'C:/Users/23624/Desktop/esp-ai/vuepress-starter/node_modules/vuepress-theme-plume/node_modules/vuepress-plugin-md-power/dist/client/components/FileTreeNode.vue'
import { setupMarkHighlight } from 'C:/Users/23624/Desktop/esp-ai/vuepress-starter/node_modules/vuepress-theme-plume/node_modules/vuepress-plugin-md-power/dist/client/composables/mark.js'

import 'C:/Users/23624/Desktop/esp-ai/vuepress-starter/node_modules/vuepress-theme-plume/node_modules/vuepress-plugin-md-power/dist/client/styles/index.css'

export default defineClientConfig({
  enhance({ router, app }) {
    app.component('VPCopyButton', VPCopyButton)
    app.component('Tabs', Tabs)
    app.component('CodeTabs', CodeTabs)
    app.component('Plot', Plot)
    app.component('FileTreeNode', FileTreeNode)
  },
  setup() {
        setupMarkHighlight("eager")

  }
})
