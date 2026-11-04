import type { components } from "./schema";

export type Scene = components["schemas"]["Scene"];
export type Item = components["schemas"]["Item"];
export type Placement = components["schemas"]["Placement"];
export type Plan = components["schemas"]["Plan"];
export type StructureRequest = components["schemas"]["StructureRequest"];
export type InventoryEvent = {
  request_id: string;
  operation: { route: string; action?: string; item_id?: string };
  created_at: string;
};

export async function request<T>(
  path: string,
  body?: unknown,
  method = "POST",
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(
      typeof error?.detail === "string"
        ? error.detail
        : `请求失败（${response.status}）`,
    );
  }
  return response.json() as Promise<T>;
}

export const api = {
  scene: () => request<Scene>("/scene"),
  events: () => request<InventoryEvent[]>("/inventory/events"),
  plan: (version: number) =>
    request<Plan>("/plans", { expected_version: version }),
  inventory: (item: Item, version: number) =>
    request<Scene>("/inventory/events", {
      request_id: crypto.randomUUID(),
      expected_version: version,
      item_id: item.id,
      action: item.status === "stored" ? "take" : "return",
    }),
  lock: (item: Item, version: number) =>
    request<Scene>(
      `/items/${item.id}/movable`,
      {
        request_id: crypto.randomUUID(),
        expected_version: version,
        movable: !item.movable,
      },
      "PATCH",
    ),
  structure: (body: StructureRequest) =>
    request<Scene>("/scene/structure", body),
  apply: (plan: Plan, version: number) =>
    request<Scene>(`/plans/${plan.id}/apply`, {
      request_id: crypto.randomUUID(),
      expected_version: version,
      execution_confirmed: true,
    }),
};
