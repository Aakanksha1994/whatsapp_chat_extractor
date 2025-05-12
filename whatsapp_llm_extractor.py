import re
import json
import os
import argparse
from typing import List, Dict, Any
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import openai
from collections import defaultdict

# Constants for OpenAI
MAX_TOKENS = 4000  # Maximum tokens for GPT-3.5-turbo
BATCH_SIZE = 10    # Number of messages to process at once

# LLM Prompts
RELEVANCE_PROMPT = """Analyze if the following WhatsApp messages are relevant to the learning objective: {objective}
Consider semantic meaning, not just keywords. Return 'yes' or 'no' followed by a brief explanation."""

EXTRACTION_PROMPT = """Extract key knowledge points from these messages related to: {objective}
Format as a JSON array of objects with fields:
- point: The key learning point
- context: Brief context or explanation
- category: One of [Tips, Resources, Examples, Concepts, Tools]"""

SUMMARIZATION_PROMPT = """Summarize this article content in relation to: {objective}
Focus on extracting practical knowledge and insights. Format as a JSON object with:
- summary: Main points
- key_insights: Array of specific insights
- relevance_score: 0-1 score of relevance to objective"""

def parse_whatsapp_chat(file_path: str) -> List[Dict]:
    """Parse WhatsApp chat export into structured messages."""
    messages = []
    pattern = r'\[(\d{1,2}/\d{1,2}/\d{2,4}, \d{1,2}:\d{2}:\d{2} [AP]M)\] ([^:]+): (.+)'
    
    with open(file_path, 'r', encoding='utf-8') as file:
        current_message = None
        
        for line in file:
            line = line.strip()
            if not line:
                continue
            
            match = re.match(pattern, line)
            if match:
                if current_message:
                    messages.append(current_message)
                
                date, sender, message = match.groups()
                current_message = {
                    'date': date,
                    'sender': sender.strip(),
                    'message': message.strip()
                }
            elif current_message:
                current_message['message'] += '\n' + line
    
    if current_message:
        messages.append(current_message)
    
    return messages

def group_messages(messages: List[Dict], time_threshold_minutes: int = 30) -> List[List[Dict]]:
    """Group messages into conversations based on time proximity."""
    if not messages:
        return []
    
    conversations = []
    current_conversation = [messages[0]]
    
    for i in range(1, len(messages)):
        current_msg = messages[i]
        prev_msg = messages[i-1]
        
        # Parse timestamps
        current_time = datetime.strptime(current_msg['date'], '%d/%m/%Y, %I:%M:%S %p')
        prev_time = datetime.strptime(prev_msg['date'], '%d/%m/%Y, %I:%M:%S %p')
        
        # If messages are close in time, add to current conversation
        if (current_time - prev_time).total_seconds() / 60 <= time_threshold_minutes:
            current_conversation.append(current_msg)
        else:
            conversations.append(current_conversation)
            current_conversation = [current_msg]
    
    if current_conversation:
        conversations.append(current_conversation)
    
    return conversations

def analyze_with_llm(text: str, prompt_template: str, **kwargs) -> str:
    """Call OpenAI API with the given prompt and text."""
    try:
        prompt = prompt_template.format(**kwargs)
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ],
            max_tokens=MAX_TOKENS,
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return ""

def extract_urls(messages: List[Dict]) -> List[str]:
    """Extract URLs from messages."""
    url_pattern = re.compile(r'https?://\S+')
    urls = set()
    for msg in messages:
        found = url_pattern.findall(msg['message'])
        urls.update(found)
    return list(urls)

