"""
step6_web.py — Web 前端服务（Port 5000）

用户入口：
  - 提交直链 URL → 自动加入队列 → 显示排队序号
  - 查看排队情况（每个人只能看到自己的任务）
  - 用户隔离：浏览器指纹区分用户，本地 localStorage 持久化记录
  - 动态 ETA：100s × 等待添加 + 25s × 待解压，实时倒计时
  - 底部 GMT+8 实时时钟

流程:
  1. GET / → HTML 提交页面
  2. POST /submit → 接收 URL + fp → 写入 task_db（status=pending）
  3. GET /queue?fp=xxx → JSON（全局数字统计 + 该 fp 的任务列表）

需要:
  pip install flask
"""

import time
import logging
from pathlib import Path

# 日志：按天命名，追加写入。同一天多次启动共用同一个文件。
_log_dir = Path(__file__).parent
_today = time.strftime("%Y-%m-%d")
_log_file = _log_dir / f"step6_web_{_today}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8", mode="a"),
        logging.StreamHandler()
    ],
    force=True
)

from flask import Flask, request, jsonify, render_template_string

from task_db import add_task, get_queue_summary, get_all, clear_all

logger = logging.getLogger("step6_web")

app = Flask(__name__)


# ─── HTML 页面 ──────────────────────────────────────────────

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>解析站</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, 'Segoe UI', sans-serif;
      background: #0f0f1a;
      color: #e0e0e0;
      display: flex;
      justify-content: center;
      padding: 32px 16px;
      min-height: 100vh;
    }
    .container { max-width: 680px; width: 100%; }

    .card {
      background: rgba(255,255,255,0.06);
      -webkit-backdrop-filter: blur(12px);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 16px;
      padding: 24px;
      margin-bottom: 16px;
    }

    .header-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 16px;
    }
    .header-row h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.3px; }
    .header-row h1 span { color: #6c8cff; }

    /* ── 提交 ── */
    .url-input-row {
      display: flex;
      gap: 10px;
      margin-bottom: 10px;
    }
    .url-input-row input[type="url"] {
      flex: 1;
      padding: 12px 16px;
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 10px;
      background: rgba(0,0,0,0.3);
      color: #e0e0e0;
      font-size: 14px;
      outline: none;
      transition: border-color 0.2s;
    }
    .url-input-row input[type="url"]:focus { border-color: #6c8cff; }
    .url-input-row input[type="url"]::placeholder { color: rgba(255,255,255,0.3); }

    .btn-submit {
      padding: 12px 28px;
      background: linear-gradient(135deg, #6c8cff, #8b6cff);
      color: #fff;
      border: none;
      border-radius: 10px;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      transition: opacity 0.2s, transform 0.1s;
    }
    .btn-submit:hover { opacity: 0.9; }
    .btn-submit:active { transform: scale(0.97); }
    .btn-submit:disabled { opacity: 0.4; cursor: not-allowed; }

    .submit-result {
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 13px;
      display: none;
    }
    .submit-result.success {
      display: block;
      background: rgba(108,140,255,0.12);
      color: #8cb4ff;
      border: 1px solid rgba(108,140,255,0.25);
    }
    .submit-result.error {
      display: block;
      background: rgba(255,80,80,0.12);
      color: #ff6b6b;
      border: 1px solid rgba(255,80,80,0.25);
    }

    /* ── ETA ── */
    .eta-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 14px;
      background: rgba(255,255,255,0.04);
      border-radius: 10px;
      margin-bottom: 16px;
      font-size: 13px;
    }
    .eta-label { color: rgba(255,255,255,0.5); }
    .eta-value {
      font-size: 18px;
      font-weight: 700;
      color: #6c8cff;
      font-variant-numeric: tabular-nums;
    }

    /* ── 全局统计（仅数字，无明细） ── */
    .stats {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr 1fr;
      gap: 8px;
      margin-bottom: 16px;
    }
    .stat-box {
      text-align: center;
      padding: 12px 8px;
      background: rgba(255,255,255,0.04);
      border-radius: 10px;
    }
    .stat-box .num { font-size: 26px; font-weight: 700; color: #8cb4ff; }
    .stat-box .label { font-size: 11px; color: rgba(255,255,255,0.4); margin-top: 4px; }

    /* ── 任务列表 ── */
    .task-list { margin-top: 4px; }
    .task-item {
      display: flex;
      align-items: center;
      padding: 12px 0;
      border-bottom: 1px solid rgba(255,255,255,0.05);
      gap: 12px;
      font-size: 13px;
    }
    .task-item:last-child { border-bottom: none; }
    .task-order {
      width: 36px;
      color: rgba(255,255,255,0.3);
      font-size: 12px;
      flex-shrink: 0;
    }
    .task-status { flex-shrink: 0; }
    .task-url {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: rgba(255,255,255,0.6);
    }
    .task-action { flex-shrink: 0; }

    .badge {
      display: inline-block;
      padding: 3px 10px;
      border-radius: 20px;
      font-size: 11px;
      font-weight: 500;
    }
    .badge.pending { background: rgba(255,160,0,0.15); color: #ffb74d; }
    .badge.adding { background: rgba(255,140,0,0.18); color: #ff9800; }
    .badge.downloading { background: rgba(100,140,255,0.15); color: #8cb4ff; }
    .badge.ready { background: rgba(180,100,255,0.15); color: #c99bff; }
    .badge.decompressing { background: rgba(100,220,160,0.12); color: #6dd4a0; }
    .badge.done { background: rgba(100,220,160,0.12); color: #6dd4a0; }
    .badge.failed { background: rgba(255,80,80,0.12); color: #ff6b6b; }

    /* ── 液态玻璃「立即查看」按钮 ── */
    .btn-glass {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 10px 24px;
      background: rgba(108,140,255,0.12);
      -webkit-backdrop-filter: blur(8px);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(108,140,255,0.25);
      border-radius: 10px;
      color: #8cb4ff;
      font-size: 14px;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
      transition: background 0.2s, border-color 0.2s;
    }
    .btn-glass:hover {
      background: rgba(108,140,255,0.22);
      border-color: rgba(108,140,255,0.4);
    }

    /* ── 底部时钟 ── */
    /* ── 作者信息 ── */
    .author-bar {
      text-align: center;
      padding: 6px 0 2px;
      font-size: 13px;
      color: rgba(255,255,255,0.25);
    }
    .author-bar a {
      color: rgba(255,255,255,0.3);
      text-decoration: none;
      transition: color 0.2s;
    }
    .author-bar a:hover { color: rgba(255,255,255,0.5); }
    .author-bar .sub { font-size: 11px; margin-top: 2px; }

    .footer-clock {
      text-align: center;
      padding: 4px 0 16px;
      font-size: 13px;
      color: rgba(255,255,255,0.25);
      font-variant-numeric: tabular-nums;
      letter-spacing: 0.5px;
    }

    .empty-state {
      text-align: center;
      padding: 32px 0;
      color: rgba(255,255,255,0.2);
      font-size: 13px;
    }

    /* ── 首次访问弹窗 ── */
    .welcome-overlay {
      position: fixed; top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.5);
      display: flex; align-items: center; justify-content: center;
      z-index: 9999;
    }
    .welcome-overlay.hidden { display: none; }
    .welcome-box {
      width: 340px; max-width: 90vw;
      background: #fff; border-radius: 16px;
      padding: 32px 28px;
      text-align: center;
      box-shadow: 0 8px 40px rgba(0,0,0,0.3);
    }
    .welcome-box .title {
      font-size: 20px; font-weight: 700; color: #000;
      margin-bottom: 2px;
    }
    .welcome-box .subtitle {
      font-size: 12px; color: #999; margin-bottom: 20px;
    }
    .welcome-box .help-btn {
      display: block;
      padding: 12px 16px;
      background: rgba(108,140,255,0.12);
      -webkit-backdrop-filter: blur(8px);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(108,140,255,0.25);
      border-radius: 10px;
      color: #6c8cff;
      font-size: 14px; font-weight: 600;
      text-decoration: none;
      margin-bottom: 14px;
      transition: background 0.2s;
    }
    .welcome-box .help-btn:hover { background: rgba(108,140,255,0.22); }
    .welcome-box .dismiss {
      display: block;
      font-size: 13px; color: #e05050; font-weight: 500;
      cursor: pointer; padding: 4px 0;
      transition: opacity 0.2s;
    }
    .welcome-box .dismiss:hover { opacity: 0.7; }

    /* ── 右下角小按钮 ── */
    .help-corner {
      position: fixed; bottom: 20px; right: 20px;
      width: 44px; height: 44px;
      background: rgba(108,140,255,0.15);
      -webkit-backdrop-filter: blur(8px);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(108,140,255,0.25);
      border-radius: 50%;
      color: #8cb4ff;
      font-size: 20px;
      display: flex; align-items: center; justify-content: center;
      cursor: pointer; z-index: 9998;
      transition: background 0.2s, transform 0.15s;
      text-decoration: none;
    }
    .help-corner:hover { background: rgba(108,140,255,0.25); transform: scale(1.05); }

    @media (max-width: 480px) {
      body { padding: 16px 12px; }
      .card { padding: 16px; }
      .url-input-row { flex-direction: column; }
      .btn-submit { width: 100%; }
      .stats { gap: 6px; }
      .stat-box .num { font-size: 22px; }
    }

    /* task time column */
    .task-time {
      flex-shrink: 0;
      color: rgba(255,255,255,0.35);
      font-size: 11px;
      font-variant-numeric: tabular-nums;
      width: 40px;
    }

    .btn-action { padding: 8px 14px; font-size: 12px; }
    .task-action { white-space: nowrap; }

    .note-overlay {
      position: fixed; top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.3);
      display: none; align-items: center; justify-content: center;
      z-index: 9999;
    }
    .note-overlay.show { display: flex; }
    .note-box {
      width: 360px; max-width: 90vw;
      background: #fff; border-radius: 16px;
      padding: 28px 24px;
      position: relative;
    }
    .note-inner {
      width: 100%; aspect-ratio: 16 / 9;
      background: #000; border-radius: 10px;
      margin: 0 auto;
      display: flex; align-items: center; justify-content: center;
      cursor: text;
      position: relative;
    }
    .note-inner textarea {
      width: 100%; height: 100%;
      background: transparent;
      border: none;
      outline: none;
      color: #fff;
      font-size: 14px;
      line-height: 1.5;
      padding: 16px;
      resize: none;
      font-family: inherit;
    }
    .note-inner textarea::placeholder {
      color: rgba(255,255,255,0.35);
    }
  </style>
</head>
<body>
  <div class="container">

    <div class="card" style="padding:16px 24px;">
      <div class="header-row" style="margin-bottom:0;">
        <h1>&#x1F527; <span>解析站</span></h1>
      </div>
    </div>

    <!-- 提交 -->
    <div class="card">
      <div class="url-input-row">
        <input type="url" id="urlInput" placeholder="粘贴直链 URL ..." autocomplete="off">
        <button class="btn-submit" id="submitBtn" onclick="submitTask()">提交</button>
      </div>
      <div id="submitResult" class="submit-result"></div>
    </div>

    <!-- 我的任务 -->
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
        <h2 style="font-size:16px;font-weight:500;">&#x1F4CB; 我的任务</h2>
      </div>

      <div class="eta-bar">
        <span class="eta-label">预估等待</span>
        <span class="eta-value" id="etaDisplay">--:--</span>
      </div>

      <div class="stats" id="stats">
        <div class="stat-box"><div class="num" id="globalPending">-</div><div class="label">等待添加</div></div>
        <div class="stat-box"><div class="num" id="globalAdding">-</div><div class="label">添加中</div></div>
        <div class="stat-box"><div class="num" id="globalDownloading">-</div><div class="label">下载中</div></div>
        <div class="stat-box"><div class="num" id="globalReady">-</div><div class="label">待解压</div></div>
        <div class="stat-box"><div class="num" id="globalFailed" style="color:#ff6b6b;">-</div><div class="label">失败待处理</div></div>
      </div>

      <div class="task-list" id="taskList"></div>
      <div class="empty-state" id="emptyState">暂无任务记录</div>
    </div>

    <div class="author-bar">
      &#x1F4E7; 作者QQ 3483180932
      <div class="sub"><a href="https://link3.cc/water_molecule" target="_blank">&#x1F517; 长时间不回复 link3.cc/water_melocule</a></div>
    </div>
    <div class="footer-clock" id="footerClock"></div>
  </div>

  <!-- note overlay -->
  <div class="note-overlay" id="noteOverlay" onclick="saveNoteAndClose()">
    <div class="note-box" onclick="event.stopPropagation()">
      <div class="note-inner" onclick="document.getElementById('noteInput').focus()">
        <textarea id="noteInput" placeholder="点击这里添加备注" maxlength="500"></textarea>
      </div>
    </div>
  </div>

  <!-- welcome overlay -->
  <div class="welcome-overlay" id="welcomeOverlay">
    <div class="welcome-box">
      <div class="title">&#x1F527; 本站永久公益免费</div>
      <div class="subtitle">仅供学习交流</div>
      <a class="help-btn" id="helpBtn" href="https://gcnk5l8dhg5s.feishu.cn/docx/HSg5dSYMzog8FnxwZV6cLTMJnWe?from=from_copylink" target="_blank">&#x1F4D6; 如果卡住了或者显示失败<br>点击我可以看说明文档</a>
      <div class="dismiss" onclick="dismissWelcome()">不需要可以先关掉<br>右下角等你哦</div>
    </div>
  </div>

  <!-- 右下角帮助按钮 -->
  <a class="help-corner" id="helpCorner" href="https://gcnk5l8dhg5s.feishu.cn/docx/HSg5dSYMzog8FnxwZV6cLTMJnWe?from=from_copylink" target="_blank" style="display:none;">&#x2764;</a>

  <script>
    // ============================================================
    // 指纹管理 — 浏览器本地生成，每次访问不变
    // ============================================================
    var FP = localStorage.getItem('decomp_fp');
    if (!FP) {
      FP = 'fp_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);
      localStorage.setItem('decomp_fp', FP);
    }

    // ============================================================
    // 本地历史 localStorage
    // ============================================================
    var MY_TASKS = [];
    try {
      var s = localStorage.getItem('decomp_mytasks');
      if (s) MY_TASKS = JSON.parse(s);
    } catch(e) {}

    function saveLocal() {
      localStorage.setItem('decomp_mytasks', JSON.stringify(MY_TASKS));
    }

    var STATUS_LABELS = {
      pending: '等待添加',
      adding: '添加中',
      downloading: '下载中',
      ready: '待解压',
      decompressing: '解压中',
      done: '已完成',
      failed: '失败',
      'bad-format': '不可解压'
    };

    // ============================================================
    // ETA 倒计时
    // ============================================================
    var etaTimer = null;
    var etaSec = 0;

    function updateEta(pendingCount, addingCount, readyCount) {
      etaSec = 20 * addingCount + 100 * pendingCount + 25 * readyCount;
      if (etaTimer) { clearInterval(etaTimer); etaTimer = null; }
      if (etaSec <= 0) { document.getElementById('etaDisplay').textContent = '--:--'; return; }
      showEta();
      etaTimer = setInterval(function() {
        etaSec = Math.max(0, etaSec - 1);
        showEta();
        if (etaSec <= 0 && etaTimer) { clearInterval(etaTimer); etaTimer = null; }
      }, 1000);
    }

    function showEta() {
      var m = Math.floor(etaSec / 60);
      var s = etaSec % 60;
      document.getElementById('etaDisplay').textContent =
        (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    }

    // ============================================================
    // 提交
    // ============================================================
    function submitTask() {
      var url = document.getElementById('urlInput').value.trim();
      if (!url) return;
      var btn = document.getElementById('submitBtn');
      var res = document.getElementById('submitResult');
      btn.disabled = true;
      res.style.display = 'none';
      res.className = 'submit-result';
      fetch('/submit', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url: url, fp: FP})
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.success) {
          res.className = 'submit-result success';
          res.textContent = '\u2705 \u5df2\u63d0\u4ea4\uff0c\u6392\u961f\u5e8f\u53f7: #' + data.queue_order;
          document.getElementById('urlInput').value = '';
          MY_TASKS.unshift({
            order: data.queue_order,
            url: url,
            status: 'pending',
            share_url: '',
            created_at: new Date().toISOString()
          });
          saveLocal();
        } else {
          res.className = 'submit-result error';
          res.textContent = '\u274c ' + (data.error || '\u63d0\u4ea4\u5931\u8d25');
        }
      })
      .catch(function(e) {
        res.className = 'submit-result error';
        res.textContent = '\u274c \u7f51\u7edc\u9519\u8bef: ' + e.message;
      })
      .then(function() {
        res.style.display = 'block';
        btn.disabled = false;
        refreshQueue();
      });
    }

    // ============================================================
    // 刷新
    // ============================================================
    function refreshQueue() {
      fetch('/queue?fp=' + encodeURIComponent(FP))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        // 全局统计数字
        document.getElementById('globalPending').textContent = data.globalSummary.pending;
        document.getElementById('globalAdding').textContent = data.globalSummary.adding;
        document.getElementById('globalDownloading').textContent = data.globalSummary.downloading;
        document.getElementById('globalReady').textContent = data.globalSummary.ready;
        var failedCount = (data.globalSummary.failed || 0) + (data.globalSummary['bad-format'] || 0);
        document.getElementById('globalFailed').textContent = failedCount;

        updateEta(data.globalSummary.pending, data.globalSummary.adding, data.globalSummary.ready);

        // 合并服务端任务
        var serverTasks = data.myTasks || [];
        var serverMap = {};
        serverTasks.forEach(function(t) { serverMap[t.queue_order] = t; });

        // 本地记录用服务端数据覆盖
        MY_TASKS = MY_TASKS.map(function(lt) {
          var st = serverMap[lt.order];
          if (st) {
            return {
              order: st.queue_order,
              url: st.url,
              status: st.status,
              share_url: st.share_url || '',
              created_at: st.created_at || lt.created_at
            };
          }
          return lt;
        });

        // 补新任务
        serverTasks.forEach(function(st) {
          if (!MY_TASKS.some(function(lt) { return lt.order === st.queue_order; })) {
            MY_TASKS.unshift({
              order: st.queue_order,
              url: st.url,
              status: st.status,
              share_url: st.share_url || '',
              created_at: st.created_at
            });
          }
        });

        saveLocal();
        renderTasks();
      })
      .catch(function() {});
    }

    function renderTasks() {
      var list = document.getElementById('taskList');
      var empty = document.getElementById('emptyState');
      if (MY_TASKS.length === 0) {
        list.innerHTML = '';
        empty.style.display = 'block';
        return;
      }
      empty.style.display = 'none';

      // 先按 order 去重（防 localStorage 或 race 导致的重复）
      var seen = {};
      var deduped = [];
      MY_TASKS.forEach(function(t) {
        if (!seen[t.order]) {
          seen[t.order] = true;
          deduped.push(t);
        }
      });
      // 同步回 MY_TASKS 保证后续操作一致性
      MY_TASKS = deduped;

      var sorted = MY_TASKS.slice().sort(function(a, b) {
        // 按 created_at 降序（新任务在上）
        var ta = a.created_at || '';
        var tb = b.created_at || '';
        if (ta < tb) return 1;
        if (ta > tb) return -1;
        return (b.order || 0) - (a.order || 0);
      });
      var html = '';
      sorted.forEach(function(t) {
        var label = STATUS_LABELS[t.status] || t.status;
        var action = '-';
        if (t.status === 'done' && t.share_url) {
          action = '<a class="btn-glass btn-action" href="' + t.share_url + '" target="_blank">\u7acb\u5373\u67e5\u770b</a>';
        } else if (t.status === 'failed' || t.status === 'bad-format') {
          action = '<a class="btn-glass btn-action" onclick="showRecoverTip(' + t.order + ')" style="cursor:pointer;color:#ffaa66;">\u4eba\u5de5\u8865\u6551</a>';
        } else {
          action = '<a class="btn-glass btn-action" onclick="editNote(' + t.order + ')" style="cursor:pointer;">\u6dfb\u52a0\u5907\u6ce8</a>';
        }
        if (t.status === 'done' && t.share_url) {
          action += '<a class="btn-glass btn-action" onclick="editNote(' + t.order + ')" style="cursor:pointer;margin-left:6px;">\u6dfb\u52a0\u5907\u6ce8</a>';
        }
        var surl = t.url;
        if (surl && surl.length > 40) surl = surl.slice(0, 37) + '...';
        var timeStr = '';
        if (t.created_at) {
          try {
            var d = new Date(t.created_at.replace(' ', 'T') + '+08:00');
            if (!isNaN(d.getTime())) {
              var mo = ('0' + (d.getMonth() + 1)).slice(-2);
              var dd = ('0' + d.getDate()).slice(-2);
              var hh = ('0' + d.getHours()).slice(-2);
              var mm = ('0' + d.getMinutes()).slice(-2);
              timeStr = mo + '-' + dd + ' ' + hh + ':' + mm;
            }
          } catch(e) {}
        }
        html += '<div class="task-item">' +
          '<div class="task-order">#' + t.order + '</div>' +
          '<div class="task-status"><span class="badge ' + t.status + '">' + label + '</span></div>' +
          '<div class="task-time">' + timeStr + '</div>' +
          '<div class="task-url" title="' + (t.url || '') + '">' + (surl || '-') + '</div>' +
          '<div class="task-action">' + action + '</div>' +
          '</div>';
      });
      list.innerHTML = html;
    }

    // ============================================================
    // GMT+8 时钟
    // ============================================================
    function tickClock() {
      var now = new Date();
      var cst = new Date(now.getTime() + now.getTimezoneOffset() * 60000 + 8 * 3600000);
      var y = cst.getFullYear();
      var mo = ('0' + (cst.getMonth() + 1)).slice(-2);
      var d = ('0' + cst.getDate()).slice(-2);
      var h = ('0' + cst.getHours()).slice(-2);
      var mi = ('0' + cst.getMinutes()).slice(-2);
      var s = ('0' + cst.getSeconds()).slice(-2);
      document.getElementById('footerClock').textContent =
        'GMT+8  ' + y + '-' + mo + '-' + d + '  ' + h + ':' + mi + ':' + s;
    }

    // ============================================================
    // 人工补救弹窗
    // ============================================================
    function showRecoverTip(order) {
      var overlay = document.createElement('div');
      overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.55);z-index:9999;display:flex;align-items:center;justify-content:center;';
      var box = document.createElement('div');
      box.style.cssText = 'background:#1a1a2e;border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:32px 40px;max-width:480px;width:90%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,0.5);';
      box.innerHTML =
        '<div style="font-size:40px;margin-bottom:12px;">\u26a0\ufe0f</div>' +
        '<h3 style="margin:0 0 8px 0;color:#fff;font-size:18px;font-weight:600;">\u4eba\u5de5\u8865\u6551</h3>' +
        '<p style="margin:0 0 4px 0;color:rgba(255,255,255,0.6);font-size:14px;line-height:1.6;">' +
          '\u7cfb\u7edf\u5361\u987f\uff0c\u8be5\u4efb\u52a1\u4e0d\u518d\u81ea\u52a8\u5904\u7406\u3002\u82e5\u6b64\u6b21\u4efb\u52a1\u4e0d\u662f\u5f88\u6025\u8bf7\u8054\u7cfb\u7ba1\u7406\u5458\u4eba\u5de5\u8865\u6551\uff0c\u4e0d\u8981\u8fc7\u591a\u5c1d\u8bd5\u5360\u7528\u6dfb\u52a0\u6b21\u6570\u3002' +
        '</p>' +
        '<div style="margin:16px 0;padding:12px;background:rgba(255,170,102,0.1);border-radius:8px;font-size:13px;color:#ffaa66;">' +
          '\u8bf7\u8054\u7cfb\u7ba1\u7406\u5458\u5904\u7406\u540e\u5377#<span style="font-weight:700;font-size:16px;">' + order + '</span>' +
        '</div>' +
        '<button onclick="this.closest(\'div[style]\').parentElement.remove()" style="padding:8px 28px;border:none;border-radius:8px;background:rgba(255,255,255,0.08);color:rgba(255,255,255,0.7);cursor:pointer;font-size:14px;">\u6211\u77e5\u9053\u4e86</button>';
      overlay.appendChild(box);
      document.body.appendChild(overlay);
    }

    // ============================================================
    // 启动
    // ============================================================
    setInterval(tickClock, 1000);
    tickClock();

    setInterval(refreshQueue, 3000);
    refreshQueue();

    // ============================================================
    // 首次访问弹窗
    // ============================================================
    (function() {
      var shown = localStorage.getItem('decomp_welcomed');
      if (!shown) {
        document.getElementById('welcomeOverlay').classList.remove('hidden');
      } else {
        document.getElementById('helpCorner').style.display = 'flex';
      }
    })();

    function dismissWelcome() {
      localStorage.setItem('decomp_welcomed', '1');
      document.getElementById('welcomeOverlay').classList.add('hidden');
      document.getElementById('helpCorner').style.display = 'flex';
    }

    // ============================================================
    // 备注
    // ============================================================
    var _noteEditingOrder = null;

    function loadNotes() {
      try {
        var s = localStorage.getItem('decomp_notes');
        return s ? JSON.parse(s) : {};
      } catch(e) { return {}; }
    }

    function saveNotes(notes) {
      localStorage.setItem('decomp_notes', JSON.stringify(notes));
    }

    function editNote(order) {
      _noteEditingOrder = order;
      var notes = loadNotes();
      document.getElementById('noteInput').value = notes[order] || '';
      document.getElementById('noteOverlay').classList.add('show');
      setTimeout(function() { document.getElementById('noteInput').focus(); }, 100);
    }

    function saveNoteAndClose() {
      if (_noteEditingOrder !== null) {
        var notes = loadNotes();
        var val = document.getElementById('noteInput').value.trim();
        if (val) notes[_noteEditingOrder] = val;
        else delete notes[_noteEditingOrder];
        saveNotes(notes);
        _noteEditingOrder = null;
      }
      document.getElementById('noteOverlay').classList.remove('show');
      document.getElementById('noteInput').value = '';
    }

    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') saveNoteAndClose();
    });
  </script>
