import { apiRequest } from "@/lib/api";

export type UserKey = {
  key_type: string;
  is_set: boolean;
  created_at: string;
  updated_at: string;
};

export async function listUserKeys(token: string): Promise<UserKey[]> {
  return apiRequest<UserKey[]>("/v1/user-keys", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function saveUserKey(
  token: string,
  keyType: string,
  apiKey: string,
): Promise<UserKey> {
  return apiRequest<UserKey>("/v1/user-keys", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ key_type: keyType, api_key: apiKey }),
  });
}

export async function deleteUserKey(
  token: string,
  keyType: string,
): Promise<void> {
  await apiRequest(`/v1/user-keys/${keyType}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
}
