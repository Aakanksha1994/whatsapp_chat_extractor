from flask import Flask, request, render_template, redirect, url_for, session, send_file
import os
import re
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
import tempfile
import json
import uuid
import shutil
import openai
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size
app.config['RESULTS_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'results')
os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)

# Initialize OpenAI with API key from .env file
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    print("WARNING: OpenAI API key not found. Please add OPENAI_API_KEY to your .env file")

def parse_whatsapp_chat(file_path: str) -> List[Dict[str, str]]:
    """Parse WhatsApp chat export into structured messages."""
    messages = []
    current_message = None
    line_count = 0
    parsed_count = 0
    
    # Pattern for date detection - very simple
    date_pattern = re.compile(r'^\[(\d{2}/\d{2}/\d{2})')
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
        for line in file:
            line_count += 1
            line = line.strip()
            if not line:
                continue
            
            # Check if this line starts a new message (has a date)
            if date_pattern.match(line):
                # Split by the closing bracket and colon
                try:
                    date_part = line.split(']')[0] + ']'
                    rest = line[len(date_part):].strip()
                    
                    if ':' in rest:
                        sender, message = rest.split(':', 1)
                        
                        # Add previous message if exists
                        if current_message:
                            messages.append(current_message)
                        
                        # Create new message
                        current_message = {
                            'date': date_part.strip('[]'),
                            'sender': sender.strip(),
                            'message': message.strip()
                        }
                        parsed_count += 1
                    else:
                        # System message without colon
                        if current_message:
                            messages.append(current_message)
                        current_message = {
                            'date': date_part.strip('[]'),
                            'sender': 'SYSTEM',
                            'message': rest.strip()
                        }
                        parsed_count += 1
                except:
                    # If parsing fails, add to previous message if exists
                    if current_message:
                        current_message['message'] += '\n' + line
            elif current_message:
                # Continuation of previous message
                current_message['message'] += '\n' + line
    
    # Add the last message
    if current_message:
        messages.append(current_message)
    
    print(f"Read {line_count} lines, parsed {parsed_count} messages")
    return messages

def extract_urls(messages: List[Dict[str, str]]) -> List[str]:
    """Extract URLs from messages."""
    url_pattern = re.compile(r'https?://\S+')
    urls = set()
    for msg in messages:
        found = url_pattern.findall(msg['message'])
        urls.update(found)
    return list(urls)