</body>
</html>
"""


# ─── 路由 ────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/submit", methods=["POST"])
def submit():
    """用户提交直链 URL"""
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    fp = (data.get("fp") or "").strip()
    if not url:
        return jsonify({"success": False, "error": "URL 不能为空"}), 400
    if not url.startswith("http"):
        return jsonify({"success": False, "error": "仅支持 HTTP/HTTPS 直链"}), 400
    if not fp:
        return jsonify({"success": False, "error": "指纹不可为空"}), 400

    folder_name = time.strftime("%Y-%m-%d %H：%M：%S")
    try:
        queue_order = add_task(folder_name, url, fp=fp)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({
        "success": True,
        "queue_order": queue_order,
        "folder_name": folder_name
    })


@app.route("/queue")
def queue():
    """排队概览（前端轮询用），按 fp 隔离"""
    fp = request.args.get("fp", "").strip()
    global_summary = get_queue_summary()

    my_tasks = get_all(fp=fp) if fp else []
    return jsonify({
        "globalSummary": global_summary,
        "myTasks": my_tasks
    })


@app.route("/reset", methods=["POST"])
def reset():
    """清空队列（调试用）"""
    clear_all()
    return jsonify({"success": True, "message": "队列已清空"})


def run_server(host="0.0.0.0", port=5000, debug=False):
    """启动 Web 服务"""
    logger.info(f"Web 服务启动: http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_server(debug=False)
