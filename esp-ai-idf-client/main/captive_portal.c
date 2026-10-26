#include "captive_portal.h"

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "esp_log.h"

// 最小 DNS 应答服务器：
// 收到查询后原样回显 header+question，A 查询附加一条 A 记录指向 192.168.4.1，
// AAAA 查询返回 0 条记录（避免系统优先 IPv6 导致探测失败）。
// 手机系统/浏览器的所有探测域名都会落到设备 HTTP 服务上，触发 Captive Portal 识别。

static const char *TAG = "captive";

#define DNS_PORT 53
#define AP_IP    "192.168.4.1"

static int s_dns_sock = -1;
static volatile bool s_dns_running = false;
static TaskHandle_t s_dns_task_handle = NULL;

// 在 query 报文中解析第一个 question 的类型；qtype 输出参数可空
static int dns_question_end(const uint8_t *pkt, int len, uint16_t *qtype)
{
    int p = 12;  // 跳过 header
    while (p < len && pkt[p] != 0) {
        if (pkt[p] & 0xC0) return -1;  // 压缩指针不应出现在 question
        p += pkt[p] + 1;
    }
    p += 1;  // 结尾 0 字节
    if (p + 4 > len) return -1;
    if (qtype) *qtype = ((uint16_t)pkt[p] << 8) | pkt[p + 1];
    return p + 4;
}

static void dns_task(void *arg)
{
    uint8_t rx[512];
    uint8_t tx[600];
    struct sockaddr_in src;
    socklen_t sl = sizeof(src);

    while (s_dns_running) {
        int n = recvfrom(s_dns_sock, rx, sizeof(rx), 0, (struct sockaddr *)&src, &sl);
        if (n < 12 || !s_dns_running) continue;

        uint16_t qtype = 0;
        int qend = dns_question_end(rx, n, &qtype);
        if (qend < 0 || qend > (int)sizeof(tx)) continue;

        // header：复制事务 ID；flags 置标准应答+递归可用；ANCOUNT 按 A 查询置 1
        memcpy(tx, rx, qend);
        tx[2] = 0x81;  // QR=1 应答, RD=1 保持
        tx[3] = 0x80;  // RA=1, RCODE=0 无错误
        tx[6] = tx[7] = 0;  // NSCOUNT=0
        tx[10] = tx[11] = 0;  // ARCOUNT=0

        int total = qend;
        if (qtype == 1) {  // A 查询 → 1 条 A 记录 192.168.4.1
            static const uint8_t answer[16] = {
                0xC0, 0x0C,        // NAME: 指向 question 起始
                0x00, 0x01,        // TYPE: A
                0x00, 0x01,        // CLASS: IN
                0x00, 0x00, 0x00, 0x3C,  // TTL: 60s
                0x00, 0x04,        // RDLENGTH: 4
                192, 168, 4, 1     // RDATA
            };
            if (total + sizeof(answer) > (int)sizeof(tx)) continue;
            memcpy(tx + total, answer, sizeof(answer));
            total += sizeof(answer);
            tx[7] = 1;  // ANCOUNT=1
        } else {
            tx[7] = 0;  // AAAA/其他：0 条记录，客户端会回退 A 查询
        }

        sendto(s_dns_sock, tx, total, 0, (struct sockaddr *)&src, sl);
    }
    vTaskDelete(NULL);
}

esp_err_t captive_portal_start(void)
{
    if (s_dns_sock >= 0) return ESP_OK;

    s_dns_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s_dns_sock < 0) {
        ESP_LOGE(TAG, "DNS socket 创建失败 errno=%d", errno);
        return ESP_FAIL;
    }
    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(DNS_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(s_dns_sock, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        ESP_LOGE(TAG, "DNS bind 53 端口失败 errno=%d", errno);
        close(s_dns_sock);
        s_dns_sock = -1;
        return ESP_FAIL;
    }

    s_dns_running = true;
    if (xTaskCreate(dns_task, "captive_dns", 4096, NULL, 4, &s_dns_task_handle) != pdPASS) {
        s_dns_running = false;
        close(s_dns_sock);
        s_dns_sock = -1;
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "Captive DNS 已启动: *.%s", AP_IP);
    return ESP_OK;
}

void captive_portal_stop(void)
{
    if (s_dns_sock < 0) return;
    s_dns_running = false;
    close(s_dns_sock);   // 阻塞的 recvfrom 立即返回并退出任务
    s_dns_sock = -1;
    s_dns_task_handle = NULL;
    ESP_LOGI(TAG, "Captive DNS 已停止");
}