def fetch_url_title(url):
    """Fetch the title of a webpage."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        title = soup.title.string if soup.title else url
        return title.strip()
    except Exception as e:
        print(f"Error fetching title for {url}: {e}")
        return url

def extract_ai_coding_knowledge_with_openai(messages: List[Dict[str, str]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Extract AI coding knowledge and tips from WhatsApp chat messages using OpenAI.
    
    Returns a dictionary with categories as keys and lists of tips as values.
    """
    if not openai.api_key:
        print("OpenAI API key not found. Using fallback local extraction.")
        return extract_coding_tips_local(messages)
    
    # Combine messages into a single text with structure
    message_text = "\n\n".join([
        f"Date: {msg['date']}, Sender: {msg['sender']}\n{msg['message']}" 
        for msg in messages
    ])
    
    # Limit text to avoid token limits (around 32k tokens for GPT-4)
    if len(message_text) > 100000:  # Approximate token limit
        message_text = message_text[:100000]
    
    try:
        # Create the system prompt with instructions
        system_prompt = """
        You are an AI assistant specialized in extracting valuable knowledge about AI coding tools and practices from WhatsApp chats.
        
        TASK: Extract and organize only the valuable knowledge, tips, and lessons about coding with AI tools from the provided WhatsApp chat.
        
        INSTRUCTIONS:
        1. Focus ONLY on information related to coding with AI tools (Cursor, Copilot, ChatGPT, Claude, etc.)
        2. Ignore general conversations, greetings, and non-informative messages
        3. Extract specific knowledge, tips, techniques, and lessons
        4. Organize the information into these categories:
           - AI Coding Tools: Information about specific tools like Cursor, Copilot, etc.
           - Prompt Engineering: Tips for writing effective prompts
           - AI Development Workflow: How to integrate AI into development workflows
           - Coding Best Practices: Best practices when working with AI
           - AI Limitations & Workarounds: Common issues and how to fix them
        
        OUTPUT FORMAT:
        Return a JSON object with categories as keys and arrays of extracted knowledge points as values.
        Each knowledge point should have:
        - content: The actual knowledge/tip text
        
        Do not include sender information or dates. Focus only on the valuable content.
        """
        
        # Make the API call to ChatGPT
        response = openai.chat.completions.create(
            model="gpt-4o",  # You can switch to gpt-3.5-turbo if needed
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Here is the WhatsApp chat transcript:\n\n{message_text}"}
            ],
            temperature=0.1,  # Low temperature for more deterministic output
            max_tokens=3000,
            response_format={"type": "json_object"}
        )
        
        # Extract and parse JSON from response
        ai_response = response.choices[0].message.content
        categorized_knowledge = json.loads(ai_response)
        
        # If the response doesn't match expected format, apply some fixes
        if not any(category in categorized_knowledge for category in [
            "AI Coding Tools", "Prompt Engineering", "AI Development Workflow", 
            "Coding Best Practices", "AI Limitations & Workarounds"
        ]):
            print("OpenAI response didn't match expected format. Attempting to fix...")
            # Create standard structure
            fixed_response = {
                "AI Coding Tools": [],
                "Prompt Engineering": [],
                "AI Development Workflow": [],
                "Coding Best Practices": [],
                "AI Limitations & Workarounds": []
            }
            
            # Try to fit the response into this structure
            for category, items in categorized_knowledge.items():
                best_match = "AI Coding Tools"  # Default
                for standard_cat in fixed_response.keys():
                    if standard_cat.lower() in category.lower() or category.lower() in standard_cat.lower():
                        best_match = standard_cat
                        break
                
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict) and "content" in item:
                            fixed_response[best_match].append(item)
                        elif isinstance(item, str):
                            fixed_response[best_match].append({"content": item})
                        else:
                            # Try to convert to standard format
                            content = str(item)
                            fixed_response[best_match].append({"content": content})
            
            return fixed_response
            
        return categorized_knowledge
        
    except Exception as e:
        print(f"Error using OpenAI API: {e}")
        # Fall back to local extraction if OpenAI fails
        return extract_coding_tips_local(messages)

