import re
import json
import os
import argparse
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import openai
from collections import defaultdict
from transformers import pipeline
from sentence_transformers import SentenceTransformer, util
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Constants
MAX_TOKENS = 4000  # Maximum tokens for GPT models
BATCH_SIZE = 10    # Number of messages to process at once
LOCAL_RELEVANCE_THRESHOLD = 0.4  # Threshold for local model relevance filtering

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

class WhatsAppParser:
    def __init__(self, use_openai: bool = False, openai_api_key: Optional[str] = None):
        """
        Initialize the WhatsApp parser.
        
        Args:
            use_openai: Whether to use OpenAI models or local models
            openai_api_key: OpenAI API key (required if use_openai is True)
        """
        self.use_openai = use_openai
        
        if use_openai:
            if not openai_api_key and not os.getenv('OPENAI_API_KEY'):
                raise ValueError("OpenAI API key required when using OpenAI models")
            openai.api_key = openai_api_key or os.getenv('OPENAI_API_KEY')
        else:
            # Initialize local models only when needed
            self.sentence_model = None
            self.summarizer = None
    
    def _get_sentence_model(self):
        """Lazy-load the sentence transformer model."""
        if self.sentence_model is None:
            print('Loading embedding model for semantic filtering...')
            self.sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
        return self.sentence_model
    
    def _get_summarizer(self):
        """Lazy-load the summarization model."""
        if self.summarizer is None:
            print('Loading summarization model...')
            self.summarizer = pipeline('summarization', model='facebook/bart-large-cnn')
        return self.summarizer
    
    def parse_chat(self, file_path: str) -> List[Dict[str, str]]:
        """Parse WhatsApp chat export into structured messages."""
        messages = []
        pattern = r'\[(\d{1,2}/\d{1,2}/\d{2,4}, \d{1,2}:\d{2}(?::\d{2})? [AP]M)\] ([^:]+): (.+)'
        
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
    
    def group_messages(self, messages: List[Dict], time_threshold_minutes: int = 30) -> List[List[Dict]]:
        """Group messages into conversations based on time proximity."""
        if not messages:
            return []
        
        conversations = []
        current_conversation = [messages[0]]
        
        for i in range(1, len(messages)):
            current_msg = messages[i]
            prev_msg = messages[i-1]
            
            # Parse timestamps - handle both formats
            try:
                if ':' in current_msg['date'].split(' ')[1].split(':')[2]:
                    current_time = datetime.strptime(current_msg['date'], '%d/%m/%Y, %I:%M:%S %p')
                    prev_time = datetime.strptime(prev_msg['date'], '%d/%m/%Y, %I:%M:%S %p')
                else:
                    current_time = datetime.strptime(current_msg['date'], '%d/%m/%Y, %I:%M %p')
                    prev_time = datetime.strptime(prev_msg['date'], '%d/%m/%Y, %I:%M %p')
            except (ValueError, IndexError):
                # Handle potential date format variations
                try:
                    current_time = datetime.strptime(current_msg['date'], '%m/%d/%y, %I:%M %p')
                    prev_time = datetime.strptime(prev_msg['date'], '%m/%d/%y, %I:%M %p')
                except ValueError:
                    # If we still can't parse, just add to current conversation
                    current_conversation.append(current_msg)
                    continue
            
            # If messages are close in time, add to current conversation
            if (current_time - prev_time).total_seconds() / 60 <= time_threshold_minutes:
                current_conversation.append(current_msg)
            else:
                conversations.append(current_conversation)
                current_conversation = [current_msg]
        
        if current_conversation:
            conversations.append(current_conversation)
        
        return conversations
    
    def extract_urls(self, messages: List[Dict]) -> List[str]:
        """Extract URLs from messages."""
        url_pattern = re.compile(r'https?://\S+')
        urls = set()
        for msg in messages:
            found = url_pattern.findall(msg['message'])
            urls.update(found)
        return list(urls)
    
    def fetch_url_content(self, url: str) -> str:
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
    
    def filter_relevant_messages(self, messages: List[Dict], objective: str) -> List[Dict]:
        """
        Filter messages based on relevance to objective.
        Uses different methods based on whether OpenAI is enabled.
        """
        if self.use_openai:
            relevant = []
            # Process in batches to avoid too many API calls
            for i in range(0, len(messages), BATCH_SIZE):
                batch = messages[i:i+BATCH_SIZE]
                batch_text = "\n".join([
                    f"{msg['sender']}: {msg['message']}"
                    for msg in batch
                ])
                
                response = self._analyze_with_llm(
                    batch_text,
                    RELEVANCE_PROMPT,
                    objective=objective
                )
                
                if response.lower().startswith('yes'):
                    relevant.extend(batch)
            return relevant
        else:
            # Use sentence-transformers for local filtering
            model = self._get_sentence_model()
            objective_emb = model.encode(objective, convert_to_tensor=True)
            relevant = []
            
            for msg in messages:
                msg_emb = model.encode(msg['message'], convert_to_tensor=True)
                similarity = util.pytorch_cos_sim(objective_emb, msg_emb).item()
                if similarity >= LOCAL_RELEVANCE_THRESHOLD:
                    relevant.append(msg)
            
            return relevant
    
    def _analyze_with_llm(self, text: str, prompt_template: str, **kwargs) -> str:
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
    
    def summarize_text(self, text: str) -> str:
        """
        Summarize text using either OpenAI or local model.
        """
        if self.use_openai:
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "Summarize the following text concisely:"},
                        {"role": "user", "content": text}
                    ],
                    max_tokens=150,
                    temperature=0.3
                )
                return response.choices[0].message.content
            except Exception as e:
                print(f"Error calling OpenAI API: {e}")
                return ""
        else:
            # Use local summarizer
            summarizer = self._get_summarizer()
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
    
    def process_conversation(self, conversation: List[Dict], objective: str) -> Optional[Dict]:
        """
        Process a conversation to extract knowledge points.
        """
        if not conversation:
            return None
            
        # Combine messages into a single text
        conversation_text = "\n".join([
            f"{msg['sender']} ({msg['date']}): {msg['message']}"
            for msg in conversation
        ])
        
        if self.use_openai:
            # Extract knowledge points using OpenAI
            knowledge_response = self._analyze_with_llm(
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
        else:
            # Extract knowledge points using rule-based approach
            categories = defaultdict(list)
            for msg in conversation:
                text = msg['message']
                # Heuristic: categorize by keywords
                if any(word in text.lower() for word in ['tip', 'trick', 'advice', 'suggestion']):
                    categories['Tips'].append(text)
                elif any(word in text.lower() for word in ['resource', 'link', 'read', 'watch', 'reference']):
                    categories['Resources'].append(text)
                elif any(word in text.lower() for word in ['example', 'case', 'demo', 'sample']):
                    categories['Examples'].append(text)
                elif any(word in text.lower() for word in ['concept', 'theory', 'principle']):
                    categories['Concepts'].append(text)
                elif any(word in text.lower() for word in ['tool', 'app', 'software', 'library']):
                    categories['Tools'].append(text)
                else:
                    categories['Other'].append(text)
            
            # Convert to expected format
            knowledge_points = []
            for category, items in categories.items():
                for item in items:
                    knowledge_points.append({
                        'point': item,
                        'context': f"From conversation on {conversation[0]['date']}",
                        'category': category
                    })
            
            return {
                'conversation': conversation,
                'knowledge_points': knowledge_points
            }
    
    def process_url(self, url: str, objective: str) -> Optional[Dict]:
        """Process a URL to extract relevant knowledge."""
        content = self.fetch_url_content(url)
        if content.startswith('[Error'):
            return None
        
        if self.use_openai:
            summary_response = self._analyze_with_llm(
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
        else:
            # Use local summarizer
            summary_text = self.summarize_text(content)
            return {
                'url': url,
                'summary': {
                    'summary': summary_text,
                    'key_insights': [],
                    'relevance_score': 0.5  # Default score when using local model
                }
            }
    
    def generate_markdown_report(self, processed_conversations: List[Dict], url_summaries: List[Dict], objective: str) -> str:
        """Generate a markdown report from processed conversations and URLs."""
        md = f"# Knowledge Extracted for: {objective}\n\n"
        
        # Add conversation knowledge points
        md += "## Key Knowledge Points\n\n"
        for conv in processed_conversations:
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
    
    def extract_knowledge(self, chat_file: str, objective: str, output_file: str = 'knowledge_report.md') -> str:
        """Main method to extract knowledge from a WhatsApp chat."""
        # Parse chat
        print('Parsing chat...')
        messages = self.parse_chat(chat_file)
        print(f"Parsed {len(messages)} messages.")
        
        # Filter relevant messages
        print('Filtering relevant messages...')
        relevant_messages = self.filter_relevant_messages(messages, objective)
        print(f"Found {len(relevant_messages)} relevant messages.")
        
        # Group into conversations
        print('Grouping messages into conversations...')
        conversations = self.group_messages(relevant_messages)
        print(f"Grouped into {len(conversations)} conversations.")
        
        # Extract URLs
        print('Extracting URLs...')
        urls = self.extract_urls(relevant_messages)
        print(f"Found {len(urls)} URLs.")
        
        # Process conversations
        print('Processing conversations...')
        processed_conversations = []
        for conv in conversations:
            result = self.process_conversation(conv, objective)
            if result:
                processed_conversations.append(result)
        
        # Process URLs
        print('Processing URLs...')
        url_summaries = []
        for url in urls:
            result = self.process_url(url, objective)
            if result:
                url_summaries.append(result)
        
        # Generate report
        print('Generating markdown report...')
        report = self.generate_markdown_report(processed_conversations, url_summaries, objective)
        
        # Save to file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"Report saved to {output_file}")
        
        return report

def main():
    parser = argparse.ArgumentParser(description='WhatsApp Chat Knowledge Extractor')
    parser.add_argument('chat_file', help='Path to WhatsApp chat export (.txt)')
    parser.add_argument('--objective', required=True, help='Learning objective')
    parser.add_argument('--output', default='knowledge_report.md', help='Output markdown file')
    parser.add_argument('--use_openai', action='store_true', help='Use OpenAI models for analysis')
    parser.add_argument('--api_key', help='OpenAI API key (or set OPENAI_API_KEY env var)')
    args = parser.parse_args()
    
    if not os.path.exists(args.chat_file):
        print(f"Error: File {args.chat_file} not found.")
        return
    
    parser = WhatsAppParser(
        use_openai=args.use_openai,
        openai_api_key=args.api_key
    )
    
    parser.extract_knowledge(
        args.chat_file,
        args.objective,
        args.output
    )

if __name__ == '__main__':
    main()
