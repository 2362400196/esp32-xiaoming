# 项目简介

## 开源地址

项目全部开源，托管在 Gitee，欢迎 Star、Fork 与贡献：

| 组件 | 仓库 |
|------|------|
| 📟 客户端固件 | [esp-ai-idf-client](https://gitee.com/zhuxiaohuaqn/esp-ai-idf-client) |
| 🖥️ 服务端 | [esp-ai-server](https://gitee.com/zhuxiaohuaqn/esp-ai-server) |
| 📱 手机 App | [esp-ai-app](https://gitee.com/zhuxiaohuaqn/esp-ai-app) |

> 采用 MIT 开源协议，Python / C++ / Vue 全栈开源，本地化部署，数据自主可控。

小明同学是一套**开源的智能语音助手方案**：把一块几十块钱的 ESP32 开发板，变成能听懂你说话、会开口回答、还有小表情的"桌面小助手"。

它支持本地化部署——服务端跑在你自己的电脑或服务器上，数据、音色、对话记录都归你管，不依赖任何厂商云平台。

它还**支持运行小龙虾**，语音就能编程——对着设备说句话，就能完成开发任务。

## 一套系统，四块拼图

小明同学不是单个软件，而是四部分协作：

| 拼图 | 是什么 | 打个比方 |
|------|--------|----------|
| 硬件设备 | 一块 ESP32-S3 开发板 + 麦克风 + 喇叭 + 小屏幕 | 助手的"身体" |
| 客户端固件 | 烧录进板子的程序，负责听、说、显示 | 助手的"本能反应" |
| 服务端 | 跑在你电脑/服务器上的程序，负责思考 | 助手的"大脑" |
| 手机 App | 手机上的配网和管理工具 | 助手的"遥控器" |

## 用它能做出什么

一个 ESP32-S3 开发板，配上这套软件，就能变成各种有趣的语音设备：


<style>
:root {
  --surface: #ffffff;
  --surface-muted: #f5f5f7;
  --border: #e5e5ea;
  --text-primary: #1d1d1f;
  --text-muted: #86868b;
  --brand: #7c3aed;
  --brand-light: #ede9fe;
  --accent: #f59e0b;
  --accent-light: #fef3c7;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "SF Mono", Monaco, Consolas, monospace;
}
</style>

<svg viewBox="0 0 720 800" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg">
  <text x="20" y="28" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--text-muted)">一块开发板，能做出什么</text>
  <line x1="20" y1="34" x2="700" y2="34" stroke="var(--border)" stroke-width="1"/>

  <!-- 辐射连线 -->
  <g stroke="var(--brand)" stroke-width="1.5" opacity="0.5">
    <line x1="360" y1="254" x2="360" y2="137"/>
    <line x1="400" y1="270" x2="519" y2="212"/>
    <line x1="400" y1="350" x2="499" y2="436"/>
    <line x1="360" y1="366" x2="360" y2="493"/>
    <line x1="320" y1="350" x2="221" y2="436"/>
    <line x1="320" y1="270" x2="201" y2="212"/>
  </g>

  <!-- 上：智能音箱 -->
  <rect x="281" y="57" width="158" height="78" rx="12" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <circle cx="360" cy="83" r="15" fill="#ffffff" stroke="#fde68a" stroke-width="1.5"/>
  <text x="360" y="90" font-family="var(--font-sans)" font-size="15" text-anchor="middle">🔈</text>
  <text x="360" y="110" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">智能音箱</text>
  <text x="360" y="126" font-family="var(--font-sans)" font-size="10" fill="#b45309" text-anchor="middle">点歌 · 问答 · 闹钟</text>

  <!-- 右上：儿童陪伴玩具 -->
  <rect x="521" y="165" width="158" height="78" rx="12" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <circle cx="600" cy="191" r="15" fill="#ffffff" stroke="#fde68a" stroke-width="1.5"/>
  <text x="600" y="198" font-family="var(--font-sans)" font-size="15" text-anchor="middle">🧸</text>
  <text x="600" y="218" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">儿童陪伴玩具</text>
  <text x="600" y="234" font-family="var(--font-sans)" font-size="10" fill="#b45309" text-anchor="middle">讲故事 · 学知识</text>

  <!-- 右下：智能机器人 -->
  <rect x="501" y="393" width="158" height="78" rx="12" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <circle cx="580" cy="419" r="15" fill="#ffffff" stroke="#fde68a" stroke-width="1.5"/>
  <text x="580" y="426" font-family="var(--font-sans)" font-size="15" text-anchor="middle">🤖</text>
  <text x="580" y="446" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">智能机器人</text>
  <text x="580" y="462" font-family="var(--font-sans)" font-size="10" fill="#b45309" text-anchor="middle">语音交互 · 表情 · 技能</text>

  <!-- 下：智能小车 -->
  <rect x="281" y="495" width="158" height="78" rx="12" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <circle cx="360" cy="521" r="15" fill="#ffffff" stroke="#fde68a" stroke-width="1.5"/>
  <text x="360" y="528" font-family="var(--font-sans)" font-size="15" text-anchor="middle">🚗</text>
  <text x="360" y="548" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">智能小车</text>
  <text x="360" y="564" font-family="var(--font-sans)" font-size="10" fill="#b45309" text-anchor="middle">语音控制 · 自主对话</text>

  <!-- 左下：桌面语音助手 -->
  <rect x="61" y="393" width="158" height="78" rx="12" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <circle cx="140" cy="419" r="15" fill="#ffffff" stroke="#fde68a" stroke-width="1.5"/>
  <text x="140" y="426" font-family="var(--font-sans)" font-size="15" text-anchor="middle">💬</text>
  <text x="140" y="446" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">桌面语音助手</text>
  <text x="140" y="462" font-family="var(--font-sans)" font-size="10" fill="#b45309" text-anchor="middle">随时唤醒 · 全屋控制</text>

  <!-- 左上：智能家居控制 -->
  <rect x="41" y="165" width="158" height="78" rx="12" fill="var(--accent-light)" stroke="var(--accent)" stroke-width="1"/>
  <circle cx="120" cy="191" r="15" fill="#ffffff" stroke="#fde68a" stroke-width="1.5"/>
  <text x="120" y="198" font-family="var(--font-sans)" font-size="15" text-anchor="middle">🏠</text>
  <text x="120" y="218" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="#92400e" text-anchor="middle">智能家居控制</text>
  <text x="120" y="234" font-family="var(--font-sans)" font-size="10" fill="#b45309" text-anchor="middle">语音开关灯 · 控制设备</text>

  <!-- 中心：ESP32-S3 -->
  <circle cx="360" cy="310" r="56" fill="var(--brand)"/>
  <text x="360" y="303" font-family="var(--font-sans)" font-size="15" font-weight="700" fill="#ffffff" text-anchor="middle">ESP32-S3</text>
  <text x="360" y="321" font-family="var(--font-sans)" font-size="9.5" fill="#ffffff" fill-opacity="0.9" text-anchor="middle">一块开发板 · 无限可能</text>

  <!-- 分隔线 -->
  <line x1="20" y1="650" x2="700" y2="650" stroke="var(--border)" stroke-width="1"/>
  <text x="20" y="680" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--text-muted)">适合人群</text>
  <line x1="20" y1="686" x2="240" y2="686" stroke="var(--border)" stroke-width="1"/>

  <!-- 适合人群：家庭用户 -->
  <rect x="41" y="700" width="198" height="86" rx="12" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1" stroke-opacity="0.6"/>
  <circle cx="83" cy="736" r="15" fill="#ffffff" stroke="#ddd6fe" stroke-width="1.5"/>
  <text x="83" y="743" font-family="var(--font-sans)" font-size="15" text-anchor="middle">🏠</text>
  <text x="110" y="734" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--brand)" text-anchor="start">家庭用户</text>
  <text x="110" y="752" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="start">给家里添个会说话的助手</text>

  <!-- 适合人群：学习开发者 -->
  <rect x="261" y="700" width="198" height="86" rx="12" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1" stroke-opacity="0.6"/>
  <circle cx="303" cy="736" r="15" fill="#ffffff" stroke="#ddd6fe" stroke-width="1.5"/>
  <text x="303" y="743" font-family="var(--font-sans)" font-size="15" text-anchor="middle">🎓</text>
  <text x="330" y="734" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--brand)" text-anchor="start">学习开发者</text>
  <text x="330" y="752" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="start">嵌入式 + AI 全栈开源</text>

  <!-- 适合人群：产品团队 -->
  <rect x="481" y="700" width="198" height="86" rx="12" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1" stroke-opacity="0.6"/>
  <circle cx="523" cy="736" r="15" fill="#ffffff" stroke="#ddd6fe" stroke-width="1.5"/>
  <text x="523" y="743" font-family="var(--font-sans)" font-size="15" text-anchor="middle">🏭</text>
  <text x="550" y="734" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--brand)" text-anchor="start">产品团队</text>
  <text x="550" y="752" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="start">快速做出语音产品原型</text>