def extract_coding_tips_local(messages: List[Dict[str, str]]) -> Dict[str, List[Dict[str, Any]]]:
    """Local fallback for extracting coding tips if OpenAI is unavailable."""
    # Keywords for different categories
    categories = {
        'AI Coding Tools': [
            'cursor', 'copilot', 'github copilot', 'gpt', 'chatgpt', 'claude', 'ai coding', 
            'ai pair programming', 'cody', 'tabnine', 'kite', 'intellicode', 'ai assistant',
            'openai', 'anthropic', 'code completion', 'code generation', 'llm'
        ],
        'Prompt Engineering': [
            'prompt', 'prompt engineering', 'system prompt', 'context window', 'few-shot', 
            'zero-shot', 'chain of thought', 'cot', 'token', 'temperature', 'top_p',
            'instruction', 'completion'
        ],
        'AI Development Workflow': [
            'workflow', 'ai workflow', 'pair programming', 'development', 'ide integration',
            'code review', 'refactoring', 'debugging', 'testing', 'documentation'
        ],
        'Coding Best Practices': [
            'best practice', 'pattern', 'architecture', 'design', 'clean code', 'maintainable', 
            'performance', 'optimization', 'efficient', 'robust', 'reliable'
        ],
        'AI Limitations & Workarounds': [
            'limitation', 'hallucination', 'error', 'workaround', 'fix', 'solution', 'problem',
            'issue', 'bug', 'incorrect', 'wrong', 'accurate', 'reliable', 'improve'
        ]
    }
    
    tips = []
    
    for msg in messages:
        text = msg['message'].lower()
        
        # Skip short messages
        if len(text.split()) < 15:
            continue
            
        # Only include if it has knowledge/tip indicators
        knowledge_indicators = [
            'how to', 'you can', 'try this', 'best practice', 'tip', 'advice', 'recommend',
            'solution', 'fixed by', 'learned that', 'discovered', 'example', 'code snippet',
            'here\'s how', 'better way', 'trick', 'method', 'approach', 'technique',
            'pattern', 'framework', 'tool', 'works well', 'avoid', 'don\'t do', 'instead of',
            'remember to', 'must have', 'essential', 'useful', 'valuable', 'game changer',
            'optimal', 'efficient', 'effective', 'strategy', 'important to note'
        ]
        
        has_indicator = any(indicator in text for indicator in knowledge_indicators)
        
        # If no knowledge indicator, skip unless it contains multiple AI tool references
        ai_tool_keywords = ['cursor', 'copilot', 'chatgpt', 'claude', 'gpt', 'ai', 'llm']
        ai_tool_count = sum(1 for keyword in ai_tool_keywords if keyword in text)
        
        if not has_indicator and ai_tool_count < 2:
            continue
        
        # Assign category
        assigned_categories = []
        for category, keywords in categories.items():
            if any(keyword in text for keyword in keywords):
                assigned_categories.append(category)
        
        # Only include if it belongs to at least one category
        if assigned_categories:
            # Process text to extract just the knowledge/tip part
            sentences = re.split(r'(?<=[.!?])\s+', text)
            
            # Filter out conversational sentences
            knowledge_sentences = []
            for sentence in sentences:
                # Skip short or conversational sentences
                if len(sentence.split()) < 5:
                    continue
                if any(phrase in sentence.lower() for phrase in ['hi ', 'hello', 'hey ', 'thanks', 'thank you', 'how are you', 'what do you think', 'what about', 'lol', 'haha', 'ok', 'okay', 'sure', 'cool', 'nice']):
                    continue
                knowledge_sentences.append(sentence)
            
            # Only include if we have substantial knowledge content
            if len(knowledge_sentences) > 0:
                tips.append({
                    'sender': msg['sender'],
                    'date': msg['date'],
                    'content': ' '.join(knowledge_sentences),
                    'categories': assigned_categories,
                    'word_count': len(text.split())
                })
    
    # Sort by word count (rough measure of detail/value)
    tips.sort(key=lambda x: x['word_count'], reverse=True)
    
    # Convert to categorized format
    categorized = {
        'AI Coding Tools': [],
        'Prompt Engineering': [],
        'AI Development Workflow': [],
        'Coding Best Practices': [],
        'AI Limitations & Workarounds': []
    }
    
    for tip in tips:
        for category in tip['categories']:
            categorized[category].append({
                'content': tip['content']
            })
    
    return categorized

@app.route('/', methods=['GET', 'POST'])
def index():
    try:
        if request.method == 'POST':
            # Check if a file was uploaded
            if 'file' not in request.files:
                return render_template('index.html', error="No file selected")
            
            file = request.files['file']
            
            # If user submits without selecting a file
            if file.filename == '':
                return render_template('index.html', error="No file selected")
            
            if file:
                # Save the file to a temporary location
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'chat.txt')
                file.save(filepath)
                
                try:
                    # Parse the WhatsApp chat
                    messages = parse_whatsapp_chat(filepath)
                    
                    # Extract URLs and their titles
                    urls = extract_urls(messages)
                    link_titles = []
                    for url in urls:
                        title = fetch_url_title(url)
                        link_titles.append({'url': url, 'title': title})
                    
                    # Extract coding tips
                    coding_tips = extract_ai_coding_knowledge_with_openai(messages)
                    
                    # Store results in session
                    session['link_titles'] = link_titles
                    session['coding_tips'] = coding_tips
                    session['message_count'] = len(messages)
                    
                    return redirect(url_for('results'))
                
                except Exception as e:
                    app.logger.error(f"Error processing file: {e}")
                    return render_template('index.html', error=f"Error processing file: {str(e)}")
                finally:
                    # Clean up the temporary file
                    if os.path.exists(filepath):
                        os.remove(filepath)
        
        # Try to render the template
        return render_template('index.html')
    
    except Exception as e:
        app.logger.error(f"Error rendering index template: {e}")
        # Fallback HTML if template rendering fails
        return f"""
        <html>
        <head><title>WhatsApp Chat Analyzer</title></head>
        <body>
            <h1>WhatsApp Chat Analyzer</h1>
            <p>Upload your WhatsApp chat export (.txt file) to extract coding tips and links.</p>
            <p style="color: red;">Note: Template rendering failed. Please check server logs.</p>
            <form method="POST" enctype="multipart/form-data">
                <input type="file" name="file" accept=".txt"><br><br>
                <button type="submit">Analyze Chat</button>
            </form>
        </body>
        </html>
        """

