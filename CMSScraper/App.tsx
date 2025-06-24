import React, { useState, useEffect } from 'react';
import { PythonArticle, FetchState, AnalysisResult } from './types';
import LoadingSpinner from './components/LoadingSpinner';
import ErrorMessage from './components/ErrorMessage';
import ArticleCard from './components/ArticleCard';

const ITEMS_PER_PAGE = 6;

const App: React.FC = () => {
  const [articles, setArticles] = useState<PythonArticle[]>([]);
  const [fetchState, setFetchState] = useState<FetchState>(FetchState.IDLE);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState<number>(1);

  // State for Article Analysis
  const [analysisTargetUrl, setAnalysisTargetUrl] = useState<string | null>(null);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [analysisFetchState, setAnalysisFetchState] = useState<FetchState>(FetchState.IDLE);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [showAnalysisModal, setShowAnalysisModal] = useState<boolean>(false);


  useEffect(() => {
    const loadArticles = async () => {
      setFetchState(FetchState.LOADING);
      setError(null);
      try {
        // For Vite, ensure cms_articles_details.json is in the 'public' directory
        // and fetched as '/cms_articles_details.json'
        // For python -m http.server, './cms_articles_details.json' is fine if it's in the root.
        const response = await fetch('./cms_articles_details.json'); 
        if (!response.ok) {
          throw new Error(`Failed to load articles JSON: ${response.status} ${response.statusText}. Ensure 'cms_articles_details.json' is accessible.`);
        }
        const data: PythonArticle[] = await response.json();
        setArticles(data);
        setFetchState(FetchState.SUCCESS);
      } catch (err) {
        console.error("Error loading articles:", err);
        if (err instanceof Error) {
          setError(err.message);
        } else {
          setError("An unknown error occurred while loading articles.");
        }
        setFetchState(FetchState.ERROR);
      }
    };
    loadArticles();
  }, []);

  const handleAnalyzeArticleClick = async (articleLink: string) => {
    console.log("Frontend: Analyzing article:", articleLink);
    setAnalysisTargetUrl(articleLink); // Store which article is being analyzed
    setShowAnalysisModal(true); // Show the modal
    setAnalysisFetchState(FetchState.LOADING);
    setAnalysisResult(null);
    setAnalysisError(null);

    try {
      // Call your Flask backend
      const response = await fetch(`http://localhost:5001/api/analyze-article?url=${encodeURIComponent(articleLink)}`);
      if (!response.ok) {
        // Try to parse error from backend if it's JSON, otherwise use statusText
        let errorMsg = `HTTP error ${response.status} - ${response.statusText}`;
        try {
            const errorData = await response.json();
            errorMsg = errorData.error || errorMsg;
        } catch (e) { /* Ignore if error response is not JSON */ }
        throw new Error(errorMsg);
      }
      const data: AnalysisResult = await response.json();
      setAnalysisResult(data);
      setAnalysisFetchState(FetchState.SUCCESS);
    } catch (err) {
      console.error("Frontend: Error fetching analysis:", err);
      if (err instanceof Error) {
        setAnalysisError(err.message);
      } else {
        setAnalysisError("An unknown error occurred while fetching analysis.");
      }
      setAnalysisFetchState(FetchState.ERROR);
    }
  };

  const handleCloseAnalysisModal = () => {
    setShowAnalysisModal(false);
    setAnalysisTargetUrl(null); // Clear target URL
    setAnalysisResult(null);
    setAnalysisFetchState(FetchState.IDLE);
    setAnalysisError(null);
  };


  // Pagination logic
  const totalPages = Math.ceil(articles.length / ITEMS_PER_PAGE);
  const startIndex = (currentPage - 1) * ITEMS_PER_PAGE;
  const endIndex = startIndex + ITEMS_PER_PAGE;
  const currentArticles = articles.slice(startIndex, endIndex);

  const handleNextPage = () => {
    setCurrentPage((prevPage: number) => Math.min(prevPage + 1, totalPages));
  };

  const handlePreviousPage = () => {
    setCurrentPage((prevPage: number) => Math.max(prevPage - 1, 1));
  };

  const PaginationControls: React.FC = () => {
    if (totalPages <= 1) return null;
    return (
      <div className="flex justify-center items-center space-x-4 my-8">
        <button
          onClick={handlePreviousPage}
          disabled={currentPage === 1}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-slate-300 disabled:cursor-not-allowed transition-colors duration-200"
        >
          Previous
        </button>
        <span className="text-slate-700">
          Page {currentPage} of {totalPages}
        </span>
        <button
          onClick={handleNextPage}
          disabled={currentPage === totalPages}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-slate-300 disabled:cursor-not-allowed transition-colors duration-200"
        >
          Next
        </button>
      </div>
    );
  };

  // Modal or Display Area for Analysis Result
  const AnalysisDisplay: React.FC = () => {
    if (!showAnalysisModal) return null; // Only render if modal should be shown

    return (
      <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center p-4 z-50 transition-opacity duration-300">
        <div className="bg-white p-6 sm:p-8 rounded-lg shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto transform transition-all duration-300 scale-100">
          <div className="flex justify-between items-start mb-4">
            <h2 className="text-xl sm:text-2xl font-semibold text-slate-800">Article Analysis</h2>
            <button 
              onClick={handleCloseAnalysisModal}
              className="text-slate-400 hover:text-slate-600 text-3xl leading-none font-bold"
              aria-label="Close analysis"
            >×</button>
          </div>

          {analysisTargetUrl && (
             <p className="text-xs text-slate-500 mb-3 break-all">
                Analyzing: <a href={analysisTargetUrl} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">{analysisTargetUrl}</a>
            </p>
          )}

          {analysisFetchState === FetchState.LOADING && <div className="py-8"><LoadingSpinner /></div>}
          {analysisFetchState === FetchState.ERROR && analysisError && <ErrorMessage message={analysisError} />}
          {analysisFetchState === FetchState.SUCCESS && analysisResult && (
            <div className="space-y-4 text-sm sm:text-base">
              <div>
                <h4 className="font-semibold text-slate-700">Sentiment:</h4>
                <p className={`font-medium ${
                  analysisResult.sentiment?.toLowerCase() === 'positive' ? 'text-green-700 bg-green-100 p-2 rounded' :
                  analysisResult.sentiment?.toLowerCase() === 'negative' ? 'text-red-700 bg-red-100 p-2 rounded' :
                  'text-slate-700 bg-slate-100 p-2 rounded'
                }`}>
                  {analysisResult.sentiment || "Not available"}
                </p>
              </div>
              <div>
                <h4 className="font-semibold text-slate-700 mt-3">Justification:</h4>
                <p className="text-slate-600 whitespace-pre-wrap bg-slate-50 p-3 rounded max-h-48 overflow-y-auto">{analysisResult.justification || "Not available"}</p>
              </div>
              <div>
                <h4 className="font-semibold text-slate-700 mt-3">Plan of Action:</h4>
                {Array.isArray(analysisResult.plan_of_action) ? (
                    <ul className="list-disc list-inside text-slate-600 space-y-1 bg-slate-50 p-3 rounded max-h-48 overflow-y-auto">
                        {analysisResult.plan_of_action.map((item, index) => (
                            <li key={index}>{item}</li>
                        ))}
                    </ul>
                ) : (
                    <p className="text-slate-600 whitespace-pre-wrap bg-slate-50 p-3 rounded max-h-48 overflow-y-auto">{analysisResult.plan_of_action || "Not available"}</p>
                )}
              </div>
              {/* Optional: Display full_text for debugging or reference 
              <div className="mt-6 pt-4 border-t">
                <h4 className="font-semibold text-slate-700">Full AI Text (for reference):</h4>
                <p className="text-xs text-slate-500 whitespace-pre-wrap bg-slate-100 p-2 rounded max-h-48 overflow-y-auto">{analysisResult.full_text || "Not available"}</p>
              </div> 
              */}
            </div>
          )}
           <button 
              onClick={handleCloseAnalysisModal}
              className="mt-8 w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2.5 px-4 rounded-md transition-colors duration-300"
            >
              Close Analysis
            </button>
        </div>
      </div>
    );
  };


  return (
    <div className="min-h-screen bg-slate-100 p-4 sm:p-8">
      <header className="container mx-auto text-center mb-10">
        <h1 className="text-3xl sm:text-4xl font-bold text-slate-800 py-2">
          CMS Article Viewer
        </h1>
        <p className="text-md text-slate-600 mt-2 px-4">
          Displaying articles from pre-scraped CMS.gov data with pagination.
        </p>
      </header>

      <main className="container mx-auto">
        {fetchState === FetchState.LOADING && <LoadingSpinner />}
        {fetchState === FetchState.ERROR && error && <ErrorMessage message={error} />}
        
        {fetchState === FetchState.SUCCESS && (
          <div>
            {articles.length === 0 ? (
              <div className="text-center text-gray-500 py-10 bg-white shadow-md rounded-lg">
                <p className="text-2xl mb-2">📄</p>
                <p className="text-xl">No articles found in the JSON data.</p>
                <p>Ensure 'cms_articles_details.json' is available (e.g., in public folder for Vite).</p>
              </div>
            ) : (
              <>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 sm:gap-8">
                  {currentArticles.map((article, index) => (
                    <ArticleCard 
                      key={`${article["Article Link"]}-${startIndex + index}`} 
                      article={article}
                      onAnalyzeClick={handleAnalyzeArticleClick} // Pass the handler
                    />
                  ))}
                </div>
                <PaginationControls />
              </>
            )}
          </div>
        )}
      </main>
      
      <AnalysisDisplay /> {/* Render the Analysis display/modal */}

      <footer className="text-center text-slate-500 mt-12 py-6 border-t border-slate-300">
        <p className="text-sm">© {new Date().getFullYear()} Article Viewer. Data from local JSON.</p>
      </footer>
    </div>
  );
};

export default App;