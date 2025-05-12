import re
import json
import argparse
import requests
from bs4 import BeautifulSoup
from transformers import pipeline
from typing import List, Dict, Any
from collections import defaultdict
import os
from sentence_transformers import SentenceTransformer, util
from dotenv import load_dotenv

load_dotenv()

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

# 3. Filter messages by learning objective

def filter_relevant_messages(messages: List[Dict[str, str]], learning_objective: str, threshold: float = 0.4) -> List[Dict[str, str]]:
    """
    Use sentence-transformers to semantically filter messages relevant to the learning objective.
    """
    print('Loading embedding model for semantic filtering...')
    model = SentenceTransformer('all-MiniLM-L6-v2')
    lo_emb = model.encode(learning_objective, convert_to_tensor=True)
    relevant = []
    for msg in messages:
        msg_emb = model.encode(msg['message'], convert_to_tensor=True)
        sim = util.pytorch_cos_sim(lo_emb, msg_emb).item()
        if sim >= threshold:
            relevant.append(msg)
    return relevant

# 4. Fetch and summarize web content

def fetch_url_content(url: str) -> str:
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        # Get visible text
        texts = soup.stripped_strings
        content = ' '.join(texts)
        return content[:5000]  # Limit to 5000 chars for summarization
    except Exception as e:
        return f"[Error fetching {url}: {e}]"

# 5. Summarize content using transformers

def get_summarizer():
    return pipeline('summarization', model='facebook/bart-large-cnn')

def summarize_text(text: str, summarizer) -> str:
    try:
        # BART has a max token limit, so chunk if needed
        max_chunk = 1024
        if len(text) <= max_chunk:
            summary = summarizer(text, max_length=130, min_length=30, do_sample=False)[0]['summary_text']
            return summary
        else:
            # Chunk and summarize each, then join
            chunks = [text[i:i+max_chunk] for i in range(0, len(text), max_chunk)]
            summaries = [summarizer(chunk, max_length=130, min_length=30, do_sample=False)[0]['summary_text'] for chunk in chunks]
            return '\n'.join(summaries)
    except Exception as e:
        return f"[Error summarizing: {e}]"

# 6. Categorize knowledge points

def categorize_knowledge(messages: List[Dict[str, str]]) -> Dict[str, List[str]]:
    categories = defaultdict(list)
    for msg in messages:
        text = msg['message']
        # Heuristic: categorize by keywords
        if any(word in text.lower() for word in ['tip', 'trick', 'advice', 'suggestion']):
            categories['Tips'].append(text)
        elif any(word in text.lower() for word in ['resource', 'link', 'read', 'watch', 'reference']):
            categories['Resources'].append(text)
        elif any(word in text.lower() for word in ['example', 'case', 'demo', 'sample']):
            categories['Examples'].append(text)
        else:
            categories['Other'].append(text)
    return categories

# 7. Generate markdown report

def generate_markdown_report(categories: Dict[str, List[str]], url_summaries: Dict[str, str], learning_objective: str) -> str:
    md = f"# Knowledge Extracted for: {learning_objective}\n\n"
    md += "## Key Knowledge Points\n"
    for cat, items in categories.items():
        md += f"\n### {cat}\n"
        for item in items:
            md += f"- {item}\n"
    md += "\n## Resource Summaries\n"
    for url, summary in url_summaries.items():
        md += f"\n### [{url}]({url})\n"
        md += f"{summary}\n"
    return md

def summarize_all_messages(messages: List[Dict[str, str]], summarizer) -> str:
    """
    Summarize the entire chat messages as a single block of text.
    """
    all_text = '\n'.join([msg['message'] for msg in messages])
    return summarize_text(all_text, summarizer)

# 8. Main orchestration

def main():
    parser = argparse.ArgumentParser(description='WhatsApp Knowledge Extractor')
    parser.add_argument('chat_file', help='Path to WhatsApp chat export (.txt)')
    parser.add_argument('--output', default='knowledge_report.md', help='Output markdown file')
    parser.add_argument('--use_openai', action='store_true', help='Use OpenAI for semantic filtering')
    parser.add_argument('--api_key', help='OpenAI API key')
    args = parser.parse_args()

    if not os.path.exists(args.chat_file):
        print(f"Error: File {args.chat_file} not found.")
        return

    print('Parsing chat...')
    messages = parse_whatsapp_chat(args.chat_file)
    print(f"Parsed {len(messages)} messages.")

    print('Extracting URLs...')
    urls = extract_urls(messages)
    print(f"Found {len(urls)} URLs.")

    print('Fetching and summarizing URLs...')
    url_summaries = {}
    summarizer = get_summarizer()
    for url in urls:
        print(f"Fetching: {url}")
        content = fetch_url_content(url)
        print(f"Summarizing: {url}")
        summary = summarize_text(content, summarizer)
        url_summaries[url] = summary

    print('Summarizing all chat messages...')
    chat_summary = summarize_all_messages(messages, summarizer)

    print('Categorizing knowledge...')
    categories = categorize_knowledge(messages)

    print('Generating markdown report...')
    md_report = f"# WhatsApp Chat Summary\n\n"
    md_report += f"## Overall Chat Summary\n\n{chat_summary}\n\n"
    md_report += generate_markdown_report(categories, url_summaries, "(Full Chat)")
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(md_report)
    print(f"Report saved to {args.output}")

if __name__ == '__main__':
    main() 