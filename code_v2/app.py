import requests
from bs4 import BeautifulSoup, Comment
from urllib.parse import urljoin, urlparse
import time
import re
import json
import os # For environment variables
import uuid
import threading
from datetime import datetime, timedelta
from flask import Flask, jsonify, request as flask_request 
from flask_cors import CORS

# For Gemini API
from google.generativeai import GenerativeModel, configure

# For Langchain (with fallback to simple memory)
try:
    from langchain.memory import ConversationBufferMemory
    from langchain.schema import HumanMessage, AIMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:
    print("Warning: Langchain not available, using simple memory management")
    LANGCHAIN_AVAILABLE = False

# --- Flask App Initialization ---
app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# NOTE: Global Gemini API configuration is removed from here.
# It will be done within each route that uses the API.

# --- Chat Session Management ---
chat_sessions = {}  # {session_id: {"messages": list, "article_content": str, "article_url": str, "last_activity": datetime, "status": str, "progress_message": str}}
session_lock = threading.Lock()
SESSION_TIMEOUT_MINUTES = 10

def cleanup_expired_sessions():
    """Remove sessions that have been inactive for more than SESSION_TIMEOUT_MINUTES"""
    with session_lock:
        current_time = datetime.now()
        expired_sessions = []
        for session_id, session_data in chat_sessions.items():
            if current_time - session_data["last_activity"] > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            del chat_sessions[session_id]
            print(f"  Cleaned up expired chat session: {session_id}")
        
        if expired_sessions:
            print(f"  Cleaned up {len(expired_sessions)} expired chat sessions")

def update_session_activity(session_id):
    """Update the last activity time for a session"""
    if session_id in chat_sessions:
        chat_sessions[session_id]["last_activity"] = datetime.now()

# --- Helper Functions (Scraping Logic - largely unchanged) ---