@app.route('/results')
def results():
    # Get result ID from session
    result_id = session.get('result_id')
    
    if not result_id:
        return redirect(url_for('index'))
    
    # Get results folder
    result_folder = os.path.join(app.config['RESULTS_FOLDER'], result_id)
    result_path = os.path.join(result_folder, 'results.json')
    
    if not os.path.exists(result_path):
        return redirect(url_for('index'))
    
    try:
        with open(result_path, 'r') as f:
            data = json.load(f)
        
        link_titles = data.get('link_titles', [])
        categorized_tips = data.get('categorized_tips', {})
        message_count = data.get('message_count', 0)
        
        return render_template(
            'results.html',
            link_titles=link_titles,
            categorized_tips=categorized_tips,
            message_count=message_count
        )
    except Exception as e:
        return redirect(url_for('index'))

@app.route('/debug')
def debug():
    """A simple route for debugging that doesn't rely on templates."""
    info = {
        'env_vars': {k: '***' if k == 'OPENAI_API_KEY' else v for k, v in os.environ.items()},
        'template_dir_exists': os.path.exists(os.path.join(os.path.dirname(__file__), 'templates')),
        'working_dir': os.getcwd(),
        'files_in_dir': os.listdir('.')
    }
    
    html = f"""
    <html>
    <head><title>Debug Info</title></head>
    <body>
        <h1>Debug Information</h1>
        <h2>Working Directory</h2>
        <p>{info['working_dir']}</p>
        
        <h2>Files in Root</h2>
        <ul>
            {''.join([f'<li>{f}</li>' for f in info['files_in_dir']])}
        </ul>
        
        <h2>Templates Directory</h2>
        <p>Exists: {info['template_dir_exists']}</p>
    </body>
    </html>
    """
    
    return html

# Add Flask error handler for 500 errors
@app.errorhandler(500)
def internal_error(error):
    return """
    <html>
    <head><title>Error</title></head>
    <body>
        <h1>Internal Server Error</h1>
        <p>The server encountered an unexpected error. This could be due to:</p>
        <ul>
            <li>Missing OPENAI_API_KEY environment variable</li>
            <li>Issues with template directories</li>
            <li>File permission problems</li>
        </ul>
        <p>Please check the server logs for more details.</p>
    </body>
    </html>
    """, 500

# Replace before_first_request with a middleware
# This works in all Flask versions
def ensure_templates_directory():
    try:
        os.makedirs('templates', exist_ok=True)
        # Verify the templates can be found
        if not os.path.exists(os.path.join(os.path.dirname(__file__), 'templates')):
            app.logger.error("Templates directory not found!")
    except Exception as e:
        app.logger.error(f"Error ensuring templates directory: {e}")

# Create templates directory when app starts
ensure_templates_directory()

if __name__ == '__main__':
    # Get port from environment variable for Railway.com compatibility
    port = int(os.environ.get('PORT', 3000))
    
    app.run(debug=False, host='0.0.0.0', port=port) 