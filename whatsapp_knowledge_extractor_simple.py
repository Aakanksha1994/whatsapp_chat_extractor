import re
import json
import os
from typing import List, Dict, Any
from collections import defaultdict
import requests
from bs4 import BeautifulSoup

# 1. Parse WhatsApp chat
def parse_whatsapp_chat(file_path: str) -> List[Dict[str, str]]:
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

# 2. Extract URLs from messages
def extract_urls(messages: List[Dict[str, str]]) -> List[str]:
    url_pattern = re.compile(r'https?://\S+')
    urls = set()
    for msg in messages:
        found = url_pattern.findall(msg['message'])
        urls.update(found)
    return list(urls)

# 3. Extract coding tips - simplified version
def extract_coding_tips(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Extract coding tips and guidance from messages, ignoring social and logistical content."""
    # Technical keywords to keep
    technical_keywords = [
        'code', 'coding', 'programming', 'developer', 'software', 'web', 'app', 
        'javascript', 'python', 'java', 'html', 'css', 'react', 'angular', 'vue',
        'node', 'api', 'git', 'github', 'stack', 'framework', 'library', 'function',
        'algorithm', 'database', 'sql', 'backend', 'frontend', 'fullstack', 'debug',
        'compiler', 'interpreter', 'syntax', 'variable', 'loop', 'condition', 'class',
        'object', 'method', 'AI', 'cursor', 'IDE', 'editor', 'build', 'deploy', 'server',
        'client', 'terminal', 'command', 'prompt', 'install', 'package', 'dependency',
        'npm', 'pip', 'yarn', 'docker', 'kubernetes', 'cloud', 'AWS', 'Azure', 'GCP',
        'gpt', 'claude', 'openai', 'llm', 'ml', 'model', 'transformer', 'bert', 'nlp',
        'whisper', 'bard', 'gemini', 'anthropic', 'grok', 'chatgpt', 'llama', 'mistral',
        'huggingface', 'pytorch', 'tensorflow', 'api', 'token', 'completion', 'embedding'
    ]
    
    # Words/phrases to ignore (social, logistical, etc.)
    ignore_phrases = [
        'hello', 'hi ', 'hey', 'how are you', 'good morning', 'good afternoon', 'good evening',
        'thanks', 'thank you', 'appreciate it', 'cool', 'awesome', 'nice', 'great',
        'see you', 'talk later', 'bye', 'goodbye', 'later', 'let me know',
        'meeting', 'schedule', 'available', 'tomorrow', 'today', 'yesterday',
        'call me', 'phone', 'zoom', 'google meet', 'teams', 'lunch', 'dinner',
        'okay', 'ok', 'sure', 'got it', 'understood', 'makes sense', 'sounds good',
        'lol', 'haha', '😂', '👍', '🙂'
    ]
    
    tips = []
    
    for msg in messages:
        text = msg['message'].lower()
        
        # Skip if too short or just a URL
        if len(text.split()) < 3 or (text.startswith('http') and len(text.split()) < 5):
            continue
            
        # Skip if it contains ignore phrases and is short
        if any(phrase in text for phrase in ignore_phrases) and len(text.split()) < 15:
            continue
        
        # Only keep if it contains technical keywords
        if any(keyword.lower() in text for keyword in technical_keywords):
            # Longer messages or those containing specific tip indicators
            if len(text.split()) > 15 or any(phrase in text for phrase in ['tip', 'advice', 'how to', 'should', 'try', 'recommend', 'suggestion', 'best practice']):
                tips.append({
                    'content': msg['message']
                })
    
    return tips

# 4. Categorize the coding tips
def categorize_tips(tips: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Categorize coding tips into meaningful groups."""
    # Define categories and their keywords
    categories = {
        "AI Coding Tools": ["cursor", "vscode", "visual studio", "code editor", "IDE", "grok", "claude", "gpt", "llm tool", "copilot", "codewhisperer", "sourcegraph", "github"],
        "Prompt Engineering": ["prompt", "instruction", "token", "context window", "whisper", "prompt engineering", "prompt design", "system prompt", "conversation", "chat history", "token", "embedding"],
        "AI Development Workflow": ["workflow", "steps", "process", "procedure", "methodology", "development", "deploy", "product", "architecture", "plan", "standard operating procedure", "SOP"],
        "Coding Best Practices": ["best practice", "pattern", "tdd", "test driven", "refactor", "clean code", "documentation", "comment", "naming", "structure", "bug", "debug"],
        "AI Limitations & Workarounds": ["limitation", "problem", "issue", "hallucination", "error", "mistake", "workaround", "solution", "fix", "solve", "rate limit", "token limit"],
        "Machine Learning & Models": ["model", "train", "fine-tune", "dataset", "parameter", "weight", "embedding", "vector", "huggingface", "pytorch", "tensorflow", "bert", "transformer"]
    }
    
    # Default category for tips that don't match any specific category
    default_category = "General AI Coding Tips"
    
    # Initialize result dictionary
    categorized = defaultdict(list)
    
    # Categorize each tip
    for tip in tips:
        content = tip['content'].lower()
        matched = False
        
        # Try to find a matching category
        for category, keywords in categories.items():
            if any(keyword.lower() in content for keyword in keywords):
                categorized[category].append(tip)
                matched = True
                break
        
        # Use default category if no match found
        if not matched:
            categorized[default_category].append(tip)
    
    return dict(categorized)

# 4. Fetch URL title
def fetch_url_title(url: str) -> str:
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

# Export to Markdown
def export_to_markdown(categorized_tips: Dict[str, List[Dict[str, Any]]], urls: List[str], url_titles: List[Dict[str, str]]) -> str:
    """Create a Markdown export of the categorized tips and resources."""
    markdown = "# AI Coding Knowledge Extraction\n\n"
    
    # Add tips by category
    for category, tips in categorized_tips.items():
        markdown += f"## {category}\n"
        markdown += f"{len(tips)} tips\n\n"
        
        for tip in tips:
            # Clean up the tip text
            content = tip['content'].strip()
            markdown += f"- {content}\n"
        
        markdown += "\n"
    
    # Add resource links
    if urls:
        markdown += "## Useful Resources\n\n"
        url_dict = {item['url']: item['title'] for item in url_titles}
        
        for url in urls:
            title = url_dict.get(url, url)
            if title == url:
                markdown += f"- [{url}]({url})\n"
            else:
                markdown += f"- [{title}]({url})\n"
                
    return markdown 