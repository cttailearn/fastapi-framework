<template>
  <div class="shell">
    <aside class="panel side">
      <div class="brand">
        <div class="brandTop">
          <div class="mark"></div>
          <div>
            <div class="brandTitle">任务服务后台</div>
            <div class="brandSub">Vue Admin Console</div>
          </div>
        </div>
      </div>
      <nav class="nav">
        <RouterLink to="/dashboard" :class="{ active: isActive('/dashboard') }">
          <span>概览</span>
        </RouterLink>
        <RouterLink to="/api-keys" :class="{ active: isActive('/api-keys') }">
          <span>API-Key</span>
        </RouterLink>
        <RouterLink to="/tasks" :class="{ active: isActive('/tasks') }">
          <span>任务</span>
        </RouterLink>
        <RouterLink to="/requests" :class="{ active: isActive('/requests') }">
          <span>请求</span>
        </RouterLink>
      </nav>
      <div class="sideFooter">
        <span class="pill"><span>登录：</span><strong>{{ username || "-" }}</strong></span>
        <div class="row">
          <a class="ghostLink" href="/docs" target="_blank" rel="noreferrer">Docs</a>
          <button class="ghostLink" type="button" @click="onLogout">注销登录</button>
        </div>
      </div>
    </aside>
    <main class="panel main">
      <slot />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

import { logout } from "@/api";

const props = defineProps<{ username?: string | null }>();

const route = useRoute();
const router = useRouter();

const username = computed(() => props.username ?? null);

function isActive(path: string): boolean {
  return route.path === path;
}

async function onLogout(): Promise<void> {
  await logout();
  await router.push("/login");
}
</script>