def extract_article_details(article_url, headers):
    print(f"    Extracting details from: {article_url}")
    details = {
        "Article Heading": "Not found",
        "Article Date": "Not found",
        "Article first few lines": "Not found",
        "Article Link": article_url
    }
    max_summary_length = 300
    try:
        response = requests.get(article_url, headers=headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        title_tag = soup.select_one('h1#page-title') or \
                    soup.select_one('h1.ds-text-heading--2xl span') or \
                    soup.select_one('article h1') or \
                    soup.select_one('h1')
        if title_tag: details["Article Heading"] = title_tag.get_text(strip=True)

        specific_date_span = soup.select_one('span.create-date')
        if specific_date_span:
            date_text = specific_date_span.get_text(strip=True)
            if date_text: details["Article Date"] = date_text
        
        if details["Article Date"] == "Not found":
            date_tag = soup.find('time', attrs={'datetime': True})
            if date_tag and date_tag.get('datetime'):
                details["Article Date"] = date_tag['datetime'].split('T')[0]
            else:
                date_div_selectors = [
                    'div.ds-text-body--sm.ds-u-color--gray', 
                    'p.ds-text-body--xs.ds-u-color--gray',
                    'div.date-display-single', 'p.published-date'
                ]
                for selector in date_div_selectors:
                    date_element = soup.select_one(selector)
                    if date_element:
                        date_text_fallback = date_element.get_text(strip=True)
                        match = re.search(r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+\d{4}', date_text_fallback)
                        if match: details["Article Date"] = match.group(0); break 
                        elif "Published on" in date_text_fallback: details["Article Date"] = date_text_fallback.replace("Published on", "").strip(); break
                        elif any(month in date_text_fallback for month in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]): details["Article Date"] = date_text_fallback; break
            if details["Article Date"] == "Not found" and soup.select_one('meta[property="article:published_time"]'):
                details["Article Date"] = soup.select_one('meta[property="article:published_time"]')['content'].split('T')[0]
        
        content_area_selectors = ['article', 'div[role="main"]', 'div.field--name-body', 'div.content', 'div.entry-content', 'div.post-content', 'div.article-body', 'div.story-body', 'div.article-content', 'section.article-content']
        content_element = next((soup.select_one(s) for s in content_area_selectors if soup.select_one(s)), None) or soup.body

        if content_element:
            paragraphs = content_element.find_all('p', recursive=True)
            summary_text = ""
            for p_tag in paragraphs:
                skip = any(p.name in ['nav', 'header', 'footer', 'aside', 'form', 'figure'] or (p.has_attr('class') and any(ci in p['class'] for ci in ['menu', 'button', 'link', 'meta'])) for p in p_tag.parents if p != content_element)
                if skip: continue
                p_text = p_tag.get_text(strip=True)
                if p_text:
                    if len(summary_text) + len(p_text) + 1 < max_summary_length: summary_text += p_text + " "
                    else:
                        remaining_len = max_summary_length - len(summary_text) -1
                        if remaining_len > 20: summary_text += p_text[:remaining_len] + "..."
                        break 
            details["Article first few lines"] = summary_text.strip()
        
        if len(details["Article first few lines"]) < 50:
            meta_desc_tag = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'})
            if meta_desc_tag and meta_desc_tag.get('content'):
                 details["Article first few lines"] = meta_desc_tag['content'][:max_summary_length].strip()
    except Exception as e: print(f"      ERROR processing {article_url} for details: {e}")
    time.sleep(0.5) 
    return details

def scrape_cms_newsroom_with_specific_link_selector(start_url, max_link_pages=None, headers=None):
    if headers is None: headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36'}
    all_article_urls, current_page_url, pages_scraped_count, visited_page_urls = set(), start_url, 0, set()
    while current_page_url and (max_link_pages is None or pages_scraped_count < max_link_pages):
        if current_page_url in visited_page_urls: break
        print(f"Gathering links from page ({pages_scraped_count + 1}" + (f"/{max_link_pages}" if max_link_pages else "") + f"): {current_page_url}")
        visited_page_urls.add(current_page_url)
        try:
            response = requests.get(current_page_url, headers=headers, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            pages_scraped_count += 1
            links_found_on_this_page = 0
            for row_container in soup.select('div.views-row'):
                link_tag = row_container.select_one('a.ds-c-button.newsroom-main-view-link[href]')
                if link_tag and link_tag.get('href'):
                    abs_url = urljoin(current_page_url, link_tag['href'])
                    if urlparse(abs_url).netloc == urlparse(start_url).netloc:
                        cleaned_url = urlparse(abs_url)._replace(query="", fragment="").geturl()
                        if cleaned_url not in all_article_urls:
                            all_article_urls.add(cleaned_url)
                            links_found_on_this_page +=1
            print(f"  Found {links_found_on_this_page} new unique links on this page. Total unique links so far: {len(all_article_urls)}")
            see_more_button = soup.select_one('a.button.vis-show-more-button[rel="next"][href]')
            if see_more_button and see_more_button.get('href'):
                next_url = urljoin(start_url, see_more_button['href'])
                current_page_url = next_url if next_url != current_page_url and next_url not in visited_page_urls else None
            else: current_page_url = None
            if current_page_url: time.sleep(1)
        except Exception as e: print(f"ERROR link gathering from {current_page_url}: {e}"); current_page_url = None
    return sorted(list(all_article_urls))

def fetch_article_main_content(article_url, headers):
    print(f"    Fetching main content from: {article_url}")
    try:
        response = requests.get(article_url, headers=headers, timeout=20)
        print(f"    HTTP Status: {response.status_code}")
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        for element_type in ['script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'button', 'input', 'select', 'textarea', 'noscript', 'img', 'figure', 'iframe', 'svg']:
            for element in soup.find_all(element_type): element.decompose()
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)): comment.extract()
        main_content_selectors = ['article', 'main', 'div[role="main"]', 'div.content', 'div.entry-content', 'div.post-content', 'div.article-body', 'div.story-body', 'div.article-content', 'section.article-content']
        content_element = next((soup.select_one(s) for s in main_content_selectors if soup.select_one(s)), None)
        if not content_element: content_element = soup.body
        if content_element:
            text_parts = [el.get_text(separator=' ', strip=True) for el in content_element.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'span', 'td', 'th'], recursive=True) if el.get_text(strip=True) and len(el.get_text(strip=True).split()) > 2 and not any(p.name in ['nav', 'header', 'footer', 'aside', 'form', 'figure'] or (p.has_attr('class') and any(ci in p['class'] for ci in ['menu', 'button', 'link', 'meta'])) for p in el.parents if p != content_element)]
            full_text = "\n".join(text_parts)
            full_text = re.sub(r'\s*\n\s*', '\n', full_text).strip()
            full_text = re.sub(r'[ \t]{2,}', ' ', full_text)
            if not full_text: full_text = content_element.get_text(separator='\n', strip=True)
            print(f"      Extracted content length: {len(full_text)} characters.")
            return full_text if len(full_text) > 50 else "Error: Fetched content was too short after cleaning."
        return "Error: Could not extract main content."
    except requests.exceptions.HTTPError as e:
        print(f"      HTTP Error: {e}")
        return f"Error: HTTP {e.response.status_code} - {e}"
    except Exception as e: 
        print(f"      General Error: {e}")
        return f"Error during content extraction for {article_url}: {e}"

