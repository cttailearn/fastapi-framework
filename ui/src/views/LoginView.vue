<template>
  <div class="shell" style="grid-template-columns: 1fr; max-width: 980px; margin: 0 auto;">
    <main class="panel main" style="padding: 26px;">
      <div class="topbar">
        <div>
          <h1 class="h1">管理员登录</h1>
          <div class="hint">使用已有账号登录。仅管理员可访问 /v1/admin 接口。</div>
        </div>
        <div class="actions">
          <a class="ghostLink" href="/docs" target="_blank" rel="noreferrer">OpenAPI</a>
        </div>
      </div>

      <div class="card">
        <div class="row" style="gap: 14px;">
          <div class="field" style="flex: 1; min-width: 240px;">
            <div class="label">用户名</div>
            <input class="input" v-model.trim="username" autocomplete="username" />
          </div>
          <div class="field" style="flex: 1; min-width: 240px;">
            <div class="label">密码</div>
            <input class="input" v-model="password" type="password" autocomplete="current-password" />
          </div>
          <div class="field" style="min-width: 160px;">
            <div class="label">动作</div>
            <button class="btn primary" type="button" :disabled="loading" @click="onLogin">
              {{ loading ? "登录中…" : "登录" }}
            </button>
          </div>
        </div>

        <div v-if="error" class="toast" style="margin-top: 14px;">
          <strong>登录失败</strong>
          <div style="margin-top: 6px;">{{ error }}</div>
        </div>
      </div>

      <div class="card" style="margin-top: 14px;">
        <div class="row" style="align-items: flex-start;">
          <div style="flex: 1; min-width: 220px;">
            <div class="k">提示</div>
            <div style="margin-top: 8px; color: var(--muted); line-height: 1.7;">
              <div>首次注册的用户会自动成为管理员。</div>
              <div style="margin-top: 8px;">
                你可以先用 API 完成注册：
                <span class="mono">POST /v1/auth/register</span>，然后登录。
              </div>
            </div>
          </div>
          <div class="toast" style="flex: 1; min-width: 260px;">
            <div class="k">环境变量</div>
            <div style="margin-top: 10px; color: var(--muted); line-height: 1.7;">
              <div><span class="mono">APP_SECRET_KEY</span>：JWT/Key Pepper</div>
              <div><span class="mono">APP_DB_PATH</span>：SQLite 路径</div>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, getMe, login, logout } from "@/api";

const router = useRouter();

const username = ref("");
const password = ref("");
const loading = ref(false);
const error = ref<string | null>(null);

async function onLogin(): Promise<void> {
  error.value = null;
  loading.value = true;
  try {
    await login(username.value, password.value);
    const me = await getMe();
    if (!me.is_admin) {
      await logout();
      error.value = "当前账号不是管理员。";
      return;
    }
    await router.push("/dashboard");
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message;
    else error.value = "未知错误";
  } finally {
    loading.value = false;
  }
}
</script>
