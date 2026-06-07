"use client";

import { useState } from "react";
import { Copy, Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { PageHeader } from "@/components/shared/page-header";

const articleBriefs = [
  { title: "How to Use AI for Reddit Outreach", keyword: "ai reddit outreach", outline: "1. Why Reddit matters\n2. Choosing subreddits\n3. Crafting replies..." },
  { title: "GEO vs SEO: What Changed", keyword: "generative engine optimization", outline: "1. Traditional SEO\n2. AI overviews\n3. Visibility tactics..." },
];

const xPosts = [
  { text: "Reddit isn't just for memes. It's where your ICP asks questions before they buy. Here's how to show up without being salesy.", type: "Thread starter" },
  { text: "The best marketing doesn't feel like marketing. It feels like a helpful reply at the right moment.", type: "Stand-alone" },
];

const linkedInPosts = [
  { text: "We analyzed 10,000 Reddit threads to find the #1 thing buyers complain about before switching tools. Spoiler: it's not price.", type: "Story" },
  { text: "3 signals that someone is in 'comparison mode' on Reddit — and how to reply without breaking community rules.", type: "Listicle" },
];

const ugcBriefs = [
  { hook: "POV: You finally found a tool that doesn't spam Reddit...", scenes: 4, duration: "45s" },
  { hook: "How I got 300 qualified leads from one Reddit comment.", scenes: 5, duration: "60s" },
];

export default function ContentStudioPage() {
  const [activeTab, setActiveTab] = useState("articles");

  return (
    <div className="space-y-6">
      <PageHeader title="Content Studio" description="Generated content briefs and posts." />

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="articles">Article Briefs</TabsTrigger>
          <TabsTrigger value="x">X Posts</TabsTrigger>
          <TabsTrigger value="linkedin">LinkedIn Posts</TabsTrigger>
          <TabsTrigger value="ugc">UGC Briefs</TabsTrigger>
        </TabsList>

        <TabsContent value="articles" className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {articleBriefs.map((item, i) => (
            <Card key={i}>
              <CardHeader>
                <CardTitle className="text-base">{item.title}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <Badge variant="secondary">{item.keyword}</Badge>
                <pre className="text-xs bg-muted rounded p-3 whitespace-pre-wrap">{item.outline}</pre>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={() => navigator.clipboard.writeText(item.outline)}>
                    <Copy className="h-3.5 w-3.5 mr-1" />
                    Copy
                  </Button>
                  <Button variant="outline" size="sm">
                    <Download className="h-3.5 w-3.5 mr-1" />
                    Export MD
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="x" className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {xPosts.map((item, i) => (
            <Card key={i}>
              <CardContent className="p-4 space-y-3">
                <Badge variant="secondary" className="text-[11px]">{item.type}</Badge>
                <p className="text-sm leading-relaxed">{item.text}</p>
                <Button variant="outline" size="sm" onClick={() => navigator.clipboard.writeText(item.text)}>
                  <Copy className="h-3.5 w-3.5 mr-1" />
                  Copy
                </Button>
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="linkedin" className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {linkedInPosts.map((item, i) => (
            <Card key={i}>
              <CardContent className="p-4 space-y-3">
                <Badge variant="secondary" className="text-[11px]">{item.type}</Badge>
                <p className="text-sm leading-relaxed">{item.text}</p>
                <Button variant="outline" size="sm" onClick={() => navigator.clipboard.writeText(item.text)}>
                  <Copy className="h-3.5 w-3.5 mr-1" />
                  Copy
                </Button>
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="ugc" className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {ugcBriefs.map((item, i) => (
            <Card key={i}>
              <CardContent className="p-4 space-y-3">
                <p className="text-sm font-medium">{item.hook}</p>
                <div className="text-xs text-muted-foreground">
                  {item.scenes} scenes · {item.duration}
                </div>
                <Button variant="outline" size="sm">
                  <Download className="h-3.5 w-3.5 mr-1" />
                  Export Brief
                </Button>
              </CardContent>
            </Card>
          ))}
        </TabsContent>
      </Tabs>
    </div>
  );
}