@app.route('/api/cms-articles', methods=['GET'])
def get_cms_articles_api():
    # ... (this route remains unchanged as it doesn't use Gemini) ...
    target_newsroom_url = "https://www.cms.gov/about-cms/contact/newsroom"
    max_link_pages = None 
    max_detail_articles = None 
    start_time = time.time()
    print(f"API call: /api/cms-articles. Stage 1: Gathering links...")
    headers = {'User-Agent': 'Mozilla/5.0 (Amgen Scraper - Article List)'}
    all_links = scrape_cms_newsroom_with_specific_link_selector(target_newsroom_url, max_link_pages=max_link_pages, headers=headers)
    if not all_links: return jsonify({"error": "No article links found.", "articles": []}), 500
    
    print(f"Stage 1 Complete: Found {len(all_links)} links. Stage 2: Extracting details...")
    articles_data = [extract_article_details(link, headers) for i, link in enumerate(all_links) if max_detail_articles is None or i < max_detail_articles]
    
    print(f"Stage 2 Complete. Scraped details for {len(articles_data)} articles. Total time: {time.time() - start_time:.2f}s.")
    return jsonify(articles_data)

# ... (imports and other functions in app.py remain the same) ...

@app.route('/api/analyze-article', methods=['GET'])
def analyze_article_api():
    # Fetch API_KEY from environment for this specific invocation
    api_key_for_request = os.environ.get("GOOGLE_API_KEY")
    if not api_key_for_request:
        print("ERROR: /api/analyze-article - API_KEY environment variable not found for this request.")
        return jsonify({"error": "Gemini API key not configured on the server for this request."}), 503
    
    try:
        configure(api_key=api_key_for_request) # Configure Gemini for this request
        print("  Gemini API configured for /api/analyze-article request.")
    except Exception as e:
        print(f"  ERROR: Failed to configure Gemini API for /api/analyze-article: {e}")
        return jsonify({"error": f"Failed to configure Gemini API: {str(e)}"}), 500

    article_url = flask_request.args.get('url')
    if not article_url: return jsonify({"error": "Missing 'url' query parameter."}), 400
    
    print(f"API call: /api/analyze-article for URL: {article_url}")
    headers = {'User-Agent': 'Mozilla/5.0 (Amgen Scraper - Analyze Content)'}
    content = fetch_article_main_content(article_url, headers)
    if content.startswith("Error:") or len(content) < 100:
        return jsonify({"error": f"Content issue: {content}", "preview": content[:200]}), 400

    prompt_template = """Imagine you are the CEO of a Large scale Life Sciences Company. This Company is called Amgen. 
    You need to identify the below 1. Sentiment - Is this news negative or Positive 2. Justify the reasoning for this sentiment. 
    Cite sources if any that lead to your reasoning 3. Possible plan of action. 
    Answer the question based on the following context. Include page numbers in your answer using the format [Page X]. 
    DO NOT MAKE UP ANY INFORMATION. If you don't know the answer, just say that you don't know. 
    
    Context: {context} Question: {question} 
    Answer (Return your response as a JSON object with keys in the order as follows: "sentiment", "justification", "plan_of_action"): """
    # MODIFIED PROMPT: Explicitly ask for JSON output
    question = "Analyze the provided article context regarding its potential impact on Amgen, and provide the sentiment, justification for the sentiment, and a possible plan of action."
    formatted_prompt = prompt_template.format(context=content, question=question)

    try:
        print("  Sending analysis prompt to Gemini...")
        model = GenerativeModel(model_name="gemini-2.5-flash-preview-04-17")
        # Request JSON output from the model
        generation_config_for_json = {"response_mime_type": "application/json"}
        response = model.generate_content(
            formatted_prompt,
            generation_config=generation_config_for_json # Add this
        )
        
        raw_analysis_text = ""
        if hasattr(response, 'text') and response.text:
            raw_analysis_text = response.text
        elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            raw_analysis_text = "".join(p.text for p in response.candidates[0].content.parts if hasattr(p, 'text'))
        
        if not raw_analysis_text:
            print(f"  Gemini analysis response was empty. Full response: {response}")
            return jsonify({"error": "Received an empty analysis from the AI."}), 500
        
        print(f"  Received raw analysis text from Gemini: {raw_analysis_text[:500]}...") # Log snippet

        # Attempt to parse the text as JSON, after stripping potential markdown fences
        json_str_to_parse = raw_analysis_text.strip()
        if json_str_to_parse.startswith("```json"):
            json_str_to_parse = json_str_to_parse[7:] # Remove ```json\n
        if json_str_to_parse.startswith("```"): # More generic fence removal
             json_str_to_parse = json_str_to_parse[3:]
        if json_str_to_parse.endswith("```"):
            json_str_to_parse = json_str_to_parse[:-3]
        json_str_to_parse = json_str_to_parse.strip()

        try:
            parsed_json_response = json.loads(json_str_to_parse)
            # Validate expected keys
            sentiment = parsed_json_response.get("sentiment", "Could not determine from JSON")
            justification = parsed_json_response.get("justification", "Could not determine from JSON")
            plan_of_action = parsed_json_response.get("plan_of_action", "Could not determine from JSON")

            analysis_parts = {
                "sentiment": sentiment,
                "justification": justification,
                "plan_of_action": plan_of_action,
                "full_text": raw_analysis_text # Keep the original full text for reference if needed
            }
            print(f"  Successfully parsed JSON analysis: {analysis_parts}")
            return jsonify(analysis_parts)

        except json.JSONDecodeError as e:
            print(f"  JSONDecodeError parsing Gemini response. String was: '{json_str_to_parse}'. Error: {e}")
            print(f"  Original full_text from Gemini for context: {raw_analysis_text}")
            # Fallback to trying to parse the previous numbered list format if JSON parsing fails badly
            # This is less ideal as the model was asked for JSON.
            print("  Falling back to regex parsing due to JSONDecodeError...")
            fallback_parts = {"sentiment": "Fallback: Could not determine", "justification": "Fallback: Could not determine", "plan_of_action": "Fallback: Could not determine", "full_text": raw_analysis_text}
            lines = raw_analysis_text.split('\n')
            current_key = None
            header_patterns = {
                "sentiment": re.compile(r"^\s*1\.\s*(?:\*\*)?Sentiment(?:\*\*)?\s*[:\-\s]?(.*)", re.IGNORECASE),
                "justification": re.compile(r"^\s*2\.\s*(?:\*\*)?(?:Justify|Justification)(?:\*\*)?\s*[:\-\s]?(.*)", re.IGNORECASE),
                "plan_of_action": re.compile(r"^\s*3\.\s*(?:\*\*)?Possible plan of action(?:\*\*)?\s*[:\-\s]?(.*)", re.IGNORECASE)
            }
            temp_buffers = {"sentiment": [], "justification": [], "plan_of_action": []}

            for line_content in lines:
                matched_new_section = False
                for key, pattern in header_patterns.items():
                    match = pattern.match(line_content.strip())
                    if match:
                        current_key = key
                        content_on_header_line = match.group(1).strip()
                        if content_on_header_line: temp_buffers[current_key].append(content_on_header_line)
                        matched_new_section = True
                        break
                if not matched_new_section and current_key:
                    if line_content.strip(): temp_buffers[current_key].append(line_content.strip())
                    elif temp_buffers[current_key]: temp_buffers[current_key].append("")
            
            for key in temp_buffers: fallback_parts[key] = "\n".join(temp_buffers[key]).strip() or f"Fallback: Could not determine {key}"
            return jsonify(fallback_parts)

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": f"AI analysis failed: {str(e)}"}), 500

