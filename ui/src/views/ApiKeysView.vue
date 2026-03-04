<template>
  <LayoutShell :username="me?.username ?? null">
    <div class="topbar">
      <div>
        <h1 class="h1">API-Key</h1>
      </div>
      <div class="actions">
        <button class="btn" type="button" :disabled="loading" @click="load">刷新</button>
      </div>
    </div>

    <div v-if="created" class="toast" style="margin-bottom: 12px;">
      <div class="row" style="justify-content: space-between; align-items: center;">
        <strong>新 API-Key</strong>
        <div class="row">
          <button class="btn mini" type="button" @click="onCopy(created.api_key)">
            {{ copiedText === created.api_key ? "已复制" : "复制" }}
          </button>
        </div>
      </div>
      <div style="margin-top: 10px;" class="mono">{{ created.api_key }}</div>
      <div style="margin-top: 10px; color: var(--muted);">
        名称：{{ created.name }} · 前缀：{{ created.prefix }}
      </div>
    </div>

    <div v-if="error" class="toast" style="margin-bottom: 12px;">
      <strong>操作失败</strong>
      <div style="margin-top: 6px;">{{ error }}</div>
    </div>

    <div class="card">
      <form class="row" style="align-items: flex-end;" @submit.prevent="onCreate">
        <div class="field" style="flex: 1; min-width: 240px;">
          <div class="label">Key 名称</div>
          <input class="input" v-model.trim="newName" placeholder="例如：prod-backend" />
        </div>
        <button class="btn primary" type="submit" :disabled="loading || !newName.trim()">
          创建
        </button>
        <button class="btn" type="button" :disabled="loading" @click="toggleAll">
          {{ showAll ? "仅看我的" : "查看全部（管理员）" }}
        </button>
      </form>
    </div>

    <div style="margin-top: 12px;" class="tableWrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th v-if="showAll">用户</th>
            <th>名称</th>
            <th>Key</th>
            <th>前缀</th>
            <th>创建</th>
            <th>最后使用</th>
            <th>状态</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="k in keys" :key="k.id">
            <td class="mono">{{ k.id }}</td>
            <td v-if="showAll" class="mono">{{ (k as any).username ?? "-" }}</td>
            <td>{{ k.name }}</td>
            <td class="mono">
              <div class="row" style="gap: 8px;">
                <span>{{ maskKey(getApiKey(k)) }}</span>
                <button class="btn mini" type="button" :disabled="!getApiKey(k)" @click="onCopy(getApiKey(k) || '')">
                  {{ copiedText === getApiKey(k) ? "已复制" : "复制" }}
                </button>
              </div>
            </td>
            <td class="mono">
              <span>{{ k.prefix }}</span>
            </td>
            <td class="mono">{{ fmt(k.created_at) }}</td>
            <td class="mono">{{ k.last_used_at ? fmt(k.last_used_at) : "-" }}</td>
            <td>
              <span class="tag" :class="k.revoked_at ? 'bad' : 'ok'">{{ k.revoked_at ? "关闭" : "启动" }}</span>
            </td>
            <td style="white-space: nowrap;">
              <button
                class="btn mini"
                :class="k.revoked_at ? '' : 'danger'"
                type="button"
                :disabled="loading"
                @click="onToggle(k.id, !!k.revoked_at)"
              >
                {{ k.revoked_at ? "启动" : "关闭" }}
              </button>
              <button class="btn mini" type="button" :disabled="loading" @click="onDelete(k.id)">
                删除
              </button>
            </td>
          </tr>
          <tr v-if="keys.length === 0">
            <td :colspan="showAll ? 9 : 8" class="muted">暂无数据</td>
          </tr>
        </tbody>
      </table>
    </div>
  </LayoutShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import {
  activateApiKey,
  AdminApiKey,
  ApiError,
  ApiKeyCreated,
  ApiKeyPublic,
  createApiKey,
  deleteApiKey,
  getMe,
  listAllApiKeys,
  listMyApiKeys,
  revokeApiKey,
  UserPublic
} from "@/api";
import LayoutShell from "@/components/LayoutShell.vue";

const me = ref<UserPublic | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const created = ref<ApiKeyCreated | null>(null);
const showAll = ref(false);
const newName = ref("");
const copiedText = ref<string | null>(null);

const keys = ref<Array<ApiKeyPublic | AdminApiKey>>([]);
const canShowAll = computed(() => (me.value?.is_admin ?? false) === true);

function getApiKey(item: ApiKeyPublic | AdminApiKey): string | null {
  const v = (item as any).api_key;
  return typeof v === "string" && v ? v : null;
}

function maskKey(value: string | null): string {
  if (!value) return "-";
  if (value.length <= 12) return value;
  return `${value.slice(0, 8)}…${value.slice(-4)}`;
}

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
    if (showAll.value && canShowAll.value) keys.value = await listAllApiKeys();
    else keys.value = await listMyApiKeys();
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "未知错误";
  } finally {
    loading.value = false;
  }
}

async function onCreate(): Promise<void> {
  const name = newName.value.trim();
  if (!name) {
    error.value = "请输入 Key 名称";
    return;
  }
  loading.value = true;
  error.value = null;
  created.value = null;
  try {
    created.value = await createApiKey(name);
    newName.value = "";
    try {
      await onCopy(created.value.api_key);
    } catch {
      // ignore copy failure
    }
    await load();
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "未知错误";
  } finally {
    loading.value = false;
  }
}

async function onRevoke(id: number): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    await revokeApiKey(id);
    await load();
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "未知错误";
  } finally {
    loading.value = false;
  }
}

async function onActivate(id: number): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    await activateApiKey(id);
    await load();
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "未知错误";
  } finally {
    loading.value = false;
  }
}

async function onToggle(id: number, isRevoked: boolean): Promise<void> {
  if (isRevoked) await onActivate(id);
  else await onRevoke(id);
}

async function onDelete(id: number): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    await deleteApiKey(id);
    await load();
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "未知错误";
  } finally {
    loading.value = false;
  }
}

function toggleAll(): void {
  if (!canShowAll.value) return;
  showAll.value = !showAll.value;
  void load();
}

async function copyToClipboard(text: string): Promise<void> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const el = document.createElement("textarea");
  el.value = text;
  el.setAttribute("readonly", "true");
  el.style.position = "fixed";
  el.style.left = "-9999px";
  el.style.top = "0";
  document.body.appendChild(el);
  el.select();
  document.execCommand("copy");
  document.body.removeChild(el);
}

async function onCopy(text: string): Promise<void> {
  error.value = null;
  try {
    await copyToClipboard(text);
    copiedText.value = text;
    window.setTimeout(() => {
      if (copiedText.value === text) copiedText.value = null;
    }, 1200);
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "复制失败";
  }
}

onMounted(load);
</script>
