---
{
  "name": "new",
  "description": "如果用户想要获取B站热门视频时激活这个技能",
  "metadata": {
    "cap_groups": [],
    "manage_mode": "readonly",
    "category": [],
    "tags": []
  }
}
---

# new

如果用户想要获取最新热榜或者是热点或者是新闻激活这个技能

## 执行步骤

如果用户想要获取B站热门视频时候，你用http_request工具来访问https://uapis.cn/api/v1/misc/hotboard?type=bilibili并且把你获取的内容总结一下。大概都有什么热点回答不要太长。