# ... (rest of app.py including summarize_article_api and other functions remains the same)
@app.route('/api/summarize-article', methods=['GET'])
def summarize_article_api():
    # Fetch API_KEY from environment for this specific invocation
    api_key_for_request = os.environ.get("GOOGLE_API_KEY")
    if not api_key_for_request:
        print("ERROR: /api/summarize-article - API_KEY environment variable not found for this request.")
        return jsonify({"error": "Gemini API key not configured on the server for this request."}), 503

    try:
        configure(api_key=api_key_for_request) # Configure Gemini for this request
        print("  Gemini API configured for /api/summarize-article request.")
    except Exception as e:
        print(f"  ERROR: Failed to configure Gemini API for /api/summarize-article: {e}")
        return jsonify({"error": f"Failed to configure Gemini API: {str(e)}"}), 500

    article_url = flask_request.args.get('url')
    if not article_url: return jsonify({"error": "Missing 'url' query parameter."}), 400

    print(f"API call: /api/summarize-article for URL: {article_url}")
    headers = {'User-Agent': 'Mozilla/5.0 (Amgen Scraper - Summarize Content)'}
    content = fetch_article_main_content(article_url, headers)
    if content.startswith("Error:") or len(content) < 50:
        return jsonify({"error": f"Content issue: {content}", "preview": content[:200]}), 400

    prompt = f"Please provide a concise, neutral summary of the following article content, capturing the main points. The summary should be approximately 10 sentences long. Bullet points are appreciated\n\nArticle Content:\n{content}\n\nSummary:"
    try:
        print("  Sending summarization prompt to Gemini...")
        model = GenerativeModel(model_name="gemini-2.5-flash-preview-04-17")
        response = model.generate_content(prompt)
        summary = response.text if hasattr(response, 'text') and response.text else "".join(p.text for p in response.candidates[0].content.parts if hasattr(p, 'text')) if response.candidates else ""

        if not summary: return jsonify({"error": "Empty summary from AI."}), 500
        print("  Received summary from Gemini.")
        return jsonify({"summary": summary.strip()})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": f"AI summarization failed: {str(e)}"}), 500

