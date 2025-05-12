from flask import Flask, request, render_template, redirect, url_for, session
import os
import re
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
import tempfile
import json

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size

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
                
                # Store results in session as JSON strings (for serialization)
                session['link_titles'] = json.dumps([{'url': item['url'], 'title': item['title']} for item in link_titles])
                session['coding_tips'] = json.dumps([{
                    'sender': tip['sender'], 
                    'date': tip['date'], 
                    'content': tip['content']
                } for tip in coding_tips])
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
    link_titles_json = session.get('link_titles', '[]')
    coding_tips_json = session.get('coding_tips', '[]')
    message_count = session.get('message_count', 0)
    
    # Parse JSON strings back to Python objects
    link_titles = json.loads(link_titles_json)
    coding_tips = json.loads(coding_tips_json)
    
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
    app.run(debug=True, host='0.0.0.0', port=5000) 