def fetch_url_content(url: str) -> str:
    """Fetch and parse webpage content."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Get text and clean it
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        return text[:5000]  # Limit content length
    except Exception as e:
        return f"[Error fetching {url}: {e}]"

def process_conversation(conversation: List[Dict], objective: str) -> Dict:
    """Process a conversation using LLM to extract knowledge."""
    # Combine messages into a single text
    conversation_text = "\n".join([
        f"{msg['sender']} ({msg['date']}): {msg['message']}"
        for msg in conversation
    ])
    
    # Check relevance
    relevance_response = analyze_with_llm(
        conversation_text,
        RELEVANCE_PROMPT,
        objective=objective
    )
    
    if not relevance_response.lower().startswith('yes'):
        return None
    
    # Extract knowledge points
    knowledge_response = analyze_with_llm(
        conversation_text,
        EXTRACTION_PROMPT,
        objective=objective
    )
    
    try:
        knowledge_points = json.loads(knowledge_response)
        return {
            'conversation': conversation,
            'knowledge_points': knowledge_points
        }
    except json.JSONDecodeError:
        print(f"Error parsing LLM response: {knowledge_response}")
        return None

def process_url(url: str, objective: str) -> Dict:
    """Process a URL using LLM to extract relevant knowledge."""
    content = fetch_url_content(url)
    if content.startswith('[Error'):
        return None
    
    summary_response = analyze_with_llm(
        content,
        SUMMARIZATION_PROMPT,
        objective=objective
    )
    
    try:
        summary = json.loads(summary_response)
        return {
            'url': url,
            'summary': summary
        }
    except json.JSONDecodeError:
        print(f"Error parsing LLM response for URL {url}")
        return None

def generate_markdown_report(conversations: List[Dict], url_summaries: List[Dict], objective: str) -> str:
    """Generate a markdown report from processed conversations and URLs."""
    md = f"# Knowledge Extracted for: {objective}\n\n"
    
    # Add conversation knowledge points
    md += "## Key Knowledge Points\n\n"
    for conv in conversations:
        if not conv:
            continue
        
        md += "### Conversation\n"
        md += f"*Date: {conv['conversation'][0]['date']}*\n\n"
        
        for point in conv['knowledge_points']:
            md += f"#### {point['category']}\n"
            md += f"- {point['point']}\n"
            if point.get('context'):
                md += f"  *Context: {point['context']}*\n"
        md += "\n"
    
    # Add URL summaries
    if url_summaries:
        md += "## Resource Summaries\n\n"
        for summary in url_summaries:
            if not summary:
                continue
            
            md += f"### [{summary['url']}]({summary['url']})\n"
            md += f"{summary['summary']['summary']}\n\n"
            
            if summary['summary'].get('key_insights'):
                md += "**Key Insights:**\n"
                for insight in summary['summary']['key_insights']:
                    md += f"- {insight}\n"
            md += "\n"
    
    return md

def main():
    parser = argparse.ArgumentParser(description='WhatsApp Chat Knowledge Extractor with LLM')
    parser.add_argument('chat_file', help='Path to WhatsApp chat export (.txt)')
    parser.add_argument('--objective', required=True, help='Learning objective')
    parser.add_argument('--api_key', help='OpenAI API key (or set OPENAI_API_KEY env var)')
    parser.add_argument('--output', default='knowledge_report.md', help='Output markdown file')
    args = parser.parse_args()
    
    # Set up OpenAI API key
    api_key = args.api_key or os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("Error: OpenAI API key required. Set OPENAI_API_KEY env var or use --api_key")
        return
    
    openai.api_key = api_key
    
    # Parse chat
    print('Parsing chat...')
    messages = parse_whatsapp_chat(args.chat_file)
    print(f"Parsed {len(messages)} messages.")
    
    # Group into conversations
    print('Grouping messages into conversations...')
    conversations = group_messages(messages)
    print(f"Found {len(conversations)} conversations.")
    
    # Process conversations
    print('Processing conversations with LLM...')
    processed_conversations = []
    for conv in conversations:
        result = process_conversation(conv, args.objective)
        if result:
            processed_conversations.append(result)
    
    # Process URLs
    print('Processing URLs...')
    urls = extract_urls(messages)
    print(f"Found {len(urls)} URLs.")
    
    url_summaries = []
    for url in urls:
        print(f"Processing: {url}")
        summary = process_url(url, args.objective)
        if summary:
            url_summaries.append(summary)
    
    # Generate report
    print('Generating markdown report...')
    report = generate_markdown_report(processed_conversations, url_summaries, args.objective)
    
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"Report saved to {args.output}")

if __name__ == '__main__':
    main() 