@app.route('/api/chat-with-article', methods=['POST'])
def chat_with_article():
    # Fetch API_KEY from environment
    api_key_for_request = os.environ.get("GOOGLE_API_KEY")
    if not api_key_for_request:
        print("ERROR: /api/chat-with-article - API_KEY environment variable not found.")
        return jsonify({"error": "Gemini API key not configured on the server."}), 503

    try:
        configure(api_key=api_key_for_request)
        print("  Gemini API configured for /api/chat-with-article request.")
    except Exception as e:
        print(f"  ERROR: Failed to configure Gemini API for /api/chat-with-article: {e}")
        return jsonify({"error": f"Failed to configure Gemini API: {str(e)}"}), 500

    # Clean up expired sessions
    cleanup_expired_sessions()
    
    data = flask_request.get_json()
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400
    
    action = data.get('action')
    
    if action == 'start':
        # Start new chat session
        article_url = data.get('url')
        if not article_url:
            return jsonify({"error": "Missing 'url' in request body for start action."}), 400
        
        print(f"API call: /api/chat-with-article - Starting chat for URL: {article_url}")
        
        # Fetch article content
        headers = {'User-Agent': 'Mozilla/5.0 (Amgen Scraper - Chat Content)'}
        content = fetch_article_main_content(article_url, headers)
        
        # Create session regardless, but handle invalid content
        session_id = str(uuid.uuid4())
        
        print(f"  Content received: {content[:200]}...")  # Debug log
        
        # Check for various error conditions
        is_error = (
            content.startswith("Error:") or 
            len(content) < 100 or  # Increased threshold
            "404" in content or 
            "Not Found" in content or
            "Page not found" in content.lower() or
            "could not extract main content" in content.lower()
        )
        
        if is_error:
            # Create session with error state
            with session_lock:
                chat_sessions[session_id] = {
                    "messages": [],
                    "article_content": None,
                    "article_url": article_url,
                    "last_activity": datetime.now(),
                    "status": "error",
                    "progress_message": "Article could not be loaded"
                }
            
            print(f"  Created chat session with error: {session_id} - Content issue: {content[:100]}")
            
            return jsonify({
                "session_id": session_id,
                "message": "Hello! I tried to read the article at the link you provided. But it seems that this link is not valid anymore. Please close this session and try another article link.",
                "status": "error"
            })
        
        # Create session with loading state and start background processing
        with session_lock:
            chat_sessions[session_id] = {
                "messages": [],
                "article_content": content,
                "article_url": article_url,
                "last_activity": datetime.now(),
                "status": "loading",
                "progress_message": "Loading article content..."
            }
        
        print(f"  Created new chat session: {session_id} - Starting background processing")
        
        # Start background processing
        def process_article_async():
            try:
                # Update status: Analyzing
                with session_lock:
                    if session_id in chat_sessions:
                        chat_sessions[session_id]["status"] = "analyzing"
                        chat_sessions[session_id]["progress_message"] = "Analyzing article content..."
                
                # Generate article summary
                print("  Generating article summary...")
                with session_lock:
                    if session_id in chat_sessions:
                        chat_sessions[session_id]["progress_message"] = "Generating response..."
                
                summary_prompt = f"""Provide a concise 2-line summary of the following article content. Focus on the main topic and key points.

Article Content:
{content[:2000]}...

Summary (2 lines maximum):"""
                
                model = GenerativeModel(model_name="gemini-2.5-flash-preview-04-17")
                summary_response = model.generate_content(summary_prompt)
                
                article_summary = ""
                if hasattr(summary_response, 'text') and summary_response.text:
                    article_summary = summary_response.text.strip()
                else:
                    article_summary = "This article discusses important healthcare policy updates and regulatory changes."
                
                print(f"  Generated article summary: {article_summary[:100]}...")
                
                # Update status: Questions
                with session_lock:
                    if session_id in chat_sessions:
                        chat_sessions[session_id]["progress_message"] = "Preparing suggested questions..."
                
                # Generate suggested questions
                print("  Generating suggested questions...")
                questions_prompt = f"""Based on the following article content, generate exactly 3 relevant questions that a user might want to ask about this article. The questions should be:
1. Specific to the article content
2. Helpful for understanding key points
3. Encourage deeper discussion

Article Content:
{content[:2000]}...

Return only the 3 questions as a JSON array with no additional text:
["Question 1?", "Question 2?", "Question 3?"]"""
                
                generation_config = {"response_mime_type": "application/json"}
                questions_response = model.generate_content(questions_prompt, generation_config=generation_config)
                
                suggested_questions = []
                if hasattr(questions_response, 'text') and questions_response.text:
                    try:
                        parsed_questions = json.loads(questions_response.text.strip())
                        if isinstance(parsed_questions, list) and len(parsed_questions) == 3:
                            suggested_questions = parsed_questions
                        else:
                            raise ValueError("Invalid questions format")
                    except (json.JSONDecodeError, ValueError):
                        print("  Could not load follow up questions.")
                        suggested_questions = [
                            "What is the main topic of this article?",
                            "What are the key points discussed?",
                            "How might this impact the healthcare industry?"
                        ]
                else:
                    print("  Could not load follow up questions.")
                    suggested_questions = [
                        "What is the main topic of this article?",
                        "What are the key points discussed?", 
                        "How might this impact the healthcare industry?"
                    ]
                
                print(f"  Generated {len(suggested_questions)} suggested questions")
                
                # Create final message
                first_message = f"Hello! I have read the article. It talks about {article_summary} Please ask your question, or you may choose from the options below."
                
                # Update session to ready state
                with session_lock:
                    if session_id in chat_sessions:
                        chat_sessions[session_id]["status"] = "ready"
                        chat_sessions[session_id]["progress_message"] = "Ready to chat!"
                        chat_sessions[session_id]["message"] = first_message
                        chat_sessions[session_id]["suggested_questions"] = suggested_questions
                
                print(f"  Background processing completed for session: {session_id}")
                
            except Exception as e:
                print(f"  Error in background processing: {e}")
                with session_lock:
                    if session_id in chat_sessions:
                        chat_sessions[session_id]["status"] = "error"
                        chat_sessions[session_id]["progress_message"] = "Processing failed"
        
        # Start background thread
        thread = threading.Thread(target=process_article_async)
        thread.daemon = True
        thread.start()
        
        # Return immediate response with loading status
        return jsonify({
            "session_id": session_id,
            "status": "loading",
            "progress_message": "Loading article content..."
        })
    
    elif action == 'close':
        # Close and invalidate session
        session_id = data.get('session_id')
        if not session_id:
            return jsonify({"error": "Missing 'session_id' in request body."}), 400
        
        with session_lock:
            if session_id in chat_sessions:
                del chat_sessions[session_id]
                print(f"  Closed and invalidated chat session: {session_id}")
                return jsonify({"message": "Session closed successfully.", "status": "closed"})
            else:
                return jsonify({"error": "Session not found or already closed."}), 404
    
    elif action == 'message':
        # Handle chat message
        session_id = data.get('session_id')
        user_message = data.get('message')
        
        if not session_id or not user_message:
            return jsonify({"error": "Missing 'session_id' or 'message' in request body."}), 400
        
        with session_lock:
            if session_id not in chat_sessions:
                return jsonify({"error": "Invalid or expired session ID."}), 404
            
            session_data = chat_sessions[session_id]
            
            # Check if session is in error state
            if session_data.get("status") == "error":
                return jsonify({"error": "This session has an invalid article. Please close this session and try another article link."}), 400
            
            update_session_activity(session_id)
        
        print(f"API call: /api/chat-with-article - Message for session: {session_id}")
        
        try:
            # Get conversation history and article content
            messages = session_data["messages"]
            article_content = session_data["article_content"]
            
            # Build conversation history string
            conversation_history = ""
            for msg in messages:
                conversation_history += f"{msg['role']}: {msg['content']}\n"
            
            # Create enhanced prompt with article context and conversation history
            prompt = f"""You are an AI assistant helping to discuss and analyze an article. 

Article Content:
{article_content}

Conversation History:
{conversation_history}

Current Question: {user_message}

Please provide a helpful response based on the article content and conversation context. Be concise and informative.

After your response, you must also suggest 3 new relevant questions that the user might want to ask next, based on:
1. The current conversation context
2. Unexplored aspects of the article
3. Natural follow-up questions to your response

Return your response as a JSON object with this exact format:
{{
  "response": "Your detailed answer here",
  "suggested_questions": ["Question 1?", "Question 2?", "Question 3?"]
}}"""
            
            # Get response from Gemini with JSON format
            model = GenerativeModel(model_name="gemini-2.5-flash-preview-04-17")
            generation_config = {"response_mime_type": "application/json"}
            response = model.generate_content(prompt, generation_config=generation_config)
            
            raw_response = ""
            if hasattr(response, 'text') and response.text:
                raw_response = response.text
            elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                raw_response = "".join(p.text for p in response.candidates[0].content.parts if hasattr(p, 'text'))
            
            if not raw_response:
                return jsonify({"error": "Empty response from AI."}), 500
            
            # Parse JSON response
            try:
                parsed_response = json.loads(raw_response.strip())
                ai_message = parsed_response.get("response", "")
                suggested_questions = parsed_response.get("suggested_questions", [])
                
                # Validate suggested questions
                if not isinstance(suggested_questions, list) or len(suggested_questions) != 3:
                    print("  Could not load follow up questions.")
                    suggested_questions = [
                        "Can you elaborate on this topic?",
                        "What are the implications of this?",
                        "How does this relate to other aspects of the article?"
                    ]
                    
            except json.JSONDecodeError as e:
                print(f"  Could not load follow up questions.")
                # Fallback to treating entire response as message
                ai_message = raw_response
                suggested_questions = [
                    "Can you elaborate on this topic?",
                    "What are the implications of this?", 
                    "How does this relate to other aspects of the article?"
                ]
            
            # Add both messages to session history
            with session_lock:
                session_data["messages"].append({"role": "Human", "content": user_message})
                session_data["messages"].append({"role": "Assistant", "content": ai_message})
            
            print(f"  Generated response with {len(suggested_questions)} suggested questions for session: {session_id}")
            
            return jsonify({
                "message": ai_message.strip(),
                "session_id": session_id,
                "suggested_questions": suggested_questions
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"Chat failed: {str(e)}"}), 500
    
    else:
        return jsonify({"error": "Invalid action. Use 'start', 'message', or 'close'."}), 400

