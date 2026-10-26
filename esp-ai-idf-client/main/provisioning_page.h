// 配网页面 HTML — AP 配网使用，视觉风格与 esp-ai-app 配网页保持一致
// （薄荷绿 #34d399 主色、#f5f5f5 页面底、白色圆角卡片、#f8f8f8 输入框）
#pragma once

const char provisioning_html[] = R"rawliteral(
<!DOCTYPE html>
<html lang='zh-CN'>

<head>
    <meta charset='UTF-8'>
    <meta name='viewport'
        content='viewport-fit=cover,width=device-width, initial-scale=1, maximum-scale=1, minimum-scale=1, user-scalable=no' />
    <title>设备配网</title>
    <style>
        * { -webkit-tap-highlight-color: transparent; }

        body {
            font-family: -apple-system, 'PingFang SC', 'Helvetica Neue', 'Microsoft YaHei', sans-serif;
            margin: 0;
            font-size: 14px;
            color: #1a1a1a;
            background-color: #f5f5f5;
        }

        /* ===== 顶部栏（与 App 顶部导航一致）===== */
        #page-header {
            position: sticky;
            top: 0;
            z-index: 5;
            background-color: #ffffff;
            padding: calc(env(safe-area-inset-top, 0px) + 14px) 16px 14px;
            text-align: center;
            font-size: 16px;
            font-weight: 600;
            color: #1a1a1a;
            border-bottom: 1px solid #f0f0f0;
        }

        #page-header .sub {
            display: block;
            font-size: 11px;
            font-weight: 400;
            color: #b0b0b0;
            margin-top: 3px;
        }

        .hint-bar {
            max-width: 420px;
            margin: 10px auto -4px;
            padding: 8px 12px;
            font-size: 11px;
            line-height: 1.6;
            color: #059669;
            background: #ecfdf5;
            border: 1px solid #a7f3d0;
            border-radius: 10px;
        }

        #wifi_setting_panel {
            max-width: 420px;
            margin: 0 auto;
            padding: 14px 14px 110px;
            box-sizing: border-box;
        }

        /* ===== 分区（App section-title + 白卡片）===== */
        .section-title {
            font-size: 14px;
            font-weight: 600;
            color: #1a1a1a;
            margin: 16px 2px 8px;
        }

        .section-title .opt {
            font-size: 11px;
            font-weight: 400;
            color: #b0b0b0;
        }

        .card {
            background-color: #ffffff;
            border-radius: 12px;
            padding: 4px 12px;
        }

        /* ===== 表单行（App cfg-row：label 左 + 控件右）===== */
        .row {
            display: flex;
            align-items: center;
            min-height: 48px;
            border-bottom: 1px solid #f5f5f5;
        }

        .row:last-child { border-bottom: none; }

        .label {
            flex-shrink: 0;
            width: 76px;
            font-size: 13px;
            color: #666666;
        }

        .label .req { color: #f87171; margin-right: 2px; }

        .input {
            flex: 1;
            min-width: 0;
            background-color: #f8f8f8;
            border: 1px solid transparent;
            border-radius: 8px;
            font-size: 13px;
            padding: 9px 10px;
            color: #1a1a1a;
            outline: none;
            box-sizing: border-box;
            -webkit-appearance: none;
            appearance: none;
            font-family: inherit;
        }

        .input::placeholder { color: #b0b0b0; }

        .input:focus {
            border-color: #34d399;
            background-color: rgba(52, 211, 153, 0.04);
        }

        /* 下拉：去原生外观 + 绿色三角箭头（App picker 同款） */
        select.input {
            padding-right: 26px;
            background-image: none;
            position: relative;
        }

        .picker-wrap { position: relative; flex: 1; min-width: 0; }

        .picker-wrap .input { width: 100%; }

        .picker-arrow {
            position: absolute;
            right: 10px;
            top: 50%;
            width: 0;
            height: 0;
            margin-top: -2px;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid #b0b0b0;
            pointer-events: none;
        }

        /* 密码可见性切换（App eye-icon 同款） */
        .pwd-wrap { display: flex; flex: 1; min-width: 0; align-items: center; gap: 8px; }

        .pwd-wrap .input { flex: 1; }

        .eye-btn {
            flex-shrink: 0;
            width: 30px;
            height: 30px;
            border: none;
            border-radius: 50%;
            background-color: #f8f8f8;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 0;
            cursor: pointer;
        }

        .eye-btn svg { width: 16px; height: 16px; stroke: #b0b0b0; fill: none; stroke-width: 1.6; }

        .eye-btn.on svg { stroke: #34d399; }

        .desc {
            font-size: 11px;
            color: #b0b0b0;
            line-height: 20px;
            padding: 10px 2px 0;
        }

        .device-id {
            font-size: 12px;
            color: #b0b0b0;
            text-align: center;
            padding: 26px 0 10px;
        }

        /* ===== 底部固定提交（App 主按钮同款）===== */
        #submit-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            padding: 12px 14px calc(env(safe-area-inset-bottom, 0px) + 14px);
            background: linear-gradient(to top, #f5f5f5 70%, rgba(245, 245, 245, 0));
        }

        #submit-inner { max-width: 392px; margin: 0 auto; }

        #submit-btn {
            width: 100%;
            box-sizing: border-box;
            border: none;
            border-radius: 10px;
            padding: 13px 0;
            font-size: 15px;
            font-weight: 600;
            letter-spacing: 4px;
            color: #ffffff;
            background-color: #34d399;
            cursor: pointer;
            transition: background-color 0.2s;
        }

        #submit-btn:active { background-color: #2bc48a; }

        /* ===== 弹窗（App 弹窗同款：白圆角 + 绿色按钮）===== */
        #msg {
            position: fixed;
            z-index: 10;
            inset: 0;
            background-color: rgba(0, 0, 0, 0.45);
            display: none;
            align-items: center;
            justify-content: center;
        }

        #msg_content {
            background-color: #fff;
            width: 280px;
            border-radius: 14px;
            padding: 22px 18px 14px;
            box-sizing: border-box;
        }

        #msg_content_text {
            max-height: 180px;
            overflow: auto;
            color: #333333;
            font-size: 14px;
            line-height: 22px;
            text-align: center;
            margin-bottom: 18px;
        }

        #msg_content_btns {
            background-color: #34d399;
            color: #fff;
            text-align: center;
            letter-spacing: 4px;
            border-radius: 10px;
            padding: 10px 0;
            font-size: 14px;
            cursor: pointer;
        }

        #msg_content_btns:active { background-color: #2bc48a; }

        /* ===== loading（绿色 spinner）===== */
        #loading {
            position: fixed;
            z-index: 20;
            inset: 0;
            background-color: rgba(255, 255, 255, 0.85);
            display: flex;
            align-items: center;
            justify-content: center;
        }

        #loading .icon {
            border: 5px solid rgba(52, 211, 153, 0.15);
            border-radius: 50%;
            border-top-color: #34d399;
            width: 44px;
            height: 44px;
            -webkit-animation: spin 0.9s linear infinite;
            animation: spin 0.9s linear infinite;
        }

        @-webkit-keyframes spin {
            0% { -webkit-transform: rotate(0deg); }
            100% { -webkit-transform: rotate(360deg); }
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>

<body>
    <div id='page-header'>设备配网<span class='sub'>连接设备热点后即可配置 WiFi 与服务端</span></div>

    <div class='hint-bar'>WiFi 列表会自动刷新；若迟迟未出现，请在系统弹窗中选择「保持连接」并稍等几秒</div>

    <div id='wifi_setting_panel'>
        <!-- ① 网络配置 -->
        <div class='section-title'>网络配置</div>
        <div class='card'>
            <div class='row'>
                <label class='label'><span class='req'>*</span>WiFi</label>
                <div class='picker-wrap'>
                    <select id='ssid' class='input'>
                        <option value='' id='scan-ing'>网络扫描中...</option>
                    </select>
                    <div class='picker-arrow'></div>
                </div>
            </div>
            <div class='row'>
                <label class='label'><span class='req'>*</span>WiFi密码</label>
                <div class='pwd-wrap'>
                    <input id='password' name='password' type='password' placeholder='请输入WiFi密码' class='input'>
                    <button type='button' class='eye-btn' id='eye-btn' onclick='togglePwd()'>
                        <svg viewBox='0 0 24 24'><path d='M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z'/><circle cx='12' cy='12' r='2.6'/></svg>
                    </button>
                </div>
            </div>
        </div>

        <!-- ② 唤醒/对话方式 -->
        <div class='section-title'>唤醒/对话方式</div>
        <div class='card'>
            <div class='row'>
                <label class='label'><span class='req'>*</span>唤醒方式</label>
                <div class='picker-wrap'>
                    <select id='wakeup-type' name='wakeup-type' class='input'>
                        <option value='boot'>BOOT按钮唤醒</option>
                        <option value='asrpro'>天问唤醒</option>
                        <option value='asrpro_boot'>天问唤醒+BOOT唤醒</option>
                        <option value='boot_listen'>按住对话(BOOT按钮)</option>
                    </select>
                    <div class='picker-arrow'></div>
                </div>
            </div>
        </div>

        <!-- ③ 服务配置 -->
        <div class='section-title'>服务配置</div>
        <div class='card'>
            <div class='row'>
                <label class='label'><span class='req'>*</span>服务协议</label>
                <div class='picker-wrap'>
                    <select id='ext4' name='ext4' class='input'>
                        <option value='http'>http</option>
                        <option value='https'>https</option>
                    </select>
                    <div class='picker-arrow'></div>
                </div>
            </div>
            <div class='row'>
                <label class='label'><span class='req'>*</span>服务地址</label>
                <input id='ext5' name='ext5' type='text' placeholder='IP 或域名' class='input'>
            </div>
            <div class='row'>
                <label class='label'><span class='req'>*</span>服务端口</label>
                <input id='ext6' name='ext6' type='text' inputmode='numeric' placeholder='如 8088' class='input'>
            </div>
            <div class='row'>
                <label class='label'>请求参数</label>
                <input id='ext8' name='ext8' type='text' placeholder='[可选]服务参数' class='input'>
            </div>
        </div>

        <div class='desc'>
            服务配置说明：<br/>
            1. 填写自建 esp-ai-server 的协议、地址和端口<br/>
            2. 默认端口 8088，与服务器部署配置保持一致
        </div>

        <div class='device-id'>设备编码：<span id='device_id'>-</span></div>
    </div>

    <!-- 底部固定提交 -->
    <div id='submit-bar'>
        <div id='submit-inner'>
            <button id='submit-btn'>保存</button>
        </div>
    </div>

    <div id='msg'>
        <div id='msg_content'>
            <div id='msg_content_text'></div>
            <div id='msg_content_btns' onclick='closeMsg()'>确定</div>
        </div>
    </div>
    <div id='loading'>
        <div class='icon'></div>
    </div>
</body>

</html>

<script>
    try {
        var domain = '';
        var loading = false;

        function myFetch(apiName, params, cb, method) {
            method = method || 'GET';
            var url = domain + apiName;
            var options = {
                method: method,
                mode: 'cors',
                headers: { 'Content-Type': 'application/json' }
            };
            if (method.toUpperCase() === 'POST') {
                options.body = JSON.stringify(params);
            }
            fetch(url, options)
                .then(function (res) { return res.json() })
                .then(function (data) { cb && cb(data); })
                .catch(function () { cb && cb({ success: false, message: '网络错误' }); });
        }

        function msg(text) {
            document.querySelector('#msg').style.display = 'flex';
            document.querySelector('#msg_content_text').innerHTML = text;
        }
        function closeMsg() {
            document.querySelector('#msg_content_text').innerHTML = '';
            document.querySelector('#msg').style.display = 'none';
        }

        function togglePwd() {
            var input = document.querySelector('#password');
            var btn = document.querySelector('#eye-btn');
            var show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            btn.classList.toggle('on', show);
        }

        function get_config() {
            myFetch('/get_config', {}, function (res) {
                document.querySelector('#loading').style.display = 'none';
                if (res.success) {
                    var data = res.data;
                    if (data.wifi_name) document.querySelector('#ssid').value = data.wifi_name;
                    if (data.wifi_pwd) document.querySelector('#password').value = data.wifi_pwd;
                    if (data.device_id) document.querySelector('#device_id').innerHTML = data.device_id;
                    if (data.ext4) document.querySelector('#ext4').value = data.ext4;
                    if (data.ext5) document.querySelector('#ext5').value = data.ext5;
                    if (data.ext6) document.querySelector('#ext6').value = data.ext6;
                    if (data.ext7) document.querySelector('#wakeup-type').value = data.ext7;
                    if (data.diyServerParams) document.querySelector('#ext8').value = data.diyServerParams;
                } else {
                    msg('请刷新页面重试');
                }
            });
        }

        function scan_ssids() {
            myFetch('/get_ssids', {}, function (res) {
                var ing = document.querySelector('#scan-ing');
                if (res.success) {
                    var data = res.data || [];
                    if (ing) ing.innerHTML = data.length ? '请选择wifi...' : '正在搜索附近的WiFi...';
                    var selectDom = document.getElementById('ssid');
                    var optionsName = [];
                    var options = selectDom.getElementsByTagName('option');
                    for (var i = 0; i < options.length; i++) {
                        optionsName.push(options[i].value);
                    }
                    data.forEach(function (item) {
                        if (item.ssid && !optionsName.includes(item.ssid)) {
                            var option = document.createElement('option');
                            option.innerText = item.ssid + ' (' + (item.channel <= 14 ? '2.4GHz' : '5GHz') + ')';
                            option.setAttribute('value', item.ssid);
                            selectDom.appendChild(option);
                        }
                    });
                }
                // 无论成功失败都持续轮询（参考 xiaozhi-esp32）：接口毫秒级返回，轮询永不超时
                setTimeout(scan_ssids, 3000);
            });
        }

        function setWifiInfo() {
            if (loading) return;
            var wifi_name = document.querySelector('#ssid').value;
            var wifi_pwd = document.querySelector('#password').value;
            var ext4 = document.querySelector('#ext4').value || '';
            var ext5 = document.querySelector('#ext5').value || '';
            var ext6 = document.querySelector('#ext6').value;
            var ext8 = document.querySelector('#ext8').value;
            var wakeupType = document.querySelector('#wakeup-type').value;

            if (!wifi_name) { msg('请输入WIFI账号哦~'); return; }
            if (!wifi_pwd) { msg('请输入WIFI密码哦~'); return; }
            if (!ext5) { msg('请输入服务地址哦~'); return; }
            if (!ext6) { msg('请输入服务端口哦~'); return; }

            loading = true;
            document.querySelector('#submit-btn').innerHTML = '配网中...';
            clearTimeout(window.reloadTimer);
            window.reloadTimer = setTimeout(function () {
                msg('未知配网状态，即将重启设备');
                setTimeout(function () { window.location.reload(); }, 2000);
            }, 20000);

            myFetch('/set_config', {
                wifi_name: wifi_name,
                wifi_pwd: wifi_pwd,
                ext4: ext4,
                ext5: ext5,
                ext6: ext6,
                ext7: wakeupType,
                diyServerParams: ext8
            }, function (res) {
                clearTimeout(window.reloadTimer);
                loading = false;
                document.querySelector('#submit-btn').innerHTML = '保存';
                if (res.success) {
                    msg(res.message);
                } else {
                    msg(res.message);
                }
            }, 'POST');
        }

        window.onload = function () {
            document.querySelector('#loading').style.display = 'none';
            get_config();
            scan_ssids();
            document.querySelector('#submit-btn').addEventListener('click', setWifiInfo);
        }
    } catch (e) {
        console.error(e);
    }
</script>
)rawliteral";