</svg>

> 上面只是几个例子——它支持多板型与模块化扩展，你可以把它改造成任何你想要的语音设备。

## 它能帮你做什么

- **语音聊天** — 喊一声唤醒词，就能和它对话，像和朋友聊天一样
- **问答百科** — 问天气、问时间、问知识，它都能答
- **定闹钟/提醒** — "十分钟后提醒我关火"，到点它会主动说话
- **放音乐** — 说"放首歌"，它给你播音乐，还能显示歌词
- **控制智能家居** — 通过语音控制灯、音量、设备模式
- **有表情有温度** — 说话时屏幕会显示表情动画，AI 还会主动找你聊天
- **越用越懂你** — 它有记忆、有成长系统，能记日记、记偏好、分析情绪

## 服务端：你自己的"AI 大脑"

服务端负责把语音变成文字、把文字交给大模型思考、再把回答变成语音发回设备。整个过程是**流式的**——你说完话，它几乎同时开始回答，不用干等。

它支持多家 AI 服务自由切换（火山引擎、腾讯云、阿里云、DeepSeek、GPT 等），并且可以同时管理**多台设备**，每台设备可以配不同的音色、性格和系统提示词。

## 手机 App：遥控器

手机 App 负责：

- **一键配网** — 通过蓝牙把 WiFi 和服务器地址发给设备，不用敲命令行
- **设备管理** — 查看、绑定、解绑设备
- **音色管理** — 给设备换声音，选你喜欢的音色
- **表情包管理** — 上传、切换设备的表情动画
- **技能管理** — 开启/关闭设备的能力（工具、MCP 服务）
- **微信绑定** — 绑定后直接在微信里和设备聊天