@app.route('/api/chat-status', methods=['GET'])
def get_chat_status():
    session_id = flask_request.args.get('session_id')
    if not session_id:
        return jsonify({"error": "Missing 'session_id' query parameter."}), 400
    
    with session_lock:
        if session_id not in chat_sessions:
            return jsonify({"error": "Session not found."}), 404
        
        session_data = chat_sessions[session_id]
        update_session_activity(session_id)
        
        response_data = {
            "session_id": session_id,
            "status": session_data["status"],
            "progress_message": session_data.get("progress_message", "")
        }
        
        # If ready, include the final message and questions
        if session_data["status"] == "ready" and "message" in session_data:
            response_data["message"] = session_data["message"]
            response_data["suggested_questions"] = session_data.get("suggested_questions", [])
        
        return jsonify(response_data)

if __name__ == '__main__':
    print("Starting Amgen Article Analyzer Flask App...")
    # print(f"Flask version: {flask.__version__}") # Requires: import flask
    # print(f"Requests version: {requests.__version__}")
    # from bs4 import __version__ as bs4_version # To get bs4 version
    # print(f"BeautifulSoup version: {bs4_version}")
    
    # Check if API_KEY is generally available for logging purposes, but routes will check again
    if os.environ.get("GOOGLE_API_KEY"): 
        print("Note: An API_KEY environment variable is present.")
    else: 
        print("WARNING: API_KEY environment variable does NOT seem to be set. Analyze/Summarize will fail if not available to routes.")
    
    print("\nEndpoints: /api/cms-articles, /api/analyze-article?url=<URL>, /api/summarize-article?url=<URL>, /api/chat-with-article, /api/chat-status")
    app.run(debug=True, port=5001, use_reloader=False)