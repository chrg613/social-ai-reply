"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Loader2, Mic2, Plus, Sparkles, Star, Trash2, Pencil, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import {
  analyzeVoiceProfile,
  createVoiceProfile,
  deleteVoiceProfile,
  getVoiceProfiles,
  updateVoiceProfile,
  type VoiceProfile,
} from "@/lib/api/voice";
import { useToast } from "@/stores/toast";
import { getErrorMessage } from "@/types/errors";

const MAX_EXAMPLES = 5;
const MAX_EXAMPLE_CHARS = 2000;

interface VoiceProfileFormState {
  name: string;
  exampleReplies: string[];
  bannedPhrases: string;
  isDefault: boolean;
}

const emptyForm: VoiceProfileFormState = {
  name: "",
  exampleReplies: [""],
  bannedPhrases: "",
  isDefault: false,
};

function parseBannedPhrases(raw: string): string[] {
  return raw
    .split(",")
    .map((phrase) => phrase.trim())
    .filter((phrase) => phrase.length > 0);
}

export function VoiceProfilesSection({
  token,
  projectId,
}: {
  token: string | null | undefined;
  projectId: number | null | undefined;
}) {
  const { success, error } = useToast();
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<VoiceProfile | null>(null);
  const [form, setForm] = useState<VoiceProfileFormState>(emptyForm);
  const [saving, setSaving] = useState(false);

  const [analyzingId, setAnalyzingId] = useState<number | null>(null);
  const [settingDefaultId, setSettingDefaultId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<VoiceProfile | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadProfiles = useCallback(async () => {
    if (!token || !projectId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const rows = await getVoiceProfiles(token, projectId);
      setProfiles(rows);
    } catch (err: unknown) {
      setLoadError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [token, projectId]);

  useEffect(() => {
    void loadProfiles();
  }, [loadProfiles]);

  function openCreateDialog() {
    setEditingProfile(null);
    setForm({ ...emptyForm, exampleReplies: [""], isDefault: profiles.length === 0 });
    setDialogOpen(true);
  }

  function openEditDialog(profile: VoiceProfile) {
    setEditingProfile(profile);
    setForm({
      name: profile.name,
      exampleReplies: profile.example_replies.length > 0 ? [...profile.example_replies] : [""],
      bannedPhrases: profile.banned_phrases.join(", "),
      isDefault: profile.is_default,
    });
    setDialogOpen(true);
  }

  function setExample(index: number, value: string) {
    setForm((prev) => ({
      ...prev,
      exampleReplies: prev.exampleReplies.map((reply, i) => (i === index ? value : reply)),
    }));
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !projectId) return;
    const name = form.name.trim();
    if (name.length < 2) {
      error("Invalid name", "Profile name must be at least 2 characters.");
      return;
    }
    const examples = form.exampleReplies.map((reply) => reply.trim()).filter((reply) => reply.length > 0);
    if (examples.some((reply) => reply.length > MAX_EXAMPLE_CHARS)) {
      error("Example too long", `Each example reply must be at most ${MAX_EXAMPLE_CHARS} characters.`);
      return;
    }
    setSaving(true);
    const payload = {
      name,
      example_replies: examples.slice(0, MAX_EXAMPLES),
      banned_phrases: parseBannedPhrases(form.bannedPhrases),
      is_default: form.isDefault,
    };
    try {
      if (editingProfile) {
        await updateVoiceProfile(token, editingProfile.id, payload);
        success("Voice profile updated");
      } else {
        await createVoiceProfile(token, projectId, payload);
        success("Voice profile created");
      }
      setDialogOpen(false);
      await loadProfiles();
    } catch (err: unknown) {
      error(editingProfile ? "Could not update profile" : "Could not create profile", getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function analyzeProfile(profile: VoiceProfile) {
    if (!token) return;
    setAnalyzingId(profile.id);
    try {
      const analyzed = await analyzeVoiceProfile(token, profile.id);
      setProfiles((rows) => rows.map((row) => (row.id === analyzed.id ? analyzed : row)));
      success("Voice analyzed", "A style guide and tone descriptors were generated from your examples.");
    } catch (err: unknown) {
      error("Could not analyze voice", getErrorMessage(err));
    } finally {
      setAnalyzingId(null);
    }
  }

  async function setAsDefault(profile: VoiceProfile) {
    if (!token || profile.is_default) return;
    setSettingDefaultId(profile.id);
    try {
      await updateVoiceProfile(token, profile.id, { is_default: true });
      setProfiles((rows) => rows.map((row) => ({ ...row, is_default: row.id === profile.id })));
      success("Default voice updated", `"${profile.name}" is now used for new reply drafts.`);
    } catch (err: unknown) {
      error("Could not set default", getErrorMessage(err));
    } finally {
      setSettingDefaultId(null);
    }
  }

  async function confirmDelete() {
    if (!token || !deleteTarget) return;
    setDeleting(true);
    try {
      await deleteVoiceProfile(token, deleteTarget.id);
      setProfiles((rows) => rows.filter((row) => row.id !== deleteTarget.id));
      success("Voice profile deleted");
      setDeleteTarget(null);
    } catch (err: unknown) {
      error("Could not delete profile", getErrorMessage(err));
    } finally {
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <div className="grid gap-4">
        <Card><CardContent className="p-6"><Skeleton className="h-24 w-full rounded-lg" /></CardContent></Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Voice profiles</h3>
          <p className="text-xs text-muted-foreground">
            Teach SignalFlow how you write. The default profile is applied automatically to new reply drafts.
          </p>
        </div>
        <Button size="sm" onClick={openCreateDialog}>
          <Plus className="h-4 w-4" /> New voice profile
        </Button>
      </div>

      {loadError ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
            <p className="text-sm text-muted-foreground">Failed to load voice profiles: {loadError}</p>
            <Button variant="outline" size="sm" onClick={() => void loadProfiles()}>Retry</Button>
          </CardContent>
        </Card>
      ) : profiles.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center p-8 text-center">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <Mic2 className="h-6 w-6 text-muted-foreground/60" />
            </div>
            <h4 className="text-sm font-semibold">No voice profiles yet</h4>
            <p className="mt-1 max-w-sm text-xs text-muted-foreground">
              Paste a few of your best replies and we&apos;ll analyze them into a reusable style guide so generated
              drafts sound like you.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {profiles.map((profile) => (
            <Card key={profile.id}>
              <CardContent className="p-5 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">{profile.name}</span>
                    {profile.is_default && (
                      <Badge variant="secondary" className="gap-1">
                        <Star className="h-3 w-3" /> Default
                      </Badge>
                    )}
                    <span className="text-xs text-muted-foreground">
                      {profile.example_replies.length} example{profile.example_replies.length === 1 ? "" : "s"}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      variant="outline"
                      size="xs"
                      onClick={() => void analyzeProfile(profile)}
                      disabled={analyzingId === profile.id || profile.example_replies.length === 0}
                      title={profile.example_replies.length === 0 ? "Add example replies first" : undefined}
                    >
                      {analyzingId === profile.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Sparkles className="h-3.5 w-3.5" />
                      )}
                      Analyze voice
                    </Button>
                    {!profile.is_default && (
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => void setAsDefault(profile)}
                        disabled={settingDefaultId === profile.id}
                      >
                        {settingDefaultId === profile.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Star className="h-3.5 w-3.5" />
                        )}
                        Set default
                      </Button>
                    )}
                    <Button variant="ghost" size="icon-xs" onClick={() => openEditDialog(profile)} aria-label={`Edit ${profile.name}`}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      onClick={() => setDeleteTarget(profile)}
                      aria-label={`Delete ${profile.name}`}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                    </Button>
                  </div>
                </div>

                {profile.tone_descriptors.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {profile.tone_descriptors.map((tone) => (
                      <Badge key={tone} variant="outline" className="text-xs">{tone}</Badge>
                    ))}
                  </div>
                )}

                {profile.banned_phrases.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">Banned phrases:</span>{" "}
                    {profile.banned_phrases.join(", ")}
                  </p>
                )}

                {profile.style_guide ? (
                  <div className="rounded-lg bg-muted p-4">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Style guide</p>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">{profile.style_guide}</p>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground italic">
                    No style guide yet — run &quot;Analyze voice&quot; to generate one from the example replies.
                  </p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create / edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{editingProfile ? "Edit voice profile" : "New voice profile"}</DialogTitle>
            <DialogDescription>
              Add up to {MAX_EXAMPLES} of your best replies. They&apos;re used to learn your tone and phrasing.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={saveProfile} className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
            <div className="space-y-2">
              <Label htmlFor="voice-name">Name</Label>
              <Input
                id="voice-name"
                value={form.name}
                onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
                placeholder="e.g., Founder voice"
              />
            </div>

            <div className="space-y-2">
              <Label>Example replies</Label>
              {form.exampleReplies.map((reply, index) => (
                <div key={index} className="flex items-start gap-2">
                  <div className="flex-1 space-y-1">
                    <Textarea
                      rows={3}
                      value={reply}
                      onChange={(e) => setExample(index, e.target.value)}
                      placeholder={`Example reply ${index + 1}`}
                      maxLength={MAX_EXAMPLE_CHARS}
                    />
                    <p className="text-right text-[11px] text-muted-foreground">
                      {reply.length}/{MAX_EXAMPLE_CHARS}
                    </p>
                  </div>
                  {form.exampleReplies.length > 1 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      aria-label={`Remove example ${index + 1}`}
                      onClick={() =>
                        setForm((prev) => ({
                          ...prev,
                          exampleReplies: prev.exampleReplies.filter((_, i) => i !== index),
                        }))
                      }
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              ))}
              {form.exampleReplies.length < MAX_EXAMPLES && (
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  onClick={() => setForm((prev) => ({ ...prev, exampleReplies: [...prev.exampleReplies, ""] }))}
                >
                  <Plus className="h-3.5 w-3.5" /> Add example
                </Button>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="voice-banned">Banned phrases</Label>
              <Input
                id="voice-banned"
                value={form.bannedPhrases}
                onChange={(e) => setForm((prev) => ({ ...prev, bannedPhrases: e.target.value }))}
                placeholder="Comma-separated, e.g., game changer, leverage, synergy"
              />
              {parseBannedPhrases(form.bannedPhrases).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {parseBannedPhrases(form.bannedPhrases).map((phrase) => (
                    <Badge key={phrase} variant="secondary" className="text-xs">{phrase}</Badge>
                  ))}
                </div>
              )}
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 rounded border-input"
                checked={form.isDefault}
                onChange={(e) => setForm((prev) => ({ ...prev, isDefault: e.target.checked }))}
              />
              <span>Use as the default voice for this project</span>
            </label>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={saving}>
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                {editingProfile ? "Save changes" : "Create profile"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete confirm */}
      <AlertDialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete voice profile?</AlertDialogTitle>
            <AlertDialogDescription>
              &quot;{deleteTarget?.name}&quot; will be removed. Reply generation will fall back to the project
              default (or brand voice notes). This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void confirmDelete()} disabled={deleting}>
              {deleting && <Loader2 className="h-4 w-4 animate-spin" />}
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
