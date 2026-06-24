"use client";

import { FormEvent, useEffect, useState } from "react";
import { useToast } from "@/stores/toast";
import { useAuth } from "@/components/auth/auth-provider";
import { apiRequest, type Project, type SecretRecord, type WebhookEndpoint } from "@/lib/api";
import { listUserKeys, saveUserKey, deleteUserKey, type UserKey } from "@/lib/api/user-keys";
import { deleteProject, getProjects, updateProject } from "@/lib/api/projects";
import {
  downloadWorkspaceExport,
  getProfile,
  getWorkspace,
  updateProfile,
  updateWorkspace,
  type NotificationPreferences,
} from "@/lib/api/workspace";
import { getRedditAccounts, connectReddit as apiConnectReddit, disconnectRedditAccount, type RedditAccount } from "@/lib/api/reddit";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2, Trash2, Link2, Key, Webhook, FolderKanban, Save } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { AccountSafetyCard } from "@/components/settings/account-safety-card";

const PROVIDERS = ["openai", "perplexity", "gemini", "claude", "reddit", "custom"];
const EVENT_TYPES = ["opportunity.found", "scan.complete", "visibility.alert", "draft.ready"];

export default function SettingsPage() {
  const { token, user } = useAuth();
  const toast = useToast();
  const [activeTab, setActiveTab] = useState("general");
  const [loading, setLoading] = useState(false);
  const [savingGeneral, setSavingGeneral] = useState(false);
  const [exporting, setExporting] = useState(false);

  // General tab state
  const [workspaceName, setWorkspaceName] = useState("");
  const [userProfile, setUserProfile] = useState({ name: user?.full_name || "", email: user?.email || "" });
  const [notifications, setNotifications] = useState<NotificationPreferences>({
    email_notifications: true,
    digest_email: false,
    slack_notifications: false,
  });

  // API Keys tab state
  const [secrets, setSecrets] = useState<SecretRecord[]>([]);
  const [newSecret, setNewSecret] = useState({ provider: "openai", label: "", value: "" });
  const [deleteSecretId, setDeleteSecretId] = useState<number | null>(null);

  // BYOK state
  const [userKeys, setUserKeys] = useState<UserKey[]>([]);
  const [byokOpenRouter, setByokOpenRouter] = useState("");
  const [byokRapidApi, setByokRapidApi] = useState("");
  const [savingByok, setSavingByok] = useState<string | null>(null);

  // Integrations tab state
  const [webhooks, setWebhooks] = useState<WebhookEndpoint[]>([]);
  const [newWebhook, setNewWebhook] = useState({
    url: "",
    eventTypes: [] as string[],
  });
  const [deleteWebhookId, setDeleteWebhookId] = useState<number | null>(null);
  const [testingWebhookId, setTestingWebhookId] = useState<number | null>(null);

  // Danger zone state
  const [deleteWorkspaceConfirm, setDeleteWorkspaceConfirm] = useState("");

  // Reddit state
  const [redditAccounts, setRedditAccounts] = useState<RedditAccount[]>([]);
  const [connectingReddit, setConnectingReddit] = useState(false);
  const [disconnectingReddit, setDisconnectingReddit] = useState<number | null>(null);

  // Projects tab state
  const [projects, setProjects] = useState<Project[]>([]);
  const [renamingProject, setRenamingProject] = useState<number | null>(null);
  const [projectDraftName, setProjectDraftName] = useState<Record<number, string>>({});
  const [deletingProjectId, setDeletingProjectId] = useState<number | null>(null);
  const [deleteProjectTarget, setDeleteProjectTarget] = useState<Project | null>(null);
  const [deleteProjectConfirm, setDeleteProjectConfirm] = useState("");

  useEffect(() => {
    if (!token) return;
    loadData();
  }, [token]);

  useEffect(() => {
    setUserProfile({ name: user?.full_name || "", email: user?.email || "" });
  }, [user]);

  async function loadData() {
    if (!token) return;
    try {
      const [webhookRows, secretRows, redditRows, workspaceRow, profileRow, projectRows, userKeyRows] = await Promise.all([
        apiRequest<WebhookEndpoint[]>("/v1/webhooks", {}, token),
        apiRequest<SecretRecord[]>("/v1/secrets", {}, token),
        getRedditAccounts(token).catch(() => [] as RedditAccount[]),
        getWorkspace(token).catch(() => null),
        getProfile(token).catch(() => null),
        getProjects(token).catch(() => [] as Project[]),
        listUserKeys(token).catch(() => [] as UserKey[]),
      ]);
      setWebhooks(webhookRows);
      setSecrets(secretRows);
      setRedditAccounts(redditRows);
      setProjects(projectRows);
      setUserKeys(userKeyRows);
      setProjectDraftName(
        Object.fromEntries(projectRows.map((p) => [p.id, p.name])),
      );
      if (workspaceRow) {
        setWorkspaceName(workspaceRow.name || "");
      }
      if (profileRow) {
        setUserProfile({ name: profileRow.full_name || "", email: profileRow.email || "" });
        if (profileRow.notification_preferences) {
          setNotifications({
            email_notifications: Boolean(profileRow.notification_preferences.email_notifications),
            digest_email: Boolean(profileRow.notification_preferences.digest_email),
            slack_notifications: Boolean(profileRow.notification_preferences.slack_notifications),
          });
        }
      }
    } catch (err) {
      toast.error("Failed to load settings", err instanceof Error ? err.message : undefined);
    }
  }

  async function handleSaveByok(keyType: "openrouter" | "rapidapi") {
    if (!token) return;
    const value = keyType === "openrouter" ? byokOpenRouter : byokRapidApi;
    if (!value.trim()) {
      toast.error("Please enter a valid API key");
      return;
    }
    setSavingByok(keyType);
    try {
      await saveUserKey(token, keyType, value.trim());
      toast.success(`${keyType === "openrouter" ? "OpenRouter" : "RapidAPI"} key saved`);
      if (keyType === "openrouter") setByokOpenRouter("");
      else setByokRapidApi("");
      const updated = await listUserKeys(token).catch(() => [] as UserKey[]);
      setUserKeys(updated);
    } catch (err) {
      toast.error("Failed to save key", err instanceof Error ? err.message : undefined);
    } finally {
      setSavingByok(null);
    }
  }

  async function handleDeleteByok(keyType: string) {
    if (!token) return;
    setSavingByok(keyType);
    try {
      await deleteUserKey(token, keyType);
      toast.success(`${keyType === "openrouter" ? "OpenRouter" : "RapidAPI"} key removed`);
      const updated = await listUserKeys(token).catch(() => [] as UserKey[]);
      setUserKeys(updated);
    } catch (err) {
      toast.error("Failed to remove key", err instanceof Error ? err.message : undefined);
    } finally {
      setSavingByok(null);
    }
  }

  async function connectReddit() {
    if (!token) return;
    setConnectingReddit(true);
    try {
      const result = await apiConnectReddit(token);
      if (result.auth_url) {
        window.open(result.auth_url, "_blank", "width=600,height=700");
        setTimeout(() => void loadData(), 3000);
      }
    } catch (err) {
      toast.error("Failed to connect Reddit", err instanceof Error ? err.message : undefined);
    }
    setConnectingReddit(false);
  }

  async function disconnectReddit(accountId: number) {
    if (!token) return;
    setDisconnectingReddit(accountId);
    try {
      await disconnectRedditAccount(token, accountId);
      setRedditAccounts((rows) => rows.filter((r) => r.id !== accountId));
      toast.success("Reddit account disconnected");
    } catch (err) {
      toast.error("Failed to disconnect", err instanceof Error ? err.message : undefined);
    }
    setDisconnectingReddit(null);
  }

  async function saveGeneralSettings() {
    if (!token) return;
    const trimmedWorkspace = workspaceName.trim();
    const trimmedName = userProfile.name.trim();
    if (trimmedWorkspace.length < 2) {
      toast.warning("Invalid workspace name", "Workspace name must be at least 2 characters.");
      return;
    }
    setSavingGeneral(true);
    try {
      // Run both updates in parallel. If either one fails we still surface a single error.
      const results = await Promise.allSettled([
        updateWorkspace(token, { name: trimmedWorkspace }),
        updateProfile(token, {
          full_name: trimmedName,
          notification_preferences: notifications,
        }),
      ]);
      const failures = results.filter((r): r is PromiseRejectedResult => r.status === "rejected");
      if (failures.length > 0) {
        const message = failures
          .map((f) => (f.reason instanceof Error ? f.reason.message : String(f.reason)))
          .join(" · ");
        throw new Error(message);
      }
      toast.success("Settings saved", "Workspace and profile updated.");
    } catch (err) {
      toast.error("Failed to save settings", err instanceof Error ? err.message : undefined);
    } finally {
      setSavingGeneral(false);
    }
  }

  async function createSecret(e: FormEvent) {
    e.preventDefault();
    if (!token || !newSecret.provider || !newSecret.label || !newSecret.value) {
      toast.warning("Invalid input", "Please fill in all fields");
      return;
    }
    setLoading(true);
    try {
      const created = await apiRequest<SecretRecord>("/v1/secrets", {
        method: "POST",
        body: JSON.stringify(newSecret),
      }, token);
      setSecrets((rows) => [created, ...rows]);
      setNewSecret({ provider: "openai", label: "", value: "" });
      toast.success("API key saved", "Your secret has been securely stored");
    } catch (err) {
      toast.error("Failed to save key", err instanceof Error ? err.message : undefined);
    } finally {
      setLoading(false);
    }
  }

  async function deleteSecret(id: number) {
    if (!token) return;
    setLoading(true);
    try {
      await apiRequest("/v1/secrets/" + id, { method: "DELETE" }, token);
      setSecrets((rows) => rows.filter((r) => r.id !== id));
      setDeleteSecretId(null);
      toast.success("API key deleted", "The secret has been removed");
    } catch (err) {
      toast.error("Failed to delete key", err instanceof Error ? err.message : undefined);
    } finally {
      setLoading(false);
    }
  }

  async function createWebhook(e: FormEvent) {
    e.preventDefault();
    if (!token || !newWebhook.url || newWebhook.eventTypes.length === 0) {
      toast.warning("Invalid input", "Please provide a URL and select at least one event");
      return;
    }
    setLoading(true);
    try {
      const created = await apiRequest<WebhookEndpoint>("/v1/webhooks", {
        method: "POST",
        body: JSON.stringify({
          target_url: newWebhook.url,
          event_types: newWebhook.eventTypes,
          is_active: true,
        }),
      }, token);
      setWebhooks((rows) => [created, ...rows]);
      setNewWebhook({ url: "", eventTypes: [] });
      toast.success("Webhook added", "Your integration has been configured");
    } catch (err) {
      toast.error("Failed to create webhook", err instanceof Error ? err.message : undefined);
    } finally {
      setLoading(false);
    }
  }

  async function toggleWebhook(id: number, isActive: boolean) {
    if (!token) return;
    setLoading(true);
    try {
      const updated = await apiRequest<WebhookEndpoint>("/v1/webhooks/" + id, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !isActive }),
      }, token);
      setWebhooks((rows) => rows.map((r) => (r.id === id ? updated : r)));
      toast.success(
        !isActive ? "Webhook enabled" : "Webhook disabled",
        "Your integration status has been updated"
      );
    } catch (err) {
      toast.error("Failed to update webhook", err instanceof Error ? err.message : undefined);
    } finally {
      setLoading(false);
    }
  }

  async function testWebhook(id: number) {
    if (!token) return;
    setTestingWebhookId(id);
    try {
      await apiRequest(`/v1/webhooks/${id}/test`, { method: "POST" }, token);
      toast.success("Webhook test sent", "Check your endpoint for the test payload");
    } catch (err) {
      toast.error("Failed to test webhook", err instanceof Error ? err.message : undefined);
    } finally {
      setTestingWebhookId(null);
    }
  }

  async function deleteWebhook(id: number) {
    if (!token) return;
    setLoading(true);
    try {
      await apiRequest("/v1/webhooks/" + id, { method: "DELETE" }, token);
      setWebhooks((rows) => rows.filter((r) => r.id !== id));
      setDeleteWebhookId(null);
      toast.success("Webhook deleted", "Your integration has been removed");
    } catch (err) {
      toast.error("Failed to delete webhook", err instanceof Error ? err.message : undefined);
    } finally {
      setLoading(false);
    }
  }

  async function exportData() {
    if (!token) return;
    setExporting(true);
    try {
      await downloadWorkspaceExport(token);
      toast.success("Export ready", "Your data export has been downloaded.");
    } catch (err) {
      toast.error("Export failed", err instanceof Error ? err.message : undefined);
    } finally {
      setExporting(false);
    }
  }

  async function deleteWorkspace() {
    if (!token || deleteWorkspaceConfirm !== "DELETE WORKSPACE") return;
    setLoading(true);
    try {
      await apiRequest("/v1/workspace", { method: "DELETE" }, token);
      toast.success("Workspace deleted", "Redirecting...");
      setTimeout(() => (window.location.href = "/"), 2000);
    } catch (err) {
      toast.error("Failed to delete workspace", err instanceof Error ? err.message : undefined);
    } finally {
      setLoading(false);
    }
  }

  async function handleRenameProject(projectId: number) {
    if (!token) return;
    const nextName = (projectDraftName[projectId] ?? "").trim();
    if (nextName.length < 2) {
      toast.warning("Invalid name", "Project name must be at least 2 characters.");
      return;
    }
    setRenamingProject(projectId);
    try {
      const updated = await updateProject(token, projectId, { name: nextName });
      setProjects((rows) => rows.map((p) => (p.id === projectId ? updated : p)));
      toast.success("Project renamed", `Now called "${updated.name}".`);
    } catch (err) {
      toast.error("Failed to rename project", err instanceof Error ? err.message : undefined);
    } finally {
      setRenamingProject(null);
    }
  }

  async function handleDeleteProject() {
    if (!token || !deleteProjectTarget) return;
    if (deleteProjectConfirm !== deleteProjectTarget.name) return;
    setDeletingProjectId(deleteProjectTarget.id);
    try {
      await deleteProject(token, deleteProjectTarget.id);
      const removedId = deleteProjectTarget.id;
      setProjects((rows) => rows.filter((p) => p.id !== removedId));
      setProjectDraftName((drafts) => {
        const next = { ...drafts };
        delete next[removedId];
        return next;
      });
      toast.success("Project deleted", `"${deleteProjectTarget.name}" was removed.`);
      setDeleteProjectTarget(null);
      setDeleteProjectConfirm("");
    } catch (err) {
      toast.error("Failed to delete project", err instanceof Error ? err.message : undefined);
    } finally {
      setDeletingProjectId(null);
    }
  }

  const maskSecret = (secret: string) => {
    if (!secret || secret.length < 4) return "***";
    return secret.slice(0, 3) + "..." + secret.slice(-3);
  };

  return (
    <div className="flex flex-col gap-8">
      <PageHeader title="Settings" description="Manage workspace preferences, integrations, and account connections." />

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="w-full overflow-x-auto">
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="reddit">
            Reddit
            {redditAccounts.length > 0 && (
              <Badge variant="secondary" className="ml-1.5 text-xs">{redditAccounts.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="api-keys">
            API Keys
            {secrets.length > 0 && (
              <Badge variant="secondary" className="ml-1.5 text-xs">{secrets.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="integrations">
            Integrations
            {webhooks.length > 0 && (
              <Badge variant="secondary" className="ml-1.5 text-xs">{webhooks.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="projects">
            Projects
            {projects.length > 0 && (
              <Badge variant="secondary" className="ml-1.5 text-xs">{projects.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="danger">Danger Zone</TabsTrigger>
        </TabsList>

        {/* GENERAL TAB */}
        <TabsContent value="general">
          <div className="mt-6 grid gap-8">
            <section>
              <h3 className="mb-4 text-sm font-semibold text-foreground">Workspace</h3>
              <div className="grid gap-2">
                <Label htmlFor="workspace-name">Workspace name</Label>
                <Input
                  id="workspace-name"
                  value={workspaceName}
                  onChange={(e) => setWorkspaceName(e.target.value)}
                  placeholder="My Workspace"
                />
              </div>
            </section>

            <Separator />

            <section>
              <h3 className="mb-4 text-sm font-semibold text-foreground">User Profile</h3>
              <div className="grid gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="full-name">Full name</Label>
                  <Input
                    id="full-name"
                    value={userProfile.name}
                    onChange={(e) => setUserProfile({ ...userProfile, name: e.target.value })}
                    placeholder="Your name"
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    value={userProfile.email}
                    onChange={(e) => setUserProfile({ ...userProfile, email: e.target.value })}
                    placeholder="your@email.com"
                    disabled
                  />
                </div>
              </div>
            </section>

            <Separator />

            <section>
              <h3 className="mb-4 text-sm font-semibold text-foreground">Notifications</h3>
              <div className="grid gap-3">
                <label className="flex items-center gap-3 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 rounded border-input"
                    checked={notifications.email_notifications}
                    onChange={(e) =>
                      setNotifications({ ...notifications, email_notifications: e.target.checked })
                    }
                  />
                  <span>Email notifications</span>
                </label>
                <label className="flex items-center gap-3 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 rounded border-input"
                    checked={notifications.digest_email}
                    onChange={(e) =>
                      setNotifications({ ...notifications, digest_email: e.target.checked })
                    }
                  />
                  <span>Weekly digest email</span>
                </label>
                <label className="flex items-center gap-3 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 rounded border-input"
                    checked={notifications.slack_notifications}
                    onChange={(e) =>
                      setNotifications({ ...notifications, slack_notifications: e.target.checked })
                    }
                  />
                  <span>Slack notifications</span>
                </label>
              </div>
            </section>

            <div className="flex flex-wrap gap-2">
              <Button onClick={saveGeneralSettings} disabled={savingGeneral}>
                {savingGeneral && <Loader2 className="h-4 w-4 animate-spin" />}
                Save changes
              </Button>
            </div>
          </div>
        </TabsContent>

        {/* REDDIT TAB */}
        <TabsContent value="reddit">
          <div className="mt-6">
            <section>
              <h3 className="mb-4 text-sm font-semibold text-foreground">Reddit Accounts</h3>
              {redditAccounts.length === 0 ? (
                <Card className="p-8">
                  <div className="flex flex-col items-center justify-center text-center">
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted mb-4">
                      <Link2 className="h-8 w-8 text-muted-foreground/50" />
                    </div>
                    <h3 className="mb-1 text-sm font-semibold text-foreground">No Reddit accounts connected</h3>
                    <p className="mb-4 text-xs text-muted-foreground">
                      Connect a Reddit account to enable automated posting and engagement
                    </p>
                    <Button onClick={() => void connectReddit()} disabled={connectingReddit}>
                      {connectingReddit && <Loader2 className="h-4 w-4 animate-spin" />}
                      Connect Reddit Account
                    </Button>
                  </div>
                </Card>
              ) : (
                <div className="grid gap-3">
                  {redditAccounts.map((account) => (
                    <Card key={account.id} className="p-4">
                      <div className="flex items-center justify-between gap-4">
                        <div className="flex items-center gap-3">
                          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10 text-primary font-bold text-sm">
                            {account.username.charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-semibold text-foreground">@{account.username}</span>
                              <span className="inline-flex items-center justify-center rounded-full border border-success/20 bg-success/10 px-2 py-0.5 text-xs font-semibold text-success">
                                Connected
                              </span>
                            </div>
                            <div className="flex gap-3 text-xs text-muted-foreground mt-0.5">
                              {account.karma !== undefined && <span>Karma: {account.karma}</span>}
                              {account.connected_at && (
                                <span>Connected: {new Date(account.connected_at).toLocaleDateString()}</span>
                              )}
                            </div>
                          </div>
                        </div>
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => void disconnectReddit(account.id)}
                          disabled={disconnectingReddit === account.id}
                        >
                          {disconnectingReddit === account.id && <Loader2 className="h-4 w-4 animate-spin" />}
                          Disconnect
                        </Button>
                      </div>
                      <AccountSafetyCard token={token} accountId={account.id} />
                    </Card>
                  ))}
                  <Button
                    variant="outline"
                    onClick={() => void connectReddit()}
                    disabled={connectingReddit}
                    className="mt-3"
                  >
                    {connectingReddit && <Loader2 className="h-4 w-4 animate-spin" />}
                    Connect Additional Account
                  </Button>
                </div>
              )}
            </section>
          </div>
        </TabsContent>

        {/* API KEYS TAB */}
        <TabsContent value="api-keys">
          <div className="mt-6 grid gap-8">
            {/* BYOK — Bring Your Own Key */}
            <section>
              <h3 className="mb-1 text-sm font-semibold text-foreground">Your Keys (BYOK)</h3>
              <p className="mb-4 text-xs text-muted-foreground">
                Provide your own API keys to use your own accounts for LLM generation and social data scraping.
                Keys are encrypted at rest and never shown after saving.
              </p>
              <div className="grid gap-4 sm:grid-cols-2">
                {/* OpenRouter */}
                <Card className="p-4">
                  <div className="flex items-center gap-3 mb-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10">
                      <Key className="h-4 w-4 text-emerald-500" />
                    </div>
                    <div>
                      <strong className="text-sm font-medium text-foreground">OpenRouter</strong>
                      <p className="text-xs text-muted-foreground">LLM provider for AI generation</p>
                    </div>
                    {userKeys.find(k => k.key_type === "openrouter") && (
                      <Badge variant="secondary" className="ml-auto text-xs">Active</Badge>
                    )}
                  </div>
                  {userKeys.find(k => k.key_type === "openrouter") ? (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground flex-1">Key is set and encrypted</span>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={savingByok === "openrouter"}
                        onClick={() => handleDeleteByok("openrouter")}
                      >
                        {savingByok === "openrouter" && <Loader2 className="h-3 w-3 animate-spin" />}
                        Remove
                      </Button>
                    </div>
                  ) : (
                    <div className="flex gap-2">
                      <Input
                        type="password"
                        placeholder="sk-or-..."
                        value={byokOpenRouter}
                        onChange={(e) => setByokOpenRouter(e.target.value)}
                        className="text-sm"
                      />
                      <Button
                        size="sm"
                        disabled={savingByok === "openrouter" || !byokOpenRouter.trim()}
                        onClick={() => handleSaveByok("openrouter")}
                      >
                        {savingByok === "openrouter" && <Loader2 className="h-3 w-3 animate-spin" />}
                        <Save className="h-3 w-3" />
                      </Button>
                    </div>
                  )}
                </Card>

                {/* RapidAPI */}
                <Card className="p-4">
                  <div className="flex items-center gap-3 mb-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/10">
                      <Key className="h-4 w-4 text-blue-500" />
                    </div>
                    <div>
                      <strong className="text-sm font-medium text-foreground">RapidAPI</strong>
                      <p className="text-xs text-muted-foreground">Social data scraping</p>
                    </div>
                    {userKeys.find(k => k.key_type === "rapidapi") && (
                      <Badge variant="secondary" className="ml-auto text-xs">Active</Badge>
                    )}
                  </div>
                  {userKeys.find(k => k.key_type === "rapidapi") ? (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground flex-1">Key is set and encrypted</span>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={savingByok === "rapidapi"}
                        onClick={() => handleDeleteByok("rapidapi")}
                      >
                        {savingByok === "rapidapi" && <Loader2 className="h-3 w-3 animate-spin" />}
                        Remove
                      </Button>
                    </div>
                  ) : (
                    <div className="flex gap-2">
                      <Input
                        type="password"
                        placeholder="Your RapidAPI key"
                        value={byokRapidApi}
                        onChange={(e) => setByokRapidApi(e.target.value)}
                        className="text-sm"
                      />
                      <Button
                        size="sm"
                        disabled={savingByok === "rapidapi" || !byokRapidApi.trim()}
                        onClick={() => handleSaveByok("rapidapi")}
                      >
                        {savingByok === "rapidapi" && <Loader2 className="h-3 w-3 animate-spin" />}
                        <Save className="h-3 w-3" />
                      </Button>
                    </div>
                  )}
                </Card>
              </div>
            </section>

            <Separator />

            <section>
              <h3 className="mb-4 text-sm font-semibold text-foreground">Add API Key</h3>
              <form onSubmit={createSecret} className="grid gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="secret-provider">Provider</Label>
                  <Select
                    value={newSecret.provider}
                    onValueChange={(value) => setNewSecret({ ...newSecret, provider: value ?? "openai" })}
                  >
                    <SelectTrigger id="secret-provider" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PROVIDERS.map((p) => (
                        <SelectItem key={p} value={p}>
                          {p.charAt(0).toUpperCase() + p.slice(1)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="secret-label">Label</Label>
                  <Input
                    id="secret-label"
                    value={newSecret.label}
                    onChange={(e) => setNewSecret({ ...newSecret, label: e.target.value })}
                    placeholder="e.g., Production key"
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="secret-value">Secret value</Label>
                  <Input
                    id="secret-value"
                    type="password"
                    value={newSecret.value}
                    onChange={(e) => setNewSecret({ ...newSecret, value: e.target.value })}
                    placeholder="Paste your API key here"
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="submit" disabled={loading}>
                    {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                    Save API key
                  </Button>
                </div>
              </form>
            </section>

            <Separator />

            <section>
              <h3 className="mb-4 text-sm font-semibold text-foreground">Saved Keys</h3>
              {secrets.length === 0 ? (
                <Card className="p-8">
                  <div className="flex flex-col items-center justify-center text-center">
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted mb-4">
                      <Key className="h-8 w-8 text-muted-foreground/50" />
                    </div>
                    <h3 className="mb-1 text-sm font-semibold text-foreground">No API keys saved</h3>
                    <p className="text-xs text-muted-foreground">Add your first API key to get started</p>
                  </div>
                </Card>
              ) : (
                <div className="grid gap-3">
                  {secrets.map((secret) => (
                    <Card key={secret.id} className="p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-3">
                          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
                            <Key className="h-4 w-4 text-muted-foreground" />
                          </div>
                          <div>
                            <strong className="text-sm font-medium text-foreground capitalize">{secret.provider}</strong>
                            <p className="text-xs text-muted-foreground">{secret.label}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <Badge variant="secondary" className="text-xs">
                            {secret.provider} • {secret.label}
                          </Badge>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            onClick={() => setDeleteSecretId(secret.id)}
                            aria-label={`Delete ${secret.provider} secret`}
                          >
                            <Trash2 className="h-4 w-4 text-muted-foreground" />
                          </Button>
                        </div>
                      </div>
                    </Card>
                  ))}
                </div>
              )}
            </section>
          </div>
        </TabsContent>

        {/* INTEGRATIONS TAB */}
        <TabsContent value="integrations">
          <div className="mt-6 grid gap-8">
            <section>
              <h3 className="mb-4 text-sm font-semibold text-foreground">Add Webhook</h3>
              <form onSubmit={createWebhook} className="grid gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="webhook-url">Webhook URL</Label>
                  <Input
                    id="webhook-url"
                    type="url"
                    value={newWebhook.url}
                    onChange={(e) => setNewWebhook({ ...newWebhook, url: e.target.value })}
                    placeholder="https://your-app.com/webhook"
                  />
                </div>
                <div className="grid gap-2">
                  <Label>Events to receive</Label>
                  <div className="mt-1 grid gap-2">
                    {EVENT_TYPES.map((event) => (
                      <label key={event} className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="size-4 rounded border-input"
                          checked={newWebhook.eventTypes.includes(event)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setNewWebhook({
                                ...newWebhook,
                                eventTypes: [...newWebhook.eventTypes, event],
                              });
                            } else {
                              setNewWebhook({
                                ...newWebhook,
                                eventTypes: newWebhook.eventTypes.filter((t) => t !== event),
                              });
                            }
                          }}
                        />
                        <span>{event}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="submit" disabled={loading}>
                    {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                    Add webhook
                  </Button>
                </div>
              </form>
            </section>

            <Separator />

            <section>
              <h3 className="mb-4 text-sm font-semibold text-foreground">Active Webhooks</h3>
              {webhooks.length === 0 ? (
                <Card className="p-8">
                  <div className="flex flex-col items-center justify-center text-center">
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted mb-4">
                      <Webhook className="h-8 w-8 text-muted-foreground/50" />
                    </div>
                    <h3 className="mb-1 text-sm font-semibold text-foreground">No webhooks configured</h3>
                    <p className="text-xs text-muted-foreground">Add a webhook to receive event notifications</p>
                  </div>
                </Card>
              ) : (
                <div className="grid gap-3">
                  {webhooks.map((webhook) => (
                    <Card key={webhook.id} className="p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted shrink-0">
                              <Webhook className="h-4 w-4 text-muted-foreground" />
                            </div>
                            <strong className="text-sm font-medium text-foreground break-all">
                              {webhook.target_url}
                            </strong>
                          </div>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {webhook.event_types.map((type) => (
                              <Badge key={type} variant="secondary" className="text-xs">
                                {type}
                              </Badge>
                            ))}
                          </div>
                          {webhook.last_tested_at && (
                            <p className="mt-2 text-xs text-muted-foreground">
                              Last tested: {new Date(webhook.last_tested_at).toLocaleDateString()}
                            </p>
                          )}
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => toggleWebhook(webhook.id, webhook.is_active)}
                            disabled={loading}
                          >
                            {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                            {webhook.is_active ? "Disable" : "Enable"}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => testWebhook(webhook.id)}
                            disabled={testingWebhookId === webhook.id}
                          >
                            {testingWebhookId === webhook.id && <Loader2 className="h-4 w-4 animate-spin" />}
                            Test
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            onClick={() => setDeleteWebhookId(webhook.id)}
                          >
                            <Trash2 className="h-4 w-4 text-muted-foreground" />
                          </Button>
                        </div>
                      </div>
                    </Card>
                  ))}
                </div>
              )}
            </section>
          </div>
        </TabsContent>

        {/* PROJECTS TAB */}
        <TabsContent value="projects">
          <div className="mt-6 grid gap-8">
            <section>
              <h3 className="mb-4 text-sm font-semibold text-foreground">Projects</h3>
              {projects.length === 0 ? (
                <Card className="p-8">
                  <div className="flex flex-col items-center justify-center text-center">
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted mb-4">
                      <FolderKanban className="h-8 w-8 text-muted-foreground/50" />
                    </div>
                    <h3 className="mb-1 text-sm font-semibold text-foreground">No projects yet</h3>
                    <p className="text-xs text-muted-foreground">
                      Create a project from the dashboard to get started.
                    </p>
                  </div>
                </Card>
              ) : (
                <div className="grid gap-3">
                  {projects.map((project) => {
                    const draft = projectDraftName[project.id] ?? project.name;
                    const dirty = draft.trim() !== project.name;
                    const isRenaming = renamingProject === project.id;
                    const isDeleting = deletingProjectId === project.id;
                    return (
                      <Card key={project.id} className="p-4">
                        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                          <div className="flex items-center gap-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted shrink-0">
                              <FolderKanban className="h-5 w-5 text-muted-foreground" />
                            </div>
                            <div className="grid gap-2">
                              <Label htmlFor={`project-name-${project.id}`} className="sr-only">
                                Project name
                              </Label>
                              <Input
                                id={`project-name-${project.id}`}
                                value={draft}
                                onChange={(e) =>
                                  setProjectDraftName((map) => ({
                                    ...map,
                                    [project.id]: e.target.value,
                                  }))
                                }
                                className="min-w-[18rem]"
                                disabled={isRenaming || isDeleting}
                              />
                              <p className="text-xs text-muted-foreground">
                                Slug: <span className="font-mono">{project.slug}</span>
                                {project.description ? ` · ${project.description}` : ""}
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleRenameProject(project.id)}
                              disabled={!dirty || isRenaming || isDeleting}
                            >
                              {isRenaming ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Save className="h-4 w-4" />
                              )}
                              Save
                            </Button>
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => {
                                setDeleteProjectTarget(project);
                                setDeleteProjectConfirm("");
                              }}
                              disabled={isDeleting}
                              aria-label={`Delete project ${project.name}`}
                            >
                              {isDeleting ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Trash2 className="h-4 w-4" />
                              )}
                              Delete
                            </Button>
                          </div>
                        </div>
                      </Card>
                    );
                  })}
                </div>
              )}
              <p className="mt-4 text-xs text-muted-foreground">
                Deleting a project permanently removes its brand profile, personas, keywords, subreddits, opportunities, and drafts. This cannot be undone.
              </p>
            </section>
          </div>
        </TabsContent>

        {/* DANGER ZONE TAB */}
        <TabsContent value="danger">
          <div className="mt-6 grid gap-8">
            <section className="rounded-lg border border-destructive/30 bg-destructive/5 p-5">
              <h3 className="mb-4 text-sm font-semibold text-destructive">Export data</h3>
              <p className="mb-4 text-sm text-muted-foreground">
                Download a copy of all your data in JSON format. This includes your workspace configuration,
                settings, and history.
              </p>
              <Button variant="outline" onClick={exportData} disabled={exporting}>
                {exporting && <Loader2 className="h-4 w-4 animate-spin" />}
                Download data export
              </Button>
            </section>

            <section className="rounded-lg border border-destructive/30 bg-destructive/5 p-5">
              <h3 className="mb-4 text-sm font-semibold text-destructive">Delete workspace</h3>
              <p className="mb-4 text-sm text-muted-foreground">
                Permanently delete this workspace and all associated data. This action cannot be undone.
              </p>
              <div className="grid gap-2">
                <Label htmlFor="delete-confirm">Type &quot;DELETE WORKSPACE&quot; to confirm</Label>
                <Input
                  id="delete-confirm"
                  value={deleteWorkspaceConfirm}
                  onChange={(e) => setDeleteWorkspaceConfirm(e.target.value)}
                  placeholder="DELETE WORKSPACE"
                />
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  variant="destructive"
                  onClick={() => deleteWorkspace()}
                  disabled={deleteWorkspaceConfirm !== "DELETE WORKSPACE" || loading}
                >
                  {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                  Delete workspace permanently
                </Button>
              </div>
            </section>
          </div>
        </TabsContent>
      </Tabs>

      {/* Confirm modals */}
      <AlertDialog open={deleteSecretId !== null} onOpenChange={(open) => { if (!open) setDeleteSecretId(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete API key</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this API key? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => deleteSecret(deleteSecretId!)}
              disabled={loading}
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={deleteWebhookId !== null} onOpenChange={(open) => { if (!open) setDeleteWebhookId(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete webhook</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this webhook? Your integrations will no longer receive events.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => deleteWebhook(deleteWebhookId!)}
              disabled={loading}
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={deleteProjectTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteProjectTarget(null);
            setDeleteProjectConfirm("");
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete project?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete <strong>{deleteProjectTarget?.name}</strong> along with its
              brand profile, personas, keywords, subreddits, opportunities, and drafts. This action
              cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="grid gap-2 py-2">
            <Label htmlFor="delete-project-confirm">
              Type the project name (<span className="font-mono">{deleteProjectTarget?.name}</span>) to confirm
            </Label>
            <Input
              id="delete-project-confirm"
              value={deleteProjectConfirm}
              onChange={(e) => setDeleteProjectConfirm(e.target.value)}
              placeholder={deleteProjectTarget?.name ?? ""}
              autoComplete="off"
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => handleDeleteProject()}
              disabled={
                deletingProjectId !== null ||
                !deleteProjectTarget ||
                deleteProjectConfirm !== deleteProjectTarget.name
              }
            >
              {deletingProjectId !== null && <Loader2 className="h-4 w-4 animate-spin" />}
              Delete project
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
