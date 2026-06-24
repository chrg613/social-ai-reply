"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  Loader2,
  MessageSquare,
  FileEdit,
  CheckCircle,
  MoreHorizontal,
  Copy,
  Pencil,
  ExternalLink,
  ChevronDown,
  ArrowRight,
  LayoutTemplate,
  Link2,
  Megaphone,
  AlertTriangle,
} from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { useToast } from "@/stores/toast";
import { getErrorMessage, isApiError } from "@/types/errors";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { type PostDraft, apiRequest } from "@/lib/api";
import { withProjectId } from "@/lib/project";
import { useSelectedProjectId } from "@/hooks/use-selected-project";
import { useDraftOps } from "@/hooks/use-draft-ops";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { SheetPanel } from "@/components/shared/sheet-panel";
import { ScoreBadge } from "@/components/shared/score-badge";
import { sourceLabel, sourcePlatform } from "@/lib/opportunity";
import { redditUrl, copyText } from "@/lib/reddit";
import { setStoredProjectId } from "@/lib/project";
import { postToReddit as apiPostToReddit } from "@/lib/api/reddit";
import { createTrackedLink, shortLinkUrl } from "@/lib/api/links";
import { createAmplifyDraft, type AmplifyTarget } from "@/lib/api/amplify";
import { rememberAmplifyDraft } from "@/lib/amplify-store";

interface ReplyDraftRow {
  id: number;
  opportunity_id: number;
  content: string;
  rationale: string;
  version: number;
  created_at: string;
  opportunity_title?: string;
  opportunity_subreddit?: string;
  permalink?: string;
  body_excerpt?: string;
  score?: number;
  platform?: string;
}

interface ProjectContext {
  id: number;
  name: string;
}

interface RedditAccount {
  id: number;
  username: string;
}

interface PublishedPost {
  id: number;
  content: string;
  subreddit: string;
  post_date: string;
  status: string;
  permalink?: string;
  upvotes?: number;
  comments?: number;
}

