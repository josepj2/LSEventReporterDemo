import React from 'react';
import { PythonArticle } from '../types';

interface ArticleCardProps {
  article: PythonArticle;
  onAnalyzeClick: (articleLink: string) => void; // Prop to handle analyze click
  // onSummarizeClick will be added later
}

const ArticleCard: React.FC<ArticleCardProps> = ({ article, onAnalyzeClick }) => {
  const displaySummary = article["Article first few lines"] && article["Article first few lines"].length > 180 
    ? article["Article first few lines"].substring(0, 177) + "..." 
    : article["Article first few lines"];

  const handleAnalyze = () => {
    onAnalyzeClick(article["Article Link"]);
  };

  return (
    <div className="bg-white shadow-lg rounded-lg p-6 border border-slate-200 hover:shadow-xl transition-shadow duration-300 flex flex-col justify-between h-full">
      <div>
        <h3 className="text-xl font-semibold text-slate-800 mb-2">{article["Article Heading"] || "Untitled Article"}</h3>
        {article["Article Date"] && article["Article Date"] !== "Not found" && (
          <p className="text-xs text-slate-500 mb-3">Date: {article["Article Date"]}</p>
        )}
        <p className="text-slate-700 text-sm mb-4 flex-grow min-h-[60px]">
          {displaySummary || "No summary available."}
        </p>
      </div>

      <div className="mt-auto pt-4 flex flex-col sm:flex-row sm:space-x-2 space-y-2 sm:space-y-0 items-center">
        <a
          href={article["Article Link"]}
          target="_blank"
          rel="noopener noreferrer"
          className="w-full sm:w-auto flex-1 bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2.5 px-4 rounded-md transition-colors duration-300 text-center text-sm mb-2 sm:mb-0"
          aria-label={`Read more about ${article["Article Heading"]}`}
        >
          Read Article
        </a>
        <button
          onClick={handleAnalyze} // Use the handler
          className="w-full sm:w-auto flex-1 bg-slate-500 hover:bg-slate-600 text-white font-semibold py-2.5 px-4 rounded-md transition-colors duration-300 text-center text-sm mb-2 sm:mb-0"
          aria-label={`Analyze article: ${article["Article Heading"]}`}
        >
          Analyze
        </button>
        <a
          href={`./summarize.html?articleUrl=${encodeURIComponent(article["Article Link"])}`} // Stays as a link for now
          className="w-full sm:w-auto flex-1 bg-teal-500 hover:bg-teal-600 text-white font-semibold py-2.5 px-4 rounded-md transition-colors duration-300 text-center text-sm"
          aria-label={`Summarize article: ${article["Article Heading"]}`}
        >
          Summarize
        </a>
      </div>
    </div>
  );
};

export default ArticleCard;