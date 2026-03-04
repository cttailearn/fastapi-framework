<template>
  <LayoutShell :username="me?.username ?? null">
    <div class="topbar">
      <div>
        <h1 class="h1">任务</h1>
        <div class="hint">最近 {{ limit }} 条任务</div>
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
        <div class="field" style="min-width: 180px;">
          <div class="label">状态筛选</div>
          <select class="input" v-model="statusFilter">
            <option value="all">全部</option>
            <option value="pending">pending</option>
            <option value="processing">processing</option>
            <option value="completed">completed</option>
            <option value="failed">failed</option>
            <option value="cancelled">cancelled</option>
          </select>
        </div>
        <div class="field" style="flex: 1; min-width: 220px;">
          <div class="label">关键词</div>
          <input class="input" v-model.trim="keywordFilter" placeholder="任务ID或类型" />
        </div>
      </div>
    </div>

    <div class="tableWrap">
      <table>
        <thead>
          <tr>
            <th>任务ID</th>
            <th>类型</th>
            <th>状态</th>
            <th>进度</th>
            <th>创建</th>
            <th>更新</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in filteredTasks" :key="t.task_id">
            <td class="mono">{{ t.task_id }}</td>
            <td>{{ t.type }}</td>
            <td><StatusTag :value="t.status" /></td>
            <td class="mono">{{ t.progress ?? "-" }}</td>
            <td class="mono">{{ fmt(t.created_at) }}</td>
            <td class="mono">{{ fmt(t.updated_at) }}</td>
            <td style="white-space: nowrap;">
              <button class="btn mini" type="button" :disabled="loading" @click="onDetail(t.task_id)">
                详情
              </button>
              <button class="btn mini" type="button" :disabled="loading" @click="onCancel(t.task_id)">
                取消
              </button>
              <button class="btn mini danger" type="button" :disabled="loading" @click="onDelete(t.task_id)">
                删除
              </button>
            </td>
          </tr>
          <tr v-if="filteredTasks.length === 0">
            <td colspan="7" class="muted">暂无任务</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-if="detailOpen && taskDetail"
      style="position: fixed; inset: 0; background: rgba(0,0,0,.24); display: flex; align-items: center; justify-content: center; padding: 16px; z-index: 50;"
      @click.self="closeDetail"
    >
      <div class="card" style="width: min(960px, 100%); max-height: 82vh; overflow: auto;">
        <div class="row" style="justify-content: space-between; align-items: center;">
          <div class="mono">{{ taskDetail.task_id }}</div>
          <button class="btn mini" type="button" @click="closeDetail">关闭</button>
        </div>
        <div class="row" style="margin-top: 10px;">
          <span class="tag">{{ taskDetail.type }}</span>
          <StatusTag :value="taskDetail.status" />
          <span class="tag">progress {{ taskDetail.progress ?? "-" }}</span>
        </div>
        <div class="row" style="margin-top: 12px;">
          <div class="field" style="flex: 1; min-width: 280px;">
            <div class="label">data</div>
            <pre class="mono" style="margin: 0; white-space: pre-wrap;">{{ pretty(taskDetail.data) }}</pre>
          </div>
          <div class="field" style="flex: 1; min-width: 280px;">
            <div class="label">config</div>
            <pre class="mono" style="margin: 0; white-space: pre-wrap;">{{ pretty(taskDetail.config) }}</pre>
          </div>
        </div>
        <div class="row" style="margin-top: 12px;">
          <div class="field" style="flex: 1; min-width: 280px;">
            <div class="label">result</div>
            <pre class="mono" style="margin: 0; white-space: pre-wrap;">{{ pretty(taskDetail.result) }}</pre>
          </div>
          <div class="field" style="flex: 1; min-width: 280px;">
            <div class="label">error</div>
            <pre class="mono" style="margin: 0; white-space: pre-wrap;">{{ pretty(taskDetail.error) }}</pre>
          </div>
        </div>
      </div>
    </div>
  </LayoutShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { AdminTask, AdminTaskDetail, ApiError, cancelTask, deleteTask, getMe, getTaskDetail, listTasks, UserPublic } from "@/api";
import LayoutShell from "@/components/LayoutShell.vue";
import StatusTag from "@/components/StatusTag.vue";

const me = ref<UserPublic | null>(null);
const tasks = ref<AdminTask[]>([]);
const limit = ref(200);
const loading = ref(false);
const error = ref<string | null>(null);
const statusFilter = ref("all");
const keywordFilter = ref("");
const detailOpen = ref(false);
const taskDetail = ref<AdminTaskDetail | null>(null);

const filteredTasks = computed(() => {
  const kw = keywordFilter.value.trim().toLowerCase();
  return tasks.value.filter((t) => {
    if (statusFilter.value !== "all" && t.status !== statusFilter.value) return false;
    if (!kw) return true;
    const target = `${t.task_id} ${t.type}`.toLowerCase();
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
    tasks.value = await listTasks(limit.value);
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "未知错误";
  } finally {
    loading.value = false;
  }
}

async function onCancel(taskId: string): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    await cancelTask(taskId);
    await load();
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "未知错误";
  } finally {
    loading.value = false;
  }
}

async function onDelete(taskId: string): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    await deleteTask(taskId);
    await load();
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "未知错误";
  } finally {
    loading.value = false;
  }
}

async function onDetail(taskId: string): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    taskDetail.value = await getTaskDetail(taskId);
    detailOpen.value = true;
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "未知错误";
  } finally {
    loading.value = false;
  }
}

function closeDetail(): void {
  detailOpen.value = false;
}

function pretty(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

onMounted(load);
</script>
