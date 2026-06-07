"use client";

import { useEffect, useState } from "react";
import { Loader2, RefreshCw, Check, X } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { useToast } from "@/stores/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import {
  getCompanies,
  getCompanyKeywords,
  generateCompanyKeywords,
  updateCompany,
  type CompanyProfile,
  type BrandKeyword,
} from "@/lib/api/company";

export default function BrandBrainPage() {
  const { token } = useAuth();
  const { success, error } = useToast();
  const [loading, setLoading] = useState(true);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [keywords, setKeywords] = useState<BrandKeyword[]>([]);
  const [regenerating, setRegenerating] = useState(false);
  const [activeTab, setActiveTab] = useState("intelligence");

  useEffect(() => {
    if (!token) return;
    void loadAll();
  }, [token]);

  async function loadAll() {
    setLoading(true);
    try {
      const companies = await getCompanies(token!);
      const active = companies.find((c) => c.is_active) ?? companies[0] ?? null;
      setCompany(active);
      if (active) {
        const kws = await getCompanyKeywords(token!, active.id);
        setKeywords(kws);
      }
    } catch (err) {
      error("Failed to load", err instanceof Error ? err.message : "Unknown error");
    }
    setLoading(false);
  }

  async function handleRegenerate() {
    if (!token || !company?.id) return;
    setRegenerating(true);
    try {
      await generateCompanyKeywords(token, company.id);
      success("Keywords regenerated", "Refreshing list...");
      await loadAll();
    } catch (err) {
      error("Failed to regenerate", err instanceof Error ? err.message : "Unknown error");
    }
    setRegenerating(false);
  }

  function toggleKeyword(keyword: BrandKeyword) {
    setKeywords((prev) =>
      prev.map((k) => (k.id === keyword.id ? { ...k, is_enabled: !k.is_enabled } : k))
    );
  }

  async function saveCompanyField(field: keyof CompanyProfile, value: unknown) {
    if (!token || !company?.id) return;
    try {
      const updated = await updateCompany(token, company.id, { [field]: value });
      setCompany(updated);
      success("Updated");
    } catch (err) {
      error("Update failed", err instanceof Error ? err.message : "Unknown error");
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full rounded-lg" />
      </div>
    );
  }

  if (!company) {
    return (
      <div className="space-y-6">
        <PageHeader title="Brand Brain" />
        <EmptyState
          icon={RefreshCw}
          title="No company found"
          description="Set up your company profile first to unlock Brand Brain."
        />
      </div>
    );
  }

  const editableSections = [
    { label: "Summary", key: "extracted_summary" as const, value: company.extracted_summary },
    { label: "ICP", key: "target_audience" as const, value: company.target_audience },
    { label: "Key Benefits", key: "benefits" as const, value: company.benefits ?? "" },
    { label: "Pain Points Solved", key: "pain_points" as const, value: company.pain_points ?? "" },
    { label: "Competitors", key: "competitors" as const, value: company.competitors ?? "" },
    { label: "Industry", key: "category" as const, value: company.category },
    { label: "Tone of Voice", key: "brand_voice" as const, value: company.brand_voice },
  ];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Brand Brain"
        actions={
          <Button variant="secondary" onClick={handleRegenerate} disabled={regenerating}>
            {regenerating && <Loader2 className="h-4 w-4 animate-spin" />}
            <RefreshCw className="h-4 w-4 mr-1" />
            Regenerate Keywords
          </Button>
        }
      />

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="intelligence">Intelligence</TabsTrigger>
          <TabsTrigger value="keywords">Keyword Universe</TabsTrigger>
        </TabsList>

        <TabsContent value="intelligence" className="space-y-6">
          {editableSections.map((section) => (
            <Card key={section.label}>
              <CardHeader>
                <CardTitle className="text-base">{section.label}</CardTitle>
              </CardHeader>
              <CardContent>
                <InlineEdit
                  value={section.value ?? ""}
                  onSave={(val) => {
                    if (Array.isArray(company[section.key])) {
                      saveCompanyField(
                        section.key,
                        val.split(",").map((s) => s.trim()).filter(Boolean)
                      );
                    } else {
                      saveCompanyField(section.key, val);
                    }
                  }}
                />
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="keywords">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Keyword Universe</CardTitle>
            </CardHeader>
            <CardContent>
              {keywords.length === 0 ? (
                <EmptyState
                  icon={RefreshCw}
                  title="No keywords yet"
                  description="Generate keywords to see your keyword universe."
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-muted-foreground">
                        <th className="text-left py-2 px-3">Keyword</th>
                        <th className="text-left py-2 px-3">Type</th>
                        <th className="text-left py-2 px-3">Weight</th>
                        <th className="text-left py-2 px-3">Matches</th>
                        <th className="text-left py-2 px-3">Enabled</th>
                      </tr>
                    </thead>
                    <tbody>
                      {keywords.map((kw) => (
                        <tr key={kw.id} className="border-b last:border-b-0 hover:bg-muted/50">
                          <td className="py-2 px-3 font-medium">{kw.keyword}</td>
                          <td className="py-2 px-3">
                            <Badge variant="secondary">{kw.type}</Badge>
                          </td>
                          <td className="py-2 px-3">{kw.weight}</td>
                          <td className="py-2 px-3">{kw.times_matched}</td>
                          <td className="py-2 px-3">
                            <button
                              type="button"
                              onClick={() => toggleKeyword(kw)}
                              className="inline-flex items-center justify-center h-6 w-6 rounded-md border hover:bg-muted transition-colors"
                              title={kw.is_enabled ? "Disable" : "Enable"}
                            >
                              {kw.is_enabled ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function InlineEdit({ value, onSave }: { value: string; onSave: (val: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(value);

  return (
    <div className="flex items-start gap-2">
      {editing ? (
        <div className="flex-1 flex items-center gap-2">
          <Input
            className="flex-1"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                onSave(text);
                setEditing(false);
              }
            }}
          />
          <Button size="sm" onClick={() => { onSave(text); setEditing(false); }}>
            Save
          </Button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="text-left text-sm text-muted-foreground hover:text-foreground cursor-text flex-1"
        >
          {value || <span className="italic opacity-60">Click to edit...</span>}
        </button>
      )}
    </div>
  );
}
