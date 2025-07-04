import requests
from bs4 import BeautifulSoup, Comment
from urllib.parse import urljoin, urlparse
import time
import re
import json
import os # For environment variables
from flask import Flask, jsonify, request as flask_request 
from flask_cors import CORS

# For Gemini API
from google.generativeai import GenerativeModel, configure

# --- Flask App Initialization ---
app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# NOTE: Global Gemini API configuration is removed from here.
# It will be done within each route that uses the API.

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
            return full_text if len(full_text) > 50 else "Fetched content was too short after cleaning."
        return "Could not extract main content."
    except Exception as e: return f"Error during content extraction for {article_url}: {e}"

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

    prompt = f"Please provide a concise, neutral summary of the following article content, capturing the main points. The summary should be approximately 2-4 sentences long.\n\nArticle Content:\n{content}\n\nSummary:"
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
    
    print("\nEndpoints: /api/cms-articles, /api/analyze-article?url=<URL>, /api/summarize-article?url=<URL>")
    app.run(debug=True, port=5001, use_reloader=False)