## 复刻流程

三步就能拥有自己的语音助手：

<svg viewBox="0 0 720 200" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arrFlow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto">
      <path d="M1,1 L7,4 L1,7 Z" fill="var(--brand)"/>
    </marker>
  </defs>

  <!-- 步骤1：购买硬件 -->
  <rect x="30" y="60" width="190" height="96" rx="12" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1" stroke-opacity="0.6"/>
  <circle cx="125" cy="84" r="14" fill="#ffffff" stroke="#ddd6fe" stroke-width="1.5"/>
  <text x="125" y="91" font-family="var(--font-sans)" font-size="14" text-anchor="middle">🛒</text>
  <text x="125" y="116" font-family="var(--font-sans)" font-size="14" font-weight="600" fill="var(--brand)" text-anchor="middle">购买硬件</text>
  <text x="125" y="136" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="middle">ESP32-S3 开发板</text>
  <text x="125" y="150" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="middle">配麦克风 · 喇叭 · 屏幕</text>

  <!-- 箭头 -->
  <line x1="220" y1="108" x2="263" y2="108" stroke="var(--brand)" stroke-width="1.5" marker-end="url(#arrFlow)"/>

  <!-- 步骤2：烧录固件 -->
  <rect x="265" y="60" width="190" height="96" rx="12" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1" stroke-opacity="0.6"/>
  <circle cx="360" cy="84" r="14" fill="#ffffff" stroke="#ddd6fe" stroke-width="1.5"/>
  <text x="360" y="91" font-family="var(--font-sans)" font-size="14" text-anchor="middle">🔥</text>
  <text x="360" y="116" font-family="var(--font-sans)" font-size="14" font-weight="600" fill="var(--brand)" text-anchor="middle">烧录固件</text>
  <text x="360" y="136" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="middle">下载固件或 idf.py</text>
  <text x="360" y="150" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="middle">一键烧录</text>

  <!-- 箭头 -->
  <line x1="455" y1="108" x2="498" y2="108" stroke="var(--brand)" stroke-width="1.5" marker-end="url(#arrFlow)"/>

  <!-- 步骤3：搭建服务端 -->
  <rect x="500" y="60" width="190" height="96" rx="12" fill="var(--brand-light)" stroke="var(--brand)" stroke-width="1" stroke-opacity="0.6"/>
  <circle cx="595" cy="84" r="14" fill="#ffffff" stroke="#ddd6fe" stroke-width="1.5"/>
  <text x="595" y="91" font-family="var(--font-sans)" font-size="14" text-anchor="middle">🖥️</text>
  <text x="595" y="116" font-family="var(--font-sans)" font-size="14" font-weight="600" fill="var(--brand)" text-anchor="middle">搭建服务端</text>
  <text x="595" y="136" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="middle">部署到电脑或服务器</text>
  <text x="595" y="150" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="middle">5 分钟启动</text>
</svg>

1. **购买硬件** — 一块 ESP32-S3 开发板，加上麦克风、喇叭和小屏幕（参考[硬件接线](/guide/client/wiring)）
2. **烧录固件** — 下载固件包，或用 `idf.py` 一键烧录（参考[烧录指南](/guide/client/flash)）
3. **搭建服务端** — 部署在自己的电脑或服务器上，配好 AI 服务，5 分钟启动（参考[快速开始](/guide/server/get-started)）

## 下一步

- 想快速跑起来？看[快速开始](/guide/server/get-started)
- 想了解全部能力？看[全功能总览](/guide/features)
- 想深入研究技术细节？看[开发者文档](/dev/api)
