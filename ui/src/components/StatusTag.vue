<template>
  <span class="tag" :class="variant">{{ label }}</span>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ value: string }>();

const variant = computed(() => {
  if (props.value === "completed") return "ok";
  if (props.value === "processing" || props.value === "pending") return "warn";
  if (props.value === "failed" || props.value === "cancelled") return "bad";
  return "";
});

const label = computed(() => props.value);
</script>
