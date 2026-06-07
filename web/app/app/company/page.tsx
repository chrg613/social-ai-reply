"use client";

import { FormEvent, useEffect, useState } from "react";
import { Loader2, Globe, Users, Target, Sparkles, Save, Zap } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { useToast } from "@/stores/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import {
  getCompanies,
  createCompany,
  updateCompany,
  analyzeCompanyWebsite,
  type CompanyProfile,
} from "@/lib/api/company";
import { startAutoPipelineV2 } from "@/lib/api/auto-pipeline-v2";

export default function CompanyPage() {
  const { token } = useAuth();
  const { success, error } = useToast();
  const [loading, setLoading] = useState(true);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [autoUrl, setAutoUrl] = useState("");
  const [isAutoRunning, setIsAutoRunning] = useState(false);

  useEffect(() => {
    if (!token) return;
    void loadCompany();
  }, [token]);

  async function loadCompany() {
    setLoading(true);
    try {
      const companies = await getCompanies(token!);
      const active = companies.find((c) => c.is_active) ?? companies[0] ?? null;
      setCompany(active);
    } catch (err) {
      error("Failed to load company", err instanceof Error ? err.message : "Unknown error");
    }
    setLoading(false);
  }

  function buildPayload(): Record<string, unknown> {
    if (!company) return {};
    // Only send fields the backend expects (strip id, workspace_id, timestamps, etc.)
    const {
      id: _id,
      workspace_id: _wid,
      created_at: _ca,
      updated_at: _ua,
      extracted_summary: _es,
      extracted_keywords: _ek,
      extracted_pain_points: _epp,
      extracted_competitors: _ec,
      is_active: _ia,
      ...payload
    } = company;
    return payload;
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !company) return;
    setIsSaving(true);
    try {
      const payload = buildPayload();
      if (company.id) {
        const updated = await updateCompany(token, company.id, payload);
        setCompany(updated);
        success("Saved", "Company profile updated.");
      } else {
        const created = await createCompany(token, payload);
        setCompany(created);
        success("Created", "Company profile created.");
      }
    } catch (err) {
      error("Save failed", err instanceof Error ? err.message : "Unknown error");
    }
    setIsSaving(false);
  }

  async function handleAnalyze() {
    if (!token || !company?.id) return;
    setIsAnalyzing(true);
    try {
      const res = await analyzeCompanyWebsite(token, company.id);
      success("Analysis started", `Run ID: ${res.run_id}`);
    } catch (err) {
      error("Analysis failed", err instanceof Error ? err.message : "Unknown error");
    }
    setIsAnalyzing(false);
  }

  async function handleAutoPipeline(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !autoUrl.trim()) return;
    setIsAutoRunning(true);
    try {
      const res = await startAutoPipelineV2(token, { website_url: autoUrl.trim() });
      success("Auto Pipeline Started", res.message);
      // Reload company list to show the newly created one
      await loadCompany();
    } catch (err) {
      error("Auto Pipeline failed", err instanceof Error ? err.message : "Unknown error");
    }
    setIsAutoRunning(false);
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Skeleton className="h-32 w-full rounded-lg" />
          <Skeleton className="h-32 w-full rounded-lg" />
        </div>
      </div>
    );
  }

  if (!company) {
    return (
      <div className="space-y-8">
        <PageHeader title="Company Setup" />

        <Card className="border-dashed border-primary/30 bg-primary/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Zap className="h-4 w-4 text-primary" />
              Quick Start — Auto Pipeline
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleAutoPipeline} className="flex flex-col sm:flex-row gap-3">
              <Input
                type="url"
                placeholder="https://your-company.com"
                value={autoUrl}
                onChange={(e) => setAutoUrl(e.target.value)}
                className="flex-1"
                required
              />
              <Button type="submit" disabled={isAutoRunning} className="shrink-0">
                {isAutoRunning && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
                <Zap className="h-4 w-4 mr-1" />
                {isAutoRunning ? "Running..." : "Auto Setup"}
              </Button>
            </form>
            <p className="text-xs text-muted-foreground mt-2">
              Paste your website URL and we&apos;ll automatically analyze it, generate keywords, and run all 9 agents.
            </p>
          </CardContent>
        </Card>

        <EmptyState
          icon={Globe}
          title="Or create manually"
          description="Fill out the form below to set up your company profile manually."
          action={{
            label: "Create Company",
            onClick: () =>
              setCompany({
                id: 0,
                workspace_id: 0,
                name: "",
                website_url: null,
                description: null,
                category: null,
                target_audience: null,
                geography: null,
                language: "en",
                features: "",
                benefits: "",
                pain_points: "",
                competitors: "",
                brand_voice: null,
                preferred_cta: null,
                extracted_summary: null,
                extracted_keywords: "",
                extracted_pain_points: "",
                extracted_competitors: "",
                is_active: true,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              }),
          }}
        />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Company Setup"
        actions={
          <Button variant="secondary" onClick={handleAnalyze} disabled={!company.website_url || isAnalyzing}>
            {isAnalyzing && <Loader2 className="h-4 w-4 animate-spin" />}
            <Sparkles className="h-4 w-4 mr-1" />
            Analyze Website
          </Button>
        }
      />

      <Card className="border-dashed border-primary/30 bg-primary/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Zap className="h-4 w-4 text-primary" />
            Quick Start — Auto Pipeline
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleAutoPipeline} className="flex flex-col sm:flex-row gap-3">
            <Input
              type="url"
              placeholder="https://your-company.com"
              value={autoUrl}
              onChange={(e) => setAutoUrl(e.target.value)}
              className="flex-1"
              required
            />
            <Button type="submit" disabled={isAutoRunning} className="shrink-0">
              {isAutoRunning && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              <Zap className="h-4 w-4 mr-1" />
              {isAutoRunning ? "Running..." : "Auto Setup"}
            </Button>
          </form>
          <p className="text-xs text-muted-foreground mt-2">
            Paste your website URL and we&apos;ll automatically analyze it, generate keywords, and run all 9 agents.
          </p>
        </CardContent>
      </Card>

      <form onSubmit={handleSave}>
        <div className="grid gap-8">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Globe className="h-4 w-4 text-muted-foreground" />
                Identity
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="name">Company Name</Label>
                  <Input
                    id="name"
                    value={company.name}
                    onChange={(e) => setCompany({ ...company, name: e.target.value })}
                    placeholder="Acme Inc."
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="website_url">Website URL</Label>
                  <Input
                    id="website_url"
                    type="url"
                    value={company.website_url ?? ""}
                    onChange={(e) => setCompany({ ...company, website_url: e.target.value })}
                    placeholder="https://example.com"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={company.description ?? ""}
                  onChange={(e) => setCompany({ ...company, description: e.target.value })}
                  placeholder="What does your company do?"
                  rows={3}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Users className="h-4 w-4 text-muted-foreground" />
                Audience & Market
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="category">Category</Label>
                  <Input
                    id="category"
                    value={company.category ?? ""}
                    onChange={(e) => setCompany({ ...company, category: e.target.value })}
                    placeholder="e.g. SaaS"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="target_audience">Target Audience</Label>
                  <Input
                    id="target_audience"
                    value={company.target_audience ?? ""}
                    onChange={(e) => setCompany({ ...company, target_audience: e.target.value })}
                    placeholder="e.g. Marketing teams"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="geography">Geography</Label>
                  <Input
                    id="geography"
                    value={company.geography ?? ""}
                    onChange={(e) => setCompany({ ...company, geography: e.target.value })}
                    placeholder="e.g. US, UK"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="language">Language</Label>
                  <Input
                    id="language"
                    value={company.language}
                    onChange={(e) => setCompany({ ...company, language: e.target.value })}
                    placeholder="en"
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Target className="h-4 w-4 text-muted-foreground" />
                Product & Positioning
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="features">Features (comma-separated)</Label>
                  <Input
                    id="features"
                    value={company.features ?? ""}
                    onChange={(e) => setCompany({ ...company, features: e.target.value })} 
                    placeholder="Feature A, Feature B"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="benefits">Benefits (comma-separated)</Label>
                  <Input
                    id="benefits"
                    value={company.benefits ?? ""}
                    onChange={(e) => setCompany({ ...company, benefits: e.target.value })} 
                    placeholder="Saves time, reduces cost"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="pain_points">Pain Points (comma-separated)</Label>
                  <Input
                    id="pain_points"
                    value={company.pain_points ?? ""}
                    onChange={(e) => setCompany({ ...company, pain_points: e.target.value })} 
                    placeholder="Slow workflows, high fees"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="competitors">Competitors (comma-separated)</Label>
                  <Input
                    id="competitors"
                    value={company.competitors ?? ""}
                    onChange={(e) => setCompany({ ...company, competitors: e.target.value })} 
                    placeholder="Competitor A, Competitor B"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="brand_voice">Brand Voice</Label>
                  <Textarea
                    id="brand_voice"
                    value={company.brand_voice ?? ""}
                    onChange={(e) => setCompany({ ...company, brand_voice: e.target.value })}
                    placeholder="Professional, witty, empathetic..."
                    rows={2}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="preferred_cta">Preferred CTA</Label>
                  <Input
                    id="preferred_cta"
                    value={company.preferred_cta ?? ""}
                    onChange={(e) => setCompany({ ...company, preferred_cta: e.target.value })}
                    placeholder="Book a demo, Start free trial"
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          {company.extracted_summary && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Extracted Intelligence</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="rounded-xl border bg-card p-4">
                  <strong className="text-sm font-semibold">Summary</strong>
                  <p className="text-sm text-muted-foreground mt-1">{company.extracted_summary}</p>
                </div>
                {company.extracted_keywords && (
                  <div className="rounded-xl border bg-card p-4">
                    <strong className="text-sm font-semibold">Keywords</strong>
                    <p className="text-sm text-muted-foreground mt-1">{company.extracted_keywords}</p>
                  </div>
                )}
                {company.extracted_pain_points && (
                  <div className="rounded-xl border bg-card p-4">
                    <strong className="text-sm font-semibold">Pain Points</strong>
                    <p className="text-sm text-muted-foreground mt-1">{company.extracted_pain_points}</p>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={isSaving}>
              {isSaving && <Loader2 className="h-4 w-4 animate-spin" />}
              <Save className="h-4 w-4 mr-1" />
              Save Company
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}