function parsePositiveInt(value: string | null): number | null {
  if (!value) {
    return null;
  }
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export default function ContentPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { token } = useAuth();
  const { success, error } = useToast();
  const selectedProjectId = useSelectedProjectId();
  const {
    savingReply,
    savingPost,
    generateReplyDraft,
    copyToClipboard,
    copyAndOpen,
    markAsPosted: markOpportunityPosted,
    saveReplyDraft: persistReplyDraft,
    savePostDraft: persistPostDraft,
  } = useDraftOps(token);
  const requestedProjectId = parsePositiveInt(searchParams.get("project_id"));
  const requestedOpportunityId = parsePositiveInt(searchParams.get("opportunity"));
  const pendingOpportunityIdRef = useRef<number | null>(null);
  const handledOpportunityIdRef = useRef<number | null>(null);
  const loadDraftsRequestRef = useRef(0);

  const [activeTab, setActiveTab] = useState("replies");
  const [drafts, setDrafts] = useState<ReplyDraftRow[]>([]);
  const [postedDrafts, setPostedDrafts] = useState<ReplyDraftRow[]>([]);
  const [postDrafts, setPostDrafts] = useState<PostDraft[]>([]);
  const [project, setProject] = useState<ProjectContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [generatingPost, setGeneratingPost] = useState(false);

  const [selectedReply, setSelectedReply] = useState<ReplyDraftRow | null>(null);
  const [replyContent, setReplyContent] = useState("");

  const [selectedPost, setSelectedPost] = useState<PostDraft | null>(null);
  const [postTitle, setPostTitle] = useState("");
  const [postBody, setPostBody] = useState("");

  const [publishedPosts, setPublishedPosts] = useState<PublishedPost[]>([]);
  const [redditAccounts, setRedditAccounts] = useState<RedditAccount[]>([]);
  const [postingReddit, setPostingReddit] = useState(false);
  const [showPostConfirm, setShowPostConfirm] = useState(false);
  const [postingDraftId, setPostingDraftId] = useState<number | null>(null);
  const [postSubreddit, setPostSubreddit] = useState("");
  const [safetyBlock, setSafetyBlock] = useState<string | null>(null);

  // Tracked-link creation (reply ROI attribution)
  const [linkDraft, setLinkDraft] = useState<ReplyDraftRow | null>(null);
  const [linkDestination, setLinkDestination] = useState("");
  const [creatingLink, setCreatingLink] = useState(false);

  // Amplify (X thread / LinkedIn post from a reply draft)
  const [amplifyingId, setAmplifyingId] = useState<number | null>(null);

  const [threadOpen, setThreadOpen] = useState(true);
  const [rationaleOpen, setRationaleOpen] = useState(false);

  useEffect(() => {
    if (requestedProjectId && requestedProjectId !== selectedProjectId) {
      setStoredProjectId(requestedProjectId);
    }
  }, [requestedProjectId, selectedProjectId]);

  useEffect(() => {
    if (!token) {
      return;
    }
    if (requestedProjectId && requestedProjectId !== selectedProjectId) {
      return;
    }
    void loadDrafts();
  }, [token, requestedProjectId, selectedProjectId]);

  async function loadDrafts() {
    const requestId = ++loadDraftsRequestRef.current;
    const projectId = selectedProjectId;
    setLoading(true);
    try {
      const [dashboardRes, draftingRes, postedRes, postsRes, accountsRes, publishedRes] = await Promise.allSettled([
        apiRequest<any>(withProjectId("/v1/dashboard", projectId), {}, token),
        apiRequest<ReplyDraftRow[]>(withProjectId("/v1/drafts/replies?status=drafting", projectId), {}, token),
        apiRequest<ReplyDraftRow[]>(withProjectId("/v1/drafts/replies?status=posted", projectId), {}, token),
        apiRequest<PostDraft[]>(withProjectId("/v1/drafts/posts", projectId), {}, token),
        apiRequest<{ items: RedditAccount[] }>(`/v1/reddit/accounts`, {}, token),
        apiRequest<{ items: PublishedPost[] }>(withProjectId("/v1/reddit/published", projectId), {}, token),
      ]);

      if (loadDraftsRequestRef.current !== requestId) {
        return;
      }

      if (dashboardRes.status === "fulfilled") {
        const focusProject =
          dashboardRes.value.projects?.find((item: ProjectContext) => item.id === projectId) ||
          dashboardRes.value.projects?.[0] ||
          null;
        setProject(focusProject ? { id: focusProject.id, name: focusProject.name } : null);
      }
      setDrafts(draftingRes.status === "fulfilled" ? draftingRes.value : []);
      setPostedDrafts(postedRes.status === "fulfilled" ? postedRes.value : []);
      setPostDrafts(postsRes.status === "fulfilled" ? postsRes.value : []);
      setRedditAccounts(accountsRes.status === "fulfilled" ? (accountsRes.value.items ?? []) : []);
      setPublishedPosts(publishedRes.status === "fulfilled" ? (publishedRes.value.items ?? []) : []);
    } catch (err) {
      setDrafts([]);
      setPostedDrafts([]);
      setPostDrafts([]);
      setRedditAccounts([]);
      setPublishedPosts([]);
    }
    if (loadDraftsRequestRef.current === requestId) {
      setLoading(false);
    }
  }

  async function postToReddit(draftId: number, overrideSafety = false) {
    if (!project || !token) return;
    const draft = postDrafts.find((d) => d.id === draftId);
    const account = redditAccounts[0];
    if (!draft || !account) return;
    const subreddit = postSubreddit.trim().replace(/^r\//i, "");
    if (subreddit.length < 2) {
      error("Subreddit required", "Enter the subreddit to post into (e.g. r/startups).");
      return;
    }
    setPostingReddit(true);
    try {
      await apiPostToReddit(token, {
        reddit_account_id: account.id,
        project_id: project.id,
        type: "post",
        subreddit,
        title: draft.title,
        content: draft.body,
        ...(overrideSafety ? { override_safety: true } : {}),
      });

      success("Posted to Reddit", "Your post has been published");
      setSafetyBlock(null);
      setShowPostConfirm(false);
      await loadDrafts();
    } catch (err: unknown) {
      // 422 = account-safety guard (warm-up daily cap). Surface the detail and
      // let the user explicitly retry with override_safety.
      if (isApiError(err) && err.status === 422) {
        setSafetyBlock(getErrorMessage(err));
      } else {
        error("Could not post to Reddit", getErrorMessage(err));
      }
    }
    setPostingReddit(false);
  }

  function closePostConfirm() {
    setShowPostConfirm(false);
    setSafetyBlock(null);
  }

  async function handleCreateTrackedLink() {
    if (!token || !project || !linkDraft) return;
    const destination = linkDestination.trim();
    if (!/^https?:\/\//i.test(destination)) {
      error("Invalid URL", "Destination must start with http:// or https://");
      return;
    }
    setCreatingLink(true);
    try {
      const link = await createTrackedLink(token, {
        project_id: project.id,
        destination_url: destination,
        reply_draft_id: linkDraft.id,
        opportunity_id: linkDraft.opportunity_id ?? null,
      });
      const url = shortLinkUrl(link);
      let copied = true;
      try {
        await copyText(url);
      } catch {
        copied = false;
      }
      success(
        copied ? "Tracked link created and copied" : "Tracked link created",
        `${url} — using it is opt-in: Redditors distrust obvious trackers, so only paste it where a link genuinely helps.`
      );
      setLinkDraft(null);
      setLinkDestination("");
    } catch (err: unknown) {
      error("Could not create tracked link", getErrorMessage(err));
    }
    setCreatingLink(false);
  }

  async function handleAmplify(draft: ReplyDraftRow, target: AmplifyTarget) {
    if (!token) return;
    setAmplifyingId(draft.id);
    try {
      const created = await createAmplifyDraft(token, { reply_draft_id: draft.id, target });
      rememberAmplifyDraft(created);
      success(
        target === "x" ? "X thread drafted" : "LinkedIn post drafted",
        "Opening the amplify editor..."
      );
      router.push(`/app/content-studio?amplifyDraft=${created.id}`);
    } catch (err: unknown) {
      error("Could not amplify draft", getErrorMessage(err));
    } finally {
      setAmplifyingId(null);
    }
  }

  async function generatePostDraft() {
    if (!project) {
      return;
    }
    setGeneratingPost(true);
    try {
      const draft = await apiRequest<PostDraft>(
        "/v1/drafts/posts",
        {
          method: "POST",
          body: JSON.stringify({ project_id: project.id }),
        },
        token
      );
      success("Original post drafted");
      setPostDrafts((rows) => [draft, ...rows]);
      openPostDraft(draft);
      setActiveTab("posts");
    } catch (err: unknown) {
      error("Could not generate post draft", getErrorMessage(err));
    }
    setGeneratingPost(false);
  }

  function openReplyDraft(draft: ReplyDraftRow) {
    setSelectedPost(null);
    setSelectedReply(draft);
    setReplyContent(draft.content);
    setThreadOpen(true);
    setRationaleOpen(false);
  }

  function openPostDraft(draft: PostDraft) {
    setSelectedReply(null);
    setSelectedPost(draft);
    setPostTitle(draft.title);
    setPostBody(draft.body);
  }

  useEffect(() => {
    if (!requestedOpportunityId || loading) {
      return;
    }
    if (requestedProjectId && selectedProjectId !== requestedProjectId) {
      return;
    }

    const existingDraft = drafts.find((draft) => draft.opportunity_id === requestedOpportunityId);
    if (existingDraft && handledOpportunityIdRef.current !== requestedOpportunityId) {
      openReplyDraft(existingDraft);
      handledOpportunityIdRef.current = requestedOpportunityId;
    }
  }, [drafts, loading, requestedOpportunityId, requestedProjectId, selectedProjectId]);

  useEffect(() => {
    if (!token || !requestedOpportunityId || loading) {
      return;
    }
    if (requestedProjectId && selectedProjectId !== requestedProjectId) {
      return;
    }
    if (handledOpportunityIdRef.current === requestedOpportunityId) {
      return;
    }
    if (drafts.some((draft) => draft.opportunity_id === requestedOpportunityId)) {
      return;
    }
    if (pendingOpportunityIdRef.current === requestedOpportunityId) {
      return;
    }

    const generateMissingDraft = async () => {
      pendingOpportunityIdRef.current = requestedOpportunityId;
      try {
        const draft = await generateReplyDraft(requestedOpportunityId);
        // Mark as handled either way so we don't keep POSTing if the new
        // draft never surfaces in the next loadDrafts() (e.g. permissions
        // filter it out, backend returns empty list, etc.).
        handledOpportunityIdRef.current = requestedOpportunityId;
        if (draft) {
          await loadDrafts();
        }
      } finally {
        pendingOpportunityIdRef.current = null;
      }
    };

    void generateMissingDraft();
  }, [drafts, generateReplyDraft, loading, requestedOpportunityId, requestedProjectId, selectedProjectId, token]);

  async function saveReplyDraft() {
    if (!selectedReply) {
      return;
    }
    const updated = await persistReplyDraft(selectedReply.id, {
      content: replyContent,
      rationale: selectedReply.rationale || null,
    });
    if (!updated) {
      return;
    }
    setDrafts((rows) => rows.map((row) => (row.id === updated.id ? { ...row, content: updated.content, rationale: updated.rationale || "" } : row)));
    setSelectedReply((current) => (current ? { ...current, content: updated.content, rationale: updated.rationale || "" } : current));
  }

  async function savePostDraft() {
    if (!selectedPost) {
      return;
    }
    const updated = await persistPostDraft(selectedPost.id, {
      title: postTitle,
      body: postBody,
      rationale: selectedPost.rationale,
    });
    if (!updated) {
      return;
    }
    setPostDrafts((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
    setSelectedPost(updated);
  }

  async function markAsPosted(oppId: number) {
    if (await markOpportunityPosted(oppId)) {
      setSelectedReply(null);
      await loadDrafts();
    }
  }

  const totalPublished = postedDrafts.length + publishedPosts.length;

  return (
    <div className="space-y-8">
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <PageHeader
          title="Content Studio"
          description="Manage reply drafts, original posts, and published activity from one workflow."
          actions={
            <Button onClick={generatePostDraft} disabled={generatingPost || !project}>
              {generatingPost && <Loader2 className="h-4 w-4 animate-spin" />}
              New Original Post
            </Button>
          }
          tabs={
            <TabsList>
              <TabsTrigger value="replies">
                Reply Queue
                {drafts.length > 0 && (
                  <Badge variant="secondary" className="ml-1.5">{drafts.length}</Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="posts">
                Original Posts
                {postDrafts.length > 0 && (
                  <Badge variant="secondary" className="ml-1.5">{postDrafts.length}</Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="published">
                Published
                {totalPublished > 0 && (
                  <Badge variant="secondary" className="ml-1.5">{totalPublished}</Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="templates">Templates</TabsTrigger>
            </TabsList>
          }
        />

        {loading && (
          <div className="grid grid-cols-1 gap-4">
            {[1, 2, 3].map((i) => (
              <Card key={i}>
                <CardContent className="py-4">
                  <div className="flex items-center gap-4">
                    <Skeleton className="h-10 w-10 rounded-full" />
                    <div className="flex-1 space-y-2">
                      <Skeleton className="h-4 w-3/5" />
                      <Skeleton className="h-3 w-4/5" />
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
        {/* Replies Tab */}
        {!loading && (
          <TabsContent value="replies">
          {drafts.length === 0 ? (
            <EmptyState
              icon={MessageSquare}
              title="No reply drafts yet"
              description="Generate response drafts from Engagement Radar. They will appear here for review, revision, and manual publishing."
              action={{
                label: "Open Engagement Radar",
                onClick: () => router.push("/app/discovery"),
              }}
            />
          ) : (
            <div className="space-y-2">
              {drafts.map((draft) => (
                <Card
                  key={draft.id}
                  className="cursor-pointer transition-colors hover:bg-accent/50"
                  onClick={() => openReplyDraft(draft)}
                >
                  <CardContent className="flex items-center gap-4 py-4">
                    {/* Left section */}
                    <div className="flex items-center gap-2 shrink-0">
                      <PlatformIcon platform={draft.platform || "reddit"} />
                      {draft.opportunity_subreddit && (
                        <Badge variant="outline">{sourceLabel({ platform: draft.platform, subreddit_name: draft.platform === "reddit" || !draft.platform ? draft.opportunity_subreddit : undefined, source_name: draft.opportunity_subreddit })}</Badge>
                      )}
                      <Badge variant="secondary">v{draft.version}</Badge>
                    </div>

                    {/* Center section */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {draft.opportunity_title || "Reply Draft"}
                      </p>
                      <p className="text-xs text-muted-foreground truncate">
                        {draft.content.substring(0, 100)}{draft.content.length > 100 ? "..." : ""}
                      </p>
                    </div>

                    {/* Right section */}
                    <div className="flex items-center gap-2 shrink-0">
                      {draft.score != null && <ScoreBadge score={draft.score} />}
                      <DropdownMenu>
                        <DropdownMenuTrigger
                          render={
                            <Button variant="ghost" size="icon-xs">
                              <MoreHorizontal />
                            </Button>
                          }
                          onClick={(e: React.MouseEvent) => e.stopPropagation()}
                        />
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onClick={(e: React.MouseEvent) => {
                              e.stopPropagation();
                              copyToClipboard(draft.content);
                            }}
                          >
                            <Copy /> Copy
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={(e: React.MouseEvent) => {
                              e.stopPropagation();
                              openReplyDraft(draft);
                            }}
                          >
                            <Pencil /> Edit
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onClick={(e: React.MouseEvent) => {
                              e.stopPropagation();
                              setLinkDestination("");
                              setLinkDraft(draft);
                            }}
                          >
                            <Link2 /> Create tracked link
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            disabled={amplifyingId === draft.id}
                            onClick={(e: React.MouseEvent) => {
                              e.stopPropagation();
                              void handleAmplify(draft, "x");
                            }}
                          >
                            <Megaphone /> Amplify to X thread
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            disabled={amplifyingId === draft.id}
                            onClick={(e: React.MouseEvent) => {
                              e.stopPropagation();
                              void handleAmplify(draft, "linkedin");
                            }}
                          >
                            <Megaphone /> Amplify to LinkedIn
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onClick={(e: React.MouseEvent) => {
                              e.stopPropagation();
                              void markAsPosted(draft.opportunity_id);
                            }}
                          >
                            <CheckCircle /> Mark as Posted
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      )}

      {/* Posts Tab */}
      {!loading && (
        <TabsContent value="posts">
          {postDrafts.length === 0 ? (
            <EmptyState
              icon={FileEdit}
              title="No original post drafts yet"
              description="Use the studio to draft community-native posts inspired by Quora-style answers, Reddit posts, or educational updates."
              action={{
                label: "Generate First Post",
                onClick: generatePostDraft,
              }}
            />
          ) : (
            <div className="space-y-2">
              {postDrafts.map((draft) => (
                <Card
                  key={draft.id}
                  className="cursor-pointer transition-colors hover:bg-accent/50"
                  onClick={() => openPostDraft(draft)}
                >
                  <CardContent className="flex items-center gap-4 py-4">
                    {/* Left section */}
                    <div className="flex items-center gap-2 shrink-0">
                      <PlatformIcon platform="reddit" />
                      <Badge variant="secondary">Original Post</Badge>
                      <Badge variant="outline">v{draft.version}</Badge>
                    </div>

                    {/* Center section */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{draft.title}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {draft.body.substring(0, 100)}{draft.body.length > 100 ? "..." : ""}
                      </p>
                    </div>

                    {/* Right section */}
                    <div className="flex items-center gap-2 shrink-0">
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={(event) => {
                          event.stopPropagation();
                          copyToClipboard(`${draft.title}\n\n${draft.body}`);
                        }}
                      >
                        <Copy className="h-3 w-3" /> Copy
                      </Button>
                      <Button
                        size="xs"
                        onClick={(event) => {
                          event.stopPropagation();
                          setPostingDraftId(draft.id);
                          setShowPostConfirm(true);
                        }}
                      >
                        Post to Reddit
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      )}

      {/* Published Tab */}
      {!loading && (
        <TabsContent value="published">
          {postedDrafts.length === 0 && publishedPosts.length === 0 ? (
            <EmptyState
              icon={CheckCircle}
              title="No published content yet"
              description="Your published replies and posts will appear here."
            />
          ) : (
            <div className="space-y-2">
              {postedDrafts.map((draft) => (
                <Card key={`reply-${draft.id}`}>
                  <CardContent className="flex items-center gap-4 py-4">
                    <div className="flex items-center gap-2 shrink-0">
                      <PlatformIcon platform={draft.platform || "reddit"} />
                      <StatusBadge variant="success">Posted</StatusBadge>
                      {draft.opportunity_subreddit && (
                        <Badge variant="outline">{sourceLabel({ platform: draft.platform, subreddit_name: draft.platform === "reddit" || !draft.platform ? draft.opportunity_subreddit : undefined, source_name: draft.opportunity_subreddit })}</Badge>
                      )}
                    </div>

                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {draft.opportunity_title || "Published Reply"}
                      </p>
                      <p className="text-xs text-muted-foreground truncate">
                        {draft.content.substring(0, 100)}{draft.content.length > 100 ? "..." : ""}
                      </p>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      {draft.permalink && (
                        <a
                          href={redditUrl(draft.permalink)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <Button variant="outline" size="xs">
                            <ExternalLink className="h-3 w-3" /> View Thread
                          </Button>
                        </a>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
              {publishedPosts.map((post) => (
                <Card key={`post-${post.id}`}>
                  <CardContent className="flex items-center gap-4 py-4">
                    <div className="flex items-center gap-2 shrink-0">
                      <PlatformIcon platform="reddit" />
                      <StatusBadge variant="success">{post.status}</StatusBadge>
                      <Badge variant="outline">{post.subreddit?.startsWith("r/") ? post.subreddit : `r/${post.subreddit}`}</Badge>
                    </div>

                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">Original Post</p>
                      <div className="flex gap-3 text-xs text-muted-foreground mt-0.5">
                        <span>{new Date(post.post_date).toLocaleDateString()}</span>
                        {post.upvotes !== undefined && <span>{post.upvotes} upvotes</span>}
                        {post.comments !== undefined && <span>{post.comments} comments</span>}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      {post.permalink && (
                        <a href={redditUrl(post.permalink)} target="_blank" rel="noopener noreferrer">
                          <Button variant="outline" size="xs">
                            <ExternalLink className="h-3 w-3" /> View on Reddit
                          </Button>
                        </a>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      )}

      {/* Templates Tab */}
      {!loading && (
        <TabsContent value="templates">
          <Card>
            <CardContent className="flex items-center gap-4 py-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted shrink-0">
                <LayoutTemplate className="h-5 w-5 text-muted-foreground" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium">Prompt Templates</p>
                <p className="text-xs text-muted-foreground">
                  Manage your prompt templates for reply and post generation.
                </p>
              </div>
              <Link href="/app/prompts">
                <Button variant="outline" size="sm">
                  Open Templates <ArrowRight className="h-3.5 w-3.5" />
                </Button>
              </Link>
            </CardContent>
          </Card>
        </TabsContent>
        )}
      </Tabs>

      {/* Reply Draft SheetPanel */}
      <SheetPanel
        title="Reply Draft"
        description="Review and edit your reply before publishing."
        open={!!selectedReply}
        onOpenChange={(open) => !open && setSelectedReply(null)}
        width="lg"
        footer={
          <div className="flex gap-2 w-full">
            <Button onClick={() => void saveReplyDraft()} disabled={savingReply} className="flex-1">
              {savingReply && <Loader2 className="h-4 w-4 animate-spin" />}
              Save
            </Button>
            <Button variant="outline" onClick={() => copyToClipboard(replyContent)}>
              <Copy className="h-3.5 w-3.5" /> Copy
            </Button>
            {selectedReply?.permalink && (
              <Button
                variant="outline"
                onClick={() => copyAndOpen(replyContent, selectedReply.permalink || "", selectedReply.platform)}
              >
                Copy &amp; Open Post
              </Button>
            )}
            {selectedReply && (
              <Button variant="outline" onClick={() => void markAsPosted(selectedReply.opportunity_id)}>
                <CheckCircle className="h-3.5 w-3.5" /> Mark as Posted
              </Button>
            )}
          </div>
        }
      >
        {selectedReply && (
          <div className="space-y-4">
            {/* Original Reddit post context — always visible so the reviewer
                can see exactly what they're replying to. */}
            {(selectedReply.opportunity_title ||
              selectedReply.opportunity_subreddit ||
              selectedReply.body_excerpt ||
              selectedReply.permalink) && (
              <div className="rounded-lg border bg-muted/40 p-4 space-y-3">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2 flex-wrap">
                    {selectedReply.opportunity_subreddit && (
                      <Badge variant="secondary" className="font-mono text-xs">
                        {sourceLabel({ platform: selectedReply.platform, subreddit_name: selectedReply.platform === "reddit" || !selectedReply.platform ? selectedReply.opportunity_subreddit : undefined, source_name: selectedReply.opportunity_subreddit })}
                      </Badge>
                    )}
                    {typeof selectedReply.score === "number" && (
                      <ScoreBadge score={selectedReply.score} />
                    )}
                  </div>
                  {selectedReply.permalink && (
                    <a
                      href={redditUrl(selectedReply.permalink)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs font-medium text-primary hover:underline inline-flex items-center gap-1"
                    >
                      View on Reddit <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </div>
                {selectedReply.opportunity_title && (
                  <h3 className="text-sm font-semibold leading-snug">
                    {selectedReply.opportunity_title}
                  </h3>
                )}
                {selectedReply.body_excerpt && (
                  <div>
                    <div
                      className={cn(
                        "text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap",
                        !threadOpen && "line-clamp-4"
                      )}
                    >
                      {selectedReply.body_excerpt}
                    </div>
                    {selectedReply.body_excerpt.length > 280 && (
                      <button
                        type="button"
                        onClick={() => setThreadOpen((prev) => !prev)}
                        className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                      >
                        <ChevronDown
                          className={cn(
                            "h-3.5 w-3.5 transition-transform",
                            !threadOpen && "-rotate-90"
                          )}
                        />
                        {threadOpen ? "Show less" : "Show full post"}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Reply content */}
            <div className="space-y-2">
              <Label>Reply Content</Label>
              <Textarea
                rows={12}
                value={replyContent}
                onChange={(event) => setReplyContent(event.target.value)}
                className="text-sm leading-relaxed"
              />
              <p className="text-xs text-muted-foreground">{replyContent.length} characters</p>
            </div>

            {/* Rationale collapsible */}
            {selectedReply.rationale && (
              <Collapsible open={rationaleOpen} onOpenChange={setRationaleOpen}>
                <CollapsibleTrigger className="flex items-center gap-1.5 text-sm font-medium w-full">
                  <ChevronDown
                    className={cn(
                      "h-4 w-4 transition-transform",
                      !rationaleOpen && "-rotate-90"
                    )}
                  />
                  Why this response works
                </CollapsibleTrigger>
                <CollapsibleContent className="mt-2">
                  <div className="rounded-xl bg-muted p-5">
                    <p className="text-sm text-muted-foreground">{selectedReply.rationale}</p>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            )}
          </div>
        )}
      </SheetPanel>

      {/* Post Draft SheetPanel */}
      <SheetPanel
        title="Original Post Draft"
        description="Edit and manage your original post draft."
        open={!!selectedPost}
        onOpenChange={(open) => !open && setSelectedPost(null)}
        width="lg"
        footer={
          <div className="flex gap-2 w-full">
            <Button onClick={() => void savePostDraft()} disabled={savingPost} className="flex-1">
              {savingPost && <Loader2 className="h-4 w-4 animate-spin" />}
              Save
            </Button>
            <Button variant="outline" onClick={() => copyToClipboard(`${postTitle}\n\n${postBody}`)}>
              <Copy className="h-3.5 w-3.5" /> Copy
            </Button>
            <Button
              onClick={() => {
                setPostingDraftId(selectedPost?.id || null);
                setShowPostConfirm(true);
              }}
            >
              Post to Reddit
            </Button>
          </div>
        }
      >
        {selectedPost && (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Title</Label>
              <Input
                type="text"
                value={postTitle}
                onChange={(event) => setPostTitle(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Post Body</Label>
              <Textarea
                rows={14}
                value={postBody}
                onChange={(event) => setPostBody(event.target.value)}
                className="text-sm leading-relaxed"
              />
              <p className="text-xs text-muted-foreground">{postBody.length} characters</p>
            </div>
            {selectedPost.rationale && (
              <div className="rounded-xl bg-muted p-5">
                <h4 className="text-sm font-medium">Why this post works</h4>
                <p className="mt-1 text-sm text-muted-foreground">
                  {selectedPost.rationale || "Educational, useful, and structured for community-native publishing."}
                </p>
              </div>
            )}
          </div>
        )}
      </SheetPanel>

      {/* Post to Reddit Confirm Dialog */}
      <Dialog open={showPostConfirm} onOpenChange={(open) => !open && closePostConfirm()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Post to Reddit</DialogTitle>
            <DialogDescription>Review your post before publishing to Reddit.</DialogDescription>
          </DialogHeader>
          {postingDraftId && postDrafts.find((d) => d.id === postingDraftId) && (
            <div className="space-y-4">
              <div className="rounded-xl bg-muted p-5">
                <strong className="block mb-2">
                  {postDrafts.find((d) => d.id === postingDraftId)?.title}
                </strong>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {postDrafts.find((d) => d.id === postingDraftId)?.body.substring(0, 200)}...
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="post-subreddit">Target Subreddit</Label>
                <Input
                  id="post-subreddit"
                  type="text"
                  placeholder="e.g., r/community"
                  value={postSubreddit}
                  onChange={(event) => setPostSubreddit(event.target.value)}
                />
              </div>
              <div className="rounded-lg bg-muted p-3">
                <Label>Connected Reddit Account</Label>
                <p className="mt-1.5 text-sm">
                  {redditAccounts.length > 0
                    ? `@${redditAccounts[0].username}`
                    : <a href="/app/settings" className="text-primary hover:underline">Connect Reddit Account</a>}
                </p>
              </div>
              {safetyBlock && (
                <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                  <p className="text-xs leading-relaxed text-destructive">{safetyBlock}</p>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={closePostConfirm}>
              Cancel
            </Button>
            {safetyBlock ? (
              <Button
                variant="destructive"
                disabled={postingReddit}
                onClick={() => void postToReddit(postingDraftId!, true)}
              >
                {postingReddit && <Loader2 className="h-4 w-4 animate-spin" />}
                Post anyway (override)
              </Button>
            ) : (
              <Button
                disabled={postingReddit || redditAccounts.length === 0 || postSubreddit.trim().length < 2}
                onClick={() => void postToReddit(postingDraftId!)}
              >
                {postingReddit && <Loader2 className="h-4 w-4 animate-spin" />}
                Post Now
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create Tracked Link Dialog */}
      <Dialog
        open={!!linkDraft}
        onOpenChange={(open) => {
          if (!open) {
            setLinkDraft(null);
            setLinkDestination("");
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Create tracked link</DialogTitle>
            <DialogDescription>
              Generates a short URL that attributes clicks back to this reply. Adding it to your reply is
              opt-in — Redditors distrust obvious trackers, so only include it where a link genuinely helps.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="link-destination">Destination URL</Label>
            <Input
              id="link-destination"
              type="url"
              placeholder="https://yoursite.com/pricing"
              value={linkDestination}
              onChange={(event) => setLinkDestination(event.target.value)}
            />
            {linkDraft?.opportunity_title && (
              <p className="text-xs text-muted-foreground truncate">
                Attributed to: {linkDraft.opportunity_title}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setLinkDraft(null);
                setLinkDestination("");
              }}
            >
              Cancel
            </Button>
            <Button
              disabled={creatingLink || linkDestination.trim().length === 0}
              onClick={() => void handleCreateTrackedLink()}
            >
              {creatingLink && <Loader2 className="h-4 w-4 animate-spin" />}
              <Link2 className="h-3.5 w-3.5" /> Create &amp; copy short URL
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
