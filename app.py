from flask import Flask, request, render_template, redirect, url_for, session
import os
import re
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
import tempfile
from collections import defaultdict
import html

# Import our chat parsing functions
from whatsapp_knowledge_extractor import parse_whatsapp_chat, extract_urls

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size

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

def extract_coding_tips(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Extract coding tips and guidance from messages."""
    coding_keywords = [
        'code', 'coding', 'programming', 'developer', 'software', 'web', 'app', 
        'javascript', 'python', 'java', 'html', 'css', 'react', 'angular', 'vue',
        'node', 'api', 'git', 'github', 'stack', 'framework', 'library', 'function',
        'algorithm', 'database', 'sql', 'backend', 'frontend', 'fullstack', 'debug',
        'compiler', 'interpreter', 'syntax', 'variable', 'loop', 'condition', 'class',
        'object', 'method', 'AI', 'cursor', 'IDE', 'editor', 'build', 'deploy', 'server',
        'client', 'terminal', 'command', 'prompt', 'install', 'package', 'dependency',
        'npm', 'pip', 'yarn', 'docker', 'kubernetes', 'cloud', 'AWS', 'Azure', 'GCP'
    ]
    
    tips = []
    
    for msg in messages:
        text = msg['message'].lower()
        
        # Check if message contains coding-related keywords
        if any(keyword.lower() in text for keyword in coding_keywords):
            # Look for sentences that might be tips or advice
            if any(phrase in text for phrase in ['tip', 'advice', 'how to', 'should', 'try', 'recommend', 'suggestion', 'best practice']):
                tips.append({
                    'sender': msg['sender'],
                    'date': msg['date'],
                    'content': msg['message']
                })
            # If message is long enough, it might be a detailed explanation
            elif len(text.split()) > 20:
                tips.append({
                    'sender': msg['sender'],
                    'date': msg['date'],
                    'content': msg['message']
                })
    
    return tips

@app.route('/', methods=['GET', 'POST'])
def index():
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
                coding_tips = extract_coding_tips(messages)
                
                # Store results in session
                session['link_titles'] = link_titles
                session['coding_tips'] = coding_tips
                session['message_count'] = len(messages)
                
                return redirect(url_for('results'))
            
            except Exception as e:
                return render_template('index.html', error=f"Error processing file: {str(e)}")
            finally:
                # Clean up the temporary file
                if os.path.exists(filepath):
                    os.remove(filepath)
    
    return render_template('index.html')

@app.route('/results')
def results():
    # Get results from session
    link_titles = session.get('link_titles', [])
    coding_tips = session.get('coding_tips', [])
    message_count = session.get('message_count', 0)
    
    if not coding_tips and not link_titles:
        return redirect(url_for('index'))
    
    return render_template(
        'results.html',
        link_titles=link_titles,
        coding_tips=coding_tips,
        message_count=message_count
    )

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    app.run(debug=True) 