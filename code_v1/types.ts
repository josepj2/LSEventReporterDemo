// Matches the structure of the JSON output from the Python script
export interface PythonArticle {
  "Article Heading": string;
  "Article Date": string;
  "Article first few lines": string;
  "Article Link": string;
}

export enum FetchState {
  IDLE,
  LOADING,
  SUCCESS,
  ERROR
}

// For the analysis result from /api/analyze-article
export interface AnalysisResult {
  sentiment: string;
  justification: string;
  plan_of_action: string | string[]; // Can be string or array of strings
  full_text: string;
}

// The types below are from previous iterations and not strictly used by App.tsx
// when it loads local PythonArticle JSON. They are kept for context from services/geminiService.ts.
export type Sentiment = 'positive' | 'negative' | 'neutral' | 'unclassified';
export interface Article {
  title: string;
  link: string;
  date: string; 
  summary: string; 
  aiSuggestedSentiment?: 'positive' | 'negative' | 'neutral';
  sentiment: Sentiment; 
}
export interface GroundingChunkWeb {
  uri?: string; 
  title?: string;
}
export interface GroundingChunk {
  web?: GroundingChunkWeb;
}