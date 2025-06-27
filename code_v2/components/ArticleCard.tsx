import React from 'react';
import { PythonArticle } from '../types';

interface ArticleCardProps {
  article: PythonArticle;
  onAnalyzeClick: (articleLink: string) => void;
  onSummarizeClick: (articleLink: string) => void;
  onChatClick: (articleLink: string) => void;
}

const ArticleCard: React.FC<ArticleCardProps> = ({ article, onAnalyzeClick, onSummarizeClick, onChatClick }) => {
  const displaySummary = article["Article first few lines"] && article["Article first few lines"].length > 180
    ? article["Article first few lines"].substring(0, 177) + "..."
    : article["Article first few lines"];

  const handleAnalyze = () => {
    onAnalyzeClick(article["Article Link"]);
  };

  const handleSummarize = () => {
    onSummarizeClick(article["Article Link"]);
  };

  const handleChat = () => {
    onChatClick(article["Article Link"]);
  };

  return (
    <div className="bg-white shadow-md rounded-lg p-2 border border-slate-200 hover:shadow-lg transition-shadow duration-300 flex flex-col justify-between h-auto min-h-40">
      <div>
        <h3 className="text-sm font-semibold text-slate-800 mb-1 line-clamp-2">{article["Article Heading"] || "Untitled Article"}</h3>
        {article["Article Date"] && article["Article Date"] !== "Not found" && (
          <p className="text-xs text-slate-500 mb-2">Date: {article["Article Date"]}</p>
        )}
        <p className="text-slate-700 text-xs mb-2 line-clamp-3">
          {displaySummary || "No summary available."}
        </p>
      </div>

      <div className="mt-auto flex flex-col space-y-1">
        <a
          href={article["Article Link"]}
          target="_blank"
          rel="noopener noreferrer"
          className="w-full bg-[#000048] hover:bg-[#000066] text-white font-medium py-1.5 px-2 rounded text-xs text-center"
          aria-label={`Read more about ${article["Article Heading"]}`}
        >
          Read
        </a>
        <div className="grid grid-cols-3 gap-1">
          <button
            onClick={handleSummarize}
            className="bg-[#000048] hover:bg-[#000066] text-white font-medium py-1.5 px-1 rounded text-xs"
            aria-label={`Summarize article: ${article["Article Heading"]}`}
          >
            Summarize
          </button>
          <button
            onClick={handleAnalyze}
            className="bg-[#000048] hover:bg-[#000066] text-white font-medium py-1.5 px-1 rounded text-xs"
            aria-label={`Analyze article: ${article["Article Heading"]}`}
          >
            Analyze
          </button>
          <button
            onClick={handleChat}
            className="bg-[#000048] hover:bg-[#000066] text-white font-medium py-1.5 px-1 rounded text-xs"
            aria-label={`Chat about article: ${article["Article Heading"]}`}
          >
            Chat
          </button>
        </div>
      </div>
    </div>
  );
};

export default ArticleCard;