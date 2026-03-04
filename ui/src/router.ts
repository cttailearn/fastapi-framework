import { createRouter, createWebHashHistory, RouteRecordRaw } from "vue-router";

import ApiKeysView from "./views/ApiKeysView.vue";
import DashboardView from "./views/DashboardView.vue";
import LoginView from "./views/LoginView.vue";
import RequestsView from "./views/RequestsView.vue";
import TasksView from "./views/TasksView.vue";

const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/dashboard" },
  { path: "/login", component: LoginView },
  { path: "/dashboard", component: DashboardView },
  { path: "/api-keys", component: ApiKeysView },
  { path: "/tasks", component: TasksView },
  { path: "/requests", component: RequestsView }
];

export const router = createRouter({
  history: createWebHashHistory("/admin/"),
  routes
});

router.beforeEach((to) => {
  const token = localStorage.getItem("admin_token");
  if (to.path !== "/login" && !token) return "/login";
  if (to.path === "/login" && token) return "/dashboard";
  return true;
});
