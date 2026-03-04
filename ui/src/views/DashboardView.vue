<template>
  <LayoutShell :username="me?.username ?? null">
    <div class="topbar">
      <div>
        <h1 class="h1">概览</h1>
        <div class="hint">系统指标来自 /v1/admin/overview（需管理员权限）。</div>
      </div>
      <div class="actions">
        <button class="btn" type="button" :disabled="loading" @click="load">刷新</button>
        <a class="ghostLink" href="/docs" target="_blank" rel="noreferrer">OpenAPI</a>
      </div>
    </div>

    <div v-if="error" class="toast" style="margin-bottom: 12px;">
      <strong>加载失败</strong>
      <div style="margin-top: 6px;">{{ error }}</div>
    </div>

    <div class="grid">
      <div class="stat">
        <div class="k">用户</div>
        <div class="v">{{ counts?.users ?? "—" }}</div>
      </div>
      <div class="stat">
        <div class="k">API Keys</div>
        <div class="v">{{ counts?.api_keys ?? "—" }}</div>
      </div>
      <div class="stat">
        <div class="k">任务</div>
        <div class="v">{{ counts?.tasks ?? "—" }}</div>
      </div>
      <div class="stat">
        <div class="k">请求日志</div>
        <div class="v">{{ counts?.requests ?? "—" }}</div>
      </div>
    </div>

    <div style="margin-top: 14px;" class="card">
      <div class="row">
        <div style="flex: 1; min-width: 260px;">
          <div style="font-family: var(--display); font-size: 18px;">快速入口</div>
          <div class="hint">高频操作：查看任务、生成 API-Key、追踪请求日志。</div>
        </div>
        <div class="row">
          <RouterLink class="btn" to="/tasks">任务</RouterLink>
          <RouterLink class="btn" to="/api-keys">API-Key</RouterLink>
          <RouterLink class="btn" to="/requests">请求</RouterLink>
        </div>
      </div>
    </div>
  </LayoutShell>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, getMe, getOverview, OverviewCounts, UserPublic } from "@/api";
import LayoutShell from "@/components/LayoutShell.vue";

const me = ref<UserPublic | null>(null);
const counts = ref<OverviewCounts | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    me.value = await getMe();
    counts.value = await getOverview();
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "未知错误";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>
