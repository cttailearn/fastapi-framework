<template>
  <LayoutShell :username="me?.username ?? null">
    <div class="topbar">
      <div>
        <h1 class="h1">请求日志</h1>
        <div class="hint">最近 {{ limit }} 条请求</div>
      </div>
      <div class="actions">
        <button class="btn" type="button" :disabled="loading" @click="load">刷新</button>
      </div>
    </div>

    <div v-if="error" class="toast" style="margin-bottom: 12px;">
      <strong>加载失败</strong>
      <div style="margin-top: 6px;">{{ error }}</div>
    </div>

    <div class="card" style="margin-bottom: 12px;">
      <div class="row" style="align-items: flex-end;">
        <div class="field" style="min-width: 180px;">
          <div class="label">数量</div>
          <input class="input" v-model.number="limit" type="number" min="1" max="500" />
        </div>
        <div class="field" style="min-width: 160px;">
          <div class="label">方法</div>
          <select class="input" v-model="methodFilter">
            <option value="all">全部</option>
            <option value="GET">GET</option>
            <option value="POST">POST</option>
            <option value="PUT">PUT</option>
            <option value="PATCH">PATCH</option>
            <option value="DELETE">DELETE</option>
          </select>
        </div>
        <div class="field" style="min-width: 160px;">
          <div class="label">状态码</div>
          <select class="input" v-model="statusGroupFilter">
            <option value="all">全部</option>
            <option value="2xx">2xx</option>
            <option value="4xx">4xx</option>
            <option value="5xx">5xx</option>
          </select>
        </div>
        <div class="field" style="flex: 1; min-width: 220px;">
          <div class="label">关键词</div>
          <input class="input" v-model.trim="keywordFilter" placeholder="路径 / 用户 / Key 前缀" />
        </div>
        <div class="spacer"></div>
        <div class="pill"><span>筛选结果：</span><strong>{{ filteredLogs.length }}</strong></div>
      </div>
    </div>

    <div class="tableWrap">
      <table>
        <thead>
          <tr>
            <th>时间</th>
            <th>方法</th>
            <th>路径</th>
            <th>状态</th>
            <th>耗时</th>
            <th>IP</th>
            <th>用户</th>
            <th>API-Key</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in filteredLogs" :key="r.id">
            <td class="mono">{{ fmt(r.ts) }}</td>
            <td><span class="tag">{{ r.method }}</span></td>
            <td class="mono">{{ r.path }}</td>
            <td>
              <span class="tag" :class="r.status_code >= 400 ? 'bad' : 'ok'">{{ r.status_code }}</span>
            </td>
            <td class="mono">{{ r.latency_ms }}ms</td>
            <td class="mono">{{ r.ip ?? "-" }}</td>
            <td class="mono">{{ r.username ?? "-" }}</td>
            <td class="mono">{{ r.api_key_prefix ?? "-" }}</td>
          </tr>
          <tr v-if="filteredLogs.length === 0">
            <td colspan="8" class="muted">暂无日志</td>
          </tr>
        </tbody>
      </table>
    </div>
  </LayoutShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { AdminRequestLog, ApiError, getMe, listRequests, UserPublic } from "@/api";
import LayoutShell from "@/components/LayoutShell.vue";

const me = ref<UserPublic | null>(null);
const logs = ref<AdminRequestLog[]>([]);
const limit = ref(200);
const loading = ref(false);
const error = ref<string | null>(null);
const methodFilter = ref("all");
const statusGroupFilter = ref("all");
const keywordFilter = ref("");

const filteredLogs = computed(() => {
  const kw = keywordFilter.value.trim().toLowerCase();
  return logs.value.filter((r) => {
    if (methodFilter.value !== "all" && r.method.toUpperCase() !== methodFilter.value) return false;
    if (statusGroupFilter.value === "2xx" && (r.status_code < 200 || r.status_code >= 300)) return false;
    if (statusGroupFilter.value === "4xx" && (r.status_code < 400 || r.status_code >= 500)) return false;
    if (statusGroupFilter.value === "5xx" && (r.status_code < 500 || r.status_code >= 600)) return false;
    if (!kw) return true;
    const target = `${r.path} ${r.username ?? ""} ${r.api_key_prefix ?? ""}`.toLowerCase();
    return target.includes(kw);
  });
});

function fmt(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    me.value = await getMe();
    logs.value = await listRequests(limit.value);
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "未知错误";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>
