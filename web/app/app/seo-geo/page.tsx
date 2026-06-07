"use client";

import { useState } from "react";
import { Search } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { PageHeader } from "@/components/shared/page-header";
import { StatusBadge } from "@/components/shared/status-badge";

const seoIssues = [
  { severity: "error" as const, url: "/blog/old-post", fix: "Update meta description and add canonical tag" },
  { severity: "warning" as const, url: "/pricing", fix: "Add structured data for pricing" },
  { severity: "success" as const, url: "/", fix: "Homepage schema is correct" },
];

const geoGaps = [
  { area: "AI Overview citations", readiness: 45, action: "Add FAQ schema to top 10 pages" },
  { area: "Featured snippets", readiness: 62, action: "Optimize headings with question format" },
];

const keywordGaps = [
  { keyword: "best ai reply tool", topic: "Comparison guide", volume: "1.2K" },
  { keyword: "reddit automation", topic: "How-to article", volume: "800" },
];

export default function SeoGeoPage() {
  const [activeTab, setActiveTab] = useState("seo");

  return (
    <div className="space-y-6">
      <PageHeader title="SEO / GEO" description="Audit and optimize for search and generative engine visibility." />

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="seo">SEO Audit</TabsTrigger>
          <TabsTrigger value="geo">GEO Visibility</TabsTrigger>
          <TabsTrigger value="gaps">Keyword Gaps</TabsTrigger>
        </TabsList>

        <TabsContent value="seo" className="space-y-4">
          {seoIssues.map((issue, i) => (
            <Card key={i}>
              <CardContent className="p-4 flex items-center gap-4">
                <StatusBadge variant={issue.severity} dot>{issue.severity}</StatusBadge>
                <div className="flex-1">
                  <div className="text-sm font-medium">{issue.url}</div>
                  <div className="text-xs text-muted-foreground">{issue.fix}</div>
                </div>
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="geo" className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {geoGaps.map((gap, i) => (
              <Card key={i}>
                <CardHeader>
                  <CardTitle className="text-base">{gap.area}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                      <div className="h-full bg-primary rounded-full" style={{ width: `${gap.readiness}%` }} />
                    </div>
                    <span className="text-xs font-medium">{gap.readiness}%</span>
                  </div>
                  <p className="text-xs text-muted-foreground">{gap.action}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="gaps" className="space-y-4">
          {keywordGaps.map((gap, i) => (
            <Card key={i}>
              <CardContent className="p-4 flex items-center gap-4">
                <Search className="h-4 w-4 text-muted-foreground shrink-0" />
                <div className="flex-1">
                  <div className="text-sm font-medium">{gap.keyword}</div>
                  <div className="text-xs text-muted-foreground">Suggested topic: {gap.topic}</div>
                </div>
                <Badge variant="secondary" className="text-xs">{gap.volume} vol</Badge>
              </CardContent>
            </Card>
          ))}
        </TabsContent>
      </Tabs>
    </div>
  );
}
