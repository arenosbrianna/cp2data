// The forecast model a request asks for (query parameter `model`). Empty = the champion (the is_selected run).
import { AsyncLocalStorage } from 'node:async_hooks';

export const modelScope = new AsyncLocalStorage();
export const currentModel = () => modelScope.getStore()?.model ?? null;
